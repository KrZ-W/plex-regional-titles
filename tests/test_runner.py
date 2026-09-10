import json

import pytest

from plex_regional_titles.curation import Curation
from plex_regional_titles.models import Candidate, Item, Kind, PlexAuthError
from plex_regional_titles.runner import EXIT_OK, EXIT_RUN_ERROR, run_once
from plex_regional_titles.sources.chain import SourceChain
from plex_regional_titles.summary import COUNTER_FIELDS
from tests.conftest import StaticSource, make_item


class FakeSection:
    def __init__(self, type_):
        self.type = type_


class FakePlex:
    """Stands in for PlexClient; items keep state across runs so idempotency can be checked."""

    def __init__(self, items: dict[str, list[Item]], kinds: dict[str, str] | None = None):
        self._items = items
        self._kinds = kinds or {}
        self.writes: list[tuple[str, str]] = []

    def section(self, name):
        if name not in self._items:
            raise LookupError(f"library {name!r} not found")
        return FakeSection(self._kinds.get(name, "movie"))

    def items(self, name):
        yield from self._items[name]

    def write_title(self, item, title):
        self.writes.append((item.rating_key, title))
        item.title = title
        item.title_locked = True


class MapSource(StaticSource):
    def __init__(self, name, authoritative, mapping):
        super().__init__(name, authoritative, None)
        self.mapping = mapping

    def resolve(self, item):
        t = self.mapping.get(item.imdb_id)
        return Candidate(t, self.name, self.authoritative) if t else None


def _items():
    return [
        Item("1", "Films", Kind.MOVIE, "À armes égales", "G.I. Jane", 1997, [], "tt1"),
        Item("2", "Films", Kind.MOVIE, "Hugo Cabret", "The Invention of Hugo Cabret", 2011, [], "tt2"),
        Item("3", "Films", Kind.MOVIE, "Le Chemin", "El Camino", 2019, [], "tt3"),
        Item("4", "Films", Kind.MOVIE, "Déjà bon", "Already Good", 2000, [], "tt4"),
        Item("5", "Films", Kind.MOVIE, "Rien", "Nothing", 2000, [], "tt5"),
        Item("6", "Films", Kind.MOVIE, "Sans ids", None, 2000, [], None),
        Item("7", "Films", Kind.MOVIE, "Exclu", "Excluded", 2000, [], "tt7"),
        Item("8", "Films", Kind.MOVIE, "Rampage", "Rampage", 2009, [], "tt8"),
    ]


def _chain():
    regie = MapSource("regie", True, {"tt1": "G.I. Jane", "tt4": "Deja bon"})
    imdb = MapSource("imdb", False, {"tt2": "Hugo", "tt3": "El Camino", "tt7": "X"})
    return SourceChain([regie, imdb])


def test_full_run_and_idempotency(settings):
    settings.same_title_mode = "review"
    items = _items()
    plex = FakePlex({"Films": items})
    curation = Curation(exclusions={"tt7"}, overrides={"tt8": "Le Forcené"})

    summary, code = run_once(settings, plex=plex, chain=_chain(), curation=curation)
    assert code == EXIT_OK
    lib = summary.libraries[0]
    assert lib.library == "Films" and lib.kind == "movie" and lib.scanned == 8
    assert lib.applied == 3 and lib.applied_by_source == {"regie": 1, "imdb": 1, "override": 1}
    assert lib.already_correct == 1 and lib.excluded == 1 and lib.overridden == 1
    assert lib.same_title_reviewed == 1 and lib.same_title_skipped == 0
    assert lib.no_candidate == 1 and lib.no_ids == 1 and lib.errors == 0
    assert lib.resolved_by_source == {"regie": 2, "imdb": 2}
    assert sorted(plex.writes) == [("1", "G.I. Jane"), ("2", "Hugo"), ("8", "Le Forcené")]

    # state file + review.csv
    data = json.loads(settings.last_run_file.read_text(encoding="utf-8"))
    assert data["status"] == "ok" and data["dry_run"] is False and data["locale"] == "fr-CA"
    for f in COUNTER_FIELDS:
        assert f in data["libraries"][0] and f in data["totals"]
    assert data["totals"]["applied"] == 3 and data["totals"]["applied_by_source"]["override"] == 1
    review = settings.review_file.read_text(encoding="utf-8").splitlines()
    assert len(review) == 2 and "El Camino" in review[1] and "tt3" in review[1]

    # second run: nothing to write
    plex.writes.clear()
    summary2, code2 = run_once(settings, plex=plex, chain=_chain(), curation=curation)
    assert code2 == EXIT_OK and plex.writes == []
    lib2 = summary2.libraries[0]
    assert lib2.applied == 0 and lib2.already_correct == 3 and lib2.overridden == 1
    assert summary2.totals["applied"] == 0


def test_dry_run_writes_nothing_but_counts(settings):
    settings.dry_run = True
    plex = FakePlex({"Films": _items()})
    summary, code = run_once(settings, plex=plex, chain=_chain(), curation=Curation())
    assert code == EXIT_OK and plex.writes == []
    assert summary.libraries[0].applied == 3 and summary.dry_run is True
    assert json.loads(settings.last_run_file.read_text())["dry_run"] is True
    rows = settings.would_apply_file.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith(
        "library,rating_key,kind,imdb_id,tmdb_id,year,current_title,candidate,source,ref,cascade_step"
    )
    assert len(rows) == 4
    assert any(",tt1,,1997,À armes égales,G.I. Jane,regie,,6," in r for r in rows)


def test_would_apply_written_in_review_mode_with_override_ref(settings):
    settings.same_title_mode = "review"
    plex = FakePlex({"Films": _items()})
    run_once(settings, plex=plex, chain=_chain(), curation=Curation(overrides={"tt8": "Le Forcené"}))
    rows = settings.would_apply_file.read_text(encoding="utf-8").splitlines()
    assert any(",8,movie,tt8,,2009,Rampage,Le Forcené,override,,2," in r for r in rows)
    assert "house_style_equivalent" in json.loads(settings.last_run_file.read_text())["totals"]


def test_would_apply_not_written_in_plain_live_mode(settings):
    plex = FakePlex({"Films": _items()})
    run_once(settings, plex=plex, chain=_chain(), curation=Curation())
    assert not settings.would_apply_file.exists()


def test_missing_library_is_error_but_run_continues(settings):
    settings.libraries = ["Nope", "Films"]
    plex = FakePlex({"Films": _items()})
    summary, code = run_once(settings, plex=plex, chain=_chain(), curation=Curation())
    assert code == EXIT_RUN_ERROR
    assert summary.libraries[0].errors == 1 and summary.libraries[1].scanned == 8
    assert summary.status == "error"


def test_write_failure_counted_as_error(settings):
    class BrokenPlex(FakePlex):
        def write_title(self, item, title):
            raise RuntimeError("boom")

    plex = BrokenPlex({"Films": _items()})
    summary, code = run_once(settings, plex=plex, chain=_chain(), curation=Curation())
    assert code == EXIT_RUN_ERROR and summary.libraries[0].errors == 3


def test_show_library_uses_series_items(settings):
    settings.libraries = ["Séries"]
    show = Item("9", "Séries", Kind.SHOW, "Show FR", "The Show", 2020, [], "tt9", "77")
    plex = FakePlex({"Séries": [show]}, kinds={"Séries": "show"})
    tmdb = MapSource("tmdb", True, {"tt9": "L'Émission"})
    regie = StaticSource("regie", True, "SHOULD NOT BE USED", supports=frozenset({Kind.MOVIE}))
    summary, code = run_once(settings, plex=plex, chain=SourceChain([regie, tmdb]), curation=Curation())
    assert code == EXIT_OK and plex.writes == [("9", "L'Émission")]
    assert summary.libraries[0].kind == "show" and regie.calls == 0


def test_plex_auth_error_propagates(settings, monkeypatch):
    import plex_regional_titles.runner as runner

    def boom(settings):
        raise PlexAuthError("bad token")

    monkeypatch.setattr(runner, "PlexClient", boom)
    with pytest.raises(PlexAuthError):
        run_once(settings, chain=_chain(), curation=Curation())


def test_make_item_helper():
    assert make_item("x").kind == Kind.MOVIE

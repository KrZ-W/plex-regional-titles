"""v1.2.0: registry corroboration, (V.F.) family, diacritic guard, review queue."""

import pytest

from plex_regional_titles.cascade import decide
from plex_regional_titles.curation import Curation
from plex_regional_titles.models import Candidate, Item, Kind, Outcome, RegistryRecord, RegistryRejection
from plex_regional_titles.normalize import diacritics, has_dubbed_version_suffix, is_stripped_variant
from plex_regional_titles.runner import EXIT_OK, EXIT_RUN_ERROR, run_once
from plex_regional_titles.sources.base import RegionalRegistry
from plex_regional_titles.sources.chain import SourceChain
from plex_regional_titles.summary import LibrarySummary
from tests.conftest import StaticSource, make_item
from tests.test_runner import FakePlex


class FakeRegistry(RegionalRegistry):
    """Returns a house-style registry string (or a rejection) for every item."""

    name = "fakereg"

    def __init__(self, result):
        self.result = result

    def resolve(self, item):
        return self.result


class FakeImdb(StaticSource):
    def __init__(self, pick, rows):
        super().__init__("imdb", False, pick)
        self.rows = rows

    def renderings(self, item):
        return list(self.rows)

    def regional_akas(self, item):
        return list(self.rows)


class FakeTmdb(StaticSource):
    def __init__(self, pick, others=()):
        super().__init__("tmdb", True, pick)
        self.others = list(others)

    def renderings(self, item):
        return ([self.title] if self.title else []) + self.others


REC = RegistryRecord("no_film=1", "SPLIT", "DIVISE", 2017)


def reg(title, record=REC):
    return FakeRegistry(
        Candidate(title, "fakereg", True, ref=record.ref, needs_corroboration=True, record=record)
    )


# --- corroboration precedence -----------------------------------------------------------------
def test_precedence_plex_title_first():
    chain = SourceChain([reg("DIVISE"), FakeTmdb("Divisé"), FakeImdb("Divisé", ["Divisé"])])
    c = chain.resolve(make_item("Divisé", "Split"))
    assert c.title == "Divisé" and c.source == "fakereg" and chain.take_rejections() == []


def test_precedence_plex_original_before_tmdb():
    chain = SourceChain([reg("G.I. JANE"), FakeTmdb("G.I. Jane (tmdb)")])
    c = chain.resolve(make_item("À armes égales", "G.I. Jane"))
    assert c.title == "G.I. Jane"


def test_precedence_tmdb_before_imdb():
    chain = SourceChain([reg("DIVISE"), FakeTmdb("Divisé"), FakeImdb("Divisé!", ["Divisé!"])])
    c = chain.resolve(make_item("Split", "Split"))
    assert c.title == "Divisé"


def test_imdb_any_row_corroborates_not_only_the_pick():
    chain = SourceChain([reg("DIVISE"), FakeImdb("Split (fr-CA pick)", ["Split (fr-CA pick)", "Divisé"])])
    c = chain.resolve(make_item("Split", "Split"))
    assert c.title == "Divisé" and c.source == "fakereg"


def test_written_value_is_never_the_registry_string():
    chain = SourceChain([reg("DIVISE"), FakeImdb(None, ["Divisé"])])
    c = chain.resolve(make_item("Split", "Split"))
    assert c.title == "Divisé"


def test_rejection_when_nothing_corroborates():
    imdb = FakeImdb("Fallback fr-CA", ["Fallback fr-CA", "Other"])
    chain = SourceChain([reg("MES MEILLEURES AMIES"), imdb])
    c = chain.resolve(make_item("Demoiselles d'honneur", "Bridesmaids"))
    assert c.source == "imdb" and c.title == "Fallback fr-CA"
    (rj,) = chain.take_rejections()
    assert rj.reason == "registry-uncorroborated" and rj.candidate_title == "MES MEILLEURES AMIES"
    assert rj.akas == ["Fallback fr-CA", "Other"] and rj.record is REC


def test_corroborator_must_have_at_least_as_many_diacritics():
    rec = RegistryRecord("no_film=2", "X", "DIVISÉ", 2017)
    chain = SourceChain([reg("DIVISÉ", rec), FakeImdb(None, ["Divise"])])
    assert chain.resolve(make_item("Split", "Split")) is None
    assert chain.take_rejections()[0].reason == "registry-uncorroborated"


def test_corroborated_row_still_applies_through_cascade():
    chain = SourceChain([reg("DIVISE"), FakeImdb(None, ["Divisé"])])
    d = decide(make_item("Split", "Split"), Curation(), chain.resolve)
    assert d.outcome == Outcome.APPLIED and d.write and d.candidate.title == "Divisé"


def test_corroborated_by_current_title_is_already_correct():
    chain = SourceChain([reg("DIVISE")])
    d = decide(make_item("Divisé", "Split"), Curation(), chain.resolve)
    assert d.outcome == Outcome.ALREADY_CORRECT


# --- (V.F.) family ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, dubbed",
    [
        ("ABYSS (V.F.)", True),
        ("HUGO (V.F)", True),
        ("HUGO (V. F.)", True),
        ("PONYO (V.A.)", True),
        ("TITRE (V.O.A.)", True),
        ("TITRE (V.O.A.S.-T.F.)", True),
        ("titre (v.f.) ", True),
        ("RESULTAT (V.O.F.)", False),
        ("ENRAGE", False),
        ("SEVEN (TZAMETI)", False),
        ("", False),
    ],
)
def test_has_dubbed_version_suffix(raw, dubbed):
    assert has_dubbed_version_suffix(raw) is dubbed


# --- diacritic guard ----------------------------------------------------------------------------
def test_diacritics_count():
    assert diacritics("Divisé") == 1 and diacritics("Divise") == 0 and diacritics("Élève") == 2


def test_is_stripped_variant_picks_best_rendering():
    assert is_stripped_variant("Divise", ["Split", "Divisé"]) == "Divisé"
    assert is_stripped_variant("Divisé", ["Divisé", "Divise"]) is None
    assert is_stripped_variant("Split", ["Divisé"]) is None
    assert is_stripped_variant("Eleve", ["Elève", "Élève"]) == "Élève"


def test_guard_upgrades_imdb_pick_when_incumbent_lacks_diacritics():
    # the "Split" -> "Divise" shape: current title has no diacritics, the fallback pick is the
    # stripped row, another row of the same title is properly rendered
    imdb = FakeImdb("Divise", ["Divise", "Divisé"])
    c = SourceChain([imdb]).resolve(make_item("Split", "Split"))
    assert c.title == "Divisé" and "diacritics-from-rendering" in c.note and c.source == "imdb"


def test_guard_uses_tmdb_renderings_too():
    c = SourceChain([FakeTmdb("Divise", others=["Divisé"])]).resolve(make_item("Split", "Split"))
    assert c.title == "Divisé"


def test_runner_refuses_stripped_write(settings):
    class BadChain(SourceChain):
        def resolve(self, item):
            return Candidate("Divise", "imdb", False)

    item = Item("1", "Films", Kind.MOVIE, "Split", "Split", 2017, [], "tt1")
    plex = FakePlex({"Films": [item]})
    chain = BadChain([FakeImdb("Divise", ["Divisé"])])
    summary, code = run_once(settings, plex=plex, chain=chain, curation=Curation())
    assert code == EXIT_RUN_ERROR and summary.libraries[0].errors == 1 and plex.writes == []


def test_runner_guard_skips_overrides(settings):
    item = Item("1", "Films", Kind.MOVIE, "Split", "Split", 2017, [], "tt1")
    plex = FakePlex({"Films": [item]})
    chain = SourceChain([FakeImdb(None, ["Divisé"])])
    _, code = run_once(settings, plex=plex, chain=chain, curation=Curation(overrides={"tt1": "Divise"}))
    assert code == EXIT_OK and plex.writes == [("1", "Divise")]


# --- review queue + counters -----------------------------------------------------------------
def test_review_queue_file_and_counters(settings):
    items = [
        Item("1", "Films", Kind.MOVIE, "Demoiselles d'honneur", "Bridesmaids", 2011, [], "tt1", "5"),
        Item("2", "Films", Kind.MOVIE, "L'abysse", "The Abyss", 1989, [], "tt2"),
        Item("3", "Films", Kind.MOVIE, "Split", "Split", 2017, [], "tt3"),
    ]
    rec1 = RegistryRecord("no_film=11", "BRIDESMAIDS", "MES MEILLEURES AMIES", 2011)
    rec2 = RegistryRecord("no_film=22", "ABYSS, THE", "ABYSS (V.F.)", 1989)

    class Reg(RegionalRegistry):
        name = "fakereg"

        def __init__(self):
            pass

        def resolve(self, item):
            return {
                "tt1": Candidate(
                    "MES MEILLEURES AMIES", "fakereg", True, needs_corroboration=True, record=rec1
                ),
                "tt2": RegistryRejection("fakereg", "registry-dubbed-version", rec2),
                "tt3": Candidate("DIVISE", "fakereg", True, needs_corroboration=True, record=REC),
            }.get(item.imdb_id)

    imdb = FakeImdb(None, ["Divisé", "Demoiselles d'honneur"])
    plex = FakePlex({"Films": items})
    summary, code = run_once(settings, plex=plex, chain=SourceChain([Reg(), imdb]), curation=Curation())
    assert code == EXIT_OK
    lib = summary.libraries[0]
    assert lib.registry_uncorroborated == 1 and lib.registry_dubbed_version == 1
    assert lib.applied == 1 and plex.writes == [("3", "Divisé")]
    rows = settings.review_queue_file.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith(
        "library,rating_key,kind,imdb_id,tmdb_id,year,current_title,original_title,reason,"
    )
    assert len(rows) == 3
    row1 = ",".join(
        [
            "Films,1,movie,tt1,5,2011,Demoiselles d'honneur,Bridesmaids,registry-uncorroborated",
            "fakereg,no_film=11,BRIDESMAIDS,MES MEILLEURES AMIES,2011,MES MEILLEURES AMIES",
            "Divisé | Demoiselles d'honneur",
        ]
    )
    assert row1 in rows[1]
    row2 = ",".join(
        [
            "Films,2,movie,tt2,,1989,L'abysse,The Abyss,registry-dubbed-version,fakereg,no_film=22",
            '"ABYSS, THE",ABYSS (V.F.),1989,,',
        ]
    )
    assert row2 in rows[2]
    assert "registry_uncorroborated" in summary.totals and summary.totals["registry_dubbed_version"] == 1


def test_summary_human_mentions_rejections():
    lib = LibrarySummary("L")
    lib.record_rejection("registry-uncorroborated")
    lib.record_rejection("registry-dubbed-version")
    assert "registry-uncorroborated=1" in lib.human() and "registry-dubbed-version=1" in lib.human()

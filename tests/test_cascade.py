import pytest

from plex_regional_titles.cascade import decide
from plex_regional_titles.curation import Curation
from plex_regional_titles.models import Candidate, Outcome
from tests.conftest import make_item


def resolver(title, source="imdb", authoritative=False):
    def _r(item):
        return None if title is None else Candidate(title, source, authoritative)

    return _r


def test_excluded_wins_over_everything():
    cur = Curation(exclusions={"tt0000001"}, overrides={"tt0000001": "X"})
    d = decide(make_item("Cur"), cur, resolver("Other", "regie", True))
    assert d.outcome == Outcome.EXCLUDED and not d.write


def test_excluded_by_tmdb_id():
    cur = Curation(exclusions={"tmdb:42"})
    d = decide(make_item("Cur", imdb=None, tmdb="42"), cur, resolver("Other"))
    assert d.outcome == Outcome.EXCLUDED


def test_override_writes_and_beats_sources():
    cur = Curation(overrides={"tt0000001": "Le Forcené"})
    d = decide(make_item("Rampage", "Rampage"), cur, resolver("Autre", "regie", True))
    assert d.outcome == Outcome.OVERRIDDEN and d.write and d.candidate.title == "Le Forcené"
    assert d.source == "override"


def test_override_already_set_and_locked_does_not_write():
    cur = Curation(overrides={"tt0000001": "Le Forcené"})
    d = decide(make_item("Le Forcené", "Rampage", locked=True), cur, resolver(None))
    assert d.outcome == Outcome.OVERRIDDEN and not d.write


def test_override_same_title_but_unlocked_writes_to_lock():
    cur = Curation(overrides={"tt0000001": "Le Forcené"})
    d = decide(make_item("Le Forcené", "Rampage", locked=False), cur, resolver(None))
    assert d.outcome == Outcome.OVERRIDDEN and d.write


def test_no_candidate_with_ids():
    d = decide(make_item("Cur"), Curation(), resolver(None))
    assert d.outcome == Outcome.NO_CANDIDATE


def test_no_ids_bucket_when_nothing_found():
    d = decide(make_item("Cur", imdb=None, tmdb=None), Curation(), resolver(None))
    assert d.outcome == Outcome.NO_IDS


def test_registry_can_resolve_item_without_ids():
    d = decide(make_item("Cur", imdb=None, tmdb=None), Curation(), resolver("Régional", "regie", True))
    assert d.outcome == Outcome.APPLIED and d.write


@pytest.mark.parametrize(
    "current", ["La Chute de l'Empire romain", "LA CHUTE DE L EMPIRE ROMAIN", "la chute de l'empire romain !"]
)
def test_already_correct_uses_normalisation(current):
    d = decide(
        make_item(current, "The Fall of the Roman Empire"),
        Curation(),
        resolver("La Chute de l'Empire romain", "regie", True),
    )
    assert d.outcome == Outcome.ALREADY_CORRECT and not d.write


# --- the ambiguous rule matrix --------------------------------------------------------
@pytest.mark.parametrize(
    "source, authoritative, mode, expected, write",
    [
        ("imdb", False, "skip", Outcome.SAME_TITLE_SKIPPED, False),
        ("imdb", False, "review", Outcome.SAME_TITLE_REVIEWED, False),
        ("regie", True, "skip", Outcome.APPLIED, True),
        ("regie", True, "review", Outcome.APPLIED, True),
        ("tmdb", True, "skip", Outcome.APPLIED, True),
        ("tmdb", True, "review", Outcome.APPLIED, True),
    ],
)
def test_same_title_rule_only_for_non_authoritative(source, authoritative, mode, expected, write):
    item = make_item("À armes égales", "G.I. Jane")
    d = decide(item, Curation(), resolver("G.I. Jane", source, authoritative), mode)
    assert d.outcome == expected
    assert d.write is write


def test_same_title_rule_needs_original_title():
    item = make_item("À armes égales", None)
    d = decide(item, Curation(), resolver("G.I. Jane", "imdb", False))
    assert d.outcome == Outcome.APPLIED


def test_imdb_candidate_differing_from_both_titles_applies():
    item = make_item("À armes égales", "G.I. Jane")
    d = decide(item, Curation(), resolver("Soldat Jane", "imdb", False))
    assert d.outcome == Outcome.APPLIED and d.write and d.candidate.title == "Soldat Jane"


def test_cascade_order_override_before_resolve():
    calls = []

    def r(item):
        calls.append(item)
        return None

    decide(make_item("Cur"), Curation(overrides={"tt0000001": "X"}), r)
    assert calls == []

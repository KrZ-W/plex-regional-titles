import pytest

from plex_regional_titles.cascade import decide
from plex_regional_titles.curation import Curation
from plex_regional_titles.models import Candidate, Outcome
from plex_regional_titles.normalize import house_key
from plex_regional_titles.summary import LibrarySummary
from tests.conftest import make_item


@pytest.mark.parametrize(
    "a, b",
    [
        ("Beethoven II", "Beethoven 2"),
        ("Le parrain III", "Le Parrain 3"),
        ("Rocky IV", "Rocky 4"),
        ("Star Trek V - L'Ultime Frontière", "Star Trek 5: L'ultime frontière"),
        ("Halloween X", "Halloween 10"),
        ("Retour vers le futur Partie II", "Retour vers le futur 2"),
        ("Back to the Future Part III", "Back to the Future 3"),
        ("Retour vers le futur: Partie 2", "Retour vers le futur - 2"),
        ("Kill Bill: Volume 1", "Kill Bill : Volume 1"),
        ("Alien - Le 8ieme Passager", "Alien: Le 8ieme Passager"),
        ("Hitch - Expert en séduction", "Hitch: Expert en seduction"),
    ],
)
def test_house_key_equivalent(a, b):
    assert house_key(a) == house_key(b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Aliens", "Aliens, le Retour"),  # real subtitle difference
        ("Hitch", "Hitch - Expert en séduction"),
        ("Rocky II", "Rocky III"),
        ("Vivre", "VI vre"),
        ("Le parrain 2e partie", "Le parrain 2"),  # 2e is not normalised
        ("Chapitre II", "Chapitre"),
        ("Partie", "Partie 2"),
    ],
)
def test_house_key_not_equivalent(a, b):
    assert house_key(a) != house_key(b)


def test_roman_only_as_standalone_token():
    assert house_key("Vivre") == "vivre"
    assert house_key("Xavier") == "xavier"
    assert house_key("Malcolm X") == "malcolm 10"  # symmetric on both sides, so harmless


def _regie(title):
    return lambda item: Candidate(title, "regie", True, ref="no_film=1")


def test_cascade_house_style_counts_as_already_correct():
    d = decide(make_item("Beethoven 2", "Beethoven's 2nd"), Curation(), _regie("Beethoven II"))
    assert d.outcome == Outcome.ALREADY_CORRECT and d.house_style and not d.write and d.step == 4


def test_cascade_exact_match_is_not_flagged_house_style():
    d = decide(make_item("Beethoven II", "Beethoven's 2nd"), Curation(), _regie("Beethoven II"))
    assert d.outcome == Outcome.ALREADY_CORRECT and not d.house_style


def test_cascade_real_subtitle_difference_still_applies():
    d = decide(make_item("Aliens", "Aliens"), Curation(), _regie("Aliens, le Retour"))
    assert d.outcome == Outcome.APPLIED and d.write and d.step == 6


def test_summary_counter():
    lib = LibrarySummary("L")
    lib.record(decide(make_item("Beethoven 2"), Curation(), _regie("Beethoven II")))
    lib.record(decide(make_item("Beethoven II"), Curation(), _regie("Beethoven II")))
    assert lib.already_correct == 2 and lib.house_style_equivalent == 1
    assert "house-style=1" in lib.human()

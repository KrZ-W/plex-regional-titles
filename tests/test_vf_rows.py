"""v1.2.1: '<X> (V.F.)' rows discriminate on X."""

import pytest

from plex_regional_titles.config import load_settings
from plex_regional_titles.download import write_meta
from plex_regional_titles.models import Candidate, RegistryRejection
from plex_regional_titles.normalize import strip_articles
from plex_regional_titles.sources.chain import SourceChain
from plex_regional_titles.sources.regie import RegieDuCinemaRegistry
from plex_regional_titles.summary import LibrarySummary
from tests.conftest import StaticSource, make_item, regie_row, write_regie_csv
from tests.test_regie import OfflineSession

ROWS = [
    regie_row(106395, "G.I. JANE", "G.I. JANE (V.F.)", "G.I. JANE", 1997, "SCOTT, RIDLEY"),
    regie_row(327970, "ZOMBIELAND", "ZOMBIELAND (V.F.)", "ZOMBIELAND", 2009, "FLEISCHER, RUBEN"),
    regie_row(27287, "ABYSS, THE", "ABYSS (V.F.)", "ABYSS, THE", 1989, "CAMERON, JAMES"),
    regie_row(420626, "WONDER WOMAN 1984", "WW84 (V.F.)", "WW 84", 2020, "JENKINS, PATTY"),
    regie_row(
        24584,
        "NATIONAL LAMPOON'S EUROPEAN VACATION",
        "EUROPEAN VACATION (V.F.)",
        "NATIONAL LAMPOON'S EUROPEAN VACATION",
        1985,
        "HECKERLING, AMY",
    ),
    regie_row(329328, "GAKE NO UE NO PONYO", "PONYO (V.F.)", "PONYO (V.A.)", 2009, "MIYAZAKI, HAYAO"),
    regie_row(
        6721,
        "FROM RUSSIA WITH LOVE",
        "FROM RUSSIA WITH LOVE (V.F.)",
        "FROM RUSSIA WITH LOVE",
        1963,
        "YOUNG, TERENCE",
    ),
    regie_row(1, "ÉTÉ, L'", "ÉTÉ, L' (V.F.)", "SUMMER", 2001, "X, Y"),
    regie_row(2, "NOYEAR", "NOYEAR (V.F.)", "NOYEAR", "", "X, Y"),
    regie_row(3, "FOO", "FOO (V.F.)", "BAR", 2001, "X, Y"),
]


@pytest.fixture
def regie(settings):
    write_regie_csv(settings.cache_dir / "regie.csv", ROWS)
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    yield src
    src.close()


def test_the_five_rows(regie):
    c = regie.resolve(make_item("À armes égales", "G.I. Jane", 1997))
    assert isinstance(c, Candidate) and c.bucket == "registry-original-confirmed" and c.title == "G.I. JANE"
    c = regie.resolve(make_item("Bienvenue à Zombieland", "Zombieland", 2009))
    assert isinstance(c, Candidate) and c.bucket == "registry-original-confirmed"
    r = regie.resolve(make_item("L'abysse", "The Abyss", 1989))
    assert (
        isinstance(r, RegistryRejection)
        and r.reason == "registry-original-ambiguous"
        and r.candidate_title == "ABYSS"
    )
    r = regie.resolve(make_item("Wonder Woman 1984", "Wonder Woman 1984", 2020))
    assert (
        isinstance(r, RegistryRejection)
        and r.reason == "registry-dubbed-version"
        and r.candidate_title == "WW84"
    )
    r = regie.resolve(make_item("Bonjour les vacances II", "National Lampoon's European Vacation", 1985))
    assert isinstance(r, RegistryRejection) and r.reason == "registry-dubbed-version"


def test_confirmed_row_still_requires_corroboration(regie):
    chain = SourceChain([regie])
    # Plex original title corroborates
    c = chain.resolve(make_item("Bienvenue à Zombieland", "Zombieland", 2009))
    assert (
        c.title == "Zombieland"
        and c.source == "regie"
        and chain.take_buckets() == ["registry-original-confirmed"]
    )
    # matched through TITRE_ANGLAIS, X equals TITRE, nothing renders X -> nothing is written,
    # queued as uncorroborated, and still counted as confirmed
    chain = SourceChain([regie])
    assert chain.resolve(make_item("Bar (fr)", "Bar", 2001)) is None
    assert chain.take_buckets() == ["registry-original-confirmed"]
    (rj,) = chain.take_rejections()
    assert rj.reason == "registry-uncorroborated" and rj.candidate_title == "FOO"


def test_confirmation_via_titre_anglais_uses_x_as_candidate(regie):
    imdb = StaticSource("imdb", False, "Ponyo sur la falaise")
    imdb.renderings = lambda item: ["Ponyo", "Ponyo sur la falaise"]
    chain = SourceChain([regie, imdb])
    c = chain.resolve(make_item("Gake no ue no Ponyo", "Gake no ue no Ponyo", 2009))
    assert c.source == "regie" and c.title == "Ponyo"


def test_year_floor_sends_old_confirmations_to_review(regie):
    r = regie.resolve(make_item("Bons baisers de Russie", "From Russia with Love", 1963))
    assert isinstance(r, RegistryRejection) and r.reason == "registry-original-ambiguous"
    r = regie.resolve(make_item("Noyear", "Noyear", 2000))
    assert r is None  # no registry year -> no year match at all


def test_year_floor_is_configurable(settings):
    settings.regie_confirm_min_year = 1960
    write_regie_csv(settings.cache_dir / "regie.csv", ROWS)
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    c = src.resolve(make_item("Bons baisers de Russie", "From Russia with Love", 1963))
    assert isinstance(c, Candidate) and c.bucket == "registry-original-confirmed"
    src.close()


def test_inverted_article_row_equal_to_titre_is_confirmed_and_uninverted(regie):
    c = regie.resolve(make_item("Summer", "L'Été", 2001))
    assert isinstance(c, Candidate) and c.title == "L'ÉTÉ" and c.bucket == "registry-original-confirmed"


def test_independent_of_original_title_confirmation_knob(settings):
    settings.regie_original_title_confirmation = True
    write_regie_csv(settings.cache_dir / "regie.csv", ROWS)
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    r = src.resolve(make_item("L'abysse", "The Abyss", 1989))
    assert isinstance(r, RegistryRejection) and r.reason == "registry-original-ambiguous"
    r = src.resolve(make_item("Wonder Woman 1984", "Wonder Woman 1984", 2020))
    assert isinstance(r, RegistryRejection) and r.reason == "registry-dubbed-version"
    src.close()


@pytest.mark.parametrize("a, b", [("ABYSS", "ABYSS, THE"), ("The Abyss", "Abyss"), ("Été, L'", "Été")])
def test_strip_articles(a, b):
    assert strip_articles(a) == strip_articles(b)


def test_strip_articles_keeps_single_token():
    assert strip_articles("The") == "the" and strip_articles("A Team") == "team"


def test_counters_and_config():
    lib = LibrarySummary("L")
    for r in (
        "registry-original-confirmed",
        "registry-original-ambiguous",
        "registry-dubbed-version",
        "registry-uncorroborated",
        "unknown",
    ):
        lib.record_rejection(r)
    assert lib.registry_original_confirmed == 1 and lib.registry_original_ambiguous == 1
    assert "registry-original-confirmed=1" in lib.human()
    base = {"PLEX_URL": "http://p", "PLEX_TOKEN": "t", "PLEX_LIBRARIES": "F"}
    assert load_settings(base).regie_confirm_min_year == 1990
    assert load_settings({**base, "REGIE_CONFIRM_MIN_YEAR": "0"}).regie_confirm_min_year == 0
    with pytest.raises(Exception, match="REGIE_CONFIRM_MIN_YEAR"):
        load_settings({**base, "REGIE_CONFIRM_MIN_YEAR": "old"})

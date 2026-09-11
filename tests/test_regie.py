import pytest
import requests

from plex_regional_titles.download import write_meta
from plex_regional_titles.models import DatasetUnavailable, Kind, RegistryRejection
from plex_regional_titles.sources.chain import SourceChain
from plex_regional_titles.sources.regie import (
    RegieDuCinemaRegistry,
    build_index,
    director_surname,
    directors_match,
    surname_tokens,
)
from tests.conftest import StaticSource, make_item, regie_row, write_regie_csv


class OfflineSession:
    def get(self, *a, **k):
        raise requests.ConnectionError("offline")


@pytest.fixture
def regie(settings):
    write_regie_csv(settings.cache_dir / "regie.csv")
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12, "last_modified": "test"})
    settings.regie_original_title_confirmation = True  # the strict reading; tests cover both
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    yield src
    src.close()


def test_default_is_no_confirmation(settings):
    """Default: an empty TITRE_FRANCAIS is a miss for the registry, the chain continues."""
    assert settings.regie_original_title_confirmation is False
    write_regie_csv(settings.cache_dir / "regie.csv")
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    assert src.resolve(make_item("Bloodrayne", "BloodRayne", 2005)) is None
    imdb = StaticSource("imdb", False, "BloodRayne (fr-CA)")
    c = SourceChain([src, imdb]).resolve(make_item("Bloodrayne", "BloodRayne", 2005))
    assert c and c.source == "imdb"
    src.close()


def test_build_index_counts(settings):
    csv_path = write_regie_csv(settings.cache_dir / "regie.csv")
    n = build_index(csv_path, settings.cache_dir / "regie.sqlite")
    assert n == 14


def test_director_surname():
    assert director_surname("SCOTT, RIDLEY") == "scott"
    assert director_surname("Ridley Scott") == "scott"
    assert director_surname("") == ""
    assert surname_tokens("LAFLEUR-EMOND, STE") == {"lafleur", "emond"}
    assert surname_tokens("Sté Lafleur-Émond") == {"emond"}
    assert directors_match(["Sté Lafleur-Émond"], ["LAFLEUR-EMOND, STE"])
    assert directors_match(["Ridley Scott"], ["SCOTT, TONY", "BOLL, UWE"]) is not False
    assert not directors_match([], ["SCOTT, RIDLEY"])


def test_unique_title_year_match_original_title_confirmed(regie):
    c = regie.resolve(make_item("Bloodrayne", "BloodRayne", 2005))
    assert c and c.source == "regie" and c.authoritative
    assert c.title == "BLOODRAYNE" and "original title" in c.note and c.needs_corroboration
    assert c.record and c.record.ref == "no_film=269007" and c.record.regional_title == ""
    # through the chain the written string is the corroborating Plex title, never the registry's
    c = SourceChain([regie]).resolve(make_item("Bloodrayne", "BloodRayne", 2005))
    assert c.title == "Bloodrayne" and "corroborated" in c.note


def test_original_title_confirmation_uses_registry_title_not_native_script(regie):
    # Plex stores the native-script original; the registry's TITRE is the market original
    c = SourceChain([regie]).resolve(make_item("Ajeossi", "아저씨", 2010))
    assert c and c.title == "Ajeossi" and "corroborated" in c.note


def test_original_title_confirmation_can_be_disabled(settings):
    settings.regie_original_title_confirmation = False  # explicit, same as default
    write_regie_csv(settings.cache_dir / "regie.csv")
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    assert src.resolve(make_item("Bloodrayne", "BloodRayne", 2005)) is None
    assert src.resolve(make_item("Rampage", "Rampage", 1992, directors=["William Friedkin"])) is not None
    src.close()


def test_duplicate_classification_rows_count_as_one(settings):
    rows = [
        regie_row(1, "LEO", "LEO (V.F.)", "LEO", 2023, "CRYSTAL, ROBERT"),
        regie_row(2, "LEO", "LEO (V.F.)", "LEO", 2023, "CRYSTAL, ROBERT"),
    ]
    write_regie_csv(settings.cache_dir / "regie.csv", rows)
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    settings.regie_original_title_confirmation = True
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    assert src.resolve(make_item("Leo", "Leo", 2023)).title == "LEO"
    src.close()


def test_vf_suffix_means_dubbed_version_of_original_title(regie):
    # strict reading (fixture): the row confirms the original title, as a registry string
    c = regie.resolve(make_item("À armes égales", "G.I. Jane", 1997, directors=["Ridley Scott"]))
    assert c and c.title == "G.I. JANE" and c.needs_corroboration and "original title" in c.note


def test_vf_suffix_is_a_dubbed_version_rejection_by_default(settings):
    write_regie_csv(settings.cache_dir / "regie.csv")
    write_meta(settings.cache_dir / "regie.csv", {"checked_at": 9e12})
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    r = src.resolve(make_item("À armes égales", "G.I. Jane", 1997))
    assert isinstance(r, RegistryRejection) and r.reason == "registry-dubbed-version"
    assert r.record.regional_title == "G.I. JANE (V.F.)" and r.record.ref == "no_film=106395"
    # never a French candidate: the chain moves on and queues the rejection
    chain = SourceChain([src, StaticSource("imdb", False, "Soldat Jane")])
    c = chain.resolve(make_item("À armes égales", "G.I. Jane", 1997))
    assert c.source == "imdb" and [r.reason for r in chain.take_rejections()] == ["registry-dubbed-version"]
    src.close()


def test_french_title_with_inverted_article(regie):
    c = regie.resolve(make_item("La Chute de l'Empire romain", "The Fall of the Roman Empire", 1964))
    assert c and c.title == "LA CHUTE DE L'EMPIRE ROMAIN"


def test_plex_title_matching_french_column(regie):
    # item already carries the QC title and no originalTitle -> still matched via TITRE_FRANCAIS
    c = regie.resolve(make_item("La Chute de l'Empire romain", None, 1965))
    assert c and c.title == "LA CHUTE DE L'EMPIRE ROMAIN"


@pytest.mark.parametrize(
    "year, hit", [(1963, True), (1964, True), (1965, True), (1962, False), (1966, False)]
)
def test_year_window(regie, year, hit):
    c = regie.resolve(make_item("The Fall of the Roman Empire", None, year))
    assert (c is not None) is hit


def test_no_year_no_match(regie):
    assert regie.resolve(make_item("The Fall of the Roman Empire", None, None)) is None
    assert regie.resolve(make_item("Noyear", None, 2000)) is None


def test_director_tiebreak(regie):
    c = regie.resolve(make_item("Rampage", "Rampage", 1992, directors=["William Friedkin"]))
    assert c and c.title == "ENRAGE"
    c = regie.resolve(make_item("Rampage", "Rampage", 2018, directors=["Brad Peyton"]))
    assert c and c.title == "RAVAGES"


def test_ambiguous_without_director_is_no_hit(regie):
    # TWIN 2010 (Smith) / 2011 (Doe) / 2010 (Smith): year 2010 matches all three
    assert regie.resolve(make_item("Twin", None, 2010)) is None
    # director surname 'smith' still leaves two rows -> no hit
    assert regie.resolve(make_item("Twin", None, 2010, directors=["John Smith"])) is None
    # 'doe' narrows to one
    c = regie.resolve(make_item("Twin", None, 2010, directors=["Jane Doe"]))
    assert c and c.title == "JUMEAU B"


def test_uwe_boll_rampage_absent_from_registry(regie):
    assert regie.resolve(make_item("Le Forcené", "Rampage", 2009, directors=["Uwe Boll"])) is None


def test_language_suffix_on_original_column(regie):
    c = regie.resolve(make_item("Yuli", "Yuli", 2018))
    assert c and c.title == "YULI"


def test_vof_suffix_and_trailing_space(regie):
    c = regie.resolve(make_item("Multi", None, 1999))
    assert c and c.title == "RESULTAT"


def test_shows_not_supported(regie):
    assert Kind.SHOW not in regie.supports


def test_chain_corroboration_from_plex_original(regie):
    chain = SourceChain([regie])
    c = chain.resolve(make_item("À armes égales", "G.I. Jane", 1997))
    assert c.title == "G.I. Jane" and "corroborated" in c.note and c.source == "regie"


def test_chain_corroboration_from_tmdb(regie):
    tmdb = StaticSource("tmdb", True, "La Chute de l'Empire romain")
    chain = SourceChain([regie, tmdb])
    c = chain.resolve(make_item("La chute de l'empire", "The Fall of the Roman Empire", 1964))
    assert c.source == "regie" and c.title == "La Chute de l'Empire romain" and "corroborated" in c.note


def test_chain_uncorroborated_registry_yields_nothing_and_continues(regie):
    tmdb = StaticSource("tmdb", True, "Something Else")
    chain = SourceChain([regie, tmdb])
    c = chain.resolve(make_item("Rampage", "Rampage", 1992, directors=["William Friedkin"]))
    assert c.source == "tmdb" and c.title == "Something Else"
    (rj,) = chain.take_rejections()
    assert rj.reason == "registry-uncorroborated" and rj.candidate_title == "ENRAGE"
    assert (
        rj.record.regional_title == "ENRAGE"
        and rj.record.original_title == "RAMPAGE"
        and rj.record.year == 1992
    )


def test_chain_first_hit_wins_and_skips_unsupported(regie):
    imdb = StaticSource("imdb", False, "From IMDb")
    chain = SourceChain([regie, imdb])
    assert chain.resolve(make_item("Bloodrayne", "BloodRayne", 2005)).source == "regie"
    assert chain.resolve(make_item("Unknown", None, 2005)).source == "imdb"
    assert chain.resolve(make_item("Show", None, 2005, kind=Kind.SHOW)).source == "imdb"
    assert imdb.calls == 2


def test_prepare_without_dataset_and_offline_fails(settings):
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    with pytest.raises(DatasetUnavailable):
        src.prepare()


def test_prepare_uses_stale_index_when_refresh_fails(settings, caplog):
    csv_path = write_regie_csv(settings.cache_dir / "regie.csv")
    build_index(csv_path, settings.cache_dir / "regie.sqlite")
    write_meta(csv_path, {"checked_at": 0})  # stale -> tries to refresh -> offline
    src = RegieDuCinemaRegistry(settings, session=OfflineSession())
    src.prepare()
    c = src.resolve(make_item("Rampage", "Rampage", 1992, directors=["William Friedkin"]))
    assert c.title == "ENRAGE" and c.needs_corroboration
    src.close()


def test_index_rebuild_is_atomic_on_bad_csv(settings):
    csv_path = write_regie_csv(settings.cache_dir / "regie.csv")
    db = settings.cache_dir / "regie.sqlite"
    build_index(csv_path, db)
    before = db.read_bytes()
    bad = settings.cache_dir / "bad.csv"
    bad.write_text("A;B;C\n1;2;3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        build_index(bad, db)
    assert db.read_bytes() == before
    assert not db.with_suffix(".tmp").exists()


def test_regie_row_helper_roundtrip(settings):
    path = write_regie_csv(settings.cache_dir / "r.csv", [regie_row(9, "X", "Y", "X", 2001, "Z, W")])
    assert build_index(path, settings.cache_dir / "r.sqlite") == 1

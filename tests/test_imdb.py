import sqlite3

import pytest
import requests

from plex_regional_titles.download import write_meta
from plex_regional_titles.models import DatasetUnavailable
from plex_regional_titles.sources.imdb import ImdbAkasSource, build_index, pick_aka
from tests.conftest import make_item, write_akas_gz


class OfflineSession:
    def get(self, *a, **k):
        raise requests.ConnectionError("offline")


@pytest.fixture
def imdb(settings):
    gz = write_akas_gz(settings.cache_dir / "title.akas.tsv.gz")
    write_meta(gz, {"checked_at": 9e12})
    src = ImdbAkasSource(settings, session=OfflineSession())
    src.prepare()
    yield src
    src.close()


def test_build_index_filters_regions_or_language(settings):
    gz = write_akas_gz(settings.cache_dir / "a.gz")
    db = settings.cache_dir / "a.sqlite"
    n = build_index(gz, db, ["CA"], "fr")
    # kept: 1(FR fr) 2(CA) 3(CA) 4(CA en) 6(CA) 7(CA) 8(CA en) 9(BE fr) 11(FR fr); dropped: original(\N), JP
    assert n == 9
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM akas WHERE region='JP'").fetchone()[0] == 0
    assert dict(conn.execute("SELECT k, v FROM meta"))["regions"] == "CA"


def test_pick_aka_skips_literal_and_working_and_wrong_language():
    rows = [
        {
            "title": "Lit",
            "region": "CA",
            "language": "fr",
            "types": "",
            "attributes": "Literal English title",
            "ordering": 1,
        },
        {
            "title": "Work",
            "region": "CA",
            "language": "fr",
            "types": "working",
            "attributes": "",
            "ordering": 2,
        },
        {
            "title": "English",
            "region": "CA",
            "language": "en",
            "types": "imdbDisplay",
            "attributes": "",
            "ordering": 3,
        },
        {"title": "Later", "region": "CA", "language": "fr", "types": "", "attributes": "", "ordering": 5},
        {
            "title": "Display",
            "region": "CA",
            "language": "fr",
            "types": "imdbDisplay",
            "attributes": "",
            "ordering": 6,
        },
    ]
    assert pick_aka(rows, ["CA"], "fr")["title"] == "Display"
    assert pick_aka(rows[:4], ["CA"], "fr")["title"] == "Later"
    assert pick_aka(rows[:3], ["CA"], "fr") is None
    assert pick_aka(rows, ["CA"], "en")["title"] == "English"


def test_pick_aka_regions_order():
    rows = [
        {"title": "FR", "region": "FR", "language": "fr", "types": "", "attributes": "", "ordering": 1},
        {"title": "CA", "region": "CA", "language": "fr", "types": "", "attributes": "", "ordering": 2},
    ]
    assert pick_aka(rows, ["CA", "FR"], "fr")["title"] == "CA"
    assert pick_aka(rows, ["FR", "CA"], "fr")["title"] == "FR"
    assert pick_aka(rows, ["BE"], "fr") is None


def test_resolve(imdb):
    c = imdb.resolve(make_item("X", imdb="tt0000001"))
    assert c and c.title == "Titre Québec" and c.source == "imdb" and not c.authoritative
    assert imdb.resolve(make_item("X", imdb="tt0000002")).title == "Final Québec"
    assert imdb.resolve(make_item("X", imdb="tt0000003")) is None  # only en-CA
    assert imdb.resolve(make_item("X", imdb="tt0000004")) is None  # BE
    assert imdb.resolve(make_item("X", imdb="tt0000006")) is None  # FR not in REGIONS
    assert imdb.resolve(make_item("X", imdb=None, tmdb="1")) is None


def test_second_region_used_when_configured(settings):
    settings.regions = ["CA", "FR"]
    gz = write_akas_gz(settings.cache_dir / "title.akas.tsv.gz")
    write_meta(gz, {"checked_at": 9e12})
    src = ImdbAkasSource(settings, session=OfflineSession())
    src.prepare()
    assert src.resolve(make_item("X", imdb="tt0000006")).title == "Second Region"
    src.close()


def test_atomic_replace_keeps_old_index_on_failure(settings):
    gz = write_akas_gz(settings.cache_dir / "ok.gz")
    db = settings.cache_dir / "imdb.sqlite"
    build_index(gz, db, ["CA"], "fr")
    before = db.read_bytes()
    bad = settings.cache_dir / "bad.gz"
    bad.write_bytes(b"not gzip at all")
    with pytest.raises(OSError):
        build_index(bad, db, ["CA"], "fr")
    assert db.read_bytes() == before
    assert not db.with_suffix(".tmp").exists()


def test_bad_header_rejected(settings):
    gz = write_akas_gz(settings.cache_dir / "h.gz", rows=[])
    import gzip

    with gzip.open(gz, "wt") as fh:
        fh.write("foo\tbar\n1\t2\n")
    with pytest.raises(ValueError, match="missing column"):
        build_index(gz, settings.cache_dir / "h.sqlite", ["CA"], "fr")


def test_prepare_offline_without_cache_raises(settings):
    with pytest.raises(DatasetUnavailable):
        ImdbAkasSource(settings, session=OfflineSession()).prepare()


def test_prepare_rebuilds_when_index_config_differs(settings):
    gz = write_akas_gz(settings.cache_dir / "title.akas.tsv.gz")
    write_meta(gz, {"checked_at": 9e12})
    build_index(gz, settings.cache_dir / "imdb-akas.sqlite", ["FR"], "fr")
    src = ImdbAkasSource(settings, session=OfflineSession())  # settings want CA
    src.prepare()
    assert src.resolve(make_item("X", imdb="tt0000001")).title == "Titre Québec"
    src.close()

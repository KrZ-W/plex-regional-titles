from pathlib import Path

import pytest

from plex_regional_titles.config import load_settings
from plex_regional_titles.curation import Curation, parse_exclusions, parse_overrides
from plex_regional_titles.models import ConfigError
from tests.conftest import make_item

BASE = {"PLEX_URL": "http://plex:32400", "PLEX_TOKEN": "t", "PLEX_LIBRARIES": "Films en français, Séries"}


def test_parse_exclusions():
    text = "# header\n tt0123 # trailing\n\nimdb:tt0456\nTMDB:789\n"
    assert parse_exclusions(text) == {"tt0123", "tt0456", "tmdb:789"}


def test_parse_exclusions_rejects_garbage():
    with pytest.raises(ConfigError, match="line 2"):
        parse_exclusions("tt1\nnot-an-id\n")


def test_parse_overrides():
    text = 'tt0001: "Le Forcené"\ntmdb:12: Hugo\n"imdb:tt0002": "21"\n'
    assert parse_overrides(text) == {"tt0001": "Le Forcené", "tmdb:12": "Hugo", "tt0002": "21"}


@pytest.mark.parametrize("text", ["- a\n- b\n", "tt1: ''\n", "bad: X\n", "tt1: 3\n"])
def test_parse_overrides_errors(text):
    with pytest.raises(ConfigError):
        parse_overrides(text)


def test_curation_load(tmp_path: Path):
    (tmp_path / "exclusions.txt").write_text("tt0001\n", encoding="utf-8")
    (tmp_path / "overrides.yaml").write_text("tmdb:5: Hugo\n", encoding="utf-8")
    cur = Curation.load(tmp_path / "exclusions.txt", tmp_path / "overrides.yaml")
    assert cur.is_excluded(make_item("x", imdb="tt0001"))
    assert cur.override_for(make_item("x", imdb="tt9", tmdb="5")) == "Hugo"
    assert cur.override_for(make_item("x", imdb="tt9")) is None


def test_curation_load_missing_files(tmp_path: Path):
    cur = Curation.load(tmp_path / "nope.txt", tmp_path / "nope.yaml")
    assert cur.exclusions == set() and cur.overrides == {}


def test_settings_defaults():
    s = load_settings(BASE)
    assert s.libraries == ["Films en français", "Séries"]
    assert s.regions == ["CA"] and s.language == "fr" and s.locale == "fr-CA"
    assert s.sources == ["regie", "tmdb", "imdb"]
    assert s.same_title_mode == "skip" and s.schedule == "30 4 * * *"
    assert s.dataset_max_age_days == 7 and s.write_rate == 5.0 and s.dry_run is False
    assert s.config_dir == Path("/config") and s.plex_verify_ssl is True


def test_settings_parsing():
    s = load_settings(
        {
            **BASE,
            "REGIONS": "ca, fr",
            "LANGUAGE": "FR",
            "SOURCES": "imdb",
            "WRITE_RATE": "2/s",
            "SCHEDULE": "once",
            "DRY_RUN": "yes",
            "SAME_TITLE_MODE": "Review",
            "TMDB_API_KEY": "k",
            "CONFIG_DIR": "/tmp/x",
            "PLEX_VERIFY_SSL": "false",
        }
    )
    assert s.regions == ["CA", "FR"] and s.language == "fr" and s.sources == ["imdb"]
    assert s.write_rate == 2.0 and s.run_once and s.dry_run and s.same_title_mode == "review"
    assert s.tmdb_api_key == "k" and s.config_dir == Path("/tmp/x") and not s.plex_verify_ssl


@pytest.mark.parametrize(
    "env, needle",
    [
        ({}, "PLEX_URL is required"),
        ({"PLEX_URL": "plex:32400"}, "http"),
        ({**BASE, "PLEX_LIBRARIES": ""}, "PLEX_LIBRARIES"),
        ({**BASE, "REGIONS": "Canada"}, "REGIONS"),
        ({**BASE, "LANGUAGE": "fra"}, "LANGUAGE"),
        ({**BASE, "SOURCES": "regie,wikipedia"}, "unknown source"),
        ({**BASE, "SOURCES": "imdb,imdb"}, "more than once"),
        ({**BASE, "SAME_TITLE_MODE": "ask"}, "SAME_TITLE_MODE"),
        ({**BASE, "SCHEDULE": "every day"}, "SCHEDULE"),
        ({**BASE, "DATASET_MAX_AGE_DAYS": "0"}, "DATASET_MAX_AGE_DAYS"),
        ({**BASE, "DATASET_MAX_AGE_DAYS": "x"}, "DATASET_MAX_AGE_DAYS"),
        ({**BASE, "WRITE_RATE": "fast"}, "WRITE_RATE"),
        ({**BASE, "WRITE_RATE": "0"}, "WRITE_RATE"),
        ({**BASE, "LOG_LEVEL": "LOUD"}, "LOG_LEVEL"),
    ],
)
def test_settings_errors(env, needle):
    with pytest.raises(ConfigError) as ei:
        load_settings(env)
    assert needle in str(ei.value)


def test_settings_error_lists_all_problems():
    with pytest.raises(ConfigError) as ei:
        load_settings({"PLEX_TOKEN": "t"})
    msg = str(ei.value)
    assert "PLEX_URL" in msg and "PLEX_LIBRARIES" in msg

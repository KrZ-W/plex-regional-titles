import json
from datetime import UTC, datetime, timedelta

from plex_regional_titles import cli
from plex_regional_titles.runner import EXIT_CONFIG


def test_main_config_error(monkeypatch, capsys):
    monkeypatch.delenv("PLEX_URL", raising=False)
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    assert cli.main(["once"]) == EXIT_CONFIG
    assert "PLEX_URL is required" in capsys.readouterr().err


def _write_state(settings, age: timedelta, status="ok"):
    finished = (datetime.now(UTC) - age).isoformat(timespec="seconds")
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.last_run_file.write_text(
        json.dumps({"started_at": finished, "finished_at": finished, "status": status})
    )


def test_healthcheck(settings, capsys):
    assert cli.healthcheck(settings) == 1  # no state yet
    _write_state(settings, timedelta(minutes=5))
    assert cli.healthcheck(settings) == 0
    _write_state(settings, timedelta(days=3))
    assert cli.healthcheck(settings) == 1
    _write_state(settings, timedelta(minutes=5), status="error")
    assert cli.healthcheck(settings) == 1
    settings.schedule = "once"
    _write_state(settings, timedelta(days=30))
    assert cli.healthcheck(settings) == 0


def test_plex_client_helpers():
    from types import SimpleNamespace as NS

    from plex_regional_titles.models import Kind
    from plex_regional_titles.plex_client import parse_guids, title_is_locked, to_item

    guids = [NS(id="imdb://tt0119173"), NS(id="tmdb://9384?lang=en"), NS(id="tvdb://1")]
    assert parse_guids(guids) == {"imdb": "tt0119173", "tmdb": "9384", "tvdb": "1"}
    obj = NS(
        ratingKey=5,
        title="G.I. Jane",
        originalTitle="",
        year="1997",
        guids=guids,
        directors=[NS(tag="Ridley Scott")],
        fields=[NS(name="title", locked=True)],
    )
    it = to_item(obj, "Films", Kind.MOVIE)
    assert it.original_title is None and it.year == 1997 and it.directors == ["Ridley Scott"]
    assert it.imdb_id == "tt0119173" and it.title_locked and it.id_label == "tt0119173"
    assert not title_is_locked(NS(fields=[]))

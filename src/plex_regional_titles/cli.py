"""Entry point: ``once``, ``cron`` (in-process scheduler), ``healthcheck``."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from croniter import croniter

from plex_regional_titles import __version__
from plex_regional_titles.config import Settings, load_settings
from plex_regional_titles.models import ConfigError, DatasetUnavailable, PlexAuthError
from plex_regional_titles.runner import (
    EXIT_CONFIG,
    EXIT_DATASET,
    EXIT_PLEX_AUTH,
    EXIT_RUN_ERROR,
    run_once,
)

log = logging.getLogger("plex_regional_titles")


def setup_logging(level: str, log_dir: Path | None) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_dir / "plex-regional-titles.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
            )
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError as exc:
            root.warning("cannot open log file in %s: %s", log_dir, exc)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _load() -> Settings:
    from plex_regional_titles.sources import available_source_names

    return load_settings(known_sources=available_source_names())


def cmd_once(settings: Settings) -> int:
    try:
        _, code = run_once(settings)
        return code
    except PlexAuthError as exc:
        log.error("%s", exc)
        return EXIT_PLEX_AUTH
    except DatasetUnavailable as exc:
        log.error("%s", exc)
        return EXIT_DATASET


def cmd_cron(settings: Settings) -> int:
    if settings.run_once:
        return cmd_once(settings)
    log.info("Scheduler: cron %r (TZ=%s)", settings.schedule, os.environ.get("TZ", "UTC"))
    while True:
        now = datetime.now().astimezone()
        nxt = croniter(settings.schedule, now).get_next(datetime)
        wait = max(0.0, (nxt - now).total_seconds())
        log.info("Next run at %s (in %.0f min)", nxt.isoformat(timespec="minutes"), wait / 60)
        time.sleep(wait)
        code = cmd_once(settings)
        log.info("Run finished with exit code %d", code)
        if code == EXIT_PLEX_AUTH:
            # a bad token will not fix itself; let the orchestrator surface it
            return code


def healthcheck(settings: Settings) -> int:
    """0 when last-run.json exists, reports no fatal error and is younger than 2x the schedule
    interval (minimum 1 hour, plus 25 minutes grace for a slow run)."""
    import json

    path = settings.last_run_file
    if not path.exists():
        print("no last-run.json yet")
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        finished = datetime.fromisoformat(data.get("finished_at") or data["started_at"])
    except (ValueError, KeyError, OSError) as exc:
        print(f"unreadable last-run.json: {exc}")
        return 1
    if settings.run_once:
        allowed = 10 * 365 * 86400.0  # a one-shot container is healthy once it ran
    else:
        base = datetime.now().astimezone()
        it = croniter(settings.schedule, base)
        a = it.get_next(datetime)
        b = it.get_next(datetime)
        allowed = max(3600.0, 2 * (b - a).total_seconds()) + 1500
    age = (datetime.now(UTC) - finished).total_seconds()
    if age > allowed:
        print(f"last run is {age / 3600:.1f}h old (allowed {allowed / 3600:.1f}h)")
        return 1
    if data.get("status") != "ok":
        print(f"last run status={data.get('status')}: {data.get('error', '')}")
        return 1
    print(f"ok: last run {age / 60:.0f} min ago")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="plex-regional-titles",
        description="Set Plex titles to the regional release title and lock them.",
    )
    ap.add_argument(
        "command",
        nargs="?",
        default="cron",
        choices=["once", "cron", "healthcheck"],
        help="once: single run then exit; cron: in-process scheduler (SCHEDULE); "
        "healthcheck: exit 0 when the last run is recent and healthy",
    )
    ap.add_argument("--dry-run", action="store_true", help="same as DRY_RUN=true")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    try:
        settings = _load()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG
    if args.dry_run:
        settings.dry_run = True

    if args.command == "healthcheck":
        return healthcheck(settings)

    setup_logging(settings.log_level, settings.log_dir)
    log.info(
        "plex-regional-titles %s | libraries=%s sources=%s regions=%s language=%s "
        "same_title_mode=%s dry_run=%s",
        __version__,
        settings.libraries,
        settings.sources,
        settings.regions,
        settings.language,
        settings.same_title_mode,
        settings.dry_run,
    )
    try:
        if args.command == "once":
            return cmd_once(settings)
        return cmd_cron(settings)
    except KeyboardInterrupt:
        return EXIT_RUN_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

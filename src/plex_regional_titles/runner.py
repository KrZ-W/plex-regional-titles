"""One full run: prepare sources, walk libraries, decide, write, summarise."""

from __future__ import annotations

import logging
from dataclasses import replace

from plex_regional_titles.cascade import decide
from plex_regional_titles.config import Settings
from plex_regional_titles.curation import Curation
from plex_regional_titles.models import Decision, Kind, Outcome
from plex_regional_titles.plex_client import PlexClient
from plex_regional_titles.review import write_review, write_would_apply
from plex_regional_titles.sources import build_sources
from plex_regional_titles.sources.chain import SourceChain
from plex_regional_titles.summary import LibrarySummary, RunSummary

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_PLEX_AUTH = 2
EXIT_DATASET = 3
EXIT_RUN_ERROR = 4


def _log_decision(d: Decision, dry_run: bool) -> None:
    it, c = d.item, d.candidate
    tag = "DRY-RUN " if dry_run and d.write else ""
    if d.outcome in (Outcome.APPLIED, Outcome.OVERRIDDEN) and d.write:
        log.info(
            "%sAPPLY  [%s] %s (%s, %s) %r -> %r  source=%s %s",
            tag,
            it.library,
            it.id_label,
            it.year,
            it.kind,
            it.title,
            c.title,
            c.source,
            c.note,
        )
    elif d.outcome in (Outcome.SAME_TITLE_SKIPPED, Outcome.SAME_TITLE_REVIEWED):
        log.info(
            "%s [%s] %s %r candidate=%r source=%s (%s)",
            d.outcome.value.upper(),
            it.library,
            it.id_label,
            it.title,
            c.title,
            c.source,
            c.note,
        )
    else:
        log.debug(
            "%s [%s] %s %r%s",
            d.outcome.value,
            it.library,
            it.id_label,
            it.title,
            f" candidate={c.title!r} source={c.source} {c.note}" if c else "",
        )


def run_once(
    settings: Settings,
    plex: PlexClient | None = None,
    chain: SourceChain | None = None,
    curation: Curation | None = None,
) -> tuple[RunSummary, int]:
    """Execute one run. Returns (summary, exit_code). Raises PlexAuthError / DatasetUnavailable
    before any Plex write when Plex auth or a dataset without cache fails."""
    summary = RunSummary.start(settings.dry_run, settings.sources, settings.locale)
    curation = curation or Curation.load(settings.exclusions_file, settings.overrides_file)
    plex = plex or PlexClient(settings)  # PlexAuthError propagates
    own_chain = chain is None
    chain = chain or SourceChain(build_sources(settings))
    if own_chain:
        chain.prepare()  # DatasetUnavailable propagates
    log.info("Sources in order: %s", ", ".join(s.name for s in chain.sources) or "(none)")

    review: list[Decision] = []
    would_apply: list[Decision] = []
    exit_code = EXIT_OK
    try:
        for name in settings.libraries:
            lib = LibrarySummary(library=name)
            summary.libraries.append(lib)
            try:
                section = plex.section(name)
            except LookupError as exc:
                log.error("%s", exc)
                lib.errors += 1
                exit_code = EXIT_RUN_ERROR
                continue
            lib.kind = section.type
            log.info("Library %r (%s): scanning", name, section.type)
            for item in plex.items(name):
                try:
                    d = decide(item, curation, chain.resolve, settings.same_title_mode)
                    if d.write:
                        # snapshot before the write so would-apply.csv shows the pre-change title
                        would_apply.append(replace(d, item=replace(item, plex_obj=None)))
                    if d.write and not settings.dry_run:
                        plex.write_title(item, d.candidate.title)
                except Exception as exc:
                    log.error("error on [%s] %s %r: %s", name, item.id_label, item.title, exc)
                    d = Decision(item, Outcome.ERROR, reason=str(exc))
                    exit_code = EXIT_RUN_ERROR
                _log_decision(d, settings.dry_run)
                lib.record(d)
                if d.outcome == Outcome.SAME_TITLE_REVIEWED:
                    review.append(d)
            log.info(lib.human())
        if settings.same_title_mode == "review" or settings.dry_run:
            write_would_apply(settings.would_apply_file, would_apply)
            log.info("would-apply.csv: %d row(s)", len(would_apply))
        if settings.same_title_mode == "review":
            write_review(settings.review_file, review)
            log.info("review.csv: %d item(s) queued", len(review))
        summary.finish(
            "ok" if exit_code == EXIT_OK else "error",
            "" if exit_code == EXIT_OK else "errors during run; see log",
        )
    except Exception as exc:
        summary.finish("error", str(exc))
        exit_code = EXIT_RUN_ERROR
        log.exception("run aborted")
    finally:
        if own_chain:
            chain.close()
    summary.write(settings.last_run_file)
    for line in summary.human().splitlines():
        log.info(line)
    return summary, exit_code


def kinds_of(settings: Settings) -> set[Kind]:  # pragma: no cover - convenience
    return {Kind.MOVIE, Kind.SHOW}

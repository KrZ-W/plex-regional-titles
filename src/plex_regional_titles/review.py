"""review.csv writer for SAME_TITLE_MODE=review."""

from __future__ import annotations

import csv
import os
from pathlib import Path

from plex_regional_titles.models import Decision, Item, RegistryRejection

COLUMNS = (
    "library",
    "kind",
    "rating_key",
    "imdb_id",
    "tmdb_id",
    "year",
    "current_title",
    "original_title",
    "candidate",
    "source",
    "note",
)


def write_review(path: Path, decisions: list[Decision]) -> None:
    """Rewrite review.csv with this run's ambiguous items (empty file when there are none)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for d in decisions:
            it, c = d.item, d.candidate
            w.writerow(
                [
                    it.library,
                    it.kind.value,
                    it.rating_key,
                    it.imdb_id or "",
                    it.tmdb_id or "",
                    it.year or "",
                    it.title,
                    it.original_title or "",
                    c.title if c else "",
                    c.source if c else "",
                    c.note if c else "",
                ]
            )
    os.replace(tmp, path)


WOULD_APPLY_COLUMNS = (
    "library",
    "rating_key",
    "kind",
    "imdb_id",
    "tmdb_id",
    "year",
    "current_title",
    "candidate",
    "source",
    "ref",
    "cascade_step",
    "reason",
)


def write_would_apply(path: Path, decisions: list[Decision]) -> None:
    """Rewrite would-apply.csv: one row per would-be title write (dry run / review mode)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(WOULD_APPLY_COLUMNS)
        for d in decisions:
            it, c = d.item, d.candidate
            w.writerow(
                [
                    it.library,
                    it.rating_key,
                    it.kind.value,
                    it.imdb_id or "",
                    it.tmdb_id or "",
                    it.year or "",
                    it.title,
                    c.title if c else "",
                    c.source if c else "",
                    c.ref if c else "",
                    d.step,
                    d.reason,
                ]
            )
    os.replace(tmp, path)


REVIEW_QUEUE_COLUMNS = (
    "library",
    "rating_key",
    "kind",
    "imdb_id",
    "tmdb_id",
    "year",
    "current_title",
    "original_title",
    "reason",
    "registry",
    "registry_ref",
    "registry_titre",
    "registry_titre_francais",
    "registry_annee",
    "registry_candidate",
    "regional_akas",
)


def write_review_queue(path: Path, entries: list[tuple[Item, RegistryRejection]]) -> None:
    """Rewrite would-apply-review.csv: registry hits that were not written and need a human
    (or an external tool) to adjudicate. Decisions come back through overrides.yaml."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(REVIEW_QUEUE_COLUMNS)
        for it, rj in entries:
            rec = rj.record
            w.writerow(
                [
                    it.library,
                    it.rating_key,
                    it.kind.value,
                    it.imdb_id or "",
                    it.tmdb_id or "",
                    it.year or "",
                    it.title,
                    it.original_title or "",
                    rj.reason,
                    rj.source,
                    rec.ref,
                    rec.original_title,
                    rec.regional_title,
                    rec.year or "",
                    rj.candidate_title,
                    " | ".join(rj.akas),
                ]
            )
    os.replace(tmp, path)

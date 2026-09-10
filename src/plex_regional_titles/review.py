"""review.csv writer for SAME_TITLE_MODE=review."""

from __future__ import annotations

import csv
import os
from pathlib import Path

from plex_regional_titles.models import Decision

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

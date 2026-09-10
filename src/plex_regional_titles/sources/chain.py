"""The ordered source chain: first hit wins, with cased-title donors for registries."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from plex_regional_titles.models import Candidate, Item
from plex_regional_titles.normalize import norm, title_case
from plex_regional_titles.sources.base import TitleSource

log = logging.getLogger(__name__)


class SourceChain:
    def __init__(self, sources: Sequence[TitleSource]) -> None:
        self.sources = list(sources)

    def prepare(self) -> None:
        for src in self.sources:
            src.prepare()

    def close(self) -> None:
        for src in self.sources:
            try:
                src.close()
            except Exception:  # pragma: no cover
                log.debug("close() failed for %s", src.name, exc_info=True)

    def resolve(self, item: Item) -> Candidate | None:
        for i, src in enumerate(self.sources):
            if item.kind not in src.supports:
                continue
            try:
                cand = src.resolve(item)
            except Exception as exc:
                log.warning("%s: resolve failed for %s (%s): %s", src.name, item.title, item.id_label, exc)
                continue
            if cand is None:
                continue
            if cand.needs_casing:
                cand = self._apply_casing(cand, item, self.sources[i + 1 :])
            return cand
        return None

    def _apply_casing(self, cand: Candidate, item: Item, donors: Sequence[TitleSource]) -> Candidate:
        """Registries may publish titles in capitals; borrow the casing from a matching title."""
        key = norm(cand.title)
        for label, text in (("plex", item.title), ("plex-original", item.original_title)):
            if text and norm(text) == key:
                return Candidate(
                    text, cand.source, cand.authoritative, f"{cand.note}; casing={label}".strip("; ")
                )
        for src in donors:
            if item.kind not in src.supports:
                continue
            try:
                other = src.resolve(item)
            except Exception:
                continue
            if other and norm(other.title) == key:
                return Candidate(
                    other.title,
                    cand.source,
                    cand.authoritative,
                    f"{cand.note}; casing={src.name}".strip("; "),
                )
        return Candidate(
            title_case(cand.title),
            cand.source,
            cand.authoritative,
            f"{cand.note}; casing=heuristic".strip("; "),
        )

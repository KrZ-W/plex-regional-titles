"""The ordered source chain: first hit wins; registry candidates must be corroborated.

A registry (Régie du cinéma or any other) is a *corroborator*, not a naming authority: it
records what was classified and released, in an internal house style (capitals, no
diacritics, inverted articles, "2ieme", "02"), and it can hold the France title when the
France dub was the version distributed. So a registry string is never written as such. It
is written only when an independently sourced, properly rendered string normalises equal
to it and carries at least as many diacritics: the current Plex title, the Plex original
title, the TMDB regional translation, or any IMDb aka row for the id, in that order. The
written value is that string. Without corroboration the registry yields nothing, the
rejection is queued for review, and the item continues down the chain.

The diacritic guard applies to every candidate from every source: a string that is a
diacritic-stripped variant of a known rendering of the same title is replaced by the best
rendering, and the runner refuses to write one should it ever get through.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from plex_regional_titles.models import Candidate, Item, RegistryRejection
from plex_regional_titles.normalize import diacritics, is_stripped_variant, norm
from plex_regional_titles.sources.base import TitleSource

log = logging.getLogger(__name__)


class SourceChain:
    def __init__(self, sources: Sequence[TitleSource]) -> None:
        self.sources = list(sources)
        self.rejections: list[RegistryRejection] = []

    def prepare(self) -> None:
        for src in self.sources:
            src.prepare()

    def close(self) -> None:
        for src in self.sources:
            try:
                src.close()
            except Exception:  # pragma: no cover
                log.debug("close() failed for %s", src.name, exc_info=True)

    def take_rejections(self) -> list[RegistryRejection]:
        out, self.rejections = self.rejections, []
        return out

    # -- helpers ---------------------------------------------------------------------------
    def _source(self, name: str) -> TitleSource | None:
        return next((s for s in self.sources if s.name == name), None)

    def renderings(self, item: Item) -> list[str]:
        """Known properly rendered strings for the item: Plex, then TMDB, then IMDb."""
        out = [t for t in (item.title, item.original_title) if t]
        for name in ("tmdb", "imdb"):
            src = self._source(name)
            if src is None or item.kind not in src.supports:
                continue
            try:
                out.extend(src.renderings(item))
            except Exception as exc:
                log.warning("%s: renderings failed for %s: %s", name, item.id_label, exc)
        return out

    def _corroborate(self, cand: Candidate, item: Item) -> str | None:
        """The first independently sourced string equal to the registry string, or None."""
        key, need = norm(cand.title), diacritics(cand.title)

        def ok(text: str | None) -> bool:
            return bool(text) and norm(text) == key and diacritics(text) >= need

        if ok(item.title):
            return item.title
        if ok(item.original_title):
            return item.original_title
        tmdb = self._source("tmdb")
        if tmdb is not None and item.kind in tmdb.supports:
            try:
                regional = tmdb.resolve(item)
            except Exception:
                regional = None
            if regional is not None and not isinstance(regional, RegistryRejection) and ok(regional.title):
                return regional.title
        imdb = self._source("imdb")
        if imdb is not None and item.kind in imdb.supports:
            try:
                for text in imdb.renderings(item):
                    if ok(text):
                        return text
            except Exception:
                pass
        return None

    def _regional_akas(self, item: Item) -> list[str]:
        imdb = self._source("imdb")
        if imdb is None or not hasattr(imdb, "regional_akas"):
            return []
        try:
            return imdb.regional_akas(item)
        except Exception:
            return []

    def _guard(self, cand: Candidate, item: Item) -> Candidate:
        """Never let a diacritic-stripped variant of a known rendering through."""
        better = is_stripped_variant(cand.title, self.renderings(item))
        if better is None:
            return cand
        log.info("diacritic guard: %r -> %r for %s (%s)", cand.title, better, item.title, item.id_label)
        return Candidate(
            better,
            cand.source,
            cand.authoritative,
            f"{cand.note}; diacritics-from-rendering".strip("; "),
            ref=cand.ref,
            record=cand.record,
        )

    # -- main ------------------------------------------------------------------------------
    def resolve(self, item: Item) -> Candidate | None:
        for src in self.sources:
            if item.kind not in src.supports:
                continue
            try:
                result = src.resolve(item)
            except Exception as exc:
                log.warning("%s: resolve failed for %s (%s): %s", src.name, item.title, item.id_label, exc)
                continue
            if result is None:
                continue
            if isinstance(result, RegistryRejection):
                result.akas = self._regional_akas(item)
                self.rejections.append(result)
                continue
            cand = result
            if cand.needs_corroboration:
                text = self._corroborate(cand, item)
                if text is None:
                    log.debug(
                        "%s: uncorroborated %r for %s (%s)", src.name, cand.title, item.title, item.id_label
                    )
                    self.rejections.append(
                        RegistryRejection(
                            src.name,
                            "registry-uncorroborated",
                            cand.record,
                            candidate_title=cand.title,
                            akas=self._regional_akas(item),
                        )
                    )
                    continue
                cand = Candidate(
                    text,
                    cand.source,
                    cand.authoritative,
                    f"{cand.note}; corroborated".strip("; "),
                    ref=cand.ref,
                    record=cand.record,
                )
            return self._guard(cand, item)
        return None

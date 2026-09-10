"""Per-item decision cascade (pure; no Plex I/O)."""

from __future__ import annotations

from collections.abc import Callable

from plex_regional_titles.curation import Curation
from plex_regional_titles.models import Candidate, Decision, Item, Outcome
from plex_regional_titles.normalize import house_key, norm

Resolver = Callable[[Item], Candidate | None]


def decide(item: Item, curation: Curation, resolve: Resolver, same_title_mode: str = "skip") -> Decision:
    """Apply the cascade:

    1. excluded id            -> EXCLUDED
    2. override               -> OVERRIDDEN (write unless already exactly that title and locked)
    3. resolve through chain  -> NO_IDS / NO_CANDIDATE when nothing
    4. candidate == current   -> ALREADY_CORRECT
    5. non-authoritative candidate == original title -> SAME_TITLE_SKIPPED / SAME_TITLE_REVIEWED
    6. otherwise              -> APPLIED (write + lock)
    """
    if curation.is_excluded(item):
        return Decision(item, Outcome.EXCLUDED, reason="id in exclusions", step=1)

    override = curation.override_for(item)
    if override is not None:
        cand = Candidate(override, "override", True, "overrides.yaml")
        already = item.title == override and item.title_locked
        return Decision(
            item,
            Outcome.OVERRIDDEN,
            cand,
            write=not already,
            reason="already set and locked" if already else "override",
            step=2,
        )

    cand = resolve(item)
    if cand is None:
        if not item.has_ids:
            return Decision(item, Outcome.NO_IDS, reason="no imdb/tmdb id and no registry match", step=3)
        return Decision(item, Outcome.NO_CANDIDATE, reason="no source returned a title", step=3)

    if norm(cand.title) == norm(item.title):
        return Decision(item, Outcome.ALREADY_CORRECT, cand, reason="candidate equals current title", step=4)
    if house_key(cand.title) == house_key(item.title):
        return Decision(
            item,
            Outcome.ALREADY_CORRECT,
            cand,
            reason="candidate equals current title up to house style",
            step=4,
            house_style=True,
        )

    if not cand.authoritative and item.original_title and norm(cand.title) == norm(item.original_title):
        if same_title_mode == "review":
            return Decision(
                item,
                Outcome.SAME_TITLE_REVIEWED,
                cand,
                reason="fallback candidate equals original title; queued for review",
                step=5,
            )
        return Decision(
            item,
            Outcome.SAME_TITLE_SKIPPED,
            cand,
            reason="fallback candidate equals original title",
            step=5,
        )

    return Decision(item, Outcome.APPLIED, cand, write=True, reason="regional title differs", step=6)

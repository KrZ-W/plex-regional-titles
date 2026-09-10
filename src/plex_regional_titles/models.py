"""Data types shared across the tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    MOVIE = "movie"
    SHOW = "show"


@dataclass(slots=True)
class Item:
    """A Plex library item (movie, or series-level show) reduced to what the tool needs."""

    rating_key: str
    library: str
    kind: Kind
    title: str
    original_title: str | None = None
    year: int | None = None
    directors: list[str] = field(default_factory=list)
    imdb_id: str | None = None
    tmdb_id: str | None = None
    tvdb_id: str | None = None
    title_locked: bool = False
    plex_obj: Any = field(default=None, repr=False, compare=False)

    @property
    def has_ids(self) -> bool:
        return bool(self.imdb_id or self.tmdb_id)

    @property
    def id_label(self) -> str:
        return self.imdb_id or (f"tmdb:{self.tmdb_id}" if self.tmdb_id else f"key:{self.rating_key}")


@dataclass(slots=True)
class Candidate:
    """A regional title proposed by a source."""

    title: str
    source: str
    authoritative: bool
    note: str = ""
    needs_casing: bool = False


class Outcome(StrEnum):
    EXCLUDED = "excluded"
    OVERRIDDEN = "overridden"
    APPLIED = "applied"
    ALREADY_CORRECT = "already-correct"
    SAME_TITLE_SKIPPED = "same-title-skipped"
    SAME_TITLE_REVIEWED = "same-title-reviewed"
    NO_CANDIDATE = "no-candidate"
    NO_IDS = "no-ids"
    ERROR = "error"


@dataclass(slots=True)
class Decision:
    item: Item
    outcome: Outcome
    candidate: Candidate | None = None
    write: bool = False  # True when the title must be written + locked
    reason: str = ""

    @property
    def source(self) -> str | None:
        return self.candidate.source if self.candidate else None


class DatasetUnavailable(RuntimeError):
    """A source cannot serve: download failed and no cached index exists."""


class PlexAuthError(RuntimeError):
    """Plex refused the token or the URL is not a Plex server."""


class ConfigError(ValueError):
    """Invalid configuration; message lists every problem found."""

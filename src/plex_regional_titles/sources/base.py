"""Source interfaces and the regional-registry plugin mechanism."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, ClassVar

from plex_regional_titles.models import Candidate, Item, Kind, RegistryRejection

if TYPE_CHECKING:
    from plex_regional_titles.config import Settings

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "plex_regional_titles.registries"


class TitleSource(ABC):
    """Something that can propose a regional title for a Plex item."""

    name: ClassVar[str]
    authoritative: ClassVar[bool]
    supports: ClassVar[frozenset[Kind]] = frozenset({Kind.MOVIE, Kind.SHOW})

    def prepare(self) -> None:  # noqa: B027 - optional hook
        """Download / refresh / index. Raise DatasetUnavailable when the source cannot serve."""

    @abstractmethod
    def resolve(self, item: Item) -> Candidate | RegistryRejection | None:
        """Return a candidate, a registry rejection (registries only) or None.
        Must not raise for ordinary misses."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release handles (SQLite connections etc.)."""

    def renderings(self, item: Item) -> list[str]:
        """Every properly rendered title string this source knows for the item (for
        corroborating registry candidates and for the diacritic guard). Default: none."""
        return []


class RegionalRegistry(TitleSource):
    """A government / industry registry of regional release titles.

    Subclass it, set ``name``, implement ``prepare`` and ``resolve``, and register the class
    with ``@register_registry`` (in-tree) or the ``plex_regional_titles.registries`` entry
    point group (third-party package). Registries are authoritative: a hit is a decision,
    so the ambiguous same-title rule never applies to them.
    """

    authoritative: ClassVar[bool] = True
    supports: ClassVar[frozenset[Kind]] = frozenset({Kind.MOVIE})

    def __init__(self, settings: Settings) -> None:
        self.settings = settings


_REGISTRIES: dict[str, type[RegionalRegistry]] = {}


def register_registry(cls: type[RegionalRegistry]) -> type[RegionalRegistry]:
    """Class decorator: make a RegionalRegistry selectable through SOURCES by its ``name``."""
    _REGISTRIES[cls.name] = cls
    return cls


def registry_classes() -> dict[str, type[RegionalRegistry]]:
    """In-tree registries plus any discovered through entry points."""
    # importing the package registers in-tree plugins
    from plex_regional_titles.sources import regie  # noqa: F401

    found = dict(_REGISTRIES)
    try:
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            if ep.name in found:
                continue
            try:
                cls = ep.load()
            except Exception as exc:  # pragma: no cover - third-party plugin failure
                log.warning("Could not load registry plugin %s: %s", ep.name, exc)
                continue
            if isinstance(cls, type) and issubclass(cls, RegionalRegistry):
                found[ep.name] = cls
    except Exception as exc:  # pragma: no cover
        log.debug("entry point scan failed: %s", exc)
    return found


def available_source_names() -> set[str]:
    return set(registry_classes()) | {"tmdb", "imdb"}


def build_sources(settings: Settings, names: Iterable[str] | None = None) -> list[TitleSource]:
    """Instantiate the configured sources in SOURCES order (does not prepare them)."""
    from plex_regional_titles.sources.imdb import ImdbAkasSource
    from plex_regional_titles.sources.tmdb import TmdbSource

    registries = registry_classes()
    sources: list[TitleSource] = []
    for name in names if names is not None else settings.sources:
        if name == "tmdb":
            if not settings.tmdb_api_key:
                log.warning("SOURCES includes tmdb but TMDB_API_KEY is not set; skipping tmdb")
                continue
            sources.append(TmdbSource(settings))
        elif name == "imdb":
            sources.append(ImdbAkasSource(settings))
        elif name in registries:
            sources.append(registries[name](settings))
        else:
            raise ValueError(f"unknown source {name!r}")
    return sources

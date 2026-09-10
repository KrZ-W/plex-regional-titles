"""Plex access via python-plexapi: read items, write + lock the title field only."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

import requests
import urllib3
from plexapi.exceptions import Unauthorized
from plexapi.server import PlexServer

from plex_regional_titles.config import Settings
from plex_regional_titles.models import Item, Kind, PlexAuthError

log = logging.getLogger(__name__)


class RateLimiter:
    """Simple fixed-interval limiter: at most ``rate`` calls per second."""

    def __init__(self, rate: float) -> None:
        self.interval = 1.0 / rate if rate > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
                now = time.monotonic()
            self._next = now + self.interval


def parse_guids(guids) -> dict[str, str]:
    out: dict[str, str] = {}
    for g in guids or []:
        gid = getattr(g, "id", "") or ""
        if "://" not in gid:
            continue
        scheme, _, value = gid.partition("://")
        value = value.split("?", 1)[0]
        if scheme in ("imdb", "tmdb", "tvdb") and value and scheme not in out:
            out[scheme] = value
    return out


def title_is_locked(obj) -> bool:
    for f in getattr(obj, "fields", None) or []:
        if getattr(f, "name", "") == "title":
            return bool(getattr(f, "locked", False))
    return False


def to_item(obj, library: str, kind: Kind) -> Item:
    ids = parse_guids(getattr(obj, "guids", None))
    directors = [d.tag for d in (getattr(obj, "directors", None) or []) if getattr(d, "tag", None)]
    year = getattr(obj, "year", None)
    return Item(
        rating_key=str(obj.ratingKey),
        library=library,
        kind=kind,
        title=obj.title or "",
        original_title=getattr(obj, "originalTitle", None) or None,
        year=int(year) if year else None,
        directors=directors,
        imdb_id=ids.get("imdb"),
        tmdb_id=ids.get("tmdb"),
        tvdb_id=ids.get("tvdb"),
        title_locked=title_is_locked(obj),
        plex_obj=obj,
    )


class PlexClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        session = requests.Session()
        session.verify = settings.plex_verify_ssl
        if not settings.plex_verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            self.server = PlexServer(
                settings.plex_url, settings.plex_token, session=session, timeout=settings.plex_timeout
            )
        except Unauthorized as exc:
            raise PlexAuthError(f"Plex rejected the token at {settings.plex_url}") from exc
        except requests.RequestException as exc:
            raise PlexAuthError(f"Cannot reach Plex at {settings.plex_url}: {exc}") from exc
        self.limiter = RateLimiter(settings.write_rate)
        log.info("Connected to Plex %s (%s)", self.server.friendlyName, self.server.version)

    def section(self, name: str):
        """Return the library section by exact name; raise LookupError if absent or wrong type."""
        for sec in self.server.library.sections():
            if sec.title == name:
                if sec.type not in ("movie", "show"):
                    raise LookupError(f"library {name!r} is of type {sec.type}; only movie/show supported")
                return sec
        raise LookupError(f"library {name!r} not found on the Plex server")

    def items(self, name: str) -> Iterator[Item]:
        sec = self.section(name)
        kind = Kind.MOVIE if sec.type == "movie" else Kind.SHOW
        # includeGuids so guids are populated without a reload per item
        for obj in sec.all(container_size=500, includeGuids=True):
            yield to_item(obj, name, kind)

    def write_title(self, item: Item, title: str) -> None:
        """Write the title field and lock it. Nothing else is touched."""
        self.limiter.wait()
        item.plex_obj.editTitle(title, locked=True)

"""TMDB translations for LANGUAGE-REGION (e.g. fr-CA), movies and shows."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Protocol

import requests

from plex_regional_titles.models import Candidate, Item, Kind
from plex_regional_titles.sources.base import TitleSource

log = logging.getLogger(__name__)

TMDB_API = "https://api.themoviedb.org/3"


class TmdbClient(Protocol):
    def translations(self, kind: Kind, tmdb_id: str) -> list[dict]:
        """Return the ``translations`` list from TMDB (each with iso_3166_1, iso_639_1, data)."""


class HttpTmdbClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: int = 30) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def translations(self, kind: Kind, tmdb_id: str) -> list[dict]:
        path = "movie" if kind == Kind.MOVIE else "tv"
        resp = self.session.get(
            f"{TMDB_API}/{path}/{tmdb_id}/translations",
            params={"api_key": self.api_key},
            timeout=self.timeout,
            headers={"User-Agent": "plex-regional-titles/1.0"},
        )
        if resp.status_code == 404:
            return []
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", "2"))
            time.sleep(min(retry, 30))
            return self.translations(kind, tmdb_id)
        resp.raise_for_status()
        return resp.json().get("translations", [])


def pick_translation(translations: list[dict], language: str, regions: list[str], kind: Kind) -> str | None:
    """First non-empty translated title for (language, region) in REGIONS order."""
    field = "title" if kind == Kind.MOVIE else "name"
    for region in regions:
        for t in translations:
            if (t.get("iso_639_1") or "").lower() != language:
                continue
            if (t.get("iso_3166_1") or "").upper() != region:
                continue
            title = ((t.get("data") or {}).get(field) or "").strip()
            if title:
                return title
    return None


class TmdbSource(TitleSource):
    name = "tmdb"
    authoritative = True

    def __init__(self, settings, client: TmdbClient | None = None) -> None:
        self.settings = settings
        self.client: TmdbClient = client or HttpTmdbClient(settings.tmdb_api_key or "")
        self.cache_path = settings.cache_dir / "tmdb.sqlite"
        self.conn: sqlite3.Connection | None = None
        self.ttl = settings.dataset_max_age_days * 86400

    def prepare(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.cache_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS translations (kind TEXT, tmdb_id TEXT, fetched_at REAL,"
            " payload TEXT, PRIMARY KEY (kind, tmdb_id))"
        )
        self.conn.commit()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _translations(self, kind: Kind, tmdb_id: str) -> list[dict]:
        if self.conn is not None:
            row = self.conn.execute(
                "SELECT fetched_at, payload FROM translations WHERE kind=? AND tmdb_id=?",
                (kind.value, tmdb_id),
            ).fetchone()
            if row and time.time() - row[0] < self.ttl:
                return json.loads(row[1])
        data = self.client.translations(kind, tmdb_id)
        if self.conn is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO translations VALUES (?,?,?,?)",
                (kind.value, tmdb_id, time.time(), json.dumps(data)),
            )
            self.conn.commit()
        return data

    def resolve(self, item: Item) -> Candidate | None:
        if not item.tmdb_id:
            return None
        translations = self._translations(item.kind, item.tmdb_id)
        title = pick_translation(translations, self.settings.language, self.settings.regions, item.kind)
        if not title:
            return None
        return Candidate(title, self.name, True, f"tmdb:{item.tmdb_id} {self.settings.locale}")

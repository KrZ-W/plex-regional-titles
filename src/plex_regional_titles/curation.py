"""exclusions.txt and overrides.yaml parsing."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from plex_regional_titles.models import ConfigError, Item

log = logging.getLogger(__name__)

_IMDB_RE = re.compile(r"^(?:imdb:)?(tt\d+)$", re.IGNORECASE)
_TMDB_RE = re.compile(r"^tmdb:(\d+)$", re.IGNORECASE)


def canonical_id(raw: str) -> str | None:
    """'tt123' / 'imdb:tt123' -> 'tt123'; 'tmdb:99' -> 'tmdb:99'; else None."""
    s = raw.strip()
    m = _IMDB_RE.match(s)
    if m:
        return m.group(1).lower()
    m = _TMDB_RE.match(s)
    if m:
        return f"tmdb:{m.group(1)}"
    return None


def parse_exclusions(text: str) -> set[str]:
    ids: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        cid = canonical_id(body)
        if cid is None:
            raise ConfigError(f"exclusions.txt line {lineno}: {body!r} is not tt… or tmdb:…")
        ids.add(cid)
    return ids


def parse_overrides(text: str) -> dict[str, str]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ConfigError("overrides.yaml must be a mapping of id -> title")
    out: dict[str, str] = {}
    for key, value in data.items():
        cid = canonical_id(str(key))
        if cid is None:
            raise ConfigError(f"overrides.yaml: key {key!r} is not tt… or tmdb:…")
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"overrides.yaml: title for {key} must be a non-empty string")
        out[cid] = value.strip()
    return out


@dataclass(slots=True)
class Curation:
    exclusions: set[str] = field(default_factory=set)
    overrides: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _keys(item: Item) -> list[str]:
        keys = []
        if item.imdb_id:
            keys.append(item.imdb_id.lower())
        if item.tmdb_id:
            keys.append(f"tmdb:{item.tmdb_id}")
        return keys

    def is_excluded(self, item: Item) -> bool:
        return any(k in self.exclusions for k in self._keys(item))

    def override_for(self, item: Item) -> str | None:
        for k in self._keys(item):
            if k in self.overrides:
                return self.overrides[k]
        return None

    @classmethod
    def load(cls, exclusions_file: Path, overrides_file: Path) -> Curation:
        cur = cls()
        if exclusions_file.exists():
            cur.exclusions = parse_exclusions(exclusions_file.read_text(encoding="utf-8"))
        if overrides_file.exists():
            cur.overrides = parse_overrides(overrides_file.read_text(encoding="utf-8"))
        log.info("Curation: %d exclusion(s), %d override(s)", len(cur.exclusions), len(cur.overrides))
        return cur

"""Conditional dataset downloads (ETag / Last-Modified) with sidecar metadata."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadResult:
    path: Path
    changed: bool  # a new file was written
    from_cache: bool  # nothing downloaded (fresh, or 304, or network failure with cache)


def _meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def read_meta(path: Path) -> dict:
    try:
        return json.loads(_meta_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_meta(path: Path, meta: dict) -> None:
    tmp = _meta_path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, _meta_path(path))


def fetch_dataset(
    url: str,
    dest: Path,
    max_age_days: int,
    session: requests.Session | None = None,
    timeout: int = 120,
    force: bool = False,
) -> DownloadResult:
    """Download ``url`` to ``dest`` if the local copy is missing or older than ``max_age_days``.

    Uses If-None-Match / If-Modified-Since. Writes to a temp file and atomically replaces.
    On a network failure with an existing local file, returns the cached file and logs a
    warning; without a local file the exception propagates.
    """
    session = session or requests.Session()
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = read_meta(dest)
    exists = dest.exists()
    if exists and not force:
        age = time.time() - meta.get("checked_at", dest.stat().st_mtime)
        if age < max_age_days * 86400:
            log.debug("%s is fresh (%.1f days); not checking upstream", dest.name, age / 86400)
            return DownloadResult(dest, changed=False, from_cache=True)

    headers = {"User-Agent": "plex-regional-titles/1.0"}
    if exists:
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with session.get(url, headers=headers, stream=True, timeout=timeout) as resp:
            if resp.status_code == 304 and exists:
                log.info("%s unchanged upstream (304)", dest.name)
                meta["checked_at"] = time.time()
                write_meta(dest, meta)
                return DownloadResult(dest, changed=False, from_cache=True)
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        fh.write(chunk)
            os.replace(tmp, dest)
            new_meta = {
                "url": url,
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "downloaded_at": time.time(),
                "checked_at": time.time(),
                "size": dest.stat().st_size,
            }
            write_meta(dest, new_meta)
            log.info("Downloaded %s (%.1f MB)", dest.name, new_meta["size"] / 1e6)
            return DownloadResult(dest, changed=True, from_cache=False)
    except (requests.RequestException, OSError) as exc:
        tmp.unlink(missing_ok=True)
        if exists:
            log.warning("Could not refresh %s (%s); using cached copy", dest.name, exc)
            return DownloadResult(dest, changed=False, from_cache=True)
        raise

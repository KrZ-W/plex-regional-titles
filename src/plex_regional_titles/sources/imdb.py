"""IMDb title.akas fallback: stream-parsed into a SQLite index of the regions/language of interest."""

from __future__ import annotations

import csv
import gzip
import logging
import os
import sqlite3
import sys
from pathlib import Path

import requests

from plex_regional_titles.download import fetch_dataset, read_meta
from plex_regional_titles.models import Candidate, DatasetUnavailable, Item
from plex_regional_titles.sources.base import TitleSource

log = logging.getLogger(__name__)
csv.field_size_limit(sys.maxsize)

SCHEMA = """
CREATE TABLE akas (
    title_id TEXT, ordering INTEGER, title TEXT, region TEXT, language TEXT,
    types TEXT, attributes TEXT, is_original INTEGER
);
CREATE INDEX idx_akas_title ON akas(title_id);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def _nn(value: str | None) -> str:
    return "" if value in (None, "\\N") else value


def build_index(akas_gz: Path, db_path: Path, regions: list[str], language: str) -> int:
    """Stream the gzipped TSV, keep rows with region in ``regions`` or language == ``language``.

    Builds into a temp file and atomically replaces ``db_path`` only on success, so a failure
    mid-way leaves the previous index untouched.
    """
    wanted_regions = {r.upper() for r in regions}
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    kept = 0
    try:
        conn.executescript(SCHEMA)
        batch: list[tuple] = []
        with gzip.open(akas_gz, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = next(reader)
            idx = {name: i for i, name in enumerate(header)}
            for col in ("titleId", "ordering", "title", "region", "language"):
                if col in idx:
                    continue
                raise ValueError(f"akas file missing column {col}")
            i_id, i_ord, i_title = idx["titleId"], idx["ordering"], idx["title"]
            i_reg, i_lang = idx["region"], idx["language"]
            i_types, i_attr, i_orig = idx.get("types"), idx.get("attributes"), idx.get("isOriginalTitle")
            for row in reader:
                if len(row) <= i_lang:
                    continue
                region = _nn(row[i_reg]).upper()
                lang = _nn(row[i_lang]).lower()
                if region not in wanted_regions and lang != language:
                    continue
                batch.append(
                    (
                        row[i_id],
                        int(row[i_ord]) if row[i_ord].isdigit() else 0,
                        row[i_title],
                        region,
                        lang,
                        _nn(row[i_types]) if i_types is not None else "",
                        _nn(row[i_attr]) if i_attr is not None else "",
                        1 if i_orig is not None and row[i_orig] == "1" else 0,
                    )
                )
                kept += 1
                if len(batch) >= 50_000:
                    conn.executemany("INSERT INTO akas VALUES (?,?,?,?,?,?,?,?)", batch)
                    batch.clear()
            if batch:
                conn.executemany("INSERT INTO akas VALUES (?,?,?,?,?,?,?,?)", batch)
        conn.execute("INSERT INTO meta VALUES ('rows', ?)", (str(kept),))
        conn.execute("INSERT INTO meta VALUES ('regions', ?)", (",".join(sorted(wanted_regions)),))
        conn.execute("INSERT INTO meta VALUES ('language', ?)", (language,))
        conn.commit()
        conn.close()
        os.replace(tmp, db_path)
    except Exception:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    return kept


def pick_aka(rows: list[dict], regions: list[str], language: str) -> dict | None:
    """First usable row in REGIONS order for ``language``.

    Skips attributes containing "literal" (case-insensitive) and working titles.
    Within a region, a row typed ``imdbDisplay`` beats the others; then lowest ordering.
    """
    for region in regions:
        usable = []
        for r in rows:
            if r["region"] != region.upper() or r["language"] != language:
                continue
            if "literal" in (r.get("attributes") or "").lower():
                continue
            if "working" in (r.get("types") or "").lower():
                continue
            if not (r.get("title") or "").strip():
                continue
            usable.append(r)
        if usable:
            usable.sort(key=lambda r: (0 if "imdbDisplay" in (r.get("types") or "") else 1, r["ordering"]))
            return usable[0]
    return None


class ImdbAkasSource(TitleSource):
    name = "imdb"
    authoritative = False

    def __init__(self, settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.gz_path = settings.cache_dir / "title.akas.tsv.gz"
        self.db_path = settings.cache_dir / "imdb-akas.sqlite"
        self.conn: sqlite3.Connection | None = None

    def _index_matches_config(self) -> bool:
        if not self.db_path.exists():
            return False
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            meta = dict(conn.execute("SELECT k, v FROM meta").fetchall())
            conn.close()
        except sqlite3.Error:
            return False
        return (
            meta.get("regions") == ",".join(sorted(r.upper() for r in self.settings.regions))
            and meta.get("language") == self.settings.language
        )

    def prepare(self) -> None:
        had_index = self._index_matches_config()
        try:
            result = fetch_dataset(
                self.settings.imdb_akas_url,
                self.gz_path,
                self.settings.dataset_max_age_days,
                self.session,
                timeout=600,
            )
            if result.changed or not had_index:
                log.info(
                    "imdb: indexing akas for regions=%s language=%s (this takes a few minutes)",
                    ",".join(self.settings.regions),
                    self.settings.language,
                )
                n = build_index(self.gz_path, self.db_path, self.settings.regions, self.settings.language)
                log.info("imdb: indexed %d aka rows", n)
        except Exception as exc:
            if had_index:
                log.warning("imdb: refresh failed (%s); using existing index", exc)
            else:
                raise DatasetUnavailable(
                    f"imdb: cannot download/index akas and no cached index: {exc}"
                ) from exc
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        meta = read_meta(self.gz_path)
        log.info("imdb: akas last-modified %s", meta.get("last_modified", "unknown"))

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def resolve(self, item: Item) -> Candidate | None:
        if not item.imdb_id:
            return None
        if self.conn is None:
            raise RuntimeError("imdb: prepare() not called")
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM akas WHERE title_id=? ORDER BY ordering", (item.imdb_id,)
            ).fetchall()
        ]
        best = pick_aka(rows, self.settings.regions, self.settings.language)
        if not best:
            return None
        return Candidate(
            best["title"].strip(),
            self.name,
            False,
            f"{item.imdb_id} {best['language']}-{best['region']} types={best['types'] or '-'}",
            ref=f"ordering={best['ordering']}",
        )

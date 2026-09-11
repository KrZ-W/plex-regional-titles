"""Régie du cinéma / Ministère de la Culture du Québec film classification registry.

Open data (Données Québec, CSV, semicolon-delimited, UTF-8 BOM).  No IMDb/TMDB ids, so
matching is by normalised original title + year (±1), with the director surname as a
tiebreaker, and requires a unique row.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

import requests

from plex_regional_titles.download import fetch_dataset, read_meta
from plex_regional_titles.models import (
    Candidate,
    DatasetUnavailable,
    Item,
    Kind,
    RegistryRecord,
    RegistryRejection,
)
from plex_regional_titles.normalize import (
    clean_registry_title,
    has_dubbed_version_suffix,
    match_key,
    norm,
    strip_articles,
    strip_language_suffix,
    strip_version_suffix,
)
from plex_regional_titles.sources.base import RegionalRegistry, register_registry

log = logging.getLogger(__name__)
csv.field_size_limit(sys.maxsize)

SCHEMA = """
CREATE TABLE films (
    no_film TEXT PRIMARY KEY,
    titre TEXT, titre_fr TEXT, titre_en TEXT,
    key_titre TEXT, key_fr TEXT, key_en TEXT,
    annee INTEGER, directors TEXT, url TEXT
);
CREATE INDEX idx_key_titre ON films(key_titre);
CREATE INDEX idx_key_fr ON films(key_fr);
CREATE INDEX idx_key_en ON films(key_en);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def surname_tokens(name: str | None) -> set[str]:
    """Registry 'LAFLEUR-EMOND, STE' -> {'lafleur', 'emond'}; Plex 'Sté Lafleur-Émond' -> {'emond'}.

    Registry names are 'SURNAME, GIVEN' so every token before the comma is a surname token; Plex
    names are 'Given Surname' so only the last token is safe. A director matches when the sets
    intersect.
    """
    s = (name or "").strip()
    if not s:
        return set()
    if "," in s:
        return set(norm(s.split(",", 1)[0]).split())
    parts = norm(s).split()
    return {parts[-1]} if parts else set()


def director_surname(name: str | None) -> str:
    """'SCOTT, RIDLEY' -> 'scott' ; 'Ridley Scott' -> 'scott' (last surname token)."""
    toks = surname_tokens(name)
    return sorted(toks)[-1] if toks else ""


def directors_match(item_directors: list[str], row_directors: list[str]) -> bool:
    item_tokens = set().union(*(surname_tokens(d) for d in item_directors)) if item_directors else set()
    if not item_tokens:
        return False
    row_tokens = set().union(*(surname_tokens(d) for d in row_directors)) if row_directors else set()
    return bool(item_tokens & row_tokens)


def build_index(csv_path: Path, db_path: Path) -> int:
    """Parse the CSV into a fresh SQLite index. Atomic: writes to a temp file, then replaces."""
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    count = 0
    try:
        conn.executescript(SCHEMA)
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            required = {"NO_FILM", "TITRE", "TITRE_FRANCAIS", "TITRE_ANGLAIS", "ANNEE"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Régie CSV is missing columns: {sorted(missing)}")
            rows = []
            for r in reader:
                titre = (r.get("TITRE") or "").strip()
                titre_fr = (r.get("TITRE_FRANCAIS") or "").strip()
                titre_en = (r.get("TITRE_ANGLAIS") or "").strip()
                annee_raw = (r.get("ANNEE") or "").strip()
                annee = int(annee_raw) if annee_raw.isdigit() else None
                directors = [
                    d.strip()
                    for d in (r.get("REALISATEUR1"), r.get("REALISATEUR2"), r.get("REALISATEUR3"))
                    if d and d.strip()
                ]
                rows.append(
                    (
                        (r.get("NO_FILM") or "").strip() or f"row{count}",
                        titre,
                        titre_fr,
                        titre_en,
                        match_key(titre),
                        match_key(titre_fr),
                        match_key(titre_en),
                        annee,
                        json.dumps(directors, ensure_ascii=False),
                        (r.get("URL") or "").strip(),
                    )
                )
                count += 1
            conn.executemany("INSERT OR REPLACE INTO films VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT INTO meta VALUES ('rows', ?)", (str(count),))
        conn.commit()
        conn.close()
        os.replace(tmp, db_path)
    except Exception:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    return count


@register_registry
class RegieDuCinemaRegistry(RegionalRegistry):
    name = "regie"
    supports = frozenset({Kind.MOVIE})

    def __init__(self, settings, session: requests.Session | None = None) -> None:
        super().__init__(settings)
        self.session = session or requests.Session()
        self.csv_path = settings.cache_dir / "regie.csv"
        self.db_path = settings.cache_dir / "regie.sqlite"
        self.conn: sqlite3.Connection | None = None

    # -- lifecycle -------------------------------------------------------------------
    def prepare(self) -> None:
        had_index = self.db_path.exists()
        try:
            result = fetch_dataset(
                self.settings.regie_url, self.csv_path, self.settings.dataset_max_age_days, self.session
            )
            if result.changed or not had_index:
                n = build_index(self.csv_path, self.db_path)
                log.info("regie: indexed %d films", n)
        except Exception as exc:
            if had_index:
                log.warning("regie: refresh failed (%s); using existing index", exc)
            else:
                raise DatasetUnavailable(
                    f"regie: cannot download dataset and no cached index: {exc}"
                ) from exc
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        meta = read_meta(self.csv_path)
        log.info("regie: dataset last-modified %s", meta.get("last_modified", "unknown"))

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    # -- matching --------------------------------------------------------------------
    def resolve(self, item: Item) -> Candidate | None:
        if self.conn is None:
            raise RuntimeError("regie: prepare() not called")
        if item.year is None:
            return None
        return self._lookup(item)

    def _lookup(self, item: Item) -> Candidate | None:
        assert self.conn is not None
        keys = {k for k in (match_key(item.original_title), match_key(item.title)) if k}
        if not keys:
            return None
        placeholders = ",".join("?" * len(keys))
        params = list(keys) * 3
        rows = self.conn.execute(
            f"SELECT * FROM films WHERE (key_titre IN ({placeholders}) OR key_en IN ({placeholders})"
            f" OR key_fr IN ({placeholders})) AND annee IS NOT NULL",
            params,
        ).fetchall()
        rows = [r for r in rows if abs(r["annee"] - item.year) <= 1]
        if not rows:
            return None
        if len(rows) > 1 and item.directors:
            rows = [r for r in rows if directors_match(item.directors, json.loads(r["directors"]))]
        if len(rows) > 1:
            # the same film classified more than once (re-release, new version): one answer
            distinct = {(r["key_titre"], r["key_fr"], r["annee"], r["directors"]) for r in rows}
            if len(distinct) == 1:
                rows = rows[:1]
        if len(rows) != 1:
            log.debug("regie: ambiguous (%d rows) for %s (%s)", len(rows), item.title, item.year)
            return None
        return self._candidate(rows[0], item)

    def _candidate(self, row: sqlite3.Row, item: Item) -> Candidate | RegistryRejection | None:
        ref = f"no_film={row['no_film']}"
        record = RegistryRecord(
            ref, row["titre"] or "", row["titre_fr"] or "", row["annee"], row["url"] or ""
        )
        raw_fr = (row["titre_fr"] or "").strip()
        if has_dubbed_version_suffix(raw_fr):
            return self._dubbed_row(row, record, raw_fr)
        titre_fr = clean_registry_title(raw_fr)
        if not titre_fr:
            # No French title on file. Only the opt-in strict reading makes that a confirmation
            # of the original title.
            if not self.settings.regie_original_title_confirmation:
                return None
            original = clean_registry_title(row["titre"]) or item.original_title or item.title
            return Candidate(
                original,
                self.name,
                True,
                f"{ref}; released under original title",
                ref=ref,
                needs_corroboration=True,
                record=record,
            )
        return Candidate(titre_fr, self.name, True, ref, ref=ref, needs_corroboration=True, record=record)

    def _dubbed_row(
        self, row: sqlite3.Row, record: RegistryRecord, raw_fr: str
    ) -> Candidate | RegistryRejection:
        """'<X> (V.F.)': the French version was released under title X. Discriminate on X.

        - X equals TITRE or TITRE_ANGLAIS (case/diacritics-insensitive, no article handling):
          the film was released under that title -> candidate X, still subject to
          corroboration. Rows older than REGIE_CONFIRM_MIN_YEAR are not trusted (early records
          file the dub under the English title) and go to review as ambiguous.
        - X differs only by a leading/trailing article ('ABYSS' vs 'ABYSS, THE'): ambiguous.
        - Otherwise X is a distinct dubbed title ('WW84'): dubbed version, never a candidate.
        """
        x_raw = strip_version_suffix(raw_fr)
        x = norm(x_raw)
        originals = [
            norm(strip_language_suffix(row["titre"])),
            norm(strip_version_suffix(strip_language_suffix(row["titre_en"]))),
        ]
        if x and x in originals:
            year = row["annee"]
            if year is None or year < self.settings.regie_confirm_min_year:
                return RegistryRejection(
                    self.name, "registry-original-ambiguous", record, candidate_title=x_raw
                )
            return Candidate(
                clean_registry_title(raw_fr),
                self.name,
                True,
                f"{record.ref}; released under original title (V.F.)",
                ref=record.ref,
                needs_corroboration=True,
                record=record,
                bucket="registry-original-confirmed",
            )
        if x and strip_articles(x_raw) in {strip_articles(o) for o in originals}:
            return RegistryRejection(self.name, "registry-original-ambiguous", record, candidate_title=x_raw)
        return RegistryRejection(self.name, "registry-dubbed-version", record, candidate_title=x_raw)

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from plex_regional_titles.config import Settings
from plex_regional_titles.models import Candidate, Item, Kind
from plex_regional_titles.sources.base import TitleSource


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        plex_url="http://plex.test:32400",
        plex_token="token",
        libraries=["Films"],
        config_dir=tmp_path / "config",
    )
    s.cache_dir.mkdir(parents=True)
    return s


def make_item(
    title: str,
    original: str | None = None,
    year: int | None = 2000,
    imdb: str | None = "tt0000001",
    tmdb: str | None = None,
    kind: Kind = Kind.MOVIE,
    directors: list[str] | None = None,
    locked: bool = False,
    library: str = "Films",
) -> Item:
    return Item(
        rating_key="1",
        library=library,
        kind=kind,
        title=title,
        original_title=original,
        year=year,
        directors=directors or [],
        imdb_id=imdb,
        tmdb_id=tmdb,
        title_locked=locked,
    )


class StaticSource(TitleSource):
    """Test source returning a fixed candidate."""

    def __init__(self, name: str, authoritative: bool, title: str | None, supports=None) -> None:
        self.name = name
        self.authoritative = authoritative
        self.title = title
        self.supports = supports or frozenset({Kind.MOVIE, Kind.SHOW})
        self.calls = 0

    def resolve(self, item: Item) -> Candidate | None:
        self.calls += 1
        if self.title is None:
            return None
        return Candidate(self.title, self.name, self.authoritative)


REGIE_HEADER = (
    "NO_FILM;TITRE;TITRE_FRANCAIS;TITRE_ANGLAIS;REALISATEUR1;REALISATEUR2;REALISATEUR3;"
    "NATION1;NATION2;NATION3;ANNEE;CLASSEMENT;INDICATION_1;INDICATION_2;DATE_DECISION;NO_FILM_1;URL"
)


def regie_row(no, titre, fr, en, annee, d1="", d2="", d3=""):
    return (
        f"{no};{titre};{fr};{en};{d1};{d2};{d3};USA;;;{annee};G;;;2014-10-16;{no};"
        f"https://repertoire.cinema.mcc.gouv.qc.ca/film/{no}"
    )


REGIE_ROWS = [
    regie_row(
        250,
        "FALL OF THE ROMAN EMPIRE, THE",
        "CHUTE DE L'EMPIRE ROMAIN, LA ",
        "FALL OF THE ROMAN EMPIRE, THE ",
        1964,
        "MANN, ANTHONY",
    ),
    regie_row(106395, "G.I. JANE", "G.I. JANE (V.F.)", "G.I. JANE", 1997, "SCOTT, RIDLEY"),
    regie_row(
        149606, "ERIN BROCKOVICH", "ERIN BROCKOVICH (V.F.)", "ERIN BROCKOVICH", 2000, "SODERBERGH, STEVEN"
    ),
    regie_row(297550, "21", "21 (V.F.)", "21", 2008, "LUKETIC, ROBERT"),
    regie_row(32043, "RAMPAGE", "ENRAGE", "RAMPAGE", 1992, "FRIEDKIN, WILLIAM"),
    regie_row(409409, "RAMPAGE", "RAVAGES", "RAMPAGE", 2018, "PEYTON, BRAD"),
    regie_row(269007, "BLOODRAYNE", "", "BLOODRAYNE", 2005, "BOLL, UWE"),
    regie_row(1, "TWIN", "JUMEAU A", "TWIN", 2010, "SMITH, JOHN"),
    regie_row(2, "TWIN", "JUMEAU B", "TWIN", 2011, "DOE, JANE"),
    regie_row(3, "TWIN", "JUMEAU C", "TWIN", 2010, "SMITH, ANNA"),
    regie_row(4, "NOYEAR", "SANS ANNEE", "NOYEAR", "", "X, Y"),
    regie_row(5, "YULI (ESPAGNOL)", "", "YULI", 2018, "BOLLAIN, ICIAR"),
    regie_row(7, "AJEOSSI (COREEN)", "", "", 2010, "LEE JEONG-BEOM"),
    regie_row(6, "MULTI", "RESULTAT (V.O.F.) ", "MULTI", 1999, "A, B"),
]


def write_regie_csv(path: Path, rows=None) -> Path:
    body = "\r\n".join([REGIE_HEADER] + (REGIE_ROWS if rows is None else rows)) + "\r\n"
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    return path


AKAS_HEADER = "titleId\tordering\ttitle\tregion\tlanguage\ttypes\tattributes\tisOriginalTitle"
AKAS_ROWS = [
    "tt0000001\t1\tTitre France\tFR\tfr\timdbDisplay\t\\N\t0",
    "tt0000001\t2\tTitre Québec littéral\tCA\tfr\t\\N\tliteral title\t0",
    "tt0000001\t3\tTitre Québec\tCA\tfr\timdbDisplay\t\\N\t0",
    "tt0000001\t4\tTitre Canada anglais\tCA\ten\timdbDisplay\t\\N\t0",
    "tt0000001\t5\tOriginal Title\t\\N\t\\N\toriginal\t\\N\t1",
    "tt0000002\t1\tWorking Québec\tCA\tfr\tworking\t\\N\t0",
    "tt0000002\t2\tFinal Québec\tCA\tfr\t\\N\t\\N\t0",
    "tt0000003\t1\tOnly English CA\tCA\ten\timdbDisplay\t\\N\t0",
    "tt0000004\t1\tTitre Belgique\tBE\tfr\timdbDisplay\t\\N\t0",
    "tt0000005\t1\tJapanese\tJP\tja\timdbDisplay\t\\N\t0",
    "tt0000006\t1\tSecond Region\tFR\tfr\timdbDisplay\t\\N\t0",
]


def write_akas_gz(path: Path, rows=None) -> Path:
    body = "\n".join([AKAS_HEADER] + (AKAS_ROWS if rows is None else rows)) + "\n"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(body)
    return path

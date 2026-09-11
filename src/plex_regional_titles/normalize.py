"""Title normalisation shared by every comparison in the tool.

``norm``: NFKD, strip combining marks, lowercase, runs of non-alphanumerics to a
single space, trim.  ``uninvert_article`` turns registry-style
"CHUTE DE L'EMPIRE ROMAIN, LA" into "LA CHUTE DE L'EMPIRE ROMAIN".
``match_key`` combines both and is what sources use to compare titles.
"""

from __future__ import annotations

import re
import unicodedata

ARTICLES = ("le", "la", "les", "l'", "un", "une", "des", "the", "a", "an")

# ", LA" / ", L'" / ", L" (apostrophe sometimes lost in the data) at the end of a title.
# Some registries leave a dangling separator after the article: "FILM LEGO, LE -", "INTERVIEW QUI TUE, L' !"
_INVERTED_RE = re.compile(
    r"^(?P<body>.+?)\s*,\s*(?P<article>le|la|les|l'|l|un|une|des|the|a|an)\s*(?P<trail>[-–—:!?…]*)\s*$",
    re.IGNORECASE,
)

# Markers naming the *dubbed / original-language version* of the original title rather than a
# French title: (V.F.), (V.F), (V. F.), (V.A.), (V.O.A.), (V.O.A.S.-T.F.) ...  "(V.O.F.)" is not one:
# it marks an original French-language version, i.e. a genuine French title.
_DUBBED_SUFFIX_RE = re.compile(
    r"\(\s*(?:v\.?\s*f\.?|v\.?\s*a\.?|v\.?\s*o\.?\s*a\.?[a-z.\s-]*)\s*\)\s*$", re.IGNORECASE
)

# Parenthesised version markers appended to registry titles: (V.F.), (V.O.A.), (V.F), (FR.) ...
_VERSION_SUFFIX_RE = re.compile(
    r"\s*\(\s*(?:v\.?\s*o\.?\s*[a-z.\s-]*|v\.?\s*f\.?|v\.?\s*a\.?|fr\.?|s\.?\s*-?\s*t\.?\s*[a-z.]*)\s*\)\s*$",
    re.IGNORECASE,
)

# Language markers appended to the original-title column, e.g. "YULI (ESPAGNOL)".
_LANGUAGE_SUFFIX_RE = re.compile(
    r"\s*\(\s*(?:espagnol|anglais|allemand|italien|portugais|russe|japonais|chinois|coreen|"
    r"coréen|arabe|hindi|hébreu|hebreu|grec|turc|polonais|suedois|suédois|danois|norvegien|"
    r"norvégien|finnois|neerlandais|néerlandais|tcheque|tchèque|hongrois|roumain|persan|"
    r"thai|thaï|vietnamien|tagalog|ukrainien|catalan|islandais|croate|serbe|latin|yiddish|"
    r"bengali|tamoul|punjabi|ourdou|farsi|mandarin|cantonais|inuktitut|cri|innu)\s*\)\s*$",
    re.IGNORECASE,
)


_LIGATURES = str.maketrans(
    {
        "œ": "oe",
        "Œ": "OE",
        "æ": "ae",
        "Æ": "AE",
        "ß": "ss",
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
    }
)


def norm(value: str | None) -> str:
    """Case/accent/punctuation-insensitive comparison key."""
    s = unicodedata.normalize("NFKD", (value or "").translate(_LIGATURES))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


_ROMAN_TOKENS = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}
_PART_WORDS = {"partie", "part"}


def house_key(value: str | None) -> str:
    """``norm`` plus a house-style layer, used only for the "already correct" comparison.

    Equivalences: roman vs arabic sequel numbers (II/2 … X/10, standalone tokens only),
    "Partie N" / "Part N" / "N", and colon vs dash vs " - " as subtitle separators (which
    ``norm`` already collapses). It never changes what gets written, only whether the current
    title is considered already correct.
    """
    tokens = norm(value).split()
    out: list[str] = []
    for i, tok in enumerate(tokens):
        if tok in _ROMAN_TOKENS:
            tok = _ROMAN_TOKENS[tok]
        if (
            tok in _PART_WORDS
            and i + 1 < len(tokens)
            and (tokens[i + 1].isdigit() or tokens[i + 1] in _ROMAN_TOKENS)
        ):
            continue
        out.append(tok)
    return " ".join(out)


def uninvert_article(value: str | None) -> str:
    """'CHUTE DE L'EMPIRE ROMAIN, LA' -> 'LA CHUTE DE L'EMPIRE ROMAIN'."""
    s = (value or "").strip()
    m = _INVERTED_RE.match(s)
    if not m:
        return s
    body, article = m.group("body").strip(), m.group("article")
    trail = m.group("trail").strip("-–—: ")  # keep '!' / '?' / '…', drop dangling separators
    if article.lower() in ("l'", "l"):
        return f"{article[0]}'{body}{trail}"
    return f"{article} {body}{trail}"


def strip_version_suffix(value: str | None) -> str:
    """Remove trailing '(V.F.)', '(V.O.A.)', '(V.F)', '(FR.)' style markers."""
    s = (value or "").strip()
    prev = None
    while prev != s:
        prev = s
        s = _VERSION_SUFFIX_RE.sub("", s).strip()
    return s


def strip_language_suffix(value: str | None) -> str:
    """Remove a trailing '(ESPAGNOL)' style language marker."""
    return _LANGUAGE_SUFFIX_RE.sub("", (value or "").strip()).strip()


def clean_registry_title(value: str | None) -> str:
    """Version suffix removed, article un-inverted. Casing untouched."""
    return uninvert_article(strip_language_suffix(strip_version_suffix(value)))


def match_key(value: str | None) -> str:
    """The key used to compare a title from any source with a Plex title."""
    return norm(clean_registry_title(value))


def has_dubbed_version_suffix(value: str | None) -> bool:
    """True for 'ABYSS (V.F.)', 'HUGO (V.F)', 'TITRE (V.O.A.)': the row names the dubbed or
    original-language version of the original title, not a French title."""
    return bool(_DUBBED_SUFFIX_RE.search((value or "").strip()))


def diacritics(value: str | None) -> int:
    """Number of combining marks in the NFD form: how 'properly rendered' a string is."""
    return sum(1 for ch in unicodedata.normalize("NFD", value or "") if unicodedata.combining(ch))


def is_stripped_variant(written: str, renderings: list[str]) -> str | None:
    """Return the rendering that ``written`` is a diacritic-stripped variant of, else None.

    A stripped variant normalises equal to a known rendering but carries fewer diacritics
    (e.g. 'Divise' vs 'Divisé'). Such a string must never be written.
    """
    key, n = norm(written), diacritics(written)
    best = None
    for r in renderings:
        if r and norm(r) == key and diacritics(r) > n and (best is None or diacritics(r) > diacritics(best)):
            best = r
    return best

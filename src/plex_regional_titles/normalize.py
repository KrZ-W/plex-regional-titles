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


_SMALL_WORDS = {
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "et",
    "a",
    "à",
    "au",
    "aux",
    "en",
    "un",
    "une",
    "d",
    "l",
    "ou",
    "sur",
    "sous",
    "dans",
    "par",
    "pour",
    "chez",
    "the",
    "of",
    "and",
    "in",
    "on",
    "to",
    "for",
    "or",
    "an",
    "at",
    "by",
    "vs",
}
_ROMAN_RE = re.compile(r"^(?=[ivxlc]+$)m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")


def _cap_word(word: str, first: bool) -> str:
    lw = word.lower()
    if not lw:
        return word
    # G.I., U.S.A., R.I.P.
    if re.fullmatch(r"(?:[a-z]\.)+[a-z]?\.?", lw):
        return lw.upper()
    if _ROMAN_RE.match(lw) and len(lw) > 1:
        return lw.upper()
    # d'artagnan / l'empire -> D'Artagnan / L'Empire ; first-position "L'" keeps capital
    m = re.match(r"^([dl])'(.+)$", lw)
    if m:
        head, rest = m.groups()
        rest = rest[:1].upper() + rest[1:]
        return (head.upper() if first else head) + "'" + rest
    if not first and lw in _SMALL_WORDS:
        return lw
    return lw[:1].upper() + lw[1:]


def title_case(value: str) -> str:
    """Best-effort casing for registries that publish titles in capitals.

    Only used when no cased donor (Plex, TMDB, IMDb) matches the registry title.
    Accents cannot be restored, which is why donors are preferred.
    """
    words = value.strip().split()
    out: list[str] = []
    first = True
    for w in words:
        # keep punctuation glued to the word
        m = re.match(r"^([\"'«(\[]*)(.*?)([\"'»)\]:;,.!?…-]*)$", w)
        lead, core, trail = m.groups() if m else ("", w, "")
        if not core:
            out.append(w)
            first = w in ("-", "–", "—", ":")
            continue
        out.append(lead + _cap_word(core, first) + trail)
        # a new "sentence" starts after ':' or ' - '
        first = bool(re.search(r"[:!?]$", trail)) or core == "-"
    return " ".join(out)

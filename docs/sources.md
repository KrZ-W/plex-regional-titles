# Title sources

Sources form an **ordered chain** (`SOURCES`, default `regie,tmdb,imdb`). For every
item the chain is walked in order and the **first source that returns a candidate
wins**; the run summary records which one. A source is either *authoritative* (its
answer is a decision) or a *fallback* (its answer may be noise and is subject to the
ambiguous same-title rule).

| Source | Kind | Authoritative | Needs | Movies | Shows |
|---|---|---|---|---|---|
| `regie` | regional registry (Québec) | yes | nothing (matches by title/year) | yes | no |
| `tmdb` | TMDB translations | yes | `TMDB_API_KEY`, tmdb id in Plex guids | yes | yes |
| `imdb` | IMDb akas | **no** | imdb id in Plex guids | yes | yes |

## 1. Régie du cinéma (Québec)

The Ministère de la Culture et des Communications du Québec (formerly the Régie du
cinéma) publishes the classification of every feature film shown in Québec as open
data: ~29 000 rows with the original title (`TITRE`), the French release title
(`TITRE_FRANCAIS`), the English title (`TITRE_ANGLAIS`), up to three directors
(`REALISATEUR1..3`, as `SURNAME, GIVEN`), the year (`ANNEE`), the registry id
(`NO_FILM`) and a URL to the registry entry.

The tool downloads the CSV (semicolon-delimited, UTF-8 with BOM) with conditional
requests and indexes it in SQLite under `/config/cache/regie.sqlite`.

### Matching

The registry has no IMDb or TMDB ids, so matching is textual and deliberately strict:

1. Normalise the Plex item's `originalTitle` and `title` (see the README) and look
   them up against the normalised `TITRE`, `TITRE_ANGLAIS` and `TITRE_FRANCAIS`
   columns. Inverted articles (`FALL OF THE ROMAN EMPIRE, THE`) and version markers
   (`(V.F.)`, `(V.O.A.)`, `(V.O.F.)`, `(FR.)`) are handled.
2. Keep rows whose year is within **±1** of the Plex year (release years differ by
   country and by source). An item without a year never matches.
3. If more than one row remains, keep rows whose director surname matches one of the
   Plex item's directors.
4. Require **exactly one** row. Anything else is *no hit* and the chain moves on.

### Semantics of a hit

- `TITRE_FRANCAIS` filled → that is the Québec title (e.g. `RAMPAGE` 1992 →
  `ENRAGE`, `INCREDIBLES, THE` → `LES INCROYABLE`).
- `TITRE_FRANCAIS` empty on a matched row → **no hit** by default; the chain continues
  with TMDB / IMDb. The registry classifies the *submitted version*: an empty French
  title usually means the distributor submitted an original-version-only screening
  (*The Darjeeling Limited* played in Québec in English only, yet the French title
  *À bord du Darjeeling Limited* is the one in use on video and streaming). It does not
  prove the film was released under its original title.

  `REGIE_ORIGINAL_TITLE_CONFIRMATION=true` selects the stricter reading: such a row
  confirms the original title, as written in the registry's `TITRE` column (the market
  original, e.g. `AJEOSSI`, not the native-script title Plex may hold as
  `originalTitle`), and it is applied and locked if it differs from the current title.

Either way the answer is authoritative: it can never land in the ambiguous
same-title rule. That is why the registry settles the case IMDb cannot — a Plex item
showing *À armes égales* (France) whose registry row says `G.I. JANE (V.F.)` is
confidently renamed back to *G.I. Jane*.

### Casing

The registry publishes titles in capitals, mostly without accents, and with its own
house style for numbering and subtitles (`BEETHOVEN II`, `RETOUR VERS LE FUTUR PARTIE II`,
`LE FLIC DE BEVERLY HILLS 02`). Numbering differences are *not* normalised away, so a
Plex title that differs from the registry only in that respect is rewritten to the
registry's form; add an override if you prefer yours. The registry
decides *which* title is right; the *cased* text is borrowed from the first of these
that normalises equal to the registry title: the Plex title, the Plex original title,
then the candidates of the sources further down the chain (TMDB, IMDb). If none
matches, a French title-casing heuristic is applied and the decision is logged with
`casing=heuristic`; such titles lose their accents, so an override is the fix when
it matters.

## 2. TMDB translations

With `TMDB_API_KEY` set, the tool asks TMDB for the translations of the item's tmdb id
(`/movie/{id}/translations` or `/tv/{id}/translations`) and takes the first non-empty
title for `LANGUAGE` + a region in `REGIONS` order (e.g. `fr-CA`). Responses are cached
in `/config/cache/tmdb.sqlite` for `DATASET_MAX_AGE_DAYS`. TMDB is treated as
authoritative because its regional translation is a curated field, not an alias list.

## 3. IMDb akas (fallback)

`title.akas.tsv.gz` (~500 MB) is downloaded with `If-None-Match` /
`If-Modified-Since`, stream-parsed, and only rows with a region in `REGIONS` or a
language equal to `LANGUAGE` are kept in `/config/cache/imdb-akas.sqlite`. The index is
built into a temporary file and atomically replaces the previous one; a failure keeps
the old index.

Candidate selection for an item: for each region in `REGIONS` order, take the rows for
that region with language `LANGUAGE`, skip rows whose `attributes` contain `literal`
(literal translations are not release titles) and rows typed `working`, prefer a row
typed `imdbDisplay`, otherwise the lowest `ordering`.

IMDb akas are a fallback because the list mixes release titles, DVD titles, festival
titles and mistakes, and because "aka equals the original title" carries no
information about whether the region *kept* the original title. Those cases go through
`SAME_TITLE_MODE`.

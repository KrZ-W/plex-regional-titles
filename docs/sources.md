# Title sources

Sources form an **ordered chain** (`SOURCES`, default `regie,tmdb,imdb`). For every
item the chain is walked in order and the **first source that returns a candidate
wins**; the run summary records which one. A source is either *authoritative* (its
answer is a decision) or a *fallback* (its answer may be noise and is subject to the
ambiguous same-title rule).

| Source | Kind | Authoritative | Needs | Movies | Shows |
|---|---|---|---|---|---|
| `regie` | regional registry (Québec), corroborated by the others | yes | nothing (matches by title/year) | yes | no |
| `tmdb` | TMDB translations | yes | `TMDB_API_KEY`, tmdb id in Plex guids | yes | yes |
| `imdb` | IMDb akas | **no** | imdb id in Plex guids | yes | yes |

## 1. Régie du cinéma (Québec) — a corroborating source

The Ministère de la Culture et des Communications du Québec (formerly the Régie du
cinéma) publishes the classification of every feature film shown in Québec as open
data: ~29 000 rows with the title submitted for classification (`TITRE`), the French
release title (`TITRE_FRANCAIS`), the English title (`TITRE_ANGLAIS`), up to three
directors (`REALISATEUR1..3`, as `SURNAME, GIVEN`), the year (`ANNEE`), the registry id
(`NO_FILM`) and a URL to the registry entry.

**What the registry is.** A record of what was classified and released in Québec, kept
in an internal house style: capitals, no diacritics, inverted articles
(`CHUTE DE L'EMPIRE ROMAIN, LA`), `2IEME PARTIE`, `02`. `TITRE_FRANCAIS` is the string a
distributor submitted for the version they distributed. When the France dub was that
version, the registry holds the France title: *Bridesmaids* is filed as
`MES MEILLEURES AMIES` where Québec used *Demoiselles d'honneur*; *Lock, Stock and Two
Smoking Barrels* as `ARNAQUES, CRIMES ET BOTANIQUE` where Québec used *Arnaques, combines
et botanique*.

**What it is not.** The authority on how a title is displayed. Editorial sources
(cinoche.com, Mediafilm) carry the marketing titles the public saw; they are out of scope
for this tool, which only uses machine-readable, licensed data.

So the registry is a **corroborator**: a registry hit tells the tool *which* of the
strings it already knows is the Québec title, and it never supplies the written string
itself.

### Matching a row

The registry has no IMDb or TMDB ids, so matching is textual and strict:

1. Normalise the Plex item's `originalTitle` and `title` and look them up against the
   normalised `TITRE`, `TITRE_ANGLAIS` and `TITRE_FRANCAIS` columns (inverted articles and
   version markers are handled).
2. Keep rows whose year is within **±1** of the Plex year. An item without a year never
   matches.
3. If more than one row remains, keep rows whose director surname matches one of the Plex
   item's directors; identical duplicate classifications count as one.
4. Require **exactly one** row. Anything else is *no hit* and the chain moves on.

### From a row to a candidate

- `TITRE_FRANCAIS` is `<X> (V.F.)` (or `(V.F)`, `(V. F.)`, `(V.A.)`, `(V.O.A.)` …): the
  French (or original-language) version was released under title X. What that means
  depends on X, compared with `TITRE` and `TITRE_ANGLAIS` case- and
  diacritics-insensitively, with no article handling:
  - X equals the original title (`G.I. JANE (V.F.)`, `ZOMBIELAND (V.F.)`, `PONYO (V.F.)`
    against `TITRE_ANGLAIS`) → the film was released under that title. X is the
    candidate, subject to corroboration like any other (the Plex original title is the
    usual corroborator). Counted as `registry-original-confirmed`. Rows older than
    `REGIE_CONFIRM_MIN_YEAR` (default 1990) are not trusted, because early records file
    the dub under the English title (`FROM RUSSIA WITH LOVE (V.F.)` for *Bons baisers de
    Russie*); they go to review as `registry-original-ambiguous`.
  - X differs from the original title only by a leading or trailing article
    (`ABYSS (V.F.)` against `ABYSS, THE`) → ambiguous: no candidate, queued as
    `registry-original-ambiguous`.
  - X is a distinct title (`WW84 (V.F.)`, `EUROPEAN VACATION (V.F.)`) → the row names a
    distinct dubbed title: no candidate, queued as `registry-dubbed-version`.

  This path is independent of `REGIE_ORIGINAL_TITLE_CONFIRMATION`. `(V.O.F.)` marks an
  original French-language film and is a French title.
- `TITRE_FRANCAIS` empty → **no hit** by default; the chain continues with TMDB / IMDb.
  With `REGIE_ORIGINAL_TITLE_CONFIRMATION=true` the stricter reading applies: the row
  confirms the original title (`TITRE`), which is then a candidate subject to
  corroboration like any other.
- Otherwise the cleaned `TITRE_FRANCAIS` is the candidate, subject to corroboration.

### Corroboration (the rule that decides what gets written)

A registry candidate is written only when an **independently sourced, properly
rendered** string normalises equal to it and carries at least as many diacritics.
Checked in this order:

1. the current Plex title,
2. the Plex original title,
3. the TMDB `LANGUAGE-REGION` translation (when the `tmdb` source is configured),
4. any IMDb aka row for the id (when the `imdb` source is configured).

The **written value is that string**, never the registry's. If nothing corroborates, the
registry yields nothing for the item, the chain continues, and the row is queued in
`/config/state/would-apply-review.csv` with reason `registry-uncorroborated`, carrying the
raw `TITRE` / `TITRE_FRANCAIS`, year, `NO_FILM`, the current title and the regional akas
seen. A human or an external tool adjudicates that file; decisions come back through
`overrides.yaml`.

Consequences: a Québec title that no other source renders properly is not written (it
would otherwise arrive in capitals without accents); a France title that slipped into the
registry is not written unless some source renders it, in which case the item is at least
as well served as by that source alone.

### Diacritic guard

Whatever the source, a candidate that is a diacritic-stripped variant of a known rendering
of the same title (`Divise` where an aka row says `Divisé`) is replaced by the best
rendering before the cascade, and the runner refuses to write one should it ever get
through (counted as an error). Overrides are exempt: they are human decisions.

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

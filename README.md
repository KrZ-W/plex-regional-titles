# plex-regional-titles

A small scheduled tool that sets the **title** of Plex movies and shows to the
**regional release title** and **locks** the field so Plex agents cannot revert it.
Built for Québec French (`fr-CA`) first; the region, language and title sources are
configuration.

Image: `ghcr.io/krz-w/plex-regional-titles` (amd64, arm64).

## Why

Plex's metadata agents know one French: France French. A library set to French
gets *À armes égales* for *G.I. Jane* and *Las Vegas 21* for *21*, even though the
film played in Québec under its original title, and *Hugo Cabret* where Québec
released *Hugo*. There is no per-library `fr-CA` option, and every refresh brings
the France title back. The only durable mechanism Plex offers is **locking the
field**, which is exactly what this tool does: resolve the regional title, write
it, lock it, repeat on a schedule for new items.

The hard case is a film that *kept its original title* in the region. IMDb's
akas cannot tell "kept the English title" apart from "a junk English aka", so a
plain aka-based script has to hold those back. The Québec government's film
classification registry (Régie du cinéma, now Ministère de la Culture) records
what was classified and released in Québec. It is used as a **corroborator**: it
decides which of the properly rendered strings the tool already knows (Plex,
TMDB, IMDb) is the Québec title, but its own house-style strings are never
written. See [docs/sources.md](docs/sources.md).

## Quick start

```yaml
services:
  plex-regional-titles:
    image: ghcr.io/krz-w/plex-regional-titles:latest
    restart: unless-stopped
    environment:
      PLEX_URL: "http://plex:32400"
      PLEX_TOKEN: "xxxxxxxxxxxxxxxxxxxx"
      PLEX_LIBRARIES: "Films en français,Séries en français"
      TMDB_API_KEY: ""          # optional, enables the tmdb source
      SCHEDULE: "30 4 * * *"
      TZ: "America/Toronto"
      DRY_RUN: "true"           # look first; set to false when happy
    volumes:
      - ./config:/config
```

```sh
docker compose up -d && docker compose logs -f
```

Read the summary in the log or `config/state/last-run.json`, then set `DRY_RUN`
to `false`. A one-shot run is `docker compose run --rm plex-regional-titles once`
(or `SCHEDULE=once`).

The first run downloads the datasets it needs (the IMDb akas file is ~500 MB
compressed and takes a few minutes to index; the Régie CSV is ~5 MB). They are
cached under `/config/cache` and refreshed with conditional requests every
`DATASET_MAX_AGE_DAYS`.

## Settings

All configuration is by environment variable.

| Variable | Default | Meaning |
|---|---|---|
| `PLEX_URL` | *(required)* | Plex server URL, e.g. `http://plex:32400`. |
| `PLEX_TOKEN` | *(required)* | Plex token ([how to find it](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)). |
| `PLEX_LIBRARIES` | *(required)* | Comma-separated library **names**. Movie and show libraries. Shows are handled at series level; seasons and episodes are never touched. Unlisted libraries are never touched. |
| `REGIONS` | `CA` | Ordered ISO 3166-1 alpha-2 region codes. First region wins. |
| `LANGUAGE` | `fr` | ISO 639-1 language code. |
| `SOURCES` | `regie,tmdb,imdb` | Ordered chain; any subset. `regie` (Québec registry, movies only), `tmdb` (needs `TMDB_API_KEY`), `imdb`. |
| `TMDB_API_KEY` | *(unset)* | TMDB API key (v3). Without it the `tmdb` source is skipped with a warning. |
| `SAME_TITLE_MODE` | `skip` | `skip` or `review`. What to do when a **fallback** (IMDb) candidate equals the item's original title. See below. |
| `SCHEDULE` | `30 4 * * *` | Cron expression for the in-process scheduler, or `once` to run and exit. |
| `DATASET_MAX_AGE_DAYS` | `7` | How old a cached dataset may be before an upstream check (ETag / Last-Modified). |
| `WRITE_RATE` | `5` | Maximum Plex title writes per second. |
| `DRY_RUN` | `false` | Decide and report, write nothing. |
| `LOG_LEVEL` | `INFO` | `DEBUG` logs every item's decision. |
| `TZ` | `UTC` | Time zone for the schedule and log timestamps. |
| `PUID` / `PGID` | `1000` / `1000` | User and group the process runs as. |
| `UMASK` | `022` | umask for files created in `/config`. |
| `PLEX_VERIFY_SSL` | `true` | Set to `false` for a self-signed HTTPS Plex certificate. |
| `PLEX_TIMEOUT` | `60` | Plex request timeout, seconds. |
| `CONFIG_DIR` | `/config` | Where config, cache, state and log live. |
| `REGIE_DATASET_URL` | Données Québec CSV | Override the registry CSV URL. |
| `REGIE_ORIGINAL_TITLE_CONFIRMATION` | `false` | Stricter reading of the registry: a row with an empty French title confirms the original title. Off by default because the registry classifies the *submitted version*, and an empty French title often means an original-version-only screening (Darjeeling Limited), not a release under the original title. With it off such rows are no hit and the chain continues. |
| `IMDB_AKAS_URL` | `https://datasets.imdbws.com/title.akas.tsv.gz` | Override the IMDb dataset URL. |

### The `/config` volume

| Path | Purpose |
|---|---|
| `exclusions.txt` | One id per line (`tt…` or `tmdb:…`, `#` comments). Never touched. |
| `overrides.yaml` | `id: "Title"` mapping. Written and locked as-is; beats every source. |
| `review.csv` | Written when `SAME_TITLE_MODE=review`: ambiguous items with current title, candidate, ids and source. Never applied. |
| `cache/` | Downloaded datasets, SQLite indexes, TMDB response cache. Safe to delete. |
| `state/last-run.json` | Summary of the last run (used by the container healthcheck). |
| `state/would-apply-review.csv` | Registry hits that were not written (`registry-uncorroborated`, `registry-dubbed-version`) with the raw registry row, year, `NO_FILM`, current title and regional akas. Adjudicate here; answer through `overrides.yaml`. |
| `state/would-apply.csv` | Written when `DRY_RUN=true` or `SAME_TITLE_MODE=review`: one row per would-be title write (ids, current title, candidate, source, registry reference, cascade step). Review it before the first live run. |
| `examples/` | Seed curation files copied in by the image at start (`exclusions.quebec.txt`, `overrides.quebec.yaml`). Never loaded automatically. |
| `log/` | Rotating log file. |

Examples are in [`config-example/`](config-example/).

## The per-item cascade

For every item in every listed library, in this order:

1. **Excluded** – IMDb or TMDB id listed in `exclusions.txt` → skip.
2. **Overridden** – id in `overrides.yaml` → write that title and lock (skipped when already exactly that title and locked).
3. **Resolve** – ask the sources in `SOURCES` order; the first hit wins and is recorded as the source. A registry hit counts only when corroborated by the current title, the original title, a TMDB translation or an IMDb aka (in that order); the corroborating string is what gets written. Uncorroborated and dubbed-version rows go to `state/would-apply-review.csv`.
4. **Already correct** – candidate normalises equal to the current Plex title → skip. A second, *house-style* comparison also counts as already correct (reported as `house-style-equivalent`): roman vs arabic sequel numbers (`II`/`2` … `X`/`10`, standalone tokens only), `Partie N` / `Part N` / `N`, and colon vs dash as subtitle separators. A real subtitle difference (*Aliens* vs *Aliens, le Retour*) is not house style and is applied.
5. **Ambiguous** – candidate came from the IMDb fallback **and** normalises equal to the item's original title → apply `SAME_TITLE_MODE`. Authoritative sources (a registry, TMDB) never reach this rule: their confirmation *is* the decision.
6. **Apply** – write the title and lock it.

Normalisation for every comparison: NFKD, combining marks stripped, lowercase,
runs of non-alphanumerics collapsed to one space, trimmed. Registry-style
inverted articles (`CHUTE DE L'EMPIRE ROMAIN, LA`) are un-inverted first.

### `SAME_TITLE_MODE`

An IMDb `fr-CA` aka that equals the original title can mean two things: the film
really was released under its original title in Québec (*Moana*, *Creed*), or the
aka is noise. Because the tool cannot tell, it never applies such a candidate on
its own:

- `skip` (default): count it as `same-title-skipped` and move on.
- `review`: also write the item to `/config/review.csv` so you can decide. Put
  the id in `overrides.yaml` (with the original title) to apply it, or in
  `exclusions.txt` to silence it.

With the Régie source enabled, most Québec movies never get here: the registry
either gives a French title or confirms the original one.

### Seeding from the Québec examples

The image copies `exclusions.quebec.txt` and `overrides.quebec.yaml` into
`/config/examples/` at every start. They hold the ids and titles curated for a
Québec library (known-bad IMDb akas, films that kept their English title). They
are never loaded on their own; on first run copy what you want:

```sh
cp config/examples/exclusions.quebec.txt config/exclusions.txt
cp config/examples/overrides.quebec.yaml config/overrides.yaml
```

then run once with `DRY_RUN=true` and read `config/state/would-apply.csv`.

### Correcting a title

- Wrong regional title from a source → add `tt…: "Right title"` to `overrides.yaml`.
- Current title is right, sources disagree → add the id to `exclusions.txt`.

Both files are re-read at every run; no restart needed.

## Run summary

Every run logs a per-library line and writes `state/last-run.json`:

```
[Films en français] scanned=2143 applied=3 (regie=2, imdb=1) already-correct=1980 excluded=12
  overridden=40 same-title-skipped=61 same-title-reviewed=0 no-candidate=42 no-ids=5 errors=0
  | resolved-by-source: imdb=812, regie=1274
```

Counters: `scanned`, `applied` (with a by-source breakdown), `already_correct`,
`house_style_equivalent` (subset of already-correct decided by the house-style rule), `registry_uncorroborated`, `registry_dubbed_version`, `excluded`, `overridden`, `same_title_skipped`, `same_title_reviewed`,
`no_candidate`, `no_ids`, `errors`, plus `resolved_by_source` (which source
produced the candidate, whatever the outcome).

Exit codes: `0` ok, `1` configuration error, `2` Plex authentication / connection
failure, `3` a dataset could not be downloaded and no cached index exists for an
enabled source, `4` errors during the run (see log). Runs are idempotent: a
second run immediately after applies zero changes.

## Coexistence with Kometa (Plex Meta Manager)

Kometa can also edit and lock titles through metadata files. Do not let both
tools manage the same field on the same items: either exclude those ids here, or
leave the `title` operation out of Kometa for these libraries. Everything else
Kometa does (collections, posters, overlays, other locked fields) is unaffected,
since this tool only ever writes the `title` field.

## Data sources and licences

- **Régie du cinéma / Ministère de la Culture et des Communications du Québec** –
  "Classement des longs métrages diffusés sur le territoire québécois", on
  [Données Québec](https://www.donneesquebec.ca/recherche/dataset/classement-des-long-metrages-diffuses-sur-le-territoire-quebecois),
  under the [Licence ouverte Données Québec (CC BY 4.0)](https://www.donneesquebec.ca/licence/).
- **IMDb non-commercial datasets** – `title.akas.tsv.gz`, downloaded **at runtime
  onto your own machine** and never redistributed by this project. Use is subject
  to [IMDb's non-commercial licensing terms](https://developer.imdb.com/non-commercial-datasets/);
  personal, non-commercial use only.
- **TMDB** – optional, with your own API key, under the
  [TMDB API terms of use](https://www.themoviedb.org/api-terms-of-use). This
  product uses the TMDB API but is not endorsed or certified by TMDB.

## Documentation

- [docs/sources.md](docs/sources.md) – each source, how it matches, and why the registry settles the "kept the English title" case.
- [docs/configuration.md](docs/configuration.md) – every setting in detail, examples for other regions.
- [docs/adding-a-registry.md](docs/adding-a-registry.md) – how to add another regional registry.
- [docs/operations.md](docs/operations.md) – scheduling, healthcheck, cache, exit codes, troubleshooting.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests && pytest
docker buildx build --platform linux/amd64,linux/arm64 -t plex-regional-titles .
```

Tests need neither network nor Plex.

## Licence

MIT – see [LICENSE](LICENSE).

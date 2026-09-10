# Configuration reference

Everything is an environment variable; see the table in the README for defaults.
This page adds the details and worked examples.

## Regions, language and the source chain

`REGIONS` is ordered. For `REGIONS=CA,FR` and `LANGUAGE=fr` the TMDB source tries
`fr-CA` then `fr-FR`, and the IMDb source prefers a `fr` aka for `CA`, then for `FR`.
The Régie source is Québec-specific and ignores `REGIONS`; keep it in `SOURCES` only
when your libraries hold Québec-market titles.

`SOURCES` is any ordered subset of the known sources. Examples:

| Goal | `SOURCES` | `REGIONS` | `LANGUAGE` |
|---|---|---|---|
| Québec French (default) | `regie,tmdb,imdb` | `CA` | `fr` |
| Québec, no IMDb download | `regie,tmdb` | `CA` | `fr` |
| Belgian French | `tmdb,imdb` | `BE,FR` | `fr` |
| Brazilian Portuguese | `tmdb,imdb` | `BR` | `pt` |
| Latin American Spanish | `tmdb,imdb` | `MX,AR` | `es` |

`REGIE_ORIGINAL_TITLE_CONFIRMATION=false` makes registry rows without a French title a
miss instead of a confirmation of the original title (see [sources.md](sources.md)).

If `SOURCES` names `tmdb` but `TMDB_API_KEY` is empty, the source is skipped with a
warning rather than failing the run.

## Schedule

`SCHEDULE` is a standard 5-field cron expression evaluated in `TZ` by an in-process
scheduler; the container stays up between runs. `SCHEDULE=once` runs immediately and
exits with the run's exit code, which suits an external scheduler
(`docker compose run --rm plex-regional-titles once`).

## Datasets

Datasets are checked upstream at most every `DATASET_MAX_AGE_DAYS`, with conditional
requests so an unchanged file costs one small request. A failed refresh keeps the
cached copy and index (warning in the log). A failed download with **no** cached index
for an enabled source aborts the run before any Plex write (exit code 3).

The Québec registry CSV is small and updates a few times a year; the IMDb file is
regenerated daily, so with the default 7 days you download ~500 MB weekly. Raise
`DATASET_MAX_AGE_DAYS` if bandwidth matters more than freshness.

## Writes

`WRITE_RATE` caps title writes per second (default 5). Each write is one Plex
`PUT` that sets `title.value` and `title.locked=1` — nothing else. `DRY_RUN=true`
performs every step except the write and reports `applied` as "would apply".

## Curation files

`exclusions.txt`:

```
# comments and blank lines are fine
tt0094761      # The Blob – keep the current title
tmdb:475557
```

`overrides.yaml`:

```yaml
tt1337057: "Le Forcené"
tmdb:146: "Crouching Tiger, Hidden Dragon"
```

Ids are matched against the item's IMDb id first, then its TMDB id. A parse error in
either file is a configuration error: the run stops before touching Plex.

## Permissions

The image starts as root only to align the `app` user with `PUID`/`PGID`, apply
`UMASK`, and make `/config/{cache,state,log}` writable; it then drops privileges with
`setpriv` before running Python. Run it with `user:` in compose if you prefer; then
make sure `/config` is writable by that user.

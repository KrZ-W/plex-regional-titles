# Operations

## Modes

| Command | Behaviour |
|---|---|
| `cron` (default) | Stay up, run at every `SCHEDULE` tick. With `SCHEDULE=once`, behaves like `once`. |
| `once` | One run, exit with the run's exit code. |
| `healthcheck` | Exit 0 when `state/last-run.json` exists, reports `status: ok` and is younger than twice the schedule interval (minimum one hour, plus grace). Used by the image `HEALTHCHECK`. |

Run them as `docker compose run --rm plex-regional-titles once`, or as a container
`command:`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Run completed, no errors. |
| 1 | Configuration error (message on stderr lists every problem). |
| 2 | Plex authentication or connection failure. In `cron` mode the process exits so the orchestrator surfaces it. |
| 3 | A dataset could not be downloaded and no cached index exists for an enabled source. Nothing was written. |
| 4 | Errors during the run (missing library, write failure, unexpected exception). Other items were still processed. |

## Logs and state

- stdout/stderr (Docker logs) and `/config/log/plex-regional-titles.log` (rotating,
  5 × 5 MB).
- `LOG_LEVEL=DEBUG` logs every item's decision with its candidate and source. `INFO`
  logs applied writes, ambiguous items and the summaries.
- `/config/state/last-run.json`: full summary of the last run (per-library counters,
  totals, sources, dry-run flag, status, timestamps).
- `/config/state/would-apply.csv`: every would-be write of the last dry run / review run.
- `/config/state/would-apply-review.csv`: registry hits the last run refused to write, for
  adjudication.
- `/config/examples/`: seed curation files, refreshed from the image at every start.

## Cache

`/config/cache` holds the Régie CSV and index, the IMDb akas file and index, the TMDB
response cache and small `*.meta.json` sidecars with ETag / Last-Modified. Delete the
directory to force a full re-download; delete only `*.sqlite` to force a re-index.
Indexes are rebuilt automatically when `REGIONS` / `LANGUAGE` change.

## Idempotency and safety

- A second run right after a successful run applies zero changes.
- Only the `title` field is written, always with `locked=1`. Summaries, sort titles,
  original titles, artwork, collections and every other field are never touched.
- Libraries not listed in `PLEX_LIBRARIES` are never read.
- Shows are edited at series level only.

## Troubleshooting

- *`library 'X' not found`* — names are exact (accents and spacing included). Check the
  Plex sidebar.
- *`SOURCES includes tmdb but TMDB_API_KEY is not set`* — either set the key or drop
  `tmdb` from `SOURCES`.
- *Many `no-ids`* — items without an IMDb or TMDB guid (unmatched in Plex). Fix the
  match in Plex.
- *A registry title I know is right was not applied* — look for it in
  `state/would-apply-review.csv`: `registry-uncorroborated` means no source renders that
  string properly, so add it to `overrides.yaml` with its accents; `registry-dubbed-version`
  means the row only named the dubbed version of the original title.
- *Kometa keeps changing titles back* — see the README section on Kometa.

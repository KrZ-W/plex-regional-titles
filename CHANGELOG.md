# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-09-10

### Changed
- `REGIE_ORIGINAL_TITLE_CONFIRMATION` now defaults to `false`: a registry row with an empty French
  title is a miss for that source and the chain continues. The registry classifies the submitted
  version, so an empty French title can mean an original-version-only screening rather than a
  release under the original title. Set it to `true` for the stricter reading.
- "Already correct" (cascade step 4) also accepts house-style equivalents: roman vs arabic sequel
  numbers (II/2 … X/10, standalone tokens), `Partie N` / `Part N` / `N`, colon vs dash separators.
  New counter `house_style_equivalent` in the summary.

### Added
- `/config/state/would-apply.csv` written on `DRY_RUN=true` or `SAME_TITLE_MODE=review`: one row per
  would-be write with ids, titles, source, source reference and the deciding cascade step.
- Québec seed files `examples/exclusions.quebec.txt` and `examples/overrides.quebec.yaml`, copied to
  `/config/examples/` at container start; never loaded automatically.

## [1.0.0] - 2026-09-10

### Added
- Scheduled tool that sets Plex movie and show titles to the regional release title and locks the field.
- Source chain: Régie du cinéma (Québec) registry, TMDB translations for `LANGUAGE-REGION`, IMDb akas fallback.
- Regional registry plugin interface (`RegionalRegistry`, `plex_regional_titles.registries` entry point).
- Per-item cascade with exclusions, overrides, already-correct detection and the ambiguous same-title rule
  (`SAME_TITLE_MODE=skip|review`).
- Conditional dataset downloads (ETag / Last-Modified), SQLite indexes with atomic replace.
- `REGIE_ORIGINAL_TITLE_CONFIRMATION` to opt out of treating registry rows without a French title as a
  confirmation of the original title.
- Run summary in `state/last-run.json` and the log; rate-limited writes; dry run.
- Docker image (`python:3.12-slim`, non-root, in-process cron, healthcheck, amd64/arm64), GitHub Actions
  CI, Dependabot.

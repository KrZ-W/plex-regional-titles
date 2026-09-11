# Adding another regional registry

A *regional registry* is an authoritative list of the titles films were released
under in a region — a government classification board, a distributors' database, a
national film archive. The Québec Régie du cinéma is the built-in one; others plug in
through the same interface.

## The interface

```python
from plex_regional_titles.models import Candidate, DatasetUnavailable, Item, Kind, RegistryRecord
from plex_regional_titles.sources import RegionalRegistry, register_registry


@register_registry            # in-tree registration; third-party packages use an entry point instead
class MyRegistry(RegionalRegistry):
    name = "myregistry"       # the token users put in SOURCES
    supports = frozenset({Kind.MOVIE})   # and/or Kind.SHOW

    def __init__(self, settings):
        super().__init__(settings)       # settings.cache_dir, settings.regions, settings.language, ...

    def prepare(self) -> None:
        """Download / refresh / index. Called once per run before any item.
        Raise DatasetUnavailable if nothing can be served (no download and no cache)."""

    def resolve(self, item: Item) -> Candidate | None:
        """Return the regional title for this item, or None when there is no confident hit.
        Never raise for an ordinary miss."""
        ...
        record = RegistryRecord("ref=123", raw_original, raw_regional, year)
        return Candidate(title, self.name, authoritative=True, note="ref=123", ref="ref=123",
                         needs_corroboration=True, record=record)

    def close(self) -> None:
        """Release handles."""
```

What you get on `Item`: `title`, `original_title`, `year`, `directors`, `imdb_id`,
`tmdb_id`, `tvdb_id`, `kind`, `library`. What you return: a `Candidate` with
`authoritative=True` (registries decide; the ambiguous same-title rule never applies to
them), `needs_corroboration=True` and a `RegistryRecord` (your raw row) so the chain can
corroborate the string against Plex / TMDB / IMDb and, failing that, queue the row in
`would-apply-review.csv`. Registries are corroborators: their own strings are never
written. Return a `RegistryRejection(name, "registry-dubbed-version", record)` for rows
that only name the dubbed version of the original title.

Helpers you should reuse:

- `plex_regional_titles.normalize.match_key` — the comparison key (normalisation +
  version-suffix stripping + article un-inversion).
- `plex_regional_titles.download.fetch_dataset` — conditional download with ETag /
  Last-Modified, atomic replace, cached fallback on failure.
- `plex_regional_titles.sources.regie.build_index` — a pattern for building a SQLite
  index atomically.

## Registering

- **In-tree**: decorate the class with `@register_registry` and import the module from
  `plex_regional_titles/sources/base.py::registry_classes` (see how `regie` is
  imported there).
- **Separate package**: declare an entry point in your `pyproject.toml`:

  ```toml
  [project.entry-points."plex_regional_titles.registries"]
  myregistry = "my_package.registry:MyRegistry"
  ```

  Install the package in the image (e.g. a derived Dockerfile with `pip install
  my-package`) and add `myregistry` to `SOURCES`.

## Matching advice

Registries rarely carry IMDb or TMDB ids. Match on the normalised original title **and**
year (±1), break ties with the director's surname, and require a unique row; return
`None` otherwise. False positives rename and lock the wrong title, false negatives only
fall through to the next source. Encode the "released under its original title"
semantics explicitly, as the Québec registry does with an empty French title: return
`Candidate(raw_original_title, ..., needs_corroboration=True, record=...)` behind an
opt-in setting, as `REGIE_ORIGINAL_TITLE_CONFIRMATION` does.

Add tests under `tests/` that build a small fixture of your registry's format and cover
unique match, year window, tiebreak, ambiguity → no hit, and the dataset-unavailable
path. The suite must stay network-free.

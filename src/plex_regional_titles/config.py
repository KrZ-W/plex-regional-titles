"""Settings from environment variables, validated up front."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from croniter import croniter

from plex_regional_titles.models import ConfigError

DEFAULT_SOURCES = ("regie", "tmdb", "imdb")
SAME_TITLE_MODES = ("skip", "review")
REGIE_DEFAULT_URL = (
    "https://www.donneesquebec.ca/recherche/dataset/"
    "classement-des-long-metrages-diffuses-sur-le-territoire-quebecois/"
    "resource/17f8a69b-acac-468a-ae85-6aa4d6d29929/download"
)
IMDB_AKAS_DEFAULT_URL = "https://datasets.imdbws.com/title.akas.tsv.gz"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(slots=True)
class Settings:
    plex_url: str
    plex_token: str
    libraries: list[str]
    regions: list[str] = field(default_factory=lambda: ["CA"])
    language: str = "fr"
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    tmdb_api_key: str | None = None
    same_title_mode: str = "skip"
    schedule: str = "30 4 * * *"
    dataset_max_age_days: int = 7
    write_rate: float = 5.0
    dry_run: bool = False
    log_level: str = "INFO"
    config_dir: Path = Path("/config")
    plex_verify_ssl: bool = True
    plex_timeout: int = 60
    regie_url: str = REGIE_DEFAULT_URL
    regie_original_title_confirmation: bool = True
    imdb_akas_url: str = IMDB_AKAS_DEFAULT_URL

    @property
    def cache_dir(self) -> Path:
        return self.config_dir / "cache"

    @property
    def state_dir(self) -> Path:
        return self.config_dir / "state"

    @property
    def log_dir(self) -> Path:
        return self.config_dir / "log"

    @property
    def exclusions_file(self) -> Path:
        return self.config_dir / "exclusions.txt"

    @property
    def overrides_file(self) -> Path:
        return self.config_dir / "overrides.yaml"

    @property
    def review_file(self) -> Path:
        return self.config_dir / "review.csv"

    @property
    def last_run_file(self) -> Path:
        return self.state_dir / "last-run.json"

    @property
    def run_once(self) -> bool:
        return self.schedule.strip().lower() == "once"

    @property
    def locale(self) -> str:
        """e.g. fr-CA for the first region."""
        return f"{self.language}-{self.regions[0]}"


def load_settings(env: dict[str, str] | None = None, known_sources: set[str] | None = None) -> Settings:
    """Build Settings from ``env`` (defaults to os.environ). Raises ConfigError listing problems."""
    e = dict(os.environ if env is None else env)
    problems: list[str] = []

    plex_url = e.get("PLEX_URL", "").strip()
    plex_token = e.get("PLEX_TOKEN", "").strip()
    if not plex_url:
        problems.append("PLEX_URL is required")
    elif not plex_url.startswith(("http://", "https://")):
        problems.append("PLEX_URL must start with http:// or https://")
    if not plex_token:
        problems.append("PLEX_TOKEN is required")

    libraries = _csv(e.get("PLEX_LIBRARIES", ""))
    if not libraries:
        problems.append("PLEX_LIBRARIES is required (comma-separated library names)")

    regions = [r.upper() for r in _csv(e.get("REGIONS", "CA"))]
    if not regions or any(len(r) != 2 or not r.isalpha() for r in regions):
        problems.append("REGIONS must be comma-separated ISO 3166-1 alpha-2 codes, e.g. CA,FR")

    language = e.get("LANGUAGE", "fr").strip().lower()
    if len(language) != 2 or not language.isalpha():
        problems.append("LANGUAGE must be an ISO 639-1 code, e.g. fr")

    sources = [s.lower() for s in _csv(e.get("SOURCES", ",".join(DEFAULT_SOURCES)))]
    known = known_sources if known_sources is not None else set(DEFAULT_SOURCES)
    unknown = [s for s in sources if s not in known]
    if not sources:
        problems.append("SOURCES must list at least one source")
    if unknown:
        problems.append(
            f"SOURCES contains unknown source(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}"
        )
    if len(set(sources)) != len(sources):
        problems.append("SOURCES lists a source more than once")

    tmdb_api_key = e.get("TMDB_API_KEY", "").strip() or None

    same_title_mode = e.get("SAME_TITLE_MODE", "skip").strip().lower()
    if same_title_mode not in SAME_TITLE_MODES:
        problems.append(f"SAME_TITLE_MODE must be one of {', '.join(SAME_TITLE_MODES)}")

    schedule = e.get("SCHEDULE", "30 4 * * *").strip()
    if schedule.lower() != "once" and not croniter.is_valid(schedule):
        problems.append(f"SCHEDULE must be a valid cron expression or 'once' (got {schedule!r})")

    def _int(name: str, default: int, minimum: int) -> int:
        raw = e.get(name, str(default)).strip()
        try:
            v = int(raw)
        except ValueError:
            problems.append(f"{name} must be an integer (got {raw!r})")
            return default
        if v < minimum:
            problems.append(f"{name} must be >= {minimum}")
        return v

    dataset_max_age_days = _int("DATASET_MAX_AGE_DAYS", 7, 1)
    plex_timeout = _int("PLEX_TIMEOUT", 60, 1)

    raw_rate = e.get("WRITE_RATE", "5").strip()
    try:
        write_rate = float(raw_rate.rstrip("/s").rstrip("/S"))
        if write_rate <= 0:
            problems.append("WRITE_RATE must be > 0")
    except ValueError:
        problems.append(f"WRITE_RATE must be a number of writes per second (got {raw_rate!r})")
        write_rate = 5.0

    log_level = e.get("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        problems.append("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")

    if problems:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))

    return Settings(
        plex_url=plex_url.rstrip("/"),
        plex_token=plex_token,
        libraries=libraries,
        regions=regions,
        language=language,
        sources=sources,
        tmdb_api_key=tmdb_api_key,
        same_title_mode=same_title_mode,
        schedule=schedule,
        dataset_max_age_days=dataset_max_age_days,
        write_rate=write_rate,
        dry_run=_bool(e.get("DRY_RUN", "false")),
        log_level=log_level,
        config_dir=Path(e.get("CONFIG_DIR", "/config")),
        plex_verify_ssl=_bool(e.get("PLEX_VERIFY_SSL", "true")),
        plex_timeout=plex_timeout,
        regie_url=e.get("REGIE_DATASET_URL", REGIE_DEFAULT_URL).strip() or REGIE_DEFAULT_URL,
        regie_original_title_confirmation=_bool(e.get("REGIE_ORIGINAL_TITLE_CONFIRMATION", "true")),
        imdb_akas_url=e.get("IMDB_AKAS_URL", IMDB_AKAS_DEFAULT_URL).strip() or IMDB_AKAS_DEFAULT_URL,
    )

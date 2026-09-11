"""Run summary: per-library counters, JSON state file and human-readable log block."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from plex_regional_titles.models import Decision, Outcome

COUNTER_FIELDS = (
    "scanned",
    "applied",
    "already_correct",
    "house_style_equivalent",
    "registry_uncorroborated",
    "registry_dubbed_version",
    "registry_original_confirmed",
    "registry_original_ambiguous",
    "excluded",
    "overridden",
    "same_title_skipped",
    "same_title_reviewed",
    "no_candidate",
    "no_ids",
    "errors",
)


@dataclass(slots=True)
class LibrarySummary:
    library: str
    kind: str = ""
    scanned: int = 0
    applied: int = 0
    applied_by_source: dict[str, int] = field(default_factory=dict)
    already_correct: int = 0
    house_style_equivalent: int = 0
    registry_uncorroborated: int = 0
    registry_dubbed_version: int = 0
    registry_original_confirmed: int = 0
    registry_original_ambiguous: int = 0
    excluded: int = 0
    overridden: int = 0
    same_title_skipped: int = 0
    same_title_reviewed: int = 0
    no_candidate: int = 0
    no_ids: int = 0
    errors: int = 0
    resolved_by_source: dict[str, int] = field(default_factory=dict)

    def record_rejection(self, reason: str) -> None:
        """Count a registry classification (rejection reason or candidate bucket)."""
        attr = reason.replace("-", "_")
        if attr in COUNTER_FIELDS:
            setattr(self, attr, getattr(self, attr) + 1)

    def record(self, decision: Decision) -> None:
        self.scanned += 1
        o = decision.outcome
        if decision.candidate and decision.candidate.source != "override":
            src = decision.candidate.source
            self.resolved_by_source[src] = self.resolved_by_source.get(src, 0) + 1
        if o == Outcome.APPLIED:
            self.applied += 1
            src = decision.source or "?"
            self.applied_by_source[src] = self.applied_by_source.get(src, 0) + 1
        elif o == Outcome.OVERRIDDEN:
            self.overridden += 1
            if decision.write:
                self.applied += 1
                self.applied_by_source["override"] = self.applied_by_source.get("override", 0) + 1
        elif o == Outcome.ALREADY_CORRECT:
            self.already_correct += 1
            if decision.house_style:
                self.house_style_equivalent += 1
        elif o == Outcome.EXCLUDED:
            self.excluded += 1
        elif o == Outcome.SAME_TITLE_SKIPPED:
            self.same_title_skipped += 1
        elif o == Outcome.SAME_TITLE_REVIEWED:
            self.same_title_reviewed += 1
        elif o == Outcome.NO_CANDIDATE:
            self.no_candidate += 1
        elif o == Outcome.NO_IDS:
            self.no_ids += 1
        elif o == Outcome.ERROR:
            self.errors += 1

    def human(self) -> str:
        by_src = ", ".join(f"{k}={v}" for k, v in sorted(self.applied_by_source.items())) or "-"
        res = ", ".join(f"{k}={v}" for k, v in sorted(self.resolved_by_source.items())) or "-"
        return (
            f"[{self.library}] scanned={self.scanned} applied={self.applied} ({by_src}) "
            f"already-correct={self.already_correct} (house-style={self.house_style_equivalent}) "
            f"excluded={self.excluded} "
            f"overridden={self.overridden} same-title-skipped={self.same_title_skipped} "
            f"same-title-reviewed={self.same_title_reviewed} no-candidate={self.no_candidate} "
            f"no-ids={self.no_ids} errors={self.errors} "
            f"registry-uncorroborated={self.registry_uncorroborated} "
            f"registry-dubbed-version={self.registry_dubbed_version} "
            f"registry-original-confirmed={self.registry_original_confirmed} "
            f"registry-original-ambiguous={self.registry_original_ambiguous} | resolved-by-source: {res}"
        )


@dataclass(slots=True)
class RunSummary:
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0.0
    dry_run: bool = False
    sources: list[str] = field(default_factory=list)
    locale: str = ""
    status: str = "ok"  # ok | error
    error: str = ""
    libraries: list[LibrarySummary] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)

    @classmethod
    def start(cls, dry_run: bool, sources: list[str], locale: str) -> RunSummary:
        return cls(
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            dry_run=dry_run,
            sources=list(sources),
            locale=locale,
        )

    def finish(self, status: str = "ok", error: str = "") -> None:
        end = datetime.now(UTC)
        self.finished_at = end.isoformat(timespec="seconds")
        self.duration_seconds = round((end - datetime.fromisoformat(self.started_at)).total_seconds(), 1)
        self.status = status
        self.error = error
        totals = {f: sum(getattr(lib, f) for lib in self.libraries) for f in COUNTER_FIELDS}
        applied_by_source: dict[str, int] = {}
        for lib in self.libraries:
            for k, v in lib.applied_by_source.items():
                applied_by_source[k] = applied_by_source.get(k, 0) + v
        self.totals = {**totals, "applied_by_source": applied_by_source}  # type: ignore[dict-item]

    def to_dict(self) -> dict:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def human(self) -> str:
        lines = [
            f"Run {'(DRY-RUN) ' if self.dry_run else ''}{self.started_at} -> {self.finished_at} "
            f"({self.duration_seconds}s) status={self.status} sources={','.join(self.sources)} "
            f"locale={self.locale}"
        ]
        lines += [lib.human() for lib in self.libraries]
        if self.totals:
            t = self.totals
            by_src = ", ".join(f"{k}={v}" for k, v in sorted(t.get("applied_by_source", {}).items())) or "-"
            lines.append(
                f"[total] scanned={t['scanned']} applied={t['applied']} ({by_src}) "
                f"already-correct={t['already_correct']} (house-style={t['house_style_equivalent']}) "
                f"excluded={t['excluded']} "
                f"overridden={t['overridden']} same-title-skipped={t['same_title_skipped']} "
                f"same-title-reviewed={t['same_title_reviewed']} no-candidate={t['no_candidate']} "
                f"no-ids={t['no_ids']} errors={t['errors']} "
                f"registry-uncorroborated={t['registry_uncorroborated']} "
                f"registry-dubbed-version={t['registry_dubbed_version']} "
                f"registry-original-confirmed={t['registry_original_confirmed']} "
                f"registry-original-ambiguous={t['registry_original_ambiguous']}"
            )
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)

"""Application contributor analysis (pure, Qt/ADB-free, NON-CAUSAL).

Ranks the already-resolved applications from the v0.8.1 Background User Apps
snapshot by how much observed load they carry during a pressure window.

This is **correlation ranking**, never causal inference:

* Only entries already present in :class:`BackgroundAppsSnapshot` are
  considered — the identity (process -> UID -> verified package -> label) was
  resolved upstream, so no UID / package / label / APK resolution happens here.
* System / protected applications are excluded: the snapshot is the verified
  user-app set, and any package in *excluded* is dropped explicitly.
* Unknown packages (empty name) are never fabricated into a named application.
* Wording is strictly observational ("observed contributor", "associated with
  the pressure window") — never "caused", "responsible for", or "guilty".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..background.models import BackgroundAppEntry, BackgroundAppsSnapshot


@dataclass(frozen=True)
class ContributorCandidate:
    """One ranked application, with non-causal association metadata."""

    package: str
    label: str | None
    cpu_percent: float | None
    memory_percent: float | None
    process_count: int | None
    state: str | None
    relevant_metric: str
    cpu_contribution: float
    memory_contribution: float
    total_contribution: float
    confidence: float
    reason: str


def _relevant_metric(
    pressure_metrics: Sequence[str], cpu: float | None, mem: float | None
) -> str:
    """Pick the pressure metric this app is associated with (non-causal)."""
    pressure = set(pressure_metrics)
    if "memory" in pressure and mem is not None:
        return "memory"
    if "cpu" in pressure and cpu is not None:
        return "cpu"
    if "process" in pressure:
        return "process"
    if pressure:
        return next(iter(pressure))
    return "process"


def rank_contributors(
    snapshot: BackgroundAppsSnapshot | None,
    *,
    pressure_metrics: Sequence[str] = (),
    excluded: set[str] | None = None,
    top_n: int = 5,
) -> tuple[ContributorCandidate, ...]:
    """Rank resolved user applications by observed load during the window.

    Returns the top ``top_n`` contributors. Entries are filtered for: a
    non-empty package name, absence from *excluded*, and at least one available
    cpu/memory observation. Confidence is the app's load share of the maximum
    observed load (0..1).
    """
    if snapshot is None or not snapshot.entries:
        return ()
    excluded = excluded or set()

    raw: list[tuple[BackgroundAppEntry, float | None, float | None, float, float, float]] = []
    max_total = 0.0
    for entry in snapshot.entries:
        package = entry.package_name
        if not package or package in excluded:
            continue
        cpu = entry.cpu_percent
        mem = entry.memory_percent
        if cpu is None and mem is None:
            # No observable load for this app; cannot rank it as a contributor.
            continue
        cpu_c = cpu or 0.0
        mem_c = mem or 0.0
        total = cpu_c + mem_c
        max_total = max(max_total, total)
        raw.append((entry, cpu, mem, cpu_c, mem_c, total))

    if not raw:
        return ()

    candidates: list[ContributorCandidate] = []
    for entry, cpu, mem, cpu_c, mem_c, total in raw:
        relevant = _relevant_metric(pressure_metrics, cpu, mem)
        confidence = round(total / max_total, 4) if max_total > 0 else 0.0
        candidates.append(ContributorCandidate(
            package=entry.package_name,
            label=entry.label,
            cpu_percent=cpu,
            memory_percent=mem,
            process_count=len(entry.pids),
            state=entry.state.value if entry.state else None,
            relevant_metric=relevant,
            cpu_contribution=cpu_c,
            memory_contribution=mem_c,
            total_contribution=total,
            confidence=confidence,
            reason=(
                f"Observed {relevant} contributor associated with the current "
                f"pressure window."
            ),
        ))

    candidates.sort(key=lambda c: c.total_contribution, reverse=True)
    return tuple(candidates[:top_n])


__all__ = ["ContributorCandidate", "rank_contributors"]

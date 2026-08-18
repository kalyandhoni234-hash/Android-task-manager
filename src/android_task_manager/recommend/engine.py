"""Recommendation engine — deterministic "what should I do?" output.

Pure and GUI-independent: consumes the health findings and (optionally)
the process snapshot and produces a deterministic, ordered tuple of
recommendations. Nothing is guessed:

* a recommendation always cites the finding it derives from;
* an action is only attached when a concrete, validated target exists (a
  user-category process whose name is a valid package name);
* destructive actions (force-stop) are never ``automation_allowed``;
* unavailable data produces no recommendation (missing ≠ problem);
* the same target is never recommended twice.
"""

from __future__ import annotations

import re

from ..action.capability import FORCE_STOP
from ..health.models import (
    COMPONENT_BATTERY,
    COMPONENT_CONNECTIVITY,
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    COMPONENT_PROCESSES,
    COMPONENT_STORAGE,
    DeviceHealth,
    Finding,
    HealthSeverity,
)
from ..process.models import ProcessCategory, ProcessSnapshot
from ..thresholds import CPU_HIGH_PERCENT, MEMORY_USED_HIGH_PERCENT
from .models import (
    RECOMMENDATION_SEVERITY_CRITICAL,
    RECOMMENDATION_SEVERITY_INFO,
    RECOMMENDATION_SEVERITY_WARNING,
    Recommendation,
)

#: Conservative Android package-name pattern: dot-separated segments, each
#: starting with a letter and containing only letters/digits/underscore.
#: No shell metacharacters can pass this gate.
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")

#: Severity order for deterministic output (critical first).
_SEVERITY_RANK = {
    RECOMMENDATION_SEVERITY_CRITICAL: 0,
    RECOMMENDATION_SEVERITY_WARNING: 1,
    RECOMMENDATION_SEVERITY_INFO: 2,
}

_PROCESS_CATEGORY_USER = ProcessCategory.USER


def is_valid_package_name(name: str) -> bool:
    """True when *name* matches the conservative package-name pattern."""
    return _PACKAGE_NAME_RE.fullmatch(name) is not None


def _force_stop_recommendation(
    finding_ref: str,
    package: str,
    severity: str,
    evidence: str,
    recommendation_id: str,
) -> Recommendation:
    """A force-stop recommendation for a validated user package.

    Force-stop is destructive, so the recommendation is never
    ``automation_allowed`` — executing it always needs explicit approval.
    """
    return Recommendation(
        recommendation_id=recommendation_id,
        finding_ref=finding_ref,
        title=f"Force-stop {package}",
        rationale=(
            f"{package} is the user process behind this finding "
            f"({evidence}). Stopping it relieves the pressure; it is a "
            "destructive action and always requires explicit approval."
        ),
        severity=severity,
        action=FORCE_STOP,
        target=package,
        destructive=True,
        automation_allowed=False,
    )


def _severity_of(finding: Finding) -> str:
    if finding.severity is HealthSeverity.CRITICAL:
        return RECOMMENDATION_SEVERITY_CRITICAL
    if finding.severity is HealthSeverity.WARNING:
        return RECOMMENDATION_SEVERITY_WARNING
    return RECOMMENDATION_SEVERITY_INFO


def _informational(
    finding_ref: str,
    title: str,
    rationale: str,
    severity: str,
    recommendation_id: str,
) -> Recommendation:
    return Recommendation(
        recommendation_id=recommendation_id,
        finding_ref=finding_ref,
        title=title,
        rationale=rationale,
        severity=severity,
        action=None,
        target=None,
        destructive=False,
        automation_allowed=False,
    )


def _with_ids(recommendations: list[Recommendation]) -> tuple[Recommendation, ...]:
    """Deterministic output: severity order, then sequential ids."""
    recommendations.sort(key=lambda rec: _SEVERITY_RANK[rec.severity])
    return tuple(
        Recommendation(
            recommendation_id=f"REC-{index:03d}",
            finding_ref=rec.finding_ref,
            title=rec.title,
            rationale=rec.rationale,
            severity=rec.severity,
            action=rec.action,
            target=rec.target,
            destructive=rec.destructive,
            automation_allowed=rec.automation_allowed,
        )
        for index, rec in enumerate(recommendations, start=1)
    )


def _flagged_user_processes(
    processes: ProcessSnapshot | None,
    *,
    cpu_threshold: float,
    memory_threshold: float | None,
    installed: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """(package, evidence) of user processes at/above the thresholds.

    ``cpu_threshold`` selects by CPU; ``memory_threshold`` (when not None)
    selects by memory share. Deterministic: ordered by CPU desc, then PID.

    Identity link (Phase H): when *installed* is given (the verified
    installed-package set from the v0.7 inventory), a process is only
    proposed when its name is a *verified installed package* — a spoofed
    process name never becomes a force-stop target. When the inventory is
    unknown (``None``), name validity alone is used and the caller knows
    the identity was not verified.
    """
    if processes is None:
        return ()
    hits: list[tuple[str, str, float, int]] = []
    for process in processes.processes:
        if process.category != _PROCESS_CATEGORY_USER:
            continue
        name = process.name or ""
        if not is_valid_package_name(name):
            continue
        if installed is not None and name not in installed:
            continue
        if process.cpu_percent is not None and process.cpu_percent >= cpu_threshold:
            hits.append(
                (
                    name,
                    f"CPU {process.cpu_percent:.0f}%",
                    process.cpu_percent,
                    process.pid,
                )
            )
        elif (
            memory_threshold is not None
            and process.memory_percent is not None
            and process.memory_percent >= memory_threshold
        ):
            hits.append(
                (
                    name,
                    f"RAM {process.memory_percent:.0f}%",
                    process.cpu_percent or 0.0,
                    process.pid,
                )
            )
    hits.sort(key=lambda hit: (-hit[2], hit[3]))
    return tuple((name, evidence) for name, evidence, _, _ in hits)


def recommend(
    health: DeviceHealth,
    processes: ProcessSnapshot | None = None,
    installed_packages: set[str] | None = None,
) -> tuple[Recommendation, ...]:
    """Derive deterministic recommendations from *health*.

    Ordering: critical first, then warning, then info; within a severity,
    the finding order of the health engine (deterministic). A target is
    never recommended twice.

    *installed_packages* carries the verified installed-package set from
    the v0.7 application inventory (the process-to-app identity link):
    heavy-user-process targets are only proposed when verified installed.
    ``None`` means the inventory is unknown — name validity alone is used,
    and the caller knows identity was not verified.
    """
    recommendations: list[Recommendation] = []
    seen_targets: set[str] = set()

    for finding in health.findings:
        severity = _severity_of(finding)
        component = finding.component
        if component == COMPONENT_CPU:
            recommendations.append(
                _informational(
                    finding.title,
                    "Investigate the CPU saturation",
                    (
                        f"{finding.evidence}. Identify the heaviest processes "
                        "before concluding anything — high utilization is not "
                        "a fault by itself."
                    ),
                    severity,
                    "",
                )
            )
            for package, evidence in _flagged_user_processes(
                processes,
                cpu_threshold=CPU_HIGH_PERCENT,
                memory_threshold=None,
                installed=installed_packages,
            ):
                if package in seen_targets:
                    continue
                seen_targets.add(package)
                recommendations.append(
                    _force_stop_recommendation(
                        finding.title, package, severity, evidence, ""
                    )
                )
        elif component == COMPONENT_PROCESSES:
            for package, evidence in _flagged_user_processes(
                processes,
                cpu_threshold=CPU_HIGH_PERCENT,
                memory_threshold=MEMORY_USED_HIGH_PERCENT,
                installed=installed_packages,
            ):
                if package in seen_targets:
                    continue
                seen_targets.add(package)
                recommendations.append(
                    _force_stop_recommendation(
                        finding.title, package, severity, evidence, ""
                    )
                )
        elif component == COMPONENT_MEMORY:
            recommendations.append(
                _informational(
                    finding.title,
                    "Close heavy applications",
                    (
                        f"{finding.evidence}. Sustained memory pressure can "
                        "force the system to kill background processes; "
                        "closing heavy applications relieves it."
                    ),
                    severity,
                    "",
                )
            )
        elif component == COMPONENT_BATTERY:
            recommendations.append(
                _informational(
                    finding.title,
                    "Act on the battery condition",
                    finding.recommendation,
                    severity,
                    "",
                )
            )
        elif component == COMPONENT_STORAGE:
            recommendations.append(
                _informational(
                    finding.title,
                    "Free internal storage",
                    (
                        f"{finding.evidence}. Free space promptly — low free "
                        "storage can break app updates and system operations."
                    ),
                    severity,
                    "",
                )
            )
        elif component == COMPONENT_CONNECTIVITY:
            recommendations.append(
                _informational(
                    finding.title,
                    "Check the network connection",
                    finding.evidence,
                    severity,
                    "",
                )
            )

    recommendations.sort(key=lambda rec: _SEVERITY_RANK[rec.severity])
    return tuple(
        Recommendation(
            recommendation_id=f"REC-{index:03d}",
            finding_ref=rec.finding_ref,
            title=rec.title,
            rationale=rec.rationale,
            severity=rec.severity,
            action=rec.action,
            target=rec.target,
            destructive=rec.destructive,
            automation_allowed=rec.automation_allowed,
        )
        for index, rec in enumerate(recommendations, start=1)
    )


__all__ = [
    "is_valid_package_name",
    "recommend",
]
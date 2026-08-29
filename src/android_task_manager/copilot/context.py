"""Context builder — live snapshots to serializable CopilotContext.

Pure function over MainWindow's live snapshot mirrors. Never touches ADB.
Builds a rich, page-aware, freshness-tagged context for the reasoning
layer while keeping the schema controlled and bounded.
"""

from __future__ import annotations

from ..applications.models import ApplicationSnapshot
from ..background.models import BackgroundAppsSnapshot, ForegroundSnapshot
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation
from ..diagnostics.models import DiagnosticReport
from ..health.models import DeviceHealth, Finding, HealthSeverity
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..performance.view import METRIC_BATTERY, METRIC_CPU, METRIC_MEMORY, METRIC_STORAGE
from ..process.models import ProcessSnapshot
from ..recommend.models import Recommendation
from ..storage.models import StorageSnapshot
from .candidates import build_candidates
from .intent import classify_intent
from .models import (
    CopilotContext,
    KillCandidate,
    ProtectedProcess,
    SafeFinding,
    SafeRecommendation,
)
from .safety import _safe_apps, protected_processes, sanitize_processes

_FINDING_SEVERITY = {
    HealthSeverity.CRITICAL: "critical",
    HealthSeverity.WARNING: "warning",
    HealthSeverity.INFO: "info",
}


def _to_safe_findings(findings: list[Finding] | tuple[Finding, ...]) -> tuple[SafeFinding, ...]:
    out: list[SafeFinding] = []
    for f in findings:
        out.append(
            SafeFinding(
                severity=_FINDING_SEVERITY.get(f.severity, f.severity.value),
                component=f.component,
                title=f.title,
                explanation=f.explanation,
                recommendation=f.recommendation,
                evidence=f.evidence,
            )
        )
    return tuple(out)


def _to_safe_recommendations(
    recommendations: tuple[Recommendation, ...],
) -> tuple[SafeRecommendation, ...]:
    out: list[SafeRecommendation] = []
    for rec in recommendations:
        out.append(
            SafeRecommendation(
                severity=rec.severity,
                title=rec.title,
                rationale=rec.rationale,
                action=rec.action,
                target=rec.target,
                destructive=rec.destructive,
            )
        )
    return tuple(out)


def _performance_view_to_context(
    performance_score: int | None,
    pressured: tuple[str, ...] | None,
) -> tuple[int | None, tuple[str, ...]]:
    if performance_score is None:
        return None, ()
    metric_labels = {
        METRIC_CPU: "cpu",
        METRIC_MEMORY: "memory",
        METRIC_STORAGE: "storage",
        METRIC_BATTERY: "battery",
    }
    mapped: list[str] = []
    if pressured:
        for key in pressured:
            mapped.append(metric_labels.get(key, key))
    return performance_score, tuple(sorted(set(mapped)))


def build_context(
    *,
    current_page: str,
    connected: bool,
    device_label: str | None = None,
    android_version: str | None = None,
    cpu: CPUSnapshot | None = None,
    memory: MemorySnapshot | None = None,
    battery: BatterySnapshot | None = None,
    storage: StorageSnapshot | None = None,
    processes: ProcessSnapshot | None = None,
    app_snapshot: ApplicationSnapshot | None = None,
    health: DeviceHealth | None = None,
    recommendations: tuple[Recommendation, ...] = (),
    device_info: DeviceInformation | None = None,
    diagnostics: DiagnosticReport | None = None,
    network: NetworkSnapshot | None = None,
    background: BackgroundAppsSnapshot | None = None,
    foreground: ForegroundSnapshot | None = None,
    user_packages: set[str] | None = None,
    performance_score: int | None = None,
    performance_pressured: tuple[str, ...] | None = None,
    context_timestamp: float | None = None,
    query: str | None = None,
) -> CopilotContext:
    """Build a serializable context from the live mirrors."""
    memory_used_percent: float | None = None
    memory_available_kb: int | None = None
    if memory is not None and memory.total_kb > 0:
        memory_used_percent = memory.used_kb / memory.total_kb * 100
        memory_available_kb = memory.available_kb

    storage_available_kb: int | None = None
    if storage is not None:
        storage_available_kb = storage.available_kb

    health_status: str | None = None
    health_score: float | None = None
    health_findings: tuple[SafeFinding, ...] = ()
    if health is not None:
        health_status = health.status.value
        health_score = health.overall_score
        # Deterministic: surface the high/warning findings in focus order.
        ordered = sorted(
            health.findings,
            key=lambda f: (
                -_SEVERITY_ORDER(f.severity),
                f.component,
                f.title,
            ),
        )
        health_findings = _to_safe_findings(ordered)

    diagnostics_findings: tuple[SafeFinding, ...] = ()
    if diagnostics is not None and diagnostics.findings:
        ordered_diag = sorted(
            diagnostics.findings,
            key=lambda f: (-f.severity.rank, f.category.value, f.title),
        )
        diagnostics_findings = tuple(
            SafeFinding(
                severity=f.severity.label,
                component=f.category.value,
                title=f.title,
                explanation=f"{f.what} {f.why}".strip(),
                recommendation=f.recommended_action,
                evidence=f.evidence,
            )
            for f in ordered_diag
        )

    user_app_count: int | None = None
    if app_snapshot is not None:
        user_app_count = sum(
            1 for a in app_snapshot.applications if a.category.value == "user"
        )

    intent = classify_intent(query) if query else None

    sanitized = sanitize_processes(processes, user_packages=user_packages)
    protected = protected_processes(processes)

    safe_apps = _safe_apps(app_snapshot, user_packages=user_packages)

    candidates, candidate_protected = build_candidates(
        background=background,
        foreground=foreground,
        memory=memory,
        app_snapshot=app_snapshot,
        user_packages=user_packages,
        intent=intent or "general",
    )

    # Merge protected system/kernel processes with candidate-layer protected.
    merged_protected = _merge_protected(protected, candidate_protected)

    # Only expose kill candidates / protected on the intents that ask for it.
    expose_candidates = intent in ("gaming", "close_app")
    kill_candidates: tuple[KillCandidate, ...] = candidates if expose_candidates else ()
    protected_final: tuple[ProtectedProcess, ...] = (
        merged_protected if expose_candidates else ()
    )

    network_connected: bool | None = None
    net_rx: float | None = None
    net_tx: float | None = None
    if network is not None:
        network_connected = bool(network.interfaces)
        if network.aggregate_throughput is not None:
            net_rx = network.aggregate_throughput.rx_bytes_per_sec
            net_tx = network.aggregate_throughput.tx_bytes_per_sec

    perf_score, perf_pressured = _performance_view_to_context(
        performance_score, performance_pressured
    )

    return CopilotContext(
        device_label=device_label,
        android_version=android_version,
        device_model=device_info.model if device_info else None,
        device_manufacturer=device_info.manufacturer if device_info else None,
        uptime_seconds=device_info.uptime_seconds if device_info else None,
        cpu_percent=cpu.aggregate_utilization_percent if cpu else None,
        memory_used_percent=memory_used_percent,
        memory_total_kb=memory.total_kb if memory else None,
        memory_available_kb=memory_available_kb,
        battery_level_percent=battery.level_percent if battery else None,
        battery_status=battery.status.label if battery else None,
        battery_temperature_c=battery.temperature_c if battery else None,
        battery_health=battery.health.label if battery else None,
        storage_used_percent=storage.used_percent if storage else None,
        storage_total_kb=storage.total_kb if storage else None,
        storage_available_kb=storage_available_kb,
        network_connected=network_connected,
        network_throughput_rx_bps=net_rx,
        network_throughput_tx_bps=net_tx,
        top_processes=sanitized,
        process_count=len(processes.processes) if processes else None,
        installed_app_count=len(app_snapshot.applications) if app_snapshot else None,
        user_app_count=user_app_count,
        applications=safe_apps,
        health_status=health_status,
        health_score=health_score,
        health_findings=health_findings,
        diagnostics_findings=diagnostics_findings,
        recommendations=_to_safe_recommendations(recommendations),
        performance_score=perf_score,
        performance_pressured=perf_pressured,
        kill_candidates=kill_candidates,
        protected_processes=protected_final,
        intent=intent,
        current_page=current_page,
        connected=connected,
        context_timestamp=context_timestamp,
    )


def _SEVERITY_ORDER(severity: HealthSeverity) -> int:
    return {
        HealthSeverity.CRITICAL: 0,
        HealthSeverity.WARNING: 1,
        HealthSeverity.INFO: 2,
    }.get(severity, 3)


def _merge_protected(
    a: tuple[ProtectedProcess, ...],
    b: tuple[ProtectedProcess, ...],
) -> tuple[ProtectedProcess, ...]:
    seen: set[tuple[str, str]] = set()
    out: list[ProtectedProcess] = []
    for p in (*a, *b):
        key = (p.name, p.safety.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return tuple(out)


__all__ = ["build_context"]

"""Deterministic process safety classification.

Runs BEFORE data reaches the LLM. Reuses the existing ``ProcessCategory``
classification, package-name validation and the action-layer capability
gate — never duplicates that logic.

Guarantees enforced here:

* kernel threads and system processes never become individual LLM
  entries (they are aggregated as ``PROTECTED``);
* only USER-category processes with a valid package name can ever be
  marked ``SAFE_CANDIDATE``;
* a process is only given a capability when the deterministic action
  layer would actually permit the action for its target.
"""

from __future__ import annotations

from ..action.capability import FORCE_STOP, supported_actions
from ..applications.models import AppCategory, ApplicationSnapshot
from ..process.models import ProcessCategory, ProcessSnapshot
from ..recommend.engine import is_valid_package_name
from .models import ProcessSafetyClass, ProtectedProcess, SafeApp, SafeProcess

_MAX_PROCESSES = 20


def classify_process(category: ProcessCategory, name: str) -> ProcessSafetyClass:
    """Classify a process for safe LLM consumption."""
    if category is ProcessCategory.KERNEL_THREAD:
        return ProcessSafetyClass.CRITICAL_SYSTEM
    if category is ProcessCategory.SYSTEM:
        return ProcessSafetyClass.SYSTEM_PROCESS
    if is_valid_package_name(name):
        return ProcessSafetyClass.SAFE_CANDIDATE
    return ProcessSafetyClass.USER_APP


def _force_stop_capability(
    name: str,
    *,
    user_packages: set[str] | None,
) -> str | None:
    """Deterministic force-stop capability for a validated user package.

    Mirrors the action layer: force-stop is permitted for user apps and
    (in this tool's conservative posture) is also offered for system apps,
    but a non-package name or a package outside the known user set never
    gains a capability. This is a capability *match*, not a command.
    """
    if not is_valid_package_name(name):
        return None
    if user_packages is not None and name not in user_packages:
        return None
    return FORCE_STOP


def sanitize_processes(
    processes: ProcessSnapshot | None,
    *,
    max_count: int = _MAX_PROCESSES,
    user_packages: set[str] | None = None,
) -> tuple[SafeProcess, ...]:
    """Pre-classify and truncate the process list for LLM context.

    Returns at most *max_count* processes, sorted by CPU desc then PID.
    Kernel threads and system processes are aggregated — only USER-category
    processes with valid package names appear as individual entries, and
    only those become capability-bearing candidates.
    """
    if processes is None:
        return ()
    candidates: list[SafeProcess] = []
    for p in processes.processes:
        safety = classify_process(p.category, p.name or "")
        if safety in (ProcessSafetyClass.CRITICAL_SYSTEM, ProcessSafetyClass.SYSTEM_PROCESS):
            continue
        package = p.name if is_valid_package_name(p.name or "") else None
        candidates.append(
            SafeProcess(
                pid=p.pid,
                name=p.name,
                category=safety,
                cpu_percent=p.cpu_percent,
                memory_percent=p.memory_percent,
                package=package,
                uid=p.uid,
                state=p.state,
                capability=_force_stop_capability(
                    p.name or "", user_packages=user_packages
                ),
            )
        )
    candidates.sort(
        key=lambda s: (-(s.cpu_percent or 0.0), -(s.memory_percent or 0.0), s.pid)
    )
    return tuple(candidates[:max_count])


#: Reasons assigned to protected-process aggregation.
_PROTECTED_REASONS = {
    ProcessSafetyClass.CRITICAL_SYSTEM: "kernel thread — never a safe action target",
    ProcessSafetyClass.SYSTEM_PROCESS: "system process — never a safe action target",
}


def protected_processes(
    processes: ProcessSnapshot | None,
    *,
    top_n: int = 8,
) -> tuple[ProtectedProcess, ...]:
    """Aggregate non-candidate processes as an explicit protected list.

    Only the overall top-N protected processes (by CPU) are surfaced, so
    kernel/system detail is not dumped wholesale — the LLM gets a bounded,
    labeled set it can reference as "protected".
    """
    if processes is None:
        return ()
    hits: list[tuple[ProtectedProcess, float]] = []
    for p in processes.processes:
        safety = classify_process(p.category, p.name or "")
        reason = _PROTECTED_REASONS.get(safety)
        if reason is None:
            continue
        hits.append(
            (
                ProtectedProcess(
                    name=p.name or "unknown",
                    safety=safety,
                    reason=reason,
                ),
                p.cpu_percent or 0.0,
            )
        )
    if not hits:
        return ()
    hits.sort(key=lambda pair: (-pair[1], pair[0].name))
    seen: set[tuple[str, str]] = set()
    out: list[ProtectedProcess] = []
    for protected, _ in hits:
        key = (protected.name, protected.safety.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(protected)
        if len(out) >= top_n:
            break
    return tuple(out)


def _safe_apps(
    app_snapshot: ApplicationSnapshot | None,
    *,
    user_packages: set[str] | None,
    max_apps: int = 25,
) -> tuple[SafeApp, ...]:
    """Pre-screen installed apps for LLM consumption."""
    if app_snapshot is None:
        return ()
    out: list[SafeApp] = []
    for app in app_snapshot.applications:
        is_system = app.category is AppCategory.SYSTEM
        actions = supported_actions(is_system, app.enabled)
        capability = FORCE_STOP if FORCE_STOP in actions else None
        is_user = app.category is AppCategory.USER
        if user_packages is not None and app.package_name in user_packages:
            # user_packages is authoritative; keep the user flag aligned.
            is_user = True
        out.append(
            SafeApp(
                package_name=app.package_name,
                category=app.category.value,
                enabled=app.enabled,
                label=app.label,
                capability=capability if is_user else None,
            )
        )
    # Deterministic ordering: user apps first, then enabled, then by name.
    out.sort(
        key=lambda a: (0 if a.category == "user" else 1, a.package_name)
    )
    return tuple(out[:max_apps])


__all__ = [
    "classify_process",
    "protected_processes",
    "sanitize_processes",
    "_safe_apps",
]

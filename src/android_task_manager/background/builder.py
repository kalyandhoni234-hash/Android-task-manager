"""Background-app builder: PROCESS -> APPLICATION -> user-app identity.

Pure aggregation over snapshots the monitor already published:

* only processes classified USER (uid >= AID_APP) are eligible;
* every eligible process must resolve via UID relationship to a package
  in the authoritative installed-application inventory (UID-or-Unknown:
  exact / `<package>:suffix` disambiguation inside the UID group;
  no process-name fallback) — unresolved processes are dropped, never
  guessed;
* packages whose inventory category is not explicitly USER (system,
  protected, unknown) are excluded entirely;
* the currently foreground application is excluded from the background
  list when the device provided a reliable foreground signal; without
  that signal every state stays UNKNOWN instead of claiming background;
* multiple processes of one application aggregate into ONE entry
  (summed CPU / memory share, ordered PID list).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..applications.models import AppCategory, AppInfo, ApplicationSnapshot
from ..memory.models import MemorySnapshot
from ..process.classification import _AID_APP
from ..process.models import ProcessCategory, ProcessInfo, ProcessSnapshot
from .models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
    ForegroundSnapshot,
)


def _uid_group_matches(package: str, process_name: str) -> bool:
    """True when *process_name* is a valid Android shape for *package*.

    Android names app processes exactly ``<package>`` or
    ``<package>:<suffix>`` (service/push/isolated-process suffixes). There is
    deliberately NO ``package + "."`` rule: ``com.foo.application`` is a
    *different package*, never an extension of ``com.foo``.
    """
    return process_name == package or process_name.startswith(package + ":")


def _resolve_owner(
    process: ProcessInfo,
    by_uid: dict[int, list[AppInfo]],
) -> AppInfo | None:
    """Resolve one process to its owning installed application.

    UID-or-Unknown (hardened contract): ownership requires a UID-backed
    candidate — an installed user package whose UID equals the process UID.
    Within equal UIDs (sharedUserId) disambiguation is deterministic:
    exact process name, then ``<package>:suffix``, then the alphabetically
    first candidate (shared-user packages are indistinguishable from
    process data alone, and the choice must never depend on dict order).

    When no UID-backed candidate exists the owner is ``None`` and the
    process is dropped — it is NEVER attributed merely because its name
    matches an installed package.
    """
    if process.uid is None:
        return None
    candidates = by_uid.get(process.uid)
    if not candidates:
        return None

    exact = [a for a in candidates if a.package_name == process.name]
    if exact:
        return exact[0]
    prefixed = sorted(
        (a for a in candidates if _uid_group_matches(a.package_name, process.name)),
        key=lambda a: a.package_name,
    )
    if prefixed:
        return prefixed[0]
    return sorted(candidates, key=lambda a: a.package_name)[0]


def _sum(values: list[float | None]) -> float | None:
    """Sum the known values; ``None`` only when nothing was reported."""
    known = [v for v in values if v is not None]
    if not known:
        return None
    return sum(known)


def build_background_apps(
    processes: ProcessSnapshot | None,
    inventory: ApplicationSnapshot | None,
    foreground: ForegroundSnapshot | None = None,
    memory: MemorySnapshot | None = None,
    timestamp: float | None = None,
    labels: Mapping[str, str | None] | None = None,
) -> BackgroundAppsSnapshot:
    """Aggregate running user processes into per-application entries.

    Requires BOTH a process snapshot and a verified application inventory:
    without the inventory no process can be proven to belong to a
    user-installed application, so the honest result is an empty snapshot.
    """
    ts = timestamp if timestamp is not None else (
        processes.timestamp if processes is not None else 0.0
    )
    if processes is None or inventory is None:
        return BackgroundAppsSnapshot(timestamp=ts, entries=[])

    user_apps = [
        app for app in inventory.applications if app.category is AppCategory.USER
    ]
    if not user_apps or not processes.processes:
        return BackgroundAppsSnapshot(timestamp=ts, entries=[])

    by_uid: dict[int, list[AppInfo]] = {}
    for app in user_apps:
        if app.uid is not None:
            by_uid.setdefault(app.uid, []).append(app)

    foreground_package = (
        foreground.package_name
        if foreground is not None and foreground.available
        else None
    )
    foreground_available = foreground_package is not None

    grouped: dict[str, list[ProcessInfo]] = {}
    owner_uids: dict[str, int | None] = {}
    owner_labels: dict[str, str | None] = {}
    for process in processes.processes:
        if process.category is ProcessCategory.KERNEL_THREAD:
            continue  # kernel threads never appear here
        if process.uid is not None and process.uid < _AID_APP:
            continue  # system/service UIDs are excluded even on name collisions
        owner = _resolve_owner(process, by_uid)
        if owner is None:
            continue  # unverified identity: dropped, never guessed
        if owner.package_name == foreground_package:
            continue  # the foreground app is not a background app
        grouped.setdefault(owner.package_name, []).append(process)
        owner_uids[owner.package_name] = owner.uid
        owner_labels[owner.package_name] = owner.label

    state = (
        BackgroundAppState.BACKGROUND
        if foreground_available
        else BackgroundAppState.UNKNOWN
    )

    total_kb = memory.total_kb if memory is not None else 0
    entries: list[BackgroundAppEntry] = []
    for package, procs in grouped.items():
        pids = tuple(sorted(proc.pid for proc in procs))
        cpu = _sum([proc.cpu_percent for proc in procs])
        mem_percent = _sum([proc.memory_percent for proc in procs])
        memory_kb: int | None = None
        if total_kb > 0 and mem_percent is not None:
            memory_kb = int(round(total_kb * mem_percent / 100.0))
        # Prefer an explicit label map (device-resolved names), then the
        # inventory's own label, then fall back to the package name in the
        # GUI. A label is never invented.
        label: str | None = None
        if labels is not None and package in labels:
            label = labels[package]
        if label is None:
            label = owner_labels.get(package)
        entries.append(
            BackgroundAppEntry(
                package_name=package,
                label=label,
                uid=owner_uids.get(package),
                pids=pids,
                cpu_percent=cpu,
                memory_percent=mem_percent,
                memory_kb=memory_kb,
                state=state,
            )
        )

    # Deterministic presentation order: heaviest memory first, then CPU,
    # then package name; unknown metrics sort last within each key.
    def _sort_key(entry: BackgroundAppEntry) -> tuple[float, float, str]:
        return (
            -(entry.memory_percent if entry.memory_percent is not None else float("-inf")),
            -(entry.cpu_percent if entry.cpu_percent is not None else float("-inf")),
            entry.package_name,
        )

    entries.sort(key=_sort_key)
    return BackgroundAppsSnapshot(timestamp=ts, entries=entries)


__all__ = ["build_background_apps"]

"""Process collector: builds a normalized ProcessSnapshot.

ps is the authoritative identity source; top supplies dynamic metrics. They are
merged strictly by PID (never by name, and never assuming matching row order).
Only processes `top` actually reported are surfaced in the snapshot: ps-only
processes carry no dynamic metrics and would render as N/A rows, so they are
not included in the process table. Uses the shared ``CommandRunner`` facade —
never calls subprocess.
"""

from __future__ import annotations

import time

from ..adb.connection import CommandRunner
from .classification import classify_process
from .models import ProcessCPUMetrics, ProcessIdentity, ProcessInfo, ProcessSnapshot
from .parser import parse_ps_output, parse_top_output


class ProcessCollector:
    """Samples process inventory (ps) and dynamic metrics (top) on the device."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout

    def sample(self) -> ProcessSnapshot:
        """Collect and merge one process snapshot.

        Detailed ``dumpsys meminfo <PID>`` per-process PSS/RSS is intentionally
        NOT collected here — it is expensive and reserved for a future on-demand
        operation.
        """
        ps_text = self._runner.shell(
            ["ps", "-A", "-o", "PID,PPID,UID,NAME"], timeout=self._timeout
        )
        top_text = self._runner.shell(["top", "-n", "1"], timeout=self._timeout)

        identities = parse_ps_output(ps_text)
        metrics = parse_top_output(top_text)
        timestamp = time.monotonic()

        return ProcessSnapshot(
            timestamp=timestamp,
            processes=_merge(identities, metrics),
        )


def _merge(
    identities: list[ProcessIdentity],
    metrics: list[ProcessCPUMetrics],
) -> list[ProcessInfo]:
    """Merge ps identity with top metrics keyed by PID.

    The process table is defined by ``top``: only processes top reported with
    dynamic metrics are surfaced. ps wins for identity (UID/name/category) on
    the PIDs it knows; a top-only PID keeps top's name as a fallback (or a
    ``<pid N>`` placeholder) with an unknown UID. First occurrence wins on
    duplicate PIDs.
    """
    identity_by_pid = {identity.pid: identity for identity in identities}

    cpu_by_pid: dict[int, ProcessCPUMetrics] = {}
    for metric in metrics:
        cpu_by_pid.setdefault(metric.pid, metric)

    processes: list[ProcessInfo] = []
    for pid, cpu in cpu_by_pid.items():
        identity = identity_by_pid.get(pid)
        if identity is not None:
            name = identity.name
            uid = identity.uid
        else:
            name = cpu.name or f"<pid {pid}>"
            uid = None
        processes.append(
            ProcessInfo(
                pid=pid,
                uid=uid,
                name=name,
                state=cpu.state,
                cpu_percent=cpu.cpu_percent,
                memory_percent=cpu.memory_percent,
                category=classify_process(name, uid),
                ppid=identity.ppid if identity is not None else None,
            )
        )

    return processes
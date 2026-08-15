"""Unit tests for process collection, PID-based merging and rendering.

No device required. The collector is driven by a fake command runner.
"""

from __future__ import annotations

import re

from android_task_manager.process.collector import ProcessCollector
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot
from android_task_manager.terminal.renderer import _process_lines, _process_row

# ---------------------------------------------------------------------------
# Fixtures (shared ps inventory + top table).
# ---------------------------------------------------------------------------

PS_TEXT = """PID   PPID  UID  NAME
1     0     0    init
2     0     0    [kthreadd]
754   1     1000 system_server
24199 754   1001 some.sys
24791 754   10203 com.instagram.android
24226 754   10205 com.whatsapp
50001 1000 10211 ps.only.process
"""

TOP_HEADER = "  PID  USER           PR  NI  VIRT     RES     SHR  S  %CPU   %MEM        TIME+           ARGS" + " " * 40
_TOP_LABELS = [m.group() for m in re.finditer(r"\S+", TOP_HEADER)]


def _top_row(pid, state, cpu, mem, name, user="root"):
    fields = {
        "PID": str(pid), "USER": user, "PR": "20", "NI": "0", "VIRT": "0K",
        "RES": "0K", "SHR": "0K", "S": state, "%CPU": cpu, "%MEM": mem,
        "TIME+": "0:00.00", "ARGS": name,
    }
    # Space-separated fields in header column order, like real `top -n 1`.
    return " ".join(fields[label] for label in _TOP_LABELS)


TOP_SUMMARY = (
    "Tasks: 123 total,   2 running, 121 sleeping,   0 stopped,   0 zombie\n"
    "Mem:  2870876k total,  2395504k used,   475372k free,   0k buffers\n"
)

TOP_ROWS = "\n".join(
    [
        _top_row(8150, "R", "120.4", "2.0", "com.heavy.app", user="u0_a99"),
        _top_row(24226, "R", "18.5", "4.1", "com.whatsapp", user="u0_a205"),
        _top_row(24791, "S", "2.9", "7.3", "com.instagram.android", user="u0_a203"),
        _top_row(754, "S", "1.2", "9.1", "system_server", user="system"),
        _top_row(2, "S", "0.0", "0.0", "[kthreadd]"),
        # top-only PID (not present in PS_TEXT inventory)
        _top_row(90001, "S", "1.5", "0.2", "top.only.app", user="u0_a99"),
        # duplicate PID within top (first occurrence should win: 754 -> 1.2)
        _top_row(754, "S", "77.7", "5.0", "system_server", user="system"),
    ]
)

TOP_TEXT = TOP_SUMMARY + TOP_HEADER + "\n" + TOP_ROWS + "\n"


class _FakeRunner:
    """Serves fixed ps/top blobs and records the commands issued."""

    def __init__(self, ps: str = PS_TEXT, top: str = TOP_TEXT) -> None:
        self.ps = ps
        self.top = top
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        if args[0] == "ps":
            return self.ps
        if args[0] == "top":
            return self.top
        return ""


def _snapshot(processes: list[ProcessInfo]) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=0.0, processes=processes)


def test_sample_merges_by_pid() -> None:
    runner = _FakeRunner()
    snapshot = ProcessCollector(runner).sample()
    by_pid = {p.pid: p for p in snapshot.processes}

    merged = by_pid[24791]
    assert merged.name == "com.instagram.android"  # ps name wins
    assert merged.uid == 10203
    assert merged.state == "S"
    assert merged.cpu_percent == 2.9
    assert merged.memory_percent == 7.3


def test_pid_present_in_ps_but_missing_in_top_is_excluded() -> None:
    runner = _FakeRunner()
    snapshot = ProcessCollector(runner).sample()
    pids = {p.pid for p in snapshot.processes}
    # 50001 exists only in ps; the process table is defined by top metrics,
    # so a ps-only process must not appear (it would render as N/A CPU/MEM).
    assert 50001 not in pids


def test_large_ps_inventory_but_small_top_only_metrics_surface() -> None:
    # 500 ps identities, but top reports only 20 processes with metrics →
    # the snapshot must contain exactly those 20 metric-bearing processes.
    ps_lines = ["PID UID NAME"] + [f"{1000 + i} {10000 + i} ps.proc.{i}" for i in range(500)]
    ps_text = "\n".join(ps_lines) + "\n"
    top_rows = [_top_row(1000 + i, "S", f"{i}.0", "1.0", f"top.proc.{i}") for i in range(20)]
    top_text = TOP_SUMMARY + TOP_HEADER + "\n" + "\n".join(top_rows) + "\n"

    snapshot = ProcessCollector(_FakeRunner(ps=ps_text, top=top_text)).sample()
    assert len(snapshot.processes) == 20
    assert all(p.cpu_percent is not None for p in snapshot.processes)
    assert all(p.memory_percent is not None for p in snapshot.processes)


def test_pid_present_in_top_but_missing_in_ps() -> None:
    runner = _FakeRunner()
    snapshot = ProcessCollector(runner).sample()
    by_pid = {p.pid: p for p in snapshot.processes}
    top_only = by_pid[90001]
    assert top_only.pid == 90001
    assert top_only.uid is None
    assert top_only.name == "top.only.app"  # fallback name from top
    assert top_only.cpu_percent == 1.5


def test_pid_merge_resolves_uid_and_name_from_ps() -> None:
    # PID merge must still attach ps identity (UID/name) to a top-reported row.
    runner = _FakeRunner()
    snapshot = ProcessCollector(runner).sample()
    by_pid = {p.pid: p for p in snapshot.processes}
    assert by_pid[24791].uid == 10203
    assert by_pid[24791].name == "com.instagram.android"
    assert by_pid[754].uid == 1000
    assert by_pid[754].name == "system_server"


def test_duplicate_pid_handling_across_sources() -> None:
    runner = _FakeRunner()
    snapshot = ProcessCollector(runner).sample()
    by_pid = {p.pid: p for p in snapshot.processes}
    # PID 754 has ONE ps identity row and appears twice in top.
    # ps supplies identity; the FIRST top metric wins as the CPU value.
    merged = by_pid[754]
    assert merged.name == "system_server"
    assert merged.uid == 1000
    assert merged.cpu_percent == 1.2  # first top occurrence, not 77.7
    assert merged.ppid == 1  # parent from the ps PPID column


def test_classification_applied_by_collector() -> None:
    snapshot = ProcessCollector(_FakeRunner()).sample()
    by_pid = {p.pid: p for p in snapshot.processes}
    assert by_pid[2].category is ProcessCategory.KERNEL_THREAD
    assert by_pid[754].category is ProcessCategory.SYSTEM
    assert by_pid[24791].category is ProcessCategory.USER
    # Top-only (unknown uid) process is classified as system.
    assert by_pid[90001].category is ProcessCategory.SYSTEM


def test_collector_uses_command_runner() -> None:
    runner = _FakeRunner()
    ProcessCollector(runner).sample()
    assert runner.calls[0][0] == "ps"
    assert runner.calls[0][1:] == ["-A", "-o", "PID,PPID,UID,NAME"]
    assert runner.calls[1][0] == "top"
    assert runner.calls[1][1:] == ["-n", "1"]


def test_rendering_sorts_processes_by_cpu_descending() -> None:
    processes = [
        ProcessInfo(pid=1, name="a", uid=0, state="S", cpu_percent=5.0, memory_percent=1.0, category=ProcessCategory.SYSTEM),
        ProcessInfo(pid=2, name="b", uid=0, state="S", cpu_percent=None, memory_percent=1.0, category=ProcessCategory.SYSTEM),
        ProcessInfo(pid=3, name="c", uid=1, state="R", cpu_percent=120.4, memory_percent=2.0, category=ProcessCategory.USER),
        ProcessInfo(pid=4, name="d", uid=1, state="S", cpu_percent=0.0, memory_percent=1.0, category=ProcessCategory.USER),
    ]
    lines = _process_lines(_snapshot(processes))
    rows = [line for line in lines if " % " in line or line.split() and line.split()[0].isdigit()]
    # Recover row order from the rendered lines: cpu descending, None last.
    pids_in_rows = []
    for line in lines:
        tokens = line.split()
        if tokens and tokens[0].isdigit():
            pids_in_rows.append(int(tokens[0]))
    assert pids_in_rows == [3, 1, 4, 2]


def test_rendering_high_cpu_value_not_reduced() -> None:
    proc = ProcessInfo(pid=3, name="c", uid=1, state="R", cpu_percent=120.4, memory_percent=2.0, category=ProcessCategory.USER)
    assert "120.4%" in _process_row(proc)


def test_rendering_missing_metrics_as_na() -> None:
    proc = ProcessInfo(pid=50001, name="x", uid=10211, state=None, cpu_percent=None, memory_percent=None, category=ProcessCategory.USER)
    row = _process_row(proc)
    assert "N/A" in row
    assert "x" in row


def test_rendering_contains_only_top_reported_processes() -> None:
    # Render a full collected snapshot: ps-only rows are gone from the table,
    # top-only rows are present, and CPU-descending order is preserved.
    runner = _FakeRunner()
    lines = _process_lines(ProcessCollector(runner).sample())
    pids_in_rows = []
    for line in lines:
        tokens = line.split()
        if tokens and tokens[0].isdigit():
            pids_in_rows.append(int(tokens[0]))
    assert 90001 in pids_in_rows  # top-only process still represented
    assert 50001 not in pids_in_rows  # ps-only process not in the table
    # CPU descending: 8150 (120.4) > 24226 (18.5) > 24791 (2.9) > 90001 (1.5)
    # > 754 (1.2) > 2 (0.0)
    assert pids_in_rows == [8150, 24226, 24791, 90001, 754, 2]
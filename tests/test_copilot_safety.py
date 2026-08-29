"""Tests for the Copilot safety classification."""

from __future__ import annotations

import time

from android_task_manager.copilot.models import ProcessSafetyClass
from android_task_manager.copilot.safety import classify_process, sanitize_processes
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot


def _make_process(
    pid: int,
    name: str,
    category: ProcessCategory = ProcessCategory.USER,
    cpu: float | None = None,
    mem: float | None = None,
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=10000 + pid,
        state="S",
        cpu_percent=cpu,
        memory_percent=mem,
        category=category,
    )


def test_classify_kernel_thread() -> None:
    assert classify_process(ProcessCategory.KERNEL_THREAD, "[kworker/0:1]") is ProcessSafetyClass.CRITICAL_SYSTEM


def test_classify_system() -> None:
    assert classify_process(ProcessCategory.SYSTEM, "system_server") is ProcessSafetyClass.SYSTEM_PROCESS


def test_classify_user_valid_package() -> None:
    assert classify_process(ProcessCategory.USER, "com.example.app") is ProcessSafetyClass.SAFE_CANDIDATE


def test_classify_user_invalid_package() -> None:
    assert classify_process(ProcessCategory.USER, "some_process") is ProcessSafetyClass.USER_APP


def test_sanitize_processes_empty() -> None:
    assert sanitize_processes(None) == ()
    assert sanitize_processes(ProcessSnapshot(timestamp=time.time(), processes=[])) == ()


def test_sanitize_processes_kernel_excluded() -> None:
    procs = ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            _make_process(1, "[kworker/0:1]", category=ProcessCategory.KERNEL_THREAD, cpu=50.0),
            _make_process(2, "system_server", category=ProcessCategory.SYSTEM, cpu=30.0),
            _make_process(3, "com.example.app", category=ProcessCategory.USER, cpu=10.0),
        ],
    )
    result = sanitize_processes(procs)
    assert len(result) == 1
    assert result[0].name == "com.example.app"
    assert result[0].category == ProcessSafetyClass.SAFE_CANDIDATE


def test_sanitize_processes_sorted_by_cpu() -> None:
    procs = ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            _make_process(1, "com.low.cpu", category=ProcessCategory.USER, cpu=5.0),
            _make_process(2, "com.high.cpu", category=ProcessCategory.USER, cpu=50.0),
            _make_process(3, "com.mid.cpu", category=ProcessCategory.USER, cpu=25.0),
        ],
    )
    result = sanitize_processes(procs)
    assert len(result) == 3
    assert result[0].name == "com.high.cpu"
    assert result[1].name == "com.mid.cpu"
    assert result[2].name == "com.low.cpu"


def test_sanitize_processes_max_count() -> None:
    procs = ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            _make_process(i, f"com.app{i}", category=ProcessCategory.USER, cpu=float(i))
            for i in range(20)
        ],
    )
    result = sanitize_processes(procs, max_count=5)
    assert len(result) == 5


def test_sanitize_processes_mixed_categories() -> None:
    procs = ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            _make_process(1, "[kworker]", category=ProcessCategory.KERNEL_THREAD, cpu=90.0),
            _make_process(2, "system", category=ProcessCategory.SYSTEM, cpu=80.0),
            _make_process(3, "com.user.app", category=ProcessCategory.USER, cpu=5.0),
            _make_process(4, "native_daemon", category=ProcessCategory.USER, cpu=3.0),
        ],
    )
    result = sanitize_processes(procs)
    names = [p.name for p in result]
    assert "com.user.app" in names
    assert "native_daemon" in names
    assert "[kworker]" not in names
    assert "system" not in names

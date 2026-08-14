"""Unit tests for the read-only process inspector (status/stat/cmdline/io).

Fixtures mirror realistic Android (Vivo V2026 style) /proc/<pid> output. No
device or subprocess is used; the inspector is driven through a fake runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from android_task_manager.adb.exceptions import ADBCommandError
from android_task_manager.process import (
    ProcessDisappearedError,
    ProcessInspector,
    StatParseError,
)
from android_task_manager.process.inspector_models import ProcessInspectionSnapshot
from android_task_manager.process.inspector_parser import (
    parse_cmdline,
    parse_io,
    parse_stat,
    parse_status,
)

ROOT = Path(__file__).resolve().parent.parent

STATUS_TEXT = """Name:\tcom.instagram.android
Umask:\t0022
State:\tS (sleeping)
Tgid:\t24791
Ngid:\t0
Pid:\t24791
PPid:\t754
TracerPid:\t0
Uid:\t10203\t10203\t10203\t10203
Gid:\t10203\t10203\t10203\t10203
FDSize:\t128
Groups:\t3003 9997 20203 50203 60203
VmPeak:\t2085796 kB
VmSize:\t1842320 kB
VmLck:\t0 kB
VmPin:\t0 kB
VmHWM:\t286724 kB
VmRSS:\t232448 kB
RssAnon:\t216704 kB
RssFile:\t14336 kB
RssShmem:\t1408 kB
VmData:\t597440 kB
VmStk:\t136 kB
VmExe:\t20 kB
VmLib:\t161736 kB
VmPTE:\t1764 kB
VmSwap:\t0 kB
CoreDumping:\t0
THP_enabled:\t1
Threads:\t42
SigQ:\t0/12059
SigPnd:\t0000000000000000
ShdPnd:\t0000000000000000
SigBlk:\t0000000000000000
SigIgn:\t0000000000000384
SigCgt:\t0000000180001443
CapInh:\t0000000000000000
CapPrm:\t0000000000000000
CapEff:\t0000000000000000
CapBnd:\t0000000000000000
CapAmb:\t0000000000000000
Seccomp:\t2
NoNewPrivs:\t0
Speculation_Store_Bypass:\tthread vulnerable
Cpus_allowed:\tff
Cpus_allowed_list:\t0-7
Mems_allowed:\t1
Mems_allowed_list:\t0
voluntary_ctxt_switches:\t71
nonvoluntary_ctxt_switches:\t17
"""

# stat fields: priority 11, nice 0, num_threads 42, vsize 1842327552 bytes,
# rss 58112 pages (x4 KiB == 232448 KiB, matching VmRSS above).
STAT_TEXT = (
    "24791 (com.instagram.android) S 754 754 0 0 -1 4194624 117531 0 144 0 "
    "316 355 152 552 11 0 42 256884 1842327561 1842327552 58112 "
    "18446744073709551615 4194304 4610392239 1073741824 32768 32768 4194304 "
    "0 0 0 22339 0 0 0 17 9 0 0 0 0 0 0 0 0 0 0 0 0 0"
)

CMDLINE_TEXT = "com.instagram.android\x00--fg\x00"

IO_TEXT = """rchar: 123456
wchar: 23456
syscr: 542
syscw: 301
read_bytes: 67890
write_bytes: 54321
cancelled_write_bytes: 0
"""


class FakeRunner:
    """Serves fixed per-path blobs and records every command issued."""

    def __init__(self, files: dict[str, str]) -> None:
        self._files = dict(files)
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        path = args[-1]
        if path in self._files:
            return self._files[path]
        raise ADBCommandError("shell " + " ".join(args), 1, stderr=f"cat: {path}: No such file or directory")


class RaisingRunner(FakeRunner):
    """Fails a specific path with a raw exception type (default: ADBError)."""

    def __init__(self, files: dict[str, str], fail_path: str, error) -> None:
        super().__init__(files)
        self.fail_path = fail_path
        self.error = error

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        path = args[-1]
        if path == self.fail_path:
            raise self.error
        return self._files.get(path, "")


def _inspector_files() -> dict[str, str]:
    return {
        "/proc/24791/status": STATUS_TEXT,
        "/proc/24791/stat": STAT_TEXT,
        "/proc/24791/cmdline": CMDLINE_TEXT,
        "/proc/24791/io": IO_TEXT,
    }


def _full_snapshot() -> ProcessInspectionSnapshot:
    return ProcessInspector(FakeRunner(_inspector_files())).sample(24791)


# ---------------------------------------------------------------------------
# Parser level: /proc/<pid>/status
# ---------------------------------------------------------------------------


def test_status_parses_normal_fields() -> None:
    fields = parse_status(STATUS_TEXT)
    assert fields.name == "com.instagram.android"
    assert fields.state == "S (sleeping)"
    assert fields.uid == 10203
    assert fields.threads == 42
    assert fields.vm_size_kb == 1842320
    assert fields.vm_rss_kb == 232448
    assert fields.rss_anon_kb == 216704
    assert fields.rss_file_kb == 14336
    assert fields.rss_shmem_kb == 1408


def test_status_missing_optional_fields_are_none() -> None:
    fields = parse_status(
        "Name:\tkernel.thread\nState:\tS (sleeping)\nThreads:\t3\n"
        # deliberately no VmSize/VmRSS/Rss* fields
    )
    assert fields.name == "kernel.thread"
    assert fields.vm_size_kb is None
    assert fields.vm_rss_kb is None
    assert fields.rss_anon_kb is None
    assert fields.rss_file_kb is None
    assert fields.rss_shmem_kb is None


def test_status_uid_is_the_real_uid_first_token() -> None:
    assert parse_status("Uid:\t10001\t10002\t10003\t10004\n").uid == 10001
    assert parse_status("Uid:\t0\n").uid == 0


def test_status_ignores_unknown_keys_and_malformed_values() -> None:
    fields = parse_status(
        "Name:\tweird\nState:\tR (running)\nThreads:\tnot-a-number\n"
        "VmRSS:\tnot-kb\nTotallyUnknownKey:\twhatever\n"
    )
    assert fields.name == "weird"
    assert fields.state == "R (running)"
    assert fields.threads is None
    assert fields.vm_rss_kb is None
    assert fields.rss_anon_kb is None


def test_status_garbage_text_does_not_crash() -> None:
    fields = parse_status("line without colon\n   garbage  \n")
    assert fields.name is None
    assert fields.uid is None
    assert fields.vm_rss_kb is None


# ---------------------------------------------------------------------------
# Parser level: /proc/<pid>/stat
# ---------------------------------------------------------------------------


def test_stat_parses_priority_nice_threads_and_memory() -> None:
    fields = parse_stat(STAT_TEXT)
    assert fields.name == "com.instagram.android"
    assert fields.state == "S"
    assert fields.priority == 11
    assert fields.nice == 0
    assert fields.num_threads == 42
    assert fields.vsize_bytes == 1842327552
    assert fields.rss_pages == 58112


def test_stat_name_with_spaces() -> None:
    fields = parse_stat("1234 (process with spaces) R 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21")
    assert fields.name == "process with spaces"
    assert fields.state == "R"


def test_stat_name_with_parentheses() -> None:
    fields = parse_stat('9876 (weird(name)) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21')
    assert fields.name == "weird(name)"
    assert fields.state == "S"


def test_stat_no_parens_raises() -> None:
    with pytest.raises(StatParseError):
        parse_stat("1234 not a stat line at all")


# ---------------------------------------------------------------------------
# Parser level: cmdline and io
# ---------------------------------------------------------------------------


def test_cmdline_nul_separated_args_joined_with_spaces() -> None:
    assert parse_cmdline("app\x00--fg\x00--cold") == "app --fg --cold"


def test_cmdline_empty_is_none() -> None:
    assert parse_cmdline("") is None
    assert parse_cmdline("\x00\x00") is None
    assert parse_cmdline("   ") is None


def test_cmdline_malformed_raw_text_does_not_crash() -> None:
    # No NULs, non-printable junk — treated as a single argv token.
    assert parse_cmdline("weird\x0bchars") == "weird\x0bchars"


def test_io_parses_read_and_write_bytes() -> None:
    read_bytes, write_bytes = parse_io(IO_TEXT)
    assert read_bytes == 67890
    assert write_bytes == 54321


# ---------------------------------------------------------------------------
# Collector level
# ---------------------------------------------------------------------------


def test_collector_issues_four_cat_commands_with_validated_pid() -> None:
    runner = FakeRunner(_inspector_files())
    ProcessInspector(runner).sample(24791)
    assert runner.calls == [
        ["cat", "/proc/24791/status"],
        ["cat", "/proc/24791/stat"],
        ["cat", "/proc/24791/cmdline"],
        ["cat", "/proc/24791/io"],
    ]


def test_collector_full_snapshot() -> None:
    snapshot = _full_snapshot()
    assert snapshot.pid == 24791
    assert snapshot.name == "com.instagram.android"
    assert snapshot.uid == 10203
    assert snapshot.state == "S (sleeping)"
    assert snapshot.threads == 42
    assert snapshot.priority == 11
    assert snapshot.nice == 0
    assert snapshot.virtual_memory_kb == 1842320
    assert snapshot.resident_memory_kb == 232448
    assert snapshot.rss_anon_kb == 216704
    assert snapshot.rss_file_kb == 14336
    assert snapshot.shared_memory_kb == 1408
    assert snapshot.command_line == "com.instagram.android --fg"
    assert snapshot.io_read_bytes == 67890
    assert snapshot.io_write_bytes == 54321
    assert snapshot.cpu_percent is None
    assert snapshot.memory_percent is None


def test_collector_falls_back_to_stat_when_status_missing_memory_fields() -> None:
    status_min = "Name:\tkernel.thread\nState:\tS (sleeping)\nThreads:\t3\n"
    # Field alignment mirrors STAT_TEXT: priority 11, nice 0, num_threads 3,
    # vsize 1842327552 bytes, rss 58112 pages (x4 KiB == 232448 KiB).
    stat_min = (
        "77 (kworker/u16:5) S 2 0 0 0 -1 69238880 0 0 0 0 316 355 152 552 "
        "11 0 3 256884 1842327561 1842327552 58112 18446744073709551615 0 0 0 "
        "0 0 0 0 2147483647 0 0 0 0 0 0 0 0 0 0 28 7 0 0 0 0 0"
    )
    runner = FakeRunner(
        {
            "/proc/77/status": status_min,
            "/proc/77/stat": stat_min,
            "/proc/77/cmdline": "",
            "/proc/77/io": "",
        }
    )
    snapshot = ProcessInspector(runner).sample(77)
    assert snapshot.pid == 77
    assert snapshot.name == "kernel.thread"
    assert snapshot.state == "S (sleeping)"
    assert snapshot.threads == 3
    assert snapshot.priority == 11
    assert snapshot.nice == 0
    assert snapshot.virtual_memory_kb == 1842327552 // 1024
    assert snapshot.resident_memory_kb == 58112 * 4
    assert snapshot.command_line is None
    assert snapshot.io_read_bytes is None
    assert snapshot.io_write_bytes is None


def test_collector_io_permission_denied_keeps_other_fields() -> None:
    denied = ADBCommandError(
        "shell cat /proc/24791/io", 1, stderr="cat: /proc/24791/io: Permission denied"
    )
    runner = RaisingRunner(_inspector_files(), "/proc/24791/io", denied)
    snapshot = ProcessInspector(runner).sample(24791)
    assert snapshot.io_read_bytes is None
    assert snapshot.io_write_bytes is None
    assert snapshot.name == "com.instagram.android"
    assert snapshot.threads == 42


def test_collector_missing_io_file_is_silent() -> None:
    missing = ADBCommandError(
        "shell cat /proc/24791/io",
        1,
        stderr="cat: /proc/24791/io: No such file or directory",
    )
    runner = RaisingRunner(_inspector_files(), "/proc/24791/io", missing)
    snapshot = ProcessInspector(runner).sample(24791)
    assert snapshot.io_read_bytes is None
    assert snapshot.io_write_bytes is None
    assert snapshot.pid == 24791


def test_collector_disappearing_process_raises() -> None:
    gone = ADBCommandError(
        "shell cat /proc/24791/status",
        1,
        stderr="cat: /proc/24791/status: No such file or directory",
    )
    runner = RaisingRunner(_inspector_files(), "/proc/24791/status", gone)
    with pytest.raises(ProcessDisappearedError) as exc_info:
        ProcessInspector(runner).sample(24791)
    assert exc_info.value.pid == 24791


def test_collector_permission_denied_status_means_unavailable_not_gone() -> None:
    denied = ADBCommandError(
        "shell cat /proc/24791/status",
        1,
        stderr="cat: /proc/24791/status: Permission denied",
    )
    runner = RaisingRunner(_inspector_files(), "/proc/24791/status", denied)
    snapshot = ProcessInspector(runner).sample(24791)
    assert snapshot.pid == 24791
    assert snapshot.uid is None  # uid only exists in status
    assert snapshot.name == "com.instagram.android"  # falls back to stat comm
    assert snapshot.threads == 42  # from stat num_threads


def test_collector_malformed_stat_keeps_status_data() -> None:
    garbage_stat = "this is not a stat line"
    runner = FakeRunner(
        {
            "/proc/24791/status": STATUS_TEXT,
            "/proc/24791/stat": garbage_stat,
            "/proc/24791/cmdline": CMDLINE_TEXT,
            "/proc/24791/io": IO_TEXT,
        }
    )
    snapshot = ProcessInspector(runner).sample(24791)
    assert snapshot.name == "com.instagram.android"
    assert snapshot.priority is None
    assert snapshot.nice is None
    assert snapshot.threads == 42  # status Threads wins over missing stat
    assert snapshot.virtual_memory_kb == 1842320


def test_collector_process_info_association_copies_cpu_and_memory() -> None:
    class _Info:
        pid = 24791
        cpu_percent = 8.8
        memory_percent = 12.3

    snapshot = ProcessInspector(FakeRunner(_inspector_files())).sample(24791, _Info())
    assert snapshot.cpu_percent == 8.8
    assert snapshot.memory_percent == 12.3


def test_collector_rejects_invalid_pids() -> None:
    inspector = ProcessInspector(FakeRunner(_inspector_files()))
    for bad in ("24791", 0, -1, 1.5, True):
        with pytest.raises(ValueError):
            inspector.sample(bad)


def test_inspector_modules_never_import_subprocess() -> None:
    for name in ("inspector_models.py", "inspector_parser.py", "inspector_collector.py"):
        source = (ROOT / "src" / "android_task_manager" / "process" / name).read_text(
            encoding="utf-8"
        )
        assert "subprocess" not in source, f"{name} must not touch subprocess"
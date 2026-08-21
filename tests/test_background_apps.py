"""Tests for background user-app intelligence (pure layers).

Covers the classification ("background user app"), the process-to-
application identity mapping, per-application aggregation, foreground
exclusion, unknown-state honesty, and the foreground-activity parser —
all against fixed fixtures, no device.
"""

from __future__ import annotations

from datetime import datetime

from android_task_manager.applications.models import (
    AppCategory,
    AppInfo,
    ApplicationSnapshot,
)
from android_task_manager.background.builder import build_background_apps
from android_task_manager.background.foreground import parse_foreground_output
from android_task_manager.background.models import BackgroundAppState
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot


def _proc(
    pid: int,
    name: str,
    uid: int | None = 10000,
    cpu: float | None = 1.0,
    mem: float | None = 1.0,
    category: ProcessCategory | None = None,
) -> ProcessInfo:
    resolved_category = category
    if resolved_category is None:
        if name.startswith("["):
            resolved_category = ProcessCategory.KERNEL_THREAD
        elif uid is None or uid < 10000:
            resolved_category = ProcessCategory.SYSTEM
        else:
            resolved_category = ProcessCategory.USER
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=uid,
        state="S",
        cpu_percent=cpu,
        memory_percent=mem,
        category=resolved_category,
    )


def _app(
    package: str,
    uid: int | None = 10000,
    category: AppCategory = AppCategory.USER,
    label: str | None = None,
) -> AppInfo:
    return AppInfo(package_name=package, uid=uid, category=category, label=label)


def _inventory(*apps: AppInfo, timestamp: float = 1.0) -> ApplicationSnapshot:
    return ApplicationSnapshot(timestamp=timestamp, applications=list(apps))


def _processes(*procs: ProcessInfo, timestamp: float = 2.0) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=timestamp, processes=list(procs))


def _memory(total_kb: int = 4_000_000) -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=1.0,
        total_kb=total_kb,
        free_kb=0,
        available_kb=total_kb // 2,
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )


def _foreground(package: str | None, available: bool = True) -> object:
    from android_task_manager.background.models import ForegroundSnapshot

    return ForegroundSnapshot(
        timestamp=1.0, package_name=package, available=available
    )


# ---------------------------------------------------------------------------
# Phase 2: classification
# ---------------------------------------------------------------------------


def test_system_processes_are_excluded() -> None:
    snapshot = build_background_apps(
        _processes(
            _proc(1, "system_server", uid=1000),
            _proc(2, "surfaceflinger", uid=1000),
            _proc(3, "[kworker/0:1]", uid=0),
            _proc(4, "com.android.systemui", uid=1000),
            _proc(5, "vendor.qti.hardware", uid=0),
        ),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


def test_user_applications_are_included() -> None:
    snapshot = build_background_apps(
        _processes(_proc(8150, "com.whatsapp", uid=10001)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground("com.launcher"),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.whatsapp"]


def test_system_category_packages_never_appear_even_with_processes() -> None:
    snapshot = build_background_apps(
        _processes(_proc(10, "com.android.chrome", uid=10002)),
        _inventory(
            _app("com.android.chrome", uid=10002, category=AppCategory.SYSTEM)
        ),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


def test_unknown_category_packages_are_excluded() -> None:
    snapshot = build_background_apps(
        _processes(_proc(11, "com.unknown.vendor", uid=10003)),
        _inventory(_app("com.unknown.vendor", uid=10003, category=AppCategory.UNKNOWN)),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


def test_process_without_verified_identity_is_dropped() -> None:
    # A USER-uid process whose package is NOT in the inventory: dropped.
    snapshot = build_background_apps(
        _processes(_proc(12, "com.not.installed", uid=10999)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


# ---------------------------------------------------------------------------
# Edge inputs
# ---------------------------------------------------------------------------


def test_empty_process_snapshot_yields_empty() -> None:
    snapshot = build_background_apps(
        _processes(),
        _inventory(_app("com.whatsapp")),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


def test_none_process_snapshot_yields_empty() -> None:
    snapshot = build_background_apps(
        None, _inventory(_app("com.whatsapp")), _foreground(None), _memory()
    )
    assert snapshot.entries == []


def test_empty_inventory_yields_empty() -> None:
    snapshot = build_background_apps(
        _processes(_proc(20, "com.whatsapp", uid=10001)),
        _inventory(),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


def test_none_inventory_yields_empty() -> None:
    snapshot = build_background_apps(
        _processes(_proc(21, "com.whatsapp", uid=10001)), None, _foreground(None)
    )
    assert snapshot.entries == []


def test_application_without_running_process_is_absent() -> None:
    snapshot = build_background_apps(
        _processes(_proc(22, "com.whatsapp", uid=10001)),
        _inventory(_app("com.whatsapp", uid=10001), _app("com.instagram", uid=10002)),
        _foreground(None),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.whatsapp"]


def test_process_with_unknown_uid_resolves_by_name() -> None:
    snapshot = build_background_apps(
        _processes(_proc(23, "com.whatsapp", uid=None)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground("com.launcher"),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.whatsapp"]
    assert snapshot.entries[0].uid == 10001


def test_process_with_unknown_uid_and_unmatched_name_is_dropped() -> None:
    snapshot = build_background_apps(
        _processes(_proc(24, "unknown_proc", uid=None)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


def test_system_uid_processes_never_match_by_name() -> None:
    # A system-uid process that happens to share a user app's name prefix
    # must not be attributed to it (category gate runs first).
    snapshot = build_background_apps(
        _processes(_proc(25, "com.whatsapp", uid=1000)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground(None),
        _memory(),
    )
    assert snapshot.entries == []


# ---------------------------------------------------------------------------
# Phase 3: process -> application mapping and aggregation
# ---------------------------------------------------------------------------


def test_multiple_processes_aggregate_into_one_entry() -> None:
    snapshot = build_background_apps(
        _processes(
            _proc(30, "com.whatsapp", uid=10001, cpu=0.3, mem=5.0),
            _proc(31, "com.whatsapp:push", uid=10001, cpu=0.2, mem=2.0),
            _proc(32, "com.whatsapp:sandboxed0", uid=10001, cpu=0.1, mem=1.0),
        ),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground("com.launcher"),
        _memory(total_kb=1_000_000),
    )
    assert len(snapshot.entries) == 1
    entry = snapshot.entries[0]
    assert entry.package_name == "com.whatsapp"
    assert entry.pids == (30, 31, 32)
    assert entry.cpu_percent == 0.6
    assert entry.memory_percent == 8.0
    assert entry.memory_kb == 80_000


def test_cpu_aggregation_treats_missing_metrics_honestly() -> None:
    snapshot = build_background_apps(
        _processes(
            _proc(40, "com.a", uid=10001, cpu=0.5, mem=None),
            _proc(41, "com.a:svc", uid=10001, cpu=None, mem=3.0),
        ),
        _inventory(_app("com.a", uid=10001)),
        _foreground(None),
        _memory(),
    )
    entry = snapshot.entries[0]
    assert entry.cpu_percent == 0.5
    assert entry.memory_percent == 3.0


def test_all_metrics_missing_stay_none() -> None:
    snapshot = build_background_apps(
        _processes(_proc(42, "com.b", uid=10005, cpu=None, mem=None)),
        _inventory(_app("com.b", uid=10005)),
        _foreground(None),
        _memory(),
    )
    entry = snapshot.entries[0]
    assert entry.cpu_percent is None
    assert entry.memory_percent is None
    assert entry.memory_kb is None


def test_memory_kb_derived_from_memory_snapshot_total() -> None:
    snapshot = build_background_apps(
        _processes(_proc(43, "com.c", uid=10006, cpu=0.0, mem=12.5)),
        _inventory(_app("com.c", uid=10006)),
        _foreground(None),
        _memory(total_kb=2_000_000),
    )
    assert snapshot.entries[0].memory_kb == 250_000


def test_memory_kb_none_without_memory_snapshot() -> None:
    snapshot = build_background_apps(
        _processes(_proc(44, "com.d", uid=10007, cpu=0.0, mem=12.5)),
        _inventory(_app("com.d", uid=10007)),
        _foreground(None),
        None,
    )
    assert snapshot.entries[0].memory_percent == 12.5
    assert snapshot.entries[0].memory_kb is None


def test_shared_uid_disambiguated_by_name_boundary() -> None:
    # Two packages share one UID (sharedUserId); the process name picks
    # the right owner, and a prefix must not leak into a sibling package.
    snapshot = build_background_apps(
        _processes(
            _proc(50, "com.shared.two", uid=10008),
            _proc(51, "com.shared.two:svc", uid=10008),
        ),
        _inventory(
            _app("com.shared.one", uid=10008),
            _app("com.shared.two", uid=10008),
        ),
        _foreground(None),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.shared.two"]
    assert snapshot.entries[0].pids == (50, 51)


def test_shared_uid_without_name_match_uses_deterministic_owner() -> None:
    snapshot = build_background_apps(
        _processes(_proc(52, "totally.different", uid=10009)),
        _inventory(
            _app("com.zeta", uid=10009),
            _app("com.alpha", uid=10009),
        ),
        _foreground(None),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.alpha"]


def test_prefix_does_not_leak_across_similar_package_names() -> None:
    snapshot = build_background_apps(
        _processes(_proc(53, "com.example.app", uid=10010)),
        _inventory(
            _app("com.example.ap", uid=10011),
            _app("com.example.app", uid=10010),
        ),
        _foreground(None),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.example.app"]


# ---------------------------------------------------------------------------
# Phase 8: foreground vs background vs unknown
# ---------------------------------------------------------------------------


def test_foreground_application_excluded_from_background_list() -> None:
    snapshot = build_background_apps(
        _processes(
            _proc(60, "com.fg.app", uid=10012),
            _proc(61, "com.bg.app", uid=10013),
        ),
        _inventory(
            _app("com.fg.app", uid=10012),
            _app("com.bg.app", uid=10013),
        ),
        _foreground("com.fg.app"),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == ["com.bg.app"]
    assert snapshot.entries[0].state is BackgroundAppState.BACKGROUND


def test_unknown_foreground_state_keeps_states_unknown() -> None:
    snapshot = build_background_apps(
        _processes(_proc(62, "com.some.app", uid=10014)),
        _inventory(_app("com.some.app", uid=10014)),
        _foreground(None, available=False),
        _memory(),
    )
    assert snapshot.entries[0].state is BackgroundAppState.UNKNOWN


def test_unavailable_foreground_signal_is_not_a_background_claim() -> None:
    snapshot = build_background_apps(
        _processes(_proc(63, "com.other.app", uid=10015)),
        _inventory(_app("com.other.app", uid=10015)),
        None,
        _memory(),
    )
    assert snapshot.entries[0].state is BackgroundAppState.UNKNOWN


def test_entries_sorted_by_memory_then_cpu_then_name() -> None:
    snapshot = build_background_apps(
        _processes(
            _proc(70, "com.small", uid=10016, cpu=9.0, mem=1.0),
            _proc(71, "com.big", uid=10017, cpu=0.1, mem=9.0),
            _proc(72, "com.mid", uid=10018, cpu=5.0, mem=5.0),
        ),
        _inventory(
            _app("com.big", uid=10017),
            _app("com.mid", uid=10018),
            _app("com.small", uid=10016),
        ),
        _foreground(None),
        _memory(),
    )
    assert [e.package_name for e in snapshot.entries] == [
        "com.big",
        "com.mid",
        "com.small",
    ]


# ---------------------------------------------------------------------------
# Foreground parser
# ---------------------------------------------------------------------------


_DUMPSYS_OUTPUT = """
ACTIVITY MANAGER activities (dumpsys activity activities)
Display #0 (activities from top to bottom):
* Hist #0: ActivityRecord{5b4fac2 u0 com.example.front/.MainActivity t123}
   Intent { cmp=com.example.front/.MainActivity }
  mResumedActivity: ActivityRecord{5b4fac2 u0 com.example.front/.MainActivity t123}
"""


def test_foreground_parser_reads_resumed_activity() -> None:
    snapshot = parse_foreground_output(_DUMPSYS_OUTPUT, timestamp=7.0)
    assert snapshot.available is True
    assert snapshot.package_name == "com.example.front"
    assert snapshot.timestamp == 7.0


def test_foreground_parser_supports_legacy_focused_activity() -> None:
    text = "mFocusedActivity: ActivityRecord{abc u0 com.old.app/.Main t5}\n"
    snapshot = parse_foreground_output(text)
    assert snapshot.available is True
    assert snapshot.package_name == "com.old.app"


def test_foreground_parser_fails_closed_on_garbage() -> None:
    snapshot = parse_foreground_output("total nonsense\nno markers here\n")
    assert snapshot.available is False
    assert snapshot.package_name is None


def test_foreground_parser_rejects_invalid_package() -> None:
    text = "mResumedActivity: ActivityRecord{abc u0 bad;package/x y z t1}\n"
    snapshot = parse_foreground_output(text)
    assert snapshot.available is False
    assert snapshot.package_name is None


def test_foreground_parser_empty_input() -> None:
    snapshot = parse_foreground_output("")
    assert snapshot.available is False


# ---------------------------------------------------------------------------
# Last-seen annotation helper (presentation-layer tracker)
# ---------------------------------------------------------------------------


def test_last_seen_tracker_updates_and_clears() -> None:
    from android_task_manager.background.builder import build_background_apps as build
    from android_task_manager.background.tracker import LastSeenTracker

    tracker = LastSeenTracker()
    first = build(
        _processes(_proc(80, "com.track.me", uid=10019)),
        _inventory(_app("com.track.me", uid=10019)),
        _foreground(None),
        _memory(),
    )
    when = datetime(2026, 1, 1, 12, 0, 0)
    annotated = tracker.annotate(first, when)
    assert annotated.entries[0].last_seen == when

    # A later observation refreshes the stamp.
    later = datetime(2026, 1, 1, 12, 0, 30)
    annotated = tracker.annotate(first, later)
    assert annotated.entries[0].last_seen == later

    # Clearing (disconnect) removes every stamp: nothing stale survives.
    tracker.clear()
    cleared = tracker.annotate(first, None)
    assert cleared.entries[0].last_seen is None


# ---------------------------------------------------------------------------
# Phase 4: application-name (label) resolution
# ---------------------------------------------------------------------------


def test_label_resolved_from_explicit_label_map() -> None:
    snapshot = build_background_apps(
        _processes(_proc(90, "com.whatsapp", uid=10001, cpu=0.5, mem=3.0)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground("com.launcher"),
        _memory(),
        labels={"com.whatsapp": "WhatsApp"},
    )
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].label == "WhatsApp"
    assert snapshot.entries[0].package_name == "com.whatsapp"


def test_label_falls_back_to_inventory_label() -> None:
    snapshot = build_background_apps(
        _processes(_proc(91, "com.whatsapp", uid=10001)),
        _inventory(_app("com.whatsapp", uid=10001, label="WhatsApp")),
        _foreground("com.launcher"),
        _memory(),
    )
    assert snapshot.entries[0].label == "WhatsApp"


def test_label_falls_back_to_package_name_when_unresolved() -> None:
    # An explicit ``None`` label means "not resolved": the builder keeps it
    # ``None`` and the GUI falls back to the package name (never invents one).
    snapshot = build_background_apps(
        _processes(_proc(92, "com.whatsapp", uid=10001)),
        _inventory(_app("com.whatsapp", uid=10001)),
        _foreground("com.launcher"),
        _memory(),
        labels={"com.whatsapp": None},
    )
    assert snapshot.entries[0].label is None


def test_label_missing_in_map_falls_back_to_inventory_label() -> None:
    snapshot = build_background_apps(
        _processes(_proc(93, "com.whatsapp", uid=10001)),
        _inventory(_app("com.whatsapp", uid=10001, label="WhatsApp")),
        _foreground("com.launcher"),
        _memory(),
        labels={"com.other": "Other"},
    )
    assert snapshot.entries[0].label == "WhatsApp"


def test_label_resolution_across_aggregated_processes() -> None:
    # All processes of one app share the same human-readable label.
    snapshot = build_background_apps(
        _processes(
            _proc(95, "com.whatsapp", uid=10001, cpu=0.3, mem=5.0),
            _proc(96, "com.whatsapp:push", uid=10001, cpu=0.2, mem=2.0),
        ),
        _inventory(_app("com.whatsapp", uid=10001, label="WhatsApp")),
        _foreground("com.launcher"),
        _memory(total_kb=1_000_000),
    )
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].label == "WhatsApp"
    assert snapshot.entries[0].pids == (95, 96)


def test_system_processes_never_receive_a_label() -> None:
    snapshot = build_background_apps(
        _processes(
            _proc(1, "system_server", uid=1000),
            _proc(2, "com.android.systemui", uid=1000),
        ),
        _inventory(_app("com.android.systemui", uid=1000, category=AppCategory.SYSTEM)),
        _foreground(None),
        _memory(),
        labels={"com.android.systemui": "System UI"},
    )
    assert snapshot.entries == []

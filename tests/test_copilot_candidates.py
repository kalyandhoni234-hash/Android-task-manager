"""Tests for the deterministic Copilot candidate-generation layer."""

from __future__ import annotations

import time

from android_task_manager.background.models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
    ForegroundSnapshot,
)
from android_task_manager.copilot.candidates import build_candidates
from android_task_manager.copilot.intent import INTENT_GENERAL
from android_task_manager.copilot.models import ProcessSafetyClass
from android_task_manager.memory.models import MemorySnapshot


def _snapshot(
    entries: list[BackgroundAppEntry],
    foreground: str | None = None,
) -> tuple[BackgroundAppsSnapshot, ForegroundSnapshot]:
    bg = BackgroundAppsSnapshot(timestamp=time.time(), entries=entries)
    fg = ForegroundSnapshot(
        timestamp=time.time(),
        package_name=foreground,
        available=foreground is not None,
    )
    return bg, fg


def _entry(
    pkg: str,
    cpu: float | None = 1.0,
    mem: float | None = 5.0,
    mem_kb: int | None = 200_000,
    state: BackgroundAppState = BackgroundAppState.BACKGROUND,
) -> BackgroundAppEntry:
    return BackgroundAppEntry(
        package_name=pkg,
        uid=10000,
        pids=(1,),
        cpu_percent=cpu,
        memory_percent=mem,
        memory_kb=mem_kb,
        state=state,
    )


def test_general_intent_produces_no_candidates() -> None:
    bg, fg = _snapshot([_entry("com.instagram.android")])
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages=None,
        intent=INTENT_GENERAL,
    )
    assert candidates == ()
    assert protected == ()


def test_gaming_intent_ranks_background_user_apps() -> None:
    bg, fg = _snapshot(
        [
            _entry("com.instagram.android", mem=11.0, mem_kb=11_000_000),
            _entry("com.whatsapp", mem=3.9, mem_kb=3_900_000),
            _entry("com.google.android.gms", mem=8.0, mem_kb=8_000_000),
        ],
        foreground="com.arena.zooba",
    )
    user_packages = {
        "com.instagram.android",
        "com.whatsapp",
        "com.google.android.gms",
        "com.arena.zooba",
    }
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages=user_packages,
        intent="gaming",
    )
    assert len(candidates) == 3
    # Ranked by memory share desc.
    assert candidates[0].name == "com.instagram.android"
    assert candidates[0].safety is ProcessSafetyClass.SAFE_CANDIDATE
    assert candidates[0].estimated_reclaimable_kb == 11_000_000
    assert candidates[2].name == "com.whatsapp"


def test_foreground_app_is_protected_not_candidate() -> None:
    bg, fg = _snapshot(
        [
            _entry("com.arena.zooba", mem=30.0),
            _entry("com.instagram.android", mem=10.0),
        ],
        foreground="com.arena.zooba",
    )
    user_packages = {"com.arena.zooba", "com.instagram.android"}
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages=user_packages,
        intent="gaming",
    )
    assert len(candidates) == 1
    assert candidates[0].name == "com.instagram.android"
    protected_names = {p.name for p in protected}
    assert "com.arena.zooba" in protected_names
    assert "currently in the foreground" in next(
        p.reason for p in protected if p.name == "com.arena.zooba"
    )


def test_system_apps_never_candidates() -> None:
    from android_task_manager.applications.models import (
        AppCategory,
        AppInfo,
        ApplicationSnapshot,
    )

    bg, fg = _snapshot(
        [
            _entry("com.google.android.gms", mem=30.0),
            _entry("com.instagram.android", mem=5.0),
        ],
        foreground="com.instagram.android",
    )
    apps = ApplicationSnapshot(
        timestamp=time.time(),
        applications=[
            AppInfo(package_name="com.google.android.gms", category=AppCategory.SYSTEM),
            AppInfo(package_name="com.instagram.android", category=AppCategory.USER),
        ],
    )
    user_packages = {"com.instagram.android"}
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=apps,
        user_packages=user_packages,
        intent="gaming",
    )
    candidate_names = [c.name for c in candidates]
    assert "com.google.android.gms" not in candidate_names
    protected_names = {p.name for p in protected}
    assert "com.google.android.gms" in protected_names


def test_unverified_package_never_candidate() -> None:
    # A process/package not in the verified user set is protected.
    bg, fg = _snapshot([_entry("com.malicious.evil", mem=50.0)])
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages={"com.legit.app"},
        intent="gaming",
    )
    assert candidates == ()
    protected_names = {p.name for p in protected}
    assert "com.malicious.evil" in protected_names


def test_invalid_package_name_skipped() -> None:
    # A non-package "process" entry should never become a candidate.
    bg, fg = _snapshot(
        [
            _entry("native_daemon", mem=99.0),
            _entry("com.instagram.android", mem=5.0),
        ]
    )
    candidates, _ = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages={"com.instagram.android"},
        intent="gaming",
    )
    assert [c.name for c in candidates] == ["com.instagram.android"]


def test_memory_estimate_from_share_when_kb_unknown() -> None:
    memory = MemorySnapshot(
        timestamp=time.time(),
        total_kb=1_000_000,
        free_kb=100_000,
        available_kb=200_000,
        buffers_kb=0,
        cached_kb=0,
        swap_cached_kb=0,
    )
    bg, fg = _snapshot(
        [
            _entry(
                "com.instagram.android",
                mem=10.0,
                mem_kb=None,
            )
        ]
    )
    candidates, _ = build_candidates(
        background=bg,
        foreground=fg,
        memory=memory,
        app_snapshot=None,
        user_packages={"com.instagram.android"},
        intent="gaming",
    )
    assert candidates[0].estimated_reclaimable_kb == 100_000


def test_foreground_app_no_memory_estimate() -> None:
    # Foreground apps are protected, not candidates, so no estimate is offered.
    bg, fg = _snapshot(
        [_entry("com.instagram.android", mem=10.0)],
        foreground="com.instagram.android",
    )
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages={"com.instagram.android"},
        intent="gaming",
    )
    assert candidates == ()
    assert any(p.name == "com.instagram.android" for p in protected)


def test_empty_background_produces_nothing() -> None:
    bg, fg = _snapshot([], foreground="com.x")
    candidates, protected = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages=set(),
        intent="gaming",
    )
    assert candidates == ()
    assert protected == ()


def test_unknown_state_app_is_candidate() -> None:
    bg, fg = _snapshot(
        [_entry("com.instagram.android", state=BackgroundAppState.UNKNOWN)]
    )
    candidates, _ = build_candidates(
        background=bg,
        foreground=fg,
        memory=None,
        app_snapshot=None,
        user_packages={"com.instagram.android"},
        intent="close_app",
    )
    assert len(candidates) == 1
    assert "without a confirmed foreground state" in candidates[0].reason

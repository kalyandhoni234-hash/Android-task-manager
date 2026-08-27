"""UID-or-Unknown attribution guard (Priority #7, RED spec).

Locks the hardened background-load attribution contract on
``background.builder.build_background_apps``:

* ownership requires UID backing — an installed user package whose UID
  equals the process UID;
* inside a UID group the existing deterministic disambiguation holds
  (exact process name > ``<package>:suffix`` > alphabetically first);
* ALL name-only fallbacks are gone: no global exact/prefix matching when
  the UID cannot be resolved, and the ``package + "."`` prefix rule is
  abolished (Android extension processes use ``:``, never ``.``);
* unresolvable processes are dropped entirely (never guessed as Unknown
  entries into ranking).

Device-free, built on the same fixtures/style as ``test_background_apps``.
"""

from __future__ import annotations

from android_task_manager.applications.models import (
    AppCategory,
    AppInfo,
    ApplicationSnapshot,
)
from android_task_manager.background.builder import build_background_apps
from android_task_manager.background.models import ForegroundSnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot


def _proc(pid: int, name: str, *, uid: int | None = None) -> ProcessInfo:
    if uid is None or uid < 10000:
        category: ProcessCategory = ProcessCategory.SYSTEM
    else:
        category = ProcessCategory.USER
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=uid,
        state="S",
        cpu_percent=5.0,
        memory_percent=2.0,
        category=category,
        ppid=1,
    )


def _processes(*procs: ProcessInfo) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=0.0, processes=list(procs))


def _app(package: str, uid: int | None) -> AppInfo:
    return AppInfo(package_name=package, uid=uid, category=AppCategory.USER)


def _foreground(snapshot_package: str | None):
    return ForegroundSnapshot(
        timestamp=0.0,
        package_name=snapshot_package or "",
        available=snapshot_package is not None,
    )


def _packages(snapshot):
    return [e.package_name for e in snapshot.entries]


def _inventory(*apps: AppInfo) -> ApplicationSnapshot:
    return ApplicationSnapshot(timestamp=1.0, applications=list(apps))


# --------------------------------------------------------------------------
# Existing valid attribution remains unchanged
# --------------------------------------------------------------------------

def test_uid_backed_exact_attribution_unchanged():
    snap = build_background_apps(
        _processes(_proc(10, "com.whatsapp", uid=10001)),
        _inventory(
            _app("com.whatsapp", 10001),
            _app("com.instagram", 10002),
        ),
        _foreground("com.instagram"),
        labels=None,
    )
    assert _packages(snap) == ["com.whatsapp"]


def test_uid_backed_suffix_process_still_attributes():
    # com.whatsapp:push is an extension process of the UID-owned package.
    snap = build_background_apps(
        _processes(_proc(11, "com.whatsapp:push", uid=10001)),
        _inventory(_app("com.whatsapp", 10001)),
        _foreground(None),
        labels=None,
    )
    assert _packages(snap) == ["com.whatsapp"]


def test_shared_uid_alphabetical_tiebreak_preserved():
    # Two user packages share one UID (sharedUserId); the process name gives
    # no hint. The documented deterministic tie-break (alphabetically first)
    # must survive the hardening.
    snap = build_background_apps(
        _processes(_proc(12, "something.else", uid=10100)),
        _inventory(_app("com.zeta", 10100), _app("com.alpha", 10100)),
        _foreground(None),
        labels=None,
    )
    assert _packages(snap) == ["com.alpha"]


# --------------------------------------------------------------------------
# Name-only attribution eliminated
# --------------------------------------------------------------------------

def test_exact_name_without_uid_is_no_longer_attributed():
    # Previously: global exact-name fallback attributed this process.
    # Now: without UID evidence the honest answer is "drop it".
    snap = build_background_apps(
        _processes(_proc(13, "com.whatsapp", uid=None)),
        _inventory(_app("com.whatsapp", 10001)),
        _foreground(None),
        labels=None,
    )
    assert _packages(snap) == []


def test_matching_name_with_different_uid_is_rejected():
    # A hostile/renamed process claims a well-known package name while its
    # UID belongs to nothing installed. Name equality must NOT win.
    snap = build_background_apps(
        _processes(_proc(14, "com.whatsapp", uid=10999)),
        _inventory(_app("com.whatsapp", 10001)),
        _foreground(None),
        labels=None,
    )
    assert _packages(snap) == []


# --------------------------------------------------------------------------
# The '.' boundary bug
# --------------------------------------------------------------------------

def test_dot_prefix_process_cannot_steal_attribution():
    # Android names extension processes <pkg>:suffix — never <pkg>.more.
    # Old rule startswith(package + ".") let process "com.foo.application"
    # be attributed to package "com.foo".
    snap = build_background_apps(
        _processes(_proc(15, "com.foo.application", uid=None)),
        _inventory(_app("com.foo", 10010)),
        _foreground(None),
        labels=None,
    )
    assert _packages(snap) == []


def test_dot_prefix_no_longer_steers_shared_uid_selection():
    # Inside a UID group the '.' rule used to steer selection toward the
    # prefixing package; after removal only exact/: rules steer, otherwise
    # the deterministic alphabetical tie-break applies.
    snap = build_background_apps(
        _processes(_proc(16, "com.foo.application", uid=10100)),
        _inventory(_app("com.foo", 10100), _app("com.bar", 10100)),
        _foreground(None),
        labels=None,
    )
    # Neither candidate's name relates by exact/':' rules, so the choice is
    # the documented alphabetical tie-break — NOT the '.'-prefixed com.foo.
    assert _packages(snap) == ["com.bar"]

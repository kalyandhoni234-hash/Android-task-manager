"""Regression tests for real-device application discovery (uid: format).

The Vivo V2026 (and likely other Android 11+ devices) outputs:

    package:/path/base.apk=com.package.name versionCode:42 uid:12345

with a COLON separator for uid, not an equals sign.  The existing parser
regex only accepted uid=, causing zero packages to be parsed from real
device output.  These tests prove the defect exists and that the fix
handles both formats.
"""

from __future__ import annotations

from android_task_manager.applications.parser import (
    build_inventory,
    parse_inventory_lines,
)

# ---------------------------------------------------------------------------
# Real-device format (uid: colon separator) — from Vivo V2026 ADB output
# ---------------------------------------------------------------------------

_REAL_DEVICE_INVENTORY = (
    "package:/apex/com.android.tethering/priv-app/TetheringGoogle/TetheringGoogle.apk="
    "com.google.android.networkstack.tethering versionCode:30 uid:1073\n"
    "package:/system/app/Gba/Gba.apk=com.mediatek.gba versionCode:30 uid:1001\n"
    "package:/system/priv-app/ImsService/ImsService.apk=com.mediatek.ims "
    "versionCode:30 uid:1001\n"
    "package:/apex/com.android.apex.cts.shim/priv-app/CtsShimPriv/CtsShimPriv.apk="
    "com.android.cts.priv.ctsshim versionCode:30 uid:10198\n"
    "package:/data/app/~~5FxNFD0WV2bcYK9XftujYA==/com.google.android.youtube-"
    "kUnD4xZm-tSfwtjb1MQorQ==/base.apk=com.google.android.youtube "
    "versionCode:1561191873 uid:10181\n"
    "package:/data/app/~~abc123==/com.example.myapp-def456==/base.apk="
    "com.example.myapp versionCode:7 uid:10234\n"
)

# uid= format (existing, still supported)
_LEGACY_INVENTORY = (
    "package:/data/app/com.example.app-abc123/base.apk=com.example.app "
    "uid=10123 versionCode:42\n"
    "package:/data/app/org.open.source-1/base.apk=org.open.source uid=10124\n"
)

_SYSTEM_LIST = "package:com.android.settings\npackage:com.android.systemui\n"
_USER_LIST = "package:com.example.app\npackage:org.open.source\n"
_DISABLED_LIST = "package:org.open.source\n"


class TestRealDeviceUidColonFormat:
    """Regression: uid: (colon) must be parsed correctly."""

    def test_real_device_inventory_parses_packages(self) -> None:
        """The real-device output must yield > 0 parsed packages."""
        entries = parse_inventory_lines(_REAL_DEVICE_INVENTORY)
        assert len(entries) == 6

    def test_real_device_uid_colon_extracted(self) -> None:
        """uid:1073 must be parsed as uid=1073."""
        entries = parse_inventory_lines(_REAL_DEVICE_INVENTORY)
        tethering = entries["com.google.android.networkstack.tethering"]
        assert tethering.uid == 1073

    def test_real_device_uid_colon_various_values(self) -> None:
        """Multiple uid: values are extracted correctly."""
        entries = parse_inventory_lines(_REAL_DEVICE_INVENTORY)
        assert entries["com.mediatek.gba"].uid == 1001
        assert entries["com.android.cts.priv.ctsshim"].uid == 10198
        assert entries["com.google.android.youtube"].uid == 10181
        assert entries["com.example.myapp"].uid == 10234

    def test_real_device_version_code_extracted(self) -> None:
        """versionCode: is still extracted alongside uid:"""
        entries = parse_inventory_lines(_REAL_DEVICE_INVENTORY)
        assert entries["com.google.android.networkstack.tethering"].version_code == 30
        assert entries["com.google.android.youtube"].version_code == 1561191873
        assert entries["com.example.myapp"].version_code == 7

    def test_real_device_package_names_valid(self) -> None:
        """Parsed package names are valid identifiers."""
        entries = parse_inventory_lines(_REAL_DEVICE_INVENTORY)
        for name in entries:
            assert "." in name, f"Package name {name!r} looks invalid"
            assert " " not in name


class TestLegacyUidEqualsFormat:
    """Ensure the existing uid= format remains supported."""

    def test_legacy_inventory_still_parses(self) -> None:
        entries = parse_inventory_lines(_LEGACY_INVENTORY)
        assert len(entries) == 2

    def test_legacy_uid_values_extracted(self) -> None:
        entries = parse_inventory_lines(_LEGACY_INVENTORY)
        assert entries["com.example.app"].uid == 10123
        assert entries["org.open.source"].uid == 10124


class TestMixedFormats:
    """Both uid= and uid: in the same input must be handled."""

    def test_mixed_inventory_parses_all(self) -> None:
        mixed = _LEGACY_INVENTORY + _REAL_DEVICE_INVENTORY
        entries = parse_inventory_lines(mixed)
        assert len(entries) == 8  # 2 legacy + 6 real

    def test_mixed_uid_values_correct(self) -> None:
        mixed = _LEGACY_INVENTORY + _REAL_DEVICE_INVENTORY
        entries = parse_inventory_lines(mixed)
        assert entries["com.example.app"].uid == 10123
        assert entries["com.google.android.networkstack.tethering"].uid == 1073


class TestBuildInventoryWithRealDeviceFormat:
    """build_inventory must produce non-empty results from real device output."""

    def test_build_inventory_real_device_non_empty(self) -> None:
        apps = build_inventory(
            _REAL_DEVICE_INVENTORY,
            system_text="",
            user_text="package:com.google.android.youtube\npackage:com.example.myapp\n",
            disabled_text="",
        )
        assert len(apps) == 6

    def test_build_inventory_real_device_categories(self) -> None:
        from android_task_manager.applications.models import AppCategory

        apps = build_inventory(
            _REAL_DEVICE_INVENTORY,
            system_text="",
            user_text="package:com.google.android.youtube\npackage:com.example.myapp\n",
            disabled_text="",
        )
        by_name = {a.package_name: a for a in apps}
        assert by_name["com.google.android.youtube"].category is AppCategory.USER
        assert by_name["com.example.myapp"].category is AppCategory.USER


class TestMalformedUidRecords:
    """Malformed uid fields cause the entire line to be skipped (fail-closed)."""

    def test_uid_non_numeric_skipped(self) -> None:
        line = "package:/data/app/x/base.apk=com.example.app uid=abc\n"
        entries = parse_inventory_lines(line)
        # uid=abc fails regex → entire line skipped (fail-closed)
        assert len(entries) == 0

    def test_uid_colon_non_numeric_skipped(self) -> None:
        line = "package:/data/app/x/base.apk=com.example.app uid:abc\n"
        entries = parse_inventory_lines(line)
        assert len(entries) == 0

    def test_no_uid_field(self) -> None:
        line = "package:/system/app/Settings/Settings.apk=com.android.settings\n"
        entries = parse_inventory_lines(line)
        assert entries["com.android.settings"].uid is None


class TestConsumerIntegration:
    """Verify downstream consumers receive parsed inventory correctly."""

    def test_background_builder_receives_real_device_inventory(self) -> None:
        from android_task_manager.applications.models import ApplicationSnapshot
        from android_task_manager.background.builder import build_background_apps
        from android_task_manager.process.models import (
            ProcessCategory,
            ProcessInfo,
            ProcessSnapshot,
        )

        apps = build_inventory(
            _REAL_DEVICE_INVENTORY,
            system_text="",
            user_text="package:com.google.android.youtube\npackage:com.example.myapp\n",
            disabled_text="",
        )
        snapshot = ApplicationSnapshot(timestamp=1.0, applications=tuple(apps))

        procs = ProcessSnapshot(
            timestamp=1.0,
            processes=(
                ProcessInfo(
                    pid=100, name="com.google.android.youtube", uid=10181,
                    state="S", cpu_percent=5.0, memory_percent=2.0,
                    category=ProcessCategory.USER,
                ),
            ),
        )

        bg = build_background_apps(processes=procs, inventory=snapshot, foreground=None)
        assert len(bg.entries) == 1
        assert bg.entries[0].package_name == "com.google.android.youtube"

    def test_capability_gate_works_with_real_device_inventory(self) -> None:
        from android_task_manager.action.capability import supported_actions
        from android_task_manager.applications.models import AppCategory

        apps = build_inventory(
            _REAL_DEVICE_INVENTORY,
            system_text="",
            user_text="package:com.google.android.youtube\npackage:com.example.myapp\n",
            disabled_text="",
        )
        by_name = {a.package_name: a for a in apps}

        yt = by_name["com.google.android.youtube"]
        actions = supported_actions(is_system=(yt.category is AppCategory.SYSTEM), enabled=yt.enabled)
        assert len(actions) >= 3  # at least LAUNCH, APP_INFO, FORCE_STOP

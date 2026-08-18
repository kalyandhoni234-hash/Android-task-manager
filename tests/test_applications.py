"""Application inventory/details parser + collector tests."""

import pytest

from android_task_manager.adb.exceptions import ADBDisconnectedError
from android_task_manager.applications import (
    AppCategory,
    ApplicationCollector,
    build_inventory,
    category_from_flags,
    enabled_from_value,
    install_location_for,
    parse_app_details,
    parse_inventory_lines,
    parse_name_list,
)

_INVENTORY = (
    "package:/data/app/com.example.app-abc123/base.apk=com.example.app uid=10123 versionCode:42\n"
    "package:/data/app/org.open.source-1/base.apk=org.open.source uid=10124\n"
    "package:/system/app/Settings/Settings.apk=com.android.settings\n"
    "junk line\n"
    "package:bad name with spaces\n"
    "package:/data/app/com.evil;rm/base.apk=com.evil;rm uid=1\n"
)

_SYSTEM_LIST = "package:com.android.settings\npackage:com.android.systemui\njunk\n"
_USER_LIST = "package:com.example.app\npackage:org.open.source\n"
_DISABLED_LIST = "package:org.open.source\n"


def test_parse_inventory_lines_extracts_all_fields() -> None:
    entries = parse_inventory_lines(_INVENTORY)
    assert set(entries) == {"com.example.app", "org.open.source", "com.android.settings"}
    assert entries["com.example.app"].apk_path == "/data/app/com.example.app-abc123/base.apk"
    assert entries["com.example.app"].uid == 10123
    assert entries["com.example.app"].version_code == 42
    assert entries["org.open.source"].version_code is None
    assert entries["com.android.settings"].uid is None


def test_parse_inventory_lines_skips_garbage_and_injection() -> None:
    entries = parse_inventory_lines(_INVENTORY)
    assert "com.evil;rm" not in entries
    assert "bad name with spaces" not in entries
    assert len(entries) == 3


def test_parse_inventory_lines_empty_input() -> None:
    assert parse_inventory_lines("") == {}


def test_parse_name_list_validates() -> None:
    assert parse_name_list(_SYSTEM_LIST) == {
        "com.android.settings",
        "com.android.systemui",
    }
    assert parse_name_list("package:bad name\njunk\n") == set()


def test_build_inventory_classifies_and_flags_disabled() -> None:
    apps = build_inventory(
        _INVENTORY,
        system_text=_SYSTEM_LIST,
        user_text=_USER_LIST,
        disabled_text=_DISABLED_LIST,
    )
    by_name = {app.package_name: app for app in apps}
    assert by_name["com.example.app"].category is AppCategory.USER
    assert by_name["com.example.app"].enabled is True
    assert by_name["com.android.settings"].category is AppCategory.SYSTEM
    assert by_name["org.open.source"].category is AppCategory.USER
    assert by_name["org.open.source"].enabled is False


def test_build_inventory_unknown_category_is_honest() -> None:
    apps = build_inventory(
        "package:/data/app/x/base.apk=com.ghost.app uid=9999\n",
        system_text="",
        user_text="",
        disabled_text="",
    )
    assert apps[0].category is AppCategory.UNKNOWN
    assert apps[0].enabled is True


def test_build_inventory_empty_lists() -> None:
    assert build_inventory("", system_text="", user_text="", disabled_text="") == []


def test_install_location_mapping() -> None:
    assert install_location_for("/data/app/x/base.apk") == "Internal storage"
    assert install_location_for("/system/app/Settings/Settings.apk") == "System partition"
    assert install_location_for("/mnt/expand/xyz/app/y/base.apk") == "Adopted storage"
    assert install_location_for(None) is None
    assert install_location_for("/weird/path/app.apk") == "Other"


def test_category_from_flags() -> None:
    assert category_from_flags(("SYSTEM", "HAS_CODE")) is AppCategory.SYSTEM
    assert category_from_flags(("UPDATED_SYSTEM_APP",)) is AppCategory.SYSTEM
    assert category_from_flags(("HAS_CODE", "ALLOW_CLEAR_USER_DATA")) is AppCategory.USER
    assert category_from_flags(()) is AppCategory.UNKNOWN


def test_enabled_from_value() -> None:
    assert enabled_from_value(0) is True
    assert enabled_from_value(1) is True
    assert enabled_from_value(2) is False
    assert enabled_from_value(3) is False
    assert enabled_from_value(4) is False
    assert enabled_from_value(None) is None


_DUMPSYS = """Packages:
  Package [com.example.app] (4e1b9d2):
    userId=10123
    pkg=Package{4e1b9d2 10123/com.example.app}
    codePath=/data/app/~~abc==/com.example.app-xyz==/base.apk
    resourcePath=/data/app/~~abc==/com.example.app-xyz==/base.apk
    versionCode=42 minSdk=26 targetSdk=34
    versionName=1.2.3
    flags=[ HAS_CODE ALLOW_CLEAR_USER_DATA ]
    privateFlags=[ PRIVATE_FLAG_ACTIVITIES_RESIZE_MODE_RESIZEABLE_VIA_SDK_VERSION ]
    firstInstallTime=2026-01-01 00:00:00
    lastUpdateTime=2026-02-01 00:00:00
    installerPackageName=com.android.vending
    signaturesPackage=com.example.app
    enabled=1
    stopped=false
    requested permissions:
      android.permission.INTERNET
      android.permission.ACCESS_NETWORK_STATE
    install permissions:
      android.permission.INTERNET: granted=true
    runtime permissions:
      android.permission.ACCESS_FINE_LOCATION: granted=true
    activities:
      com.example.app/.MainActivity
      com.example.app/.SecondaryActivity
    services:
      com.example.app/.MainService
    receivers:
      com.example.app/.BootReceiver
    providers:
      com.example.app/.MainProvider
Activity Resolver Table:
  Full MIME Types:
  Non-Data Actions:
    android.intent.action.MAIN:
      4e1b9d2 com.example.app/.MainActivity filter 0x1111000
        Action: "android.intent.action.MAIN"
        Category: "android.intent.category.LAUNCHER"
        AutoVerify=false
    android.intent.action.VIEW:
      4e1b9d2 com.example.app/.SecondaryActivity filter 0x1112000
    android.intent.category.LAUNCHER:
      4e1b9d2 com.example.app/.MainActivity filter 0x1111000
  Schemes:
  MIME Types:
"""


def test_parse_app_details_full_record() -> None:
    details = parse_app_details(_DUMPSYS, "com.example.app")
    assert details.parse_complete
    assert details.version_name == "1.2.3"
    assert details.version_code == 42
    assert details.uid == 10123
    assert details.apk_path == "/data/app/~~abc==/com.example.app-xyz==/base.apk"
    assert details.install_location == "Internal storage"
    assert details.category is AppCategory.USER
    assert details.enabled is True
    assert details.installer == "com.android.vending"
    assert "HAS_CODE" in details.flags
    assert "ALLOW_CLEAR_USER_DATA" in details.flags
    assert details.launchable_activity == "com.example.app/.MainActivity"
    assert details.activities == (
        "com.example.app/.MainActivity",
        "com.example.app/.SecondaryActivity",
    )
    assert details.services == ("com.example.app/.MainService",)
    assert details.receivers == ("com.example.app/.BootReceiver",)


def test_parse_app_details_not_installed_is_honest() -> None:
    details = parse_app_details("Package [com.other] (ab1):\n    userId=1\n", "com.gone.app")
    assert not details.parse_complete
    assert details.version_name is None
    assert details.category is AppCategory.UNKNOWN


def test_parse_app_details_garbage_input() -> None:
    details = parse_app_details("garbage\nnot a package dump\n", "com.example.app")
    assert not details.parse_complete


def test_parse_app_details_stops_at_next_package() -> None:
    text = (
        _DUMPSYS
        + "  Package [com.second.app] (ff00):\n    userId=999\n    versionName=9.9\n"
    )
    details = parse_app_details(text, "com.example.app")
    assert details.version_name == "1.2.3"
    assert details.uid == 10123
    second = parse_app_details(text, "com.second.app")
    assert second.version_name == "9.9"
    assert second.uid == 999


def test_parse_app_details_legacy_bare_header() -> None:
    text = "[com.example.app]:\n    versionCode=7\n    enabled=3\n"
    details = parse_app_details(text, "com.example.app")
    assert details.version_code == 7
    assert details.enabled is False


def test_parse_app_details_disabled_user_state() -> None:
    text = _DUMPSYS.replace("enabled=1", "enabled=3")
    details = parse_app_details(text, "com.example.app")
    assert details.enabled is False


def test_parse_app_details_system_app_classification() -> None:
    text = _DUMPSYS.replace(
        "flags=[ HAS_CODE ALLOW_CLEAR_USER_DATA ]",
        "flags=[ SYSTEM HAS_CODE ]",
    )
    details = parse_app_details(text, "com.example.app")
    assert details.category is AppCategory.SYSTEM


def test_parse_app_details_no_launcher() -> None:
    text = _DUMPSYS.replace(
        "    android.intent.action.MAIN:\n      4e1b9d2 com.example.app/.MainActivity filter 0x1111000\n",
        "    android.intent.action.MAIN:\n",
    )
    details = parse_app_details(text, "com.example.app")
    assert details.launchable_activity is None


# ---------------------------------------------------------------------------
# Collector (through the shared CommandRunner abstraction)
# ---------------------------------------------------------------------------


class _FakeRunner:
    def __init__(self, responses: dict[str, str], fails: dict[str, BaseException] | None = None) -> None:
        self.responses = responses
        self.fails = fails or {}
        self.calls: list[list[str]] = []
        self.timeouts: list[float | None] = []

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        self.timeouts.append(timeout)
        key = " ".join(args)
        if key in self.fails:
            raise self.fails[key]
        return self.responses.get(key, "")


def test_collect_makes_four_pm_reads_and_normalizes() -> None:
    runner = _FakeRunner(
        {
            "pm list packages -f -U --show-versioncode": _INVENTORY,
            "pm list packages -s": _SYSTEM_LIST,
            "pm list packages -3": _USER_LIST,
            "pm list packages -d": _DISABLED_LIST,
        }
    )
    collector = ApplicationCollector(runner, timeout=6.0)
    snapshot = collector.collect(timestamp=123.0)
    assert snapshot.timestamp == 123.0
    assert {a.package_name for a in snapshot.applications} == {
        "com.example.app",
        "org.open.source",
        "com.android.settings",
    }
    assert runner.calls == [
        ["pm", "list", "packages", "-f", "-U", "--show-versioncode"],
        ["pm", "list", "packages", "-s"],
        ["pm", "list", "packages", "-3"],
        ["pm", "list", "packages", "-d"],
    ]
    assert runner.timeouts == [6.0, 6.0, 6.0, 6.0]


def test_collect_surfaces_typed_adb_failure() -> None:
    runner = _FakeRunner(
        {"pm list packages -f -U --show-versioncode": ""},
        fails={"pm list packages -f -U --show-versioncode": ADBDisconnectedError("gone")},
    )
    collector = ApplicationCollector(runner)
    with pytest.raises(ADBDisconnectedError):
        collector.collect()


def test_collect_details_reads_dumpsys() -> None:
    runner = _FakeRunner({"dumpsys package com.example.app": _DUMPSYS})
    collector = ApplicationCollector(runner, timeout=8.0)
    details = collector.collect_details("com.example.app")
    assert details.parse_complete
    assert details.version_name == "1.2.3"
    assert runner.calls == [["dumpsys", "package", "com.example.app"]]
    assert runner.timeouts == [8.0]
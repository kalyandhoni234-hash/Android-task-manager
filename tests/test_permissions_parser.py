"""Unit tests for the ``dumpsys package`` permission parser.

No device required: the fixtures are hand-built ``dumpsys package`` sample
text modeled on the publicly documented output structure (package header,
``requested permissions:`` block, ``install permissions:`` section, and a
``User 0:`` block nesting ``runtime permissions:``), and the parser is
defensive about whitespace and section variance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from android_task_manager.permissions import parse_dumpsys_package
from android_task_manager.permissions.models import (
    PERMISSION_INSTALL,
    PERMISSION_RUNTIME,
)

# ---------------------------------------------------------------------------
# Fixtures: hand-built dumpsys package sample output.
# ---------------------------------------------------------------------------

PACKAGE_DUMP = """Package [com.example.app] (4f9a2c1):
    userId=10200
    targetSdk=34
    versionCode=1020000 minSdk=26
    requested permissions:
        android.permission.INTERNET
        android.permission.ACCESS_NETWORK_STATE
        android.permission.READ_SMS
    install permissions:
        android.permission.INTERNET: granted=true
        android.permission.ACCESS_NETWORK_STATE: granted=true
        android.permission.READ_CONTACTS: granted=false
        android.permission.POST_NOTIFICATIONS: granted=true
    User 0:
        runtime permissions:
            android.permission.READ_SMS: granted=true, flags=[USER_SET|USER_FIXED]
            android.permission.SEND_SMS: granted=false, flags=[USER_SET]
            android.permission.READ_PHONE_STATE: granted=true
            android.permission.CAMERA: granted=false, flags=[USER_SET]
            com.example.permission.PARTNER_RESTRICTION: flags=[INSTALLER]
"""

PACKAGE_NOT_FOUND = """Can't find package: com.example.ghost
"""

PACKAGE_DUMP_CRAMPED = (
    "Package [com.example.app] (chunk-3):\n"
    "targetSdk=31\n"
    "requested permissions:\n"
    "android.permission.INTERNET\n"
    "adb shell dumpsys package com.example.app\n"
    "install permissions:\n"
    "android.permission.INTERNET: granted=true\n"
    "com.example.permission.PARTNER_RESTRICTION: flags=[INSTALLER]\n"
    "User 0:\n"
    "runtime permissions:\n"
    "android.permission.READ_SMS: granted=true, flags=[USER_SET]\n"
)


def _entries(audit):
    return {(e.name, e.granted, e.permission_type) for e in audit.permissions}


class TestRecognizedSections:
    def test_install_granted_true(self):
        audit = parse_dumpsys_package(PACKAGE_DUMP, "com.example.app")
        assert audit.parse_complete is True
        assert ("android.permission.INTERNET", True, PERMISSION_INSTALL) in _entries(audit)
        assert (
            "android.permission.POST_NOTIFICATIONS",
            True,
            PERMISSION_INSTALL,
        ) in _entries(audit)

    def test_install_granted_false(self):
        audit = parse_dumpsys_package(PACKAGE_DUMP, "com.example.app")
        assert ("android.permission.READ_CONTACTS", False, PERMISSION_INSTALL) in _entries(audit)

    def test_runtime_nested_under_user_block(self):
        audit = parse_dumpsys_package(PACKAGE_DUMP, "com.example.app")
        assert ("android.permission.READ_SMS", True, PERMISSION_RUNTIME) in _entries(audit)
        assert ("android.permission.SEND_SMS", False, PERMISSION_RUNTIME) in _entries(audit)
        assert ("android.permission.CAMERA", False, PERMISSION_RUNTIME) in _entries(audit)

    def test_permission_line_without_boolean_keeps_none(self):
        audit = parse_dumpsys_package(PACKAGE_DUMP, "com.example.app")
        assert (
            "com.example.permission.PARTNER_RESTRICTION",
            None,
            PERMISSION_RUNTIME,
        ) in _entries(audit)

    def test_requested_permissions_block_never_produces_entries(self):
        """Bare names under `requested permissions:` carry no granted state
        and must not be interpreted as entries."""
        audit = parse_dumpsys_package(PACKAGE_DUMP, "com.example.app")
        assert all(e.name != "android.permission.INTERNET" or e.permission_type != PERMISSION_RUNTIME
                   for e in audit.permissions)
        assert len([e for e in audit.permissions if e.name == "android.permission.INTERNET"]) == 1

    def test_whitespace_and_section_variance_parses_equivalently(self):
        """Tab/cramped indentation and blank lines must not change results."""
        canonical = parse_dumpsys_package(PACKAGE_DUMP, "com.example.app")
        cramped = parse_dumpsys_package(PACKAGE_DUMP_CRAMPED, "com.example.app")
        assert _entries(cramped) == {
            ("android.permission.INTERNET", True, PERMISSION_INSTALL),
            ("com.example.permission.PARTNER_RESTRICTION", None, PERMISSION_INSTALL),
            ("android.permission.READ_SMS", True, PERMISSION_RUNTIME),
        }
        assert cramped.parse_complete is True
        assert canonical.parse_complete is True


class TestNoRecognizableSection:
    def test_empty_input_is_incomplete_not_clean(self):
        audit = parse_dumpsys_package("", "com.example.app")
        assert audit.parse_complete is False
        assert audit.permissions == ()
        assert audit.combination_flags == ()

    def test_package_not_found_message_is_incomplete_not_clean(self):
        audit = parse_dumpsys_package(PACKAGE_NOT_FOUND, "com.example.ghost")
        assert audit.parse_complete is False
        assert audit.permissions == ()
        assert audit.combination_flags == ()

    def test_package_name_echoed_in_audit(self):
        audit = parse_dumpsys_package("", "com.example.app")
        assert audit.package_name == "com.example.app"

    def test_read_at_defaults_to_utc_now_and_override_is_accepted(self):
        fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        audit = parse_dumpsys_package("", "com.example.app", read_at=fixed)
        assert audit.read_at == fixed
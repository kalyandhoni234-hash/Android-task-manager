"""Unit tests for the permission combination flags.

Covers the uncertainty rules: only ``granted is True`` counts (a merely
requested, revoked, or ambiguous permission never contributes to a flag),
matching is exact/case-sensitive on the real Android permission constants,
and results are deterministically ordered.
"""

from __future__ import annotations

from android_task_manager.permissions.combinations import (
    FLAG_OVERLAY_ACCESSIBILITY,
    FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN,
    evaluate_combinations,
)
from android_task_manager.permissions.models import PERMISSION_INSTALL, PermissionEntry

P = "android.permission.{}"


def _e(name: str, granted: bool | None) -> PermissionEntry:
    return PermissionEntry(name=name, granted=granted, permission_type=PERMISSION_INSTALL)


def _ids(flags):
    return [f.flag_id for f in flags]


class TestSmsAccessibilityDeviceAdminFlag:
    def test_all_three_granted_fires(self):
        flags = evaluate_combinations(
            (
                _e(P.format("READ_SMS"), True),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
                _e(P.format("BIND_DEVICE_ADMIN"), True),
            )
        )
        assert _ids(flags) == [FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN]
        flag = flags[0]
        assert set(flag.matched_permissions) == {
            P.format("READ_SMS"),
            P.format("BIND_ACCESSIBILITY_SERVICE"),
            P.format("BIND_DEVICE_ADMIN"),
        }
        assert "worth reviewing" in flag.description

    def test_any_sms_permission_satisfies_sms_part(self):
        for sms in ("READ_SMS", "RECEIVE_SMS", "SEND_SMS"):
            flags = evaluate_combinations(
                (
                    _e(P.format(sms), True),
                    _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
                    _e(P.format("BIND_DEVICE_ADMIN"), True),
                )
            )
            assert _ids(flags) == [FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN], sms

    def test_missing_device_admin_does_not_fire(self):
        flags = evaluate_combinations(
            (
                _e(P.format("READ_SMS"), True),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
            )
        )
        assert _ids(flags) == []

    def test_missing_accessibility_does_not_fire(self):
        flags = evaluate_combinations(
            (
                _e(P.format("READ_SMS"), True),
                _e(P.format("BIND_DEVICE_ADMIN"), True),
            )
        )
        assert _ids(flags) == []


class TestOverlayAccessibilityFlag:
    def test_both_granted_fires(self):
        flags = evaluate_combinations(
            (
                _e(P.format("SYSTEM_ALERT_WINDOW"), True),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
            )
        )
        assert _ids(flags) == [FLAG_OVERLAY_ACCESSIBILITY]
        flag = flags[0]
        assert set(flag.matched_permissions) == {
            P.format("SYSTEM_ALERT_WINDOW"),
            P.format("BIND_ACCESSIBILITY_SERVICE"),
        }
        assert "worth reviewing" in flag.description

    def test_only_overlay_granted_does_not_fire(self):
        flags = evaluate_combinations((_e(P.format("SYSTEM_ALERT_WINDOW"), True),))
        assert _ids(flags) == []


class TestUncertaintyRules:
    def test_granted_none_never_satisfies_a_flag(self):
        flags = evaluate_combinations(
            (
                _e(P.format("READ_SMS"), None),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
                _e(P.format("BIND_DEVICE_ADMIN"), True),
                _e(P.format("SYSTEM_ALERT_WINDOW"), None),
            )
        )
        assert _ids(flags) == []

    def test_granted_false_never_satisfies_a_flag(self):
        flags = evaluate_combinations(
            (
                _e(P.format("READ_SMS"), False),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
                _e(P.format("BIND_DEVICE_ADMIN"), True),
            )
        )
        assert _ids(flags) == []

    def test_exact_case_sensitive_matching(self):
        """A lowercase / differently-cased lookalike must not match."""
        flags = evaluate_combinations(
            (
                _e("android.permission.read_sms", True),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
                _e(P.format("BIND_DEVICE_ADMIN"), True),
            )
        )
        assert _ids(flags) == []

    def test_empty_permissions_produce_no_flags(self):
        assert evaluate_combinations(()) == ()
        assert evaluate_combinations((_e(P.format("INTERNET"), True),)) == ()

    def test_both_flags_fire_in_fixed_order_with_matching_sets(self):
        flags = evaluate_combinations(
            (
                _e(P.format("SEND_SMS"), True),
                _e(P.format("BIND_ACCESSIBILITY_SERVICE"), True),
                _e(P.format("BIND_DEVICE_ADMIN"), True),
                _e(P.format("SYSTEM_ALERT_WINDOW"), True),
            )
        )
        assert _ids(flags) == [
            FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN,
            FLAG_OVERLAY_ACCESSIBILITY,
        ]
        assert flags[0].matched_permissions == (
            P.format("BIND_ACCESSIBILITY_SERVICE"),
            P.format("BIND_DEVICE_ADMIN"),
            P.format("SEND_SMS"),
        )
        assert flags[1].matched_permissions == (
            P.format("BIND_ACCESSIBILITY_SERVICE"),
            P.format("SYSTEM_ALERT_WINDOW"),
        )
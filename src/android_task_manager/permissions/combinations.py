"""Combination flags — fixed, documented permission combinations worth
reviewing (informational only, applied to granted permissions).

Rules on uncertainty (the "no fabricated data" rule, applied to flags):

* Only ``granted is True`` entries count. A merely requested-but-unset
  permission or an ambiguous line (``granted=None``) is **not** confirmed
  and never treated as a match — "unknown" is not "granted".
* Matching uses the real Android permission constant names, case-sensitive
  exact comparison; unknown/custom permission names can never satisfy a
  flag by substring luck.
* Flag output order is fixed (SMS flag first, then overlay) and every flag's
  ``matched_permissions`` is sorted, so results are deterministic.

Nothing here is a verdict: the fixed descriptions frame each combination as
"worth reviewing" — a definitive threat determination is out of scope.
"""

from __future__ import annotations

from .models import CombinationFlag, PermissionEntry

#: Fixed v1 flag identifiers.
FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN = "SMS_ACCESSIBILITY_DEVICE_ADMIN"
FLAG_OVERLAY_ACCESSIBILITY = "OVERLAY_ACCESSIBILITY"

#: The SMS-related permission constants qualifying for Flag 1 (any one).
_SMS_PERMISSIONS = frozenset(
    {
        "android.permission.READ_SMS",
        "android.permission.RECEIVE_SMS",
        "android.permission.SEND_SMS",
    }
)
_ACCESSIBILITY_PERMISSION = "android.permission.BIND_ACCESSIBILITY_SERVICE"
_DEVICE_ADMIN_PERMISSION = "android.permission.BIND_DEVICE_ADMIN"
_OVERLAY_PERMISSION = "android.permission.SYSTEM_ALERT_WINDOW"

_DESCRIPTION_SMS_ACCESSIBILITY_DEVICE_ADMIN = (
    "Requests SMS access alongside Accessibility Service and Device Admin — a "
    "combination sometimes seen in banking-trojan-style malware, worth reviewing "
    "why this app needs all three."
)
_DESCRIPTION_OVERLAY_ACCESSIBILITY = (
    "Requests draw-over-other-apps alongside Accessibility Service — this "
    "combination can enable overlay-based phishing/credential-capture UI, worth "
    "reviewing."
)


def evaluate_combinations(
    permissions: tuple[PermissionEntry, ...],
) -> tuple[CombinationFlag, ...]:
    """Evaluate the fixed flag set against a *granted* permission set.

    Returns a deterministically ordered tuple of the flags that fired. An
    empty permission list yields an empty tuple.
    """
    granted = {entry.name for entry in permissions if entry.granted is True}

    flags: list[CombinationFlag] = []

    sms_permissions = sorted(_SMS_PERMISSIONS & granted)
    if (
        sms_permissions
        and _ACCESSIBILITY_PERMISSION in granted
        and _DEVICE_ADMIN_PERMISSION in granted
    ):
        flags.append(
            CombinationFlag(
                flag_id=FLAG_SMS_ACCESSIBILITY_DEVICE_ADMIN,
                matched_permissions=tuple(
                    sorted(
                        sms_permissions
                        + [_ACCESSIBILITY_PERMISSION, _DEVICE_ADMIN_PERMISSION]
                    )
                ),
                description=_DESCRIPTION_SMS_ACCESSIBILITY_DEVICE_ADMIN,
            )
        )

    if _OVERLAY_PERMISSION in granted and _ACCESSIBILITY_PERMISSION in granted:
        flags.append(
            CombinationFlag(
                flag_id=FLAG_OVERLAY_ACCESSIBILITY,
                matched_permissions=tuple(
                    sorted([_OVERLAY_PERMISSION, _ACCESSIBILITY_PERMISSION])
                ),
                description=_DESCRIPTION_OVERLAY_ACCESSIBILITY,
            )
        )

    return tuple(flags)
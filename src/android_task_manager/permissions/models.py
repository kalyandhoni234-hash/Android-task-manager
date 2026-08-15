"""Package/permission audit — data models.

One installed package's granted permissions (read via ``dumpsys package``),
plus a small, fixed set of documented *combination flags* worth a second
look. All analysis output here is informational framing ("worth reviewing"),
never a definitive threat verdict.

The "facts vs. judgment" separation used elsewhere in the project holds
here too: raw permission parsing (``parser.py``) and combination flagging
(``combinations.py``) are separate, independently testable layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Permission source sections as grouped by ``dumpsys package`` itself.
PERMISSION_RUNTIME = "runtime"
PERMISSION_INSTALL = "install"
PERMISSION_UNKNOWN = "unknown"


@dataclass(frozen=True)
class PermissionEntry:
    """One permission line seen in a ``dumpsys package`` permissions section.

    ``granted`` is ``None`` when the output did not state a clean boolean —
    an ambiguous line is never defaulted to "not granted".
    """

    name: str
    granted: bool | None
    #: PERMISSION_RUNTIME | PERMISSION_INSTALL | PERMISSION_UNKNOWN — mirrors
    #: dumpsys's own grouping; "unknown" when no section was recognizable.
    permission_type: str


@dataclass(frozen=True)
class CombinationFlag:
    """A permission combination worth a second look (informational only)."""

    flag_id: str  # e.g. "SMS_ACCESSIBILITY_DEVICE_ADMIN"
    #: The actual granted permission names that satisfied the combination.
    matched_permissions: tuple[str, ...] = ()
    #: One sentence, "worth reviewing" framing — never a verdict.
    description: str = ""


@dataclass(frozen=True)
class PackagePermissionAudit:
    """Normalized result of auditing one package's granted permissions."""

    package_name: str
    #: When the audit was produced (UTC). Supplied by the collector.
    read_at: datetime
    permissions: tuple[PermissionEntry, ...] = ()
    #: False when no recognizable permissions section was found, meaning the
    #: list may be incomplete — never presented as a clean empty success.
    parse_complete: bool = False
    combination_flags: tuple[CombinationFlag, ...] = ()
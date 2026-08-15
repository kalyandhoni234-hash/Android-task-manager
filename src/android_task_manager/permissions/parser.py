"""Parsing of ``dumpsys package <pkg>`` output into a ``PackagePermissionAudit``.

Defensive, token-based parsing (no fixed column offsets): the parser scans
for the two recognizable permission sections — ``install permissions:`` and
``runtime permissions:`` (which may be nested under an indented ``User 0:``
block) — and then matches field-name tokens (``<name>: granted=<bool>``)
inside them. Whitespace/indentation variance is tolerated because matching
happens on stripped, token-level patterns.

Uncertainty rules:

* A permission name inside a recognized section without a clean
  ``granted=true/false`` token keeps ``granted=None`` — never defaulted to
  "not granted".
* Text containing **no** recognizable permissions section at all (empty
  input, garbage, or a "package not found" style message) yields an audit
  with ``permissions=()`` and ``parse_complete=False`` — the caller can
  honestly say "could not verify" instead of a plausible empty success.
* Nothing outside a recognized section produces entries (e.g. the bare
  names under ``requested permissions:`` carry no granted state and are
  deliberately not interpreted).

Pure function: no ADB, no I/O. Device interaction lives in ``collector.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .combinations import evaluate_combinations
from .models import (
    PERMISSION_INSTALL,
    PERMISSION_RUNTIME,
    PackagePermissionAudit,
    PermissionEntry,
)

#: Section headers (matched on the stripped line, so indentation is free).
_SECTION_HEADER_RE = re.compile(r"^(install|runtime) permissions:\s*$")

#: A permission name line: dotted identifier followed by a colon. Android
#: permission constants always contain at least one dot, which also keeps
#: labels like ``User 0:`` or ``requested permissions:`` from matching.
_PERMISSION_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+):")

#: Granted-state token anywhere on the permission line (may be followed by
#: ``, flags=[...]`` or other attributes).
_GRANTED_STATE_RE = re.compile(r"granted=(true|false)")


def parse_dumpsys_package(
    raw_output: str,
    package_name: str,
    *,
    read_at: datetime | None = None,
) -> PackagePermissionAudit:
    """Parse ``dumpsys package`` text into a :class:`PackagePermissionAudit`.

    ``read_at`` is supplied by the collector (UTC now by default); pass a
    fixed value in tests for deterministic results.
    """
    section: str | None = None
    section_seen = False
    entries: list[PermissionEntry] = []

    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        header = _SECTION_HEADER_RE.match(stripped)
        if header is not None:
            section = PERMISSION_INSTALL if header.group(1) == "install" else PERMISSION_RUNTIME
            section_seen = True
            continue
        if section is None:
            continue
        permission_line = _PERMISSION_LINE_RE.match(stripped)
        if permission_line is None:
            continue
        name = permission_line.group(1)
        granted_match = _GRANTED_STATE_RE.search(stripped)
        granted: bool | None = None
        if granted_match is not None:
            granted = granted_match.group(1) == "true"
        entries.append(PermissionEntry(name=name, granted=granted, permission_type=section))

    if not section_seen:
        return PackagePermissionAudit(
            package_name=package_name,
            read_at=read_at or datetime.now(timezone.utc),
            permissions=(),
            parse_complete=False,
            combination_flags=(),
        )

    permissions = tuple(entries)
    return PackagePermissionAudit(
        package_name=package_name,
        read_at=read_at or datetime.now(timezone.utc),
        permissions=permissions,
        parse_complete=True,
        combination_flags=evaluate_combinations(permissions),
    )
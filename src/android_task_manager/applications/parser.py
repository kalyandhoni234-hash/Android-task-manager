"""Parsing of ``pm list packages`` and ``dumpsys package`` output.

Defensive, token-based parsing with no fixed column offsets. The inventory
parser consumes one ``pm list packages -f -U --show-versioncode`` read plus
the system/third-party/disabled companion lists; the details parser consumes
one ``dumpsys package <pkg>`` read. Anything unrecognizable is dropped (or
kept ``None``), never guessed.

All functions are pure: no ADB, no I/O. Device interaction lives in
``collector.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..action.package import validate_package_name
from .models import AppCategory, AppDetails, AppInfo

#: One ``package:...`` inventory line: ``package:/path/base.apk=name
#: uid=123 versionCode:42``. The path half may contain dots, dashes and
#: underscores; the name half must survive strict package validation.
_INVENTORY_LINE_RE = re.compile(
    r"^package:(?P<path>\S+)=(?P<name>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)"
    r"(?: uid=(?P<uid>\d+))?(?: versionCode:(?P<version_code>\d+))?$"
)

#: ``package:name`` lines from the -s / -3 / -d companion lists.
_NAME_LINE_RE = re.compile(
    r"^package:(?P<name>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)$"
)

#: Fields inside the ``Package [<name>] (hash):`` section of dumpsys.
_VERSION_NAME_RE = re.compile(r"^versionName=(?P<value>\S+)$")
_VERSION_CODE_RE = re.compile(r"^versionCode=(?P<value>\d+)")
_UID_RE = re.compile(r"^(?:uid|userId)=(?P<value>\d+)$")
_CODE_PATH_RE = re.compile(r"^codePath=(?P<value>\S+)$")
_INSTALLER_RE = re.compile(r"^installerPackageName=(?P<value>\S+)$")
_ENABLED_RE = re.compile(r"^enabled=(?P<value>\d+)$")
_FLAGS_RE = re.compile(r"^(?:flags|pkgFlags)=\[(?P<value>[^\]]*)\]")

#: Component lines under ``activities:`` / ``services:`` / ``receivers:``
#: (the line begins with the owning package name).
_COMPONENT_LINE_RE = re.compile(
    r"^(?P<package>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)"
    r"/(?P<name>\.?[A-Za-z$][A-Za-z0-9_.$]*)$"
)

#: Resolver-table lines: ``<hash> <package>/<Component> filter <hex>``. The
#: hash prefix means the component appears mid-line, so this is a search
#: pattern used only inside the activity resolver table.
_RESOLVER_COMPONENT_RE = re.compile(
    r"(?P<package>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)"
    r"/(?P<name>\.?[A-Za-z$][A-Za-z0-9_.$]*)\s+filter\s"
)

#: Resolver-table headers (``android.intent.action.MAIN:`` and
#: ``android.intent.category.LAUNCHER:`` etc).
_RESOLVER_HEADER_RE = re.compile(
    r"^android\.intent\.(?:action|category)\.[A-Za-z_.]+:$"
)

#: The package section header: ``Package [<name>] (hash):``.
_PACKAGE_SECTION_RE = re.compile(
    r"^Package \[(?P<name>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)\]"
)
#: Legacy bare header ``[<name>]:`` tolerated on old dumpsys variants.
_LEGACY_SECTION_RE = re.compile(
    r"^\[(?P<name>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)\](?::)?$"
)

#: Known codePath prefixes mapped to human install-location labels.
_INSTALL_LOCATIONS = (
    ("/data/app", "Internal storage"),
    ("/data/user_de", "Internal storage"),
    ("/data/data", "Internal storage"),
    ("/mnt/expand", "Adopted storage"),
    ("/system", "System partition"),
    ("/product", "System partition"),
    ("/vendor", "System partition"),
    ("/odm", "System partition"),
    ("/oem", "System partition"),
    ("/apex", "System partition"),
)

#: ``enabled=`` values from dumpsys package: default/enabled are enabled
#: states; disabled/disabled-user/disabled-until-used are not.
_DISABLED_ENABLED_VALUES = (2, 3, 4)

_SYSTEM_FLAGS = ("SYSTEM", "UPDATED_SYSTEM_APP")


@dataclass(frozen=True)
class _InventoryEntry:
    """Raw per-package facts from one ``pm list packages`` line."""

    apk_path: str | None = None
    uid: int | None = None
    version_code: int | None = None


def parse_inventory_lines(text: str) -> dict[str, _InventoryEntry]:
    """Parse ``pm list packages -f -U --show-versioncode`` into a name-keyed
    map of raw entries. Lines that fail strict validation are skipped."""
    entries: dict[str, _InventoryEntry] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("package:"):
            continue
        match = _INVENTORY_LINE_RE.match(stripped)
        if match is None:
            continue
        name = match.group("name")
        try:
            validate_package_name(name)
        except ValueError:
            continue
        entries[name] = _InventoryEntry(
            apk_path=match.group("path"),
            uid=_to_int(match.group("uid")),
            version_code=_to_int(match.group("version_code")),
        )
    return entries


def parse_name_list(text: str) -> set[str]:
    """Parse one ``pm list packages`` companion list into validated names."""
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        match = _NAME_LINE_RE.match(stripped)
        if match is None:
            continue
        name = match.group("name")
        try:
            validate_package_name(name)
        except ValueError:
            continue
        names.add(name)
    return names


def build_inventory(
    inventory_text: str,
    *,
    system_text: str,
    user_text: str,
    disabled_text: str,
) -> list[AppInfo]:
    """Merge the four ``pm`` reads into normalized :class:`AppInfo` rows.

    Classification is authoritative where the companion lists agree; a
    package missing from both lists keeps ``AppCategory.UNKNOWN`` (never
    guessed). ``enabled`` is ``False`` exactly when the package appears in
    the disabled list, ``True`` otherwise — a package absent from both
    enabled/disabled states is impossible, so no ``None`` is produced here.
    """
    entries = parse_inventory_lines(inventory_text)
    system = parse_name_list(system_text)
    user = parse_name_list(user_text)
    disabled = parse_name_list(disabled_text)

    apps: list[AppInfo] = []
    for name, raw in entries.items():
        if name in system:
            category = AppCategory.SYSTEM
        elif name in user:
            category = AppCategory.USER
        else:
            category = AppCategory.UNKNOWN
        apps.append(
            AppInfo(
                package_name=name,
                apk_path=raw.apk_path,
                uid=raw.uid,
                version_code=raw.version_code,
                category=category,
                enabled=name not in disabled,
            )
        )
    return apps


def install_location_for(code_path: str | None) -> str | None:
    """Map a device codePath to a human install-location label.

    ``None`` when the path is unknown or unrecognized (rendered as "N/A").
    """
    if not code_path:
        return None
    for prefix, label in _INSTALL_LOCATIONS:
        if code_path.startswith(prefix):
            return label
    return "Other"


def category_from_flags(flags: tuple[str, ...]) -> AppCategory:
    """Derive system/user classification from dumpsys package flags.

    ``UPDATED_SYSTEM_APP`` counts as SYSTEM: an updated system app is still
    a system app, and its uninstall would only remove the update — such a
    half-measure must never be offered as a full uninstall.
    """
    if not flags:
        return AppCategory.UNKNOWN
    if any(flag in _SYSTEM_FLAGS for flag in flags):
        return AppCategory.SYSTEM
    return AppCategory.USER


def enabled_from_value(value: int | None) -> bool | None:
    """Map the ``enabled=`` integer to a boolean; ``None`` stays unknown."""
    if value is None:
        return None
    return value not in _DISABLED_ENABLED_VALUES


def parse_app_details(raw_output: str, package_name: str) -> AppDetails:
    """Parse ``dumpsys package <pkg>`` into a :class:`AppDetails`.

    Only the package's own section is trusted: reading stops at the next
    package header. Fields are captured on a first-wins basis; component
    sections may appear in different orders between Android versions, so
    every section is scanned independently.
    """
    lines = raw_output.splitlines()
    section_start = _find_package_section(lines, package_name)
    if section_start is None:
        return AppDetails(package_name=package_name, parse_complete=False)

    version_name: str | None = None
    version_code: int | None = None
    uid: int | None = None
    code_path: str | None = None
    installer: str | None = None
    enabled: bool | None = None
    flags: tuple[str, ...] = ()

    activities: list[str] = []
    services: list[str] = []
    receivers: list[str] = []
    main_activities: set[str] = set()
    launcher_activities: set[str] = set()

    section: str | None = None
    resolver_action: str | None = None

    for line in lines[section_start + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if _section_name(stripped) is not None:
            break  # next package section: stop reading this package

        if stripped == "Activity Resolver Table:":
            section = "resolver"
            resolver_action = None
            continue
        if stripped == "activities:":
            section = "activities"
            continue
        if stripped == "services:":
            section = "services"
            continue
        if stripped == "receivers:":
            section = "receivers"
            continue
        if stripped == "providers:":
            section = "providers"
            continue

        action_header = _RESOLVER_HEADER_RE.match(stripped)
        if action_header is not None:
            resolver_action = stripped[:-1]
            continue

        if section == "resolver" and resolver_action is not None:
            match = _RESOLVER_COMPONENT_RE.search(stripped)
            if match is not None and match.group("package") == package_name:
                component = _component_full_name(package_name, match.group("name"))
                if resolver_action == "android.intent.action.MAIN":
                    main_activities.add(component)
                elif resolver_action == "android.intent.category.LAUNCHER":
                    launcher_activities.add(component)
            continue

        if section in ("activities", "services", "receivers"):
            match = _COMPONENT_LINE_RE.match(stripped)
            if match is not None and match.group("package") == package_name:
                component = _component_full_name(package_name, match.group("name"))
                if section == "activities":
                    activities.append(component)
                elif section == "services":
                    services.append(component)
                else:
                    receivers.append(component)
            continue

        if section == "providers":
            continue

        if version_name is None:
            match = _VERSION_NAME_RE.match(stripped)
            if match is not None:
                version_name = match.group("value")
        if version_code is None:
            match = _VERSION_CODE_RE.match(stripped)
            if match is not None:
                version_code = _to_int(match.group("value"))
        if uid is None:
            match = _UID_RE.match(stripped)
            if match is not None:
                uid = _to_int(match.group("value"))
        if code_path is None:
            match = _CODE_PATH_RE.match(stripped)
            if match is not None:
                code_path = match.group("value")
        if installer is None:
            match = _INSTALLER_RE.match(stripped)
            if match is not None:
                installer = match.group("value")
        if enabled is None:
            match = _ENABLED_RE.match(stripped)
            if match is not None:
                enabled = enabled_from_value(_to_int(match.group("value")))
        if not flags:
            match = _FLAGS_RE.match(stripped)
            if match is not None:
                flags = tuple(match.group("value").split())

    launchable = next(
        (
            a
            for a in activities
            if a in main_activities and a in launcher_activities
        ),
        None,
    )
    if launchable is None:
        shared = sorted(main_activities & launcher_activities)
        if shared:
            launchable = shared[0]

    return AppDetails(
        package_name=package_name,
        version_name=version_name,
        version_code=version_code,
        uid=uid,
        apk_path=code_path,
        install_location=install_location_for(code_path),
        category=category_from_flags(flags),
        enabled=enabled,
        installer=installer,
        flags=flags,
        launchable_activity=launchable,
        activities=tuple(activities),
        services=tuple(services),
        receivers=tuple(receivers),
        parse_complete=True,
    )


def _find_package_section(lines: list[str], package_name: str) -> int | None:
    """Index of the requested package's section header, or ``None``."""
    for index, line in enumerate(lines):
        if _section_name(line.strip()) == package_name:
            return index
    return None


def _section_name(stripped: str) -> str | None:
    """The package name a header line declares, or ``None``."""
    match = _PACKAGE_SECTION_RE.match(stripped)
    if match is not None:
        return match.group("name")
    match = _LEGACY_SECTION_RE.match(stripped)
    if match is not None:
        return match.group("name")
    return None


def _component_full_name(package: str, name: str) -> str:
    """Join a package and its (possibly dotted-shorthand) component name."""
    if name.startswith("."):
        return f"{package}/{name}"
    return name


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "_InventoryEntry",
    "build_inventory",
    "category_from_flags",
    "enabled_from_value",
    "install_location_for",
    "parse_app_details",
    "parse_inventory_lines",
    "parse_name_list",
]
"""Package-name validation for controlled device actions.

A PID is not an Android application identity; every application action in
this codebase targets a *validated package name*. Nothing derived from user
input ever reaches a shell command line unvalidated.
"""

from __future__ import annotations

import re

#: Android package identifiers: dot-separated segments of letters, digits
#: and underscores, each segment starting with a letter. The strict pattern
#: rejects whitespace, shell metacharacters, separators, path traversal and
#: any other input that could reshape a command line.
PACKAGE_NAME_PATTERN = r"[A-Za-z][A-Za-z0-9_]*"
PACKAGE_NAME_RE = re.compile(
    rf"^{PACKAGE_NAME_PATTERN}(\.{PACKAGE_NAME_PATTERN})*$"
)

#: Maximum accepted package identifier length (Android's own limit).
MAX_PACKAGE_LENGTH = 255

#: A resolved launch component "package/Activity" from Android's
#: ``cmd package resolve-activity`` output. The activity half may use the
#: abbreviated ``.Activity`` shorthand and may contain inner-class ``$``
#: names; both halves are validated before use.
COMPONENT_RE = re.compile(
    rf"^{PACKAGE_NAME_PATTERN}(\.{PACKAGE_NAME_PATTERN})*/"
    rf"(\.)?[A-Za-z$][A-Za-z0-9_.$]*$"
)


class PackageValidationError(ValueError):
    """Raised when a string is not a safe Android package identifier."""


def validate_package_name(name: object) -> str:
    """Return *name* if it is a valid, safe package identifier.

    Raises :class:`PackageValidationError` for empty, malformed or
    shell-hostile inputs. The returned string contains only
    ``[A-Za-z0-9_.]`` so it can be placed in an argument list safely.
    """
    if not isinstance(name, str):
        raise PackageValidationError(
            f"invalid package name: expected a string, got {type(name).__name__}"
        )
    candidate = name.strip()
    if not candidate:
        raise PackageValidationError("package name must not be empty")
    if len(candidate) > MAX_PACKAGE_LENGTH:
        raise PackageValidationError(
            f"package name is too long ({len(candidate)} > {MAX_PACKAGE_LENGTH})"
        )
    if not PACKAGE_NAME_RE.fullmatch(candidate):
        raise PackageValidationError(
            f"invalid package name: {candidate!r} is not a safe Android package identifier"
        )
    return candidate


def validate_component(component: str) -> str:
    """Validate a resolved ``package/Activity`` string from ADB output.

    Raised :class:`PackageValidationError` if the output is empty,
    malformed or unsafe.
    """
    candidate = component.strip()
    if not candidate:
        raise PackageValidationError("resolved activity component is empty")
    if not COMPONENT_RE.fullmatch(candidate):
        raise PackageValidationError(
            f"unsafe activity component: {candidate!r}"
        )
    return candidate


def parse_package_list(text: str) -> set[str]:
    """Parse ``pm list packages`` output into validated package names.

    Lines that do not start with ``package:`` or that do not survive strict
    validation are skipped instead of failing the whole read.
    """
    packages: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        candidate = line[len("package:") :].strip()
        try:
            packages.add(validate_package_name(candidate))
        except PackageValidationError:
            continue
    return packages
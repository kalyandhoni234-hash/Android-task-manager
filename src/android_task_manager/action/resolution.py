"""Safe process → Android package resolution.

A PID is not an application identity. A process is only associated with a
package when one of its identity signals — the command line's argv[0] or the
``ps`` NAME — maps to an *installed* package, i.e. the identity is **verified
against the device's installed package list**. Anything else resolves to
``None`` so kernel/system rows never receive application actions.

The identity pipeline is:

    process name
        ↓  reject kernel-thread style names ([kworker/0:1], …)
        ↓  strip Android secondary-process suffix (:remote, :service, …)
        ↓  strict package-syntax validation
        ↓  verify the base name is present in the installed package list
    verified package (or None — never a guess)
"""

from __future__ import annotations

from .package import PACKAGE_NAME_RE


def parse_command_line_argv0(command_line: str | None) -> str | None:
    """Return the first whitespace-separated token of *command_line*.

    For an Android application main process the first cmdline token is the
    package name. ``None`` input or empty output yields ``None``.
    """
    if not command_line:
        return None
    tokens = command_line.split()
    return tokens[0] if tokens else None


def strip_secondary_suffix(name: str) -> str:
    """Return the base application name of an Android secondary process.

    Android secondary (isolated/broadcast/service) processes run under names
    like ``com.example.app:remote``; the application identity is everything
    before the first colon, since package identifiers never contain colons.
    Names without a colon are returned unchanged.
    """
    colon = name.find(":")
    return name[:colon] if colon != -1 else name


def is_kernel_style_name(name: str) -> bool:
    """True for names that look like kernel-thread stack/comm entries.

    The kernel renders kthread names in square brackets (``[kworker/0:1]``,
    ``[rcu_preempt]``); such names are never application identities.
    """
    return len(name) >= 2 and name.startswith("[") and name.endswith("]")


def resolve_package(
    name: str | None,
    command_line: str | None,
    installed_packages: set[str],
) -> str | None:
    """Resolve a process to a verified installed package, or ``None``.

    Candidate identities, in priority order:

    1. argv[0] of the /proc command line (exact for app main processes);
    2. the ``ps`` NAME column (often the package for app processes).

    Every candidate is normalized, rejected if it is kernel-style, split at
    its first colon to recover the base of a secondary-process name, and
    accepted **only** when it has valid package syntax **and** the base is
    present in *installed_packages* — an exact match against the device's
    own package list, never a guess. Processes that resolve to ``None``
    (kernel threads, framework processes, transient processes) are simply
    not actionable.
    """
    if not installed_packages:
        return None

    candidates: list[str] = []
    argv0 = parse_command_line_argv0(command_line)
    if argv0 is not None:
        candidates.append(argv0)
    if name:
        candidates.append(name)

    for candidate in candidates:
        candidate = strip_secondary_suffix(candidate)
        if is_kernel_style_name(candidate):
            continue
        if PACKAGE_NAME_RE.fullmatch(candidate) and candidate in installed_packages:
            return candidate
    return None
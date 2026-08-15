"""PackageResolver: verified process → package identity on the connected device.

The resolver owns the device's *verified* installed-package set — the exact
answer to the question "does this package actually exist on the connected
Android device?" — and resolves process identity against it. It never
guesses: without a positive verification against the installed list, a
process simply has no application identity.

The cache is a pure in-memory filter on top of :func:`resolve_package`; it
is refreshed whenever the device (re)connects and entries are dropped when a
device action reports the package as no longer installed, so a stale entry
can never hand out an unsafe identity.
"""

from __future__ import annotations

from .resolution import resolve_package


class PackageResolver:
    """Caches installed packages and maps process names to verified packages.

    Instances are cheap; the same resolver is passed to GUI/worker layers so
    they share one view of the device's package list.
    """

    def __init__(self, installed_packages: set[str] | None = None) -> None:
        self._installed: set[str] = set(installed_packages) if installed_packages else set()

    def installed(self) -> set[str]:
        """Copy of the verified installed-package set."""
        return set(self._installed)

    def update(self, packages: set[str]) -> None:
        """Atomically replace the installed set (refresh/invalidate-all)."""
        self._installed = set(packages)

    def invalidate(self, package: str) -> None:
        """Drop a single package whose continued existence is now doubtful.

        Used when a device action reports the package as no longer
        installed, so the stale identity is removed immediately instead of
        lingering until the next reconnect.
        """
        self._installed.discard(package)

    def resolve(
        self,
        process_name: str | None,
        command_line: str | None = None,
    ) -> str | None:
        """Return the verified package for a process, or ``None``."""
        return resolve_package(process_name, command_line, self._installed)


__all__ = ["PackageResolver"]
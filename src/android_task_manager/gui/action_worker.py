"""Worker that runs device actions off the GUI thread.

The dashboard never executes an action synchronously: clicking an action
button emits ``action_requested``, which (after a queued connection onto
this object's thread) runs the controlled action through ``ActionService``
over the shared connection, and publishes a typed :class:`ActionResult`
back through ``action_completed``. GUI code never calls into ADB itself.

The worker also owns the :class:`PackageResolver` used to verify process
identity, and refreshes it whenever the device (re)connects. When an action
reports a package as no longer installed, that package is dropped from the
resolver immediately so no stale identity survives.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..action import (
    ActionError,
    ActionErrorKind,
    ActionResult,
    ActionService,
    PackageResolver,
)
from ..adb.connection import CommandRunner, ConnectionManager
from ..core.diagnostics import log_unexpected_failure
from .monitor import ConnectionState


class ActionWorker(QObject):
    """Runs the three controlled device actions and package-list refresh."""

    #: (ActionResult) a completed action, success or typed failure
    action_completed = Signal(object)

    #: (set[str]) verified installed packages, or an empty set when the
    #: device could not be read (actions then stay disabled, never guessed)
    packages_ready = Signal(object)

    def __init__(
        self,
        connection: CommandRunner | None = None,
        adb_path: str = "adb",
        timeout: float = 10.0,
        device_serial: str | None = None,
    ) -> None:
        super().__init__()
        self._service = ActionService(
            connection
            or ConnectionManager(
                adb_path=adb_path,
                timeout=timeout,
                device_serial=device_serial,
            ),
            timeout=timeout,
        )
        self._busy = False
        self._resolver = PackageResolver()
        self._packages_loaded = False

    # ------------------------------------------------------------------
    # Test/status accessors
    # ------------------------------------------------------------------

    def is_busy(self) -> bool:
        """True while an action is in flight (duplicates are dropped)."""
        return self._busy

    def packages(self) -> set[str] | None:
        """Verified package set, or ``None`` before a successful refresh."""
        if not self._packages_loaded:
            return None
        return self._resolver.installed()

    def run_action(self, action: str, package: object) -> ActionResult:
        """Synchronous action execution (used by tests); raises on failure."""
        return self._service.run(action, package)

    # ------------------------------------------------------------------
    # Slots (delivered onto this worker's thread by queued connections)
    # ------------------------------------------------------------------

    @Slot(str, str)
    def request_action(self, action: object, package: object) -> None:
        """Execute *action* for *package* and publish the typed result.

        While an action is running, further requests are ignored: no
        second click can stack a duplicate ADB call onto the first one.
        """
        if self._busy:
            return
        self._busy = True
        try:
            result = self._service.run(str(action), package)
        except ActionError as exc:
            result = ActionResult(
                str(action),
                str(package),
                False,
                exc.message,
                exc.kind,
            )
            if exc.kind is ActionErrorKind.NOT_FOUND and isinstance(package, str):
                self._drop_package(package)
        except Exception as exc:  # noqa: BLE001 - a worker bug never freezes the GUI
            log_unexpected_failure("action", "run", exc)
            result = ActionResult(
                str(action),
                str(package),
                False,
                "The action failed unexpectedly.",
                ActionErrorKind.UNKNOWN,
            )
        finally:
            self._busy = False
        self.action_completed.emit(result)

    @Slot(object, str)
    def on_connection_changed(self, state, _detail: str) -> None:
        """Refresh the installed package list when the device (re)connects.

        Runs on this worker's thread (queued from the monitor thread), so
        the ``pm list packages`` subprocess never blocks the GUI.
        """
        if state is ConnectionState.CONNECTED:
            self.reload_packages()

    @Slot()
    def reload_packages(self) -> None:
        """Re-read the installed package list and publish it via signal.

        On failure the published set is empty, which disables every action
        button — losing verified identity is safer than guessing.
        """
        try:
            packages = self._service.list_packages()
        except ActionError:
            self._resolver.update(set())
            self._packages_loaded = False
            self.packages_ready.emit(frozenset())
            return
        self._resolver.update(packages)
        self._packages_loaded = True
        self.packages_ready.emit(packages)

    def _drop_package(self, package: str) -> None:
        """Remove a package the device just reported as not installed."""
        self._resolver.invalidate(package)
        if self._packages_loaded:
            self.packages_ready.emit(self._resolver.installed())
"""Worker that runs on-demand permission audits off the GUI thread.

Collecting one package's granted permissions (``dumpsys package <pkg>``) is a
device read, so it runs here on a QThread through a queued connection — the
dashboard and inspector never call into ADB themselves. The worker wraps
``PermissionCollector`` unchanged (read-only, one package per call) and
publishes either the typed audit or a failure message; a duplicate request
while one is in flight is dropped (the ActionWorker convention).

The inspector gates the result: an audit that arrives after the selection
changed is discarded there — this worker never decides which process the
result belongs to.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..adb.connection import CommandRunner, ConnectionManager
from ..adb.exceptions import ADBError
from ..core.diagnostics import log_unexpected_failure
from ..permissions import PermissionCollector


class PermissionWorker(QObject):
    """One-shot, on-demand permission audits for a single package."""

    #: (PackagePermissionAudit) a completed audit
    audit_ready = Signal(object)
    #: (package, message) the device read failed
    audit_failed = Signal(str, str)

    def __init__(
        self,
        connection: CommandRunner | None = None,
        adb_path: str = "adb",
        timeout: float = 10.0,
        device_serial: str | None = None,
    ) -> None:
        super().__init__()
        self._collector = PermissionCollector(
            connection
            or ConnectionManager(
                adb_path=adb_path,
                timeout=timeout,
                device_serial=device_serial,
            ),
            timeout=timeout,
        )
        self._busy = False

    def is_busy(self) -> bool:
        """True while an audit is in flight (duplicates are dropped)."""
        return self._busy

    @Slot(object)
    def request_audit(self, package: object) -> None:
        """Audit *package* and publish the result (or a failure message)."""
        if self._busy:
            return
        self._busy = True
        package_name = str(package)
        try:
            audit = self._collector.collect(package_name)
        except ADBError as exc:
            self.audit_failed.emit(package_name, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a worker bug never freezes the GUI
            log_unexpected_failure("permissions", "audit", exc)
            self.audit_failed.emit(package_name, "The permission audit failed unexpectedly.")
            return
        finally:
            self._busy = False
        self.audit_ready.emit(audit)
"""Worker that runs application inventory/detail reads off the GUI thread.

The dashboard never reads the application list or a package's details
synchronously: refresh requests and selection-driven detail reads arrive
as queued slots on this object's thread, run through the shared
``ApplicationCollector``, and publish typed results via signals. The GUI
only renders.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..adb.connection import CommandRunner, ConnectionManager
from ..adb.exceptions import ADBError
from ..applications import ApplicationCollector
from ..applications.apk_label import ApkLabelResolver
from ..core.diagnostics import log_unexpected_failure
from .monitor import ConnectionState


class AppsWorker(QObject):
    """Reads the installed-application inventory and per-package details."""

    #: (ApplicationSnapshot) the freshly read inventory, or an empty
    #: snapshot on device/connection failure (honest empty, never stale).
    inventory_ready = Signal(object)

    #: (human_message) the inventory could not be read.
    inventory_failed = Signal(str)

    #: (AppDetails) a completed per-package detail read.
    details_ready = Signal(object)

    #: (package, human_message) the detail read failed (ADB error or a
    #: package that is no longer installed).
    details_failed = Signal(str, str)

    #: (dict[package, label|None]) resolved human-readable labels for the
    #: requested packages, or ``None`` when no label could be read from the
    #: device APK. The caller falls back to the package name; never a guess.
    labels_ready = Signal(object)

    #: (list[package]) request label resolution for the named packages.
    #: Queued onto this worker's thread so APK reads never block the GUI.
    resolve_labels_requested = Signal(object)

    def __init__(
        self,
        connection: CommandRunner | None = None,
        adb_path: str = "adb",
        timeout: float = 10.0,
        device_serial: str | None = None,
    ) -> None:
        super().__init__()
        self._connection = connection or ConnectionManager(
            adb_path=adb_path,
            timeout=timeout,
            device_serial=device_serial,
        )
        self._collector = ApplicationCollector(self._connection, timeout=timeout)
        #: Resolves application labels from APKs on the connected device.
        #: Cached per APK path; never fabricates a label.
        self._label_resolver = ApkLabelResolver(self._connection, timeout=timeout)
        #: Last successful inventory, retained so label resolution can map a
        #: package to its APK path without re-collecting the inventory.
        self._inventory: object | None = None
        self._busy = False
        self.resolve_labels_requested.connect(self.resolve_labels)

    # ------------------------------------------------------------------
    # Test/status accessors
    # ------------------------------------------------------------------

    def is_busy(self) -> bool:
        """True while an inventory refresh is in flight."""
        return self._busy

    def collect_inventory(self, timestamp: float | None = None):
        """Synchronous inventory read (used by tests); raises on failure."""
        return self._collector.collect(timestamp=timestamp)

    def collect_details(self, package: str):
        """Synchronous detail read (used by tests); raises on failure."""
        return self._collector.collect_details(package)

    # ------------------------------------------------------------------
    # Slots (delivered onto this worker's thread by queued connections)
    # ------------------------------------------------------------------

    @Slot()
    def refresh_inventory(self) -> None:
        """Re-read the installed-application inventory and publish it.

        Duplicate refreshes while one is in flight are dropped; a failure
        publishes an empty snapshot plus a typed failure message so the
        GUI never renders stale data as current.
        """
        if self._busy:
            return
        self._busy = True
        try:
            snapshot = self._collector.collect()
        except ADBError as exc:
            from ..applications import ApplicationSnapshot

            self.inventory_ready.emit(ApplicationSnapshot(timestamp=0.0))
            self.inventory_failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - collector bug never freezes the GUI
            log_unexpected_failure("apps", "inventory", exc)
            from ..applications import ApplicationSnapshot

            self.inventory_ready.emit(ApplicationSnapshot(timestamp=0.0))
            self.inventory_failed.emit("The application list could not be read.")
            return
        finally:
            self._busy = False
        self._inventory = snapshot
        self.inventory_ready.emit(snapshot)

    @Slot(object)
    def resolve_labels(self, packages: object) -> None:
        """Resolve human-readable labels for *packages* from their APKs.

        Each package's APK path comes from the most recent inventory; a
        package with no inventory entry or no APK path maps to ``None``
        (the GUI falls back to the package name). Any device/parse error
        for a single package yields ``None`` for that package only — label
        resolution is best-effort and never fabricated.
        """
        names = [str(p) for p in packages] if isinstance(packages, (list, tuple, set)) else []
        result: dict[str, str | None] = {}
        if self._inventory is None:
            self.labels_ready.emit(result)
            return
        by_package = {app.package_name: app for app in self._inventory.applications}
        for package in names:
            info = by_package.get(package)
            if info is None or not info.apk_path:
                result[package] = None
                continue
            try:
                result[package] = self._label_resolver.resolve(info.apk_path)
            except ADBError:
                result[package] = None
            except Exception as exc:  # noqa: BLE001 - one bad APK must not sink the batch
                log_unexpected_failure("apps", "label", exc)
                result[package] = None
        self.labels_ready.emit(result)

    @Slot(object)
    def request_details(self, package: object) -> None:
        """Read one package's detail record and publish the typed result.

        Only the latest request matters: a duplicate detail read while one
        is in flight is dropped, and stale results are discarded by the
        GUI layer via package matching.
        """
        name = str(package).strip()
        if not name:
            self.details_failed.emit("", "invalid package: empty name")
            return
        try:
            details = self._collector.collect_details(name)
        except ADBError as exc:
            self.details_failed.emit(name, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - collector bug never freezes the GUI
            log_unexpected_failure("apps", "details", exc)
            self.details_failed.emit(name, "The application details could not be read.")
            return
        self.details_ready.emit(details)

    @Slot(object, str)
    def on_connection_changed(self, state, _detail: str) -> None:
        """Refresh the inventory whenever the device (re)connects.

        Runs on this worker's thread (queued from the monitor thread), so
        the ``pm list`` subprocess never blocks the GUI.
        """
        if state is ConnectionState.CONNECTED:
            self.refresh_inventory()


__all__ = ["AppsWorker"]
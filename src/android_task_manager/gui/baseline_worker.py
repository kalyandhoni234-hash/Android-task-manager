"""Worker that runs baseline save/check/export operations off the GUI thread.

Scans, diffs and heuristic evaluation all involve device reads, so — like the
monitor/inspector/action workers — everything runs on a QThread through
queued connections; the dashboard never blocks while a baseline is being
captured or compared. File exports (JSON/CSV) are also written off the GUI
thread here.

The worker builds its own baseline snapshot from the existing collectors
(process list + network investigation sample, which carries the package map
and socket tables), exactly like the baseline test suite does. Device read
failures surface as typed messages via the failure signals — never as GUI
exceptions. Duplicate save/check requests while one is in flight are dropped
(the same convention as ActionWorker).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from ..adb.connection import CommandRunner, ConnectionManager
from ..adb.exceptions import ADBError
from ..baseline import (
    BaselineSnapshot,
    DriftReport,
    Session,
    build_snapshot,
    diff_snapshot,
    write_drift_events_csv,
    write_session_json,
)
from ..heuristics import HeuristicReport, evaluate_heuristics
from ..network_investigation.collector import NetworkInvestigationCollector
from ..process.collector import ProcessCollector

_JSON = "json"
_CSV = "csv"


class BaselineWorker(QObject):
    """One-shot baseline capture, drift check, and session export."""

    #: (BaselineSnapshot) a baseline was captured successfully
    baseline_saved = Signal(object)
    #: (message) the device read or connection failed
    baseline_failed = Signal(str)
    #: (DriftReport, current BaselineSnapshot, HeuristicReport) a check ran
    drift_checked = Signal(object, object, object)
    #: (message) the drift check's device read failed
    drift_failed = Signal(str)
    #: (success, message) an export finished (or failed) — never silent
    export_completed = Signal(bool, str)

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
        self._process_collector = ProcessCollector(self._connection, timeout=timeout)
        self._investigation_collector = NetworkInvestigationCollector(
            self._connection, timeout=timeout
        )
        self._busy = False
        self._export_busy = False

    # ------------------------------------------------------------------
    # Test/status accessors
    # ------------------------------------------------------------------

    def is_busy(self) -> bool:
        """True while a save or drift check is in flight."""
        return self._busy

    def is_exporting(self) -> bool:
        """True while an export is being written."""
        return self._export_busy

    # ------------------------------------------------------------------
    # Synchronous operations (used by tests; slots call these)
    # ------------------------------------------------------------------

    def build(self) -> BaselineSnapshot:
        """Capture a fresh baseline snapshot from the connected device.

        Raises the typed ADB exceptions on device/connection failure.
        """
        serial = self._connection.require_device()
        return self._collect(serial)

    def _collect(self, serial: str) -> BaselineSnapshot:
        """Read the process + investigation samples and project a snapshot."""
        processes = self._process_collector.sample()
        investigation = self._investigation_collector.sample()
        installed_packages = {
            name for names in investigation.uid_packages.values() for name in names
        }
        return build_snapshot(
            device_serial=serial,
            processes=processes.processes,
            installed_packages=installed_packages,
            uid_packages=investigation.uid_packages,
            sockets=investigation,
        )

    def check(self, baseline: BaselineSnapshot) -> tuple[DriftReport, BaselineSnapshot, HeuristicReport]:
        """Diff the current state against *baseline* and run the heuristics.

        Returns ``(report, current_snapshot, heuristic_report)``; the
        current snapshot is returned so UI highlight layers can project
        the NEW identities without another device read.
        """
        current = self.build()
        report = diff_snapshot(baseline, current)
        heuristics = evaluate_heuristics(report, baseline, current)
        return report, current, heuristics

    def export_session(self, session: Session, kind: str, path: str) -> str:
        """Write *session* to *path* in the requested format; returns a
        human-readable confirmation message. Raises on write errors."""
        if kind == _JSON:
            write_session_json(session, path)
            return f"Exported session JSON to {path}."
        if kind == _CSV:
            write_drift_events_csv(session.drift_report, path)
            return f"Exported drift events CSV to {path}."
        raise ValueError(f"unsupported export format: {kind!r}")

    # ------------------------------------------------------------------
    # Slots (delivered onto this worker's thread by queued connections)
    # ------------------------------------------------------------------

    @Slot()
    def request_save_baseline(self) -> None:
        """Capture a baseline and publish it (or a failure message)."""
        if self._busy:
            return
        self._busy = True
        try:
            snapshot = self.build()
        except ADBError as exc:
            self.baseline_failed.emit(str(exc))
            return
        except Exception:  # noqa: BLE001 - a worker bug never freezes the GUI
            self.baseline_failed.emit("The baseline save failed unexpectedly.")
            return
        finally:
            self._busy = False
        self.baseline_saved.emit(snapshot)

    @Slot(object)
    def request_drift_check(self, baseline: object) -> None:
        """Diff the current state against *baseline* and evaluate heuristics."""
        if self._busy:
            return
        self._busy = True
        try:
            report, current, heuristics = self.check(baseline)
        except ADBError as exc:
            self.drift_failed.emit(str(exc))
            return
        except Exception:  # noqa: BLE001 - a worker bug never freezes the GUI
            self.drift_failed.emit("The drift check failed unexpectedly.")
            return
        finally:
            self._busy = False
        self.drift_checked.emit(report, current, heuristics)

    @Slot(str, str, object)
    def request_export(self, kind: object, path: object, session: object) -> None:
        """Write the session export off the GUI thread; always reports back."""
        if not isinstance(kind, str) or not isinstance(path, str):
            self.export_completed.emit(False, "The export was cancelled.")
            return
        if self._export_busy:
            return
        self._export_busy = True
        try:
            message = self.export_session(session, kind, path)
        except (OSError, ValueError) as exc:
            self.export_completed.emit(False, f"Export failed: {exc}")
            return
        except Exception:  # noqa: BLE001 - a worker bug never freezes the GUI
            self.export_completed.emit(False, "The export failed unexpectedly.")
            return
        finally:
            self._export_busy = False
        self.export_completed.emit(True, message)
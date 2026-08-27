"""Qt-facing integration adapter for the performance engine.

This is the only performance module that knows about Qt. It is a thin
translation/orchestration layer:

* it subscribes to the **existing** ``MonitorWorker`` signals (it defines no
  new signal, no new timer, no new worker);
* it forwards each update to the pure :class:`PerformanceOrchestrator`,
  which owns all analysis logic;
* it re-publishes the orchestrator's output (evidence / findings / events) on
  Qt signals for the GUI to consume later.

All diagnostic reasoning lives in ``android_task_manager.performance`` (Qt-
independent). This object performs no ADB, no subprocess and never touches a
widget directly.
"""

from __future__ import annotations

import time
from typing import cast

from PySide6.QtCore import QObject, Signal, Slot

from ..background.models import BackgroundAppsSnapshot
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..performance.orchestrator import OrchestratorResult, PerformanceOrchestrator
from ..process.models import ProcessSnapshot
from ..storage.models import StorageSnapshot
from .monitor import _DEVICE_LOSS_STATES, ConnectionState


class PerformanceIntegration(QObject):
    """Bridges MonitorWorker snapshots to the performance domain."""

    #: (tuple[PerformanceEvidence, ...])
    evidence_ready = Signal(object)
    #: (tuple[DiagnosticFinding, ...]) — deduplicated, newly started findings.
    findings_ready = Signal(object)
    #: (tuple[PerformanceEvent, ...]) — lifecycle events.
    events_ready = Signal(object)

    def __init__(
        self,
        orchestrator: PerformanceOrchestrator | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._orchestrator = orchestrator or PerformanceOrchestrator()

    @property
    def orchestrator(self) -> PerformanceOrchestrator:
        return self._orchestrator

    # ------------------------------------------------------------------
    # Snapshot ingestion (existing MonitorWorker signals)
    # ------------------------------------------------------------------

    @Slot(object, object, object, object, object)
    def on_snapshots(
        self,
        cpu: CPUSnapshot | None,
        memory: MemorySnapshot | None,
        processes: ProcessSnapshot | None,
        battery: BatterySnapshot | None,
        network: NetworkSnapshot | None,
    ) -> None:
        ts = cpu.timestamp if cpu is not None else None
        self._emit(
            self._orchestrator.ingest(
                cpu=cpu,
                memory=memory,
                processes=processes,
                battery=battery,
                network=network,
                timestamp=ts,
            )
        )

    @Slot(object)
    def on_storage(self, storage: StorageSnapshot | None) -> None:
        ts = storage.timestamp if storage is not None else None
        self._emit(self._orchestrator.ingest(storage=storage, timestamp=ts))

    @Slot(object)
    def on_background_apps(self, background_apps: object) -> None:
        """Receive the already-resolved v0.8.1 background-app snapshot."""
        bg = cast("BackgroundAppsSnapshot | None", background_apps)
        self._orchestrator.set_background_apps(bg)
        self._emit(
            self._orchestrator.ingest(
                background_apps=bg, timestamp=time.monotonic()
            )
        )

    # ------------------------------------------------------------------
    # Lifecycle (existing MonitorWorker signals)
    # ------------------------------------------------------------------

    @Slot(str)
    def on_serial_ready(self, serial: str) -> None:
        self._orchestrator.begin_session(serial, timestamp=time.monotonic())

    @Slot(object, str)
    def on_connection_changed(self, state: object, detail: str) -> None:
        if state is ConnectionState.CONNECTED:
            if self._orchestrator.session.device_serial is None:
                self._orchestrator.begin_session(None, timestamp=time.monotonic())
        elif state in _DEVICE_LOSS_STATES:
            # Device lost: close the live session so no stale state survives.
            self._orchestrator.end_session()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _emit(self, result: object) -> None:
        res = cast(OrchestratorResult, result)
        if res.evidence:
            self.evidence_ready.emit(res.evidence)
        if res.findings:
            self.findings_ready.emit(res.findings)
        if res.events:
            self.events_ready.emit(res.events)


__all__ = ["PerformanceIntegration"]

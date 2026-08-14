"""Central monitoring worker: drives the existing collectors on a worker thread.

This is the only GUI component that talks to the ADB layer: it builds the
shared ``ConnectionManager`` and the existing collectors, and emits normalized
snapshots into the GUI thread via Qt signals. Widgets never run ADB commands,
never parse device output, and never touch ``subprocess``.

Sampling cadence mirrors the terminal app: CPU every tick, memory/process/
battery on their own slower intervals, re-emitting the last cached snapshot
in between.
"""

from __future__ import annotations

import time
from enum import Enum

from PySide6.QtCore import QObject, Signal

from ..adb.connection import CommandRunner, ConnectionManager
from ..adb.exceptions import (
    ADBError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from ..battery.collector import BatteryCollector
from ..cpu.collector import CPUCollector
from ..memory.collector import MemoryCollector
from ..network.collector import NetworkCollector
from ..process.collector import ProcessCollector


class ConnectionState(Enum):
    """Coarse GUI-facing state of the monitoring pipeline."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ADB_ERROR = "adb error"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    COLLECTOR_ERROR = "collector error"


class MonitorWorker(QObject):
    """Runs one sampling loop and publishes normalized snapshots via signals.

    Instantiate on the GUI thread, then ``moveToThread`` onto a QThread and
    start the thread with ``started`` connected to ``run`` (see
    ``gui.app.main``). In tests the worker can also be run synchronously by
    calling ``tick()`` directly without any thread.
    """

    #: (cpu, memory, processes, battery, network) — cached snapshot objects
    #: (None until that collector has produced its first successful result).
    snapshots = Signal(object, object, object, object, object)
    #: (device_label, android_version)
    device_info = Signal(str, str)
    #: (ConnectionState, error_detail)
    connection_changed = Signal(object, str)

    def __init__(
        self,
        connection: CommandRunner | None = None,
        adb_path: str = "adb",
        timeout: float = 10.0,
        device_serial: str | None = None,
        cpu_interval: float = 2.0,
        memory_interval: float = 10.0,
        process_interval: float = 5.0,
        battery_interval: float = 15.0,
        network_interval: float = 5.0,
    ) -> None:
        super().__init__()
        self._connection = connection or ConnectionManager(
            adb_path=adb_path,
            timeout=timeout,
            device_serial=device_serial,
        )
        self._cpu_collector = CPUCollector(self._connection)
        self._memory_collector = MemoryCollector(self._connection)
        self._process_collector = ProcessCollector(self._connection)
        self._battery_collector = BatteryCollector(self._connection)
        self._network_collector = NetworkCollector(self._connection)

        self._cpu_interval = cpu_interval
        self._memory_interval = memory_interval
        self._process_interval = process_interval
        self._battery_interval = battery_interval
        self._network_interval = network_interval

        self._stopped = False
        self._cpu: object | None = None
        self._memory: object | None = None
        self._processes: object | None = None
        self._battery: object | None = None
        self._network: object | None = None
        self._last_memory_at = 0.0
        self._last_process_at = 0.0
        self._last_battery_at = 0.0
        self._last_network_at = 0.0

    # ------------------------------------------------------------------
    # Lifecycle / loop
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Ask the sampling loop to exit after the current tick."""
        self._stopped = True

    def run(self) -> None:
        """The worker-thread entry point: connect, then sample forever."""
        self._connect()
        while not self._stopped:
            start = time.monotonic()
            self.tick()
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, self._cpu_interval - elapsed))

    def _connect(self) -> None:
        try:
            self._connection.verify_available()
            serial = self._connection.require_device()
            manufacturer = self._connection.shell(["getprop", "ro.product.manufacturer"]).strip()
            model = self._connection.shell(["getprop", "ro.product.model"]).strip()
            release = self._connection.shell(["getprop", "ro.build.version.release"]).strip()
            label = f"{manufacturer} {model}".strip() or serial
            self.device_info.emit(label, release or "Unknown")
            self.connection_changed.emit(ConnectionState.CONNECTED, "")
        except ADBUnauthorizedError as exc:
            self.connection_changed.emit(ConnectionState.UNAUTHORIZED, str(exc))
        except ADBTimeoutError as exc:
            self.connection_changed.emit(ConnectionState.TIMEOUT, str(exc))
        except ADBError as exc:
            self.connection_changed.emit(ConnectionState.ADB_ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001 - never surface tracebacks
            self.connection_changed.emit(ConnectionState.ADB_ERROR, str(exc))

    def tick(self) -> None:
        """Collect one round of samples and publish the cached snapshots.

        Public for synchronous testing; normally driven by ``run``.
        """
        errors: list[str] = []
        state = ConnectionState.CONNECTED

        def collect(label: str, sampler, holder: str) -> None:
            nonlocal state, errors
            try:
                setattr(self, holder, sampler())
            except ADBUnauthorizedError as exc:
                state = ConnectionState.UNAUTHORIZED
                errors.append(f"{label}: {exc}")
            except ADBTimeoutError as exc:
                state = ConnectionState.TIMEOUT
                errors.append(f"{label}: {exc}")
            except ADBNoDeviceError as exc:
                state = ConnectionState.DISCONNECTED
                errors.append(f"{label}: {exc}")
            except ADBError as exc:
                state = ConnectionState.ADB_ERROR
                errors.append(f"{label}: {exc}")
            except Exception as exc:  # noqa: BLE001 - collector bug ≠ GUI crash
                state = ConnectionState.COLLECTOR_ERROR
                errors.append(f"{label}: {exc}")

        collect("cpu", self._cpu_collector.sample, "_cpu")

        now = time.monotonic()
        if self._memory is None or (now - self._last_memory_at) >= self._memory_interval:
            collect("memory", self._memory_collector.sample, "_memory")
            self._last_memory_at = time.monotonic()
        if self._processes is None or (now - self._last_process_at) >= self._process_interval:
            collect("process", self._process_collector.sample, "_processes")
            self._last_process_at = time.monotonic()
        if self._battery is None or (now - self._last_battery_at) >= self._battery_interval:
            collect("battery", self._battery_collector.sample, "_battery")
            self._last_battery_at = time.monotonic()
        if self._network is None or (now - self._last_network_at) >= self._network_interval:
            collect("network", self._network_collector.sample, "_network")
            self._last_network_at = time.monotonic()

        if errors:
            self.connection_changed.emit(state, "; ".join(errors))
        else:
            self.connection_changed.emit(ConnectionState.CONNECTED, "")

        self.snapshots.emit(self._cpu, self._memory, self._processes, self._battery, self._network)
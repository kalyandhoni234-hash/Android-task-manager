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
    ADBAmbiguousDeviceError,
    ADBDisconnectedError,
    ADBError,
    ADBNotFoundError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from ..battery.collector import BatteryCollector
from ..cpu.collector import CPUCollector
from ..device.collector import DeviceInfoCollector
from ..memory.collector import MemoryCollector
from ..network.collector import NetworkCollector
from ..network_investigation.collector import NetworkInvestigationCollector
from ..process.collector import ProcessCollector


class ConnectionState(Enum):
    """Coarse GUI-facing state of the monitoring pipeline."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    #: adb itself could not be found / is not usable.
    ADB_MISSING = "adb missing"
    #: adb works, but the device is connected and "offline" (bad cable, adb
    #: server hiccup, or the device just dropped off the bus).
    OFFLINE = "offline"
    #: More than one authorized device; the GUI must let the user pick one.
    MULTIPLE_DEVICES = "multiple devices"
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
    #: (NetworkInvestigationSnapshot) — the socket-level view from the
    #: investigation collector; published on its own slower cadence.
    network_investigation = Signal(object)
    #: (device_label, android_version)
    device_info = Signal(str, str)
    #: (DeviceInformation) — the structured identity snapshot, emitted once
    #: per successful connection (static facts are cached for the session).
    device_information = Signal(object)
    #: (ConnectionState, error_detail)
    connection_changed = Signal(object, str)
    #: (list[dict]) — attached devices for the multi-device selection UI. Each
    #: entry has "serial", "state", "label" (manufacturer + model) and
    #: "android_version" keys.
    devices_available = Signal(object)

    #: How long to wait between failed connection attempts in ``run``.
    _RETRY_DELAY_S = 2.0

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
        network_investigation_interval: float = 10.0,
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
        self._network_investigation_collector = NetworkInvestigationCollector(self._connection)
        self._device_info_collector = DeviceInfoCollector(self._connection)

        self._cpu_interval = cpu_interval
        self._memory_interval = memory_interval
        self._process_interval = process_interval
        self._battery_interval = battery_interval
        self._network_interval = network_interval
        self._network_investigation_interval = network_investigation_interval

        self._stopped = False
        self._cpu: object | None = None
        self._memory: object | None = None
        self._processes: object | None = None
        self._battery: object | None = None
        self._network: object | None = None
        self._network_investigation: object | None = None
        self._last_memory_at = 0.0
        self._last_process_at = 0.0
        self._last_battery_at = 0.0
        self._last_network_at = 0.0
        self._last_network_investigation_at = 0.0

    # ------------------------------------------------------------------
    # Lifecycle / loop
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Ask the sampling loop to exit after the current tick."""
        self._stopped = True

    def run(self) -> None:
        """The worker-thread entry point: connect, then sample forever.

        Connection is attempted immediately and re-attempted every
        ``_RETRY_DELAY_S`` while it fails, so hot-plugging a phone, authorizing
        USB debugging, or locating adb mid-session recovers without restarting
        the app. Sampling only starts once a device is connected.
        """
        self._connected = False
        while not self._stopped:
            if not self._connected:
                self._connect()
                if not self._connected:
                    time.sleep(self._RETRY_DELAY_S)
                    continue
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
            # One structured identity snapshot per connection session; the
            # collector tolerates per-property failures, so a single blocked
            # property never fails the connect. A total command failure maps
            # through the same typed ADB errors as the rest of the pipeline.
            self.device_information.emit(self._device_info_collector.sample())
            self._connected = True
            self.connection_changed.emit(ConnectionState.CONNECTED, "")
        except ADBNotFoundError as exc:
            self._connected = False
            self.connection_changed.emit(ConnectionState.ADB_MISSING, str(exc))
        except ADBAmbiguousDeviceError as exc:
            self._connected = False
            self.connection_changed.emit(ConnectionState.MULTIPLE_DEVICES, str(exc))
            self._report_devices()
        except ADBNoDeviceError as exc:
            self._connected = False
            self.connection_changed.emit(ConnectionState.DISCONNECTED, str(exc))
        except ADBDisconnectedError as exc:
            self._connected = False
            self.connection_changed.emit(ConnectionState.OFFLINE, str(exc))
        except ADBUnauthorizedError as exc:
            self._connected = False
            self.connection_changed.emit(ConnectionState.UNAUTHORIZED, str(exc))
        except ADBTimeoutError as exc:
            self._connected = False
            self.connection_changed.emit(ConnectionState.TIMEOUT, str(exc))
        except Exception as exc:  # noqa: BLE001 - never surface tracebacks
            self._connected = False
            self.connection_changed.emit(ConnectionState.ADB_ERROR, str(exc))

    def _report_devices(self) -> None:
        """Enumerate attached devices (best-effort) for the selection UI."""
        devices: list[dict[str, str]] = []
        try:
            for device in self._connection.list_devices():
                entry = {"serial": device.serial, "state": device.state}
                if device.state == "device":
                    details = self._connection.get_device_details(device.serial)
                    manufacturer = details.get("ro.product.manufacturer", "")
                    model = details.get("ro.product.model", "")
                    entry["label"] = f"{manufacturer} {model}".strip() or device.serial
                    entry["android_version"] = details.get("ro.build.version.release", "")
                else:
                    entry["label"] = device.serial
                    entry["android_version"] = ""
                devices.append(entry)
        except Exception:  # noqa: BLE001 - listing must never crash the loop
            devices = []
        self.devices_available.emit(devices)

    # ------------------------------------------------------------------
    # GUI-driven reconfiguration (invoked from the GUI thread; delivered
    # on the worker thread via Qt's queued connections)
    # ------------------------------------------------------------------

    def retry(self) -> None:
        """Re-attempt the connection immediately (e.g. the Retry button)."""
        if not self._stopped:
            self._connect()

    def set_adb_path(self, adb_path: str) -> None:
        """Switch the shared connection to a different adb executable."""
        setter = getattr(self._connection, "set_adb_path", None)
        if setter is not None:
            setter(adb_path)
        if not self._stopped:
            self._connect()

    def select_device(self, serial: str) -> None:
        """Pin the target device to *serial* and reconnect to it."""
        setter = getattr(self._connection, "set_device_serial", None)
        if setter is not None:
            setter(serial)
        if not self._stopped:
            self._connect()

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
            except ADBDisconnectedError as exc:
                state = ConnectionState.OFFLINE
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
        if self._network_investigation is None or (
            now - self._last_network_investigation_at
        ) >= self._network_investigation_interval:
            collect(
                "network investigation",
                self._network_investigation_collector.sample,
                "_network_investigation",
            )
            self._last_network_investigation_at = time.monotonic()

        if errors:
            self.connection_changed.emit(state, "; ".join(errors))
        else:
            self.connection_changed.emit(ConnectionState.CONNECTED, "")

        self.snapshots.emit(self._cpu, self._memory, self._processes, self._battery, self._network)
        if self._network_investigation is not None:
            self.network_investigation.emit(self._network_investigation)
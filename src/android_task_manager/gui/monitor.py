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

import logging
import time
from enum import Enum

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..adb.connection import CommandRunner, ConnectionManager
from ..adb.exceptions import (
    ADBAmbiguousDeviceError,
    ADBDisconnectedError,
    ADBError,
    ADBNoDeviceError,
    ADBNotFoundError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)
from ..battery.collector import BatteryCollector
from ..core.diagnostics import log_unexpected_failure
from ..cpu.collector import CPUCollector
from ..device.collector import DeviceInfoCollector
from ..memory.collector import MemoryCollector
from ..network.collector import NetworkCollector
from ..network_investigation.collector import NetworkInvestigationCollector
from ..process.collector import ProcessCollector

logger = logging.getLogger("android_task_manager.monitor")


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


#: States that mean the *device* is lost (as opposed to a transient single
#: read failure). Telemetry is invalidated and the connection re-established
#: from scratch when any of these is observed.
_DEVICE_LOSS_STATES = frozenset(
    {
        ConnectionState.DISCONNECTED,
        ConnectionState.OFFLINE,
        ConnectionState.UNAUTHORIZED,
        ConnectionState.ADB_ERROR,
    }
)


class MonitorWorker(QObject):
    """Runs one sampling loop and publishes normalized snapshots via signals.

    Instantiate on the GUI thread, then ``moveToThread`` onto a QThread and
    start the thread with ``started`` connected to ``run`` (see
    ``gui.app.main``). ``run`` starts a QTimer and returns, so the thread's
    event loop keeps running: queued slots (``retry``, ``select_device``,
    ``locate_adb``, ``stop``) are delivered while the timer drives
    connection attempts and sampling. In tests the worker can also be run
    synchronously by calling ``_connect()`` / ``tick()`` directly without
    any thread.
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
        self._timeout = timeout
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
        self._connected = False
        self._timer: QTimer | None = None
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

    @Slot()
    def stop(self) -> None:
        """Ask the sampling loop to exit after the current tick.

        Safe to call from any thread (a plain flag write). When the worker
        thread is inside a blocking ADB call, the loop exits once that call
        returns and the stop flag is observed.
        """
        self._stopped = True
        if self._timer is not None:
            self._timer.stop()

    def run(self) -> None:
        """The worker-thread entry point: start the sampling timer, then return.

        Connection is attempted immediately and re-attempted every
        ``_RETRY_DELAY_S`` while it fails, so hot-plugging a phone, authorizing
        USB debugging, or locating adb mid-session recovers without restarting
        the app. Sampling only starts once a device is connected.

        Returning (instead of looping) is deliberate: QThread's event loop
        then processes queued slots directed at this worker — ``retry``,
        ``select_device``, ``locate_adb`` and ``stop`` — while the timer
        drives connection + sampling.
        """
        self._connected = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        # An interval of 0 fires the first timeout as soon as the event
        # loop starts: the first connection attempt happens immediately.
        self._timer.start(0)

    def _on_timer(self) -> None:
        """One timer tick: (re)connect while offline, sample while online."""
        if self._stopped:
            return
        if not self._connected:
            self._connect()
            if not self._connected:
                self._timer.setInterval(int(self._RETRY_DELAY_S * 1000))
                return
            self._timer.setInterval(int(self._cpu_interval * 1000))
        self.tick()

    def _connect(self) -> None:
        try:
            self._connection.verify_available()
            if self._stopped:
                return
            serial = self._connection.require_device()
            if self._stopped:
                return
            manufacturer = self._connection.shell(["getprop", "ro.product.manufacturer"]).strip()
            model = self._connection.shell(["getprop", "ro.product.model"]).strip()
            release = self._connection.shell(["getprop", "ro.build.version.release"]).strip()
            if self._stopped:
                return
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
            self._connect_failed(ConnectionState.ADB_MISSING, exc)
        except ADBAmbiguousDeviceError as exc:
            self._connect_failed(ConnectionState.MULTIPLE_DEVICES, exc)
            self._report_devices()
        except ADBNoDeviceError as exc:
            self._connect_failed(ConnectionState.DISCONNECTED, exc)
        except ADBDisconnectedError as exc:
            self._connect_failed(ConnectionState.OFFLINE, exc)
        except ADBUnauthorizedError as exc:
            self._connect_failed(ConnectionState.UNAUTHORIZED, exc)
        except ADBTimeoutError as exc:
            self._connect_failed(ConnectionState.TIMEOUT, exc)
        except Exception as exc:  # noqa: BLE001 - never surface tracebacks
            log_unexpected_failure("monitor", "connect", exc)
            self._connect_failed(ConnectionState.ADB_ERROR, exc)

    def _connect_failed(self, state: ConnectionState, exc: BaseException) -> None:
        """Record a failed connect: log it, drop stale telemetry, emit."""
        logger.warning("connection failed (%s): %s", state.value, exc)
        self._connected = False
        self._invalidate_snapshots()
        self.connection_changed.emit(state, str(exc))

    def _invalidate_snapshots(self) -> None:
        """Drop every cached telemetry snapshot.

        Called when the device is lost: data collected from a previous
        device/session must never be presented as current, and the next
        successful connect re-collects everything from scratch.
        """
        self._cpu = None
        self._memory = None
        self._processes = None
        self._battery = None
        self._network = None
        self._network_investigation = None
        self._last_memory_at = 0.0
        self._last_process_at = 0.0
        self._last_battery_at = 0.0
        self._last_network_at = 0.0
        self._last_network_investigation_at = 0.0

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
        except Exception as exc:  # noqa: BLE001 - listing must never crash the loop
            log_unexpected_failure("monitor", "devices", exc)
            devices = []
        self.devices_available.emit(devices)

    # ------------------------------------------------------------------
    # GUI-driven reconfiguration (invoked from the GUI thread; delivered
    # on the worker thread via Qt's queued connections)
    # ------------------------------------------------------------------

    @Slot()
    def retry(self) -> None:
        """Re-attempt the connection immediately (e.g. the Retry button)."""
        if not self._stopped:
            self._connect()

    @Slot(str)
    def set_adb_path(self, adb_path: str) -> None:
        """Switch the shared connection to a different adb executable."""
        setter = getattr(self._connection, "set_adb_path", None)
        if setter is not None:
            setter(adb_path)
        if not self._stopped:
            self._connect()

    @Slot(str)
    def locate_adb(self, adb_path: str) -> None:
        """Validate a user-chosen adb executable, then reconnect with it.

        Runs entirely on the worker thread (queued from the GUI), so the
        ``adb version`` probe and the re-connect never block the UI. An
        unusable executable surfaces as the typed ADB_MISSING state with a
        message instead of being silently accepted.
        """
        if self._stopped:
            return
        from ..adb.discovery import is_usable_adb, version_validator

        if not is_usable_adb(adb_path, version_validator(self._timeout)):
            self.connection_changed.emit(
                ConnectionState.ADB_MISSING,
                f"'{adb_path}' is not a usable adb executable.",
            )
            return
        self.set_adb_path(adb_path)

    @Slot(str)
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
                log_unexpected_failure("monitor.collect", label, exc)
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
            if state in _DEVICE_LOSS_STATES:
                # The device is gone: drop every cached snapshot (telemetry
                # from the old session must never be presented as current),
                # publish an unambiguous empty snapshot, and let run()'s loop
                # re-establish the connection from scratch.
                logger.warning(
                    "device lost while sampling (%s): %s", state.value, "; ".join(errors)
                )
                self._invalidate_snapshots()
                self._connected = False
                self.snapshots.emit(None, None, None, None, None)
                return
        else:
            self.connection_changed.emit(ConnectionState.CONNECTED, "")

        self.snapshots.emit(self._cpu, self._memory, self._processes, self._battery, self._network)
        if self._network_investigation is not None:
            self.network_investigation.emit(self._network_investigation)
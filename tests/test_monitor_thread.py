"""Real-thread monitor tests: queued slots must be delivered (F-02 guard).

The pre-fix implementation blocked the worker thread in a ``while`` loop
with ``time.sleep`` and never entered Qt's event loop, so queued slots
(``retry`` / ``select_device`` / ``stop``) were never delivered. These
tests run a real QThread + event loop and fail against that
implementation: the queued invocation is only processed when the event
loop is running.

Synchronization mirrors ``test_updater_gui``: ``threading.Event`` /
bounded deadlines with ``QApplication.processEvents`` — no arbitrary
sleeps, every wait has a deadline.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Q_ARG, QMetaObject, Qt, QThread
from PySide6.QtWidgets import QApplication

from android_task_manager.adb.exceptions import ADBNoDeviceError
from android_task_manager.gui.monitor import MonitorWorker


class _NoDeviceConnection:
    """Fast-failing connection: every connect attempt emits DISCONNECTED.

    ``set_device_serial`` records deliveries — it is only ever invoked
    through the ``select_device`` queued slot, which makes it the perfect
    discriminator between an event loop that delivers queued slots and a
    blocking loop that never does.
    """

    def __init__(self) -> None:
        self.selected_serials: list[str | None] = []

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        raise ADBNoDeviceError("no device attached")

    def set_device_serial(self, serial: str | None) -> None:
        self.selected_serials.append(serial)

    def shell(self, args, timeout=None) -> str:  # noqa: ARG002 - protocol signature
        return ""


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _start_worker(worker: MonitorWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
    return thread


def _process_until(condition, timeout_s: float = 5.0) -> bool:
    """Drain the main-thread event queue until *condition* or the deadline."""
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    return condition()


def test_queued_select_device_is_delivered_while_running(qtapp) -> None:
    """A queued ``select_device`` reaches the worker on its own thread.

    The recorded serial can only be produced by the worker processing the
    queued invocation; the old blocking-loop implementation never did, so
    this fails against it.
    """
    connection = _NoDeviceConnection()
    worker = MonitorWorker(connection=connection)

    first_state = threading.Event()

    def on_state(_state, _detail: str) -> None:
        first_state.set()

    worker.connection_changed.connect(on_state)

    thread = _start_worker(worker)
    try:
        # The first connect attempt (from the initial timer tick) confirms
        # the worker thread is up and emitting states.
        assert _process_until(first_state.is_set, 5.0), "worker never connected"

        QMetaObject.invokeMethod(
            worker,
            "select_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, "FAKE123"),
        )
        assert _process_until(
            lambda: connection.selected_serials == ["FAKE123"], 5.0
        ), "queued select_device was never delivered"

        assert connection.selected_serials == ["FAKE123"]
    finally:
        worker.stop()
        thread.quit()
        thread.wait(5000)
        assert not thread.isRunning(), "worker thread did not stop cleanly"


def test_queued_retry_is_delivered_while_running(qtapp) -> None:
    """A queued ``retry`` triggers an immediate re-connect attempt.

    Discrimination via timing: the retry loop re-attempts only every 2 s,
    so an emission arriving within the sub-second window after the queued
    invocation can only come from the delivered retry slot.
    """
    connection = _NoDeviceConnection()
    worker = MonitorWorker(connection=connection)

    emissions = threading.Event()
    count = {"n": 0}

    def on_state(_state, _detail: str) -> None:
        count["n"] += 1
        emissions.set()

    worker.connection_changed.connect(on_state)

    thread = _start_worker(worker)
    try:
        assert _process_until(emissions.is_set, 5.0), "worker never connected"
        emissions.clear()
        before = count["n"]

        QMetaObject.invokeMethod(worker, "retry", Qt.ConnectionType.QueuedConnection)
        # Well below the 2 s retry cadence: only a delivered retry can emit.
        assert _process_until(emissions.is_set, 0.5), "retry was not delivered"

        assert count["n"] > before
    finally:
        worker.stop()
        thread.quit()
        thread.wait(5000)
        assert not thread.isRunning(), "worker thread did not stop cleanly"


def test_queued_stop_is_delivered_while_running(qtapp) -> None:
    """A queued ``stop`` reaches the worker and halts the sampling timer.

    With the old implementation the stop event was never delivered, so the
    stop flag stayed False and the timer kept running.
    """
    connection = _NoDeviceConnection()
    worker = MonitorWorker(connection=connection)

    first_state = threading.Event()

    def on_state(_state, _detail: str) -> None:
        first_state.set()

    worker.connection_changed.connect(on_state)

    thread = _start_worker(worker)
    try:
        assert _process_until(first_state.is_set, 5.0), "worker never connected"

        QMetaObject.invokeMethod(worker, "stop", Qt.ConnectionType.QueuedConnection)

        assert _process_until(lambda: worker._stopped, 5.0), (  # noqa: SLF001
            "queued stop was never delivered"
        )

        # The queued stop was delivered: the sampling timer is halted.
        assert worker._timer is not None
        assert not worker._timer.isActive(), "sampling timer still armed after stop"
    finally:
        thread.quit()
        thread.wait(5000)
        assert not thread.isRunning(), "worker thread did not stop cleanly"

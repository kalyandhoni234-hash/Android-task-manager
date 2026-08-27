"""GUI-level tests for Device Actions: availability, confirmation, worker,
and wiring. Mirrors the conventions of test_gui.py (offscreen Qt)."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from android_task_manager.action import ActionErrorKind, ActionResult
from android_task_manager.adb.exceptions import ADBDisconnectedError
from android_task_manager.gui import main_window as mw_main
from android_task_manager.gui.action_worker import ActionWorker
from android_task_manager.gui.main_window import MainWindow, wire, wire_actions
from android_task_manager.gui.monitor import MonitorWorker
from android_task_manager.gui.widgets.process_inspector_widget import (
    ProcessInspectorWidget,
)
from android_task_manager.process.inspector_models import ProcessInspectionSnapshot


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def app_snapshot(command_line: str | None = None) -> ProcessInspectionSnapshot:
    return ProcessInspectionSnapshot(
        pid=8150,
        name="com.heavy.app",
        uid=10001,
        state="R",
        command_line=command_line,
        timestamp=1.0,
    )


def kernel_snapshot() -> ProcessInspectionSnapshot:
    return ProcessInspectionSnapshot(pid=17, name="kworker/0:1", uid=0, timestamp=1.0)


def system_snapshot() -> ProcessInspectionSnapshot:
    return ProcessInspectionSnapshot(
        pid=1054, name="system_server", uid=1000, timestamp=1.0
    )


PACKAGES = {"com.heavy.app", "com.instagram.android", "com.android.systemui"}


class _FakeRunner:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.fail: BaseException | None = None

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if self.fail is not None:
            raise self.fail
        return self.responses.get(" ".join(args), "")


# ---------------------------------------------------------------------------
# ProcessInspectorWidget: action availability
# ---------------------------------------------------------------------------


def _show_dashboard(window: MainWindow) -> None:
    """Flip the stacked window onto the live dashboard (device connected)
    and open the PROCESSES page, where the inspector panel lives."""
    from android_task_manager.gui.monitor import ConnectionState

    window.show()
    window.update_connection(ConnectionState.CONNECTED, "ok")
    window.sidebar.button("processes").click()
    QApplication.processEvents()


def test_actions_section_renders_inside_live_dashboard(qtapp) -> None:
    # Regression: the actions row must be visible in the real window path
    # (MainWindow -> ProcessWidget -> ProcessInspectorWidget) once the
    # dashboard page is shown, not only on a standalone inspector widget.
    window = MainWindow()
    _show_dashboard(window)
    window.processes.inspector.set_packages(PACKAGES)
    window.processes.inspector.set_snapshot(app_snapshot())
    QApplication.processEvents()
    inspector = window.processes.inspector
    assert inspector.isVisible()
    assert inspector._actions_caption.isVisible()
    assert inspector._open_btn.isVisible()
    assert inspector._info_btn.isVisible()
    assert inspector._stop_btn.isVisible()
    assert inspector._open_btn.isEnabled()
    assert inspector._stop_btn.isEnabled()


def test_actions_section_visible_but_disabled_for_unverified(qtapp) -> None:
    # The section must stay visible for kernel/system rows — never hidden.
    window = MainWindow()
    _show_dashboard(window)
    window.processes.inspector.set_packages(PACKAGES)
    window.processes.inspector.set_snapshot(system_snapshot())
    QApplication.processEvents()
    inspector = window.processes.inspector
    assert inspector._actions_caption.isVisible()
    assert inspector._open_btn.isVisible()
    assert inspector._stop_btn.isVisible()
    assert not inspector._open_btn.isEnabled()
    assert not inspector._stop_btn.isEnabled()
    assert (
        inspector._actions_caption.text()
        == "Application actions unavailable for this process."
    )


def test_actions_disabled_before_any_inspection(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    assert not widget._open_btn.isEnabled()
    assert not widget._stop_btn.isEnabled()
    assert widget.resolved_package() is None


def test_actions_enabled_for_verified_app_process(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    assert widget.resolved_package() == "com.heavy.app"
    assert widget._open_btn.isEnabled()
    assert widget._info_btn.isEnabled()
    assert widget._stop_btn.isEnabled()
    assert widget._actions_caption.text() == "Actions for com.heavy.app"


def test_actions_resolve_via_command_line_argv0(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    # ps NAME truncated; the cmdline argv0 is the verified identity.
    snapshot = app_snapshot()
    snapshot = ProcessInspectionSnapshot(
        pid=snapshot.pid,
        name="avy.app",
        uid=snapshot.uid,
        command_line="com.heavy.app --fg",
        timestamp=1.0,
    )
    widget.set_snapshot(snapshot)
    assert widget.resolved_package() == "com.heavy.app"
    assert widget._open_btn.isEnabled()


def test_kernel_thread_never_gets_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(kernel_snapshot())
    assert widget.resolved_package() is None
    assert not widget._open_btn.isEnabled()
    assert not widget._stop_btn.isEnabled()
    assert widget._actions_caption.text() == "Application actions unavailable for this process."


def test_system_process_without_verified_identity_gets_no_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(system_snapshot())
    assert widget.resolved_package() is None
    assert not widget._open_btn.isEnabled()


def test_empty_package_list_blocks_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(set())
    widget.set_snapshot(app_snapshot())
    assert widget.resolved_package() is None
    assert not widget._stop_btn.isEnabled()


def test_package_list_arriving_after_inspection_enables_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_snapshot(app_snapshot())
    assert widget.resolved_package() is None
    widget.set_packages(PACKAGES)
    assert widget.resolved_package() == "com.heavy.app"
    assert widget._stop_btn.isEnabled()


def test_set_gone_disables_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    assert widget._open_btn.isEnabled()
    widget.set_gone(8150)
    assert widget.resolved_package() is None
    assert not widget._open_btn.isEnabled()
    assert widget._actions_caption.text() == "Actions unavailable"


def test_secondary_process_resolves_to_verified_base(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    snapshot = app_snapshot()
    snapshot = ProcessInspectionSnapshot(
        pid=snapshot.pid,
        name="com.heavy.app:remote",
        uid=snapshot.uid,
        timestamp=1.0,
    )
    widget.set_snapshot(snapshot)
    assert widget.resolved_package() == "com.heavy.app"
    assert widget._open_btn.isEnabled()
    assert widget._stop_btn.isEnabled()


def test_vendor_process_gets_no_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    snapshot = ProcessInspectionSnapshot(
        pid=141, name="surfaceflinger", uid=1000, timestamp=1.0
    )
    widget.set_snapshot(snapshot)
    assert widget.resolved_package() is None
    assert not widget._open_btn.isEnabled()
    assert widget._actions_caption.text() == "Application actions unavailable for this process."


def test_click_emits_action_with_package(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    emitted: list[tuple[str, str]] = []
    widget.action_requested.connect(lambda *args: emitted.append(args))
    widget._open_btn.click()
    widget._stop_btn.click()
    assert emitted == [("open_app", "com.heavy.app"), ("force_stop", "com.heavy.app")]


def test_click_without_package_emits_nothing(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(kernel_snapshot())
    emitted: list[tuple[str, str]] = []
    widget.action_requested.connect(lambda *args: emitted.append(args))
    widget._open_btn.click()
    widget._stop_btn.click()
    assert emitted == []


def test_busy_disables_buttons_until_released(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_actions_busy(True)
    assert not widget._open_btn.isEnabled()
    assert not widget._stop_btn.isEnabled()
    widget.set_actions_busy(False)
    assert widget._open_btn.isEnabled()
    assert widget._stop_btn.isEnabled()


# ---------------------------------------------------------------------------
# ProcessInspectorWidget: action result rendering
# ---------------------------------------------------------------------------


def test_success_result_shows_message_and_reenables(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_actions_busy(True)
    widget.show_action_result(
        ActionResult(action="open_app", package_name="com.heavy.app", success=True, message="Opened com.heavy.app")
    )
    assert widget._status.text() == "Opened com.heavy.app"
    assert widget._status.objectName() == "muted"
    assert widget._open_btn.isEnabled()


def test_failure_result_shows_typed_message(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    result = ActionResult(
        action="force_stop",
        package_name="com.heavy.app",
        success=False,
        message="Device disconnected. Reconnect your Android device and try again.",
        error_kind=ActionErrorKind.DISCONNECTED,
    )
    widget.show_action_result(result)
    assert widget._status.text() == result.message
    assert widget._status.objectName() == "statusWarn"
    assert widget._stop_btn.isEnabled()


def test_display_name_returns_process_name(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    assert widget.display_name() == "com.heavy.app"


# ---------------------------------------------------------------------------
# ActionWorker
# ---------------------------------------------------------------------------


def test_worker_executes_action_and_emits_result(qtapp) -> None:
    worker = ActionWorker(
        connection=_FakeRunner(
            {
                "cmd package resolve-activity --brief -c android.intent.category.LAUNCHER -a android.intent.action.MAIN com.heavy.app": "com.heavy.app/.Main\n",
                "am start -W -n com.heavy.app/.Main": "Status: ok",
            }
        ),
        timeout=3.0,
    )
    results: list[ActionResult] = []
    worker.action_completed.connect(lambda r: results.append(r))
    worker.request_action("open_app", "com.heavy.app")
    assert len(results) == 1
    assert results[0].success
    assert results[0].action == "open_app"
    assert results[0].package_name == "com.heavy.app"
    assert results[0].message == "Opened com.heavy.app"
    assert not worker.is_busy()


def test_worker_translates_service_failure_to_typed_result(qtapp) -> None:
    runner = _FakeRunner()
    runner.fail = ADBDisconnectedError("x")
    worker = ActionWorker(connection=runner, timeout=3.0)
    results: list[ActionResult] = []
    worker.action_completed.connect(lambda r: results.append(r))
    worker.request_action("force_stop", "com.heavy.app")
    assert len(results) == 1
    assert not results[0].success
    assert results[0].error_kind is ActionErrorKind.DISCONNECTED
    assert "Reconnect" in results[0].message


def test_worker_unknown_action_is_typed_failure(qtapp) -> None:
    worker = ActionWorker(connection=_FakeRunner(), timeout=3.0)
    results: list[ActionResult] = []
    worker.action_completed.connect(lambda r: results.append(r))
    worker.request_action("delete_everything", "com.heavy.app")
    assert len(results) == 1
    assert not results[0].success
    assert results[0].error_kind is ActionErrorKind.INVALID_TARGET


def test_worker_surprising_failure_never_crashes(qtapp, monkeypatch) -> None:
    worker = ActionWorker(connection=_FakeRunner(), timeout=3.0)

    def boom(action, package):
        raise RuntimeError("internal bug")

    monkeypatch.setattr(worker._service, "run", boom)
    results: list[ActionResult] = []
    worker.action_completed.connect(lambda r: results.append(r))
    worker.request_action("open_app", "com.heavy.app")
    assert len(results) == 1
    assert not results[0].success
    assert results[0].error_kind is ActionErrorKind.UNKNOWN
    assert "traceback" not in results[0].message.lower()


def test_worker_drops_duplicate_requests_while_busy(qtapp, monkeypatch) -> None:
    worker = ActionWorker(connection=_FakeRunner(), timeout=3.0)
    gate = threading.Event()
    entered = threading.Event()

    def slow_run(action, package):
        entered.set()
        assert gate.wait(5)
        return ActionResult(str(action), str(package), True, "ok")

    monkeypatch.setattr(worker._service, "run", slow_run)
    results: list[ActionResult] = []
    worker.action_completed.connect(
        lambda r: results.append(r), Qt.ConnectionType.DirectConnection
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(worker.request_action, "open_app", "com.heavy.app")
        assert entered.wait(5)
        worker.request_action("open_app", "com.heavy.app")  # duplicate: dropped
        assert worker.is_busy()
        gate.set()
        future.result(5)
    assert len(results) == 1


def test_worker_reload_packages_emits_parsed_set(qtapp) -> None:
    worker = ActionWorker(
        connection=_FakeRunner({"pm list packages": "package:com.heavy.app\npackage:org.foo\n"}),
        timeout=3.0,
    )
    received: list = []
    worker.packages_ready.connect(lambda p: received.append(p))
    worker.reload_packages()
    assert received == [{"com.heavy.app", "org.foo"}]
    assert worker.packages() == {"com.heavy.app", "org.foo"}


def test_worker_reload_packages_failure_emits_empty_set(qtapp) -> None:
    runner = _FakeRunner()

    def fail_shell(args, timeout=None):
        raise ADBDisconnectedError("gone")

    runner.shell = fail_shell  # type: ignore[method-assign]
    worker = ActionWorker(connection=runner, timeout=3.0)
    received: list = []
    worker.packages_ready.connect(lambda p: received.append(p))
    worker.reload_packages()
    assert len(received) == 1
    assert received[0] == frozenset()
    assert worker.packages() is None


def test_worker_not_found_drops_package_from_cache(qtapp) -> None:
    runner = _FakeRunner({"pm list packages": "package:com.heavy.app\npackage:org.foo\n"})
    fails: dict[str, BaseException] = {}

    def fail_shell(args, timeout=None):
        key = " ".join(args)
        if key in fails:
            raise fails.pop(key)
        return runner.responses.get(key, "")

    runner.shell = fail_shell  # type: ignore[method-assign]
    worker = ActionWorker(connection=runner, timeout=3.0)
    worker.reload_packages()
    assert worker.packages() == {"com.heavy.app", "org.foo"}

    from android_task_manager.adb.exceptions import ADBCommandError

    key = "am force-stop com.heavy.app"
    fails[key] = ADBCommandError(key, 1, stderr="Error: Unknown package: com.heavy.app")
    results: list[ActionResult] = []
    worker.action_completed.connect(lambda r: results.append(r))
    refreshed: list = []
    worker.packages_ready.connect(lambda p: refreshed.append(p))
    worker.request_action("force_stop", "com.heavy.app")
    assert len(results) == 1
    assert results[0].error_kind is ActionErrorKind.NOT_FOUND
    # The stale identity is dropped immediately, not at next reconnect.
    assert worker.packages() == {"org.foo"}
    assert refreshed and refreshed[-1] == {"org.foo"}


def test_worker_refresh_replaces_stale_cache(qtapp) -> None:
    runner = _FakeRunner({"pm list packages": "package:org.foo\n"})
    worker = ActionWorker(connection=runner, timeout=3.0)
    worker.reload_packages()
    assert worker.packages() == {"org.foo"}
    runner.responses["pm list packages"] = (
        "package:org.foo\npackage:com.newly.installed\n"
    )
    worker.reload_packages()
    assert worker.packages() == {"org.foo", "com.newly.installed"}


def test_worker_run_action_sync_path(qtapp) -> None:
    worker = ActionWorker(
        connection=_FakeRunner({"am force-stop com.heavy.app": ""}), timeout=3.0
    )
    result = worker.run_action("force_stop", "com.heavy.app")
    assert result.success
    assert result.message == "Force stopped com.heavy.app"


# ---------------------------------------------------------------------------
# MainWindow: confirmation + forwarding (no dialog automation needed)
# ---------------------------------------------------------------------------


def _select_verified(window: MainWindow, snapshot: ProcessInspectionSnapshot | None = None) -> None:
    """Give the window a verified current selection (real click prerequisite)."""
    window.processes.inspector.set_packages(PACKAGES)
    window.processes.inspector.set_snapshot(snapshot or app_snapshot())


def test_force_stop_cancel_does_not_execute(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _select_verified(window)
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda *args: emitted.append(args))
    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation",
        lambda *a, **k: False,
    )
    window._on_action_clicked("force_stop", "com.heavy.app")
    assert emitted == []
    inspector = window.processes.inspector
    assert not inspector._busy  # busy flag not set on cancel


def test_force_stop_confirm_executes(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _select_verified(window)
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda *args: emitted.append(args))
    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation",
        lambda *a, **k: True,
    )
    window._on_action_clicked("force_stop", "com.heavy.app")
    assert emitted == [("force_stop", "com.heavy.app")]
    assert window.processes.inspector._busy


def test_harmless_actions_skip_confirmation(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _select_verified(window)
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda *args: emitted.append(args))
    called = {"confirmation": False}

    def confirmation(*args, **kwargs):
        called["confirmation"] = True
        return True

    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation", confirmation
    )
    window._on_action_clicked("open_app", "com.heavy.app")
    window._on_action_clicked("app_info", "com.heavy.app")
    assert emitted == [("open_app", "com.heavy.app"), ("app_info", "com.heavy.app")]
    assert not called["confirmation"]


def test_confirmation_dialog_names_the_package(qtapp, monkeypatch) -> None:
    window = MainWindow()
    texts: list[str] = []

    def capture_builder(parent, title, text):
        texts.append(text)
        import types

        from PySide6.QtWidgets import QMessageBox

        return types.SimpleNamespace(
            text=text,
            exec=lambda: QMessageBox.StandardButton.Cancel,
        )

    monkeypatch.setattr(mw_main, "_build_confirmation", capture_builder)
    window.processes.inspector.set_packages({"com.heavy.app"})
    window.processes.inspector.set_snapshot(
        ProcessInspectionSnapshot(pid=8150, name="com.heavy.app", uid=10001, timestamp=1.0)
    )
    window._on_action_clicked("force_stop", "com.heavy.app")
    assert texts and "com.heavy.app" in texts[0]
    assert texts[0].startswith("This will stop:")


def test_on_action_result_forwards_to_panel(qtapp) -> None:
    window = MainWindow()
    window.processes.inspector.set_packages({"com.heavy.app"})
    window.processes.inspector.set_snapshot(app_snapshot())
    window.processes.inspector.set_actions_busy(True)
    result = ActionResult(
        action="force_stop",
        package_name="com.heavy.app",
        success=True,
        message="Force stopped com.heavy.app",
    )
    window.on_action_result(result)
    assert window.processes.inspector._status.text() == "Force stopped com.heavy.app"
    assert not window.processes.inspector._busy
    assert window.processes.inspector._stop_btn.isEnabled()


def test_on_packages_ready_forwards_to_panel(qtapp) -> None:
    window = MainWindow()
    window.processes.inspector.set_snapshot(app_snapshot())
    window.on_packages_ready({"com.heavy.app"})
    assert window.processes.inspector.resolved_package() == "com.heavy.app"


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


class _SignalSource(QObject):
    connection_changed = Signal(object, object)


def test_wire_actions_connects_action_path(qtapp) -> None:
    window = MainWindow()
    worker = ActionWorker(
        connection=_FakeRunner({"am force-stop com.heavy.app": ""}), timeout=3.0
    )
    received: list[ActionResult] = []
    worker.action_completed.connect(lambda r: received.append(r))
    wire_actions(window, _SignalSource(), worker)
    window.action_requested.emit("force_stop", "com.heavy.app")
    assert len(received) == 1
    assert received[0].success
    assert received[0].action == "force_stop"


def test_wire_actions_reloads_packages_on_connect(qtapp, monkeypatch) -> None:
    window = MainWindow()
    runner = _FakeRunner({"pm list packages": "package:com.heavy.app\n"})
    worker = ActionWorker(connection=runner, timeout=3.0)
    source = _SignalSource()
    wire_actions(window, source, worker)
    reloads: list = []
    original = worker.reload_packages

    def spy():
        reloads.append(1)
        return original()

    monkeypatch.setattr(worker, "reload_packages", spy)
    from android_task_manager.gui.monitor import ConnectionState

    source.connection_changed.emit(ConnectionState.CONNECTED, "ok")
    source.connection_changed.emit(ConnectionState.DISCONNECTED, "bye")
    source.connection_changed.emit(ConnectionState.CONNECTED, "ok again")
    assert len(reloads) == 2


# ---------------------------------------------------------------------------
# M12.2: selection transition — no state may leak between processes
# ---------------------------------------------------------------------------


def system_snapshot_named(name: str = "system_server") -> ProcessInspectionSnapshot:
    return ProcessInspectionSnapshot(pid=1054, name=name, uid=1000, timestamp=1.0)


def _system_snapshot() -> ProcessInspectionSnapshot:
    return system_snapshot_named()


def test_switch_from_verified_app_disables_all_actions(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    assert widget._open_btn.isEnabled()
    assert widget._info_btn.isEnabled()
    assert widget._stop_btn.isEnabled()
    widget.set_snapshot(_system_snapshot())
    assert widget.resolved_package() is None
    assert not widget._open_btn.isEnabled()
    assert not widget._info_btn.isEnabled()
    assert not widget._stop_btn.isEnabled()


def test_switch_clears_stale_result_status(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_actions_busy(True)
    widget.show_action_result(
        ActionResult(
            action="app_info",
            package_name="com.heavy.app",
            success=True,
            message="Opened App Info for com.heavy.app",
        )
    )
    assert widget._status.text() == "Opened App Info for com.heavy.app"
    widget.set_snapshot(_system_snapshot())
    assert widget._status.text() == ""
    assert widget._status.objectName() == "muted"
    assert not widget._open_btn.isEnabled()


def test_switch_after_app_info_never_targets_previous_package(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_snapshot(_system_snapshot())
    emitted: list[tuple[str, str]] = []
    widget.action_requested.connect(lambda *args: emitted.append(args))
    widget._open_btn.click()
    widget._info_btn.click()
    widget._stop_btn.click()
    assert emitted == []


def test_switch_from_system_to_app_b_resolves_b_not_a(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(_system_snapshot())
    assert widget.resolved_package() is None
    snapshot_b = ProcessInspectionSnapshot(
        pid=777, name="com.android.systemui", uid=10013, timestamp=1.0
    )
    widget.set_snapshot(snapshot_b)
    assert widget.resolved_package() == "com.android.systemui"
    assert widget._info_btn.isEnabled()


def test_stale_async_result_is_discarded_after_switching(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())  # com.heavy.app selected
    widget.set_actions_busy(True)  # app_info for com.heavy.app in flight
    # The user switches selection while the action runs...
    snapshot_b = ProcessInspectionSnapshot(
        pid=777, name="com.android.systemui", uid=10013, timestamp=1.0
    )
    widget.set_snapshot(snapshot_b)
    assert widget.resolved_package() == "com.android.systemui"
    # ...and the old result arrives afterwards.
    widget.show_action_result(
        ActionResult(
            action="app_info",
            package_name="com.heavy.app",
            success=True,
            message="Opened App Info for com.heavy.app",
        )
    )
    assert widget._status.text() == ""
    assert widget.resolved_package() == "com.android.systemui"
    assert widget._info_btn.isEnabled()


def test_stale_async_result_after_gone_is_discarded(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_actions_busy(True)
    widget.set_gone(8150)
    widget.show_action_result(
        ActionResult(
            action="force_stop",
            package_name="com.heavy.app",
            success=True,
            message="Force stopped com.heavy.app",
        )
    )
    assert widget._status.text() == ""
    assert not widget._open_btn.isEnabled()


def test_matching_result_is_still_rendered_after_reselect(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_actions_busy(True)
    widget.show_action_result(
        ActionResult(
            action="open_app",
            package_name="com.heavy.app",
            success=True,
            message="Opened com.heavy.app",
        )
    )
    assert widget._status.text() == "Opened com.heavy.app"
    assert widget._open_btn.isEnabled()


def test_empty_package_list_disables_actions_after_switch(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_packages(set())
    assert widget.resolved_package() is None
    assert not widget._open_btn.isEnabled()
    assert not widget._info_btn.isEnabled()
    assert not widget._stop_btn.isEnabled()


def test_gone_process_click_executes_nothing(qtapp) -> None:
    widget = ProcessInspectorWidget()
    widget.set_packages(PACKAGES)
    widget.set_snapshot(app_snapshot())
    widget.set_gone(8150)
    emitted: list[tuple[str, str]] = []
    widget.action_requested.connect(lambda *args: emitted.append(args))
    widget._open_btn.click()
    widget._stop_btn.click()
    assert emitted == []


def test_no_stale_confirmation_state_after_switch(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _select_verified(window)
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda *args: emitted.append(args))
    confirmed: list[str] = []

    def confirmation(parent, title, text):
        confirmed.append(text)
        return True

    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation", confirmation
    )
    window._on_action_clicked("force_stop", "com.heavy.app")
    assert emitted == [("force_stop", "com.heavy.app")]
    window.processes.inspector.set_snapshot(_system_snapshot())
    # A fresh force-stop request for the unverified system_server is rejected
    # before any dialog: no stale confirmation, no stale execution.
    window._on_action_clicked("force_stop", "com.heavy.app")
    assert emitted == [("force_stop", "com.heavy.app")]
    assert len(confirmed) == 1


# ---------------------------------------------------------------------------
# M12.2 security: stale package context must be rejected at the window
# ---------------------------------------------------------------------------


def test_old_package_context_rejected_after_selection_change(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _select_verified(window)  # com.heavy.app selected and verified
    emitted: list[tuple[str, str]] = []
    window.action_requested.connect(lambda *args: emitted.append(args))
    # The user switches to system_server...
    window.processes.inspector.set_snapshot(_system_snapshot())
    # ...then an action request arrives carrying the OLD package context.
    window._on_action_clicked("force_stop", "com.heavy.app")
    window._on_action_clicked("open_app", "com.heavy.app")
    assert emitted == []
    assert not window.processes.inspector._busy


def test_worker_never_runs_action_for_stale_package(qtapp) -> None:
    runner = _FakeRunner({"am force-stop com.heavy.app": ""})
    worker = ActionWorker(connection=runner, timeout=3.0)
    window = MainWindow()
    _select_verified(window)
    wire_actions(window, _SignalSource(), worker)
    window.processes.inspector.set_snapshot(_system_snapshot())
    results: list[ActionResult] = []
    worker.action_completed.connect(lambda r: results.append(r))
    window._on_action_clicked("force_stop", "com.heavy.app")
    assert results == []
    assert runner.calls == []


def test_main_window_with_wire_closes_cleanly(qtapp) -> None:
    window = MainWindow()
    worker = MonitorWorker(
        connection=_FakeRunner({"pm list packages": "package:com.heavy.app\n"})
    )
    actions = ActionWorker(
        connection=_FakeRunner({"pm list packages": "package:com.heavy.app\n"}), timeout=3.0
    )
    wire(window, worker)
    wire_actions(window, worker, actions)
    window.closed.emit()
    assert worker._stopped
    assert not actions.is_busy()


# ---------------------------------------------------------------------------
# Manage button: navigation into the Applications manager
# ---------------------------------------------------------------------------


def test_manage_button_available_for_verified_package(qtapp) -> None:
    window = MainWindow()
    _show_dashboard(window)
    window.processes.inspector.set_packages(PACKAGES)
    window.processes.inspector.set_snapshot(app_snapshot())
    QApplication.processEvents()
    inspector = window.processes.inspector
    assert inspector._manage_btn.isVisible()
    assert inspector._manage_btn.isEnabled()


def test_manage_button_disabled_for_unverified(qtapp) -> None:
    window = MainWindow()
    _show_dashboard(window)
    window.processes.inspector.set_packages(PACKAGES)
    window.processes.inspector.set_snapshot(system_snapshot())
    QApplication.processEvents()
    inspector = window.processes.inspector
    assert inspector._manage_btn.isVisible()
    assert not inspector._manage_btn.isEnabled()


def test_manage_button_emits_resolved_package(qtapp) -> None:
    window = MainWindow()
    _show_dashboard(window)
    window.processes.inspector.set_packages(PACKAGES)
    window.processes.inspector.set_snapshot(app_snapshot())
    QApplication.processEvents()
    managed: list[str] = []
    window.processes.inspector.manage_requested.connect(lambda p: managed.append(p))
    window.processes.inspector._manage_btn.click()
    assert managed == ["com.heavy.app"]
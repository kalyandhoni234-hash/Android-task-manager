"""GUI-level tests for the Applications manager: page, details panel,
worker, safety confirmations and navigation integration. Mirrors the
conventions of test_gui_actions.py (offscreen Qt)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from android_task_manager.action import (
    DESTRUCTIVE_ACTIONS,
    ActionErrorKind,
    ActionResult,
)
from android_task_manager.adb.exceptions import ADBDisconnectedError
from android_task_manager.applications import (
    AppCategory,
    AppDetails,
    AppInfo,
    ApplicationSnapshot,
)
from android_task_manager.gui import main_window as mw_main
from android_task_manager.gui.action_worker import ActionWorker
from android_task_manager.gui.apps_page import ApplicationsPage
from android_task_manager.gui.apps_worker import AppsWorker
from android_task_manager.gui.main_window import MainWindow, wire, wire_actions, wire_apps
from android_task_manager.gui.monitor import ConnectionState, MonitorWorker
from android_task_manager.gui.widgets.app_details_widget import AppDetailsWidget


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _snapshot(*apps: AppInfo) -> ApplicationSnapshot:
    return ApplicationSnapshot(timestamp=1.0, applications=list(apps))


def _app(package: str, category=AppCategory.USER, enabled=True) -> AppInfo:
    return AppInfo(
        package_name=package,
        apk_path=f"/data/app/{package}-1/base.apk",
        uid=10123,
        version_code=42,
        category=category,
        enabled=enabled,
    )


def _details(package: str, category=AppCategory.USER, enabled=True) -> AppDetails:
    return AppDetails(
        package_name=package,
        version_name="1.2.3",
        version_code=42,
        uid=10123,
        apk_path="/data/app/x/base.apk",
        install_location="Internal storage",
        category=category,
        enabled=enabled,
        installer="com.android.vending",
        flags=("HAS_CODE",) if category is AppCategory.USER else ("SYSTEM",),
        launchable_activity=f"{package}/.MainActivity",
        activities=(f"{package}/.MainActivity",),
        services=(),
        receivers=(),
        parse_complete=True,
    )


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


class _FakeConnection:
    """MonitorWorker stand-in connection returning canned output."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.fail: BaseException | None = None
        self.calls: list[list[str]] = []

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        return "FAKE123"

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if self.fail is not None:
            raise self.fail
        return self.responses.get(" ".join(args), "")


# ---------------------------------------------------------------------------
# AppsWorker
# ---------------------------------------------------------------------------


def test_worker_inventory_success_publishes_snapshot(qtapp) -> None:
    runner = _FakeRunner(
        {
            "pm list packages -f -U --show-versioncode": (
                "package:/data/app/com.example.app-1/base.apk=com.example.app "
                "uid=10123 versionCode:42\n"
            ),
            "pm list packages -s": "package:com.android.settings\n",
            "pm list packages -3": "package:com.example.app\n",
            "pm list packages -d": "",
        }
    )
    worker = AppsWorker(connection=runner, timeout=4.0)
    results: list = []
    failures: list[str] = []
    worker.inventory_ready.connect(lambda s: results.append(s))
    worker.inventory_failed.connect(lambda m: failures.append(m))
    worker.refresh_inventory()
    assert len(results) == 1
    assert results[0].applications[0].package_name == "com.example.app"
    assert results[0].applications[0].category is AppCategory.USER
    assert failures == []


def test_worker_inventory_failure_publishes_empty_and_message(qtapp) -> None:
    runner = _FakeRunner()
    runner.fail = ADBDisconnectedError("gone")
    worker = AppsWorker(connection=runner)
    results: list = []
    failures: list[str] = []
    worker.inventory_ready.connect(lambda s: results.append(s))
    worker.inventory_failed.connect(lambda m: failures.append(m))
    worker.refresh_inventory()
    assert len(results) == 1 and results[0].applications == []
    assert len(failures) == 1


def test_worker_drops_duplicate_inventory_refresh(qtapp) -> None:
    runner = _FakeRunner({"pm list packages -f -U --show-versioncode": ""})
    worker = AppsWorker(connection=runner)
    worker._busy = True
    results: list = []
    worker.inventory_ready.connect(lambda s: results.append(s))
    worker.refresh_inventory()
    assert results == []


def test_worker_details_success_and_failure(qtapp) -> None:
    dumpsys = (
        "Packages:\n"
        "  Package [com.example.app] (ab1):\n"
        "    userId=10123\n"
        "    versionCode=42\n"
        "    versionName=1.2.3\n"
        "    enabled=1\n"
    )
    runner = _FakeRunner({"dumpsys package com.example.app": dumpsys})
    worker = AppsWorker(connection=runner)
    ready: list = []
    failed: list = []
    worker.details_ready.connect(lambda d: ready.append(d))
    worker.details_failed.connect(lambda p, m: failed.append((p, m)))
    worker.request_details("com.example.app")
    assert len(ready) == 1 and ready[0].package_name == "com.example.app"
    worker.request_details("")
    assert len(failed) == 1 and failed[0][0] == ""


def test_worker_refreshes_on_connection(qtapp) -> None:
    runner = _FakeRunner(
        {
            "pm list packages -f -U --show-versioncode": "",
            "pm list packages -s": "",
            "pm list packages -3": "",
            "pm list packages -d": "",
        }
    )
    worker = AppsWorker(connection=runner)
    results: list = []
    worker.inventory_ready.connect(lambda s: results.append(s))
    worker.on_connection_changed(ConnectionState.CONNECTED, "ok")
    assert len(results) == 1
    worker.on_connection_changed(ConnectionState.DISCONNECTED, "gone")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# ApplicationsPage: table, filtering, selection
# ---------------------------------------------------------------------------


def test_page_empty_state(qtapp) -> None:
    page = ApplicationsPage()
    assert "Waiting for the device" in page._status.text()
    assert page._table.rowCount() == 0
    assert page._count.text() == ""


def test_page_renders_snapshot_rows(qtapp) -> None:
    page = ApplicationsPage()
    page.set_snapshot(
        _snapshot(
            _app("com.example.app"),
            _app("com.android.settings", category=AppCategory.SYSTEM),
        )
    )
    assert page._table.rowCount() == 2
    assert "2 installed" in page._count.text()
    assert page._status.text() == ""


def test_page_filtering_applies_client_side(qtapp) -> None:
    page = ApplicationsPage()
    page.set_snapshot(
        _snapshot(_app("com.example.app"), _app("org.open.source"))
    )
    page._filter.setText("example")
    assert page._table.rowCount() == 1
    assert page._table.item(0, 0).text() == "com.example.app"
    page._filter.setText("")
    assert page._table.rowCount() == 2


def test_page_selection_emits_detail_request(qtapp) -> None:
    page = ApplicationsPage()
    page.set_snapshot(_snapshot(_app("com.example.app")))
    requested: list[str] = []
    page.detail_requested.connect(lambda p: requested.append(p))
    page._select_row(0)
    assert requested == ["com.example.app"]


def test_page_select_package_in_table(qtapp) -> None:
    page = ApplicationsPage()
    page.set_snapshot(_snapshot(_app("com.example.app")))
    requested: list[str] = []
    page.detail_requested.connect(lambda p: requested.append(p))
    page.select_package("com.example.app")
    assert requested == ["com.example.app"]
    assert page._pending is None


def test_page_select_package_falls_back_to_direct_request(qtapp) -> None:
    page = ApplicationsPage()
    page.set_snapshot(_snapshot(_app("com.example.app")))
    requested: list[str] = []
    page.detail_requested.connect(lambda p: requested.append(p))
    page.select_package("com.other.app")
    assert requested == ["com.other.app"]
    assert page.details.current_package() == "com.other.app"


def test_page_clear_resets_everything(qtapp) -> None:
    page = ApplicationsPage()
    page.set_snapshot(_snapshot(_app("com.example.app")))
    page.show_details(_details("com.example.app"))
    page.clear()
    assert page._table.rowCount() == 0
    assert page._count.text() == ""
    assert page.details.current_package() is None


def test_page_inventory_failure_state(qtapp) -> None:
    page = ApplicationsPage()
    page.show_inventory_failed("device gone")
    assert "unavailable" in page._status.text().lower()


# ---------------------------------------------------------------------------
# AppDetailsWidget: rendering + capability-gated actions
# ---------------------------------------------------------------------------


def test_details_widget_user_app_offers_management(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    assert widget._open_btn.isEnabled()
    assert widget._info_btn.isEnabled()
    assert widget._stop_btn.isEnabled()
    assert widget._toggle_btn.isEnabled()
    assert widget._toggle_btn.text() == "Disable"
    assert widget._uninstall_btn.isEnabled()
    assert "SYSTEM APP" not in widget._type_badge.text()


def test_details_widget_system_app_hides_destructive_controls(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.android.settings", category=AppCategory.SYSTEM))
    assert widget._open_btn.isEnabled()
    assert widget._info_btn.isEnabled()
    assert widget._stop_btn.isEnabled()
    assert not widget._toggle_btn.isEnabled()
    assert not widget._uninstall_btn.isEnabled()
    assert "SYSTEM APP" in widget._type_badge.text()
    assert "system applications" in widget._actions_caption.text().lower()


def test_details_widget_disabled_app_offers_enable(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app", enabled=False))
    assert widget._toggle_btn.isEnabled()
    assert widget._toggle_btn.text() == "Enable"
    assert widget._uninstall_btn.isEnabled()  # user app: uninstall still offered


def test_details_widget_unknown_state_omits_toggle(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app", enabled=None))
    assert not widget._toggle_btn.isEnabled()


def test_details_widget_emits_only_allowed_actions(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    emitted: list = []
    widget.action_requested.connect(lambda a, p: emitted.append((a, p)))
    widget._on_action_clicked("uninstall")
    assert emitted == [("uninstall", "com.example.app")]
    widget.set_details(_details("com.android.settings", category=AppCategory.SYSTEM))
    widget._on_action_clicked("uninstall")
    assert len(emitted) == 1  # system app: rejected at the widget gate


def test_details_widget_busy_disables_buttons(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    widget.set_actions_busy(True)
    assert not widget._open_btn.isEnabled()
    assert not widget._uninstall_btn.isEnabled()
    widget.set_actions_busy(False)
    assert widget._open_btn.isEnabled()


def test_details_widget_action_result_stale_discard(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    widget.show_action_result(
        ActionResult("uninstall", "com.other.app", True, "Uninstalled com.other.app")
    )
    assert widget._status.text() == ""  # stale: belongs to another package


def test_details_widget_action_result_rendered(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    widget.show_action_result(
        ActionResult("uninstall", "com.example.app", True, "Uninstalled com.example.app")
    )
    assert widget._status.text() == "Uninstalled com.example.app"


def test_details_widget_failure_status_style(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    widget.show_action_result(
        ActionResult(
            "uninstall",
            "com.example.app",
            False,
            "not allowed",
            error_kind=ActionErrorKind.PERMISSION_DENIED,
        )
    )
    assert "not allowed" in widget._status.text()
    assert widget._status.objectName() == "statusWarn"


def test_details_widget_details_failed_state(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.show_loading("com.example.app")
    widget.show_details_failed("com.example.app", "not installed")
    assert "could not be read" in widget._subtitle.text()


def test_details_widget_fields_render(qtapp) -> None:
    widget = AppDetailsWidget()
    widget.set_details(_details("com.example.app"))
    assert widget._rows["version"].text() == "1.2.3"
    assert widget._rows["version_code"].text() == "42"
    assert widget._rows["uid"].text() == "10123"
    assert widget._rows["install_location"].text() == "Internal storage"
    assert widget._rows["state"].text() == "Enabled"
    assert widget._rows["launchable"].text() == "com.example.app/.MainActivity"


# ---------------------------------------------------------------------------
# MainWindow integration: routing, confirmations, navigation
# ---------------------------------------------------------------------------


def _wire_window(window: MainWindow) -> tuple[_FakeConnection, _FakeRunner, _FakeRunner]:
    monitor_connection = _FakeConnection()
    monitor = MonitorWorker(connection=monitor_connection, network_investigation_interval=0.0)
    action_runner = _FakeRunner({"pm list packages": "package:com.example.app\n"})
    actions = ActionWorker(connection=action_runner, timeout=3.0)
    apps_runner = _FakeRunner()
    apps = AppsWorker(connection=apps_runner, timeout=3.0)
    wire(window, monitor)
    wire_actions(window, monitor, actions)
    wire_apps(window, monitor, apps, actions)
    window._monitor = monitor
    window._actions = actions
    window._apps = apps
    window._monitor_connection = monitor_connection
    window._action_runner = action_runner
    window._apps_runner = apps_runner
    return monitor_connection, action_runner, apps_runner


def _show_dashboard(window: MainWindow) -> None:
    window.update_connection(ConnectionState.CONNECTED, "ok")
    QApplication.processEvents()


def test_window_manage_request_navigates_and_selects(qtapp) -> None:
    window = MainWindow()
    _wire_window(window)
    _show_dashboard(window)
    window.apps.set_snapshot(_snapshot(_app("com.example.app")))
    requested: list[str] = []
    window.apps.detail_requested.connect(lambda p: requested.append(p))
    window._on_manage_requested("com.example.app")
    assert window._pages.currentIndex() == 3
    assert window.sidebar.active_page() == "applications"
    assert requested == ["com.example.app"]


def test_window_apps_action_confirmations(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _, action_runner, _ = _wire_window(window)
    _show_dashboard(window)
    window.apps.details.set_details(_details("com.example.app"))

    confirmed: list[str] = []
    window.action_requested.connect(lambda a, p: confirmed.append(a))

    # Canceled destructive action never dispatches.
    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation",
        staticmethod(lambda *a, **k: False),
    )
    window.apps.details._on_action_clicked("uninstall")
    assert confirmed == []
    assert "pm uninstall com.example.app" not in [
        " ".join(c) for c in action_runner.calls
    ]

    # Confirmed destructive action dispatches exactly once.
    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation",
        staticmethod(lambda *a, **k: True),
    )
    window.apps.details._on_action_clicked("uninstall")
    assert confirmed == ["uninstall"]
    assert "pm uninstall com.example.app" in [" ".join(c) for c in action_runner.calls]


def test_window_system_app_action_rejected_at_window_gate(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _, action_runner, _ = _wire_window(window)
    _show_dashboard(window)
    window.apps.details.set_details(
        _details("com.android.settings", category=AppCategory.SYSTEM)
    )
    monkeypatch.setattr(
        "android_task_manager.gui.main_window._ask_confirmation",
        staticmethod(lambda *a, **k: True),
    )
    confirmed: list[str] = []
    window.action_requested.connect(lambda a, p: confirmed.append(a))
    window._on_apps_action_clicked("uninstall", "com.android.settings")
    assert confirmed == []
    assert "pm uninstall com.android.settings" not in [
        " ".join(c) for c in action_runner.calls
    ]


def test_window_force_stop_confirmation_names_package(qtapp, monkeypatch) -> None:
    window = MainWindow()
    _wire_window(window)
    _show_dashboard(window)
    window.apps.details.set_details(_details("com.example.app"))
    seen: list[str] = []

    def capture_builder(parent, title, message):
        seen.append(message)
        import types


        return types.SimpleNamespace(
            text=message,
            exec=lambda: QMessageBox.StandardButton.Cancel,
        )

    monkeypatch.setattr(mw_main, "_build_confirmation", capture_builder)
    window.apps.details._on_action_clicked("force_stop")
    assert seen and "com.example.app" in seen[0]


def test_window_action_result_routes_to_apps_and_refreshes(qtapp) -> None:
    window = MainWindow()
    _, _, apps_runner = _wire_window(window)
    _show_dashboard(window)
    window.apps.details.set_details(_details("com.example.app"))
    window.on_action_result(
        ActionResult("disable", "com.example.app", True, "Disabled com.example.app")
    )
    # A successful toggle triggers an inventory refresh AND a detail re-read
    # (the panel ends up showing the freshly re-read details record).
    assert "pm list packages -f -U --show-versioncode" in [
        " ".join(c) for c in apps_runner.calls
    ]
    assert "dumpsys package com.example.app" in [" ".join(c) for c in apps_runner.calls]
    assert window.apps.details.current_package() == "com.example.app"


def test_window_disconnect_clears_apps_page(qtapp) -> None:
    window = MainWindow()
    _wire_window(window)
    _show_dashboard(window)
    window.apps.set_snapshot(_snapshot(_app("com.example.app")))
    window.apps.details.set_details(_details("com.example.app"))
    window.update_connection(ConnectionState.DISCONNECTED, "gone")
    assert window.apps._table.rowCount() == 0
    assert window.apps.details.current_package() is None


def test_window_inventory_handlers_update_page(qtapp) -> None:
    window = MainWindow()
    _wire_window(window)
    _show_dashboard(window)
    window.on_apps_inventory_ready(_snapshot(_app("com.example.app")))
    assert window.apps._table.rowCount() == 1
    window.on_apps_details_ready(_details("com.example.app"))
    assert window.apps.details.current_package() == "com.example.app"
    window.on_apps_inventory_failed("device gone")
    assert "unavailable" in window.apps._status.text().lower()


def test_destructive_actions_are_force_stop_disable_uninstall() -> None:
    assert set(DESTRUCTIVE_ACTIONS) == {"force_stop", "disable", "uninstall"}


class _SignalSource(QObject):
    connection_changed = Signal(object, object)


def test_wire_apps_connects_refresh_and_details_paths(qtapp) -> None:
    window = MainWindow()
    runner = _FakeRunner()
    apps = AppsWorker(connection=runner, timeout=3.0)
    source = _SignalSource()
    wire_apps(window, source, apps, _NoopActions())
    refreshed: list = []
    apps.inventory_ready.connect(lambda s: refreshed.append(s))
    window.apps_refresh_requested.emit()
    assert len(refreshed) == 1
    details: list = []
    apps.details_ready.connect(lambda d: details.append(d))
    window.apps_detail_requested.emit("com.example.app")
    # Empty dumpsys still yields a typed (unparseable) record, never a crash.
    assert len(details) == 1 and details[0].parse_complete is False


class _NoopActions(QObject):
    def reload_packages(self) -> None:
        pass
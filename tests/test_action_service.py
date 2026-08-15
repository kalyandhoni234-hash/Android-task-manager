"""ActionService tests: command shapes, typing, timeouts, security."""

import re

import pytest

from android_task_manager.action import ActionError, ActionErrorKind
from android_task_manager.action.service import (
    APP_DETAILS_SETTINGS,
    LAUNCHER_CATEGORY,
    MAIN_ACTION,
    ActionService,
)
from android_task_manager.adb.exceptions import (
    ADBCommandError,
    ADBDisconnectedError,
    ADBNotFoundError,
    ADBNoDeviceError,
    ADBTimeoutError,
    ADBUnauthorizedError,
)

LAUNCHER = "com.example.app/.MainActivity"


class _FakeRunner:
    """Records argument lists and timeout kwargs like CommandRunner.shell."""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        fails: dict[str, BaseException] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.fails = fails or {}
        self.calls: list[list[str]] = []
        self.timeouts: list[float | None] = []

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        self.timeouts.append(timeout)
        key = " ".join(args)
        if key in self.fails:
            raise self.fails[key]
        return self.responses.get(key, "")


def _resolve_args(package: str) -> list[str]:
    return [
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-c",
        LAUNCHER_CATEGORY,
        "-a",
        MAIN_ACTION,
        package,
    ]


def _am_start_args(component: str) -> list[str]:
    return ["am", "start", "-W", "-n", component]


def _resolve_key(package: str) -> str:
    return " ".join(_resolve_args(package))


def _am_start_key(component: str) -> str:
    return " ".join(_am_start_args(component))


# ---------------------------------------------------------------------------
# Open App
# ---------------------------------------------------------------------------


def test_open_app_resolves_and_launches() -> None:
    runner = _FakeRunner(
        {_resolve_key("com.example.app"): f"{LAUNCHER}\n", _am_start_key(LAUNCHER): "Status: ok\n"}
    )
    service = ActionService(runner, timeout=5.0)
    result = service.run("open_app", "com.example.app")
    assert result.success
    assert result.action == "open_app"
    assert result.package_name == "com.example.app"
    assert result.message == "Opened com.example.app"
    assert runner.calls == [_resolve_args("com.example.app"), _am_start_args(LAUNCHER)]
    assert runner.timeouts == [5.0, 5.0]


def test_open_app_with_no_launchable_activity_fails_typed() -> None:
    runner = _FakeRunner({_resolve_key("com.example.app"): ""})
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("open_app", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.NOT_LAUNCHABLE
    assert "no launchable activity" in excinfo.value.message
    assert len(runner.calls) == 1  # am start was never reached


def test_open_app_garbage_component_output_rejected() -> None:
    runner = _FakeRunner({_resolve_key("com.example.app"): "garbage output here"})
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("open_app", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.NOT_LAUNCHABLE
    assert len(runner.calls) == 1


def test_open_app_am_start_error_type_3() -> None:
    runner = _FakeRunner(
        {
            _resolve_key("com.example.app"): f"{LAUNCHER}\n",
            _am_start_key(LAUNCHER): "Error type 3\nError: Activity class does not exist.\n",
        }
    )
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("open_app", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.COMMAND_FAILED
    assert "could not be launched" in excinfo.value.message


def test_open_app_validates_package_before_any_adb_call() -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("open_app", "com.example; rm -rf /")
    assert excinfo.value.kind is ActionErrorKind.INVALID_PACKAGE
    assert runner.calls == []


# ---------------------------------------------------------------------------
# App Info
# ---------------------------------------------------------------------------


def test_app_info_opens_settings_page() -> None:
    runner = _FakeRunner(
        {"am start -a " + APP_DETAILS_SETTINGS + " -d package:com.example.app": "Starting: Intent\n"}
    )
    service = ActionService(runner)
    result = service.run("app_info", "com.example.app")
    assert result.success
    assert result.action == "app_info"
    assert result.message == "Opened App Info for com.example.app"
    assert runner.calls == [
        ["am", "start", "-a", APP_DETAILS_SETTINGS, "-d", "package:com.example.app"]
    ]


def test_app_info_rejects_invalid_package_without_adb() -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("app_info", "com.example && reboot")
    assert excinfo.value.kind is ActionErrorKind.INVALID_PACKAGE
    assert runner.calls == []


def test_app_info_failure_surfaces_typed_error() -> None:
    runner = _FakeRunner(
        {"am start -a " + APP_DETAILS_SETTINGS + " -d package:com.example.app": "Error type 3\n"}
    )
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("app_info", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.COMMAND_FAILED
    assert "App Info could not be opened" in excinfo.value.message


# ---------------------------------------------------------------------------
# Force Stop
# ---------------------------------------------------------------------------


def test_force_stop_uses_package_level_command_not_pid_kill() -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    result = service.run("force_stop", "com.example.app")
    assert result.success
    assert result.action == "force_stop"
    assert result.message == "Force stopped com.example.app"
    # The single addressed identity is the validated PACKAGE, not a PID.
    assert runner.calls == [["am", "force-stop", "com.example.app"]]


def test_force_stop_never_emits_kill() -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    service.run("force_stop", "com.example.app")
    assert all("kill" not in arg for args in runner.calls for arg in args)


def test_force_stop_unknown_package_is_not_found() -> None:
    runner = _FakeRunner(
        fails={
            "am force-stop com.gone.app": ADBCommandError(
                "am force-stop com.gone.app",
                1,
                stderr="Error: Unknown package: com.gone.app",
            )
        }
    )
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("force_stop", "com.gone.app")
    assert excinfo.value.kind is ActionErrorKind.NOT_FOUND
    assert "not found on the device" in excinfo.value.message


def test_force_stop_rejects_invalid_package() -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("force_stop", "com.example..app")
    assert excinfo.value.kind is ActionErrorKind.INVALID_PACKAGE
    assert runner.calls == []


# ---------------------------------------------------------------------------
# Dispatch + typed error translation
# ---------------------------------------------------------------------------


def test_run_rejects_unknown_action() -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("delete_everything", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.INVALID_PACKAGE
    assert runner.calls == []


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ADBTimeoutError("am start -W", 10.0), ActionErrorKind.TIMEOUT),
        (ADBDisconnectedError("gone"), ActionErrorKind.DISCONNECTED),
        (ADBUnauthorizedError("ZP4X"), ActionErrorKind.UNAUTHORIZED),
        (ADBNoDeviceError(), ActionErrorKind.NO_DEVICE),
        (ADBNotFoundError(), ActionErrorKind.ADB_MISSING),
        (ADBCommandError("am start -W", 1, stderr="boom"), ActionErrorKind.COMMAND_FAILED),
    ],
)
def test_open_app_translates_typed_adb_errors(exc: BaseException, kind: ActionErrorKind) -> None:
    runner = _FakeRunner(fails={_resolve_key("com.example.app"): exc})
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("open_app", "com.example.app")
    assert excinfo.value.kind is kind
    assert isinstance(excinfo.value.__cause__, type(exc))


def test_disconnected_message_is_user_friendly() -> None:
    runner = _FakeRunner(
        fails={"am force-stop com.example.app": ADBDisconnectedError("gone")}
    )
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("force_stop", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.DISCONNECTED
    assert "Reconnect your Android device and try again" in excinfo.value.message


def test_timeout_has_no_traceback_y_no_machine_detail() -> None:
    runner = _FakeRunner(
        fails={"am force-stop com.example.app": ADBTimeoutError("am force-stop", 10.0)}
    )
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run("force_stop", "com.example.app")
    assert excinfo.value.kind is ActionErrorKind.TIMEOUT
    assert "traceback" not in excinfo.value.message.lower()


def test_timeout_passed_to_every_call() -> None:
    runner = _FakeRunner(
        {_resolve_key("com.example.app"): f"{LAUNCHER}\n", _am_start_key(LAUNCHER): "ok"}
    )
    service = ActionService(runner, timeout=3.5)
    service.run("open_app", "com.example.app")
    assert runner.timeouts == [3.5, 3.5]


# ---------------------------------------------------------------------------
# Package list
# ---------------------------------------------------------------------------


def test_list_packages_returns_validated_set() -> None:
    runner = _FakeRunner(
        {"pm list packages": "package:com.example.app\npackage:org.foo\njunk\npackage:bad name\n"}
    )
    service = ActionService(runner, timeout=7.0)
    assert service.list_packages() == {"com.example.app", "org.foo"}
    assert runner.calls == [["pm", "list", "packages"]]
    assert runner.timeouts == [7.0]


def test_list_packages_translates_adb_failure() -> None:
    runner = _FakeRunner(fails={"pm list packages": ADBDisconnectedError("x")})
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.list_packages()
    assert excinfo.value.kind is ActionErrorKind.DISCONNECTED


# ---------------------------------------------------------------------------
# Security regression: no injected command can reach ADB
# ---------------------------------------------------------------------------

INJECTIONS = [
    "com.example; rm -rf /",
    "com.example && reboot",
    "com.example | sh -c id",
    "com.example`id`",
    "$(id)",
    "com.example$(cat /etc/passwd)",
    "com.example &",
    "com.example\nreboot",
    "com.example\rreboot",
    "../com.example",
    "-a android.settings -d package:",
    "com.example -d",
    "com.example --user 0",
    "com.example/app_process",
]


@pytest.mark.parametrize("payload", INJECTIONS)
@pytest.mark.parametrize("action", ["open_app", "app_info", "force_stop"])
def test_injection_payloads_never_reach_adb(payload: str, action: str) -> None:
    runner = _FakeRunner()
    service = ActionService(runner)
    with pytest.raises(ActionError) as excinfo:
        service.run(action, payload)
    assert excinfo.value.kind is ActionErrorKind.INVALID_PACKAGE
    assert runner.calls == []


def test_service_never_passes_unvalidated_input_to_adb() -> None:
    runner = _FakeRunner(
        {_resolve_key("com.example.app"): f"{LAUNCHER}\n", _am_start_key(LAUNCHER): "ok"}
    )
    service = ActionService(runner, timeout=2.0)
    service.run("open_app", "com.example.app")
    # Every single argument that reaches the runner is either a fixed
    # framework token or a strictly validated identifier.
    allowed = re.compile(r"^[A-Za-z0-9_.:/+-]+$")
    for args in runner.calls:
        for arg in args:
            assert allowed.fullmatch(arg), f"unexpected raw argument: {arg!r}"


def test_resolved_component_is_never_fabricated() -> None:
    # The component passed to `am start` must come from ADB's own output,
    # never from the caller-supplied package string.
    runner = _FakeRunner(
        {_resolve_key("com.example.app"): "com.other.thing/.Activity\n", _am_start_key("com.other.thing/.Activity"): "ok"}
    )
    service = ActionService(runner)
    result = service.run("open_app", "com.example.app")
    assert result.success
    assert runner.calls[1] == ["am", "start", "-W", "-n", "com.other.thing/.Activity"]
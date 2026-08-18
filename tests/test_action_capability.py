"""Capability gate tests: system-app protection and target validation."""

import pytest

from android_task_manager.action.capability import (
    APP_INFO,
    DISABLE,
    ENABLE,
    FORCE_STOP,
    LAUNCH,
    UNINSTALL,
    supported_actions,
    validate_action,
)
from android_task_manager.action.models import ActionError, ActionErrorKind

_ALWAYS = (LAUNCH, APP_INFO, FORCE_STOP)


def test_user_app_supports_full_management() -> None:
    assert supported_actions(is_system=False, enabled=True) == _ALWAYS + (
        DISABLE,
        UNINSTALL,
    )


def test_disabled_user_app_can_be_enabled() -> None:
    assert supported_actions(is_system=False, enabled=False) == _ALWAYS + (
        ENABLE,
        UNINSTALL,
    )


def test_unknown_enabled_state_offers_neither_toggle() -> None:
    assert supported_actions(is_system=False, enabled=None) == _ALWAYS + (UNINSTALL,)


def test_system_app_never_offers_destructive_controls() -> None:
    assert supported_actions(is_system=True, enabled=True) == _ALWAYS
    assert supported_actions(is_system=True, enabled=False) == _ALWAYS


def test_validate_action_accepts_permitted_actions() -> None:
    validate_action(LAUNCH, is_system=False, enabled=True)
    validate_action(FORCE_STOP, is_system=True, enabled=True)
    validate_action(UNINSTALL, is_system=False, enabled=True)


def test_validate_action_rejects_unknown_action() -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_action("delete_everything", is_system=False, enabled=True)
    assert excinfo.value.kind is ActionErrorKind.INVALID_TARGET


def test_validate_action_rejects_uninstall_of_system_app() -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_action(UNINSTALL, is_system=True, enabled=True)
    assert excinfo.value.kind is ActionErrorKind.NOT_SUPPORTED
    assert "system applications" in excinfo.value.message


def test_validate_action_rejects_disable_of_system_app() -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_action(DISABLE, is_system=True, enabled=True)
    assert excinfo.value.kind is ActionErrorKind.NOT_SUPPORTED


def test_validate_action_rejects_toggle_with_unknown_state() -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_action(DISABLE, is_system=False, enabled=None)
    assert excinfo.value.kind is ActionErrorKind.NOT_SUPPORTED


def test_destructive_actions_are_declared() -> None:
    from android_task_manager.action import DESTRUCTIVE_ACTIONS

    assert set(DESTRUCTIVE_ACTIONS) == {FORCE_STOP, DISABLE, UNINSTALL}
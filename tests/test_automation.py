"""Tests for the safe automation engine (Phase F).

Covers the approval gate, the never-auto-destructive invariant (defense
in depth even after approval), target validation, cooldowns, loop
protection, session scoping, deterministic behavior and executor failure
handling.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from android_task_manager.action.models import ActionResult
from android_task_manager.automation import AutomationEngine, AutomationStatus
from android_task_manager.recommend.models import Recommendation


@dataclass(frozen=True)
class _FakeExecutor:
    """Records calls; can be programmed to succeed or fail."""

    calls: list[tuple[str, str]] | None = None
    fail: bool = False
    message: str = "ok"

    def __call__(self, action: str, target: str) -> ActionResult:
        if self.calls is not None:
            self.calls.append((action, target))
        if self.fail:
            return ActionResult(
                action=action,
                package_name=target,
                success=False,
                message="device refused",
            )
        return ActionResult(
            action=action,
            package_name=target,
            success=True,
            message=f"{action} {target} done",
        )


def _recommendation(
    *,
    automation_allowed: bool = True,
    action: str = "enable",
    target: str = "com.example.app",
    destructive: bool = False,
    recommendation_id: str = "REC-001",
) -> Recommendation:
    return Recommendation(
        recommendation_id=recommendation_id,
        finding_ref="finding",
        title="t",
        rationale="r",
        severity="warning",
        action=action,
        target=target,
        destructive=destructive,
        automation_allowed=automation_allowed,
    )


# ---------------------------------------------------------------------------
# Submission gate
# ---------------------------------------------------------------------------


def test_submit_creates_waiting_approval_task() -> None:
    engine = AutomationEngine()
    task = engine.submit(_recommendation(), now=10.0)
    assert task.task_id == "A-001"
    assert task.status is AutomationStatus.WAITING_APPROVAL
    assert task.action == "enable"
    assert task.target == "com.example.app"
    assert task.requested_at == 10.0
    assert task.approved_at is None


def test_submit_rejects_missing_target() -> None:
    engine = AutomationEngine()
    task = engine.submit(
        _recommendation(action=None, target=None, automation_allowed=False),
        now=10.0,
    )
    assert task.status is AutomationStatus.FAILED
    assert "no actionable target" in task.message


def test_submit_rejects_not_automation_eligible() -> None:
    engine = AutomationEngine()
    task = engine.submit(
        _recommendation(automation_allowed=False, destructive=True),
        now=10.0,
    )
    assert task.status is AutomationStatus.FAILED
    assert "not automation-eligible" in task.message


def test_submit_rejects_invalid_package_target() -> None:
    engine = AutomationEngine()
    task = engine.submit(_recommendation(target="com;rm -rf /"), now=10.0)
    assert task.status is AutomationStatus.FAILED
    assert "Invalid target" in task.message


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


def test_execute_without_approval_is_blocked() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls))
    task = engine.submit(_recommendation(), now=10.0)
    task = engine.execute(task.task_id, now=20.0)
    assert task.status is AutomationStatus.BLOCKED
    assert "approval" in task.message
    assert calls == []


def test_approve_then_execute_succeeds() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls))
    task = engine.submit(_recommendation(), now=10.0)
    approved = engine.approve(task.task_id, now=15.0)
    assert approved.approved_at == 15.0
    executed = engine.execute(task.task_id, now=20.0)
    assert executed.status is AutomationStatus.SUCCEEDED
    assert executed.executed_at == 20.0
    assert executed.message == "enable com.example.app done"
    assert calls == [("enable", "com.example.app")]


def test_approve_unknown_task_returns_none() -> None:
    engine = AutomationEngine()
    assert engine.approve("A-999", now=10.0) is None
    assert engine.execute("A-999", now=10.0) is None


def test_execute_without_executor_fails() -> None:
    engine = AutomationEngine()  # no executor configured
    task = engine.submit(_recommendation(), now=10.0)
    engine.approve(task.task_id, now=15.0)
    executed = engine.execute(task.task_id, now=20.0)
    assert executed.status is AutomationStatus.FAILED
    assert "No action executor" in executed.message


# ---------------------------------------------------------------------------
# No auto-destructive (defense in depth)
# ---------------------------------------------------------------------------


def test_destructive_task_blocked_even_after_approval() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls))
    task = engine.submit(
        _recommendation(
            action="force_stop",
            automation_allowed=False,  # destructive never eligible
            destructive=True,
        ),
        now=10.0,
    )
    assert task.status is AutomationStatus.FAILED  # rejected at the gate
    assert calls == []


def test_destructive_approved_task_never_executes() -> None:
    # Defense in depth: even a caller that approved a destructive task
    # (e.g. via a legacy path) can never make the engine run it.
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls))
    task = engine.submit(
        _recommendation(
            action="force_stop",
            automation_allowed=True,  # forced by a broken caller
            destructive=True,
        ),
        now=10.0,
    )
    assert task.status is AutomationStatus.WAITING_APPROVAL  # gate missed it
    engine.approve(task.task_id, now=15.0)
    executed = engine.execute(task.task_id, now=20.0)
    assert executed.status is AutomationStatus.BLOCKED
    assert "never run through automation" in executed.message
    assert calls == []


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


def test_cooldown_blocks_immediate_repeat() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls), cooldown=60.0)
    first = engine.submit(_recommendation(recommendation_id="REC-001"), now=10.0)
    engine.approve(first.task_id, now=15.0)
    assert engine.execute(first.task_id, now=20.0).status is AutomationStatus.SUCCEEDED

    second = engine.submit(_recommendation(recommendation_id="REC-002"), now=30.0)
    engine.approve(second.task_id, now=35.0)
    blocked = engine.execute(second.task_id, now=40.0)
    assert blocked.status is AutomationStatus.BLOCKED
    assert "Cooldown" in blocked.message
    assert len(calls) == 1


def test_same_target_different_action_has_own_cooldown() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls), cooldown=60.0)
    first = engine.submit(_recommendation(action="enable"), now=10.0)
    engine.approve(first.task_id, now=15.0)
    engine.execute(first.task_id, now=20.0)
    second = engine.submit(_recommendation(action="open_app"), now=30.0)
    engine.approve(second.task_id, now=35.0)
    executed = engine.execute(second.task_id, now=40.0)
    assert executed.status is AutomationStatus.SUCCEEDED
    assert len(calls) == 2


def test_fires_again_after_cooldown_elapsed() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls), cooldown=60.0)
    first = engine.submit(_recommendation(recommendation_id="REC-001"), now=10.0)
    engine.approve(first.task_id, now=15.0)
    engine.execute(first.task_id, now=20.0)
    second = engine.submit(_recommendation(recommendation_id="REC-002"), now=80.0)
    engine.approve(second.task_id, now=85.0)
    executed = engine.execute(second.task_id, now=90.0)
    assert executed.status is AutomationStatus.SUCCEEDED
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Loop protection
# ---------------------------------------------------------------------------


def test_loop_protection_budget_blocks_repeats() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(
        executor=_FakeExecutor(calls), cooldown=0.0, max_executions_per_target=2
    )
    for index in range(3):
        task = engine.submit(
            _recommendation(recommendation_id=f"REC-{index:03d}"), now=float(index)
        )
        engine.approve(task.task_id, now=float(index) + 1)
        result = engine.execute(task.task_id, now=float(index) + 2)
        if index < 2:
            assert result.status is AutomationStatus.SUCCEEDED
        else:
            assert result.status is AutomationStatus.BLOCKED
            assert "Loop protection" in result.message
    assert len(calls) == 2


def test_loop_protection_state_resets_on_new_session() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(
        executor=_FakeExecutor(calls), cooldown=0.0, max_executions_per_target=1
    )
    task = engine.submit(_recommendation(), now=10.0)
    engine.approve(task.task_id, now=15.0)
    assert engine.execute(task.task_id, now=20.0).status is AutomationStatus.SUCCEEDED
    engine.begin_session()
    # Fresh session: stale tasks are gone (bounded memory), ids restart, and
    # the execution budget resets so the same pair may run again.
    assert engine.tasks == ()
    task = engine.submit(_recommendation(), now=30.0)
    assert task.task_id == "A-001"
    engine.approve(task.task_id, now=35.0)
    assert engine.execute(task.task_id, now=40.0).status is AutomationStatus.SUCCEEDED


def test_task_list_cannot_grow_unbounded_across_sessions() -> None:
    engine = AutomationEngine()
    for _ in range(5):
        engine.begin_session()
        engine.submit(_recommendation(), now=10.0)
    # Only the current session's tasks remain.
    assert len(engine.tasks) == 1


def test_invalid_engine_parameters_rejected() -> None:
    with pytest.raises(ValueError):
        AutomationEngine(cooldown=-1.0)
    with pytest.raises(ValueError):
        AutomationEngine(max_executions_per_target=0)


# ---------------------------------------------------------------------------
# Executor failure handling
# ---------------------------------------------------------------------------


def test_executor_failure_marks_task_failed() -> None:
    engine = AutomationEngine(executor=_FakeExecutor(fail=True))
    task = engine.submit(_recommendation(), now=10.0)
    engine.approve(task.task_id, now=15.0)
    executed = engine.execute(task.task_id, now=20.0)
    assert executed.status is AutomationStatus.FAILED
    assert executed.message == "device refused"


def test_executor_exception_marks_task_failed() -> None:
    def boom(action: str, target: str) -> ActionResult:
        raise RuntimeError("adb crashed")

    engine = AutomationEngine(executor=boom)
    task = engine.submit(_recommendation(), now=10.0)
    engine.approve(task.task_id, now=15.0)
    executed = engine.execute(task.task_id, now=20.0)
    assert executed.status is AutomationStatus.FAILED
    assert "adb crashed" in executed.message


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_tasks_in_submission_order() -> None:
    engine = AutomationEngine()
    engine.submit(_recommendation(recommendation_id="REC-001"), now=10.0)
    engine.submit(_recommendation(recommendation_id="REC-002"), now=20.0)
    assert [t.recommendation_id for t in engine.tasks] == ["REC-001", "REC-002"]


def test_clear_resets_tasks_and_state() -> None:
    calls: list[tuple[str, str]] = []
    engine = AutomationEngine(executor=_FakeExecutor(calls), cooldown=0.0)
    task = engine.submit(_recommendation(), now=10.0)
    engine.approve(task.task_id, now=15.0)
    engine.execute(task.task_id, now=20.0)
    engine.clear()
    assert engine.tasks == ()
    task = engine.submit(_recommendation(recommendation_id="REC-002"), now=30.0)
    assert task.task_id == "A-001"
    engine.approve(task.task_id, now=35.0)
    assert engine.execute(task.task_id, now=40.0).status is AutomationStatus.SUCCEEDED

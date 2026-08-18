"""Automation engine — approved, cooldown-bounded, loop-protected actions.

Pure and GUI-independent: the engine decides *whether* a recommendation
may run; the actual execution is injected (the GUI wires
:class:`~android_task_manager.action.service.ActionService.run`). Tests
inject a fake executor.

Guarantees:

* **Approval gate** — a task stays WAITING_APPROVAL until explicitly
  approved; nothing runs unapproved.
* **No auto-destructive** — destructive actions are never executed, even
  after approval (and the recommendation engine already marks them
  automation-ineligible).
* **Target validation** — every target is validated with the v0.7 package
  validator before anything is scheduled; invalid targets fail closed.
* **Cooldowns** — after a run, the same (action, target) cannot run again
  until the cooldown elapsed.
* **Loop protection** — a per-session execution budget per target: a
  restart-crash-restart cycle cannot spin forever.
* **Session scoping** — cooldown and budget state reset on a new session.
* **Deterministic** — pure function of state and the explicit ``now``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..action.capability import DESTRUCTIVE_ACTIONS
from ..action.models import ActionResult
from ..action.package import validate_package_name
from ..recommend.models import Recommendation
from .models import AutomationStatus, AutomationTask

#: Default minimum time between two executions of the same (action,
#: target) pair, in monotonic seconds.
DEFAULT_ACTION_COOLDOWN_SECONDS = 300.0

#: Default per-session execution budget per (action, target) — loop
#: protection: a process that keeps misbehaving after being acted on must
#: not be acted on forever.
DEFAULT_MAX_EXECUTIONS_PER_TARGET = 3


@dataclass(frozen=True)
class _TargetState:
    """Per-target automation state within one session."""

    last_run_at: float | None = None
    executions: int = 0


class AutomationEngine:
    """Schedules and executes approved recommendations safely."""

    def __init__(
        self,
        executor: Callable[[str, str], ActionResult] | None = None,
        cooldown: float = DEFAULT_ACTION_COOLDOWN_SECONDS,
        max_executions_per_target: int = DEFAULT_MAX_EXECUTIONS_PER_TARGET,
    ) -> None:
        if cooldown < 0:
            raise ValueError("cooldown must be >= 0")
        if max_executions_per_target < 1:
            raise ValueError("max_executions_per_target must be >= 1")
        self._executor = executor
        self._cooldown = cooldown
        self._max_executions = max_executions_per_target
        self._tasks: dict[str, AutomationTask] = {}
        self._next_id = 1
        self._targets: dict[tuple[str, str], _TargetState] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def begin_session(self) -> None:
        """Reset cooldowns, execution budgets and the task list.

        A new device session starts from a clean slate: previous sessions'
        tasks are gone (bounded memory — the task list cannot grow forever),
        and every (action, target) pair may be acted on again under the
        session budget.
        """
        self._tasks = {}
        self._next_id = 1
        self._targets = {}

    def clear(self) -> None:
        """Drop every task and reset all state."""
        self._tasks = {}
        self._next_id = 1
        self._targets = {}

    def set_executor(
        self, executor: Callable[[str, str], ActionResult] | None
    ) -> None:
        """Wire (or detach) the action executor used by :meth:`execute`.

        The engine is pure by default — the GUI injects a callable that
        reuses the v0.7 action layer, while tests inject fakes. May be
        called again to replace a stale executor after a reconnect.
        """
        self._executor = executor

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def submit(self, recommendation: Recommendation, now: float) -> AutomationTask:
        """Create a task from *recommendation*, or a FAILED task when the
        recommendation is not automation-eligible.

        Eligibility: an action exists, the target is a valid package name,
        and the recommendation is explicitly automation-allowed (never
        true for destructive recommendations).
        """
        task_id = f"A-{self._next_id:03d}"
        self._next_id += 1
        if recommendation.action is None or recommendation.target is None:
            return self._record(
                AutomationTask(
                    task_id=task_id,
                    recommendation_id=recommendation.recommendation_id,
                    action="",
                    target="",
                    destructive=recommendation.destructive,
                    requested_at=now,
                    status=AutomationStatus.FAILED,
                    message="The recommendation carries no actionable target.",
                )
            )
        if not recommendation.automation_allowed:
            return self._record(
                AutomationTask(
                    task_id=task_id,
                    recommendation_id=recommendation.recommendation_id,
                    action=recommendation.action,
                    target=recommendation.target,
                    destructive=recommendation.destructive,
                    requested_at=now,
                    status=AutomationStatus.FAILED,
                    message=(
                        "The recommendation is not automation-eligible "
                        "(destructive actions never run through automation)."
                    ),
                )
            )
        try:
            validate_package_name(recommendation.target)
        except ValueError as exc:
            return self._record(
                AutomationTask(
                    task_id=task_id,
                    recommendation_id=recommendation.recommendation_id,
                    action=recommendation.action,
                    target=recommendation.target,
                    destructive=recommendation.destructive,
                    requested_at=now,
                    status=AutomationStatus.FAILED,
                    message=f"Invalid target: {exc}",
                )
            )
        return self._record(
            AutomationTask(
                task_id=task_id,
                recommendation_id=recommendation.recommendation_id,
                action=recommendation.action,
                target=recommendation.target,
                destructive=recommendation.destructive,
                requested_at=now,
            )
        )

    def approve(self, task_id: str, now: float) -> AutomationTask | None:
        """Approve *task_id* for execution (idempotent; unknown ids -> None).

        Approval gates timing only: a destructive task is still refused at
        execution time.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status is AutomationStatus.WAITING_APPROVAL:
            task = AutomationTask(
                task_id=task.task_id,
                recommendation_id=task.recommendation_id,
                action=task.action,
                target=task.target,
                destructive=task.destructive,
                requested_at=task.requested_at,
                status=AutomationStatus.WAITING_APPROVAL,
                approved_at=now,
            )
            self._tasks[task_id] = task
        return task

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def gate(self, task_id: str, now: float) -> AutomationTask | None:
        """Validate that *task_id* may execute, without executing it.

        Runs exactly the same checks as :meth:`execute` (approval,
        destructive, cooldown, loop protection, executor availability)
        but never calls the executor. On success the task is returned
        unchanged (still WAITING_APPROVAL); on failure the task status
        becomes BLOCKED/FAILED with the reason. Used by GUI flows that
        execute the action through an asynchronous worker.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status is not AutomationStatus.WAITING_APPROVAL:
            return task
        if task.approved_at is None:
            return self._update(
                task,
                AutomationStatus.BLOCKED,
                message="Execution requires explicit approval.",
            )
        if task.action in DESTRUCTIVE_ACTIONS:
            return self._update(
                task,
                AutomationStatus.BLOCKED,
                message=(
                    "Destructive actions never run through automation; "
                    "execute this one manually from the application page."
                ),
            )
        if self._executor is None:
            return self._update(
                task,
                AutomationStatus.FAILED,
                message="No action executor is configured.",
            )
        refusal = self._gate_refusal(task, now)
        if refusal is not None:
            return refusal
        return task

    def record_result(
        self, task_id: str, success: bool, now: float, message: str = ""
    ) -> AutomationTask | None:
        """Record the outcome of an externally executed task.

        The GUI runs approved actions through its asynchronous action
        worker; this applies the same bookkeeping :meth:`execute` would
        (target cooldown, loop-protection budget, task status) after the
        worker reported the typed result.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if success:
            state = self._targets.get((task.action, task.target))
            executions = state.executions if state is not None else 0
            self._targets[(task.action, task.target)] = _TargetState(
                last_run_at=now, executions=executions + 1
            )
            return self._update(
                task,
                AutomationStatus.SUCCEEDED,
                message=message,
                executed_at=now,
            )
        return self._update(
            task,
            AutomationStatus.FAILED,
            message=message or "The action failed on the device.",
            executed_at=now,
        )

    def _gate_refusal(self, task: AutomationTask, now: float) -> AutomationTask | None:
        """The gate checks shared by :meth:`gate` and :meth:`execute`."""
        state = self._targets.get((task.action, task.target))
        if state is not None and state.last_run_at is not None:
            if now - state.last_run_at < self._cooldown:
                remaining = self._cooldown - (now - state.last_run_at)
                return self._update(
                    task,
                    AutomationStatus.BLOCKED,
                    message=f"Cooldown active for {task.action} {task.target} "
                    f"({remaining:.0f} s remaining).",
                )
        executions = state.executions if state is not None else 0
        if executions >= self._max_executions:
            return self._update(
                task,
                AutomationStatus.BLOCKED,
                message=(
                    f"Loop protection: {task.action} {task.target} was "
                    f"already executed {executions} times this session."
                ),
            )
        return None

    def execute(self, task_id: str, now: float) -> AutomationTask | None:
        """Execute *task_id* when approved and safe; return the task.

        Refusals (no approval, destructive, cooldown, loop protection)
        are reported through the task status — nothing is silently
        dropped and nothing runs partially.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.status is not AutomationStatus.WAITING_APPROVAL:
            return task
        if task.approved_at is None:
            return self._update(
                task,
                AutomationStatus.BLOCKED,
                message="Execution requires explicit approval.",
            )
        if task.action in DESTRUCTIVE_ACTIONS:
            return self._update(
                task,
                AutomationStatus.BLOCKED,
                message=(
                    "Destructive actions never run through automation; "
                    "execute this one manually from the application page."
                ),
            )
        if self._executor is None:
            return self._update(
                task,
                AutomationStatus.FAILED,
                message="No action executor is configured.",
            )
        refusal = self._gate_refusal(task, now)
        if refusal is not None:
            return refusal
        self._update(task, AutomationStatus.RUNNING)
        try:
            result = self._executor(task.action, task.target)
        except Exception as exc:  # noqa: BLE001 — executor failures are task failures
            return self._update(
                task,
                AutomationStatus.FAILED,
                message=f"Execution failed: {exc}",
            )
        return self.record_result(task.task_id, result.success, now, result.message)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def task(self, task_id: str) -> AutomationTask | None:
        return self._tasks.get(task_id)

    @property
    def tasks(self) -> tuple[AutomationTask, ...]:
        """All tasks, in submission order."""
        return tuple(self._tasks.values())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _record(self, task: AutomationTask) -> AutomationTask:
        self._tasks[task.task_id] = task
        return task

    def _update(
        self,
        task: AutomationTask,
        status: AutomationStatus,
        message: str = "",
        executed_at: float | None = None,
    ) -> AutomationTask:
        updated = AutomationTask(
            task_id=task.task_id,
            recommendation_id=task.recommendation_id,
            action=task.action,
            target=task.target,
            destructive=task.destructive,
            requested_at=task.requested_at,
            status=status,
            approved_at=task.approved_at,
            executed_at=executed_at if executed_at is not None else task.executed_at,
            message=message,
        )
        self._tasks[task.task_id] = updated
        return updated


__all__ = [
    "DEFAULT_ACTION_COOLDOWN_SECONDS",
    "DEFAULT_MAX_EXECUTIONS_PER_TARGET",
    "AutomationEngine",
]
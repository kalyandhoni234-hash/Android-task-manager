"""Safe automation — approved, cooldown-bounded, loop-protected actions.

Runs recommendations through the v0.7 action layer with an explicit
approval gate, per-(action, target) cooldowns and a per-session execution
budget (loop protection). Destructive actions never run through
automation, even when approved.
"""

from .engine import (
    DEFAULT_ACTION_COOLDOWN_SECONDS,
    DEFAULT_MAX_EXECUTIONS_PER_TARGET,
    AutomationEngine,
)
from .models import AutomationStatus, AutomationTask

__all__ = [
    "DEFAULT_ACTION_COOLDOWN_SECONDS",
    "DEFAULT_MAX_EXECUTIONS_PER_TARGET",
    "AutomationEngine",
    "AutomationStatus",
    "AutomationTask",
]
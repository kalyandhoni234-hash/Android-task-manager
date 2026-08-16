"""Diagnostics engine: evidence-based device diagnostics.

A pure, deterministic layer that turns already-collected snapshots
(CPU, memory, battery, device information) into structured, explainable
:class:`~android_task_manager.diagnostics.models.DiagnosticFinding`
objects. It adds no ADB traffic, never guesses, treats UNKNOWN data as
"no claim", and never produces a score.
"""

from .evaluate import evaluate
from .models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticSeverity,
)

__all__ = [
    "DiagnosticCategory",
    "DiagnosticFinding",
    "DiagnosticReport",
    "DiagnosticSeverity",
    "evaluate",
]
"""Diagnostics models: structured, evidence-based findings.

A :class:`DiagnosticFinding` is the contract between the rule functions
(``rules.py``), the evaluator (``evaluate.py``) and — in a later phase —
the GUI. Every finding carries its own explanation: WHAT the situation
is, WHY it was raised, the EVIDENCE it is based on (always actual
collected fields, never vague claims) and a RECOMMENDED ACTION.

Design rules:

- Findings are frozen and deterministic: the same inputs always produce
  the same finding.
- ``UNKNOWN`` data never produces a finding. A missing value means "no
  evidence" and therefore "no claim".
- No score is computed anywhere: findings are individual, explainable
  facts, never aggregated into a health/security number.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiagnosticCategory(Enum):
    """Which domain a finding belongs to (for grouping in the UI)."""

    BATTERY = "battery"
    STORAGE = "storage"
    MEMORY = "memory"
    CPU = "cpu"
    NETWORK = "network"
    SECURITY = "security"
    #: Process-count / scheduler pressure (advanced performance intelligence).
    PROCESS = "process"


class DiagnosticSeverity(Enum):
    """Small explicit severity model: three levels, nothing more."""

    #: (rank, label): rank orders findings critical-first in a report.
    INFO = (0, "info")
    WARNING = (1, "warning")
    CRITICAL = (2, "critical")

    @property
    def rank(self) -> int:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]


@dataclass(frozen=True)
class DiagnosticFinding:
    """One explainable, evidence-based diagnostic observation.

    ``evidence`` is always a concrete restatement of collected fields
    (e.g. ``"/data usage: 92%"``) — never a vague claim such as
    "device appears unhealthy".
    """

    severity: DiagnosticSeverity
    category: DiagnosticCategory
    title: str
    what: str
    why: str
    evidence: str
    recommended_action: str


@dataclass(frozen=True)
class DiagnosticReport:
    """The deterministic result of evaluating one snapshot bundle.

    ``findings`` is ordered severity-first (CRITICAL, WARNING, INFO) and
    then by category and title, so identical inputs always produce an
    identical report.
    """

    findings: tuple[DiagnosticFinding, ...]

    @property
    def counts(self) -> dict[DiagnosticSeverity, int]:
        """Findings per severity (all three levels always present)."""
        counts = {
            DiagnosticSeverity.INFO: 0,
            DiagnosticSeverity.WARNING: 0,
            DiagnosticSeverity.CRITICAL: 0,
        }
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts


__all__ = [
    "DiagnosticCategory",
    "DiagnosticFinding",
    "DiagnosticReport",
    "DiagnosticSeverity",
]
"""Why-flagged dialog: the evidence facts behind one heuristic signal.

Read-only "why was this flagged?" panel. The facts come from the pure
``explain_signal`` aggregation over already-collected data — deterministic,
no LLM, no GUI-text scraping. Facts are facts ("Socket was not present in
baseline."), never verdicts ("This is malware.").
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..heuristics.models import SuspiciousSignal
from ..investigation.models import EvidenceExplanation, EvidenceFact


class WhyFlaggedDialog(QDialog):
    """Evidence explanation for one suspicious signal."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Why Was This Flagged?")
        self.resize(720, 520)

        self._title = QLabel("")
        self._title.setObjectName("incidentDialogTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)

        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)

        close_btn.clicked.connect(self.accept)

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def show_explanation(
        self, signal: SuspiciousSignal, explanation: EvidenceExplanation
    ) -> None:
        """Render the signal header and its evidence facts."""
        self._title.setText(f"{signal.rule_id} · {signal.severity} · {signal.entity}")
        lines: list[str] = [
            explanation.headline,
            "",
            f"Rule: {signal.rule_id}",
            f"Severity: {signal.severity}",
            f"Entity: {signal.entity}",
            "",
            "EVIDENCE (facts from collected data):",
            "",
        ]
        for fact in explanation.facts:
            lines.extend(_fact_lines(fact))
        if not explanation.facts:
            lines.append("No evidence facts could be derived from the collected data.")
        lines.extend(
            [
                "",
                "This panel lists facts only — it does not determine whether "
                "the entity is malicious.",
            ]
        )
        self._view.setPlainText("\n".join(lines))

    def show_error(self, message: str) -> None:
        """Honest fallback when the signal cannot be explained from data."""
        self._title.setText("Why Was This Flagged?")
        self._view.setPlainText(message)


def _fact_lines(fact: EvidenceFact) -> list[str]:
    reference = f"  [{fact.reference}]" if fact.reference else ""
    return [
        f"• {fact.text}{reference}",
        f"    category: {fact.category}",
        "",
    ]
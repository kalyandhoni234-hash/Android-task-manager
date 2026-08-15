"""Findings page: severity-first presentation of existing heuristic signals.

The signals come straight from the already-evaluated HeuristicReport — the
same signal objects the Baseline page lists inline. No new analysis: this
page only re-orders and re-emphasizes by severity (HIGH first, then MEDIUM,
then anything else), renders the signal's own reason wording verbatim, and
offers the same "Why?" evidence button. The existing IncidentPanel (report
generation/export) is hosted here so findings and their investigation
artifact live in one place.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..heuristics import SEVERITY_HIGH, SEVERITY_MEDIUM, HeuristicReport
from ..incident.models import IncidentReport
from .widgets.incident_panel import IncidentPanel

_SEVERITY_RANK = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1}


class FindingsPage(QWidget):
    """The FINDINGS navigation destination: signals + incident reporting."""

    #: (SuspiciousSignal) the user asked "why was this flagged?" for a signal.
    why_requested = Signal(object)

    def __init__(
        self,
        incident_panel: IncidentPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._incident = incident_panel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        title = QLabel("Findings")
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        subtitle = QLabel("Suspicious signals from the last heuristic evaluation")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(subtitle)

        self._signals_box = QWidget()
        self._signals_layout = QVBoxLayout(self._signals_box)
        self._signals_layout.setContentsMargins(0, 0, 0, 0)
        self._signals_layout.setSpacing(10)
        self._empty = QLabel("")
        self._empty.setObjectName("emptyBody")
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        self._empty.setWordWrap(True)
        self._signals_layout.addWidget(self._empty)
        layout.addWidget(self._signals_box, 1)

        layout.addWidget(self._incident)
        self.show_heuristics(None)

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def show_heuristics(self, heuristics: HeuristicReport | None) -> None:
        """Render the signals severity-first; None clears the list."""
        while self._signals_layout.count() > 1:
            item = self._signals_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if heuristics is None:
            self._empty.setText(
                "No suspicious signals have been evaluated yet.\n\n"
                "Save a baseline and run Check Drift to evaluate the "
                "heuristic rules against the device state."
            )
            self._empty.show()
            return
        signals = sorted(
            heuristics.signals,
            key=lambda s: (
                _SEVERITY_RANK.get(s.severity, 2),
                s.rule_id,
                s.entity,
            ),
        )
        if not signals:
            self._empty.setText(
                f"No suspicious signals detected ({len(heuristics.rules_applied)} "
                "rules checked)."
            )
            self._empty.show()
            return
        self._empty.hide()
        for signal in signals:
            self._signals_layout.addWidget(self._make_card(signal))

    def show_report(self, report: IncidentReport | None) -> None:
        """Mirror the hosted incident panel's report state."""
        self._incident.set_report(report)

    # ------------------------------------------------------------------
    # Card rendering
    # ------------------------------------------------------------------

    def _make_card(self, signal) -> QWidget:
        card = QWidget()
        card.setObjectName(
            "findingCardHigh"
            if signal.severity == SEVERITY_HIGH
            else "findingCard"
        )

        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        severity = QLabel(signal.severity)
        severity.setObjectName("findingSeverity")
        severity.setTextFormat(Qt.TextFormat.PlainText)
        if signal.severity == SEVERITY_HIGH:
            severity.setProperty("level", "high")
        elif signal.severity == SEVERITY_MEDIUM:
            severity.setProperty("level", "elevated")
        else:
            severity.setObjectName("muted")
        head.addWidget(severity)

        rule = QLabel(signal.rule_id)
        rule.setObjectName("findingRule")
        rule.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(rule, 1)

        why = QPushButton("Why?")
        why.setObjectName("secondary")
        why.setCursor(Qt.CursorShape.PointingHandCursor)
        why.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        why.setAccessibleName(f"Why was {signal.rule_id} flagged")
        why.setToolTip("Show the evidence facts behind this signal")
        why.clicked.connect(lambda checked=False, s=signal: self.why_requested.emit(s))
        head.addWidget(why)
        inner.addLayout(head)

        reason = QLabel(signal.reason)
        reason.setObjectName("findingReason")
        reason.setWordWrap(True)
        reason.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(reason)

        entity = QLabel(f"Entity: {signal.entity}")
        entity.setObjectName("muted")
        entity.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(entity)
        return card
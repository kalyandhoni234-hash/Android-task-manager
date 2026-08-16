"""Diagnostics page: presentation of the diagnostics engine's report.

Pure rendering of a structured :class:`DiagnosticReport` — the rules live
in the diagnostics engine and are never restated here. The page shows
every finding with its full WHAT / WHY / EVIDENCE / RECOMMENDED ACTION
(no collapse: everything is visible to assistive technology), preserves
the report's severity-first order exactly, and never invents a finding:
missing data simply means no finding, and "no issues detected" is always
qualified as an absence-of-evidence statement, never a health claim.

Distinct states are rendered distinctly:

- no device connected: a clear empty state (stale findings never linger);
- connected with zero findings: "No issues detected" plus the honest
  caveat that absence of findings is not proof of health;
- connected with findings: severity-first cards.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics.models import (
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticSeverity,
)
from .styles import repolish

#: Card objectName per severity (theme accent, never color-only).
_CARD_STYLE = {
    DiagnosticSeverity.CRITICAL: "findingCardHigh",
    DiagnosticSeverity.WARNING: "findingCard",
    DiagnosticSeverity.INFO: "diagCardInfo",
}

#: Severity badge level property -> theme color token.
_BADGE_LEVEL = {
    DiagnosticSeverity.CRITICAL: "high",
    DiagnosticSeverity.WARNING: "elevated",
    DiagnosticSeverity.INFO: "info",
}


class DiagnosticsPage(QWidget):
    """The DIAGNOSTICS navigation destination: rule findings, verbatim."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        title = QLabel("Diagnostics")
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        subtitle = QLabel(
            "Device telemetry interpreted by the diagnostics rules"
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(subtitle)

        self._summary = QLabel("")
        self._summary.setObjectName("securityStatus")
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._summary)

        self._findings_box = QWidget()
        self._findings_layout = QVBoxLayout(self._findings_box)
        self._findings_layout.setContentsMargins(0, 0, 0, 0)
        self._findings_layout.setSpacing(10)
        self._empty = QLabel("")
        self._empty.setObjectName("deviceEmptyTitle")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        self._findings_layout.addWidget(self._empty)
        layout.addWidget(self._findings_box, 1)

        self.refresh(None, False)

    # ------------------------------------------------------------------
    # State entry (MainWindow calls this on the GUI thread)
    # ------------------------------------------------------------------

    def refresh(
        self,
        report: DiagnosticReport | None,
        connected: bool,
    ) -> None:
        """Render one report; ``connected`` selects the device states.

        ``None`` with no connection is the "no device" state; ``None`` or
        an empty report on a connected device is the "no issues detected"
        state. The report's finding order is preserved exactly — this page
        never re-sorts.
        """
        self._clear_findings()
        if not connected:
            self._summary.hide()
            self._empty.setText(
                "NO DEVICE CONNECTED\n\n"
                "Connect an Android device through ADB to monitor telemetry."
            )
            self._empty.setObjectName("deviceEmptyTitle")
            self._empty.show()
            return
        self._summary.show()
        findings = report.findings if report is not None else ()
        self._render_summary(report.counts if report is not None else {})
        if not findings:
            self._empty.setObjectName("emptyBody")
            self._empty.setText(
                "No issues detected.\n\n"
                "The currently collected device data does not indicate a "
                "known problem. Absence of findings is not proof of health."
            )
            self._empty.show()
            return
        self._empty.hide()
        for finding in findings:
            self._findings_layout.addWidget(self._make_card(finding))

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_summary(self, counts: dict[DiagnosticSeverity, int]) -> None:
        critical = counts.get(DiagnosticSeverity.CRITICAL, 0)
        warning = counts.get(DiagnosticSeverity.WARNING, 0)
        info = counts.get(DiagnosticSeverity.INFO, 0)
        parts = [
            f"{critical} CRITICAL",
            f"{warning} WARNING",
            f"{info} INFO",
        ]
        self._summary.setText(" \u00b7 ".join(parts))
        if critical:
            self._summary.setObjectName("securityStatusHigh")
        elif warning:
            self._summary.setObjectName("securityStatusMedium")
        else:
            self._summary.setObjectName("securityStatus")
        repolish(self._summary)

    def _make_card(self, finding: DiagnosticFinding) -> QWidget:
        card = QWidget()
        card.setObjectName(_CARD_STYLE[finding.severity])

        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        severity = QLabel(finding.severity.label.upper())
        severity.setObjectName("findingSeverity")
        severity.setTextFormat(Qt.TextFormat.PlainText)
        level = _BADGE_LEVEL.get(finding.severity)
        if level is not None:
            severity.setProperty("level", level)
        else:
            severity.setObjectName("muted")
        head.addWidget(severity)

        title_label = QLabel(finding.title)
        title_label.setObjectName("findingRule")
        title_label.setWordWrap(True)
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(title_label, 1)

        category = QLabel(finding.category.value.upper())
        category.setObjectName("muted")
        category.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(category)
        inner.addLayout(head)

        for caption, text in (
            ("WHAT", finding.what),
            ("WHY", finding.why),
            ("EVIDENCE", finding.evidence),
            ("RECOMMENDED ACTION", finding.recommended_action),
        ):
            inner.addLayout(self._detail_row(caption, text))
        return card

    @staticmethod
    def _detail_row(caption: str, text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        field = QLabel(caption)
        field.setObjectName("diagField")
        field.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(field)
        value = QLabel(text)
        value.setObjectName("findingReason")
        value.setWordWrap(True)
        value.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(value, 1)
        return row

    def _clear_findings(self) -> None:
        """Remove every rendered finding card (keeps the empty label)."""
        while self._findings_layout.count() > 1:
            item = self._findings_layout.takeAt(1)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
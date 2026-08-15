"""Overview page: a concise summary of existing application state.

Pure presentation over data the monitoring session already collected —
no analysis is performed here. Every metric is displayed only when the
value exists; otherwise the card shows an honest "—". No security scores,
no risk percentages, no threat levels are ever computed: the Security
Status section re-states the existing severity counts in the severity
model's own vocabulary (HIGH / MEDIUM / INFO).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .monitor import ConnectionState
from .styles import repolish


@dataclass(frozen=True)
class OverviewState:
    """Everything the overview page may render — all fields optional."""

    device_label: str | None = None
    android_version: str | None = None
    connection: ConnectionState | None = None
    process_count: int | None = None
    socket_count: int | None = None
    drift_count: int | None = None
    high_findings: int | None = None
    medium_findings: int | None = None
    baseline_at: str | None = None
    drift_checked_at: str | None = None
    audits_run: int | None = None
    rules_checked: int | None = None
    signals_seen: int | None = None


class OverviewPage(QWidget):
    """Device summary, metric cards, security status and recent activity."""

    #: The user asked to open the Baseline page (empty-state shortcut).
    baseline_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self._page_title = QLabel("Overview")
        self._page_title.setObjectName("pageTitle")
        self._page_title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._page_title)

        self._page_subtitle = QLabel("Device summary and current monitoring state")
        self._page_subtitle.setObjectName("pageSubtitle")
        self._page_subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._page_subtitle)

        # -- Device summary --------------------------------------------------
        self._device_title = QLabel("No device selected")
        self._device_title.setObjectName("value")
        self._device_subtitle = QLabel("Connect a device to begin monitoring.")
        self._device_subtitle.setObjectName("muted")
        self._device_status = QLabel("\u25cb No device connected")
        self._device_status.setObjectName("statusError")

        device_row = QHBoxLayout()
        device_col = QVBoxLayout()
        device_col.setSpacing(2)
        device_col.addWidget(self._device_title)
        device_col.addWidget(self._device_subtitle)
        device_row.addLayout(device_col, 1)
        device_row.addWidget(self._device_status)
        layout.addLayout(device_row)

        # -- Metric cards ----------------------------------------------------
        self._cards: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setSpacing(12)
        for column, (key, caption) in enumerate(
            (
                ("processes", "PROCESSES"),
                ("sockets", "NETWORK"),
                ("drift", "DRIFT"),
                ("high", "HIGH FINDINGS"),
                ("medium", "MEDIUM FINDINGS"),
            )
        ):
            card, value = self._make_card(caption)
            self._cards[key] = value
            grid.addWidget(card, 0, column)
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        # -- Security status -------------------------------------------------
        security_card = QWidget()
        security_card.setObjectName("metricCard")
        security_layout = QVBoxLayout(security_card)
        security_layout.setContentsMargins(14, 12, 14, 12)
        security_layout.setSpacing(4)

        status_title = QLabel("SECURITY STATUS")
        status_title.setObjectName("sectionTitle")
        security_layout.addWidget(status_title)

        self._security_line = QLabel("No findings to report yet.")
        self._security_line.setObjectName("securityStatus")
        self._security_line.setWordWrap(True)
        self._security_line.setTextFormat(Qt.TextFormat.PlainText)
        security_layout.addWidget(self._security_line)

        self._drift_link = QPushButton("Run a drift check from the Baseline page")
        self._drift_link.setObjectName("link")
        self._drift_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drift_link.setAccessibleName("Run a drift check from the Baseline page")
        self._drift_link.setVisible(False)
        self._drift_link.clicked.connect(self.baseline_requested.emit)
        security_layout.addWidget(self._drift_link)

        layout.addWidget(security_card)

        # -- Recent activity -------------------------------------------------
        activity_card = QWidget()
        activity_card.setObjectName("metricCard")
        activity_layout = QVBoxLayout(activity_card)
        activity_layout.setContentsMargins(14, 12, 14, 12)
        activity_layout.setSpacing(4)

        activity_title = QLabel("RECENT ACTIVITY")
        activity_title.setObjectName("sectionTitle")
        activity_layout.addWidget(activity_title)

        self._activity = QLabel("No monitoring activity yet.")
        self._activity.setObjectName("muted")
        self._activity.setWordWrap(True)
        self._activity.setTextFormat(Qt.TextFormat.PlainText)
        activity_layout.addWidget(self._activity)

        layout.addWidget(activity_card)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def refresh(self, state: OverviewState) -> None:
        """Re-render the whole page from one immutable summary state."""
        self._render_device(state)
        self._render_cards(state)
        self._render_security(state)
        self._render_activity(state)

    def _render_device(self, state: OverviewState) -> None:
        if state.device_label:
            self._device_title.setText(state.device_label)
            self._device_subtitle.setText(
                f"Android {state.android_version}" if state.android_version else ""
            )
        else:
            self._device_title.setText("No device selected")
            self._device_subtitle.setText("Connect a device to begin monitoring.")
        if state.connection is not None:
            text, object_name = self._status_for(state.connection)
            self._device_status.setText(text)
            self._device_status.setObjectName(object_name)
            repolish(self._device_status)
        else:
            self._device_status.setText("\u25cb No device connected")
            self._device_status.setObjectName("statusError")
            repolish(self._device_status)

    def _render_cards(self, state: OverviewState) -> None:
        values = {
            "processes": state.process_count,
            "sockets": state.socket_count,
            "drift": state.drift_count,
            "high": state.high_findings,
            "medium": state.medium_findings,
        }
        for key, value in values.items():
            label = self._cards[key]
            label.setText(self._fmt(value))
            if key == "high" and value:
                label.setObjectName("cardValueHigh")
            elif key == "medium" and value:
                label.setObjectName("cardValueMedium")
            else:
                label.setObjectName("cardValue")
            repolish(label)

    def _render_security(self, state: OverviewState) -> None:
        high = state.high_findings or 0
        medium = state.medium_findings or 0
        if state.high_findings is None and state.medium_findings is None:
            self._security_line.setText("No findings to report yet.")
            self._security_line.setObjectName("securityStatus")
            self._drift_link.setVisible(True)
        elif high:
            self._security_line.setText(
                f"{high} HIGH finding(s). Review the Findings page."
            )
            self._security_line.setObjectName("securityStatusHigh")
            self._drift_link.setVisible(False)
        elif medium:
            self._security_line.setText(
                f"{medium} MEDIUM finding(s). Review the Findings page."
            )
            self._security_line.setObjectName("securityStatusMedium")
            self._drift_link.setVisible(False)
        else:
            self._security_line.setText("No HIGH or MEDIUM findings.")
            self._security_line.setObjectName("securityStatus")
            self._drift_link.setVisible(False)
        repolish(self._security_line)

    def _render_activity(self, state: OverviewState) -> None:
        lines: list[str] = []
        if state.baseline_at:
            lines.append(f"Baseline saved: {state.baseline_at}")
        if state.drift_checked_at:
            lines.append(f"Last drift check: {state.drift_checked_at} ({state.drift_count or 0} change(s))")
        if state.rules_checked is not None:
            lines.append(
                f"Last signal check: {state.rules_checked} rule(s) applied, "
                f"{state.signals_seen or 0} signal(s)"
            )
        if state.audits_run:
            audits = "1 permission audit" if state.audits_run == 1 else f"{state.audits_run} permission audits"
            lines.append(f"Session audits: {audits}")
        self._activity.setText(
            "\n".join(lines)
            if lines
            else "No monitoring activity yet. Activity will appear here once monitoring starts."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(value: int | None) -> str:
        return "—" if value is None else str(value)

    @staticmethod
    def _status_for(state: ConnectionState) -> tuple[str, str]:
        mapping = {
            ConnectionState.CONNECTED: ("\u25cf Connected", "statusConnected"),
            ConnectionState.DISCONNECTED: ("\u25cb No device connected", "statusError"),
            ConnectionState.ADB_MISSING: ("\u26a0 ADB not found", "statusError"),
            ConnectionState.OFFLINE: ("\u26a0 Device offline", "statusWarn"),
            ConnectionState.MULTIPLE_DEVICES: ("\u26a0 Multiple devices", "statusWarn"),
            ConnectionState.ADB_ERROR: ("\u26a0 adb error", "statusError"),
            ConnectionState.UNAUTHORIZED: ("\u26a0 Not authorized", "statusWarn"),
            ConnectionState.TIMEOUT: ("\u26a0 Timed out", "statusWarn"),
            ConnectionState.COLLECTOR_ERROR: ("\u26a0 Data error", "statusWarn"),
        }
        return mapping.get(state, ("\u25cb No device connected", "statusError"))

    def _make_card(self, caption: str) -> tuple[QWidget, QLabel]:
        card = QWidget()
        card.setObjectName("metricCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(4)
        cap = QLabel(caption)
        cap.setObjectName("cardCaption")
        cap.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(cap)
        value = QLabel("—")
        value.setObjectName("cardValue")
        value.setProperty("mono", True)
        value.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(value)
        return card, value
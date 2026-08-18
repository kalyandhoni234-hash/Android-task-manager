"""Intelligence page: device health, recommendations, timeline and rules.

The v0.8 DEVICE INTELLIGENCE surface: a single page that renders the
deterministic intelligence core (health engine, event timeline, rule
engine, recommendation engine, automation state) without owning any of
it — MainWindow owns the engines; this page only presents their outputs
and forwards the user's Apply clicks.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..automation.models import AutomationTask
from ..health.models import DeviceHealth
from ..recommend.models import Recommendation
from ..timeline.models import TimelineEvent

#: Maximum number of timeline rows rendered (the timeline itself is
#: bounded; this caps the page rendering on top of it).
MAX_TIMELINE_ROWS = 40


@dataclass(frozen=True)
class IntelligenceState:
    """Everything the page renders; owned by MainWindow."""

    connected: bool = False
    health: DeviceHealth | None = None
    recommendations: tuple[Recommendation, ...] = ()
    timeline: tuple[TimelineEvent, ...] = ()
    rule_fires: tuple[str, ...] = ()
    automation_tasks: tuple[AutomationTask, ...] = ()


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("intelligenceSection")
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class IntelligencePage(QWidget):
    """The DEVICE INTELLIGENCE page (renders engines' outputs only)."""

    #: (Recommendation) the user asked to apply a recommendation's action.
    apply_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("intelligencePage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # -- Health -------------------------------------------------------
        layout.addWidget(_section("DEVICE HEALTH"))
        self._health_card = QFrame()
        self._health_card.setObjectName("healthCard")
        health_layout = QVBoxLayout(self._health_card)
        health_layout.setContentsMargins(10, 8, 10, 8)
        self._health_status = QLabel()
        self._health_status.setObjectName("healthStatus")
        self._health_status.setWordWrap(True)
        health_layout.addWidget(self._health_status)
        self._health_components = QLabel()
        self._health_components.setObjectName("healthComponents")
        self._health_components.setWordWrap(True)
        health_layout.addWidget(self._health_components)
        layout.addWidget(self._health_card)

        # -- Recommendations ----------------------------------------------
        layout.addWidget(_section("RECOMMENDATIONS"))
        self._recommendations_area = QScrollArea()
        self._recommendations_area.setObjectName("recommendationsArea")
        self._recommendations_area.setWidgetResizable(True)
        self._recommendations_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._recommendations_box = QWidget()
        self._recommendations_layout = QVBoxLayout(self._recommendations_box)
        self._recommendations_layout.setContentsMargins(0, 0, 0, 0)
        self._recommendations_layout.setSpacing(6)
        self._recommendations_area.setWidget(self._recommendations_box)
        self._recommendations_empty = QLabel("No recommendations yet.")
        self._recommendations_empty.setObjectName("recommendationsEmpty")
        self._recommendations_empty.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._recommendations_area, 2)
        self._recommendation_rows: list[QWidget] = []

        # -- Timeline ------------------------------------------------------
        layout.addWidget(_section("TIMELINE"))
        self._timeline_label = QLabel()
        self._timeline_label.setObjectName("timelineText")
        self._timeline_label.setWordWrap(True)
        self._timeline_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._timeline_label)

        # -- Rule alerts ---------------------------------------------------
        layout.addWidget(_section("RULE ALERTS"))
        self._rules_label = QLabel()
        self._rules_label.setObjectName("ruleAlertsText")
        self._rules_label.setWordWrap(True)
        self._rules_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._rules_label)

        # -- Automation -----------------------------------------------------
        layout.addWidget(_section("AUTOMATION"))
        self._automation_label = QLabel()
        self._automation_label.setObjectName("automationText")
        self._automation_label.setWordWrap(True)
        self._automation_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._automation_label)

        layout.addStretch(1)
        self.refresh(IntelligenceState())

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def refresh(self, state: IntelligenceState) -> None:
        """Render a snapshot of the intelligence engines' outputs."""
        self._render_health(state.health, state.connected)
        self._render_recommendations(state.recommendations)
        self._render_timeline(state.timeline)
        self._render_rules(state.rule_fires)
        self._render_automation(state.automation_tasks)

    def _render_health(self, health: DeviceHealth | None, connected: bool) -> None:
        if not connected or health is None:
            self._health_status.setText("\u2014 No device connected")
            self._health_components.setText("")
            return
        status = health.status.value
        score = health.overall_score
        score_text = "\u2014" if score is None else f"{score:.0f}"
        self._health_status.setText(
            f"Overall: {score_text}/100 \u00b7 Status: {status.upper()}"
        )
        parts = []
        for key in ("cpu", "memory", "battery", "storage", "processes", "applications", "connectivity"):
            component = health.components.get(key)
            if component is None:
                continue
            parts.append(f"{key}: {component.status.value}")
        self._health_components.setText(" \u00b7 ".join(parts))

    def _render_recommendations(self, recommendations: tuple[Recommendation, ...]) -> None:
        for row in self._recommendation_rows:
            row.deleteLater()
        self._recommendation_rows = []
        if not recommendations:
            self._recommendations_layout.addWidget(self._recommendations_empty)
            return
        self._recommendations_empty.deleteLater()
        for recommendation in recommendations:
            row = self._recommendation_row(recommendation)
            self._recommendation_rows.append(row)
            self._recommendations_layout.addWidget(row)

    def _recommendation_row(self, recommendation: Recommendation) -> QWidget:
        frame = QFrame()
        frame.setObjectName("recommendationRow")
        frame.setProperty("severity", recommendation.severity)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        title = QLabel(
            f"{recommendation.recommendation_id} \u00b7 "
            f"{recommendation.severity.upper()} \u00b7 {recommendation.title}"
        )
        title.setObjectName("recommendationTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        rationale = QLabel(recommendation.rationale)
        rationale.setObjectName("recommendationRationale")
        rationale.setTextFormat(Qt.TextFormat.PlainText)
        rationale.setWordWrap(True)
        layout.addWidget(rationale)
        if recommendation.action is not None and recommendation.target is not None:
            action_line = QLabel(
                f"Action: {recommendation.action} {recommendation.target}"
            )
            action_line.setObjectName("recommendationAction")
            action_line.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(action_line)
            apply = QPushButton("Apply")
            apply.setObjectName("recommendationApply")
            apply.setCursor(Qt.CursorShape.PointingHandCursor)
            apply.clicked.connect(
                lambda checked=False, rec=recommendation: self.apply_requested.emit(rec)
            )
            layout.addWidget(apply, alignment=Qt.AlignmentFlag.AlignRight)
        return frame

    def _render_timeline(self, events: tuple[TimelineEvent, ...]) -> None:
        if not events:
            self._timeline_label.setText("\u2014 No events yet.")
            return
        lines = []
        for event in events[-MAX_TIMELINE_ROWS:]:
            when = event.timestamp.strftime("%H:%M:%S") if event.timestamp else "\u2014"
            lines.append(f"{when}  {event.event_id}  {event.title}")
        self._timeline_label.setText("\n".join(lines))

    def _render_rules(self, rule_fires: tuple[str, ...]) -> None:
        if not rule_fires:
            self._rules_label.setText("\u2014 No rule alerts.")
            return
        self._rules_label.setText("\n".join(rule_fires))

    def _render_automation(self, tasks: tuple[AutomationTask, ...]) -> None:
        if not tasks:
            self._automation_label.setText("\u2014 No automation tasks.")
            return
        lines = [
            f"{task.task_id} \u00b7 {task.status.value} \u00b7 "
            f"{task.action} {task.target}"
            + (f" \u00b7 {task.message}" if task.message else "")
            for task in tasks
        ]
        self._automation_label.setText("\n".join(lines))
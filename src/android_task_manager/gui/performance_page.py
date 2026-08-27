"""Performance Intelligence UI (Phase 3 presentation).

Pure rendering of :class:`android_task_manager.performance.view.PerformanceViewState`
— the analysis lives in :mod:`android_task_manager.performance` and is never
restated here. The page answers the six Phase 3 questions:

* is the device under pressure?      -> the overview badge
* which metric?                      -> per-metric condition badges
* how strong is the evidence?        -> the evidence panel + occupancy
* how does it compare to baseline?   -> per-metric baseline / delta
* which app deserves investigation?  -> the application correlation rows
* started / active / recovered?      -> findings phase + lifecycle events

Strict honesty rules (inherited from the domain):

* unavailable values render as ``—`` (never fabricated 0);
* baseline statistics only show when enough samples exist, otherwise
  "Collecting baseline…";
* application rows show *correlation* (elevated activity during the pressure
  window), never "this app caused the spike";
* no action is ever triggered from this page.

Two surfaces are provided:

* :class:`PerformancePage` — the full standalone page (sidebar destination).
* :class:`PerformanceSummaryWidget` — a compact widget embedded in the existing
  Intelligence page (near Device Health), with a "View Performance" button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..performance.episodes import format_duration as _format_duration
from ..performance.view import (
    STATE_APPLICATION_PRESSURE,
    STATE_CPU_PRESSURE,
    STATE_MEMORY_PRESSURE,
    STATE_MULTI_METRIC,
    STATE_NORMAL,
    STATE_PROCESS_PRESSURE,
    STATE_RECOVERING,
    STATE_STORAGE_PRESSURE,
    AppCorrelation,
    EventRow,
    EvidenceRow,
    FindingView,
    MetricView,
    PerformanceViewState,
)
from .styles import repolish
from .widgets.history_base import HistoryPlotWidget

#: Card objectName per finding/condition severity (theme accent, never color-only).
_CARD_STYLE = {
    "CRITICAL": "findingCardHigh",
    "WARNING": "findingCard",
    "INFO": "diagCardInfo",
}

#: Severity badge level property -> theme color token.
_BADGE_LEVEL = {
    "CRITICAL": "high",
    "ELEVATED": "elevated",
    "WARNING": "elevated",
    "INFO": "info",
    "NORMAL": "info",
    "UNKNOWN": "muted",
}

#: Overall-state badge level property -> theme color token.
_STATE_BADGE_LEVEL = {
    STATE_NORMAL: "info",
    STATE_RECOVERING: "elevated",
    STATE_CPU_PRESSURE: "high",
    STATE_MEMORY_PRESSURE: "high",
    STATE_STORAGE_PRESSURE: "high",
    STATE_PROCESS_PRESSURE: "high",
    STATE_APPLICATION_PRESSURE: "high",
    STATE_MULTI_METRIC: "high",
}

#: Evidence panel group display order and titles.
_EVIDENCE_GROUPS = (
    ("observed", "OBSERVED"),
    ("threshold", "THRESHOLD"),
    ("baseline", "BASELINE"),
    ("change", "CHANGE"),
    ("correlated", "CORRELATED ACTIVITY"),
)


def _fmt_pct(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "—"


def _empty_metric(key: str) -> MetricView:
    return MetricView(
        key=key, label=key, unit="%", current=None, baseline=None,
        delta=None, occupancy=None, condition="UNKNOWN", evidence=None,
    )


def _fmt_occ(value: float | None) -> str:
    return f"{value * 100:.0f}%" if value is not None else "—"


def _fmt_int(value: int | None) -> str:
    return str(value) if value is not None else "—"


class _MetricCard(QFrame):
    """One canonical metric's compact card (current / baseline / condition)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("perfMetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        head = QHBoxLayout()
        self._label = QLabel()
        self._label.setObjectName("perfMetricLabel")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self._label)
        self._condition = QLabel()
        self._condition.setObjectName("findingSeverity")
        self._condition.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self._condition, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(head)

        self._current = QLabel()
        self._current.setObjectName("perfMetricValue")
        self._current.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._current)

        self._baseline = QLabel()
        self._baseline.setObjectName("perfMetricBaseline")
        self._baseline.setWordWrap(True)
        self._baseline.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._baseline)

        self._occupancy = QLabel()
        self._occupancy.setObjectName("perfMetricOcc")
        self._occupancy.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._occupancy)

        self._evidence = QLabel()
        self._evidence.setObjectName("perfMetricEvidence")
        self._evidence.setWordWrap(True)
        self._evidence.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._evidence)

    def update(self, view: MetricView) -> None:  # type: ignore[override]
        self._label.setText(view.label)
        self._current.setText(_fmt_pct(view.current))
        level = _BADGE_LEVEL.get(view.condition, "muted")
        self._condition.setText(view.condition)
        self._condition.setProperty("level", level)
        repolish(self._condition)
        if view.baseline is None:
            self._baseline.setText("Collecting baseline…")
        else:
            b = view.baseline
            delta = f"{view.delta:+.1f}" if view.delta is not None else "—"
            self._baseline.setText(
                f"Baseline  median {_fmt_pct(b.median)} · "
                f"p95 {_fmt_pct(b.p95)} · σ {_fmt_pct(b.stddev)}"
            )
            self._occupancy.setText(
                f"Δ baseline {delta} pp · threshold occupancy {_fmt_occ(view.occupancy)}"
            )
        self._evidence.setText(view.evidence or "")


class PerformancePage(QWidget):
    """The PERFORMANCE sidebar page: the full performance intelligence surface."""

    #: The user asked to jump to the unified Timeline (lives on the
    #: Intelligence page); the window navigates there.
    view_timeline_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("performancePage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Performance Intelligence")
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        subtitle = QLabel(
            "Observation and evidence from device telemetry — not a root-cause diagnosis."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(subtitle)

        self._state = QLabel()
        self._state.setObjectName("perfStateBadge")
        self._state.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._state)

        self._score = QLabel()
        self._score.setObjectName("perfScoreBadge")
        self._score.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._score)

        # -- Metric cards ---------------------------------------------------
        self._cards: dict[str, _MetricCard] = {}
        cards = QGridLayout()
        cards.setSpacing(10)
        for col, key in enumerate(("cpu", "memory", "storage", "battery")):
            card = _MetricCard()
            self._cards[key] = card
            cards.addWidget(card, 0, col)
        layout.addLayout(cards)

        # -- History -------------------------------------------------------
        self._history: dict[str, HistoryPlotWidget] = {}
        hist = QGridLayout()
        hist.setSpacing(10)
        for col, key in enumerate(("cpu", "memory", "storage", "battery")):
            plot = HistoryPlotWidget(f"{key.title()} history", ["#3d9be9"])
            self._history[key] = plot
            hist.addWidget(plot, 0, col)
        layout.addLayout(hist)

        # -- Findings ------------------------------------------------------
        layout.addWidget(self._section("Active findings"))
        self._findings_box = QWidget()
        self._findings_layout = QVBoxLayout(self._findings_box)
        self._findings_layout.setContentsMargins(0, 0, 0, 0)
        self._findings_layout.setSpacing(10)
        layout.addWidget(self._findings_box, 1)

        # -- Evidence ------------------------------------------------------
        layout.addWidget(self._section("Evidence"))
        self._evidence_box = QWidget()
        self._evidence_layout = QVBoxLayout(self._evidence_box)
        self._evidence_layout.setContentsMargins(0, 0, 0, 0)
        self._evidence_layout.setSpacing(8)
        layout.addWidget(self._evidence_box, 1)

        # -- Application correlation ---------------------------------------
        layout.addWidget(self._section("Application correlation"))
        self._apps_box = QWidget()
        self._apps_layout = QVBoxLayout(self._apps_box)
        self._apps_layout.setContentsMargins(0, 0, 0, 0)
        self._apps_layout.setSpacing(6)
        layout.addWidget(self._apps_box, 1)

        # -- Lifecycle events ----------------------------------------------
        layout.addWidget(self._section("Recent lifecycle events"))
        self._events_box = QWidget()
        self._events_layout = QVBoxLayout(self._events_box)
        self._events_layout.setContentsMargins(0, 0, 0, 0)
        self._events_layout.setSpacing(6)
        layout.addWidget(self._events_box, 1)

        # -- Why this is happening (Phase 4) -------------------------------
        layout.addWidget(self._section("Why this is happening"))
        self._why_box = QWidget()
        self._why_layout = QVBoxLayout(self._why_box)
        self._why_layout.setContentsMargins(0, 0, 0, 0)
        self._why_layout.setSpacing(10)
        layout.addWidget(self._why_box, 1)

        # -- Performance episodes (Phase 5) --------------------------------
        layout.addWidget(self._section("Performance episodes"))
        self._episodes_box = QWidget()
        self._episodes_layout = QVBoxLayout(self._episodes_box)
        self._episodes_layout.setContentsMargins(0, 0, 0, 0)
        self._episodes_layout.setSpacing(8)
        layout.addWidget(self._episodes_box, 1)

        # -- Timeline navigation -------------------------------------------
        nav = QPushButton("View in Timeline")
        nav.setObjectName("perfTimelineButton")
        nav.setCursor(Qt.CursorShape.PointingHandCursor)
        nav.clicked.connect(self.view_timeline_requested.emit)
        layout.addWidget(nav, alignment=Qt.AlignmentFlag.AlignLeft)

        self.refresh(PerformanceViewState(
            overall_state=STATE_NORMAL,
            metrics={},
            findings=(),
            evidence=(),
            app_correlations=(),
            events=(),
            history={},
        ), False)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def refresh(self, state: PerformanceViewState, connected: bool) -> None:
        self._clear(self._findings_layout)
        self._clear(self._evidence_layout)
        self._clear(self._apps_layout)
        self._clear(self._events_layout)
        self._clear(self._why_layout)
        self._clear(self._episodes_layout)

        if not connected:
            self._state.setText("DEVICE DISCONNECTED")
            self._state.setProperty("level", "muted")
            repolish(self._state)
            self._render_disconnected()
            return

        level = _STATE_BADGE_LEVEL.get(state.overall_state, "info")
        self._state.setText(state.overall_state.replace("_", " "))
        self._state.setProperty("level", level)
        repolish(self._state)

        for key, card in self._cards.items():
            card.update(state.metrics.get(key, _empty_metric(key)))
        self._refresh_history(state)

        if state.findings:
            for finding in state.findings:
                self._findings_layout.addWidget(self._make_finding_card(finding))
        else:
            self._add_empty(self._findings_layout, "No active performance conditions.")

        self._render_evidence(state.evidence)
        self._render_apps(state.app_correlations)
        self._render_why(state)
        self._render_episodes(state)

        if state.events:
            for event in state.events:
                self._events_layout.addWidget(self._make_event_row(event))
        else:
            self._add_empty(self._events_layout, "No lifecycle events yet.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _render_disconnected(self) -> None:
        for card in self._cards.values():
            card.update(MetricView(
                key="", label="—", unit="%", current=None, baseline=None,
                delta=None, occupancy=None, condition="UNKNOWN", evidence=None,
            ))
        for plot in self._history.values():
            plot.clear()
        self._score.setText("")
        self._score.setProperty("level", "muted")
        repolish(self._score)
        self._add_empty(self._findings_layout, "No device connected.")
        self._add_empty(self._evidence_layout, "No evidence collected.")
        self._add_empty(self._apps_layout, "No application activity.")
        self._add_empty(self._events_layout, "No lifecycle events.")
        self._add_empty(self._why_layout, "No evidence collected.")
        self._add_empty(self._episodes_layout, "No performance episodes recorded yet.")

    def _refresh_history(self, state: PerformanceViewState) -> None:
        for key, plot in self._history.items():
            plot.clear()
            for value in state.history.get(key, ()):
                plot.add_sample(0, value)

    def _render_evidence(self, rows: tuple[EvidenceRow, ...]) -> None:
        if not rows:
            self._add_empty(self._evidence_layout, "No evidence collected yet.")
            return
        for group_key, title in _EVIDENCE_GROUPS:
            group_rows = [r for r in rows if r.group == group_key]
            if not group_rows:
                continue
            label = QLabel(title)
            label.setObjectName("evidenceGroupTitle")
            label.setTextFormat(Qt.TextFormat.PlainText)
            self._evidence_layout.addWidget(label)
            for row in group_rows:
                self._evidence_layout.addWidget(self._make_evidence_row(row))

    def _render_apps(self, apps: tuple[AppCorrelation, ...]) -> None:
        if not apps:
            self._add_empty(self._apps_layout, "No correlated application activity.")
            return
        for app in apps:
            self._apps_layout.addWidget(self._make_app_row(app))

    def _render_why(self, state: PerformanceViewState) -> None:
        score = state.performance_score
        if score is not None:
            self._score.setText(f"PERFORMANCE HEALTH {score.score}/100")
            level = "info" if score.score >= 70 else ("elevated" if score.score >= 40 else "high")
            self._score.setProperty("level", level)
            repolish(self._score)
        else:
            self._score.setText("")
            self._score.setProperty("level", "muted")
            repolish(self._score)

        if not state.explanations:
            self._add_empty(self._why_layout, "No active performance conditions to explain.")
            return
        for expl in state.explanations:
            self._why_layout.addWidget(self._make_explanation_card(expl))
        if state.investigation_recommendations:
            rec_title = QLabel("RECOMMENDED INVESTIGATION")
            rec_title.setObjectName("whySectionTitle")
            rec_title.setTextFormat(Qt.TextFormat.PlainText)
            self._why_layout.addWidget(rec_title)
            for rec in state.investigation_recommendations:
                self._why_layout.addWidget(self._make_recommendation_row(rec))

    def _make_explanation_card(self, expl) -> QWidget:
        card = QWidget()
        card.setObjectName("perfExplanationCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)

        head = QLabel(expl.title)
        head.setObjectName("perfWhyTitle")
        head.setWordWrap(True)
        head.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(head)

        for line in expl.observed:
            inner.addWidget(self._make_note_row(line))

        interp = QLabel(expl.interpretation)
        interp.setObjectName("findingReason")
        interp.setWordWrap(True)
        interp.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(interp)

        if expl.contributors:
            sub = QLabel("OBSERVED CONTRIBUTORS")
            sub.setObjectName("whySectionTitle")
            sub.setTextFormat(Qt.TextFormat.PlainText)
            inner.addWidget(sub)
            for c in expl.contributors[:3]:
                inner.addWidget(self._make_contributor_row(c))
        return card

    def _make_note_row(self, text: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName("evidenceRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        dot = QLabel("•")
        dot.setObjectName("muted")
        dot.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(dot)
        value = QLabel(text)
        value.setObjectName("findingReason")
        value.setWordWrap(True)
        value.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(value, 1)
        return widget

    def _make_contributor_row(self, c) -> QWidget:
        widget = QWidget()
        widget.setObjectName("evidenceRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        name = QLabel(c.label or c.package)
        name.setObjectName("findingRule")
        name.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(name, 1)
        load = c.cpu_percent if c.relevant_metric == "cpu" else c.memory_percent
        detail = QLabel(
            f"{c.relevant_metric}: {_fmt_pct(load)} · procs {c.process_count or 0}"
        )
        detail.setObjectName("diagField")
        detail.setWordWrap(True)
        detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(detail, 2)
        return widget

    def _make_recommendation_row(self, rec: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName("evidenceRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        marker = QLabel("→")
        marker.setObjectName("muted")
        marker.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(marker)
        value = QLabel(rec)
        value.setObjectName("findingReason")
        value.setWordWrap(True)
        value.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(value, 1)
        return widget

    def _render_episodes(self, state: PerformanceViewState) -> None:
        episodes = list(state.active_episodes) + list(state.recent_episodes)
        if not episodes:
            self._add_empty(self._episodes_layout, "No performance episodes recorded yet.")
            return
        for ep in episodes:
            self._episodes_layout.addWidget(self._make_episode_card(ep))

    def _make_episode_card(self, ep) -> QWidget:
        card = QWidget()
        card.setObjectName("perfEpisodeCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(4)

        head = QHBoxLayout()
        title_text = f"{ep.condition_key.replace(':', ' ').upper()}"
        if getattr(ep, "episode_id", None):
            title_text = f"{ep.episode_id} · {title_text}"
        title = QLabel(title_text)
        title.setObjectName("perfWhyTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(title, 1)
        status_text = getattr(ep, "lifecycle", None) or (
            "ACTIVE" if ep.is_active else "RECOVERED"
        )
        status = QLabel(status_text)
        status.setObjectName("findingSeverity")
        status.setTextFormat(Qt.TextFormat.PlainText)
        level = "high" if ep.is_active else "info"
        status.setProperty("level", level)
        head.addWidget(status, alignment=Qt.AlignmentFlag.AlignRight)
        inner.addLayout(head)

        span = f"{_fmt_time(ep.started_at)} → {_fmt_time(ep.recovered_at)}"
        meta = QLabel(
            f"{span}   ·   {_format_duration(ep.duration)}"
        )
        meta.setObjectName("diagField")
        meta.setWordWrap(True)
        meta.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(meta)

        metrics_tuple = getattr(ep, "metrics", ()) or (ep.metric,)
        metric_names = " · ".join(m.upper() for m in metrics_tuple)
        sev_level = {"critical": "high", "warning": "elevated", "info": "info"}.get(
            str(ep.severity).lower(), "muted"
        )
        detail = QLabel(f"{str(ep.severity).upper()}   ·   METRICS {metric_names}")
        detail.setObjectName("findingSeverity")
        detail.setProperty("level", sev_level)
        detail.setTextFormat(Qt.TextFormat.PlainText)
        inner.addWidget(detail)

        score_parts: list[str] = []
        start = getattr(ep, "score_at_start", None)
        low = getattr(ep, "score_min", None)
        recovery = getattr(ep, "score_at_recovery", None)
        delta = getattr(ep, "score_delta", None)
        if low is not None or start is not None:
            score_parts.append(
                f"Score impact {_fmt_int(start)} → {_fmt_int(low)}"
            )
            if recovery is not None:
                score_parts.append(f"recovered at {_fmt_int(recovery)}")
            if delta is not None:
                score_parts.append(f"Δ {_fmt_int(delta)}")
        if score_parts:
            inner.addWidget(self._make_note_row("   ·   ".join(score_parts)))

        if ep.peak_value is not None:
            peak = f"Peak {ep.peak_value:.1f}%"
            if ep.baseline_value is not None:
                diff = ep.peak_value - ep.baseline_value
                sign = "+" if diff >= 0 else ""
                peak += f"   ·   {sign}{diff:.1f} pp vs baseline"
            inner.addWidget(self._make_note_row(peak))

        if ep.contributor_correlation:
            top = ep.contributor_correlation[0]
            if top.times_top > 0:
                name = top.label or top.package
                inner.addWidget(
                    self._make_note_row(
                        f"Top observed contributor: {name} "
                        f"({top.times_top}/{top.samples_total} samples)"
                    )
                )

        return card

    def _make_finding_card(self, finding: FindingView) -> QWidget:
        card = QWidget()
        card.setObjectName(_CARD_STYLE.get(finding.severity.upper(), "findingCard"))
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        severity = QLabel(finding.severity.upper())
        severity.setObjectName("findingSeverity")
        severity.setTextFormat(Qt.TextFormat.PlainText)
        sev_level = _BADGE_LEVEL.get(finding.severity.upper(), "muted")
        severity.setProperty("level", sev_level)
        head.addWidget(severity)
        title = QLabel(finding.title)
        title.setObjectName("findingRule")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(title, 1)
        category = QLabel(finding.category.upper())
        category.setObjectName("muted")
        category.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(category)
        inner.addLayout(head)

        inner.addLayout(self._detail_row("EVIDENCE", finding.evidence))
        phase = f"{finding.phase} · first seen {_fmt_time(finding.first_seen)}"
        inner.addLayout(self._detail_row("STATE", phase))
        return card

    def _make_evidence_row(self, row: EvidenceRow) -> QWidget:
        widget = QWidget()
        widget.setObjectName("evidenceRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        metric = QLabel(row.metric or "—")
        metric.setObjectName("diagField")
        metric.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(metric)
        statement = QLabel(row.statement)
        statement.setObjectName("findingReason")
        statement.setWordWrap(True)
        statement.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(statement, 1)
        return widget

    def _make_app_row(self, app: AppCorrelation) -> QWidget:
        widget = QWidget()
        widget.setObjectName("evidenceRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        name = QLabel(f"{app.label or app.package}")
        name.setObjectName("findingRule")
        name.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(name, 1)
        detail = QLabel(
            f"{app.package} · cpu {_fmt_pct(app.cpu_percent)} · "
            f"mem {_fmt_pct(app.memory_percent)} · procs {app.process_count or 0} · "
            f"{app.state or 'unknown'}"
        )
        detail.setObjectName("diagField")
        detail.setWordWrap(True)
        detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(detail, 2)
        return widget

    def _make_event_row(self, event: EventRow) -> QWidget:
        widget = QWidget()
        widget.setObjectName("evidenceRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        severity = QLabel(event.phase.upper())
        severity.setObjectName("findingSeverity")
        severity.setTextFormat(Qt.TextFormat.PlainText)
        level = {"recovered": "info", "active": "elevated", "started": "high"}.get(
            event.phase, "muted"
        )
        severity.setProperty("level", level)
        layout.addWidget(severity)
        title = QLabel(event.title)
        title.setObjectName("findingReason")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title, 1)
        return widget

    @staticmethod
    def _section(title: str) -> QLabel:
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

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

    @staticmethod
    def _add_empty(layout: QVBoxLayout, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("deviceEmptyTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()


class PerformanceSummaryWidget(QWidget):
    """Compact Performance Intelligence widget for the Intelligence page.

    Shows the overall state, a one-line metric summary and an active-finding
    count, with a "View Performance" button that opens the full page. It is a
    renderer of the same :class:`PerformanceViewState`; no analysis occurs.
    """

    #: The user asked to open the full Performance page.
    view_full_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("perfSummary")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        head = QHBoxLayout()
        self._state = QLabel()
        self._state.setObjectName("perfStateBadge")
        self._state.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self._state)
        self._score = QLabel()
        self._score.setObjectName("perfScoreBadge")
        self._score.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self._score)
        head.addStretch(1)
        button = QPushButton("View Performance")
        button.setObjectName("perfTimelineButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self.view_full_requested.emit)
        head.addWidget(button)
        layout.addLayout(head)

        self._metrics = QLabel()
        self._metrics.setObjectName("perfSummaryMetrics")
        self._metrics.setWordWrap(True)
        self._metrics.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._metrics)

        self._findings = QLabel()
        self._findings.setObjectName("muted")
        self._findings.setWordWrap(True)
        self._findings.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._findings)

    def refresh(self, state: PerformanceViewState, connected: bool) -> None:
        if not connected:
            self._state.setText("DISCONNECTED")
            self._state.setProperty("level", "muted")
            repolish(self._state)
            self._score.setText("")
            self._score.setProperty("level", "muted")
            repolish(self._score)
            self._metrics.setText("—")
            self._findings.setText("Connect a device to collect performance intelligence.")
            return
        level = _STATE_BADGE_LEVEL.get(state.overall_state, "info")
        self._state.setText(state.overall_state.replace("_", " "))
        self._state.setProperty("level", level)
        repolish(self._state)
        score = state.performance_score
        if score is not None:
            self._score.setText(f"Health {score.score}/100")
            slevel = "info" if score.score >= 70 else ("elevated" if score.score >= 40 else "high")
            self._score.setProperty("level", slevel)
            repolish(self._score)
        else:
            self._score.setText("")
            self._score.setProperty("level", "muted")
            repolish(self._score)
        parts = []
        for key in ("cpu", "memory", "storage", "battery"):
            view = state.metrics.get(key)
            if view is None or view.current is None:
                parts.append(f"{key.title()} —")
            else:
                parts.append(f"{key.title()} {view.current:.0f}% {view.condition[:4]}")
        self._metrics.setText("  ·  ".join(parts))
        count = len(state.findings)
        if count == 0:
            self._findings.setText("No active performance conditions.")
        else:
            self._findings.setText(
                f"{count} active condition{'s' if count != 1 else ''} under investigation."
            )


def _fmt_time(value: float | None) -> str:
    if value is None:
        return "—"
    try:
        from datetime import datetime

        return datetime.fromtimestamp(value).strftime("%H:%M:%S")
    except (ValueError, OSError):
        return "—"


__all__ = ["PerformancePage", "PerformanceSummaryWidget"]

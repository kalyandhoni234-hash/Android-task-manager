"""Investigation timeline dialog: unified, evidence-first event list.

Read-only viewer of the investigation timeline produced by the pure
``build_investigation_timeline`` aggregation — the same deterministic
ordering the incident report uses. Selecting an event shows its details
(title, severity, entity, timestamp, evidence references, related
entities). No device reads happen here; the data was already collected.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
)

from ..investigation.models import InvestigationEvent


def _fmt_timestamp(value) -> str:
    if value is None:
        return "Not recorded"
    try:
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (AttributeError, ValueError, OSError):
        return str(value)


class InvestigationDialog(QDialog):
    """The investigation timeline of the current session."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Investigation Timeline")
        self.resize(880, 560)

        self._title = QLabel("")
        self._title.setObjectName("incidentDialogTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)

        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._list)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(splitter, 1)

        self._events: tuple[InvestigationEvent, ...] = ()

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def show_timeline(self, events: tuple[InvestigationEvent, ...]) -> None:
        """Render the timeline; events are already deterministically ordered."""
        self._events = events
        self._title.setText(f"Investigation timeline — {len(events)} event(s)")
        self._list.clear()
        for event in events:
            entity = f" · {event.entity}" if event.entity else ""
            severity = f"[{event.severity}] " if event.severity else ""
            item = QListWidgetItem(
                f"{event.event_id}  {severity}{event.event_type}{entity}"
            )
            item.setData(Qt.ItemDataRole.UserRole, event)
            self._list.addItem(item)
        if events:
            self._list.setCurrentRow(0)

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self._detail.setPlainText("Select an event to see its details.")
            return
        event = current.data(Qt.ItemDataRole.UserRole)
        self._render_event(event)

    def _render_event(self, event: InvestigationEvent) -> None:
        refs = ", ".join(event.evidence_refs) if event.evidence_refs else "—"
        related = ", ".join(event.related_entities) if event.related_entities else "—"
        self._detail.setPlainText(
            "\n".join(
                [
                    f"Event: {event.event_id} ({event.event_type})",
                    f"Title: {event.title}",
                    f"Description: {event.description}",
                    f"Severity: {event.severity or 'Not recorded'}",
                    f"Timestamp: {_fmt_timestamp(event.timestamp)}",
                    f"Entity: {event.entity or '—'}",
                    f"Evidence references: {refs}",
                    f"Related entities: {related}",
                ]
            )
        )
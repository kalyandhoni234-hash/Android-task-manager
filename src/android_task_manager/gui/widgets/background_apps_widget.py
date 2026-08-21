"""Background user-apps widget: the Intelligence page's BACKGROUND USER APPS
section.

Renders the aggregated :class:`~android_task_manager.background.models.BackgroundAppsSnapshot`
as a human-first table (application label first, package name as secondary
technical detail) plus a detail panel for the selected application.

The widget is presentation-only: it never talks to ADB, never parses device
output and never dispatches commands. Selection emits ``detail_requested`` and
``action_requested`` signals the window routes through the existing v0.7 action
layer, so every capability gate (system-app protection, destructive-action
confirmation, invalid-package rejection) is preserved unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...action import ActionResult
from ...applications import AppDetails
from ...background.models import BackgroundAppEntry, BackgroundAppsSnapshot, BackgroundAppState
from .app_details_widget import AppDetailsWidget

_COLUMN_APP = 0
_COLUMN_PACKAGE = 1
_COLUMN_MEMORY = 2
_COLUMN_CPU = 3
_COLUMN_PROCESSES = 4
_COLUMN_STATE = 5
_COLUMN_LAST_SEEN = 6

_COLUMNS = ("APPLICATION", "PACKAGE", "MEMORY", "CPU", "PROCESSES", "STATE", "LAST SEEN")

_STATE_LABELS = {
    BackgroundAppState.FOREGROUND: "Foreground",
    BackgroundAppState.BACKGROUND: "Background",
    BackgroundAppState.UNKNOWN: "Unknown",
}

_AWAITING = "No device connected."
_EMPTY = "No user applications are currently running in the background."

_ACTIVITY_TEXT = {
    BackgroundAppState.FOREGROUND: "This application is currently in the foreground.",
    BackgroundAppState.BACKGROUND: "This application is currently running in the background.",
    BackgroundAppState.UNKNOWN: "Background activity could not be determined for this application.",
}


class _SortableItem(QTableWidgetItem):
    """Table cell that sorts by an explicit key, not by its rendered text."""

    def __init__(self, text: str, key: object) -> None:
        super().__init__(text)
        self._key = key

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _SortableItem):
            return super().__lt__(other)  # type: ignore[no-any-return]
        left, right = self._key, other._key
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return str(left).lower() < str(right).lower()


def _format_memory(entry: BackgroundAppEntry) -> str:
    """Render memory as MiB when known, else percent share, else N/A.

    ``memory_kb`` is an absolute estimate derived from the memory snapshot's
    total; falls back to the percent share when the total was unavailable;
    never invented when both are missing.
    """
    if entry.memory_kb is not None:
        return f"{entry.memory_kb // 1024} MB"
    if entry.memory_percent is not None:
        return f"{entry.memory_percent:.1f}%"
    return "N/A"


def _format_cpu(entry: BackgroundAppEntry) -> str:
    return "N/A" if entry.cpu_percent is None else f"{entry.cpu_percent:.1f}%"


def _format_last_seen(entry: BackgroundAppEntry) -> str:
    if entry.last_seen is None:
        return "—"
    return entry.last_seen.strftime("%H:%M:%S")


class BackgroundAppsWidget(QWidget):
    """The BACKGROUND USER APPS table + detail panel."""

    #: (package) the user selected a row; the window forwards it to the apps
    #: worker's detail read (off the GUI thread).
    detail_requested = Signal(str)

    #: (action, package) the user clicked an action button for the selected
    #: background application.
    action_requested = Signal(str, str)

    #: (package) the user asked to audit the selected app's permissions.
    permission_audit_requested = Signal(str)

    #: The user pressed Refresh (rebuild from the latest cached telemetry).
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondary")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        toolbar.addWidget(self._refresh_btn)
        self._filter = QLineEdit()
        self._filter.setObjectName("processFilter")
        self._filter.setPlaceholderText("Filter apps...")
        self._filter.setClearButtonEnabled(True)
        self._filter.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._filter.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter, 1)
        self._count = QLabel("")
        self._count.setObjectName("muted")
        toolbar.addWidget(self._count)
        layout.addLayout(toolbar)

        self._status = QLabel(_AWAITING)
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self._table.horizontalHeader()
        # APPLICATION (the human-readable primary identity) absorbs the slack;
        # every other column gets a fixed, readable width so package names and
        # numeric values stay legible without pointless horizontal scrolling.
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        for column in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(column, header.ResizeMode.Interactive)
        self._table.setColumnWidth(_COLUMN_PACKAGE, 210)
        self._table.setColumnWidth(_COLUMN_MEMORY, 92)
        self._table.setColumnWidth(_COLUMN_CPU, 72)
        self._table.setColumnWidth(_COLUMN_PROCESSES, 84)
        self._table.setColumnWidth(_COLUMN_STATE, 96)
        self._table.setColumnWidth(_COLUMN_LAST_SEEN, 96)
        header.setMinimumSectionSize(60)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table)

        # -- Detail panel -----------------------------------------------------
        self._detail = QFrame()
        self._detail.setObjectName("panel")
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(16, 14, 16, 16)
        detail_layout.setSpacing(8)

        self._detail_title = QLabel("")
        self._detail_title.setObjectName("sectionTitle")
        self._detail_title.setWordWrap(True)
        detail_layout.addWidget(self._detail_title)
        self._detail_subtitle = QLabel("")
        self._detail_subtitle.setObjectName("muted")
        self._detail_subtitle.setWordWrap(True)
        detail_layout.addWidget(self._detail_subtitle)

        runtime = QFrame()
        runtime.setObjectName("panel")
        runtime_layout = QVBoxLayout(runtime)
        runtime_layout.setContentsMargins(10, 8, 10, 8)
        runtime_layout.setSpacing(4)
        self._runtime_grid = QWidget()
        grid = QHBoxLayout(self._runtime_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        self._runtime_state = QLabel("")
        self._runtime_cpu = QLabel("")
        self._runtime_mem = QLabel("")
        self._runtime_procs = QLabel("")
        for widget in (self._runtime_state, self._runtime_mem, self._runtime_cpu, self._runtime_procs):
            widget.setObjectName("muted")
            widget.setWordWrap(True)
            grid.addWidget(widget)
        runtime_layout.addWidget(self._runtime_grid)
        self._runtime_pids = QLabel("")
        self._runtime_pids.setObjectName("muted")
        self._runtime_pids.setWordWrap(True)
        self._runtime_pids.setProperty("mono", True)
        runtime_layout.addWidget(self._runtime_pids)
        self._activity = QLabel("")
        self._activity.setObjectName("muted")
        self._activity.setWordWrap(True)
        runtime_layout.addWidget(self._activity)
        detail_layout.addWidget(runtime)

        # Embedded standard detail/actions panel (reuses the v0.7 action gate).
        self._details = AppDetailsWidget()
        self._details.action_requested.connect(self.action_requested.emit)
        self._details.permission_audit_requested.connect(self.permission_audit_requested.emit)
        detail_layout.addWidget(self._details)

        self._detail.hide()
        layout.addWidget(self._detail)

        self._entries: list[BackgroundAppEntry] = []
        self._filter_query = ""
        self._selected: str | None = None

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _on_filter_changed(self, text: str) -> None:
        self._filter_query = text.strip()
        self._rebuild_table()

    def _matches_filter(self, entry: BackgroundAppEntry) -> bool:
        query = self._filter_query.lower()
        if not query:
            return True
        name = (entry.label or entry.package_name).lower()
        return query in name or query in entry.package_name.lower()

    # ------------------------------------------------------------------
    # Snapshot rendering
    # ------------------------------------------------------------------

    def set_snapshot(self, snapshot: BackgroundAppsSnapshot | None) -> None:
        """Replace the table contents (filter applied)."""
        self._entries = list(snapshot.entries) if snapshot is not None else []
        if snapshot is None:
            self._status.setText(_AWAITING)
            self._status.setObjectName("muted")
        elif not self._entries:
            self._status.setText(_EMPTY)
            self._status.setObjectName("muted")
        else:
            self._status.setText("")
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        visible = [e for e in self._entries if self._matches_filter(e)]
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            name = entry.label or entry.package_name
            values = (
                _SortableItem(name, (entry.label or entry.package_name).lower()),
                _SortableItem(entry.package_name, entry.package_name.lower()),
                _SortableItem(_format_memory(entry), _memory_key(entry)),
                _SortableItem(_format_cpu(entry), entry.cpu_percent if entry.cpu_percent is not None else float("-inf")),
                _SortableItem(str(len(entry.pids)), len(entry.pids)),
                _SortableItem(_STATE_LABELS.get(entry.state, "Unknown"),
                              _STATE_LABELS.get(entry.state, "Unknown").lower()),
                _SortableItem(_format_last_seen(entry),
                              entry.last_seen.timestamp() if entry.last_seen is not None else float("-inf")),
            )
            for column, item in enumerate(values):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == _COLUMN_APP:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self._table.setItem(row, column, item)
        self._table.setSortingEnabled(True)
        self._count.setText(
            f"{len(visible)} / {len(self._entries)} background"
            if self._filter_query else f"{len(visible)} background apps"
        )

    # ------------------------------------------------------------------
    # Selection + detail
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        pkg = self._table.item(rows[0].row(), _COLUMN_PACKAGE)
        if pkg is None:
            return
        self._selected = pkg.text()
        self.detail_requested.emit(self._selected)

    def set_background_entry(self, entry: BackgroundAppEntry) -> None:
        """Populate the runtime block for the selected entry (no detail read)."""
        name = entry.label or entry.package_name
        self._detail_title.setText(name)
        self._detail_subtitle.setText(entry.package_name)
        self._runtime_state.setText(f"State: {_STATE_LABELS.get(entry.state, 'Unknown')}")
        self._runtime_mem.setText(f"Memory: {_format_memory(entry)}")
        self._runtime_cpu.setText(f"CPU: {_format_cpu(entry)}")
        self._runtime_procs.setText(f"Processes: {len(entry.pids)}")
        if entry.pids:
            self._runtime_pids.setText(f"PIDs: {', '.join(str(p) for p in entry.pids)}")
        else:
            self._runtime_pids.setText("PIDs: —")
        self._activity.setText(_ACTIVITY_TEXT.get(entry.state, ""))
        self._detail.show()

    def show_details(self, details: AppDetails) -> None:
        """Render the fetched AppDetails in the embedded action panel.

        Only rendered when it still matches the current selection; a stale
        detail from a previous selection is discarded.
        """
        if self._selected is not None and details.package_name != self._selected:
            return
        self._details.set_details(details)

    def show_details_failed(self, package: str, message: str) -> None:
        if self._selected is not None and package != self._selected:
            return
        self._details.show_details_failed(package, message)

    def clear(self) -> None:
        """Reset for a device disconnect (no stale data lingers)."""
        self._entries = []
        self._selected = None
        self._table.setRowCount(0)
        self._count.setText("")
        self._status.setText(_AWAITING)
        self._status.setObjectName("muted")
        self._detail.hide()
        self._details.clear()

    def set_actions_busy(self, busy: bool) -> None:
        """Forward the action busy lock to the embedded detail panel."""
        self._details.set_actions_busy(busy)

    def show_action_result(self, result: ActionResult) -> None:
        """Render the typed action outcome in the embedded panel."""
        self._details.show_action_result(result)


def _memory_key(entry: BackgroundAppEntry) -> float:
    if entry.memory_kb is not None:
        return float(entry.memory_kb)
    if entry.memory_percent is not None:
        return -entry.memory_percent  # percent sorts below absolute MiB values
    return float("-inf")

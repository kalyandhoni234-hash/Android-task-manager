"""Process widget: metric-bearing process table (PID/UID/CPU/MEM/STATE/NAME).

The table hides the process spawned by the monitor's own ``top -n 1`` sample
command — it is internal tooling, not a real app, and matching its exact
command identity is safe and precise (a bare ``top`` or ``top -n 2`` process
is never touched). The raw snapshot still contains it; only the presented
rows are filtered.

The table supports client-side filtering (name/PID, applied to the latest
snapshot only — no extra ADB traffic) and numeric-aware header sorting
(PID/UID/CPU/MEM sort by value, not by text). When the currently inspected
process disappears from the table (e.g. the filter hides it), the detail
panel is reset to the clean "gone" state so no stale action identity can
survive.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...baseline import ProcessRef
from ...network_investigation.models import NetworkInvestigationSnapshot
from ...process.inspector_models import ProcessInspectionSnapshot
from ...process.models import ProcessSnapshot
from . import panel_host
from .process_inspector_widget import ProcessInspectorWidget

_COLUMN_PID = 0
_COLUMN_UID = 1
_COLUMN_CPU = 2
_COLUMN_MEM = 3
_COLUMN_STATE = 4
_COLUMN_NAME = 5

_COLUMNS = ("PID", "UID", "CPU", "MEM", "STATE", "NAME")

#: Default presentation order: CPU descending (the established policy).
_DEFAULT_SORT_COLUMN = _COLUMN_CPU
_DEFAULT_SORT_ORDER = Qt.SortOrder.DescendingOrder

#: The exact command line of the monitoring ``top -n 1`` sample, as it
#: appears in ps/top NAME/ARGS. A ``toybox top -n 1`` variant is also
#: recognised; anything else (e.g. plain ``top``, ``top -n 2``) is untouched.
_MONITOR_COMMAND_RE = re.compile(r"^(?:toybox\s+)?top\s+-n\s+1$")

#: Cell badge text for rows matching a NEW drift event (identity-stable:
#: uid + name + classification, never PID).
_NEW_BADGE = "[NEW] "
#: Subtle row tint for badge rows, kept inside the existing dark palette.
_NEW_BACKGROUND = QColor("#2f3d35")
#: Tooltip explaining the badge (never a verdict, just the drift fact).
_NEW_TOOLTIP = "New process since the baseline was saved."


def _is_monitor_process(process) -> bool:
    """True when *process* is the monitor's own ``top -n 1`` helper."""
    return bool(_MONITOR_COMMAND_RE.fullmatch((process.name or "").strip()))


class _SortableItem(QTableWidgetItem):
    """A table cell that sorts by an explicit key, not by its text.

    Numeric keys make PID/UID/CPU/MEM order numerically (100 > 20 > 3);
    text keys make NAME/STATE order case-insensitively. ``None`` metrics
    use a key of -inf so "N/A" rows sink below real values.
    """

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


class ProcessWidget(QWidget):
    """Renders a ProcessSnapshot with filtering and numeric-aware sorting.

    The snapshot already contains only top-reported (metric-bearing)
    processes — ps-only rows never reach this table — and the monitor's own
    ``top -n 1`` process is excluded from presentation.

    Selecting a row emits :attr:`inspection_requested` with the PID so the
    dashboard can run an on-demand /proc inspection off the GUI thread; the
    result (or a "process gone" state) is rendered in the embedded detail
    panel below the table.
    """

    #: (pid) the user selected a single table row and wants it inspected.
    inspection_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "PROCESSES")

        self._all_processes: list = []
        self._filter_query = ""
        self._sort_column = _DEFAULT_SORT_COLUMN
        self._sort_order = _DEFAULT_SORT_ORDER
        self._inspected_pid: int | None = None
        #: ProcessRef identities NEW since the baseline; their rows get the
        #: badge. Empty when no baseline/drift state exists.
        self._new_process_refs: frozenset[ProcessRef] = frozenset()

        self._filter = QLineEdit()
        self._filter.setObjectName("processFilter")
        self._filter.setPlaceholderText("Filter processes...")
        self._filter.setClearButtonEnabled(True)
        self._filter.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._filter.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._filter)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COLUMN_NAME, QHeaderView.ResizeMode.Stretch)
        self._table.setSortingEnabled(True)
        self._table.sortItems(_DEFAULT_SORT_COLUMN, _DEFAULT_SORT_ORDER)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        layout.addWidget(self._table)

        self._inspector = ProcessInspectorWidget()
        self._inspector.closed.connect(self._inspector.hide)
        layout.addWidget(self._inspector)
        self.set_snapshot(ProcessSnapshot(timestamp=0.0))

    @property
    def inspector(self) -> ProcessInspectorWidget:
        """The embedded detail/actions panel."""
        return self._inspector

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def set_filter_text(self, text: str) -> None:
        """Set the filter box text (also drives the live box)."""
        self._filter.setText(text)

    def filter_text(self) -> str:
        """The current filter query."""
        return self._filter_query

    def _on_filter_changed(self, text: str) -> None:
        self._filter_query = text.strip()
        self._rebuild()

    def _matches_filter(self, process) -> bool:
        query = self._filter_query
        if not query:
            return True
        needle = query.lower()
        if needle in (process.name or "").lower():
            return True
        return str(process.pid).startswith(needle)

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        self._sort_column = column
        self._sort_order = order

    # ------------------------------------------------------------------
    # Snapshot rendering
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        item = self._table.item(rows[0].row(), _COLUMN_PID)
        if item is None or not item.text().isdigit():
            return
        self.inspection_requested.emit(int(item.text()))

    def show_inspection(
        self,
        snapshot: ProcessInspectionSnapshot,
        network_data: NetworkInvestigationSnapshot | None = None,
    ) -> None:
        """Present a completed inspection below the table."""
        self._inspected_pid = snapshot.pid
        self._inspector.set_snapshot(snapshot, network_data)

    def show_inspection_gone(self, pid: int, message: str | None = None) -> None:
        """Present the clean "process no longer available" state."""
        self._inspected_pid = None
        self._inspector.set_gone(pid, message)

    def clear_inspection(self) -> None:
        """Hide the detail panel (e.g. when the dashboard is closing)."""
        self._inspected_pid = None
        self._inspector.hide()

    def set_snapshot(self, snapshot: ProcessSnapshot) -> None:
        """Replace the table contents (filter + user sort applied)."""
        self._all_processes = [
            p for p in snapshot.processes if not _is_monitor_process(p)
        ]
        self._rebuild()

    def set_new_process_refs(self, refs: frozenset[ProcessRef]) -> None:
        """Set the NEW identities to badge; an empty set clears all badges.

        The badge is a row highlight on the existing table — the table is
        not replaced by (or re-populated from) a separate drift view.
        """
        self._new_process_refs = frozenset(refs)
        self._rebuild()

    def _rebuild(self) -> None:
        visible = [p for p in self._all_processes if self._matches_filter(p)]
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(visible))
        for row_index, process in enumerate(visible):
            is_new = (
                ProcessRef(
                    uid=process.uid,
                    process_name=process.name,
                    classification=process.category,
                )
                in self._new_process_refs
            )
            cpu = process.cpu_percent
            mem = process.memory_percent
            uid = process.uid
            values = (
                _SortableItem(str(process.pid), process.pid),
                _SortableItem(
                    "N/A" if uid is None else str(uid),
                    uid if uid is not None else float("-inf"),
                ),
                _SortableItem(
                    "N/A" if cpu is None else f"{cpu:.1f}%",
                    cpu if cpu is not None else float("-inf"),
                ),
                _SortableItem(
                    "N/A" if mem is None else f"{mem:.1f}%",
                    mem if mem is not None else float("-inf"),
                ),
                _SortableItem(process.state or "-", (process.state or "-").lower()),
                _SortableItem(
                    (_NEW_BADGE + process.name) if is_new else process.name,
                    (process.name or "").lower(),
                ),
            )
            for column, item in enumerate(values):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if is_new:
                    item.setBackground(QBrush(_NEW_BACKGROUND))
                    item.setToolTip(_NEW_TOOLTIP)
                self._table.setItem(row_index, column, item)
        self._table.setSortingEnabled(True)
        self._table.sortItems(self._sort_column, self._sort_order)
        self._handle_filtered_inspection(visible)

    def _handle_filtered_inspection(self, visible: list) -> None:
        """Reset the inspector when the inspected process was filtered out.

        A process that is no longer visible cannot be the selected process;
        carrying its package identity or action result would be stale.
        """
        pid = self._inspected_pid
        if pid is None:
            return
        if any(p.pid == pid for p in visible):
            return
        self.show_inspection_gone(pid, "removed from the table by the current filter")

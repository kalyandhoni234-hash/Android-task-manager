"""Process widget: metric-bearing process table (PID/CPU/MEM/STATE/NAME).

The table hides the process spawned by the monitor's own ``top -n 1`` sample
command — it is internal tooling, not a real app, and matching its exact
command identity is safe and precise (a bare ``top`` or ``top -n 2`` process
is never touched). The raw snapshot still contains it; only the presented
rows are filtered.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ...process.inspector_models import ProcessInspectionSnapshot
from ...process.models import ProcessSnapshot
from . import panel_host
from .process_inspector_widget import ProcessInspectorWidget

_COLUMNS = ("PID", "CPU", "MEM", "STATE", "NAME")

#: The exact command line of the monitoring ``top -n 1`` sample, as it
#: appears in ps/top NAME/ARGS. A ``toybox top -n 1`` variant is also
#: recognised; anything else (e.g. plain ``top``, ``top -n 2``) is untouched.
_MONITOR_COMMAND_RE = re.compile(r"^(?:toybox\s+)?top\s+-n\s+1$")


def _cpu_sort_key(process) -> float:
    return process.cpu_percent if process.cpu_percent is not None else float("-inf")


def _is_monitor_process(process) -> bool:
    """True when *process* is the monitor's own ``top -n 1`` helper."""
    return bool(_MONITOR_COMMAND_RE.fullmatch((process.name or "").strip()))


class ProcessWidget(QWidget):
    """Renders a ProcessSnapshot, sorted by CPU descending.

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
        header.setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._table)

        self._inspector = ProcessInspectorWidget()
        self._inspector.closed.connect(self._inspector.hide)
        layout.addWidget(self._inspector)
        self.set_snapshot(ProcessSnapshot(timestamp=0.0))

    @property
    def inspector(self) -> ProcessInspectorWidget:
        """The embedded detail/actions panel."""
        return self._inspector

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        item = self._table.item(rows[0].row(), 0)
        if item is None or not item.text().isdigit():
            return
        self.inspection_requested.emit(int(item.text()))

    def show_inspection(self, snapshot: ProcessInspectionSnapshot) -> None:
        """Present a completed inspection below the table."""
        self._inspector.set_snapshot(snapshot)

    def show_inspection_gone(self, pid: int, message: str | None = None) -> None:
        """Present the clean "process no longer available" state."""
        self._inspector.set_gone(pid, message)

    def clear_inspection(self) -> None:
        """Hide the detail panel (e.g. when the dashboard is closing)."""
        self._inspector.hide()

    def set_snapshot(self, snapshot: ProcessSnapshot) -> None:
        """Replace the table contents, keeping CPU-descending order."""
        rows = sorted(
            (p for p in snapshot.processes if not _is_monitor_process(p)),
            key=_cpu_sort_key,
            reverse=True,
        )
        self._table.setRowCount(len(rows))
        for row_index, process in enumerate(rows):
            values = (
                str(process.pid),
                "N/A" if process.cpu_percent is None else f"{process.cpu_percent:.1f}%",
                "N/A" if process.memory_percent is None else f"{process.memory_percent:.1f}%",
                process.state or "-",
                process.name,
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_index, column, item)

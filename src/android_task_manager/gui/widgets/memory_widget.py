"""Memory widget: available memory as the primary metric, then the breakdown.

The underlying model uses ``available_kb`` (Linux ``MemAvailable``) as the
pressure-oriented baseline, so the GUI leads with Available; the pressure bar
and ``% used`` figure are clearly labeled as used share of total, never as a
claim about ``MemFree``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ...memory.models import MemorySnapshot
from ...terminal.renderer import format_kib
from ..thresholds import MetricLevel, apply_metric_level, classify_used_memory
from . import panel_host
from .memory_history import MemoryHistoryWidget


class MemoryWidget(QWidget):
    """Leads with available memory, shows the used-pressure bar and a breakdown."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "MEMORY")

        self._available = QLabel("N/A")
        self._available.setObjectName("valueBig")
        self._available.setProperty("mono", True)
        self._available.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self._available_caption = QLabel("Available")
        self._available_caption.setObjectName("muted")
        self._available_caption.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(12)

        self._used = QLabel("0% used")
        self._used.setObjectName("caption")
        self._used.setProperty("mono", True)
        self._used.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        summary = QVBoxLayout()
        summary.setSpacing(2)
        summary.addWidget(self._available)
        summary.addWidget(self._available_caption)
        summary.addWidget(self._bar)
        summary.addWidget(self._used)

        self._rows: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for index, field in enumerate(("Total", "Free", "Cached", "Buffers")):
            label = QLabel(field)
            label.setObjectName("caption")
            value = QLabel("N/A")
            value.setObjectName("muted")
            value.setProperty("mono", True)
            grid.addWidget(label, index, 0)
            grid.addWidget(value, index, 1)
            self._rows[field] = value
        grid.setColumnStretch(1, 1)

        combo = QVBoxLayout()
        combo.addLayout(summary)
        combo.addSpacing(6)
        combo.addLayout(grid)
        combo.addStretch(1)

        # The history graph sits beside the summary block, mirroring CPU.
        self._history = MemoryHistoryWidget()
        self._history.setMinimumWidth(120)

        main = QHBoxLayout()
        main.setSpacing(14)
        main.addLayout(combo)
        main.addWidget(self._history, 1)
        layout.addLayout(main)

        self.set_snapshot(None)

    def set_snapshot(self, snapshot: MemorySnapshot | None) -> None:
        """Refresh the primary Available figure and the breakdown."""
        if snapshot is None:
            self._available.setText("N/A")
            self._bar.setValue(0)
            self._used.setText("0% used")
            apply_metric_level(self._available, MetricLevel.NORMAL)
            apply_metric_level(self._used, MetricLevel.NORMAL)
            for value in self._rows.values():
                value.setText("N/A")
            self._history.add_sample(None)
            return

        total = snapshot.total_kb
        used = max(0, total - snapshot.available_kb)
        percent = 0.0 if total <= 0 else (used / total * 100)
        self._available.setText(format_kib(snapshot.available_kb))
        self._bar.setValue(int(round(percent)))
        self._used.setText(f"{percent:.0f}% used")
        apply_metric_level(self._used, classify_used_memory(percent))
        self._rows["Total"].setText(format_kib(total))
        self._rows["Free"].setText(format_kib(snapshot.free_kb))
        self._rows["Cached"].setText(format_kib(snapshot.cached_kb))
        self._rows["Buffers"].setText(format_kib(snapshot.buffers_kb))
        available_percent = 0.0 if total <= 0 else (snapshot.available_kb / total * 100)
        self._history.add_sample(available_percent)

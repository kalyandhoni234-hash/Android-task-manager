"""CPU widget: overall utilization, live history graph, and per-core bars."""

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

from ...cpu.models import CPUCore, CPUSnapshot
from . import panel_host
from .cpu_history import CPUHistoryWidget


class CPUWidget(QWidget):
    """Displays aggregate utilization, a recent history plot, and one bar per core."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "CPU")

        self._overall = QLabel("N/A")
        self._overall.setObjectName("valueBig")
        self._overall.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        self._overall_caption = QLabel("Overall CPU")
        self._overall_caption.setObjectName("muted")
        self._overall_caption.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )

        overall = QVBoxLayout()
        overall.setSpacing(0)
        overall.addWidget(self._overall)
        overall.addWidget(self._overall_caption)

        # The history graph occupies the space to the right of the headline
        # number and fills the vertical room that used to be empty.
        self._history = CPUHistoryWidget()
        self._history.setMinimumHeight(84)

        head = QHBoxLayout()
        head.setSpacing(14)
        head.addLayout(overall)
        head.addWidget(self._history, 1)
        layout.addLayout(head)

        self._core_rows: list[tuple[QLabel, QProgressBar, QLabel, QLabel]] = []
        table = QGridLayout()
        table.setHorizontalSpacing(10)
        table.setVerticalSpacing(4)
        self._table = table
        layout.addLayout(table, 1)

        self.set_snapshot(CPUSnapshot(
            timestamp=0.0,
            aggregate_utilization_percent=None,
            cores=[CPUCore(core_id=i, utilization_percent=None, frequency_khz=None, frequency_available=False) for i in range(0)],
        ))

    def set_snapshot(self, snapshot: CPUSnapshot) -> None:
        """Refresh the headline, history, and per-core bars from one snapshot."""
        aggregate = (
            "N/A"
            if snapshot.aggregate_utilization_percent is None
            else f"{snapshot.aggregate_utilization_percent:.1f}%"
        )
        self._overall.setText(aggregate)
        self._history.add_sample(snapshot.aggregate_utilization_percent)

        # Rebuild the grid row by row.
        self._core_rows.clear()
        self._clear(self._table)
        for column_index, core in enumerate(snapshot.cores):
            label = QLabel(f"Core {core.core_id}")
            label.setObjectName("muted")

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(12)
            bar.setFormat("")
            bar.setValue(int(round(core.utilization_percent or 0)))

            pct = QLabel(
                "N/A" if core.utilization_percent is None else f"{core.utilization_percent:.1f}%"
            )
            pct.setObjectName("caption")

            freq = QLabel(_frequency(core))
            freq.setObjectName("muted")

            self._table.addWidget(label, 0, column_index)
            self._table.addWidget(bar, 1, column_index)
            self._table.addWidget(pct, 2, column_index)
            self._table.addWidget(freq, 3, column_index)
            self._core_rows.append((label, bar, pct, freq))

    @staticmethod
    def _clear(table: QGridLayout) -> None:
        while table.count():
            item = table.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


def _frequency(core) -> str:
    if core.frequency_khz is None:
        return "N/A"
    if core.frequency_khz >= 1_000_000:
        return f"{core.frequency_khz / 1_000_000:.2f} GHz"
    return f"{core.frequency_khz / 1_000:.0f} MHz"

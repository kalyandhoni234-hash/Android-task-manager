"""Memory history graph: recent Available memory (share of total).

Tracks the same pressure-oriented baseline the widget leads with
(``MemAvailable``), shown as a percentage of total so the fixed 0-100 scale
matches the CPU plot. ``None`` samples (no snapshot yet) are skipped and
never drawn as a fabricated drop.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .history_base import HistoryPlotWidget


class MemoryHistoryWidget(QWidget):
    """Bounded sliding window of recent Available-memory percentages."""

    def __init__(self, max_samples: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = HistoryPlotWidget(
            caption="recent available memory",
            colors=[QColor("#3d9be9")],
            max_samples=max_samples,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)
        self.setMinimumHeight(self._plot.minimumHeight())

    @property
    def samples(self) -> list[float]:
        """Copy of the retained history (oldest first)."""
        return self._plot.samples(0)

    def add_sample(self, value: float | None) -> None:
        """Append one Available-percent sample (``None`` is skipped)."""
        self._plot.add_sample(0, value)
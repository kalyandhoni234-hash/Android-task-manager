"""Battery history graph: recent level percentage.

Battery level changes slowly (the monitor samples it on its own 15 s
cadence), so the window stays modest and the graph conveys direction and
charge events rather than high-frequency detail. ``None`` samples are
skipped; the fixed 0-100 scale matches the level bar.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .history_base import HistoryPlotWidget


class BatteryHistoryWidget(QWidget):
    """Bounded sliding window of recent battery level percentages."""

    def __init__(self, max_samples: int = 24, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = HistoryPlotWidget(
            caption="recent battery level",
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
        """Append one level sample (``None`` is skipped)."""
        self._plot.add_sample(0, value)
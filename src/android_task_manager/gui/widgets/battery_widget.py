"""Battery widget: level, status, health, level bar, and a compact readout."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ...battery.models import BatterySnapshot
from ..thresholds import MetricLevel, apply_metric_level, classify_temperature
from . import panel_host
from .battery_history import BatteryHistoryWidget


class BatteryWidget(QWidget):
    """Displays a normalized BatterySnapshot in a compact layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "BATTERY")

        self._level = QLabel("N/A")
        self._level.setObjectName("valueBig")
        self._level.setProperty("mono", True)

        self._status = QLabel()
        self._status.setObjectName("statusConnected")
        self._health = QLabel()
        self._health.setObjectName("muted")

        head = QHBoxLayout()
        head.setSpacing(18)
        head.addWidget(self._level)
        head.addStretch(1)
        head.addWidget(self._status)
        head.addWidget(self._health)
        head.addStretch(2)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(10)

        # Level history under the bar: modest window, direction over detail.
        self._history = BatteryHistoryWidget()
        self._history.setMinimumHeight(56)

        self._fields: dict[str, QLabel] = {}
        fields_row = QHBoxLayout()
        fields_row.setSpacing(18)
        for field in ("Temperature", "Voltage", "Technology", "Power"):
            label = QLabel(field)
            label.setObjectName("muted")
            value = QLabel("N/A")
            value.setObjectName("caption")
            value.setProperty("mono", True)
            fields_row.addWidget(label)
            fields_row.addWidget(value)
            self._fields[field] = value
        fields_row.addStretch(1)

        layout.addLayout(head)
        layout.addWidget(self._bar)
        layout.addWidget(self._history)
        layout.addLayout(fields_row)
        layout.addStretch(1)

        self.set_snapshot(None)

    def set_snapshot(self, snapshot: BatterySnapshot | None) -> None:
        """Refresh every displayed value from one normalized snapshot."""
        if snapshot is None:
            self._level.setText("N/A")
            self._status.setText("Unknown")
            self._health.setText("")
            self._bar.setValue(0)
            for value in self._fields.values():
                value.setText("N/A")
            apply_metric_level(self._fields["Temperature"], MetricLevel.NORMAL)
            self._history.add_sample(None)
            return

        level = (
            "N/A"
            if snapshot.level_percent is None
            else f"{snapshot.level_percent:.0f}%"
        )
        temperature = (
            "N/A"
            if snapshot.temperature_c is None
            else f"{snapshot.temperature_c:.1f} \u00b0C"
        )
        voltage = (
            "N/A" if snapshot.voltage_mv is None else f"{snapshot.voltage_mv / 1000:.3f} V"
        )
        self._level.setText(level)
        self._status.setText(snapshot.status.label if snapshot.status else "Unknown")
        self._health.setText(snapshot.health.label if snapshot.health else "Unknown")
        self._bar.setValue(int(round(snapshot.level_percent or 0)))
        self._history.add_sample(snapshot.level_percent)
        self._fields["Temperature"].setText(temperature)
        apply_metric_level(
            self._fields["Temperature"], classify_temperature(snapshot.temperature_c)
        )
        self._fields["Voltage"].setText(voltage)
        self._fields["Technology"].setText(snapshot.technology or "Unknown")
        self._fields["Power"].setText(_power_sources(snapshot))


def _power_sources(snapshot: BatterySnapshot) -> str:
    sources = []
    if snapshot.ac_powered is True:
        sources.append("AC")
    if snapshot.usb_powered is True:
        sources.append("USB")
    if snapshot.wireless_powered is True:
        sources.append("Wireless")
    return ", ".join(sources) if sources else "None"

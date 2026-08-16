"""Device page: identity, specifications and status of the connected device.

Consumes only structured data: a ``DeviceInformation`` snapshot (collected
once per connection session by ``DeviceInfoCollector``) plus the existing
live battery/memory/CPU snapshots already flowing through the monitor.
This widget never runs ADB commands and never parses device output.

Facts-first rules:

- Missing values render as ``N/A``; a whole category with no data collapses
  to one concise "unavailable" line instead of a grid of blanks.
- No values are ever guessed, inferred from the model name, or hardcoded.
- Long values (e.g. build fingerprint) are elided on screen, with the full
  value kept in the tooltip.
- When no device is connected the page shows a clear empty state — stale
  values from a previous device are never left visible.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation, StorageInfo
from ..memory.models import MemorySnapshot
from ..terminal.renderer import format_kib
from .monitor import ConnectionState
from .widgets import panel
from .widgets.device_widget import DeviceWidget

#: Every category card: (field key, caption) rendered from a value getter.
_CARD_SPECS: dict[str, list[tuple[str, str]]] = {
    "BASIC INFORMATION": [
        ("manufacturer", "Manufacturer"),
        ("brand", "Brand"),
        ("model", "Model"),
        ("device", "Device"),
        ("product", "Product"),
        ("board", "Board"),
        ("hardware", "Hardware"),
        ("soc", "SoC"),
    ],
    "ANDROID / SOFTWARE": [
        ("android_version", "Android version"),
        ("api_level", "API level"),
        ("security_patch", "Security patch"),
        ("build_id", "Build ID"),
        ("build_number", "Build number"),
        ("kernel", "Kernel"),
        ("bootloader", "Bootloader"),
        ("baseband", "Baseband"),
        ("fingerprint", "Build fingerprint"),
    ],
    "CPU / HARDWARE": [
        ("processor", "Processor"),
        ("architecture", "Architecture"),
        ("cores", "Cores"),
        ("max_frequency", "Max frequency"),
        ("load", "Current load"),
    ],
    "BATTERY": [
        ("level", "Level"),
        ("status", "Status"),
        ("health", "Health"),
        ("temperature", "Temperature"),
        ("voltage", "Voltage"),
        ("technology", "Technology"),
    ],
    "MEMORY": [
        ("ram_total", "Total"),
        ("ram_available", "Available"),
        ("ram_used", "Used"),
    ],
    "STORAGE": [
        ("storage_total", "Total"),
        ("storage_used", "Used"),
        ("storage_free", "Free"),
    ],
    "DISPLAY": [
        ("resolution", "Resolution"),
        ("density", "Density"),
        ("refresh_rate", "Refresh rate"),
        ("orientation", "Orientation"),
    ],
    "IDENTIFIERS": [
        ("android_id", "Android ID"),
        ("wifi_mac", "Wi-Fi MAC"),
        ("bluetooth_mac", "Bluetooth MAC"),
    ],
}

_NA = "N/A"
_NA_CATEGORY = f"{_NA} — unavailable on this device"


class DevicePage(QWidget):
    """The DEVICE navigation destination: summary + fact cards."""

    def __init__(
        self,
        device_widget: DeviceWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._device = device_widget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Device")
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        subtitle = QLabel("Identity and specifications of the connected device")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(subtitle)

        layout.addWidget(self._device)

        self._summary_line = QLabel("")
        self._summary_line.setObjectName("muted")
        self._summary_line.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._summary_line)

        self._cards: dict[str, QFrame] = {}
        self._values: dict[str, dict[str, QLabel]] = {}
        self._na: dict[str, QLabel] = {}
        self._storage_bar: QProgressBar | None = None

        grid = QGridLayout()
        grid.setSpacing(10)
        order = (
            "BASIC INFORMATION",
            "ANDROID / SOFTWARE",
            "CPU / HARDWARE",
            "BATTERY",
            "MEMORY",
            "STORAGE",
            "DISPLAY",
            "IDENTIFIERS",
        )
        for index, card_name in enumerate(order):
            card, values, na = self._make_card(card_name)
            self._cards[card_name] = card
            self._values[card_name] = values
            self._na[card_name] = na
            grid.addWidget(card, index // 2, index % 2)
            grid.setColumnStretch(index % 2, 1)
        layout.addLayout(grid)

        note = QLabel(
            "\u24d8 Values are retrieved from the connected Android device "
            "and may not be available on all devices."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(note)

        self._empty = QLabel(
            "NO DEVICE CONNECTED\n\n"
            "Connect an Android device through ADB to view device information."
        )
        self._empty.setObjectName("deviceEmptyTitle")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._empty)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    # State entry (GUI thread; MainWindow calls this)
    # ------------------------------------------------------------------

    def refresh(
        self,
        info: DeviceInformation | None,
        battery: BatterySnapshot | None,
        memory: MemorySnapshot | None,
        cpu: CPUSnapshot | None,
        state: ConnectionState | None,
    ) -> None:
        """Re-render the page from one structured state bundle."""
        connected = state is ConnectionState.CONNECTED
        self._empty.setVisible(not connected)
        for card_name in self._values:
            self._cards[card_name].setVisible(connected)
        self._summary_line.setVisible(connected)
        if not connected:
            self._reset_values()
            return
        self._render_summary(info)
        values: dict[str, str] = {}
        values.update(_info_values(info))
        values.update(_live_values(battery, memory, cpu))
        for card_name, spec in _CARD_SPECS.items():
            self._render_card(card_name, spec, values)

    def _reset_values(self) -> None:
        """Clear every value label so nothing stale survives a disconnect."""
        for card_name, spec in _CARD_SPECS.items():
            for key, _caption in spec:
                label = self._values[card_name][key]
                label.setText(_NA)
                label.setToolTip("")
            self._na[card_name].setVisible(True)
        if self._storage_bar is not None:
            self._storage_bar.setValue(0)

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_summary(self, info: DeviceInformation | None) -> None:
        parts: list[str] = []
        if info is not None:
            if info.api_level:
                parts.append(f"API {info.api_level}")
            if info.manufacturer:
                parts.append(f"Manufacturer {info.manufacturer}")
            if info.brand:
                parts.append(f"Brand {info.brand}")
        self._summary_line.setText(" · ".join(parts))

    def _render_card(
        self,
        card_name: str,
        spec: list[tuple[str, str]],
        values: dict[str, str],
    ) -> None:
        present = sum(1 for key, _caption in spec if key in values)
        na_label = self._na[card_name]
        for key, _caption in spec:
            label = self._values[card_name][key]
            label.setVisible(present > 0)
            label.setText(values.get(key, _NA))
            if key == "fingerprint":
                label.setToolTip(values.get("fingerprint_full") or None)
        na_label.setVisible(present == 0)
        if card_name == "STORAGE" and self._storage_bar is not None:
            self._storage_bar.setVisible(present > 0)
            storage = values.get("storage_percent")
            self._storage_bar.setValue(0 if storage is None else int(round(storage)))

    def _make_card(self, title: str) -> tuple[QFrame, dict[str, QLabel], QLabel]:
        card, layout = panel(title)
        values: dict[str, QLabel] = {}
        for key, caption in _CARD_SPECS[title]:
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(caption)
            label.setObjectName("muted")
            label.setTextFormat(Qt.TextFormat.PlainText)
            value = QLabel(_NA)
            value.setObjectName("caption")
            value.setProperty("mono", True)
            value.setWordWrap(True)
            value.setTextFormat(Qt.TextFormat.PlainText)
            row.addWidget(label)
            row.addWidget(value, 1)
            layout.addLayout(row)
            values[key] = value
        if title == "STORAGE":
            self._storage_bar = QProgressBar()
            self._storage_bar.setRange(0, 100)
            self._storage_bar.setFixedHeight(10)
            layout.addWidget(self._storage_bar)
        na = QLabel(_NA_CATEGORY)
        na.setObjectName("muted")
        na.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(na)
        layout.addStretch(1)
        return card, values, na


# ---------------------------------------------------------------------------
# Value formatting (presentation only — never fabricates)
# ---------------------------------------------------------------------------


def _info_values(info: DeviceInformation | None) -> dict[str, str]:
    if info is None:
        return {}
    values: dict[str, str] = {}
    for key in (
        "manufacturer",
        "brand",
        "model",
        "device",
        "product",
        "board",
        "hardware",
        "soc",
        "processor",
        "architecture",
        "android_version",
        "api_level",
        "security_patch",
        "build_id",
        "build_number",
        "kernel",
        "bootloader",
        "baseband",
        "orientation",
    ):
        value = getattr(info, key)
        if value:
            values[key] = value
    if info.build_fingerprint:
        values["fingerprint"] = _elide(info.build_fingerprint, 52)
        values["fingerprint_full"] = info.build_fingerprint
    if info.max_frequency_khz:
        values["max_frequency"] = _format_frequency(info.max_frequency_khz)
    if info.resolution:
        values["resolution"] = info.resolution.replace("x", " \u00d7 ")
    if info.density_dpi:
        values["density"] = f"{info.density_dpi} dpi"
    if info.refresh_rate_hz:
        values["refresh_rate"] = f"{info.refresh_rate_hz:g} Hz"
    if info.storage is not None:
        values.update(_storage_values(info.storage))
    if info.android_id:
        values["android_id"] = info.android_id
    if info.wifi_mac:
        values["wifi_mac"] = info.wifi_mac
    if info.bluetooth_mac:
        values["bluetooth_mac"] = info.bluetooth_mac
    return values


def _live_values(
    battery: BatterySnapshot | None,
    memory: MemorySnapshot | None,
    cpu: CPUSnapshot | None,
) -> dict[str, str]:
    values: dict[str, str] = {}
    if battery is not None:
        if battery.level_percent is not None:
            values["level"] = f"{battery.level_percent:.0f}%"
        if battery.status is not None:
            values["status"] = battery.status.label
        if battery.health is not None:
            values["health"] = battery.health.label
        if battery.temperature_c is not None:
            values["temperature"] = f"{battery.temperature_c:.1f} \u00b0C"
        if battery.voltage_mv is not None:
            values["voltage"] = f"{battery.voltage_mv / 1000:.3f} V"
        if battery.technology:
            values["technology"] = battery.technology
    if memory is not None:
        values["ram_total"] = format_kib(memory.total_kb)
        values["ram_available"] = format_kib(memory.available_kb)
        values["ram_used"] = format_kib(memory.used_kb)
    if cpu is not None:
        if cpu.cores:
            values["cores"] = str(len(cpu.cores))
        if cpu.aggregate_utilization_percent is not None:
            values["load"] = f"{cpu.aggregate_utilization_percent:.1f}%"
    return values


def _storage_values(storage: StorageInfo) -> dict[str, str]:
    percent = storage.used_percent
    used_text = f"{format_kib(storage.used_kb)}"
    if percent is not None:
        used_text += f" ({percent:.0f}%)"
    values = {
        "storage_total": format_kib(storage.total_kb),
        "storage_used": used_text,
        "storage_free": format_kib(storage.available_kb),
    }
    if percent is not None:
        values["storage_percent"] = percent
    return values


def _format_frequency(khz: int) -> str:
    if khz >= 1_000_000:
        return f"{khz / 1_000_000:.2f} GHz"
    return f"{khz / 1000:.0f} MHz"


def _elide(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "\u2026"
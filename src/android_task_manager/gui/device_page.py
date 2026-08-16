"""Device page: identity, specifications and status of the connected device.

Consumes only structured data: a ``DeviceInformation`` snapshot (collected
once per connection session by ``DeviceInfoCollector``) plus the existing
live battery/memory/CPU snapshots already flowing through the monitor.
This widget never runs ADB commands and never parses device output.

Facts-first rules:

- Missing values render as ``Unknown``; a whole category with no data
  collapses to one concise "not available" line instead of a grid of
  blanks. ``None`` / ``N/A`` / ``null`` never reach the user-visible UI.
- Security facts are displayed as evidence, never as verdicts: an unknown
  SELinux mode is NOT "Disabled", unknown root evidence is NOT "Not
  rooted", and an unknown verified-boot state is NOT "Secure". No security
  score is computed or shown anywhere.
- Values whose backend semantics are intentionally unknown (e.g. the raw
  battery design capacity) are shown verbatim with a ``(reported)`` note —
  the GUI never invents unit conversions the backend did not claim.
- No values are ever guessed, inferred from the model name, or hardcoded.
- Long values (e.g. build fingerprint) are elided on screen, with the full
  value kept in the tooltip.
- When no device is connected the page shows a clear empty state — stale
  values from a previous device are never left visible.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..battery.models import BatterySnapshot, BatteryStatus
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation, StorageInfo
from ..diagnostics.models import (
    DiagnosticCategory,
    DiagnosticReport,
    DiagnosticSeverity,
)
from ..memory.models import MemorySnapshot
from ..terminal.renderer import format_kib
from .monitor import ConnectionState
from .styles import repolish
from .widgets import panel
from .widgets.device_widget import DeviceWidget

#: Every category card: (field key, caption) rendered from a value getter.
#: ``_CARD_ORDER`` (not this dict) defines the visual hierarchy.
_CARD_SPECS: dict[str, list[tuple[str, str]]] = {
    "DEVICE": [
        ("model", "Model"),
        ("manufacturer", "Manufacturer"),
        ("brand", "Brand"),
        ("device", "Device"),
        ("product", "Product"),
        ("board", "Board"),
        ("hardware", "Hardware"),
        ("soc", "SoC"),
    ],
    "SYSTEM / ANDROID": [
        ("android_version", "Android version"),
        ("api_level", "API level"),
        ("build_id", "Build ID"),
        ("build_number", "Build number"),
        ("kernel", "Kernel"),
        ("uptime", "Uptime"),
        ("boot_time", "Boot time"),
        ("bootloader", "Bootloader"),
        ("baseband", "Baseband"),
        ("fingerprint", "Build fingerprint"),
    ],
    "BATTERY": [
        ("level", "Level"),
        ("status", "Status"),
        ("source", "Power source"),
        ("health", "Health"),
        ("temperature", "Temperature"),
        ("voltage", "Voltage"),
        ("technology", "Technology"),
        ("design_capacity", "Design capacity"),
        ("cycle_count", "Cycle count"),
    ],
    "STORAGE": [
        ("storage_total", "Total"),
        ("storage_used", "Used"),
        ("storage_free", "Free"),
        ("storage_mount", "Mount"),
        ("storage_filesystem", "Filesystem"),
    ],
    "PROCESSOR": [
        ("processor", "Processor"),
        ("architecture", "Architecture"),
        ("cpu_64bit", "64-bit"),
        ("cores", "Cores"),
        ("max_frequency", "Max frequency"),
        ("load", "Current load"),
    ],
    "GRAPHICS & DISPLAY": [
        ("gpu_vendor", "GPU vendor"),
        ("gpu_model", "GPU model"),
        ("resolution", "Resolution"),
        ("density", "Density"),
        ("refresh_rate", "Refresh rate"),
        ("supported_refresh_rates", "Supported refresh rates"),
        ("orientation", "Orientation"),
        ("display_override", "Display override"),
    ],
    "MEMORY": [
        ("ram_total", "Total"),
        ("ram_available", "Available"),
        ("ram_used", "Used"),
    ],
    "NETWORK": [
        ("transport", "Transport"),
        ("wifi_enabled", "Wi-Fi"),
        ("wifi_connected", "Wi-Fi link"),
        ("ssid", "SSID"),
        ("frequency", "Frequency"),
        ("link_speed", "Link speed"),
        ("rssi", "RSSI"),
        ("ipv4", "IPv4"),
        ("ipv6", "IPv6"),
        ("gateway", "Gateway"),
        ("dns", "DNS"),
        ("vpn", "VPN"),
    ],
    "SECURITY": [
        ("selinux", "SELinux"),
        ("verified_boot", "Verified Boot"),
        ("bootloader_state", "Bootloader"),
        ("root", "Root evidence"),
        ("security_patch", "Security patch"),
        ("debuggable", "Debuggable build"),
        ("secure_build", "Secure build"),
        ("encryption", "Encryption"),
        ("encryption_type", "Encryption type"),
        ("verity", "Verity"),
    ],
    "IDENTIFIERS": [
        ("android_id", "Android ID"),
        ("wifi_mac", "Wi-Fi MAC"),
        ("bluetooth_mac", "Bluetooth MAC"),
    ],
}

#: Grid order defines hierarchy: identity/system/battery/storage first
#: (primary), then processor/display/memory, then network/security, and
#: identifiers last as the detail row. Two columns wide.
_CARD_ORDER = (
    "DEVICE",
    "SYSTEM / ANDROID",
    "BATTERY",
    "STORAGE",
    "PROCESSOR",
    "GRAPHICS & DISPLAY",
    "MEMORY",
    "NETWORK",
    "SECURITY",
    "IDENTIFIERS",
)

_UNKNOWN = "Unknown"
_NOT_AVAILABLE = "Not available on this device"

#: Human labels for backend security tokens (display only — the model keeps
#: the machine tokens; an unrecognized token is passed through unchanged).
_SELINUX_LABELS = {
    "enforcing": "Enforcing",
    "permissive": "Permissive",
    "disabled": "Disabled",
}
_VERIFIED_BOOT_LABELS = {
    "green": "Green",
    "yellow": "Yellow",
    "orange": "Orange",
    "red": "Red",
}
_ROOT_LABELS = {
    "ROOT_EVIDENCE": "Root evidence detected",
    "NO_ROOT_EVIDENCE": "No root evidence detected",
}
_ENCRYPTION_LABELS = {
    "encrypted": "Encrypted",
    "unencrypted": "Unencrypted",
}
_ENCRYPTION_TYPE_LABELS = {
    "file": "File",
    "block": "Block",
}
_VERITY_LABELS = {
    "enforcing": "Enforcing",
    "eio": "EIO",
    "logging": "Logging",
    "disabled": "Disabled",
}

#: Category cards that carry a diagnostics annotation: (card name, category).
#: Only BATTERY / STORAGE / SECURITY are annotated — the diagnostics rules
#: that speak to the page's fact cards live in those categories.
_ANNOTATED_CARDS = (
    ("BATTERY", DiagnosticCategory.BATTERY),
    ("STORAGE", DiagnosticCategory.STORAGE),
    ("SECURITY", DiagnosticCategory.SECURITY),
)

#: Severity label prefix for annotation lines (text, never color-only).
_ANNOTATION_LABEL = {
    DiagnosticSeverity.CRITICAL: "CRITICAL",
    DiagnosticSeverity.WARNING: "WARNING",
}


class DevicePage(QWidget):
    """The DEVICE navigation destination: summary + fact cards."""

    #: The user asked to export the device report (MainWindow opens the
    #: save dialog, builds the payload and hands the write to a worker).
    export_requested = Signal()

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

        subtitle = QLabel(
            "Identity, performance, network and security of the connected device"
        )
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
        self._notes: dict[str, QLabel] = {}
        self._storage_bar: QProgressBar | None = None

        grid = QGridLayout()
        grid.setSpacing(10)
        for index, card_name in enumerate(_CARD_ORDER):
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

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self._export_btn = QPushButton("Export Device Report")
        self._export_btn.setObjectName("secondary")
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self.export_requested.emit)
        self._exporting = False
        self._export_status = QLabel("")
        self._export_status.setObjectName("muted")
        self._export_status.setWordWrap(True)
        self._export_status.setTextFormat(Qt.TextFormat.PlainText)
        export_row.addWidget(self._export_btn)
        export_row.addWidget(self._export_status, 1)
        export_row.addStretch(1)
        layout.addLayout(export_row)

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
        diagnostics: DiagnosticReport | None = None,
    ) -> None:
        """Re-render the page from one structured state bundle."""
        connected = state is ConnectionState.CONNECTED
        self._empty.setVisible(not connected)
        self.set_export_available(connected)
        for card_name in self._values:
            self._cards[card_name].setVisible(connected)
        self._summary_line.setVisible(connected)
        self._render_annotations(diagnostics)
        if not connected:
            self._reset_values()
            return
        self._render_summary(info)
        values: dict[str, str] = {}
        values.update(_info_values(info))
        values.update(_live_values(battery, memory, cpu))
        for card_name, spec in _CARD_SPECS.items():
            self._render_card(card_name, spec, values)

    # ------------------------------------------------------------------
    # Device report export state (GUI thread; MainWindow calls this)
    # ------------------------------------------------------------------

    def set_export_available(self, available: bool) -> None:
        """Enable the export button only while a device is connected."""
        self._export_btn.setEnabled(available and not self._exporting)
        if not available:
            self._export_status.setText("")

    def set_export_busy(self, busy: bool) -> None:
        """Lock the button while an export is being written."""
        self._exporting = busy
        self._export_btn.setEnabled(not busy)
        if busy:
            self._export_status.setText("Exporting…")

    def show_export_result(self, success: bool, message: str) -> None:
        """Render the worker's outcome; failures stay visible and honest."""
        self._exporting = False
        self._export_btn.setEnabled(True)
        self._export_status.setText(message)

    def _render_annotations(
        self, diagnostics: DiagnosticReport | None
    ) -> None:
        """Attach the first WARNING+ finding of a category to its card.

        The report is already ordered severity-first, so ``next()`` over
        its findings yields the most severe one of the category without
        any re-sorting here. Annotations are text + color (the severity
        word is always visible), never color alone.
        """
        for card_name, category in _ANNOTATED_CARDS:
            note = self._notes[card_name]
            finding = None
            if diagnostics is not None:
                finding = next(
                    (
                        f
                        for f in diagnostics.findings
                        if f.category is category
                        and f.severity in _ANNOTATION_LABEL
                    ),
                    None,
                )
            if finding is None:
                note.hide()
                continue
            note.setText(
                f"\u26a0 {_ANNOTATION_LABEL[finding.severity]}: {finding.title}"
            )
            note.setObjectName(
                "statusError"
                if finding.severity is DiagnosticSeverity.CRITICAL
                else "statusWarn"
            )
            note.setToolTip(finding.evidence)
            repolish(note)
            note.show()

    def _reset_values(self) -> None:
        """Clear every value label so nothing stale survives a disconnect."""
        for card_name, spec in _CARD_SPECS.items():
            for key, _caption in spec:
                label = self._values[card_name][key]
                label.setText(_UNKNOWN)
                label.setToolTip("")
            self._na[card_name].setVisible(True)
        for note in self._notes.values():
            note.hide()
        if self._storage_bar is not None:
            self._storage_bar.setValue(0)

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _render_summary(self, info: DeviceInformation | None) -> None:
        parts: list[str] = []
        if info is not None:
            if info.model:
                parts.append(f"Model {info.model}")
            if info.api_level:
                parts.append(f"API {info.api_level}")
            if info.manufacturer:
                parts.append(f"Manufacturer {info.manufacturer}")
            if info.brand:
                parts.append(f"Brand {info.brand}")
        self._summary_line.setText(" \u00b7 ".join(parts))

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
            label.setText(values.get(key, _UNKNOWN))
            if key == "fingerprint":
                label.setToolTip(values.get("fingerprint_full") or "")
        na_label.setVisible(present == 0)
        if card_name == "STORAGE" and self._storage_bar is not None:
            self._storage_bar.setVisible(present > 0)
            storage_text = values.get("storage_percent")
            if storage_text is None:
                self._storage_bar.setValue(0)
            else:
                self._storage_bar.setValue(int(round(float(storage_text))))

    def _make_card(self, title: str) -> tuple[QFrame, dict[str, QLabel], QLabel]:
        card, layout = panel(title)
        values: dict[str, QLabel] = {}
        for key, caption in _CARD_SPECS[title]:
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(caption)
            label.setObjectName("muted")
            label.setTextFormat(Qt.TextFormat.PlainText)
            value = QLabel(_UNKNOWN)
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
        na = QLabel(_NOT_AVAILABLE)
        na.setObjectName("muted")
        na.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(na)
        if title in {card_name for card_name, _category in _ANNOTATED_CARDS}:
            note = QLabel("")
            note.setObjectName("statusWarn")
            note.setWordWrap(True)
            note.setTextFormat(Qt.TextFormat.PlainText)
            note.hide()
            layout.addWidget(note)
            self._notes[title] = note
        layout.addStretch(1)
        return card, values, na


# ---------------------------------------------------------------------------
# Value formatting (presentation only — never fabricates)
# ---------------------------------------------------------------------------


def _info_values(info: DeviceInformation | None) -> dict[str, str]:
    """Snapshot facts from the device-information model, human-formatted."""
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
        "build_id",
        "build_number",
        "kernel",
        "bootloader",
        "baseband",
    ):
        value = getattr(info, key)
        if value:
            values[key] = value
    if info.build_fingerprint:
        values["fingerprint"] = _elide(info.build_fingerprint, 52)
        values["fingerprint_full"] = info.build_fingerprint
    if info.cpu_64bit is not None:
        values["cpu_64bit"] = _yes_no(info.cpu_64bit)
    if info.max_frequency_khz:
        values["max_frequency"] = _format_frequency(info.max_frequency_khz)
    if info.uptime_seconds is not None:
        values["uptime"] = _format_duration(info.uptime_seconds)
    if info.boot_time is not None:
        values["boot_time"] = info.boot_time.strftime("%Y-%m-%d %H:%M UTC")
    if info.resolution:
        values["resolution"] = info.resolution.replace("x", " \u00d7 ")
    if info.density_dpi:
        values["density"] = f"{info.density_dpi} dpi"
    if info.refresh_rate_hz:
        values["refresh_rate"] = f"{info.refresh_rate_hz:g} Hz"
    if info.supported_refresh_rates_hz:
        values["supported_refresh_rates"] = " \u00b7 ".join(
            f"{rate:g} Hz" for rate in info.supported_refresh_rates_hz
        )
    if info.orientation:
        values["orientation"] = info.orientation
    values.update(_override_values(info))
    if info.gpu_vendor:
        values["gpu_vendor"] = info.gpu_vendor
    if info.gpu_model:
        values["gpu_model"] = info.gpu_model
    if info.battery_design_capacity is not None:
        # ``charge_full_design`` is kept verbatim by the backend (OEM units
        # vary); the UI only marks it as a raw reported figure.
        values["design_capacity"] = f"{info.battery_design_capacity:,} (reported)"
    if info.battery_cycle_count is not None:
        values["cycle_count"] = f"{info.battery_cycle_count:,}"
    if info.storage is not None:
        values.update(_storage_values(info.storage))
    if info.storage_filesystem:
        values["storage_filesystem"] = info.storage_filesystem
    values.update(_network_values(info))
    values.update(_security_values(info))
    if info.android_id:
        values["android_id"] = info.android_id
    if info.wifi_mac:
        values["wifi_mac"] = info.wifi_mac
    if info.bluetooth_mac:
        values["bluetooth_mac"] = info.bluetooth_mac
    return values


def _override_values(info: DeviceInformation) -> dict[str, str]:
    """Display override: the reported override, or a genuine "no override"
    when the physical resolution was readable and no override is active."""
    parts: list[str] = []
    if info.display_override_resolution:
        parts.append(info.display_override_resolution.replace("x", " \u00d7 "))
    if info.display_override_density:
        parts.append(f"{info.display_override_density} dpi")
    if parts:
        return {"display_override": " \u00b7 ".join(parts)}
    if info.resolution:
        return {"display_override": "No override"}
    return {}


def _network_values(info: DeviceInformation) -> dict[str, str]:
    """Network facts; BSSID and MAC stay out of this card on purpose."""
    values: dict[str, str] = {}
    if info.active_transport:
        values["transport"] = info.active_transport
    if info.wifi_enabled is not None:
        values["wifi_enabled"] = _yes_no(info.wifi_enabled)
    if info.wifi_connected is not None:
        values["wifi_connected"] = (
            "Connected" if info.wifi_connected else "Not connected"
        )
    if info.wifi_ssid:
        values["ssid"] = info.wifi_ssid
    if info.wifi_frequency_mhz:
        values["frequency"] = f"{info.wifi_frequency_mhz} MHz"
    if info.wifi_link_speed_mbps is not None:
        values["link_speed"] = f"{info.wifi_link_speed_mbps:.0f} Mbps"
    if info.wifi_rssi_dbm is not None:
        values["rssi"] = f"{info.wifi_rssi_dbm} dBm"
    if info.ipv4_addresses:
        values["ipv4"] = ", ".join(info.ipv4_addresses)
    if info.ipv6_addresses:
        values["ipv6"] = ", ".join(info.ipv6_addresses)
    if info.default_gateway:
        values["gateway"] = info.default_gateway
    if info.dns_servers:
        values["dns"] = ", ".join(info.dns_servers)
    if info.vpn_active is not None:
        label = "Connected" if info.vpn_active else "Not detected"
        if info.vpn_active and info.vpn_interface:
            label += f" ({info.vpn_interface})"
        values["vpn"] = label
    return values


def _security_values(info: DeviceInformation) -> dict[str, str]:
    """Evidence-based security facts. Unknown stays Unknown — it is never
    rendered as "Disabled", "Not rooted", "Secure" or any verdict."""
    values: dict[str, str] = {}
    if info.selinux_status:
        values["selinux"] = _SELINUX_LABELS.get(
            info.selinux_status, info.selinux_status
        )
    if info.verified_boot_state:
        values["verified_boot"] = _VERIFIED_BOOT_LABELS.get(
            info.verified_boot_state, info.verified_boot_state
        )
    if info.bootloader_locked is not None:
        values["bootloader_state"] = (
            "Locked" if info.bootloader_locked else "Unlocked"
        )
    if info.root_status:
        values["root"] = _ROOT_LABELS.get(info.root_status, info.root_status)
    patch = _security_patch_text(info)
    if patch:
        values["security_patch"] = patch
    if info.debuggable is not None:
        values["debuggable"] = _yes_no(info.debuggable)
    if info.secure_build is not None:
        values["secure_build"] = _yes_no(info.secure_build)
    if info.encryption_state:
        values["encryption"] = _ENCRYPTION_LABELS.get(
            info.encryption_state, info.encryption_state
        )
    if info.encryption_type:
        values["encryption_type"] = _ENCRYPTION_TYPE_LABELS.get(
            info.encryption_type, info.encryption_type
        )
    if info.verity_mode:
        values["verity"] = _VERITY_LABELS.get(info.verity_mode, info.verity_mode)
    return values


def _security_patch_text(info: DeviceInformation) -> str | None:
    """Validated patch date when available, else the raw reported string."""
    if info.security_patch_date is not None:
        return info.security_patch_date.isoformat()
    return info.security_patch


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
        source = _battery_source(battery)
        if source is not None:
            values["source"] = source
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


def _battery_source(battery: BatterySnapshot) -> str | None:
    """Power source from the live snapshot flags; None when unknown.

    Only flag-based evidence is used: no flag and not discharging means the
    source is simply not reported (Unknown), never assumed.
    """
    sources: list[str] = []
    if battery.ac_powered is True:
        sources.append("AC")
    if battery.usb_powered is True:
        sources.append("USB")
    if battery.wireless_powered is True:
        sources.append("Wireless")
    if sources:
        return " + ".join(sources)
    if battery.status == BatteryStatus.DISCHARGING:
        return "Battery"
    return None


def _storage_values(storage: StorageInfo) -> dict[str, str]:
    percent = storage.used_percent
    used_text = f"{format_kib(storage.used_kb)}"
    if percent is not None:
        used_text += f" ({percent:.0f}%)"
    values: dict[str, str] = {
        "storage_total": format_kib(storage.total_kb),
        "storage_used": used_text,
        "storage_free": format_kib(storage.available_kb),
        "storage_mount": storage.mount,
    }
    if percent is not None:
        values["storage_percent"] = f"{percent}"
    return values


def _format_frequency(khz: int) -> str:
    if khz >= 1_000_000:
        return f"{khz / 1_000_000:.2f} GHz"
    return f"{khz / 1000:.0f} MHz"


def _format_duration(seconds: float) -> str:
    """Human duration like "1d 10h", "3h 12m", "45m 30s", "12s"."""
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _elide(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "\u2026"
"""Minimal terminal renderer for normalized CPU, memory, process, battery and
network snapshots.

Deliberately dependency-light (standard library only) and ADB-agnostic: it
consumes normalized data (snapshots + device strings) and formats text.
"""

from __future__ import annotations

from ..battery.models import BatterySnapshot
from ..cpu.models import CPUCore, CPUSnapshot
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..process.models import ProcessInfo, ProcessSnapshot

_SEPARATOR_LENGTH = 40
_PROCESS_TABLE_LENGTH = 60

#: Binary (1024-based) unit conversion, consistent everywhere RAM is shown.
_KIB_PER_MIB = 1024
_KIB_PER_GIB = _KIB_PER_MIB * _KIB_PER_MIB


def _format_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}%"


def _format_frequency(core: CPUCore) -> str:
    if not core.frequency_available or core.frequency_khz is None:
        return "N/A"
    return f"{round(core.frequency_khz / 1000)} MHz"


def _format_core(core: CPUCore) -> str:
    pct = _format_percent(core.utilization_percent)
    freq = _format_frequency(core)
    return f"Core {core.core_id:<3} {pct:>6}   {freq}"


def format_kib(kib: int) -> str:
    """Format a KiB value as a human-readable binary unit string."""
    gib = kib / _KIB_PER_GIB
    if gib >= 1.0:
        return f"{gib:.2f} GB"
    mib = kib / _KIB_PER_MIB
    if mib >= 1.0:
        return f"{mib:.0f} MB"
    return f"{kib} KB"


def _memory_lines(memory: MemorySnapshot) -> list[str]:
    rows = [
        ("Total", memory.total_kb),
        ("Available", memory.available_kb),
        ("Free", memory.free_kb),
        ("Cached", memory.cached_kb),
        ("Buffers", memory.buffers_kb),
    ]
    return [f"{label + ':':<12}{format_kib(value)}" for label, value in rows]


def _process_cpu_sort_key(process: ProcessInfo) -> float:
    return process.cpu_percent if process.cpu_percent is not None else float("-inf")


def _process_row(process: ProcessInfo) -> str:
    cpu = "N/A" if process.cpu_percent is None else f"{process.cpu_percent:.1f}%"
    mem = "N/A" if process.memory_percent is None else f"{process.memory_percent:.1f}%"
    uid = "N/A" if process.uid is None else str(process.uid)
    state = process.state if process.state else "-"
    return f"{process.pid:<8} {uid:<9} {cpu:>7} {mem:>7} {state:<6} {process.name}"


def _process_lines(processes: ProcessSnapshot) -> list[str]:
    rows = sorted(processes.processes, key=_process_cpu_sort_key, reverse=True)
    header = f"{'PID':<8} {'UID':<9} {'CPU':>7} {'MEM':>7} {'STATE':<6} NAME"
    return [
        "Processes",
        "-" * _PROCESS_TABLE_LENGTH,
        header,
        "-" * _PROCESS_TABLE_LENGTH,
        *[_process_row(row) for row in rows],
    ]


def format_throughput(bytes_per_sec: float | None) -> str:
    """Format a bytes-per-second rate as a human readable unit string.

    ``None`` (no baseline yet, or a device error) renders as ``N/A``.
    """
    if bytes_per_sec is None:
        return "N/A"
    mib = bytes_per_sec / (_KIB_PER_MIB * _KIB_PER_MIB)
    if mib >= 1.0:
        return f"{mib:.2f} MB/s"
    if bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.0f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


def _network_lines(network: NetworkSnapshot) -> list[str]:
    def row(label: str, value: str) -> str:
        return f"{label + ':':<14}{value}"

    agg = network.aggregate_throughput
    lines = [
        "Network",
        "-" * _SEPARATOR_LENGTH,
        "",
        row("Download", format_throughput(agg.rx_bytes_per_sec)),
        row("Upload", format_throughput(agg.tx_bytes_per_sec)),
        "",
        row("RX bytes", f"{network.aggregate_rx_bytes:,}"),
        row("TX bytes", f"{network.aggregate_tx_bytes:,}"),
    ]
    for interface in network.interfaces:
        if interface.name == "lo":
            continue
        t = network.interface_throughput.get(interface.name)
        down = format_throughput(t.rx_bytes_per_sec if t else None)
        up = format_throughput(t.tx_bytes_per_sec if t else None)
        lines.append(row(interface.name, f"down {down:>9}  up {up:>9}"))
    if not network.interfaces:
        lines.append(row("Interfaces", "none"))
    return lines


def _power_sources(battery: BatterySnapshot) -> str:
    sources = []
    if battery.ac_powered is True:
        sources.append("AC")
    if battery.usb_powered is True:
        sources.append("USB")
    if battery.wireless_powered is True:
        sources.append("Wireless")
    return ", ".join(sources) if sources else "None"


def _battery_lines(battery: BatterySnapshot) -> list[str]:
    def row(label: str, value: str) -> str:
        return f"{label + ':':<14}{value}"

    level = "N/A" if battery.level_percent is None else f"{battery.level_percent:.0f}%"
    temperature = (
        "N/A"
        if battery.temperature_c is None
        else f"{battery.temperature_c:.1f} \u00b0C"
    )
    voltage = "N/A" if battery.voltage_mv is None else f"{battery.voltage_mv / 1000:.3f} V"
    return [
        "Battery",
        "-" * _SEPARATOR_LENGTH,
        "",
        row("Level", level),
        row("Status", battery.status.label),
        row("Health", battery.health.label),
        row("Temperature", temperature),
        row("Voltage", voltage),
        row("Technology", battery.technology or "Unknown"),
        row("Power", _power_sources(battery)),
    ]


class TerminalRenderer:
    """Formats snapshots (plus device identity) as plain text."""

    def __init__(self, device_label: str, android_version: str) -> None:
        self._device_label = device_label or "Unknown device"
        self._android_version = android_version or "Unknown"

    def render(
        self,
        snapshot: CPUSnapshot,
        memory: MemorySnapshot | None = None,
        processes: ProcessSnapshot | None = None,
        battery: BatterySnapshot | None = None,
        network: NetworkSnapshot | None = None,
    ) -> str:
        header = [
            "Android Task Manager",
            f"Device: {self._device_label}",
            f"Android: {self._android_version}",
        ]
        body = [
            "CPU",
            "-" * _SEPARATOR_LENGTH,
            "",
            f"Overall: {_format_percent(snapshot.aggregate_utilization_percent)}",
            "",
            *[_format_core(core) for core in snapshot.cores],
        ]
        if memory is not None:
            body += [
                "",
                "Memory",
                "-" * _SEPARATOR_LENGTH,
                "",
                *_memory_lines(memory),
            ]
        if processes is not None:
            body += [
                "",
                *_process_lines(processes),
            ]
        if battery is not None:
            body += [
                "",
                *_battery_lines(battery),
            ]
        if network is not None:
            body += [
                "",
                *_network_lines(network),
            ]
        return "\n".join(header + [""] + body)
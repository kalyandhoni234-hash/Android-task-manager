"""Entry point for the terminal Android Task Manager (CPU + memory + processes + battery)."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

from .adb.connection import ConnectionManager
from .adb.discovery import find_adb, version_validator
from .adb.exceptions import ADBAmbiguousDeviceError, ADBError
from .battery.collector import BatteryCollector
from .core.diagnostics import setup_logging
from .cpu.collector import CPUCollector
from .memory.collector import MemoryCollector
from .network.collector import NetworkCollector
from .process.collector import ProcessCollector
from .terminal.renderer import TerminalRenderer

_DEFAULT_INTERVAL = 2.0
_DEFAULT_MEMORY_INTERVAL = 10.0
_DEFAULT_PROCESS_INTERVAL = 5.0
_DEFAULT_BATTERY_INTERVAL = 15.0
_DEFAULT_NETWORK_INTERVAL = 5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android-task-manager",
        description="Terminal Android system monitor over ADB (CPU + memory + processes + battery).",
    )
    parser.add_argument(
        "--adb",
        default=None,
        help=(
            "Path to the adb executable. When omitted, adb is located "
            "automatically (beside the app, on PATH, or in a standard SDK folder)."
        ),
    )
    parser.add_argument(
        "--device",
        dest="device_serial",
        default=None,
        help="Explicit adb serial of the target device.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=_DEFAULT_INTERVAL,
        help="Seconds between CPU samples (default: %(default)s).",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="Stop after this many samples (default: run until Ctrl+C).",
    )
    parser.add_argument(
        "--memory-interval",
        type=float,
        default=_DEFAULT_MEMORY_INTERVAL,
        help="Seconds between /proc/meminfo reads (default: %(default)s). "
        "Memory is sampled less often than CPU on purpose.",
    )
    parser.add_argument(
        "--process-interval",
        type=float,
        default=_DEFAULT_PROCESS_INTERVAL,
        help="Seconds between ps/top process refreshes (default: %(default)s). "
        "Process collection (ps + top) is more expensive than CPU reads.",
    )
    parser.add_argument(
        "--battery-interval",
        type=float,
        default=_DEFAULT_BATTERY_INTERVAL,
        help="Seconds between dumpsys battery reads (default: %(default)s). "
        "Battery state changes slowly, so it is sampled rarely.",
    )
    parser.add_argument(
        "--network-interval",
        type=float,
        default=_DEFAULT_NETWORK_INTERVAL,
        help="Seconds between /proc/net/dev reads (default: %(default)s). "
        "Network throughput needs a baseline, so it is sampled on its own cadence.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-command timeout (default: %(default)s).")
    return parser


def _device_label(connection: ConnectionManager, serial: str) -> tuple[str, str]:
    manufacturer = connection.get_prop("ro.product.manufacturer")
    model = connection.get_prop("ro.product.model")
    release = connection.get_prop("ro.build.version.release")

    combined = f"{manufacturer} {model}".strip()
    if not combined:
        combined = serial
    return combined, release


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    try:
        connection = ConnectionManager(
            adb_path=(
                find_adb(explicit=args.adb, validator=version_validator(args.timeout))
                or args.adb
                or "adb"
            ),
            timeout=args.timeout,
            device_serial=args.device_serial,
        )
        connection.verify_available()
        serial = connection.require_device()
    except ADBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        label, android_release = _device_label(connection, serial)
    except ADBError as exc:
        print(f"ERROR reading device properties: {exc}", file=sys.stderr)
        return 1

    collector = CPUCollector(connection)
    memory_collector = MemoryCollector(connection)
    process_collector = ProcessCollector(connection)
    battery_collector = BatteryCollector(connection)
    network_collector = NetworkCollector(connection)
    renderer = TerminalRenderer(label, android_release)

    try:
        memory_snapshot = None
        process_snapshot = None
        battery_snapshot = None
        network_snapshot = None
        last_memory_at = 0.0
        last_process_at = 0.0
        last_battery_at = 0.0
        last_network_at = 0.0
        collected = 0
        while True:
            snapshot = collector.sample()

            now = time.monotonic()
            if memory_snapshot is None or (now - last_memory_at) >= args.memory_interval:
                # /proc/meminfo needs no baseline and changes slowly, so it is
                # refreshed on its own slower cadence instead of every CPU tick.
                memory_snapshot = memory_collector.sample()
                last_memory_at = now

            if process_snapshot is None or (now - last_process_at) >= args.process_interval:
                # ps + top are comparatively expensive; refresh on their own
                # cadence and cache the result between refreshes.
                process_snapshot = process_collector.sample()
                last_process_at = now

            if battery_snapshot is None or (now - last_battery_at) >= args.battery_interval:
                # Battery changes slowly; sample rarely and render the cached
                # snapshot in between.
                battery_snapshot = battery_collector.sample()
                last_battery_at = now

            if network_snapshot is None or (now - last_network_at) >= args.network_interval:
                # /proc/net/dev needs a baseline to compute throughput; sample
                # on its own cadence and render the cached snapshot in between.
                network_snapshot = network_collector.sample()
                last_network_at = now

            print(renderer.render(snapshot, memory_snapshot, process_snapshot, battery_snapshot, network_snapshot))
            print()
            sys.stdout.flush()
            collected += 1
            if args.samples is not None and collected >= args.samples:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped.")
        return 0
    except ADBError as exc:
        print(f"\nADB error: {exc}", file=sys.stderr)
        return 1
    except ADBAmbiguousDeviceError:
        raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
"""Unit tests for the device-information parsers (pure functions).

Covers structured parsing of bulk getprop output, wm size/density, df -k,
refresh rate and orientation tokens, MAC/Android-ID normalization, and the
malformed-output tolerance every parser must have.
"""

from __future__ import annotations

import pytest

from android_task_manager.device.models import StorageInfo
from android_task_manager.device.parser import (
    parse_android_id,
    parse_cpu_hardware_line,
    parse_df_k,
    parse_getprop_output,
    parse_mac_address,
    parse_max_frequency_khz,
    parse_orientation,
    parse_refresh_rate,
    parse_wm_density,
    parse_wm_size,
    pick_internal_storage,
)


# ---------------------------------------------------------------------------
# getprop
# ---------------------------------------------------------------------------


def test_getprop_parses_bracket_lines() -> None:
    text = (
        "[ro.product.model]: [V2026]\n"
        "[ro.build.version.sdk]: [30]\n"
        "[ro.product.cpu.abilist]: [arm64-v8a,armeabi-v7a]\n"
    )
    props = parse_getprop_output(text)
    assert props["ro.product.model"] == "V2026"
    assert props["ro.build.version.sdk"] == "30"
    assert props["ro.product.cpu.abilist"] == "arm64-v8a,armeabi-v7a"


def test_getprop_ignores_non_bracket_lines() -> None:
    props = parse_getprop_output(
        "Usage: getprop [options]\n"
        "[ro.product.model]: [V2026]\n"
        "garbage line without brackets\n"
        ""
    )
    assert props == {"ro.product.model": "V2026"}


def test_getprop_keeps_explicitly_empty_value() -> None:
    props = parse_getprop_output("[ro.product.model]: []\n")
    assert props["ro.product.model"] == ""


def test_getprop_handles_brackets_inside_value() -> None:
    props = parse_getprop_output("[ro.build.display.id]: [build[2] final]\n")
    assert props["ro.build.display.id"] == "build[2] final"


# ---------------------------------------------------------------------------
# wm size / density
# ---------------------------------------------------------------------------


def test_wm_size_physical_wins_over_override() -> None:
    text = "Override size: 720x1440\nPhysical size: 1080x2340\n"
    assert parse_wm_size(text) == "1080x2340"


def test_wm_size_missing_is_none() -> None:
    assert parse_wm_size("Status bar height: 66\n") is None
    assert parse_wm_size("") is None


def test_wm_density_parses_int() -> None:
    assert parse_wm_density("Physical density: 440\n") == 440


def test_wm_density_malformed_is_none() -> None:
    assert parse_wm_density("Physical density: not-a-number\n") is None
    assert parse_wm_density("") is None


# ---------------------------------------------------------------------------
# df -k
# ---------------------------------------------------------------------------


def test_df_parses_volume_rows() -> None:
    text = (
        "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
        "/dev/block/sda11 121934848 69120000 52814848 57% /data\n"
        "/dev/block/sda12 4000000 1000000 3000000 25% /vendor\n"
    )
    volumes = parse_df_k(text)
    assert len(volumes) == 2
    data = volumes[0]
    assert data.mount == "/data"
    assert data.total_kb == 121934848
    assert data.used_kb == 69120000
    assert data.available_kb == 52814848
    assert data.used_percent == pytest.approx(56.69, abs=0.1)


def test_df_skips_malformed_rows() -> None:
    text = (
        "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
        "/dev/block/sda11 12x 69120000 52814848 57% /data\n"
        "/dev/block/sda12 4000000 nope 3000000 25% /vendor\n"
        "df: /data: No such file or directory\n"
    )
    assert parse_df_k(text) == []


def test_df_error_line_never_crashes() -> None:
    assert parse_df_k("df: /data: Permission denied\n") == []


def test_pick_internal_storage_exact_mount() -> None:
    volumes = [
        StorageInfo(mount="/vendor", total_kb=1, used_kb=0, available_kb=1),
        StorageInfo(mount="/data", total_kb=2, used_kb=1, available_kb=1),
    ]
    picked = pick_internal_storage(volumes)
    assert picked is not None
    assert picked.mount == "/data"


def test_pick_internal_storage_fbe_per_user_view() -> None:
    """FBE devices report ``/data`` as ``/data/user/0`` — still internal."""
    volumes = [
        StorageInfo(mount="/vendor", total_kb=1, used_kb=0, available_kb=1),
        StorageInfo(mount="/data/user/0", total_kb=2, used_kb=1, available_kb=1),
    ]
    picked = pick_internal_storage(volumes)
    assert picked is not None
    assert picked.mount == "/data/user/0"


def test_pick_internal_storage_prefers_exact_data_mount() -> None:
    volumes = [
        StorageInfo(mount="/data/user/0", total_kb=2, used_kb=1, available_kb=1),
        StorageInfo(mount="/data", total_kb=3, used_kb=1, available_kb=2),
    ]
    picked = pick_internal_storage(volumes)
    assert picked is not None
    assert picked.mount == "/data"


def test_pick_internal_storage_missing_is_none() -> None:
    volumes = [StorageInfo(mount="/vendor", total_kb=1, used_kb=0, available_kb=1)]
    assert pick_internal_storage(volumes) is None
    assert pick_internal_storage([]) is None


# ---------------------------------------------------------------------------
# Display tokens
# ---------------------------------------------------------------------------


def test_refresh_rate_matches_known_tokens() -> None:
    assert parse_refresh_rate("mRefreshRate=60.000004\n") == pytest.approx(60.0)
    assert parse_refresh_rate("mDefaultRefreshRate=90.5\n") == pytest.approx(90.5)
    assert parse_refresh_rate("refreshRate: 120\n") == pytest.approx(120.0)


def test_refresh_rate_absent_is_none() -> None:
    assert parse_refresh_rate("mDisplayInfo=DisplayInfo{}\n") is None
    assert parse_refresh_rate("") is None


def test_orientation_maps_surface_values() -> None:
    assert parse_orientation("SurfaceOrientation: 0\n") == "Portrait"
    assert parse_orientation("SurfaceOrientation: 1\n") == "Landscape"
    assert parse_orientation("SurfaceOrientation: 2\n") == "Reverse portrait"
    assert parse_orientation("SurfaceOrientation: 3\n") == "Reverse landscape"


def test_orientation_invalid_or_absent_is_none() -> None:
    assert parse_orientation("SurfaceOrientation: 9\n") is None
    assert parse_orientation("no orientation here\n") is None
    assert parse_orientation("") is None


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


def test_mac_address_accepts_real_value() -> None:
    assert parse_mac_address("3C:28:6D:AB:CD:EF\n") == "3c:28:6d:ab:cd:ef"


def test_mac_address_rejects_placeholder() -> None:
    assert parse_mac_address("02:00:00:00:00:00\n") is None


def test_mac_address_rejects_malformed() -> None:
    assert parse_mac_address("3c:28:6d\n") is None
    assert parse_mac_address("zz:28:6d:ab:cd:ef\n") is None
    assert parse_mac_address("") is None


def test_android_id_accepts_value_rejects_null() -> None:
    assert parse_android_id("a1b2c3d4e5f60718\n") == "a1b2c3d4e5f60718"
    assert parse_android_id("null\n") is None
    assert parse_android_id("") is None


# ---------------------------------------------------------------------------
# CPU facts
# ---------------------------------------------------------------------------


def test_cpu_hardware_line_parsed() -> None:
    text = "Processor\t: AArch64 Processor rev 2 (aarch64)\nHardware\t: Qualcomm SM8250\n"
    assert parse_cpu_hardware_line(text) == "Qualcomm SM8250"


def test_cpu_hardware_line_missing_is_none() -> None:
    assert parse_cpu_hardware_line("Processor\t: AArch64\n") is None
    assert parse_cpu_hardware_line("") is None


def test_max_frequency_parses_int() -> None:
    assert parse_max_frequency_khz("2841600\n") == 2841600


def test_max_frequency_malformed_is_none() -> None:
    assert parse_max_frequency_khz("not-a-number\n") is None
    assert parse_max_frequency_khz("") is None
"""Unit tests for the device-information parsers (pure functions).

Covers structured parsing of bulk getprop output, wm size/density, df -k,
refresh rate and orientation tokens, MAC/Android-ID normalization, and the
malformed-output tolerance every parser must have.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from android_task_manager.device.models import StorageInfo
from android_task_manager.device.parser import (
    derive_boot_time,
    derive_cpu_64bit,
    khz_to_hz,
    parse_android_id,
    parse_cpu_features,
    parse_cpu_hardware_line,
    parse_cpu_range,
    parse_cpufreq_khz,
    parse_cpuinfo_cores,
    parse_cpuinfo_model_name,
    parse_df_k,
    parse_epoch_seconds,
    parse_getprop_output,
    parse_governor,
    parse_gpu_gles,
    parse_mac_address,
    parse_max_frequency_khz,
    parse_orientation,
    parse_orientation_degrees,
    parse_proc_uptime,
    parse_refresh_rate,
    parse_supported_refresh_rates,
    parse_uname_a,
    parse_uname_a_machine,
    parse_wm_density,
    parse_wm_override_density,
    parse_wm_override_size,
    parse_wm_size,
    parse_wm_size_dimensions,
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


def test_wm_size_dimensions_parsed() -> None:
    assert parse_wm_size_dimensions("Physical size: 1080x2340\n") == (1080, 2340)


def test_wm_size_dimensions_physical_wins_over_override() -> None:
    text = "Override size: 720x1440\nPhysical size: 1080x2340\n"
    assert parse_wm_size_dimensions(text) == (1080, 2340)


def test_wm_size_dimensions_malformed_or_missing_is_none() -> None:
    assert parse_wm_size_dimensions("Physical size: 1080x\n") is None
    assert parse_wm_size_dimensions("Physical size: 0x0\n") is None
    assert parse_wm_size_dimensions("Physical size: -1x2\n") is None
    assert parse_wm_size_dimensions("Physical size: abc x 2340\n") is None
    assert parse_wm_size_dimensions("Status bar height: 66\n") is None
    assert parse_wm_size_dimensions("") is None


def test_wm_override_size_parsed_when_set() -> None:
    assert parse_wm_override_size("Override size: 720x1440\n") == "720x1440"


def test_wm_override_size_absent_or_null_is_none() -> None:
    assert parse_wm_override_size("Physical size: 1080x2340\n") is None
    assert parse_wm_override_size("Override size: null\n") is None
    assert parse_wm_override_size("Override size: 720x\n") is None
    assert parse_wm_override_size("") is None


def test_wm_override_density_parsed_when_set() -> None:
    assert parse_wm_override_density("Override density: 420\n") == 420


def test_wm_override_density_absent_or_invalid_is_none() -> None:
    assert parse_wm_override_density("Physical density: 440\n") is None
    assert parse_wm_override_density("Override density: null\n") is None
    assert parse_wm_override_density("Override density: 0\n") is None
    assert parse_wm_override_density("Override density: -1\n") is None
    assert parse_wm_override_density("Override density: big\n") is None
    assert parse_wm_override_density("") is None


def test_supported_refresh_rates_distinct_and_sorted() -> None:
    text = (
        "  DisplayModeInfo{id=0, refreshRate=90.000000}\n"
        "  DisplayModeInfo{id=1, refreshRate=60.000004}\n"
        "  DisplayModeInfo{id=2, refreshRate=60.000004}\n"
    )
    assert parse_supported_refresh_rates(text) == pytest.approx((60.0, 90.0))


def test_supported_refresh_rates_ignores_current_rate_token() -> None:
    # mRefreshRate (capital R) is the CURRENT rate, not an advertised mode;
    # only the canonical lowercase DisplayModeInfo token counts.
    assert parse_supported_refresh_rates("mRefreshRate=60.000004\n") is None
    assert parse_supported_refresh_rates(
        "mRefreshRate=60.000004\nDisplayModeInfo{id=0, refreshRate=60.000004}\n"
    ) == pytest.approx((60.0,))


def test_supported_refresh_rates_ignores_invalid_tokens() -> None:
    text = "refreshRate=0\nrefreshRate=abc\nrefreshRate=-5.0\n"
    assert parse_supported_refresh_rates(text) is None


def test_supported_refresh_rates_absent_is_none() -> None:
    assert parse_supported_refresh_rates("mDisplayInfo=DisplayInfo{}\n") is None
    assert parse_supported_refresh_rates("") is None


def test_orientation_degrees_maps_surface_values() -> None:
    assert parse_orientation_degrees("SurfaceOrientation: 0\n") == 0
    assert parse_orientation_degrees("SurfaceOrientation: 1\n") == 90
    assert parse_orientation_degrees("SurfaceOrientation: 2\n") == 180
    assert parse_orientation_degrees("SurfaceOrientation: 3\n") == 270


def test_orientation_degrees_invalid_or_absent_is_none() -> None:
    assert parse_orientation_degrees("SurfaceOrientation: 9\n") is None
    assert parse_orientation_degrees("no orientation here\n") is None
    assert parse_orientation_degrees("") is None


# ---------------------------------------------------------------------------
# GPU facts
# ---------------------------------------------------------------------------


def test_gpu_gles_parses_vendor_and_renderer() -> None:
    assert parse_gpu_gles("GLES: Qualcomm, Adreno (TM) 610\n") == (
        "Qualcomm",
        "Adreno (TM) 610",
    )


def test_gpu_gles_renderer_without_vendor() -> None:
    assert parse_gpu_gles("GLES: Mali-G76 MC4\n") == (None, "Mali-G76 MC4")


def test_gpu_gles_empty_vendor_or_renderer() -> None:
    assert parse_gpu_gles("GLES: ARM, \n") == ("ARM", None)
    assert parse_gpu_gles("GLES: , Adreno\n") == (None, "Adreno")


def test_gpu_gles_first_line_wins() -> None:
    text = "GLES: ARM, Mali-G76 MC4\nGLES: Qualcomm, Adreno (TM) 610\n"
    assert parse_gpu_gles(text) == ("ARM", "Mali-G76 MC4")


def test_gpu_gles_missing_or_empty_is_none() -> None:
    assert parse_gpu_gles("Display 0 HWC layers: 2\n") == (None, None)
    assert parse_gpu_gles("GLES:\n") == (None, None)
    assert parse_gpu_gles("") == (None, None)


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


# ---------------------------------------------------------------------------
# Kernel / uptime / boot time
# ---------------------------------------------------------------------------


def test_uname_a_returns_full_first_line() -> None:
    text = "Linux localhost 4.14.186+ #1 SMP PREEMPT Wed Jun 2 12:00:00 2021 aarch64\n"
    assert parse_uname_a(text) == "Linux localhost 4.14.186+ #1 SMP PREEMPT Wed Jun 2 12:00:00 2021 aarch64"


def test_uname_a_multiline_keeps_first_line() -> None:
    assert parse_uname_a("line one\nline two\n") == "line one"


def test_uname_a_empty_is_none() -> None:
    assert parse_uname_a("") is None
    assert parse_uname_a("   \n") is None


def test_proc_uptime_parses_fractional_seconds() -> None:
    assert parse_proc_uptime("123456.78 987654.32\n") == pytest.approx(123456.78)


def test_proc_uptime_parses_integer_token() -> None:
    assert parse_proc_uptime("42 7\n") == pytest.approx(42.0)


def test_proc_uptime_malformed_or_missing_is_none() -> None:
    assert parse_proc_uptime("not-a-number 2\n") is None
    assert parse_proc_uptime("") is None
    assert parse_proc_uptime("  \n") is None


def test_proc_uptime_negative_is_none() -> None:
    assert parse_proc_uptime("-5.0 0.0\n") is None


def test_epoch_seconds_parses_int() -> None:
    assert parse_epoch_seconds("1622773057\n") == 1622773057


def test_epoch_seconds_malformed_is_none() -> None:
    assert parse_epoch_seconds("yesterday\n") is None
    assert parse_epoch_seconds("") is None


def test_boot_time_derived_when_reliable() -> None:
    boot = derive_boot_time(1622773057, 123456.78)
    assert boot == datetime.fromtimestamp(1622773057 - 123456.78, tz=timezone.utc)
    assert boot.tzinfo is not None  # UTC, unambiguous


def test_boot_time_zero_uptime_matches_device_clock() -> None:
    assert derive_boot_time(1622773057, 0.0) == datetime.fromtimestamp(
        1622773057, tz=timezone.utc
    )


def test_boot_time_unreliable_when_clock_behind_uptime() -> None:
    assert derive_boot_time(100, 200.0) is None


def test_boot_time_rejects_negative_uptime() -> None:
    assert derive_boot_time(1000, -1.0) is None


# ---------------------------------------------------------------------------
# CPU architecture / machine
# ---------------------------------------------------------------------------


def test_uname_a_machine_is_last_token() -> None:
    text = "Linux localhost 4.14.186+ #1 SMP PREEMPT Wed Jun 2 12:00:00 2021 aarch64\n"
    assert parse_uname_a_machine(text) == "aarch64"


def test_uname_a_machine_single_token() -> None:
    assert parse_uname_a_machine("aarch64\n") == "aarch64"


def test_uname_a_machine_empty_is_none() -> None:
    assert parse_uname_a_machine("") is None
    assert parse_uname_a_machine("   \n") is None


def test_cpu_64bit_mapping() -> None:
    assert derive_cpu_64bit("aarch64") is True
    assert derive_cpu_64bit("x86_64") is True
    assert derive_cpu_64bit("armv7l") is False
    assert derive_cpu_64bit("i686") is False


def test_cpu_64bit_ambiguous_or_missing_is_none() -> None:
    assert derive_cpu_64bit("armv8l") is None  # 64-bit-capable core, 32-bit world
    assert derive_cpu_64bit("sparc") is None
    assert derive_cpu_64bit(None) is None


# ---------------------------------------------------------------------------
# CPU topology
# ---------------------------------------------------------------------------


def test_cpu_range_simple_range() -> None:
    assert parse_cpu_range("0-7\n") == 8
    assert parse_cpu_range("0-3\n") == 4


def test_cpu_range_single_cpu() -> None:
    assert parse_cpu_range("4\n") == 1
    assert parse_cpu_range("0-0\n") == 1


def test_cpu_range_comma_lists() -> None:
    assert parse_cpu_range("0,1,4-7\n") == 6
    assert parse_cpu_range("0-3,8-11\n") == 8


def test_cpu_range_malformed_or_missing_is_none() -> None:
    assert parse_cpu_range("8-3\n") is None  # inverted
    assert parse_cpu_range("0-7,abc\n") is None
    assert parse_cpu_range("abc\n") is None
    assert parse_cpu_range("-1\n") is None
    assert parse_cpu_range("") is None
    assert parse_cpu_range("  \n") is None


def test_cpu_range_singleton_segments() -> None:
    assert parse_cpu_range("0-0,1-1\n") == 2  # two real CPUs, listed as ranges


def test_cpuinfo_cores_counts_processor_entries() -> None:
    text = (
        "processor\t: 0\n"
        "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
        "processor\t: 1\n"
        "Hardware\t: qcom\n"
    )
    assert parse_cpuinfo_cores(text) == 2


def test_cpuinfo_cores_missing_is_none() -> None:
    assert parse_cpuinfo_cores("Hardware\t: qcom\n") is None
    assert parse_cpuinfo_cores("") is None


def test_cpuinfo_model_name_parsed() -> None:
    text = "processor\t: 0\nmodel name\t: Qualcomm Technologies, Inc SM8250\n"
    assert parse_cpuinfo_model_name(text) == "Qualcomm Technologies, Inc SM8250"


def test_cpuinfo_model_name_missing_or_empty_is_none() -> None:
    assert parse_cpuinfo_model_name("Hardware\t: qcom\n") is None
    assert parse_cpuinfo_model_name("model name\t:   \n") is None
    assert parse_cpuinfo_model_name("") is None


# ---------------------------------------------------------------------------
# CPU frequency / governor / features
# ---------------------------------------------------------------------------


def test_cpufreq_khz_parses_int_and_zero() -> None:
    assert parse_cpufreq_khz("576000\n") == 576000
    assert parse_cpufreq_khz("0\n") == 0  # kernel-reported, valid


def test_cpufreq_khz_malformed_or_negative_is_none() -> None:
    assert parse_cpufreq_khz("-100\n") is None
    assert parse_cpufreq_khz("not-a-number\n") is None
    assert parse_cpufreq_khz("") is None


def test_khz_to_hz_converts_to_canonical_unit() -> None:
    assert khz_to_hz(576000) == 576_000_000.0
    assert khz_to_hz(2_841_600) == 2_841_600_000.0
    assert khz_to_hz(0) == 0.0


def test_governor_parsed() -> None:
    assert parse_governor("schedutil\n") == "schedutil"
    assert parse_governor("  performance  \n") == "performance"


def test_governor_empty_is_none() -> None:
    assert parse_governor("") is None
    assert parse_governor("  \n") is None


def test_cpu_features_arm_line_normalized() -> None:
    text = "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 asimddp\n"
    features = parse_cpu_features(text)
    assert features is not None
    assert features == ("fp", "asimd", "evtstrm", "aes", "pmull", "sha1", "sha2", "crc32", "asimddp")


def test_cpu_features_arm_line_duplicates_removed() -> None:
    text = "Features\t: fp asimd FP AES aes sha2\n"
    assert parse_cpu_features(text) == ("fp", "asimd", "aes", "sha2")


def test_cpu_features_x86_flags_line() -> None:
    text = "flags\t: fpu vme de pse tsc msr pae\n"
    assert parse_cpu_features(text) == ("fpu", "vme", "de", "pse", "tsc", "msr", "pae")


def test_cpu_features_missing_or_empty_is_none() -> None:
    assert parse_cpu_features("Hardware\t: qcom\n") is None
    assert parse_cpu_features("Features\t:  \n") is None
    assert parse_cpu_features("") is None
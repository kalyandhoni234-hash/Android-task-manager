"""Unit tests for the device-information parsers (pure functions).

Covers structured parsing of bulk getprop output, wm size/density, df -k,
refresh rate and orientation tokens, MAC/Android-ID normalization, and the
malformed-output tolerance every parser must have.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from android_task_manager.device.models import StorageInfo
from android_task_manager.device.parser import (
    SU_NOT_FOUND,
    collect_ipv4_addresses,
    collect_ipv6_addresses,
    derive_boot_time,
    derive_cpu_64bit,
    khz_to_hz,
    mark_default_route,
    parse_active_transport,
    parse_android_id,
    parse_bootloader_locked,
    parse_charge_full_design,
    parse_connectivity_dns,
    parse_cpu_features,
    parse_cpu_hardware_line,
    parse_cpu_range,
    parse_cpufreq_khz,
    parse_cpuinfo_cores,
    parse_cpuinfo_model_name,
    parse_cycle_count,
    parse_df_k,
    parse_encryption_state,
    parse_encryption_type,
    parse_epoch_seconds,
    parse_getprop_output,
    parse_governor,
    parse_gpu_gles,
    parse_ip_addr,
    parse_ip_route,
    parse_mac_address,
    parse_max_frequency_khz,
    parse_mounts_filesystem,
    parse_orientation,
    parse_orientation_degrees,
    parse_proc_uptime,
    parse_property_bool,
    parse_refresh_rate,
    parse_root_status,
    parse_security_patch_date,
    parse_selinux_status,
    parse_supported_refresh_rates,
    parse_uname_a,
    parse_uname_a_machine,
    parse_verified_boot_state,
    parse_verity_mode,
    parse_vpn_state,
    parse_wifi_bssid,
    parse_wifi_connected,
    parse_wifi_enabled,
    parse_wifi_frequency,
    parse_wifi_link_speed,
    parse_wifi_rssi,
    parse_wifi_ssid,
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
# Battery static facts / storage filesystem
# ---------------------------------------------------------------------------


def test_charge_full_design_parses_positive_int() -> None:
    assert parse_charge_full_design("4880000\n") == 4880000


def test_charge_full_design_invalid_is_none() -> None:
    assert parse_charge_full_design("0\n") is None
    assert parse_charge_full_design("-100\n") is None
    assert parse_charge_full_design("lots\n") is None
    assert parse_charge_full_design("") is None


def test_cycle_count_parses_non_negative_int() -> None:
    assert parse_cycle_count("412\n") == 412
    assert parse_cycle_count("0\n") == 0  # a new battery


def test_cycle_count_invalid_is_none() -> None:
    assert parse_cycle_count("-1\n") is None
    assert parse_cycle_count("many\n") is None
    assert parse_cycle_count("") is None


def test_mounts_filesystem_found_for_data() -> None:
    text = "rootfs / rootfs rw 0 0\n/dev/block/dm-5 /data ext4 rw,seclabel,nosuid 0 0\n"
    assert parse_mounts_filesystem(text, ("/data", "/data/user/0")) == "ext4"


def test_mounts_filesystem_accepts_fbe_user_view() -> None:
    text = "/dev/block/dm-5 /data/user/0 f2fs rw 0 0\n"
    assert parse_mounts_filesystem(text, ("/data", "/data/user/0")) == "f2fs"


def test_mounts_filesystem_first_matching_line_wins() -> None:
    text = (
        "/dev/block/dm-5 /data/user/0 f2fs rw 0 0\n"
        "/dev/block/dm-5 /data ext4 rw 0 0\n"
    )
    assert parse_mounts_filesystem(text, ("/data", "/data/user/0")) == "f2fs"


def test_mounts_filesystem_missing_is_none() -> None:
    text = "rootfs / rootfs rw 0 0\n/dev/block/dm-0 /system ext4 ro 0 0\n"
    assert parse_mounts_filesystem(text, ("/data", "/data/user/0")) is None
    assert parse_mounts_filesystem("", ("/data",)) is None


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


# ---------------------------------------------------------------------------
# Phase 2E: network interfaces (ip addr)
# ---------------------------------------------------------------------------

_IP_ADDR_SAMPLE = (
    "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN "
    "group default qlen 1000\n"
    "    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00\n"
    "    inet 127.0.0.1/8 scope host lo\n"
    "    inet6 ::1/128 scope host\n"
    "2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state "
    "UP group default qlen 1000\n"
    "    link/ether 3C:28:6D:AB:CD:EF brd ff:ff:ff:ff:ff:ff\n"
    "    inet 192.168.50.10/24 brd 192.168.50.255 scope global wlan0\n"
    "    inet6 fe80::3c28:6dff:feab:cdef/64 scope link\n"
    "3: rmnet0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN "
    "group default qlen 1000\n"
    "    link/ether 92:e2:ba:10:81:77 brd ff:ff:ff:ff:ff:ff\n"
)


def test_ip_addr_parses_multiple_interfaces() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    assert [i.name for i in interfaces] == ["lo", "wlan0", "rmnet0"]


def test_ip_addr_interface_types_classified() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    by_name = {i.name: i for i in interfaces}
    assert by_name["lo"].interface_type == "Loopback"
    assert by_name["wlan0"].interface_type == "Wi-Fi"
    assert by_name["rmnet0"].interface_type == "Cellular"


def test_ip_addr_up_state_from_flags() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    by_name = {i.name: i for i in interfaces}
    assert by_name["lo"].is_up is True
    assert by_name["wlan0"].is_up is True
    assert by_name["rmnet0"].is_up is False


def test_ip_addr_loopback_has_no_mac() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    assert interfaces[0].mac_address is None  # lo has no hardware address


def test_ip_addr_mac_normalized_to_lowercase() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    wlan0 = interfaces[1]
    assert wlan0.mac_address == "3c:28:6d:ab:cd:ef"
    assert interfaces[2].mac_address == "92:e2:ba:10:81:77"


def test_ip_addr_ipv4_addresses_with_prefix() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    assert interfaces[0].ipv4_addresses == ("127.0.0.1/8",)
    assert interfaces[1].ipv4_addresses == ("192.168.50.10/24",)
    assert interfaces[2].ipv4_addresses == ()


def test_ip_addr_ipv6_addresses_with_prefix() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    assert interfaces[0].ipv6_addresses == ("::1/128",)
    assert interfaces[1].ipv6_addresses == ("fe80::3c28:6dff:feab:cdef/64",)
    assert interfaces[2].ipv6_addresses == ()


def test_ip_addr_missing_is_none() -> None:
    assert parse_ip_addr("") is None
    assert parse_ip_addr("sh: ip: not found\n") is None
    assert parse_ip_addr("  \n") is None


def test_ip_addr_malformed_lines_skipped() -> None:
    text = (
        "garbage before any interface\n"
        "2: wlan0: <UP> mtu 1500\n"
        "    link/ether not-a-mac brd 00:00:00:00:00:00\n"
        "    inet not-an-ip/24 scope global wlan0\n"
        "    inet6 fe80::1/129 scope link\n"
        "    inet 192.168.1.5/24 scope global wlan0\n"
    )
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    assert len(interfaces) == 1
    wlan0 = interfaces[0]
    assert wlan0.name == "wlan0"
    assert wlan0.mac_address is None  # malformed MAC ignored
    assert wlan0.ipv4_addresses == ("192.168.1.5/24",)  # valid line survives
    assert wlan0.ipv6_addresses == ()  # /129 invalid for IPv6


def test_ip_addr_placeholder_mac_is_none() -> None:
    text = (
        "2: wlan0: <UP> mtu 1500\n"
        "    link/ether 02:00:00:00:00:00 brd ff:ff:ff:ff:ff:ff\n"
    )
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    assert interfaces[0].mac_address is None


def test_ip_addr_unknown_interface_is_other() -> None:
    text = "4: veth123: <UP> mtu 1500\n    link/ether aa:bb:cc:dd:ee:ff brd 00:00:00:00:00:00\n"
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    assert interfaces[0].interface_type == "Other"


def test_ip_addr_known_vpn_prefix_classified() -> None:
    text = "4: tun0: <UP> mtu 1500\n    link/ether aa:bb:cc:dd:ee:ff brd 00:00:00:00:00:00\n"
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    assert interfaces[0].interface_type == "VPN"


def test_ip_addr_interface_without_address_lines() -> None:
    text = "2: eth0: <UP> mtu 1500\n"
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    assert interfaces[0].name == "eth0"
    assert interfaces[0].interface_type == "Ethernet"
    assert interfaces[0].ipv4_addresses == ()
    assert interfaces[0].ipv6_addresses == ()


def test_ip_addr_invalid_prefix_drops_address() -> None:
    text = (
        "2: wlan0: <UP> mtu 1500\n"
        "    inet 192.168.1.5/33 scope global wlan0\n"
        "    inet 192.168.1.6/abc scope global wlan0\n"
        "    inet 192.168.1.7 scope global wlan0\n"
    )
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    # /33 and /abc are malformed; a bare valid address is accepted.
    assert interfaces[0].ipv4_addresses == ("192.168.1.7",)


def test_ip_addr_invalid_ipv4_dropped() -> None:
    text = (
        "2: wlan0: <UP> mtu 1500\n"
        "    inet 999.1.1.1/24 scope global wlan0\n"
        "    inet 10.0.0.2/24 scope global wlan0\n"
    )
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    assert interfaces[0].ipv4_addresses == ("10.0.0.2/24",)


def test_ip_addr_multiple_ipv4_addresses_kept() -> None:
    text = (
        "2: eth0: <UP> mtu 1500\n"
        "    inet 10.0.0.2/24 scope global eth0\n"
        "    inet 10.0.0.3/24 scope global eth0\n"
        "    inet6 fe80::1/64 scope link\n"
        "    inet6 2001:db8::1/64 scope global\n"
    )
    interfaces = parse_ip_addr(text)
    assert interfaces is not None
    eth0 = interfaces[0]
    assert eth0.ipv4_addresses == ("10.0.0.2/24", "10.0.0.3/24")
    assert eth0.ipv6_addresses == ("fe80::1/64", "2001:db8::1/64")


def test_mark_default_route_flags_matching_interface() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    marked = mark_default_route(interfaces, "wlan0")
    by_name = {i.name: i for i in marked}
    assert by_name["wlan0"].is_default_route is True
    assert by_name["lo"].is_default_route is False
    assert by_name["rmnet0"].is_default_route is False


def test_mark_default_route_without_route_flags_none() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    marked = mark_default_route(interfaces, None)
    assert all(i.is_default_route is False for i in marked)


def test_collect_ipv4_excludes_loopback() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    assert collect_ipv4_addresses(interfaces) == ("192.168.50.10",)


def test_collect_ipv6_excludes_loopback() -> None:
    interfaces = parse_ip_addr(_IP_ADDR_SAMPLE)
    assert interfaces is not None
    assert collect_ipv6_addresses(interfaces) == ("fe80::3c28:6dff:feab:cdef",)


def test_collect_addresses_missing_is_none() -> None:
    assert collect_ipv4_addresses(()) is None
    assert collect_ipv6_addresses(()) is None


# ---------------------------------------------------------------------------
# Phase 2E: routes (ip route)
# ---------------------------------------------------------------------------


def test_ip_route_default_via() -> None:
    assert parse_ip_route(
        "default via 192.168.50.1 dev wlan0 proto static metric 10\n"
    ) == ("192.168.50.1", "wlan0", 10)


def test_ip_route_default_without_metric() -> None:
    assert parse_ip_route("default via 192.168.50.1 dev wlan0\n") == (
        "192.168.50.1",
        "wlan0",
        None,
    )


def test_ip_route_default_link_scope_no_gateway() -> None:
    assert parse_ip_route("default dev tun0 scope link\n") == (None, "tun0", None)


def test_ip_route_default_ipv6_gateway() -> None:
    assert parse_ip_route("default via fe80::1 dev wlan0 metric 20\n") == (
        "fe80::1",
        "wlan0",
        20,
    )


def test_ip_route_non_default_lines_ignored() -> None:
    text = (
        "192.168.50.0/24 dev wlan0 proto static scope link metric 10\n"
        "default via 192.168.50.1 dev wlan0 proto static metric 10\n"
    )
    assert parse_ip_route(text) == ("192.168.50.1", "wlan0", 10)


def test_ip_route_missing_is_none() -> None:
    assert parse_ip_route("") is None
    assert parse_ip_route("sh: ip: not found\n") is None
    assert parse_ip_route("192.168.50.0/24 dev wlan0 proto static\n") is None


def test_ip_route_malformed_gateway_ignored() -> None:
    assert parse_ip_route("default via not-an-ip dev wlan0\n") is None
    assert parse_ip_route("default via 999.1.1.1 dev wlan0\n") is None


def test_ip_route_malformed_metric_is_none() -> None:
    assert parse_ip_route("default via 192.168.50.1 dev wlan0 metric lots\n") == (
        "192.168.50.1",
        "wlan0",
        None,
    )


# ---------------------------------------------------------------------------
# Phase 2E: Wi-Fi state (dumpsys wifi)
# ---------------------------------------------------------------------------

_WIFI_CONNECTED = (
    "Wi-Fi is enabled\n"
    "mWifiInfo SSID: \"HomeWiFi\", BSSID: aa:bb:cc:dd:ee:ff, "
    "MAC: 02:00:00:00:00:00, IP: 192.168.50.10/24, "
    "Supplicant state: COMPLETED, Link speed: 866Mbps, "
    "Frequency: 5180MHz, RSSI: -45\n"
    "mNetworkInfo=NetworkInfo: type: WIFI[], state: CONNECTED/CONNECTED, "
    "reason: (unspecified)\n"
)


def test_wifi_enabled() -> None:
    assert parse_wifi_enabled("Wi-Fi is enabled\n") is True
    assert parse_wifi_enabled("Wi-Fi is disabled\n") is False


def test_wifi_enabled_fallback_token() -> None:
    assert parse_wifi_enabled("mWifiEnabled=true\n") is True
    assert parse_wifi_enabled("mWifiEnabled=false\n") is False


def test_wifi_enabled_missing_is_none() -> None:
    assert parse_wifi_enabled("") is None
    assert parse_wifi_enabled("no state here\n") is None


def test_wifi_connected_state() -> None:
    assert parse_wifi_connected(_WIFI_CONNECTED) is True
    assert parse_wifi_connected("NetworkInfo: type: WIFI[], state: DISCONNECTED/DISCONNECTED\n") is False


def test_wifi_connected_intermediate_state_is_none() -> None:
    assert (
        parse_wifi_connected(
            "NetworkInfo: type: WIFI[], state: CONNECTING/CONNECTING\n"
        )
        is None
    )


def test_wifi_connected_missing_is_none() -> None:
    assert parse_wifi_connected("Wi-Fi is enabled\n") is None
    assert parse_wifi_connected("") is None


def test_wifi_connected_malformed_state_is_none() -> None:
    assert parse_wifi_connected("mNetworkInfo=NetworkInfo: type: WIFI[], state: ???\n") is None


def test_wifi_ssid_parsed() -> None:
    assert parse_wifi_ssid(_WIFI_CONNECTED) == "HomeWiFi"


def test_wifi_ssid_current_network_section() -> None:
    text = "Current network info: SSID: \"OfficeNet\", BSSID: aa:bb:cc:dd:ee:ff\n"
    assert parse_wifi_ssid(text) == "OfficeNet"


def test_wifi_ssid_redacted_is_none() -> None:
    text = "Wi-Fi is enabled\nmWifiInfo SSID: <ssid>, BSSID: aa:bb:cc:dd:ee:ff\n"
    assert parse_wifi_ssid(text) is None


def test_wifi_ssid_unknown_placeholder_is_none() -> None:
    text = 'mWifiInfo SSID: "<unknown ssid>", BSSID: aa:bb:cc:dd:ee:ff\n'
    assert parse_wifi_ssid(text) is None


def test_wifi_ssid_empty_or_missing_is_none() -> None:
    assert parse_wifi_ssid('mWifiInfo SSID: "", BSSID: aa:bb:cc:dd:ee:ff\n') is None
    assert parse_wifi_ssid("Wi-Fi is enabled\n") is None
    assert parse_wifi_ssid("") is None


def test_wifi_ssid_scan_result_never_matches() -> None:
    # Scan results are other networks and use their own section; the parser
    # only reads the current-connection line.
    text = (
        "Scan results:\n"
        "BSSID: aa:bb:cc:dd:ee:ff SSID: \"NeighborNet\", level: -70\n"
    )
    assert parse_wifi_ssid(text) is None


def test_wifi_bssid_parsed_and_normalized() -> None:
    assert parse_wifi_bssid(_WIFI_CONNECTED) == "aa:bb:cc:dd:ee:ff"
    text = 'mWifiInfo SSID: "x", BSSID: AA:BB:CC:DD:EE:FF\n'
    assert parse_wifi_bssid(text) == "aa:bb:cc:dd:ee:ff"


def test_wifi_bssid_placeholder_or_malformed_is_none() -> None:
    text = 'mWifiInfo SSID: "x", BSSID: 02:00:00:00:00:00\n'
    assert parse_wifi_bssid(text) is None
    assert parse_wifi_bssid('mWifiInfo SSID: "x", BSSID: broken\n') is None


def test_wifi_bssid_missing_is_none() -> None:
    assert parse_wifi_bssid("Wi-Fi is enabled\n") is None
    assert parse_wifi_bssid("") is None


def test_wifi_frequency_parsed() -> None:
    assert parse_wifi_frequency(_WIFI_CONNECTED) == 5180
    text = "Current network info: SSID: \"x\", Frequency: 2400MHz\n"
    assert parse_wifi_frequency(text) == 2400


def test_wifi_frequency_fallback_token() -> None:
    assert parse_wifi_frequency("mFrequency=5180\n") == 5180


def test_wifi_frequency_zero_negative_or_malformed_is_none() -> None:
    assert parse_wifi_frequency("mWifiInfo SSID: \"x\", Frequency: 0MHz\n") is None
    assert parse_wifi_frequency("mWifiInfo SSID: \"x\", Frequency: -5MHz\n") is None
    assert parse_wifi_frequency("mFrequency=0\n") is None
    assert parse_wifi_frequency("mFrequency=abc\n") is None


def test_wifi_frequency_missing_is_none() -> None:
    assert parse_wifi_frequency("Wi-Fi is enabled\n") is None
    assert parse_wifi_frequency("") is None


def test_wifi_frequency_scan_result_token_ignored() -> None:
    # Scan results use lowercase "frequency:" — never the connected network.
    text = 'Scan results:\nBSSID: aa:bb:cc:dd:ee:ff SSID: "x", frequency: 5180\n'
    assert parse_wifi_frequency(text) is None


def test_wifi_link_speed_parsed() -> None:
    assert parse_wifi_link_speed(_WIFI_CONNECTED) == pytest.approx(866.0)
    text = 'mWifiInfo SSID: "x", Link speed: 866Mbps, Frequency: 5180MHz\n'
    assert parse_wifi_link_speed(text) == pytest.approx(866.0)


def test_wifi_link_speed_fallback_token() -> None:
    assert parse_wifi_link_speed("mLinkSpeed=144\n") == pytest.approx(144.0)


def test_wifi_link_speed_zero_negative_or_malformed_is_none() -> None:
    assert parse_wifi_link_speed('mWifiInfo SSID: "x", Link speed: 0Mbps\n') is None
    assert parse_wifi_link_speed('mWifiInfo SSID: "x", Link speed: -3Mbps\n') is None
    assert parse_wifi_link_speed("mLinkSpeed=abc\n") is None


def test_wifi_link_speed_missing_is_none() -> None:
    assert parse_wifi_link_speed("Wi-Fi is enabled\n") is None
    assert parse_wifi_link_speed("") is None


def test_wifi_rssi_parsed_negative() -> None:
    assert parse_wifi_rssi(_WIFI_CONNECTED) == -45
    text = 'mWifiInfo SSID: "x", RSSI: -67\n'
    assert parse_wifi_rssi(text) == -67


def test_wifi_rssi_fallback_token() -> None:
    assert parse_wifi_rssi("mRssi=-45\n") == -45


def test_wifi_rssi_out_of_range_or_malformed_is_none() -> None:
    assert parse_wifi_rssi('mWifiInfo SSID: "x", RSSI: +5\n') is None
    assert parse_wifi_rssi('mWifiInfo SSID: "x", RSSI: -200\n') is None
    assert parse_wifi_rssi("mRssi=abc\n") is None


def test_wifi_rssi_missing_is_none() -> None:
    assert parse_wifi_rssi("Wi-Fi is enabled\n") is None
    assert parse_wifi_rssi("") is None


def test_wifi_rssi_scan_result_token_ignored() -> None:
    # Scan results report "level:" — the current-network RSSI is separate.
    text = 'Scan results:\nBSSID: aa:bb:cc:dd:ee:ff SSID: "x", level: -70\n'
    assert parse_wifi_rssi(text) is None


# ---------------------------------------------------------------------------
# Phase 2E: connectivity (dumpsys connectivity)
# ---------------------------------------------------------------------------

_CONNECTIVITY_BLOCK = (
    "ConnectivityService state:\n"
    "  NetworkAgentInfos:\n"
    "    100 NetworkAgentInfo{ [WIFI () - 100]  id=100, uptimeMs=86400000 }\n"
    "      LinkProperties: {InterfaceName: wlan0 "
    "LinkAddresses: [ 192.168.50.10/24 ] "
    "DnsAddresses: [ 192.168.50.1, 9.9.9.9 ] MTU: 1500 "
    "Routes: [ 0.0.0.0/0 -> 192.168.50.1 wlan0 ]}\n"
    "  Active default network: 100\n"
)


def test_active_transport_bare_id_form() -> None:
    assert parse_active_transport(_CONNECTIVITY_BLOCK) == "Wi-Fi"


def test_active_transport_inline_form() -> None:
    text = (
        "  Active default network: NetworkAgentInfo{ [CELLULAR () - 42] "
        "id=42, linkProperties=[{}]}\n"
    )
    assert parse_active_transport(text) == "Cellular"


def test_active_transport_ethernet_and_vpn_tokens() -> None:
    assert (
        parse_active_transport(
            "Active default network: NetworkAgentInfo{ [ETHERNET () - 1] }\n"
        )
        == "Ethernet"
    )
    assert (
        parse_active_transport(
            "Active default network: NetworkAgentInfo{ [VPN () - 2] }\n"
        )
        == "VPN"
    )


def test_active_transport_unknown_token_is_other() -> None:
    assert (
        parse_active_transport(
            "Active default network: NetworkAgentInfo{ [UNKNOWNX () - 3] }\n"
        )
        == "Other"
    )


def test_active_transport_null_or_missing_is_none() -> None:
    assert parse_active_transport("Active default network: null\n") is None
    assert parse_active_transport("ConnectivityService state:\n") is None
    assert parse_active_transport("") is None


def test_connectivity_dns_bare_id_form() -> None:
    assert parse_connectivity_dns(_CONNECTIVITY_BLOCK) == (
        "192.168.50.1",
        "9.9.9.9",
    )


def test_connectivity_dns_inline_form() -> None:
    text = (
        "Active default network: NetworkAgentInfo{ [WIFI () - 100] "
        "linkProperties=[{InterfaceName: wlan0 "
        "DnsAddresses: [ 192.168.50.1, 8.8.8.8 ] Routes: [ ] }] }\n"
    )
    assert parse_connectivity_dns(text) == ("192.168.50.1", "8.8.8.8")


def test_connectivity_dns_alternate_token_names() -> None:
    text = (
        "Active default network: NetworkAgentInfo{ [WIFI () - 100] "
        "linkProperties=[{DnsServers: [ 192.168.50.1 ]}] }\n"
    )
    assert parse_connectivity_dns(text) == ("192.168.50.1",)
    text = (
        "Active default network: NetworkAgentInfo{ [WIFI () - 100] "
        "linkProperties=[{DNS servers: [ 192.168.50.1 ]}] }\n"
    )
    assert parse_connectivity_dns(text) == ("192.168.50.1",)


def test_connectivity_dns_malformed_entries_dropped() -> None:
    text = (
        "Active default network: NetworkAgentInfo{ [WIFI () - 100] "
        "linkProperties=[{DnsAddresses: [ 192.168.50.1, not-an-ip, 999.1.1.1 ]}] }\n"
    )
    assert parse_connectivity_dns(text) == ("192.168.50.1",)


def test_connectivity_dns_missing_is_none() -> None:
    assert parse_connectivity_dns("Active default network: null\n") is None
    assert parse_connectivity_dns("ConnectivityService state:\n") is None
    assert parse_connectivity_dns("") is None


def test_connectivity_dns_wrong_network_ignored() -> None:
    # DNS is only reported for the ACTIVE network, never a secondary one.
    text = (
        "ConnectivityService state:\n"
        "  100 NetworkAgentInfo{ [WIFI () - 100]  id=100 }\n"
        "      LinkProperties: {InterfaceName: wlan0 "
        "DnsAddresses: [ 192.168.50.1 ]}\n"
        "  101 NetworkAgentInfo{ [VPN () - 101]  id=101 }\n"
        "      LinkProperties: {InterfaceName: tun0 "
        "DnsAddresses: [ 10.0.0.1 ]}\n"
        "  Active default network: 101\n"
    )
    assert parse_connectivity_dns(text) == ("10.0.0.1",)


# ---------------------------------------------------------------------------
# Phase 2E: VPN (dumpsys vpn)
# ---------------------------------------------------------------------------


def test_vpn_state_disconnected() -> None:
    assert parse_vpn_state("VPN state: disconnected\n") == (False, None)


def test_vpn_state_connected_with_interface() -> None:
    text = (
        "VPN state: connected\n"
        "VPN connected: {\n"
        "  interface: tun0\n"
        "  source: com.example.vpn\n"
        "}\n"
    )
    assert parse_vpn_state(text) == (True, "tun0")


def test_vpn_state_connected_without_interface() -> None:
    assert parse_vpn_state("VPN state: connected\n") == (True, None)


def test_vpn_state_case_insensitive() -> None:
    assert parse_vpn_state("Vpn state: connected\n") == (True, None)


def test_vpn_state_unavailable() -> None:
    assert parse_vpn_state("") == (None, None)
    assert parse_vpn_state("dumpsys: unknown service vpn\n") == (None, None)


# ---------------------------------------------------------------------------
# Security posture (Phase 2F): SELinux
# ---------------------------------------------------------------------------


def test_selinux_status_canonical_modes() -> None:
    assert parse_selinux_status("Enforcing\n") == "enforcing"
    assert parse_selinux_status("Permissive") == "permissive"
    assert parse_selinux_status("Disabled\n") == "disabled"


def test_selinux_status_case_and_whitespace_tolerated() -> None:
    assert parse_selinux_status("  ENFORCING  \n") == "enforcing"
    assert parse_selinux_status("permissive\r\n") == "permissive"


def test_selinux_status_malformed_is_none() -> None:
    assert parse_selinux_status("permissive-ish\n") is None
    assert parse_selinux_status("maybe\n") is None
    assert parse_selinux_status("") is None


def test_selinux_status_failure_is_none_never_disabled() -> None:
    # A failed read (None) must NOT be interpreted as "disabled".
    assert parse_selinux_status(None) is None


# ---------------------------------------------------------------------------
# Security posture (Phase 2F): verified boot / verity
# ---------------------------------------------------------------------------


def test_verified_boot_state_all_android_states() -> None:
    for state in ("green", "yellow", "orange", "red"):
        assert parse_verified_boot_state(state) == state


def test_verified_boot_state_normalized_lowercase() -> None:
    assert parse_verified_boot_state("ORANGE") == "orange"


def test_verified_boot_state_missing_or_malformed_is_none() -> None:
    assert parse_verified_boot_state(None) is None
    assert parse_verified_boot_state("blue") is None
    assert parse_verified_boot_state("") is None


def test_verity_mode_all_modes() -> None:
    for mode in ("enforcing", "eio", "logging", "disabled"):
        assert parse_verity_mode(mode) == mode


def test_verity_mode_missing_or_malformed_is_none() -> None:
    assert parse_verity_mode(None) is None
    assert parse_verity_mode("off") is None
    assert parse_verity_mode("") is None


# ---------------------------------------------------------------------------
# Security posture (Phase 2F): bootloader lock state
# ---------------------------------------------------------------------------


def test_bootloader_locked_primary_property() -> None:
    assert parse_bootloader_locked("1", None) is True
    assert parse_bootloader_locked("0", None) is False
    assert parse_bootloader_locked("true", None) is True
    assert parse_bootloader_locked("false", None) is False


def test_bootloader_locked_vbmeta_corroboration() -> None:
    assert parse_bootloader_locked(None, "locked") is True
    assert parse_bootloader_locked(None, "unlocked") is False
    assert parse_bootloader_locked(None, "LOCKED") is True


def test_bootloader_locked_agreeing_sources() -> None:
    assert parse_bootloader_locked("1", "locked") is True
    assert parse_bootloader_locked("0", "unlocked") is False


def test_bootloader_locked_conflicting_sources_is_none() -> None:
    # Contradictory evidence is UNKNOWN, never resolved by guessing.
    assert parse_bootloader_locked("1", "unlocked") is None
    assert parse_bootloader_locked("0", "locked") is None


def test_bootloader_locked_malformed_or_missing_is_none() -> None:
    assert parse_bootloader_locked(None, None) is None
    assert parse_bootloader_locked("2", None) is None
    assert parse_bootloader_locked(None, "floating") is None
    assert parse_bootloader_locked("", "") is None


# ---------------------------------------------------------------------------
# Security posture (Phase 2F): root evidence
# ---------------------------------------------------------------------------


def test_root_status_session_running_as_root() -> None:
    assert (
        parse_root_status(
            "uid=0(root) gid=0(root) groups=0(root)\n", SU_NOT_FOUND + "\n"
        )
        == "ROOT_EVIDENCE"
    )


def test_root_status_su_on_path_is_evidence() -> None:
    assert (
        parse_root_status(
            "uid=2000(shell) gid=2000(shell) groups=2000(shell)\n",
            "/system/xbin/su\n",
        )
        == "ROOT_EVIDENCE"
    )


def test_root_status_no_evidence_from_both_sources() -> None:
    assert (
        parse_root_status(
            "uid=2000(shell) gid=2000(shell) groups=2000(shell)\n",
            SU_NOT_FOUND + "\n",
        )
        == "NO_ROOT_EVIDENCE"
    )


def test_root_status_su_not_found_without_id_is_no_evidence() -> None:
    assert parse_root_status(None, SU_NOT_FOUND + "\n") == "NO_ROOT_EVIDENCE"


def test_root_status_id_unparseable_with_marker_is_no_evidence() -> None:
    assert parse_root_status("garbage\n", SU_NOT_FOUND + "\n") == "NO_ROOT_EVIDENCE"


def test_root_status_all_sources_failed_is_none() -> None:
    assert parse_root_status(None, None) is None


def test_root_status_empty_su_output_is_ambiguous() -> None:
    # Empty output is neither a path nor the marker: UNKNOWN, not a claim.
    assert parse_root_status(None, "") is None


def test_root_status_shell_error_text_is_not_evidence() -> None:
    # "...: not found" is shell error text, not a located path: it must
    # never become ROOT_EVIDENCE and without other sources stays UNKNOWN.
    assert parse_root_status(None, "command -v: su: not found\n") is None


# ---------------------------------------------------------------------------
# Security posture (Phase 2F): build security properties
# ---------------------------------------------------------------------------


def test_property_bool_numeric_and_word_values() -> None:
    assert parse_property_bool("1") is True
    assert parse_property_bool("0") is False
    assert parse_property_bool("true") is True
    assert parse_property_bool("false") is False


def test_property_bool_case_and_whitespace_tolerated() -> None:
    assert parse_property_bool(" TRUE \n") is True


def test_property_bool_missing_or_malformed_is_none() -> None:
    assert parse_property_bool(None) is None
    assert parse_property_bool("maybe") is None
    assert parse_property_bool("") is None


def test_security_patch_date_parses_valid() -> None:
    assert parse_security_patch_date("2026-08-01") == date(2026, 8, 1)
    assert parse_security_patch_date(" 2021-06-01\n") == date(2021, 6, 1)


def test_security_patch_date_rejects_malformed() -> None:
    assert parse_security_patch_date("2026/08/01") is None
    assert parse_security_patch_date("2026-99-99") is None
    assert parse_security_patch_date("Aug 2026") is None
    assert parse_security_patch_date("") is None
    assert parse_security_patch_date(None) is None


# ---------------------------------------------------------------------------
# Security posture (Phase 2F): encryption
# ---------------------------------------------------------------------------


def test_encryption_state_parses() -> None:
    assert parse_encryption_state("encrypted") == "encrypted"
    assert parse_encryption_state("unencrypted") == "unencrypted"
    assert parse_encryption_state("ENCRYPTED") == "encrypted"


def test_encryption_state_unknown_or_malformed_is_none() -> None:
    assert parse_encryption_state(None) is None
    assert parse_encryption_state("encryptedish") is None
    assert parse_encryption_state("") is None


def test_encryption_type_parses() -> None:
    assert parse_encryption_type("file") == "file"
    assert parse_encryption_type("block") == "block"
    assert parse_encryption_type("BLOCK") == "block"


def test_encryption_type_unknown_or_malformed_is_none() -> None:
    assert parse_encryption_type(None) is None
    assert parse_encryption_type("inline") is None
    assert parse_encryption_type("") is None
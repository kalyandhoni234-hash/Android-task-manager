"""Collector tests: structured device-information reads through a fake runner.

No real device: ``DeviceRunner`` serves canned raw ADB output per scenario.
Verifies that the collector normalizes every field, tolerates missing and
malformed values, never aborts on a single failed read, and only propagates
a total failure (the first bulk getprop read) to the connection layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication

from android_task_manager.adb.exceptions import ADBCommandError
from android_task_manager.device import DeviceInfoCollector
from android_task_manager.device.models import DeviceInformation, StorageInfo
from android_task_manager.gui.monitor import MonitorWorker
from tests import device_fixtures as fx


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def collect(scenario: str, runner=None) -> DeviceInformation:
    runner = runner or fx.DeviceRunner(fx.scenario(scenario))
    return DeviceInfoCollector(runner).sample()


def test_normal_device_full_snapshot() -> None:
    info = collect("normal")
    assert info.manufacturer == "vivo"
    assert info.brand == "vivo"
    assert info.model == "V2026"
    assert info.device == "PD2026F"
    assert info.product == "PD2026F_EX_A"
    assert info.board == "kona"
    assert info.hardware == "qcom"
    assert info.soc == "Qualcomm SM8250"
    assert info.android_version == "11"
    assert info.api_level == "30"
    assert info.security_patch == "2021-06-01"
    assert info.build_id == "RP1A.200720.012"
    assert "PD2026F_EX_A_11_W" in info.build_number
    assert "vivo/PD2026F_EX_A" in info.build_fingerprint
    assert info.build_tags == "release-keys"
    assert info.build_type == "user"
    assert info.bootloader == "UFS"
    assert info.baseband == "MPSS.JO.4.7.c2-00125-8937_GEN_PACK-1.10"
    assert info.kernel == "4.14.186+"  # uname -r
    assert info.kernel_version == (
        "Linux localhost 4.14.186+ #1 SMP PREEMPT Wed Jun 2 12:00:00 2021 aarch64"
    )
    assert info.uptime_seconds == pytest.approx(123456.78)
    assert info.boot_time == datetime.fromtimestamp(
        1622773057 - 123456.78, tz=timezone.utc
    )
    assert info.boot_time.tzinfo is not None  # UTC, unambiguous
    assert info.processor == "SM8250"  # ro.soc.model
    assert info.architecture == "arm64-v8a"
    assert info.cpu_architecture == "aarch64"  # uname -a machine token
    assert info.cpu_64bit is True
    assert info.cpu_abis == ("arm64-v8a", "armeabi-v7a", "armeabi")
    assert info.cpu_core_count == 8  # /sys present range
    assert info.cpu_online_cores == 8
    assert info.cpu_offline_cores == 0
    assert info.cpu_governor == "schedutil"
    assert info.cpu_current_frequency_hz == pytest.approx(576_000_000.0)
    assert info.cpu_min_frequency_hz == pytest.approx(300_000_000.0)
    assert info.cpu_max_frequency_hz == pytest.approx(2_841_600_000.0)
    assert "aes" in info.cpu_features
    assert "sha2" in info.cpu_features
    assert "crc32" in info.cpu_features
    assert "asimd" in info.cpu_features
    assert info.max_frequency_khz == 2841600  # cpuinfo_max_freq, unchanged
    assert info.max_frequency_khz == 2841600
    assert info.resolution == "1080x2340"
    assert info.density_dpi == 440
    assert info.refresh_rate_hz == pytest.approx(60.0)
    assert info.orientation == "Portrait"
    assert info.display_width_px == 1080
    assert info.display_height_px == 2340
    assert info.display_override_resolution is None
    assert info.display_override_density is None
    assert info.display_orientation_degrees == 0
    assert info.supported_refresh_rates_hz == pytest.approx((60.000004, 90.0))
    assert info.gpu_vendor == "Qualcomm"
    assert info.gpu_model == "Adreno (TM) 610"
    assert info.android_id == "a1b2c3d4e5f60718"
    assert info.wifi_mac == "3c:28:6d:ab:cd:ef"
    assert info.bluetooth_mac == "aa:bb:cc:dd:ee:ff"
    assert isinstance(info.storage, StorageInfo)
    assert info.storage.mount == "/data"
    assert info.storage.total_kb == 121934848
    assert info.storage.used_percent == pytest.approx(56.69, abs=0.1)


def test_kernel_version_comes_from_uname() -> None:
    runner = fx.DeviceRunner({**fx.scenario("normal"), "uname -r": "4.14.186+\n"})
    info = DeviceInfoCollector(runner).sample()
    assert info.kernel == "4.14.186+"


def test_build_tags_and_type_come_from_properties() -> None:
    info = collect("normal")
    assert info.build_tags == "release-keys"
    assert info.build_type == "user"


def test_missing_build_metadata_becomes_none() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "getprop": fx.scenario("normal")["getprop"]
            .replace("[ro.build.tags]: [release-keys]\n", "")
            .replace("[ro.build.type]: [user]\n", "[ro.build.type]: [   ]\n"),
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.build_tags is None  # key absent
    assert info.build_type is None  # whitespace-only value
    assert info.build_id == "RP1A.200720.012"  # rest intact


def test_system_facts_unavailable_degrade_to_none() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "uname -a": "FAILURE",
            "cat /proc/uptime": "FAILURE",
            "date +%s": "FAILURE",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.kernel_version is None
    assert info.uptime_seconds is None
    assert info.boot_time is None
    assert info.kernel == "4.14.186+"  # independent read survives
    assert info.model == "V2026"


def test_boot_time_requires_device_clock() -> None:
    runner = fx.DeviceRunner({**fx.scenario("normal"), "date +%s": "FAILURE"})
    info = DeviceInfoCollector(runner).sample()
    assert info.uptime_seconds == pytest.approx(123456.78)
    assert info.boot_time is None


def test_boot_time_unreliable_when_clock_behind_uptime() -> None:
    runner = fx.DeviceRunner({**fx.scenario("normal"), "date +%s": "100\n"})
    info = DeviceInfoCollector(runner).sample()
    assert info.boot_time is None


def test_uptime_malformed_does_not_abort_snapshot() -> None:
    runner = fx.DeviceRunner({**fx.scenario("normal"), "cat /proc/uptime": "garbage\n"})
    info = DeviceInfoCollector(runner).sample()
    assert info.uptime_seconds is None
    assert info.boot_time is None
    assert info.model == "V2026"


# ---------------------------------------------------------------------------
# Phase 2B: CPU & hardware intelligence
# ---------------------------------------------------------------------------


def test_total_cpu_source_failure_degrades_gracefully() -> None:
    runner = fx.DeviceRunner(
        fx.failing_commands(
            fx.scenario("normal"),
            [
                "cat /sys/devices/system/cpu/present",
                "cat /sys/devices/system/cpu/online",
                "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
                "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq",
                "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq",
                "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
            ],
        )
    )
    info = DeviceInfoCollector(runner).sample()
    assert isinstance(info, DeviceInformation)
    assert info.cpu_core_count == 8  # sysfs failed -> /proc/cpuinfo fallback
    assert info.cpu_online_cores is None
    assert info.cpu_offline_cores is None
    assert info.cpu_governor is None
    assert info.cpu_current_frequency_hz is None
    assert info.cpu_min_frequency_hz is None
    assert info.cpu_max_frequency_hz is None
    assert info.manufacturer == "vivo"  # identity survives
    assert info.model == "V2026"
    assert info.cpu_architecture == "aarch64"  # uname -a still read
    assert info.cpu_features is not None  # /proc/cpuinfo still read


def test_partial_cpu_data_degrades_field_by_field() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "garbage\n",
            "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor": "FAILURE",
            "cat /sys/devices/system/cpu/online": "FAILURE",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_current_frequency_hz is None  # malformed value
    assert info.cpu_governor is None  # failed command
    assert info.cpu_online_cores is None
    assert info.cpu_offline_cores is None  # derivation needs online
    assert info.cpu_min_frequency_hz == pytest.approx(300_000_000.0)
    assert info.cpu_max_frequency_hz == pytest.approx(2_841_600_000.0)
    assert info.cpu_core_count == 8
    assert info.model == "V2026"


def test_core_count_falls_back_to_cpuinfo() -> None:
    runner = fx.DeviceRunner(
        {**fx.scenario("normal"), "cat /sys/devices/system/cpu/present": "FAILURE"}
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_core_count == 8  # processor entries in /proc/cpuinfo


def test_online_exceeding_present_is_unreliable() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "cat /sys/devices/system/cpu/present": "0-3\n",
            "cat /sys/devices/system/cpu/online": "0-7\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_core_count == 4
    assert info.cpu_online_cores == 8
    assert info.cpu_offline_cores is None  # inconsistent, not derived


def test_32bit_device_machine_token() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "uname -a": "Linux localhost 4.9.190+ #1 SMP PREEMPT armv7l\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_architecture == "armv7l"
    assert info.cpu_64bit is False


def test_ambiguous_machine_token_is_none() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "uname -a": "Linux localhost 4.9.190+ #1 SMP PREEMPT armv8l\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_architecture == "armv8l"
    assert info.cpu_64bit is None  # never guessed


def test_architecture_unavailable_is_none() -> None:
    runner = fx.DeviceRunner({**fx.scenario("normal"), "uname -a": "FAILURE"})
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_architecture is None
    assert info.cpu_64bit is None
    assert info.kernel_version is None


def test_processor_falls_back_to_cpuinfo_model_name() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("missing_optional"),  # ro.soc.* stripped
            "cat /proc/cpuinfo": (
                "processor\t: 0\n"
                "model name\t: Qualcomm Technologies, Inc SM8250\n"
            ),
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.processor == "Qualcomm Technologies, Inc SM8250"


def test_cpu_abis_missing_is_none() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "getprop": fx.scenario("normal")["getprop"].replace(
                "[ro.product.cpu.abilist]: [arm64-v8a,armeabi-v7a,armeabi]\n", ""
            ),
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.cpu_abis is None
    assert info.architecture == "arm64-v8a"  # primary ABI still present


def test_missing_optional_properties_become_none() -> None:
    info = collect("missing_optional")
    assert info.soc == "kona"  # falls back to ro.board.platform
    assert info.baseband is None
    assert info.bootloader is None
    assert info.build_fingerprint is None
    # Required-ish fields still present.
    assert info.model == "V2026"
    assert info.android_version == "11"


def test_partial_output_tolerated() -> None:
    info = collect("partial")
    assert info.manufacturer == "vivo"
    assert info.resolution is None
    assert info.storage is None
    assert info.density_dpi is None


def test_older_android_device() -> None:
    info = collect("older_android")
    assert info.android_version == "5.1.1"
    assert info.api_level == "22"
    assert info.soc is None
    assert info.processor == "Qualcomm Technologies, Inc SM8250"  # cpuinfo fallback
    assert info.density_dpi is None
    assert info.orientation == "Reverse landscape"
    assert info.max_frequency_khz == 1497600
    assert info.bootloader is None


def test_unknown_and_empty_properties_become_none() -> None:
    info = collect("unknown_empty")
    assert info.model is None
    assert info.device is None
    assert info.android_version is None
    assert info.build_id is None
    assert info.architecture is None
    assert info.soc is None
    assert info.manufacturer == "vivo"  # untouched key survives
    assert info.storage is None


def test_display_unavailable_degrades() -> None:
    info = collect("display_unavailable")
    assert info.resolution is None
    assert info.density_dpi is None
    assert info.refresh_rate_hz is None
    assert info.orientation is None
    assert info.display_width_px is None
    assert info.display_height_px is None
    assert info.display_override_resolution is None
    assert info.display_override_density is None
    assert info.display_orientation_degrees is None
    assert info.supported_refresh_rates_hz is None
    assert info.gpu_vendor == "Qualcomm"  # independent source survives
    assert info.gpu_model == "Adreno (TM) 610"
    assert info.model == "V2026"  # rest of the snapshot intact


def test_gpu_unavailable_degrades() -> None:
    info = collect("gpu_unavailable")
    assert info.gpu_vendor is None
    assert info.gpu_model is None
    assert info.resolution == "1080x2340"  # display intact
    assert info.model == "V2026"


def test_gpu_and_display_unavailable_degrades() -> None:
    runner = fx.DeviceRunner(
        fx.failing_commands(
            fx.scenario("normal"),
            [
                "wm size",
                "wm density",
                "dumpsys display",
                "dumpsys input",
                "dumpsys SurfaceFlinger",
            ],
        )
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.gpu_vendor is None
    assert info.gpu_model is None
    assert info.resolution is None
    assert info.density_dpi is None
    assert info.refresh_rate_hz is None
    assert info.orientation is None
    assert info.display_width_px is None
    assert info.display_height_px is None
    assert info.display_override_resolution is None
    assert info.display_override_density is None
    assert info.display_orientation_degrees is None
    assert info.supported_refresh_rates_hz is None
    assert info.manufacturer == "vivo"
    assert info.model == "V2026"


def test_display_overrides_parsed_when_set() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "wm size": "Override size: 720x1440\nPhysical size: 1080x2340\n",
            "wm density": "Physical density: 440\nOverride density: 420\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.resolution == "1080x2340"  # physical still wins
    assert info.display_width_px == 1080
    assert info.display_height_px == 2340
    assert info.display_override_resolution == "720x1440"
    assert info.density_dpi == 440
    assert info.display_override_density == 420


def test_override_null_is_treated_as_absent() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "wm size": "Override size: null\nPhysical size: 1080x2340\n",
            "wm density": "Physical density: 440\nOverride density: null\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.display_override_resolution is None
    assert info.display_override_density is None
    assert info.display_width_px == 1080
    assert info.density_dpi == 440


def test_landscape_orientation_reported_numerically() -> None:
    runner = fx.DeviceRunner(
        {**fx.scenario("normal"), "dumpsys input": "SurfaceOrientation: 1\n"}
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.orientation == "Landscape"
    assert info.display_orientation_degrees == 90


def test_refresh_modes_absent_leave_supported_rates_none() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "dumpsys display": "mDisplayInfo=DisplayInfo{...}\n  mCurrentOrientation=0\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.refresh_rate_hz is None
    assert info.supported_refresh_rates_hz is None


def test_current_rate_token_alone_leaves_supported_rates_none() -> None:
    runner = fx.DeviceRunner(
        {**fx.scenario("normal"), "dumpsys display": "  mRefreshRate=60.000004\n"}
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.refresh_rate_hz == pytest.approx(60.0)  # current rate intact
    assert info.supported_refresh_rates_hz is None  # no advertised modes


def test_identifiers_unavailable_degrades() -> None:
    info = collect("identifiers_unavailable")
    assert info.android_id is None
    assert info.wifi_mac is None
    assert info.bluetooth_mac is None
    assert info.manufacturer == "vivo"


def test_storage_unavailable_degrades() -> None:
    info = collect("storage_unavailable")
    assert info.storage is None
    assert info.model == "V2026"


def test_optional_command_failure_does_not_abort() -> None:
    runner = fx.DeviceRunner(
        fx.failing_commands(fx.scenario("normal"), ["df -k /data", "wm density"])
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.storage is None
    assert info.density_dpi is None
    assert info.resolution == "1080x2340"
    assert info.manufacturer == "vivo"


def test_first_command_failure_propagates() -> None:
    runner = fx.DeviceRunner(fx.failing_commands(fx.scenario("normal"), ["getprop"]))
    with pytest.raises(ADBCommandError):
        DeviceInfoCollector(runner).sample()


def test_whitespace_only_values_normalized() -> None:
    runner = fx.DeviceRunner(
        {
            **fx.scenario("normal"),
            "getprop": "[ro.product.model]: [   ]\n[ro.product.manufacturer]: [ vivo ]\n",
        }
    )
    info = DeviceInfoCollector(runner).sample()
    assert info.model is None
    assert info.manufacturer == "vivo"


# ---------------------------------------------------------------------------
# Monitor integration: one structured snapshot per connection
# ---------------------------------------------------------------------------


def test_monitor_emits_device_information_on_connect(qtapp) -> None:
    worker = MonitorWorker(connection=fx.DeviceRunner(fx.scenario("normal")))
    received: list = []
    worker.device_information.connect(lambda info: received.append(info))
    worker._connect()
    assert len(received) == 1
    info = received[0]
    assert isinstance(info, DeviceInformation)
    assert info.model == "V2026"
    assert info.manufacturer == "vivo"
    assert info.storage is not None


def test_monitor_emits_sparse_information_when_properties_absent(qtapp) -> None:
    worker = MonitorWorker(connection=fx.DeviceRunner(fx.scenario("unknown_empty")))
    received: list = []
    worker.device_information.connect(lambda info: received.append(info))
    worker._connect()
    assert len(received) == 1
    assert received[0].model is None
    assert received[0].manufacturer == "vivo"
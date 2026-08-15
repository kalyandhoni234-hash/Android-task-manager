"""Collector tests: structured device-information reads through a fake runner.

No real device: ``DeviceRunner`` serves canned raw ADB output per scenario.
Verifies that the collector normalizes every field, tolerates missing and
malformed values, never aborts on a single failed read, and only propagates
a total failure (the first bulk getprop read) to the connection layer.
"""

from __future__ import annotations

import pytest

from android_task_manager.adb.exceptions import ADBCommandError
from android_task_manager.device import DeviceInfoCollector
from android_task_manager.device.models import DeviceInformation, StorageInfo
from android_task_manager.gui.monitor import MonitorWorker
from PySide6.QtWidgets import QApplication

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
    assert info.bootloader == "UFS"
    assert info.baseband == "MPSS.JO.4.7.c2-00125-8937_GEN_PACK-1.10"
    assert info.kernel is None  # uname -r is not part of the property dump
    assert info.processor == "SM8250"  # ro.soc.model
    assert info.architecture == "arm64-v8a"
    assert info.max_frequency_khz == 2841600
    assert info.resolution == "1080x2340"
    assert info.density_dpi == 440
    assert info.refresh_rate_hz == pytest.approx(60.0)
    assert info.orientation == "Portrait"
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
    assert info.model == "V2026"  # rest of the snapshot intact


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
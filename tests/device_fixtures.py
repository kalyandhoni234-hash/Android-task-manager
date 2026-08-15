"""Shared fixture factories for the device-information tests.

Provides representative raw ADB outputs (bulk ``getprop``, ``wm``, ``df``,
``dumpsys``, sysfs reads) for the scenarios the spec requires — a normal
modern device, missing/partial/empty properties, an older Android device,
and unavailable display/identifier data — plus a CommandRunner fake that
serves them without any device.
"""

from __future__ import annotations

from android_task_manager.adb.exceptions import ADBCommandError


def scenario(name: str) -> dict[str, str]:
    """Raw device output per collector command for a named scenario.

    Keys are the exact ``" ".join(args)`` command strings the collector
    sends; the value is the device's stdout. Scenarios are constructed by
    layering over the full ``normal`` device.
    """
    base = _normal()
    if name == "normal":
        return base
    if name == "missing_optional":
        props = _strip_properties(
            base["getprop"],
            "ro.soc.manufacturer",
            "ro.soc.model",
            "gsm.version.baseband",
            "ro.boot.bootloader",
            "ro.build.fingerprint",
        )
        return {**base, "getprop": props}
    if name == "partial":
        # Truncated / mixed-content output: the parser must keep the rows
        # it can read and ignore the rest.
        lines = base["getprop"].splitlines()[:5]
        lines.append("garbage that is not a property line")
        return {
            **base,
            "getprop": "\n".join(lines) + "\n",
            "df -k /data": "Filesystem      1K-blocks     Used Available Use% Mounted on\n",
            "wm size": "Status bar height: 66\n",
            "wm density": "",
        }
    if name == "older_android":
        props = _strip_properties(
            base["getprop"],
            "ro.soc.manufacturer",
            "ro.soc.model",
            "ro.board.platform",
            "ro.build.fingerprint",
            "ro.boot.bootloader",
        )
        props = props.replace("[11]", "[5.1.1]").replace("[30]", "[22]")
        return {
            **base,
            "getprop": props,
            "wm density": "",
            "dumpsys input": "SurfaceOrientation: 3\n",
            "cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq": "1497600",
        }
    if name == "unknown_empty":
        # Properties explicitly set to empty values; also some bogus keys.
        props = _strip_properties(base["getprop"], *(
            "ro.product.model",
            "ro.product.device",
            "ro.build.version.release",
            "ro.build.id",
            "ro.product.cpu.abi",
            "ro.soc.manufacturer",
            "ro.soc.model",
            "ro.board.platform",
        ))
        props = props.replace(
            "[ro.product.brand]: [vivo]",
            "[ro.product.model]: []\n[ro.product.device]: []\n[ro.build.version.release]: []",
        )
        return {
            **base,
            "getprop": props + "[totally.unknown.key]: [some-value]\n",
            "df -k /data": "df: /data: No such file or directory\n",
        }
    if name == "display_unavailable":
        return {
            **base,
            "wm size": "FAILURE",
            "wm density": "FAILURE",
            "dumpsys display": "FAILURE",
            "dumpsys input": "FAILURE",
        }
    if name == "identifiers_unavailable":
        return {
            **base,
            "settings get secure android_id": "null\n",
            "cat /sys/class/net/wlan0/address": "02:00:00:00:00:00\n",
            "settings get secure bluetooth_address": "null\n",
        }
    if name == "storage_unavailable":
        return {**base, "df -k /data": "df: /data: Permission denied\n"}
    raise KeyError(f"unknown scenario: {name}")


def failing_commands(scenario_responses: dict[str, str], commands: list[str]) -> dict[str, str]:
    """Mark whole commands as failing (sentinel) for the fake runner."""
    marked = dict(scenario_responses)
    for command in commands:
        marked[command] = "FAILURE"
    return marked


class DeviceRunner:
    """CommandRunner stand-in: canned responses, per-command failures."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        return "FAKE123"

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        command = " ".join(args)
        if self.responses.get(command) == "FAILURE":
            raise ADBCommandError(command, 1, stdout="", stderr="permission denied")
        return self.responses.get(command, "")


# ---------------------------------------------------------------------------
# Raw output builders
# ---------------------------------------------------------------------------


def _normal() -> dict[str, str]:
    return {
        "getprop": (
            "[ro.product.manufacturer]: [vivo]\n"
            "[ro.product.brand]: [vivo]\n"
            "[ro.product.model]: [V2026]\n"
            "[ro.product.device]: [PD2026F]\n"
            "[ro.product.name]: [PD2026F_EX_A]\n"
            "[ro.product.board]: [kona]\n"
            "[ro.hardware]: [qcom]\n"
            "[ro.soc.manufacturer]: [Qualcomm]\n"
            "[ro.soc.model]: [SM8250]\n"
            "[ro.board.platform]: [kona]\n"
            "[ro.build.version.release]: [11]\n"
            "[ro.build.version.sdk]: [30]\n"
            "[ro.build.version.security_patch]: [2021-06-01]\n"
            "[ro.build.id]: [RP1A.200720.012]\n"
            "[ro.build.display.id]: [PD2026F_EX_A_11_W_2021.06.01_15:40:47]\n"
            "[ro.build.fingerprint]: [vivo/PD2026F_EX_A/PD2026F:11/RP1A.200720.012/15.40.47:user/release-keys]\n"
            "[ro.boot.bootloader]: [UFS]\n"
            "[gsm.version.baseband]: [MPSS.JO.4.7.c2-00125-8937_GEN_PACK-1.10]\n"
            "[ro.product.cpu.abi]: [arm64-v8a]\n"
            "[ro.product.cpu.abilist]: [arm64-v8a,armeabi-v7a,armeabi]\n"
            "[dalvik.vm.heapsize]: [256m]\n"
            "Usage: getprop [options]\n"
        ),
        "cat /proc/cpuinfo": (
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "Hardware\t: Qualcomm Technologies, Inc SM8250\n"
        ),
        "cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq": "2841600\n",
        "wm size": "Physical size: 1080x2340\n",
        "wm density": "Physical density: 440\n",
        "dumpsys display": (
            "mDisplayInfo=DisplayInfo{...}\n"
            "  mRefreshRate=60.000004\n"
            "  mDefaultRefreshRate=60.000004\n"
            "  mCurrentOrientation=0\n"
        ),
        "dumpsys input": "SurfaceOrientation: 0\n",
        "df -k /data": (
            "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
            "/dev/block/sda11 121934848 69120000 52814848 57% /data\n"
        ),
        "settings get secure android_id": "a1b2c3d4e5f60718\n",
        "cat /sys/class/net/wlan0/address": "3c:28:6d:ab:cd:ef\n",
        "settings get secure bluetooth_address": "aa:bb:cc:dd:ee:ff\n",
    }


def _strip_properties(getprop_text: str, *keys: str) -> str:
    """Remove whole ``[key]: [value]`` lines from a bulk getprop dump."""
    kept = []
    for line in getprop_text.splitlines():
        for key in keys:
            if line.startswith(f"[{key}]:"):
                break
        else:
            kept.append(line)
    return "\n".join(kept) + "\n"
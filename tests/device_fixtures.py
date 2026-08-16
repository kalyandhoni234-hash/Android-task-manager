"""Shared fixture factories for the device-information tests.

Provides representative raw ADB outputs (bulk ``getprop``, ``wm``, ``df``,
``dumpsys``, ``ip``, sysfs reads) for the scenarios the spec requires — a
normal modern device, missing/partial/empty properties, an older Android
device, and unavailable display/identifier/network data — plus a
CommandRunner fake that serves them without any device.

All network identifiers are sanitized fiction: no real SSID, BSSID, MAC or
personally-identifiable address appears in any fixture.
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
    if name == "gpu_unavailable":
        return {**base, "dumpsys SurfaceFlinger": "FAILURE"}
    if name == "identifiers_unavailable":
        return {
            **base,
            "settings get secure android_id": "null\n",
            "cat /sys/class/net/wlan0/address": "02:00:00:00:00:00\n",
            "settings get secure bluetooth_address": "null\n",
        }
    if name == "storage_unavailable":
        return {**base, "df -k /data": "df: /data: Permission denied\n"}
    if name == "network_partial":
        # Wi-Fi dump unavailable; interface, route, connectivity and VPN
        # sources still deliver their share of the snapshot.
        return {**base, "dumpsys wifi": "FAILURE"}
    if name == "network_unavailable":
        # Every Phase 2E source is gone; the rest of the snapshot survives.
        return failing_commands(
            base,
            [
                "ip addr",
                "ip route",
                "dumpsys wifi",
                "dumpsys connectivity",
                "dumpsys vpn",
            ],
        )
    if name == "network_redacted":
        # Android 8+ redacts the connected SSID (prints "<ssid>") and the
        # device hides the BSSID; enabled/connected state still reports.
        return {
            **base,
            "dumpsys wifi": (
                "Wi-Fi is enabled\n"
                "mWifiInfo SSID: <ssid>, BSSID: 02:00:00:00:00:00, "
                "MAC: 02:00:00:00:00:00, IP: 192.168.50.10/24, "
                "Supplicant state: COMPLETED, Link speed: 866Mbps, "
                "Frequency: 5180MHz\n"
                "mNetworkInfo=NetworkInfo: type: WIFI[], state: CONNECTED/CONNECTED, "
                "reason: (unspecified)\n"
            ),
        }
    if name == "security_permissive":
        # SELinux running, but permissive: the mode fact changes, the rest
        # of the snapshot is untouched.
        return {**base, "getenforce": "Permissive\n"}
    if name == "security_unlocked":
        # Unlocked bootloader on a (still enforcing) userdebug-style build:
        # verified-boot state degrades to orange, both lock sources agree.
        props = _strip_properties(base["getprop"], "ro.boot.verifiedbootstate")
        props = props.replace(
            "[ro.boot.flash.locked]: [1]",
            "[ro.boot.flash.locked]: [0]",
        ).replace(
            "[ro.boot.vbmeta.device_state]: [locked]",
            "[ro.boot.vbmeta.device_state]: [unlocked]",
        ).replace(
            "[ro.debuggable]: [0]",
            "[ro.debuggable]: [1]",
        ).replace(
            "[ro.secure]: [1]",
            "[ro.secure]: [0]",
        )
        return {
            **base,
            "getprop": props + "[ro.boot.verifiedbootstate]: [orange]\n",
            "id": (
                "uid=2000(shell) gid=2000(shell) groups=2000(shell),1004(input),"
                "1007(log),1011(adb),1015(sdcard_rw)\n"
            ),
        }
    if name == "security_root_evidence":
        # Simulated rooted device: a su binary answers on PATH. This is
        # sanitized fixture evidence, not a real device or a real su run.
        return {
            **base,
            "command -v su || echo __SU_NOT_FOUND__": "/system/xbin/su\n",
        }
    if name == "security_unknown":
        # Every security source unavailable or property absent: each fact
        # must be UNKNOWN (None) while the rest of the snapshot survives.
        props = _strip_properties(
            base["getprop"],
            "ro.boot.verifiedbootstate",
            "ro.boot.flash.locked",
            "ro.boot.vbmeta.device_state",
            "ro.boot.veritymode",
            "ro.debuggable",
            "ro.secure",
            "ro.crypto.state",
            "ro.crypto.type",
        )
        return failing_commands(
            {**base, "getprop": props},
            ["getenforce", "id", "command -v su || echo __SU_NOT_FOUND__"],
        )
    if name == "security_malformed":
        # Garbage from every security source: parsers must return None
        # (UNKNOWN) and never crash the snapshot.
        props = _strip_properties(
            base["getprop"],
            "ro.boot.verifiedbootstate",
            "ro.boot.flash.locked",
            "ro.boot.vbmeta.device_state",
            "ro.boot.veritymode",
            "ro.debuggable",
            "ro.secure",
            "ro.crypto.state",
            "ro.crypto.type",
            "ro.build.version.security_patch",
        )
        props = props + (
            "[ro.boot.verifiedbootstate]: [blue]\n"
            "[ro.boot.flash.locked]: [2]\n"
            "[ro.boot.vbmeta.device_state]: [floating]\n"
            "[ro.boot.veritymode]: [off]\n"
            "[ro.debuggable]: [maybe]\n"
            "[ro.secure]: []\n"
            "[ro.crypto.state]: [encryptedish]\n"
            "[ro.crypto.type]: [inline]\n"
            "[ro.build.version.security_patch]: [2026-99-99]\n"
        )
        return {
            **base,
            "getprop": props,
            "getenforce": "permissive-ish\n",
            "id": "not an id at all\n",
            "command -v su || echo __SU_NOT_FOUND__": "command -v: su: not found\n",
        }
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
            "[ro.build.tags]: [release-keys]\n"
            "[ro.build.type]: [user]\n"
            "[ro.boot.bootloader]: [UFS]\n"
            "[gsm.version.baseband]: [MPSS.JO.4.7.c2-00125-8937_GEN_PACK-1.10]\n"
            "[ro.product.cpu.abi]: [arm64-v8a]\n"
            "[ro.product.cpu.abilist]: [arm64-v8a,armeabi-v7a,armeabi]\n"
            "[dalvik.vm.heapsize]: [256m]\n"
            # -- Phase 2F: security posture properties (sanitized) ----------
            "[ro.boot.verifiedbootstate]: [green]\n"
            "[ro.boot.flash.locked]: [1]\n"
            "[ro.boot.vbmeta.device_state]: [locked]\n"
            "[ro.boot.veritymode]: [enforcing]\n"
            "[ro.debuggable]: [0]\n"
            "[ro.secure]: [1]\n"
            "[ro.crypto.state]: [encrypted]\n"
            "[ro.crypto.type]: [file]\n"
            "Usage: getprop [options]\n"
        ),
        "cat /proc/cpuinfo": (
            "processor\t: 0\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "Hardware\t: Qualcomm Technologies, Inc SM8250\n"
            "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp\n"
            "processor\t: 1\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "processor\t: 2\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "processor\t: 3\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "processor\t: 4\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "processor\t: 5\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "processor\t: 6\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
            "processor\t: 7\n"
            "Processor\t: AArch64 Processor rev 2 (aarch64)\n"
        ),
        "cat /sys/devices/system/cpu/present": "0-7\n",
        "cat /sys/devices/system/cpu/online": "0-7\n",
        "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "576000\n",
        "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq": "300000\n",
        "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq": "2841600\n",
        "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor": "schedutil\n",
        "cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq": "2841600\n",
        "uname -r": "4.14.186+\n",
        "uname -a": (
            "Linux localhost 4.14.186+ #1 SMP PREEMPT Wed Jun 2 12:00:00 2021 aarch64\n"
        ),
                "cat /proc/uptime": "123456.78 987654.32\n",
        "date +%s": "1622773057\n",
        "cat /sys/class/power_supply/battery/charge_full_design": "4880000\n",
        "cat /sys/class/power_supply/battery/cycle_count": "412\n",
        "cat /proc/mounts": (
            "rootfs / rootfs rw 0 0\n"
            "tmpfs /dev tmpfs rw,seclabel,nosuid,relatime,mode=755 0 0\n"
            "/dev/block/dm-0 /system ext4 ro,seclabel,relatime 0 0\n"
            "/dev/block/dm-5 /data ext4 rw,seclabel,nosuid,nodev,noatime,inlinecrypt 0 0\n"
            "/dev/block/sda1 /storage/emulated fuse rw,nosuid,nodev,noexec,noatime 0 0\n"
        ),
        "wm size": "Physical size: 1080x2340\n",
        "wm density": "Physical density: 440\n",
        "dumpsys display": (
            "mDisplayInfo=DisplayInfo{...}\n"
            "  mRefreshRate=60.000004\n"
            "  mDefaultRefreshRate=60.000004\n"
            "  mCurrentOrientation=0\n"
            "  DisplayModeInfo{id=0, width=1080, height=2340, refreshRate=60.000004}\n"
            "  DisplayModeInfo{id=1, width=1080, height=2340, refreshRate=90.000000}\n"
        ),
        "dumpsys input": "SurfaceOrientation: 0\n",
        "dumpsys SurfaceFlinger": (
            "Display 0 HWC layers: 2\n"
            "GLES: Qualcomm, Adreno (TM) 610\n"
        ),
        "df -k /data": (
            "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
            "/dev/block/sda11 121934848 69120000 52814848 57% /data\n"
        ),
        "settings get secure android_id": "a1b2c3d4e5f60718\n",
        "cat /sys/class/net/wlan0/address": "3c:28:6d:ab:cd:ef\n",
        "settings get secure bluetooth_address": "aa:bb:cc:dd:ee:ff\n",
        # -- Phase 2E: network configuration / connectivity (sanitized) ------
        "ip addr": (
            "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN "
            "group default qlen 1000\n"
            "    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00\n"
            "    inet 127.0.0.1/8 scope host lo\n"
            "    valid_lft forever preferred_lft forever\n"
            "    inet6 ::1/128 scope host\n"
            "    valid_lft forever preferred_lft forever\n"
            "2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state "
            "UP group default qlen 1000\n"
            "    link/ether 3c:28:6d:ab:cd:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 192.168.50.10/24 brd 192.168.50.255 scope global wlan0\n"
            "    valid_lft forever preferred_lft forever\n"
            "    inet6 fe80::3c28:6dff:feab:cdef/64 scope link\n"
            "    valid_lft forever preferred_lft forever\n"
            "3: rmnet0: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN "
            "group default qlen 1000\n"
            "    link/ether 92:e2:ba:10:81:77 brd ff:ff:ff:ff:ff:ff\n"
        ),
        "ip route": (
            "default via 192.168.50.1 dev wlan0 proto static metric 10\n"
            "192.168.50.0/24 dev wlan0 proto static scope link metric 10\n"
        ),
        "dumpsys wifi": (
            "Wi-Fi is enabled\n"
            "mWifiInfo SSID: \"HomeWiFi\", BSSID: aa:bb:cc:dd:ee:ff, "
            "MAC: 02:00:00:00:00:00, IP: 192.168.50.10/24, "
            "Supplicant state: COMPLETED, Link speed: 866Mbps, "
            "Frequency: 5180MHz, RSSI: -45\n"
            "mNetworkInfo=NetworkInfo: type: WIFI[], state: CONNECTED/CONNECTED, "
            "reason: (unspecified)\n"
        ),
        "dumpsys connectivity": (
            "ConnectivityService state:\n"
            "  NetworkAgentInfos:\n"
            "    100 NetworkAgentInfo{ [WIFI () - 100]  id=100, "
            "uptimeMs=86400000, networkMonitor=NetworkMonitorAgentInfo{} }\n"
            "      requested by: [android, com.android.settings]\n"
            "      LinkProperties: {InterfaceName: wlan0 "
            "LinkAddresses: [ 192.168.50.10/24 ] "
            "DnsAddresses: [ 192.168.50.1, 9.9.9.9 ] Domains: null "
            "MTU: 1500 Routes: [ 192.168.50.0/24 -> 0.0.0.0 wlan0, "
            "0.0.0.0/0 -> 192.168.50.1 wlan0 ]}\n"
            "  Active default network: 100\n"
        ),
        "dumpsys vpn": "VPN state: disconnected\n",
        # -- Phase 2F: security posture command reads (read-only) -----------
        "getenforce": "Enforcing\n",
        "id": (
            "uid=2000(shell) gid=2000(shell) groups=2000(shell),1004(input),"
            "1007(log),1011(adb),1015(sdcard_rw),1028(sdcard_r),3001(net_bt_admin),"
            "3002(net_bt),3003(inet),3006(net_bw_stats),3009(uhid),3011(readproc)\n"
        ),
        "command -v su || echo __SU_NOT_FOUND__": "__SU_NOT_FOUND__\n",
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
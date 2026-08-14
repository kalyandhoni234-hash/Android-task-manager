"""First-run / connection-setup panel shown until a device is connected.

Pure presentation: it renders monitor states and forwards user actions as
signals. It never talks to adb itself — that stays in ``MonitorWorker``.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .monitor import ConnectionState

#: Instructions shown by the "How to enable USB debugging" help dialog.
USB_DEBUGGING_STEPS = (
    "1. On your phone: Settings -> About phone.\n"
    "2. Tap \u201cBuild number\u201d 7 times until Developer options are enabled.\n"
    "3. Open Settings -> System -> Developer options.\n"
    "4. Turn on \u201cUSB debugging\u201d.\n"
    "5. Connect the phone via USB and pick \u201cFile Transfer\u201d (MTP) when asked.\n"
    "6. When the phone asks \u201cAllow USB debugging?\u201d, tap \u201cAllow\u201d."
)

#: Instructions shown by the "How to install ADB" help dialog.
INSTALL_ADB_STEPS = (
    "Android Task Manager uses the Android Debug Bridge (ADB), which is not\n"
    "bundled with the app.\n\n"
    "Install it by downloading Android SDK Platform-Tools from Google:\n"
    "  https://developer.android.com/tools/releases/platform-tools\n\n"
    "Extract the ZIP and either:\n"
    "  - place adb.exe next to AndroidTaskManager.exe, or\n"
    "  - use the \u201cLocate ADB\u201d button to point at the extracted adb.exe."
)


class SetupPanel(QWidget):
    """Stateful setup screen: explains what is wrong and how to fix it.

    Signals
    -------
    retry_requested : re-run the connection attempt.
    locate_requested : the user wants to pick an adb executable via a file dialog.
    usb_help_requested : show the USB debugging instructions.
    install_help_requested : show the ADB installation instructions.
    refresh_requested : re-enumerate devices in the multi-device view.
    device_selected : (serial) the user chose a device from the list.
    """

    retry_requested = Signal()
    locate_requested = Signal()
    usb_help_requested = Signal()
    install_help_requested = Signal()
    refresh_requested = Signal()
    device_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("setupPanel")

        self._title = QLabel()
        self._title.setObjectName("setupTitle")
        self._title.setAlignment(self._title.alignment().AlignHCenter)

        self._message = QLabel()
        self._message.setObjectName("muted")
        self._message.setWordWrap(True)
        self._message.setAlignment(self._message.alignment().AlignHCenter)

        self._devices = QListWidget()
        self._devices.setObjectName("deviceList")
        self._devices.setMinimumHeight(140)
        self._devices.currentRowChanged.connect(self._on_row_changed)
        self._devices.itemDoubleClicked.connect(lambda _item: self._connect_selected())

        self._locate = QPushButton("Locate ADB\u2026")
        self._locate.setObjectName("primary")
        self._locate.clicked.connect(self.locate_requested.emit)

        self._retry = QPushButton("Retry")
        self._retry.setObjectName("primary")
        self._retry.clicked.connect(self.retry_requested.emit)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("primary")
        self._connect_btn.clicked.connect(self._connect_selected)

        self._refresh = QPushButton("Refresh")
        self._refresh.setObjectName("secondary")
        self._refresh.clicked.connect(self.refresh_requested.emit)

        self._usb_help = QPushButton("How to enable USB debugging")
        self._usb_help.setObjectName("link")
        self._usb_help.clicked.connect(self.usb_help_requested.emit)

        self._install_help = QPushButton("How to install ADB")
        self._install_help.setObjectName("link")
        self._install_help.clicked.connect(self.install_help_requested.emit)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        actions.addWidget(self._connect_btn)
        actions.addWidget(self._refresh)
        actions.addWidget(self._locate)
        actions.addWidget(self._retry)
        actions.addStretch(1)

        links = QHBoxLayout()
        links.setSpacing(18)
        links.addStretch(1)
        links.addWidget(self._install_help)
        links.addWidget(self._usb_help)
        links.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(18)
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addWidget(self._message)
        layout.addWidget(self._devices)
        layout.addLayout(actions)
        layout.addLayout(links)
        layout.addStretch(1)

        self._devices_by_row: list[dict[str, str]] = []
        self.show_scanning()

    # ------------------------------------------------------------------
    # Presentation API
    # ------------------------------------------------------------------

    def show_scanning(self) -> None:
        self._title.setText("Connecting\u2026")
        self._message.setText("Looking for your Android device\u2026")
        self._devices.hide()
        self._connect_btn.hide()
        self._refresh.hide()
        self._locate.hide()
        self._retry.hide()
        self._install_help.show()
        self._usb_help.show()

    def show_state(self, state: ConnectionState, detail: str) -> None:
        """Render the setup screen for a non-connected monitor state."""
        self._devices.hide()
        self._connect_btn.hide()
        self._refresh.hide()
        self._locate.hide()
        self._retry.hide()
        self._install_help.hide()
        self._usb_help.hide()

        if state is ConnectionState.ADB_MISSING:
            self._title.setText("ADB not found")
            self._message.setText(
                "Android Task Manager needs the Android Debug Bridge (ADB) to talk to "
                "your phone. Install it, or point the app at an adb you already have."
            )
            self._locate.show()
            self._retry.show()
            self._install_help.show()
        elif state is ConnectionState.DISCONNECTED:
            self._title.setText("No Android device detected")
            self._message.setText(
                "Connect your Android phone with a USB cable and make sure USB "
                "debugging is enabled."
            )
            self._retry.show()
            self._usb_help.show()
        elif state is ConnectionState.UNAUTHORIZED:
            self._title.setText("Authorization required")
            self._message.setText(
                "Your phone is connected but has not authorized this computer. "
                "Unlock the phone and tap \u201cAllow\u201d on the USB debugging prompt."
            )
            self._retry.show()
            self._usb_help.show()
        elif state is ConnectionState.OFFLINE:
            self._title.setText("Device is offline")
            self._message.setText(
                "The device stopped responding to ADB. Reconnect the USB cable, "
                "or run \u201cadb kill-server\u201d and try again."
            )
            self._retry.show()
        elif state is ConnectionState.MULTIPLE_DEVICES:
            self._title.setText("Multiple devices found")
            self._message.setText("Choose which device to monitor:")
            self._devices.show()
            self._connect_btn.show()
            self._refresh.show()
        elif state is ConnectionState.TIMEOUT:
            self._title.setText("Connection timed out")
            self._message.setText(
                "The device did not answer in time. Check the cable and try again."
            )
            self._retry.show()
        else:  # ADB_ERROR and anything unexpected
            self._title.setText("Connection problem")
            self._message.setText(detail or "Something went wrong talking to the device.")
            self._locate.show()
            self._retry.show()

    def set_devices(self, devices: list[dict[str, str]]) -> None:
        """Populate the device picker (one entry per attached device)."""
        self._devices.clear()
        self._devices_by_row = devices
        for entry in devices:
            label = entry.get("label") or entry["serial"]
            version = entry.get("android_version") or ""
            state = entry.get("state", "")
            suffix = f" \u00b7 Android {version}" if version else ""
            text = label + suffix
            if state != "device":
                text += f" \u00b7 ({state})"
            self._devices.addItem(text)
        if devices:
            self._devices.setCurrentRow(0)
            self._connect_btn.setEnabled(devices[0]["state"] == "device")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _selected_serial(self) -> str | None:
        row = self._devices.currentRow()
        if row < 0 or row >= len(self._devices_by_row):
            return None
        return self._devices_by_row[row]["serial"]

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._devices_by_row):
            self._connect_btn.setEnabled(self._devices_by_row[row]["state"] == "device")

    def _connect_selected(self) -> None:
        serial = self._selected_serial()
        if serial:
            self.device_selected.emit(serial)
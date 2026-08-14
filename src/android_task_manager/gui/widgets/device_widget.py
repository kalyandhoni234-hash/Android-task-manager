"""Device identity + connection status header widget."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..monitor import ConnectionState
from . import panel_host


class DeviceWidget(QWidget):
    """Shows the device label, Android version and live connection state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "DEVICE")

        self._title = QLabel("No device selected")
        self._title.setObjectName("value")

        self._subtitle = QLabel()
        self._subtitle.setObjectName("muted")

        self._status = QLabel("Connecting\u2026")
        self._status.setObjectName("statusWarn")

        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(self._title)
        left.addWidget(self._subtitle)
        left.addStretch(1)

        right = QVBoxLayout()
        right.addStretch(1)
        right.addWidget(self._status)
        right.addStretch(1)

        combo = QHBoxLayout()
        combo.addLayout(left, 1)
        combo.addLayout(right)
        layout.addLayout(combo)

    def set_info(self, label: str, android_version: str) -> None:
        self._title.setText(label)
        self._subtitle.setText(f"Android {android_version}")

    def set_status(self, state: ConnectionState, detail: str) -> None:
        mapping = {
            ConnectionState.CONNECTED: ("\u25cf Connected", "statusConnected"),
            ConnectionState.DISCONNECTED: ("\u25cb No device", "statusError"),
            ConnectionState.ADB_MISSING: ("\u26a0 ADB not found", "statusError"),
            ConnectionState.OFFLINE: ("\u26a0 Device offline", "statusWarn"),
            ConnectionState.MULTIPLE_DEVICES: ("\u26a0 Multiple devices", "statusWarn"),
            ConnectionState.ADB_ERROR: ("\u26a0 adb error", "statusError"),
            ConnectionState.UNAUTHORIZED: ("\u26a0 Not authorized", "statusWarn"),
            ConnectionState.TIMEOUT: ("\u26a0 Timed out", "statusWarn"),
            ConnectionState.COLLECTOR_ERROR: ("\u26a0 Data error", "statusWarn"),
        }
        text, object_name = mapping[state]
        self._status.setText(text)
        self._status.setObjectName(object_name)
        self._status.setToolTip(detail or None)
        app = QApplication.instance()
        if app is not None:
            app.style().unpolish(self._status)
            app.style().polish(self._status)
"""Compact persistent device-state strip above the page content.

Reflects the same ConnectionManager state the DeviceWidget shows on the
Device page — a duplicate presentation of one source of truth, never a
second connection system. Hidden while no device is selected only when the
app is still on the setup screen; once the dashboard is reached the strip
always states the current connection state honestly.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .monitor import ConnectionState
from .styles import repolish

#: (status text, objectName) per state — the same vocabulary as DeviceWidget.
_STATUS = {
    ConnectionState.CONNECTED: ("\u25cf Connected", "statusConnected"),
    ConnectionState.DISCONNECTED: ("\u25cb No device connected", "statusError"),
    ConnectionState.ADB_MISSING: ("\u26a0 ADB not found", "statusError"),
    ConnectionState.OFFLINE: ("\u26a0 Device offline", "statusWarn"),
    ConnectionState.MULTIPLE_DEVICES: ("\u26a0 Multiple devices", "statusWarn"),
    ConnectionState.ADB_ERROR: ("\u26a0 adb error", "statusError"),
    ConnectionState.UNAUTHORIZED: ("\u26a0 Not authorized", "statusWarn"),
    ConnectionState.TIMEOUT: ("\u26a0 Timed out", "statusWarn"),
    ConnectionState.COLLECTOR_ERROR: ("\u26a0 Data error", "statusWarn"),
}

_DEFAULT = ("\u25cb No device connected", "statusError")


class ConnectionStrip(QWidget):
    """One quiet row: connection state · device label · Android version."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("connectionStrip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        self._status = QLabel(_DEFAULT[0])
        self._status.setObjectName(_DEFAULT[1])
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setAccessibleName("Device connection state")
        layout.addWidget(self._status)

        self._device = QLabel("")
        self._device.setObjectName("muted")
        self._device.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._device)

        layout.addStretch(1)

    def set_state(self, state: ConnectionState, detail: str) -> None:
        text, object_name = _STATUS.get(state, _DEFAULT)
        self._status.setText(text)
        self._status.setObjectName(object_name)
        repolish(self._status)
        self._status.setToolTip(detail or None)

    def set_device(self, label: str, android_version: str) -> None:
        if label:
            self._device.setText(f"{label} \u00b7 Android {android_version}")
        else:
            self._device.setText("")
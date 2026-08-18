"""Application detail panel: renders an AppDetails record and action controls.

This is a presentation view. It consumes an already-normalized
:class:`~android_task_manager.applications.models.AppDetails` record (or an
explicit "not installed / could not be read" state) and renders labels; it
never sends commands, never reads device output and never computes raw
state.

Device Actions live here: Open App / App Info / Force Stop / Enable or
Disable / Uninstall. Buttons are derived ONLY from the capability gate
(``action.capability.supported_actions``): system applications never see
destructive controls, and enable/disable appears only when the device
reported a concrete enabled state. Destructive requests (force stop,
disable, uninstall) are confirmed at the window layer before dispatch.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ...action import (
    APP_INFO,
    DISABLE,
    ENABLE,
    FORCE_STOP,
    LAUNCH,
    UNINSTALL,
    ActionResult,
    supported_actions,
)
from ...applications import AppCategory, AppDetails
from ...permissions import PackagePermissionAudit
from . import panel_host

_NA = "N/A"

#: Identity + installation + runtime fields, in visual order.
_IDENTITY_FIELDS = (
    ("Version", "version"),
    ("Version Code", "version_code"),
    ("UID", "uid"),
    ("Installer", "installer"),
)
_INSTALL_FIELDS = (
    ("APK Path", "apk_path"),
    ("Install Location", "install_location"),
)
_RUNTIME_FIELDS = (
    ("State", "state"),
    ("Launch Activity", "launchable"),
)

#: Caption when no details record is loaded yet.
_AWAITING = "Select an application to see its details."

#: Caption when the package could not be read (not installed / ADB error).
_NOT_READ = "Application details could not be read."

#: Caption shown while a detail read is in flight.
_LOADING = "Reading application details…"

#: Type badges shown next to the package title.
_TYPE_LABELS = {
    AppCategory.SYSTEM: "SYSTEM APP",
    AppCategory.USER: "USER APP",
    AppCategory.UNKNOWN: "APP CATEGORY UNKNOWN",
}

#: Human labels for the enabled state (the honest third value is "N/A").
_ENABLED_LABELS = {True: "Enabled", False: "Disabled"}

#: Caption explaining why destructive controls are absent.
_SYSTEM_APP_NOTE = (
    "System apps: launch, app info and force stop only. "
    "Uninstall and disable are not offered for system applications."
)


class AppDetailsWidget(QWidget):
    """Detail view shown when an application row is selected."""

    #: (action, package) the user clicked an action button.
    action_requested = Signal(str, str)

    #: (package) the user asked to audit the selected app's permissions.
    permission_audit_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "APPLICATION DETAILS")

        self._title = QLabel("")
        self._title.setObjectName("value")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("muted")
        layout.addWidget(self._subtitle)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self._rows: dict[str, QLabel] = {}
        row_index = 0
        for caption, key in _IDENTITY_FIELDS + _INSTALL_FIELDS + _RUNTIME_FIELDS:
            label = QLabel(caption)
            label.setObjectName("caption")
            value = QLabel(_NA)
            value.setObjectName("muted")
            value.setProperty("mono", True)
            value.setWordWrap(True)
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value, row_index, 1)
            self._rows[key] = value
            row_index += 1
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self._type_badge = QLabel("")
        self._type_badge.setObjectName("caption")
        layout.addWidget(self._type_badge)

        self._components = QLabel("")
        self._components.setObjectName("muted")
        self._components.setWordWrap(True)
        self._components.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._components)

        # ------------------------------------------------------------------
        # Permissions (on-demand audit through the shared permission worker)
        # ------------------------------------------------------------------
        perms_row = QHBoxLayout()
        perms_row.setSpacing(8)
        self._audit_btn = QPushButton("Audit Permissions")
        self._audit_btn.setObjectName("secondary")
        self._audit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._audit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._audit_btn.setEnabled(False)
        self._audit_btn.clicked.connect(self._on_audit_clicked)
        perms_row.addWidget(self._audit_btn)
        self._perm_status = QLabel("")
        self._perm_status.setObjectName("muted")
        self._perm_status.setWordWrap(True)
        perms_row.addWidget(self._perm_status, 1)
        layout.addLayout(perms_row)

        # ------------------------------------------------------------------
        # Device Actions row (capability-gated)
        # ------------------------------------------------------------------
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._actions_caption = QLabel("Actions")
        self._actions_caption.setObjectName("caption")
        action_row.addWidget(self._actions_caption)
        self._open_btn = self._make_button("Open App")
        self._info_btn = self._make_button("App Info")
        self._stop_btn = self._make_button("Force Stop", primary=False)
        self._toggle_btn = self._make_button("Disable", primary=False)
        self._uninstall_btn = self._make_button("Uninstall", primary=False)
        self._open_btn.clicked.connect(lambda: self._on_action_clicked(LAUNCH))
        self._info_btn.clicked.connect(lambda: self._on_action_clicked(APP_INFO))
        self._stop_btn.clicked.connect(lambda: self._on_action_clicked(FORCE_STOP))
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)
        self._uninstall_btn.clicked.connect(lambda: self._on_action_clicked(UNINSTALL))
        for button in (
            self._open_btn,
            self._info_btn,
            self._stop_btn,
            self._toggle_btn,
            self._uninstall_btn,
        ):
            action_row.addWidget(button)
        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        action_row.addWidget(self._status, 1)
        layout.addLayout(action_row)

        self._package: str | None = None
        self._details: AppDetails | None = None
        self._busy = False
        self._permission_busy = False

        self.hide()

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------

    def _make_button(self, text: str, primary: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primary" if primary else "secondary")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setEnabled(False)
        return button

    def _reset(self) -> None:
        """Clear every field and release every lock (fresh selection)."""
        for value in self._rows.values():
            value.setText(_NA)
        self._type_badge.setText("")
        self._components.setText("")
        self._status.setText("")
        self._status.setObjectName("muted")
        self._perm_status.setText("")
        self._perm_status.setObjectName("muted")
        self._package = None
        self._details = None
        self._busy = False
        self._permission_busy = False
        self._set_buttons(())
        self._audit_btn.setEnabled(False)

    def show_loading(self, package: str) -> None:
        """Show the loading state for a package whose details are in flight."""
        self._reset()
        self._title.setText(package)
        self._subtitle.setText(_LOADING)
        self._package = package
        self.show()

    def set_details(self, details: AppDetails) -> None:
        """Populate the panel with a normalized detail record and show it.

        Selection state is reset FIRST: the previous package's buttons and
        result status must never leak into the new selection. Buttons are
        then recomputed from the capability gate.
        """
        self._reset()
        self._package = details.package_name
        self._details = details
        self._title.setText(details.package_name)
        self._subtitle.setText("")
        self._type_badge.setText(
            f"TYPE: {_TYPE_LABELS.get(details.category, 'APP CATEGORY UNKNOWN')}"
        )

        values = {
            "version": details.version_name or _NA,
            "version_code": _NA if details.version_code is None else str(details.version_code),
            "uid": _NA if details.uid is None else str(details.uid),
            "installer": details.installer or _NA,
            "apk_path": details.apk_path or _NA,
            "install_location": details.install_location or _NA,
            "state": _ENABLED_LABELS.get(details.enabled, _NA),
            "launchable": details.launchable_activity or _NA,
        }
        for key, text in values.items():
            self._rows[key].setText(text)

        parts = []
        if details.activities:
            parts.append(f"Activities: {len(details.activities)}")
        if details.services:
            parts.append(f"Services: {len(details.services)}")
        if details.receivers:
            parts.append(f"Receivers: {len(details.receivers)}")
        if parts:
            self._components.setText("  ".join(parts))

        self._refresh_actions()
        self._refresh_permission_button()
        self.show()

    def show_details_failed(self, package: str, message: str) -> None:
        """Show the honest "could not be read" state for *package*.

        Only rendered when the failure still belongs to the current
        selection; a stale failure from a previous selection is discarded.
        """
        if package != self._package:
            return
        self._reset()
        self._package = package
        self._title.setText(package)
        self._subtitle.setText(f"{_NOT_READ} ({message})")
        self._actions_caption.setText("Actions unavailable")
        self.show()

    def clear(self) -> None:
        """Hide the panel entirely (device disconnected / closing)."""
        self._reset()
        self.hide()

    def current_package(self) -> str | None:
        """The package whose details are currently shown (or ``None``)."""
        return self._package

    def current_details(self) -> AppDetails | None:
        """The details record of the current selection (or ``None``)."""
        return self._details

    # ------------------------------------------------------------------
    # Device Actions
    # ------------------------------------------------------------------

    def set_actions_busy(self, busy: bool) -> None:
        """Disable action buttons while an action is in flight."""
        self._busy = busy
        self._refresh_actions()

    def show_action_result(self, result: ActionResult) -> None:
        """Render the typed outcome of an action, if it still belongs here.

        The result is rendered only when its package still matches the
        current selection; otherwise it is discarded (stale results must
        never appear under a different application). The busy lock is
        released either way.
        """
        self._busy = False
        self._refresh_actions()
        if result.package_name != self._package:
            return
        self._status.setText(result.message)
        self._status.setObjectName(
            "muted" if result.success or result.error_kind is None else "statusWarn"
        )
        self._restyle(self._status)

    def _on_action_clicked(self, action: str) -> None:
        package = self._package
        details = self._details
        if package is None or details is None:
            return
        available = supported_actions(
            is_system=details.category is AppCategory.SYSTEM,
            enabled=details.enabled,
        )
        if action not in available:
            return
        self.action_requested.emit(action, package)

    def _on_toggle_clicked(self) -> None:
        details = self._details
        if details is None or details.enabled is None:
            return
        self._on_action_clicked(ENABLE if details.enabled is False else DISABLE)

    def _refresh_actions(self) -> None:
        """Recompute button availability from the current details record.

        The safe default when nothing is loaded is all buttons disabled.
        """
        details = self._details
        if details is None:
            self._actions_caption.setText("Actions unavailable")
            self._set_buttons(())
            return

        is_system = details.category is AppCategory.SYSTEM
        available = supported_actions(is_system=is_system, enabled=details.enabled)

        if is_system:
            self._actions_caption.setText(_SYSTEM_APP_NOTE)
        else:
            self._actions_caption.setText(f"Actions for {details.package_name}")

        if self._busy:
            self._set_buttons(())
            return
        self._set_buttons(available)

    def _set_buttons(self, available: tuple[str, ...]) -> None:
        self._open_btn.setEnabled(LAUNCH in available)
        self._info_btn.setEnabled(APP_INFO in available)
        self._stop_btn.setEnabled(FORCE_STOP in available)
        has_toggle = ENABLE in available or DISABLE in available
        self._toggle_btn.setEnabled(has_toggle)
        if self._details is not None and self._details.enabled is False:
            self._toggle_btn.setText("Enable")
        else:
            self._toggle_btn.setText("Disable")
        self._uninstall_btn.setEnabled(UNINSTALL in available)

    # ------------------------------------------------------------------
    # Permissions audit
    # ------------------------------------------------------------------

    def _refresh_permission_button(self) -> None:
        self._audit_btn.setEnabled(
            self._package is not None and not self._permission_busy
        )

    def _on_audit_clicked(self) -> None:
        package = self._package
        if package is None or self._permission_busy:
            return
        self.permission_audit_requested.emit(package)
        self._permission_busy = True
        self._refresh_permission_button()
        self._perm_status.setText("Reading permissions…")
        self._perm_status.setObjectName("muted")
        self._restyle(self._perm_status)

    def show_permission_audit(self, audit: PackagePermissionAudit) -> None:
        """Render an audit outcome, unless it belongs to a previous selection."""
        self._permission_busy = False
        self._refresh_permission_button()
        if audit.package_name != self._package:
            return
        if audit.parse_complete:
            text = f"Permission audit: {len(audit.permissions)} permission entries"
        else:
            text = "Permission audit could not be completed"
        self._perm_status.setText(text)
        self._perm_status.setObjectName(
            "muted" if audit.parse_complete else "statusWarn"
        )
        self._restyle(self._perm_status)

    def show_permission_audit_failed(self, package: str, message: str) -> None:
        """Render a typed audit failure, unless it belongs to a previous
        selection."""
        self._permission_busy = False
        self._refresh_permission_button()
        if package != self._package:
            return
        self._perm_status.setText(f"Permission read failed: {message}")
        self._perm_status.setObjectName("statusWarn")
        self._restyle(self._perm_status)

    @staticmethod
    def _restyle(label: QLabel) -> None:
        style = label.style()
        style.unpolish(label)
        style.polish(label)
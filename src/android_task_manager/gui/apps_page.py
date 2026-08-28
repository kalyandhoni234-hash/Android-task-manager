"""Applications page: installed-application inventory with management.

The page presents the normalized :class:`ApplicationSnapshot` with
client-side filtering (package name/PID-free), numeric-aware header sorting
and a detail panel below the table. Selecting a row emits
:attr:`detail_requested` so the dashboard can run an on-demand
``dumpsys package`` read off the GUI thread; the result (or a typed
failure) is rendered in the embedded detail panel.

The page itself never talks to ADB: refresh requests and detail requests
are signals, and everything that mutates the device flows through the
window-level action layer.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ..action import ActionResult
from ..applications import AppCategory, AppDetails, ApplicationSnapshot
from ..permissions import PackagePermissionAudit
from .widgets import panel_host
from .widgets.app_details_widget import AppDetailsWidget

_COLUMN_PACKAGE = 0
_COLUMN_TYPE = 1
_COLUMN_STATE = 2
_COLUMN_UID = 3
_COLUMN_VERSION = 4
_COLUMN_APK = 5

_COLUMNS = ("PACKAGE", "TYPE", "STATE", "UID", "VERSION", "APK PATH")

#: Default presentation order: package name ascending.
_DEFAULT_SORT_COLUMN = _COLUMN_PACKAGE
_DEFAULT_SORT_ORDER = Qt.SortOrder.AscendingOrder

_TYPE_LABELS = {
    AppCategory.SYSTEM: "SYSTEM",
    AppCategory.USER: "USER",
    AppCategory.UNKNOWN: "UNKNOWN",
}
_ENABLED_LABELS = {True: "Enabled", False: "Disabled"}

#: System rows get a quiet tint so the destructive-control boundary reads
#: at a glance (kept inside the existing dark palette).
_SYSTEM_BACKGROUND = QColor("#2b3238")

#: Caption shown before the first inventory read arrives.
_AWAITING = "Waiting for the device — the application list appears here."

#: Caption shown while an inventory refresh is in flight.
_LOADING = "Loading applications…"

#: Caption shown when the inventory could not be read.
_ERROR_PREFIX = "Application list unavailable: "


class _SortableItem(QTableWidgetItem):
    """A table cell that sorts by an explicit key, not by its text."""

    def __init__(self, text: str, key: object) -> None:
        super().__init__(text)
        self._key = key

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, _SortableItem):
            return super().__lt__(other)  # type: ignore[no-any-return]
        left, right = self._key, other._key
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return str(left).lower() < str(right).lower()


class ApplicationsPage(QWidget):
    """The installed-application management page."""

    #: The user pressed Refresh; the window forwards it to the apps worker.
    refresh_requested = Signal()

    #: (package) the user selected a row (or a pending selection resolved);
    #: the window forwards it to the apps worker's detail read.
    detail_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "APPLICATIONS")

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondary")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        toolbar.addWidget(self._refresh_btn)
        self._filter = QLineEdit()
        self._filter.setObjectName("processFilter")
        self._filter.setPlaceholderText("Filter applications...")
        self._filter.setClearButtonEnabled(True)
        self._filter.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._filter.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter, 1)
        self._count = QLabel("")
        self._count.setObjectName("muted")
        toolbar.addWidget(self._count)
        layout.addLayout(toolbar)

        self._status = QLabel(_AWAITING)
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(_COLUMN_APK, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(_COLUMN_PACKAGE, 280)
        self._table.setColumnWidth(_COLUMN_TYPE, 80)
        self._table.setColumnWidth(_COLUMN_STATE, 80)
        self._table.setColumnWidth(_COLUMN_UID, 80)
        self._table.setColumnWidth(_COLUMN_VERSION, 100)
        self._table.setSortingEnabled(True)
        self._table.sortItems(_DEFAULT_SORT_COLUMN, _DEFAULT_SORT_ORDER)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        layout.addWidget(self._table)

        self._details = AppDetailsWidget()
        layout.addWidget(self._details)

        self._all_apps: list = []
        self._filter_query = ""
        self._sort_column = _DEFAULT_SORT_COLUMN
        self._sort_order = _DEFAULT_SORT_ORDER
        self._selected_package: str | None = None
        self._pending: str | None = None

    @property
    def details(self) -> AppDetailsWidget:
        """The embedded detail/actions panel."""
        return self._details

    # ------------------------------------------------------------------
    # Filtering / sorting
    # ------------------------------------------------------------------

    def _on_filter_changed(self, text: str) -> None:
        self._filter_query = text.strip()
        self._rebuild()

    def _matches_filter(self, app) -> bool:
        query = self._filter_query
        if not query:
            return True
        needle = query.lower()
        return needle in app.package_name.lower()

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        self._sort_column = column
        self._sort_order = order

    # ------------------------------------------------------------------
    # Snapshot rendering
    # ------------------------------------------------------------------

    def set_loading(self) -> None:
        """Show the loading caption (a refresh is in flight)."""
        self._status.setText(_LOADING)
        self._status.setObjectName("muted")

    def set_snapshot(self, snapshot: ApplicationSnapshot) -> None:
        """Replace the table contents (filter + user sort applied)."""
        self._all_apps = list(snapshot.applications)
        self._status.setText("")
        self._rebuild()
        self._resolve_pending()

    def show_inventory_failed(self, message: str) -> None:
        """Show the honest error state; the previous table is not reused."""
        self._status.setText(f"{_ERROR_PREFIX}{message}")
        self._status.setObjectName("statusWarn")

    def clear(self) -> None:
        """Reset the page for a device disconnect (no stale data lingers)."""
        self._all_apps = []
        self._pending = None
        self._selected_package = None
        self._table.setRowCount(0)
        self._count.setText("")
        self._status.setText(_AWAITING)
        self._status.setObjectName("muted")
        self._details.clear()

    def select_package(self, package: str) -> None:
        """Select *package* for management; falls back to a direct detail
        request when the package is not in the current table (inventory
        stale, filtered out, or not yet loaded)."""
        self._pending = package
        self._resolve_pending()

    def _resolve_pending(self) -> None:
        package = self._pending
        if package is None:
            return
        row = self._row_of(package)
        if row is None:
            self._details.show_loading(package)
            self.detail_requested.emit(package)
            return
        self._pending = None
        self._select_row(row)

    def _row_of(self, package: str) -> int | None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COLUMN_PACKAGE)
            if item is not None and item.text() == package:
                return row
        return None

    def _select_row(self, row: int) -> None:
        item = self._table.item(row, _COLUMN_PACKAGE)
        if item is None:
            return
        package = item.text()
        if package == self._selected_package:
            # Already the current selection: selectRow() would not emit the
            # selection-changed signal, so request the details directly.
            self.detail_requested.emit(package)
            return
        self._table.selectRow(row)

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        item = self._table.item(rows[0].row(), _COLUMN_PACKAGE)
        if item is None:
            return
        package = item.text()
        self._selected_package = package
        self._pending = None
        self.detail_requested.emit(package)

    def _rebuild(self) -> None:
        visible = [a for a in self._all_apps if self._matches_filter(a)]
        self._table.setUpdatesEnabled(False)
        try:
            self._table.setSortingEnabled(False)
            self._table.setRowCount(len(visible))
            for row_index, app in enumerate(visible):
                uid = app.uid
                version = app.version_code
                values = (
                    _SortableItem(app.package_name, app.package_name.lower()),
                    _SortableItem(
                        _TYPE_LABELS.get(app.category, "UNKNOWN"),
                        _TYPE_LABELS.get(app.category, "UNKNOWN").lower(),
                    ),
                    _SortableItem(
                        _ENABLED_LABELS.get(app.enabled, "N/A"),
                        str(_ENABLED_LABELS.get(app.enabled, "N/A")).lower(),
                    ),
                    _SortableItem(
                        "N/A" if uid is None else str(uid),
                        uid if uid is not None else float("-inf"),
                    ),
                    _SortableItem(
                        "N/A" if version is None else str(version),
                        version if version is not None else float("-inf"),
                    ),
                    _SortableItem(app.apk_path or "N/A", (app.apk_path or "N/A").lower()),
                )
                for column, item in enumerate(values):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if app.category is AppCategory.SYSTEM:
                        item.setBackground(QBrush(_SYSTEM_BACKGROUND))
                    self._table.setItem(row_index, column, item)
            self._table.setSortingEnabled(True)
            self._table.sortItems(self._sort_column, self._sort_order)
        finally:
            self._table.setUpdatesEnabled(True)
        self._count.setText(
            f"{len(visible)} / {len(self._all_apps)} installed"
            if self._filter_query
            else f"{len(visible)} installed"
        )

    # ------------------------------------------------------------------
    # Detail panel forwarding
    # ------------------------------------------------------------------

    def show_details(self, details: AppDetails) -> None:
        """Present a completed detail read below the table."""
        self._selected_package = details.package_name
        self._details.set_details(details)

    def show_details_failed(self, package: str, message: str) -> None:
        """Present the honest failure state for the requested package."""
        self._details.show_details_failed(package, message)

    def set_actions_busy(self, busy: bool) -> None:
        """Forward the action busy lock to the detail panel."""
        self._details.set_actions_busy(busy)

    def show_action_result(self, result: ActionResult) -> None:
        """Render the typed action outcome in the detail panel."""
        self._details.show_action_result(result)

    def show_permission_audit(self, audit: PackagePermissionAudit) -> None:
        """Render a permission audit outcome in the detail panel."""
        self._details.show_permission_audit(audit)

    def show_permission_audit_failed(self, package: str, message: str) -> None:
        """Render a typed permission audit failure in the detail panel."""
        self._details.show_permission_audit_failed(package, message)
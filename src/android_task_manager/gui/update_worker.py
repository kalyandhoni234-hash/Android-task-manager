"""Worker that runs the one-shot update check off the GUI thread.

The check is a network call (GitHub API), so — like every other worker in
this app — it runs on a QThread through queued connections. The dashboard
never blocks while the release feed is being fetched, and every failure
mode is silent: the worker always emits exactly one typed
``UpdateCheckResult`` and never raises.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal, Slot

from ..core.diagnostics import log_unexpected_failure
from ..updater import UpdateCheckResult, check_for_update


class UpdateWorker(QObject):
    """One-shot update check against the latest GitHub release."""

    #: (UpdateCheckResult) the check finished — success or failure.
    check_completed = Signal(object)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self._current_version = current_version
        self._busy = False

    def is_busy(self) -> bool:
        """True while a check is in flight (duplicate requests are dropped)."""
        return self._busy

    @Slot()
    def request_check(self) -> None:
        """Run the check and publish the typed result (never raises)."""
        if self._busy:
            return
        self._busy = True
        try:
            result = check_for_update(self._current_version)
        except Exception as exc:  # noqa: BLE001 - a worker bug never freezes the GUI
            log_unexpected_failure("updates", "check", exc)
            result = UpdateCheckResult(
                checked_at=datetime.now(timezone.utc),
                current_version=self._current_version,
                error="The update check failed unexpectedly.",
            )
        finally:
            self._busy = False
        self.check_completed.emit(result)
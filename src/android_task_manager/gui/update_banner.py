"""Slim dismissible banner announcing a newer release.

Rendered by the main window when the one-shot update check reports
``update_available``; hidden in every other case (up to date, or the check
failed silently). Dismissing it hides it for the rest of this app session
(in-memory only, no persistence). The banner never downloads or installs
anything — "View Release" only opens the release page in the system's
default browser.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..updater import UpdateCheckResult

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _is_safe_url(url: str | None) -> bool:
    """Return True only if *url* uses an allowed scheme (http/https)."""
    if not url:
        return False
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme.lower() in _ALLOWED_URL_SCHEMES


def _display_version(version: str) -> str:
    """Normalize a tag to a single leading ``v`` (GitHub tags are ``v0.2.0``)."""
    text = version.strip()
    if text[:1].lower() == "v":
        return text
    return f"v{text}"


class UpdateBanner(QWidget):
    """A compact, quiet strip: message, release link, dismiss control."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("updateBanner")
        self._url: str | None = None
        self._dismissed = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 8, 8)
        layout.setSpacing(10)

        self._message = QLabel("")
        self._message.setObjectName("caption")
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._message)

        self._view = QPushButton("View Release")
        self._view.setObjectName("link")
        self._view.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._view.clicked.connect(self._open_release)
        layout.addWidget(self._view)

        layout.addStretch(1)

        self._dismiss = QPushButton("\u00d7")
        self._dismiss.setObjectName("link")
        self._dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._dismiss.setToolTip("Dismiss")
        self._dismiss.setAccessibleName("Dismiss update banner")
        self._dismiss.clicked.connect(self._on_dismissed)
        layout.addWidget(self._dismiss)

        self.hide()

    def show_result(self, result: UpdateCheckResult) -> None:
        """Show the banner for an available update; hide it otherwise.

        Failed checks and up-to-date states stay invisible — an error
        dialog is never shown. A dismissed banner stays hidden for the
        rest of this session.
        """
        if self._dismissed:
            return
        if not result.update_available or not result.latest_version or not result.release_url:
            self.hide()
            return
        self._url = result.release_url
        self._message.setText(
            f"A new version ({_display_version(result.latest_version)}) is available."
        )
        self.show()

    def _on_dismissed(self) -> None:
        self._dismissed = True
        self.hide()

    def _open_release(self) -> None:
        if _is_safe_url(self._url):
            url = self._url
            assert url is not None  # guaranteed by _is_safe_url
            QDesktopServices.openUrl(QUrl(url))
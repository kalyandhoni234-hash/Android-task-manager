"""Update checks against the GitHub release feed.

``fetch_latest_release_tag`` performs one HTTP GET with an explicit timeout
and never raises: every failure mode (no network, non-200, timeout,
malformed JSON, missing fields) collapses into ``(None, None)``.
``check_for_update`` orchestrates fetch + comparison into a single
``UpdateCheckResult`` and likewise never raises.

The repo's release tags are ``v<version>`` (e.g. ``v0.2.0``); the running
app's version (``android_task_manager.__version__``) has no prefix. Both
forms parse identically.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

from .models import UpdateCheckResult

#: Allowed URL schemes for release links — anything else is rejected.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

#: GitHub API endpoint for the newest published release of this repository.
_RELEASES_LATEST_URL = (
    "https://api.github.com/repos/kalyandhoni234-hash/Android-task-manager/releases/latest"
)


class VersionParseError(ValueError):
    """A version string could not be parsed into comparable parts."""


def _urlopen(request: Request, timeout: float) -> Any:
    """Thin indirection so tests can stub the network without a real call."""
    return urlopen(request, timeout=timeout)


def parse_version(value: str) -> tuple[int, ...]:
    """Parse ``'v1.2.3'`` / ``'1.2.3'`` style versions into a comparable tuple.

    Raises :class:`VersionParseError` on unparseable input (empty string,
    non-numeric parts, pre-release-style tags such as ``'latest'`` or
    ``'nightly-build'``).
    """
    text = value.strip()
    if text[:1].lower() == "v":
        text = text[1:]
    if not text:
        raise VersionParseError(f"empty version string: {value!r}")
    parts = text.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise VersionParseError(f"unparseable version string: {value!r}")
    return tuple(int(part) for part in parts)


def is_newer(current: str, latest: str) -> bool:
    """True when *latest* is a newer release than *current*.

    Pure function, no I/O. A ``v`` prefix on either side is ignored
    consistently (GitHub tags are typically ``v0.2.0``). If either string
    fails to parse, returns ``False`` — an unparseable version never
    claims an update is available.
    """
    try:
        current_version = parse_version(current)
        latest_version = parse_version(latest)
    except VersionParseError:
        return False
    return latest_version > current_version


def fetch_latest_release_tag(timeout_seconds: float = 5.0) -> tuple[str | None, str | None]:
    """Fetch ``(tag_name, html_url)`` of the latest GitHub release.

    Returns ``(None, None)`` on any failure — network error, non-200
    response, timeout, malformed JSON or missing fields. Never raises out
    of this function; the timeout guarantees the call cannot hang the
    calling thread indefinitely.
    """
    try:
        request = Request(_RELEASES_LATEST_URL, headers={"User-Agent": "android-task-manager"})
        with _urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", None)
            if status is not None and status != 200:
                return None, None
            payload = json.loads(response.read().decode("utf-8"))
        tag = payload.get("tag_name")
        url = payload.get("html_url")
        if not isinstance(tag, str) or not tag:
            return None, None
        if not isinstance(url, str) or not url:
            return None, None
        # Reject non-http(s) URLs — a compromised API response must not
        # cause javascript:/file:/data: URLs to be opened.
        from urllib.parse import urlparse

        try:
            scheme = urlparse(url).scheme.lower()
        except ValueError:
            return None, None
        if scheme not in _ALLOWED_SCHEMES:
            return None, None
        return tag, url
    except Exception:  # noqa: BLE001 - every network/parsing failure is silent
        return None, None


def check_for_update(current_version: str) -> UpdateCheckResult:
    """Compare *current_version* against the latest GitHub release.

    Never raises: any unexpected failure is folded into an
    ``UpdateCheckResult`` with ``update_available`` False and a short
    human-readable ``error``.
    """
    checked_at = datetime.now(timezone.utc)
    try:
        tag, url = fetch_latest_release_tag()
    except Exception:  # noqa: BLE001 - last line of defense, never raise
        return UpdateCheckResult(
            checked_at=checked_at,
            current_version=current_version,
            error="The update check failed unexpectedly.",
        )
    if tag is None:
        return UpdateCheckResult(
            checked_at=checked_at,
            current_version=current_version,
            error="The update check could not reach the GitHub release feed.",
        )
    try:
        available = is_newer(current_version, tag)
    except Exception:  # noqa: BLE001 - an unparseable tag never claims an update
        available = False
    return UpdateCheckResult(
        checked_at=checked_at,
        current_version=current_version,
        latest_version=tag,
        update_available=available,
        release_url=url,
    )
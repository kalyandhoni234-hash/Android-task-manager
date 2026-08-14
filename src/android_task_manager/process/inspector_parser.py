"""Parsers for the read-only process-inspection /proc/<pid> files.

Each parser is defensive: unknown keys and malformed individual values are
ignored rather than raising, because Android permission/version differences
mean fields legitimately come and go. Only a file that cannot even provide its
core structure (the stat line's parenthesized comm) raises ``StatParseError``.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Expected CPU THz-> scheduling priority is at stat field 18; the tail list
#: (fields after comm) is indexed by ``field_number - 3``.
_PRIORITY_INDEX = 18 - 3  # 15
_NICE_INDEX = 19 - 3  # 16
_NUM_THREADS_INDEX = 20 - 3  # 17
_VSIZE_INDEX = 23 - 3  # 20
_RSS_INDEX = 24 - 3  # 21


@dataclass(frozen=True)
class StatusFields:
    """Parsed, Optional-valued fields from /proc/<pid>/status."""

    name: str | None = None
    state: str | None = None
    uid: int | None = None
    threads: int | None = None
    vm_size_kb: int | None = None
    vm_rss_kb: int | None = None
    rss_anon_kb: int | None = None
    rss_file_kb: int | None = None
    rss_shmem_kb: int | None = None


@dataclass(frozen=True)
class StatFields:
    """Parsed fields from /proc/<pid>/stat (comm handled via paren isolation)."""

    name: str | None = None
    state: str | None = None
    priority: int | None = None
    nice: int | None = None
    num_threads: int | None = None
    vsize_bytes: int | None = None
    rss_pages: int | None = None


class StatParseError(ValueError):
    """The stat line has no usable parenthesized comm structure."""


_STATUS_VALUE_KEYS = {
    "Name": "name",
    "State": "state",
    "Uid": "uid",
    "Threads": "threads",
    "VmSize": "vm_size_kb",
    "VmRSS": "vm_rss_kb",
    "RssAnon": "rss_anon_kb",
    "RssFile": "rss_file_kb",
    "RssShmem": "rss_shmem_kb",
}


def _to_kb(value: str) -> int | None:
    """Parse a kernel byte/KiB token like ``"227"`` or ``"227 kB"``."""
    token = value.strip()
    if token.endswith("kB"):
        token = token[:-2].strip()
    token = token.split()[0] if token else ""
    try:
        return int(token)
    except ValueError:
        return None


def parse_status(text: str) -> StatusFields:
    """Parse /proc/<pid>/status key: value lines, ignoring unknown keys."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, remainder = line.partition(":")
        key = key.strip()
        remainder = remainder.strip()
        if key in _STATUS_VALUE_KEYS:
            values[key] = remainder

    return StatusFields(
        name=values.get("Name") or None,
        state=values.get("State") or None,
        uid=_parse_uid(values.get("Uid")),
        threads=_to_int(values.get("Threads")),
        vm_size_kb=_to_kb(values.get("VmSize", "")),
        vm_rss_kb=_to_kb(values.get("VmRSS", "")),
        rss_anon_kb=_to_kb(values.get("RssAnon", "")),
        rss_file_kb=_to_kb(values.get("RssFile", "")),
        rss_shmem_kb=_to_kb(values.get("RssShmem", "")),
    )


def _parse_uid(value: str | None) -> int | None:
    """Real UID is the first of Uid's four whitespace values."""
    if not value:
        return None
    first = value.split()[0] if value.split() else None
    return _to_int(first)


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def parse_stat(text: str) -> StatFields:
    """Parse /proc/<pid>/stat.

    The comm field is enclosed in a single parenthesized group and may contain
    spaces and parentheses, so the line is split on the first ``(`` and last
    ``)`` rather than by naive whitespace. The remaining tail fields are then
    indexed from field 3 (state) onward.
    """
    open_idx = text.find("(")
    close_idx = text.rfind(")")
    if open_idx == -1 or close_idx == -1 or close_idx < open_idx:
        raise StatParseError("no parenthesized comm group in stat line")

    name = text[open_idx + 1 : close_idx]
    tail = text[close_idx + 1 :].split()
    # pid comes from the prefix before '(' (or is recorded by the caller).
    fields: dict[str, int | None] = {}

    def field_at(index: int):
        try:
            return int(tail[index])
        except (IndexError, ValueError):
            return None

    return StatFields(
        name=name or None,
        state=tail[0] if len(tail) > 0 else None,
        priority=field_at(_PRIORITY_INDEX),
        nice=field_at(_NICE_INDEX),
        num_threads=field_at(_NUM_THREADS_INDEX),
        vsize_bytes=field_at(_VSIZE_INDEX),
        rss_pages=field_at(_RSS_INDEX),
    )


def parse_cmdline(text: str) -> str | None:
    """Convert NUL-separated cmdline args to a readable string.

    Empty/whitespace-only cmdline (including bare NUL padding) yields ``None``
    so the UI can show "N/A" without inventing a command line from the process
    name.
    """
    joined = " ".join(text.split("\x00")).strip()
    return joined or None


def parse_io(text: str) -> tuple[int | None, int | None]:
    """Return (read_bytes, write_bytes) from /proc/<pid>/io, or None,None.

    Android may omit these or hide the file behind a permission boundary; the
    collector handles a failed read before this parser is ever called.
    """
    read_bytes = None
    write_bytes = None
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, remainder = line.partition(":")
        remainder = remainder.strip()
        value = _to_int(remainder)
        if key.strip() == "read_bytes":
            read_bytes = value
        elif key.strip() == "write_bytes":
            write_bytes = value
    return read_bytes, write_bytes
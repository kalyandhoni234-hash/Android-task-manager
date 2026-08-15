"""Parsing of Android ``ps`` and ``top`` output into normalized models.

Two independent parsers live here:

- ``parse_ps_output`` — authoritative process identity (PID, UID, NAME).
- ``parse_top_output`` — dynamic CPU/memory percentages (merged later by PID).

They fail loudly on an unusable header (a parser error), but skip individual
malformed rows so one bad process never crashes the whole monitor. A
non-numeric CPU/percent *cell* on an otherwise-valid row is treated as a
"missing optional metric" (None), a distinct case from a malformed row.
"""

from __future__ import annotations

import re
from typing import Sequence

from .models import ProcessCPUMetrics, ProcessIdentity

# TIME+ column values look like "24:48.52", "85:09.94", "2:20.81", "0:00".
_TIME_RE = re.compile(r"^\d+:\d{2}(:\d{2})?(\.\d+)?$")

# ANSI/terminal control sequences (CSI: ESC [ params final). These appear in
# real `top` output (e.g. cursor-position reports, bold/reverse-video row
# decoration) and must never be parsed as process data. Normalization is
# isolated to this top parser.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI/terminal control sequences from top output.

    Only used here in the top parser; ps parsing is untouched.
    """
    return _ANSI_CSI_RE.sub("", text)


class ProcessParseError(ValueError):
    """Raised when ps/top output has no usable structure (e.g. missing header)."""


# ---------------------------------------------------------------------------
# ps
# ---------------------------------------------------------------------------

def parse_ps_output(text: str) -> list[ProcessIdentity]:
    """Parse ``ps -A -o PID,PPID,UID,NAME`` into process identities.

    The header row and blank lines are ignored. Any number of extra columns or
    spaces is tolerated; the NAME is everything after the leading numeric
    columns so command names containing spaces survive. Rows with a
    non-numeric PID, PPID or UID are skipped. On duplicate PIDs the first
    occurrence wins.

    Both the current four-column layout (PID PPID UID NAME) and the older
    three-column layout (PID UID NAME) are accepted; three-column rows get
    ``ppid=None`` (a parent was not collected — never inferred).
    """
    identities: list[ProcessIdentity] = []
    seen_pids: set[int] = set()

    for raw_line in text.splitlines():
        tokens = raw_line.strip().split()
        if not tokens or tokens[0] == "PID":
            continue  # blank line or the column header row

        if len(tokens) < 3:
            continue  # malformed / too short row

        try:
            pid = int(tokens[0])
            if len(tokens) >= 4:
                ppid = int(tokens[1])
                uid = int(tokens[2])
                name = " ".join(tokens[3:])
            else:
                ppid = None
                uid = int(tokens[1])
                name = " ".join(tokens[2:])
        except ValueError:
            continue  # malformed row — skip, don't crash the monitor

        if pid in seen_pids:
            continue  # duplicate PID: first wins
        seen_pids.add(pid)

        identities.append(ProcessIdentity(pid=pid, uid=uid, name=name, ppid=ppid))

    return identities


# ---------------------------------------------------------------------------
# top
# ---------------------------------------------------------------------------

def parse_top_output(text: str) -> list[ProcessCPUMetrics]:
    """Parse ``top -n 1`` (Android/toybox) into per-process dynamic metrics.

    ANSI control sequences are stripped first (they vary in length per line —
    the header row arrives wrapped in reverse-video codes, the first data row
    in bold codes — so they must never define column offsets). Then the column
    header row (containing ``PID`` and ``%CPU``) is located; only its presence
    is validated, because Android/toybox right-aligns every column to
    per-column widths, which makes absolute character offsets drift between
    rows. Instead, each data row is split on whitespace and anchored from its
    END: ``TIME+`` has a fixed shape, the ``S %CPU %MEM`` values sit
    immediately before it, and everything after it is the process name (which
    may itself contain spaces, e.g. ``top -n 1``). Blank middle cells
    (PR/NI/VIRT/RES/SHR) are naturally tolerated. Rows whose PID cannot be
    parsed are skipped.
    """
    text = _strip_ansi(text)
    lines = text.splitlines()

    header_index = _find_table_header(lines)
    if header_index is None:
        raise ProcessParseError(
            "top output has no process table header (expected 'PID ... %CPU ...')."
        )

    metrics: list[ProcessCPUMetrics] = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        tokens = line.split()
        try:
            pid = int(tokens[0])
        except (ValueError, IndexError):
            continue  # not a real table row (summary/separator) — skip

        state, cpu, mem, name = _row_metrics(tokens)
        metrics.append(
            ProcessCPUMetrics(
                pid=pid,
                name=name,
                state=state,
                cpu_percent=cpu,
                memory_percent=mem,
            )
        )
    return metrics


def _find_table_header(lines: Sequence[str]) -> int | None:
    for index, line in enumerate(lines):
        tokens = line.split()
        if "PID" in tokens and ("%CPU" in tokens or "S[%CPU]" in tokens):
            return index
    return None


def _row_metrics(
    tokens: list[str],
) -> tuple[str | None, float | None, float | None, str | None]:
    """Extract (state, cpu_percent, memory_percent, name) from a row's tokens.

    Anchors on the ``TIME+`` token (found by shape, scanning from the right):
    ``%MEM``, ``%CPU`` and ``S`` are the three tokens before it, and the name
    is everything after it. A non-numeric metric cell yields None (missing
    metric) rather than a crash.
    """
    body = tokens[1:]  # everything after PID
    time_index: int | None = None
    for index in range(len(body) - 1, -1, -1):
        if _TIME_RE.fullmatch(body[index]):
            time_index = index
            break

    if time_index is None:
        # No TIME+ column: nothing metric-bearing to anchor on.
        return None, None, None, (" ".join(body) or None)

    state = _parse_state(body[time_index - 3]) if time_index >= 3 else None
    cpu = _parse_pct(body[time_index - 2]) if time_index >= 2 else None
    mem = _parse_pct(body[time_index - 1]) if time_index >= 1 else None
    name = " ".join(body[time_index + 1 :]) or None
    return state, cpu, mem, name


def _parse_state(value: str) -> str | None:
    """A state column token is a single alpha character (S/R/I/D/Z/...)."""
    return value if len(value) == 1 and value.isalpha() else None


def _parse_pct(value: str) -> float | None:
    """Parse a percent cell, returning None for a missing/unparseable metric."""
    cleaned = value.strip().strip("%")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        # On an otherwise-valid row, a bad percent cell is a missing metric.
        return None

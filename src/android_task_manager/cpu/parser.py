"""Parsing of Linux CPU accounting text from ``/proc/stat`` and cpufreq nodes."""

from __future__ import annotations

import re

from .models import CPUCounters, ProcStat

# Aggregate line:  "cpu  7412737 2342824 5072560 ..."
_AGGREGATE_RE = re.compile(r"^cpu\s+(.+)$")
# Per-core line:   "cpu0 964099 248320 566456 ..."
_CORE_RE = re.compile(r"^cpu(\d+)\s+(.+)$")

# Number of counters we consume per CPU line: user nice system idle iowait irq softirq
_COUNTER_FIELD_COUNT = 7


class CPUParseError(ValueError):
    """Raised when /proc/stat or cpufreq text can not be parsed safely.

    We deliberately fail loudly rather than emit silently-wrong metrics.
    """


def parse_proc_stat(text: str) -> ProcStat:
    """Parse ``/proc/stat`` into aggregate + per-core CPU counters.

    Lines not starting with ``cpu`` (intr, ctxt, btime, processes, softirq,
    procs_running, procs_blocked, ...) are ignored. Fields after ``softirq`` on
    a CPU line (steal, guest, guest_nice, ...) are tolerated and ignored.
    """
    aggregate: CPUCounters | None = None
    cores: list[CPUCounters] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("cpu"):
            continue

        core_match = _CORE_RE.match(line)
        if core_match:
            cores.append(_parse_counters(int(core_match.group(1)), core_match.group(2), line))
            continue

        aggregate_match = _AGGREGATE_RE.match(line)
        if aggregate_match:
            aggregate = _parse_counters(None, aggregate_match.group(1), line)
            continue

        # Starts with "cpu" but matches neither a core nor the aggregate line.
        raise CPUParseError(f"Malformed CPU line in /proc/stat: {raw_line!r}")

    if aggregate is None:
        raise CPUParseError("No aggregate 'cpu' line found in /proc/stat")

    cores.sort(key=lambda c: c.core_id)  # type: ignore[arg-type]  # core_id is int for cores
    return ProcStat(aggregate=aggregate, cores=cores)


def _parse_counters(
    core_id: int | None,
    fields_text: str,
    full_line: str,
) -> CPUCounters:
    tokens = fields_text.split()
    if len(tokens) < _COUNTER_FIELD_COUNT:
        raise CPUParseError(f"Too few fields on CPU line: {full_line!r}")

    try:
        values = [int(token) for token in tokens[:_COUNTER_FIELD_COUNT]]
    except ValueError as exc:
        raise CPUParseError(f"Non-integer counter on CPU line: {full_line!r}") from exc

    if any(v < 0 for v in values):
        raise CPUParseError(f"Negative tick counter on CPU line: {full_line!r}")

    user, nice, system, idle, iowait, irq, softirq = values
    return CPUCounters(
        core_id=core_id,
        user=user,
        nice=nice,
        system=system,
        idle=idle,
        iowait=iowait,
        irq=irq,
        softirq=softirq,
    )


def parse_scaling_frequency(text: str) -> int:
    """Parse a cpufreq ``scaling_cur_freq`` value into an integer kHz.

    The node contains a single integer (e.g. ``"1617000\\n"``).
    """
    tokens = text.strip().split()
    if len(tokens) != 1:
        raise CPUParseError(f"Unexpected cpufreq value: {text!r}")
    try:
        value = int(tokens[0])
    except ValueError as exc:
        raise CPUParseError(f"Non-integer cpufreq value: {text!r}") from exc
    if value < 0:
        raise CPUParseError(f"Negative cpufreq value: {text!r}")
    return value
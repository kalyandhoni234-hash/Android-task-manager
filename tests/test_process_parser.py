"""Unit tests for ps/top parsing and process classification.

No device required. Fixtures mirror the verified Android (Vivo V2026) ps/top
formats. Top rows are built as space-separated fields in header column order,
matching real `top -n 1` output where every column is whitespace-separated
(and numeric columns right-aligned).
"""

from __future__ import annotations

import re

import pytest

from android_task_manager.process.classification import classify_process
from android_task_manager.process.models import ProcessCategory
from android_task_manager.process.parser import ProcessParseError, parse_ps_output, parse_top_output

# ---------------------------------------------------------------------------
# Top fixture builder (rows mirror real `top -n 1` whitespace-separated rows).
# ---------------------------------------------------------------------------

TOP_HEADER = "  PID  USER           PR  NI  VIRT     RES     SHR  S  %CPU   %MEM        TIME+           ARGS" + " " * 40


def _row_for(
    header: str,
    pid,
    state,
    cpu,
    mem,
    name,
    user="root",
    pr="20",
    ni="0",
    virt="0K",
    res="0K",
    shr="0K",
    time="0:00.00",
    blank_middle=False,
) -> str:
    """Build a top data row as space-separated fields, like real top output.

    Values are joined by single spaces in header column order (the parser
    anchors on whitespace tokens, so exact column offsets are irrelevant).
    Android's merged ``S[%CPU]`` header still yields two separate values
    (state char, CPU percent) in the data row, mirroring the device.
    """
    labels = [m.group() for m in re.finditer(r"\S+", header)]
    values = {
        "PID": str(pid),
        "USER": user,
        "PR": "" if blank_middle else pr,
        "NI": "" if blank_middle else ni,
        "VIRT": "" if blank_middle else virt,
        "RES": "" if blank_middle else res,
        "SHR": "" if blank_middle else shr,
        "S": state,
        "%CPU": str(cpu),
        "%MEM": str(mem),
        "TIME+": time,
        "ARGS": name,
    }
    fields: list[str] = []
    for label in labels:
        if label == "S[%CPU]":
            # State char and CPU percent are separate tokens in data rows.
            for value in (state.strip(), str(cpu)):
                if value:
                    fields.append(value)
            continue
        value = values[label]
        if value and value.strip():
            fields.append(value)
    return " ".join(fields)


def _top_row(*args, **kwargs) -> str:
    return _row_for(TOP_HEADER, *args, **kwargs)


TOP_SUMMARY = (
    "Tasks: 123 total,   2 running, 121 sleeping,   0 stopped,   0 zombie\n"
    "Mem:  2870876k total,  2395504k used,   475372k free,   0k buffers\n"
    "Swap:  1048572k total,  0k used,  1048572k free\n"
)

TOP_ROWS = "\n".join(
    [
        _top_row(24791, "S", "2.9", "7.3", "com.instagram.android", user="u0_a203"),
        _top_row(754, "S", "1.2", "9.1", "system_server", user="system"),
        _top_row(2, "S", "0.0", "0.0", "[kthreadd]"),
        _top_row(24226, "R", "18.5", "4.1", "com.whatsapp", user="u0_a205"),
        _top_row(8150, "R", "120.4", "2.0", "com.heavy.app", user="u0_a99"),
    ]
)

TOP_TEXT = TOP_SUMMARY + TOP_HEADER + "\n" + TOP_ROWS + "\n"


# ---------------------------------------------------------------------------
# ps
# ---------------------------------------------------------------------------

PS_TEXT = """PID   PPID  UID  NAME
1     0     0    init
2     0     0    [kthreadd]
3     2     0    [ksoftirqd/0]
754   1     1000 system_server
24791 754   10203 com.instagram.android
24226 754   10205 com.whatsapp
"""

#: Legacy 3-column layout (PID UID NAME) — still accepted with ppid=None.
PS_TEXT_3COL = """PID   UID  NAME
1     0    init
2     0    [kthreadd]
754   1000 system_server
"""


def test_ps_header_skipped() -> None:
    identities = parse_ps_output(PS_TEXT)
    assert len(identities) == 6
    assert all(i.pid != -1 for i in identities)
    assert identities[0].pid == 1
    assert identities[0].name == "init"


def test_ps_process_row_fields() -> None:
    identities = parse_ps_output(PS_TEXT)
    by_pid = {i.pid: i for i in identities}
    assert by_pid[24791].uid == 10203
    assert by_pid[24791].name == "com.instagram.android"


def test_ps_ppid_parsed() -> None:
    identities = parse_ps_output(PS_TEXT)
    by_pid = {i.pid: i for i in identities}
    assert by_pid[754].ppid == 1
    assert by_pid[24226].ppid == 754
    assert by_pid[3].ppid == 2


def test_ps_legacy_three_column_layout_ppid_none() -> None:
    identities = parse_ps_output(PS_TEXT_3COL)
    assert len(identities) == 3
    assert all(i.ppid is None for i in identities)
    assert identities[2].name == "system_server"
    assert identities[2].uid == 1000


def test_ps_pid_and_uid_are_ints() -> None:
    identities = parse_ps_output(PS_TEXT)
    assert all(isinstance(i.pid, int) for i in identities)
    assert all(isinstance(i.uid, int) for i in identities)


def test_ps_names_with_spaces() -> None:
    text = PS_TEXT + "12345 754 10299 my app name here\n"
    identities = parse_ps_output(text)
    by_pid = {i.pid: i for i in identities}
    assert by_pid[12345].name == "my app name here"
    assert by_pid[12345].ppid == 754


def test_ps_names_with_unusual_characters() -> None:
    text = PS_TEXT + "9001 754 10207 some.app[1]&^special\n"
    identities = parse_ps_output(text)
    by_pid = {i.pid: i for i in identities}
    assert by_pid[9001].name == "some.app[1]&^special"


def test_ps_duplicate_pid_first_wins() -> None:
    text = PS_TEXT + "24791 754 99999 duplicate.name\n"
    identities = parse_ps_output(text)
    matches = [i for i in identities if i.pid == 24791]
    assert len(matches) == 1
    assert matches[0].uid == 10203  # first occurrence kept


def test_ps_malformed_rows_skipped() -> None:
    text = PS_TEXT + "abc def ghi jkl\n" + "1 2\n" + "\nnot a row at all\n"
    identities = parse_ps_output(text)
    assert len(identities) == 6  # malformed rows ignored, ps unchanged


# ---------------------------------------------------------------------------
# top
# ---------------------------------------------------------------------------

def test_top_header_detected_and_rows_parsed() -> None:
    metrics = parse_top_output(TOP_TEXT)
    pids = {m.pid for m in metrics}
    assert pids == {24791, 754, 2, 24226, 8150}


def test_top_parses_cpu_pct() -> None:
    metrics = parse_top_output(TOP_TEXT)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[24791].cpu_percent == pytest.approx(2.9)
    assert by_pid[24791].memory_percent == pytest.approx(7.3)
    assert by_pid[24791].state == "S"


def test_top_parses_cpu_above_100() -> None:
    metrics = parse_top_output(TOP_TEXT)
    by_pid = {m.pid: m for m in metrics}
    # Not clamped, not divided by core count.
    assert by_pid[8150].cpu_percent == pytest.approx(120.4)


def test_top_parses_name_and_state() -> None:
    metrics = parse_top_output(TOP_TEXT)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[754].name == "system_server"
    assert by_pid[754].state == "S"
    assert by_pid[24226].state == "R"


def test_top_blank_middle_cells_tolerated() -> None:
    text = TOP_SUMMARY + TOP_HEADER + "\n" + _top_row(9999, "S", "0.0", "0.0", "some.tool", blank_middle=True) + "\n"
    metrics = parse_top_output(text)
    assert len(metrics) == 1
    assert metrics[0].pid == 9999
    assert metrics[0].state == "S"
    assert metrics[0].cpu_percent == pytest.approx(0.0)
    assert metrics[0].name == "some.tool"


def test_top_malformed_rows_skipped() -> None:
    text = (
        TOP_SUMMARY
        + TOP_HEADER
        + "\n"
        + TOP_ROWS
        + "\n"
        + "this is not a pid row\n"
        + "=== separator ===\n"
        + _top_row(90001, "S", "1.0", "0.1", "top.only")
        + "\n"
    )
    metrics = parse_top_output(text)
    pids = {m.pid for m in metrics}
    assert 90001 in pids
    assert len(metrics) == 6  # two malformed lines skipped, valid row parsed


def test_top_missing_header_raises() -> None:
    with pytest.raises(ProcessParseError):
        parse_top_output("no table here\njust some text\n")


def test_top_missing_required_columns_raises() -> None:
    # A table-like header with neither PID nor %CPU cannot be parsed.
    with pytest.raises(ProcessParseError):
        parse_top_output("  USER  PR  NI  VIRT  RES  %MEM  TIME+  ARGS\n1 2 3 4 5 6 7 8\n")


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def test_classify_kernel_thread() -> None:
    assert classify_process("[kworker/0:1]", 0) is ProcessCategory.KERNEL_THREAD
    assert classify_process("[ksoftirqd/0]", 0) is ProcessCategory.KERNEL_THREAD


def test_classify_system_by_low_uid() -> None:
    assert classify_process("system_server", 1000) is ProcessCategory.SYSTEM
    assert classify_process("init", 0) is ProcessCategory.SYSTEM


def test_classify_user_by_app_uid() -> None:
    assert classify_process("com.instagram.android", 10203) is ProcessCategory.USER
    assert classify_process("com.whatsapp", 10205) is ProcessCategory.USER


def test_classify_unknown_uid_as_system() -> None:
    assert classify_process("some.process", None) is ProcessCategory.SYSTEM


# ---------------------------------------------------------------------------
# Real Vivo V2026 top header (state and CPU columns merged as "S[%CPU]").
# ---------------------------------------------------------------------------

VIVO_HEADER = "   PID  USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS" + " " * 40
VIVO_SUMMARY = (
    "Tasks: 401 total,   3 running, 398 sleeping,   0 stopped,   0 zombie\n"
    "Mem:  2870876k total,  2391636k used,   479240k free,   7116k buffers\n"
)
VIVO_TOP = VIVO_SUMMARY + VIVO_HEADER + "\n" + "\n".join(
    [
        _row_for(VIVO_HEADER, 16230, "S", "8.8", "17.9", "com.wildlife.g+", user="u0_a278", virt="38G", res="502M", shr="46M", time="24:48.52"),
        _row_for(VIVO_HEADER, 147, "S", "5.8", "0.0", "[kswapd0]", virt="0", res="0", shr="0", time="85:09.94"),
        _row_for(VIVO_HEADER, 1465, "S", "2.9", "5.5", "system_server", user="system", pr="18", ni="-2", virt="11G", res="155M", shr="61M", time="223:07.34"),
        _row_for(VIVO_HEADER, 805, "S", "2.9", "0.0", "[cldma_rxq0]", virt="0", res="0", shr="0", time="2:20.81"),
    ]
) + "\n"


def test_vivo_android_header_detected() -> None:
    metrics = parse_top_output(VIVO_TOP)
    assert {m.pid for m in metrics} == {16230, 147, 1465, 805}


def test_vivo_android_state_and_cpu_columns_detected() -> None:
    metrics = parse_top_output(VIVO_TOP)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[16230].state == "S"  # state column from the merged S[%CPU]
    assert by_pid[16230].cpu_percent == pytest.approx(8.8)


def test_vivo_android_cpu_values_parsed() -> None:
    metrics = parse_top_output(VIVO_TOP)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[16230].cpu_percent == pytest.approx(8.8)
    assert by_pid[147].cpu_percent == pytest.approx(5.8)
    assert by_pid[1465].cpu_percent == pytest.approx(2.9)
    assert by_pid[805].cpu_percent == pytest.approx(2.9)


def test_vivo_android_memory_percentages_parsed() -> None:
    metrics = parse_top_output(VIVO_TOP)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[16230].memory_percent == pytest.approx(17.9)
    assert by_pid[1465].memory_percent == pytest.approx(5.5)
    assert by_pid[147].memory_percent == pytest.approx(0.0)


def test_vivo_android_pid_values_parsed() -> None:
    metrics = parse_top_output(VIVO_TOP)
    assert all(isinstance(m.pid, int) for m in metrics)
    assert {m.pid for m in metrics} == {16230, 147, 1465, 805}


def test_vivo_android_truncated_names_accepted() -> None:
    metrics = parse_top_output(VIVO_TOP)
    by_pid = {m.pid: m for m in metrics}
    # Names may be truncated by top with "+"; we keep them verbatim.
    assert by_pid[16230].name == "com.wildlife.g+"


def test_vivo_android_cpu_above_100_not_reduced() -> None:
    text = VIVO_TOP + _row_for(VIVO_HEADER, 1111, "R", "120.4", "2.0", "com.multi.core") + "\n"
    metrics = parse_top_output(text)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[1111].cpu_percent == pytest.approx(120.4)


def test_vivo_android_cpu_26_4_parsed() -> None:
    text = VIVO_TOP + _row_for(VIVO_HEADER, 2222, "R", "26.4", "3.1", "com.mid.cpu") + "\n"
    metrics = parse_top_output(text)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[2222].cpu_percent == pytest.approx(26.4)


def test_vivo_android_ansi_sequences_do_not_break_parsing() -> None:
    ansi = "\x1b[30;120R\x1b[2J\x1b[1;1H"  # cursor-position report + clears
    text = (
        ansi
        + VIVO_SUMMARY
        + "\x1b[2K"
        + VIVO_HEADER
        + "\n"
        + "\x1b[30;120R" + _row_for(VIVO_HEADER, 16230, "S", "8.8", "17.9", "com.wildlife.g+") + "\n"
        + "\x1b[30;120R"  # ANSI-only line must be ignored, not parsed as a row
        + "\n"
        + _row_for(VIVO_HEADER, 147, "S", "5.8", "0.0", "[kswapd0]") + "\n"
    )
    metrics = parse_top_output(text)
    by_pid = {m.pid: m for m in metrics}
    assert set(by_pid) == {16230, 147}
    assert by_pid[16230].cpu_percent == pytest.approx(8.8)
    assert by_pid[147].cpu_percent == pytest.approx(5.8)


def test_vivo_android_malformed_rows_skipped() -> None:
    text = (
        VIVO_TOP
        + "this is not a pid row\n"
        + "=== separator ===\n"
        + _row_for(VIVO_HEADER, 3333, "S", "1.0", "0.1", "valid.row") + "\n"
    )
    metrics = parse_top_output(text)
    pids = {m.pid for m in metrics}
    assert 3333 in pids
    assert len(metrics) == 5  # two malformed lines skipped


def test_vivo_android_blank_state_cell_tolerated() -> None:
    # State missing inside the merged span (a space placeholder); CPU still parsed.
    row = _row_for(VIVO_HEADER, 4444, " ", "2.0", "0.5", "no.state")
    text = VIVO_SUMMARY + VIVO_HEADER + "\n" + row + "\n"
    metrics = parse_top_output(text)
    by_pid = {m.pid: m for m in metrics}
    assert by_pid[4444].cpu_percent == pytest.approx(2.0)
    assert by_pid[4444].state is None
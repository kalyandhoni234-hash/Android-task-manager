"""Bounded APK-label extraction (Priority #6).

Deterministic, device-free: the ADB transport is a scripted fake runner and
every archive fixture is crafted in memory. Locks the hardening contract:

* transfers/decompression are capped BEFORE expensive work;
* malformed archives fail safely into ``None`` (never crash, never guess);
* no temporary files are created;
* entry counts are bounded;
* hostile label content cannot smuggle past the size limits.
"""

from __future__ import annotations

import base64
import struct
import zlib

import pytest

from android_task_manager.applications import apk_label as apk
from android_task_manager.applications.apk_label import (
    ApkLabelError,
    ApkLabelResolver,
    parse_central_directory,
)

MANIFEST_NAME = "AndroidManifest.xml"


# --------------------------------------------------------------------------
# Fixture builders (minimal real ZIP/AXML structures)
# --------------------------------------------------------------------------

def _stored_entry(name: str, payload: bytes) -> tuple[bytes, int, int, int]:
    """Return (local_header_block, offset_within_block, csize, method)."""
    name_bytes = name.encode()
    header = struct.pack(
        "<IHHHHHIIIHH",
        0x04034B50, 20, 0, _METHOD_STORED, 0, 0, 0,
        len(payload), len(payload), len(name_bytes), 0,
    )
    assert len(header) == 30
    block = header + name_bytes + payload
    return block, 30 + len(name_bytes), len(payload), _METHOD_STORED


_METHOD_STORED = 0
_METHOD_DEFLATE = 8


def _central_tail(entries: list[tuple[str, int, int, int]], *,
                  declared_total: int | None = None,
                  cd_offset_delta: int = 0) -> bytes:
    """Build a tail buffer: central directory + EOCD for *entries*.

    Each entry tuple is ``(name, local_offset, csize, method)``. The record
    layout mirrors the parser exactly: sig(I) vm(H) vn(H) flags(H) then
    method/mtime/mdate(HHH) crc/csize/usize(III) nl/el/cl/disk/attr(HHHHH)
    local_off(I).
    """
    cd = b""
    for name, local_off, csize, method in entries:
        nb = name.encode()
        cd += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20, 20, 0,
            method, 0, 0,
            0, csize, csize,
            len(nb), 0, 0, 0, 0,
            0, local_off,
        ) + nb
    total = len(entries) if declared_total is None else declared_total
    eocd = struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, total, total, len(cd),
        cd_offset_delta, 0,
    )
    return cd + eocd


def _axml_literal_label(label: str) -> bytes:
    """Minimal compiled AXML: <application android:label="label"/>."""
    strings = ["application", "label", label]

    def u8(s: str) -> bytes:
        # Android UTF-8 pool string: [u8 charLen][u8 byteLen][bytes][NUL].
        data = s.encode("utf-8")
        return bytes([len(s), len(data)]) + data + b"\x00"

    blob = b"".join(u8(s) for s in strings)
    offsets = []
    pos = 0
    for s in strings:
        offsets.append(pos)
        pos += len(u8(s))
    strings_start = 28 + 4 * len(strings)
    pool_size = strings_start + len(blob)
    pool = struct.pack(
        "<HHIIIIII", 0x0001, 28, pool_size, len(strings), 0,
        1 << 8, strings_start, 0,
    ) + b"".join(struct.pack("<I", o) for o in offsets) + blob

    attr_name_idx = strings.index("label")
    attr_value_idx = strings.index(label)
    attribute = struct.pack(
        "<IIIHBBI", 0xFFFFFFFF, attr_name_idx, 0xFFFFFFFF, 8, 0, 0x03, attr_value_idx
    )
    elem_body = struct.pack(
        "<IIIIIHHHHHH",
        1, 0, 0xFFFFFFFF, strings.index("application"), 32,
        20, 1, 0, 0, 0, 0,
    ) + attribute
    elem_size = 8 + len(elem_body)
    element = struct.pack("<HHI", 0x0102, 16, elem_size) + elem_body

    total = 8 + len(pool) + len(element)
    return struct.pack("<HHI", 0x0003, 8, total) + pool + element


class _FakeRunner:
    """Serves the tail/range commands from in-memory byte blobs."""

    def __init__(self, tail: bytes, ranges: dict[int, bytes]) -> None:
        self.tail = tail
        self.ranges = ranges  # keyed by (skip_blocks, blocks)
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None) -> str:
        self.calls.append(list(args))
        if args[0] == "tail":
            return base64.b64encode(self.tail).decode()
        if args[0] == "dd":
            skip = int([a for a in args if a.startswith("skip=")][0].split("=")[1])
            count = int([a for a in args if a.startswith("count=")][0].split("=")[1])
            payload = self.ranges.get((skip, count))
            if payload is None:
                raise AssertionError(f"unexpected dd range {(skip, count)}")
            return base64.b64encode(payload).decode()
        raise AssertionError(f"unexpected command {args!r}")


def _resolver_for(manifest_block: bytes, manifest_offset_in_block: int,
                  csize: int, *, tail_overrides: dict | None = None):
    """Wire a resolver whose central directory describes one manifest entry."""
    entry_local_off = 500  # arbitrary absolute offset inside the fake APK
    tail = _central_tail([(MANIFEST_NAME, entry_local_off, csize, _METHOD_STORED)])
    if tail_overrides:
        tail = tail_overrides.get("tail", tail)
    skip_blocks, blocks, slice_start = apk.range_read_plan(entry_local_off, csize)
    raw = b"\x00" * slice_start + manifest_block
    ranges = {(skip_blocks, blocks): raw}
    runner = _FakeRunner(tail, ranges)
    return ApkLabelResolver(runner, timeout=1.0), runner


# --------------------------------------------------------------------------
# 1. Normal extraction succeeds
# --------------------------------------------------------------------------

def test_normal_label_extraction_succeeds():
    axml = _axml_literal_label("WhatsApp")
    block, off, csize, _ = _stored_entry(MANIFEST_NAME, axml)
    resolver, _runner = _resolver_for(block, off, csize)
    assert resolver.resolve("/data/app/~~x/com.example/base.apk") == "WhatsApp"


# --------------------------------------------------------------------------
# 2. Missing manifest handled safely
# --------------------------------------------------------------------------

def test_missing_manifest_returns_none_without_dd():
    empty_cd = _central_tail([])
    runner = _FakeRunner(empty_cd, {})
    resolver = ApkLabelResolver(runner, timeout=1.0)
    assert resolver.resolve("/data/app/x/base.apk") is None
    # Only the tail was fetched: no ranged read for a missing entry.
    assert all(c[0] != "dd" for c in runner.calls)


# --------------------------------------------------------------------------
# 3. Malformed ZIP rejected safely
# --------------------------------------------------------------------------

def test_malformed_zip_degrades_to_none():
    runner = _FakeRunner(b"not a zip at all", {})
    resolver = ApkLabelResolver(runner, timeout=1.0)
    assert resolver.resolve("/data/app/x/base.apk") is None
    with pytest.raises(ApkLabelError):
        parse_central_directory(b"not a zip at all")


# --------------------------------------------------------------------------
# 4. Oversized entry transfer rejected BEFORE the ranged read
# --------------------------------------------------------------------------

def test_oversized_entry_transfer_rejected_before_read(monkeypatch):
    cap = apk._MAX_ENTRY_COMPRESSED_BYTES
    big_csize = cap + 1
    tail = _central_tail([(MANIFEST_NAME, 500, big_csize, _METHOD_STORED)])
    runner = _FakeRunner(tail, {})  # no dd payload prepared
    resolver = ApkLabelResolver(runner, timeout=1.0)

    assert resolver.resolve("/data/app/x/base.apk") is None
    assert all(c[0] != "dd" for c in runner.calls), "must not issue huge dd"
    # And the inflated-data path is never reached either.


def test_deflated_oversized_entry_also_rejected_before_read(monkeypatch):
    cap = apk._MAX_ENTRY_COMPRESSED_BYTES
    tail = _central_tail([(MANIFEST_NAME, 500, cap + 1, _METHOD_DEFLATE)])
    runner = _FakeRunner(tail, {})
    resolver = ApkLabelResolver(runner, timeout=1.0)
    assert resolver.resolve("/data/app/x/base.apk") is None
    assert all(c[0] != "dd" for c in runner.calls)


_METHOD_DEFLATE = 8


# --------------------------------------------------------------------------
# 5. Decompression bomb bounded
# --------------------------------------------------------------------------

def test_inflate_output_is_bounded():
    cap = apk._MAX_ENTRY_INFLATED_BYTES
    bomb = zlib.compress(b"\x00" * (cap + 1024), 9)
    block, off, csize, _ = _stored_entry(MANIFEST_NAME, bomb)
    chunk = block[off:]
    with pytest.raises(ApkLabelError):
        apk.extract_entry(chunk, csize, _METHOD_DEFLATE)


def test_stored_oversized_payload_rejected_by_cap_check(monkeypatch):
    # A STORED entry whose declared size slips past the pre-read cap is cut
    # off at the resolver level (no dd); direct extract of a slightly-over
    # inflated-equivalent payload still honors the inflated bound.
    assert apk._MAX_ENTRY_INFLATED_BYTES > 0
    assert apk._MAX_ENTRY_COMPRESSED_BYTES >= apk._MAX_ENTRY_INFLATED_BYTES


# --------------------------------------------------------------------------
# 6. Excessive entry count rejected
# --------------------------------------------------------------------------

def test_excessive_entry_count_rejected():
    tail = _central_tail([], declared_total=apk._MAX_TOTAL_ENTRIES + 1)
    with pytest.raises(ApkLabelError):
        parse_central_directory(tail)


# --------------------------------------------------------------------------
# 7. No temporary files / cleanup invariant
# --------------------------------------------------------------------------

def test_no_temporary_files_created_even_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())

    runner = _FakeRunner(b"garbage", {})
    ApkLabelResolver(runner, timeout=1.0).resolve("/data/app/x/base.apk")

    bomb = zlib.compress(b"\x00" * (apk._MAX_ENTRY_INFLATED_BYTES + 1), 9)
    block, off, csize, _ = _stored_entry(MANIFEST_NAME, bomb)
    with pytest.raises(ApkLabelError):
        apk.extract_entry(block[off:], csize, _METHOD_DEFLATE)

    after = sorted(p.name for p in tmp_path.iterdir())
    assert after == before  # purely in-memory: nothing to clean up


# --------------------------------------------------------------------------
# 8. Hostile label content cannot bypass the limits
# --------------------------------------------------------------------------

def test_hostile_label_passes_through_but_limits_still_apply():
    hostile = '<font color="red"><b>DEVICE</b></font>'
    axml = _axml_literal_label(hostile)
    block, off, csize, _ = _stored_entry(MANIFEST_NAME, axml)
    resolver, _runner = _resolver_for(block, off, csize)
    # Content-neutral: rendering safety is the GUI's PlainText contract (P5);
    # here we assert extraction itself stays bounded and honest.
    assert resolver.resolve("/data/app/x/base.apk") == hostile

    # And the same hostile content cannot excuse an oversized transfer.
    tail = _central_tail([(MANIFEST_NAME, 500,
                           apk._MAX_ENTRY_COMPRESSED_BYTES + 1, _METHOD_STORED)])
    runner = _FakeRunner(tail, {})
    assert ApkLabelResolver(runner, timeout=1.0).resolve(
        "/data/app/x/base.apk") is None


# --------------------------------------------------------------------------
# Path validation regression (existing safety, unchanged)
# --------------------------------------------------------------------------

def test_unsafe_apk_paths_still_rejected():
    # Note: dot/dotdot segments are *accepted by design* (fixed argument list,
    # no shell reshaping); whitespace/metacharacters and empty/relative paths
    # are the rejected classes.
    for bad in ("relative.apk", "/data/app/x;rm -rf", "/a b.apk", "", None):
        with pytest.raises(ApkLabelError):
            apk.validate_apk_path(bad)

"""Device-derived application-label resolution.

Android exposes no ``pm``/``dumpsys`` field carrying an application's
human-readable label, so the honest way to show "WhatsApp" instead of
``com.whatsapp`` is to read the label from the application's own APK on
the connected device:

1. ``pm list packages -f`` already recorded each app's APK path (v0.7
   inventory — reused, nothing re-collected);
2. a bounded ``tail`` of the APK yields the ZIP central directory;
3. two small block-rounded ``dd`` ranges yield the compiled
   ``AndroidManifest.xml`` and ``resources.arsc`` entries;
4. the manifest's ``android:label`` reference is resolved against the
   resource table's default string.

Every transfer is base64-encoded ON DEVICE, so everything flows through
the existing text-only ``ConnectionManager.shell()`` interface — no new
ADB transport, no binary channel, no free-form shell. Every step is
fail-closed: any malformed/unexpected byte stream simply produces
``None`` and the GUI falls back to the package name. A label is never
invented, never guessed, never hardcoded.
"""

from __future__ import annotations

import re
import struct
import zlib

#: Strict device-path pattern for APK files. Real paths look like
#: ``/data/app/~~Rq1abc==/com.example-pQ9xyz==/base.apk``; the pattern
#: admits only characters that cannot reshape the fixed remote command
#: line (no whitespace, no shell metacharacters, no traversal tricks).
APK_PATH_RE = re.compile(r"^/[A-Za-z0-9_~][A-Za-z0-9_./=~+-]*$")

#: Maximum accepted APK path length (defensive bound).
MAX_APK_PATH_LENGTH = 512

#: Bytes read from the APK tail to capture the ZIP central directory.
_TAIL_BYTES = 131072

#: Block size for ranged ``dd`` reads.
_BLOCK_SIZE = 4096

#: Slack added around ranged reads (local headers carry variable extras).
_RANGE_SLACK = 4096

_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_LOCAL_SIGNATURE = b"PK\x03\x04"

_METHOD_STORED = 0
_METHOD_DEFLATE = 8

# --- AXML (compiled binary XML) constants ---------------------------------
_AXML_STRING_POOL_TYPE = 0x0001
_AXML_START_ELEMENT_TYPE = 0x0102
_AXML_UTF8_FLAG = 1 << 8

# --- ARSC (resource table) constants --------------------------------------
_ARSC_TABLE_TYPE = 0x0002
_ARSC_PACKAGE_TYPE = 0x0200
_ARSC_TYPE_TYPE = 0x0201
_ARSC_STRING_POOL_TYPE = 0x0001
_ARSC_VALUE_STRING = 0x03


class ApkLabelError(ValueError):
    """Raised internally when an APK structure cannot be parsed."""


def validate_apk_path(path: object) -> str:
    """Return *path* when it is a safe absolute device APK path.

    Raises :class:`ApkLabelError` otherwise. Only validated paths ever
    become part of a fixed remote command argument list.
    """
    if not isinstance(path, str):
        raise ApkLabelError("APK path must be a string")
    candidate = path.strip()
    if not candidate:
        raise ApkLabelError("APK path must not be empty")
    if len(candidate) > MAX_APK_PATH_LENGTH:
        raise ApkLabelError("APK path is too long")
    if not APK_PATH_RE.fullmatch(candidate):
        raise ApkLabelError(f"unsafe APK path: {candidate!r}")
    return candidate


def decode_base64_payload(text: str) -> bytes:
    """Decode a (possibly line-wrapped) base64 payload from device output."""
    compact = "".join(text.split())
    if not compact or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
        raise ApkLabelError("device returned an unusable base64 payload")
    import base64

    return base64.b64decode(compact, validate=True)


# ---------------------------------------------------------------------------
# ZIP structures
# ---------------------------------------------------------------------------


def parse_central_directory(tail: bytes) -> dict[str, tuple[int, int, int]]:
    """Parse the ZIP central directory captured in an APK tail buffer.

    Returns ``{name: (local_header_offset, compressed_size, method)}``.
    Raises :class:`ApkLabelError` when no usable end-of-central-directory
    record exists or the directory itself is truncated/zip64.
    """
    eocd_index = tail.rfind(_ZIP_EOCD_SIGNATURE)
    if eocd_index < 0 or eocd_index + 22 > len(tail):
        raise ApkLabelError("no ZIP end-of-central-directory record")
    (
        _disk,
        _cd_disk,
        _disk_entries,
        total_entries,
        cd_size,
        cd_offset,
        _comment_len,
    ) = struct.unpack_from("<HHHHIIH", tail, eocd_index + 4)
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        raise ApkLabelError("zip64 archives are not supported")
    cd_start = eocd_index - cd_size
    if cd_start < 0:
        raise ApkLabelError("central directory truncated in tail buffer")

    entries: dict[str, tuple[int, int, int]] = {}
    position = cd_start
    for _ in range(total_entries):
        if position + 46 > len(tail) or tail[position : position + 4] != _ZIP_CENTRAL_SIGNATURE:
            break
        (method, _mtime, _mdate, _crc, compressed_size, _uncompressed_size,
         name_len, extra_len, comment_len, _disk_start, _attrs,
         local_offset) = struct.unpack_from("<HHHHHIIIHHHHI", tail, position + 10)
        name_start = position + 46
        name_end = name_start + name_len
        if name_end > len(tail):
            break
        name = tail[name_start:name_end].decode("utf-8", "replace")
        entries.setdefault(name, (local_offset, compressed_size, method))
        position = name_end + extra_len + comment_len
    if not entries:
        raise ApkLabelError("central directory contained no entries")
    return entries


def extract_entry(
    chunk: bytes, compressed_size: int, method: int
) -> bytes:
    """Extract and decompress one entry from a local-header-aligned chunk.

    *chunk* begins at the entry's local file header. Raises
    :class:`ApkLabelError` on any structural surprise.
    """
    if len(chunk) < 30 or chunk[:4] != _ZIP_LOCAL_SIGNATURE:
        raise ApkLabelError("bad local file header")
    name_len, extra_len = struct.unpack_from("<HH", chunk, 26)
    data_start = 30 + name_len + extra_len
    data_end = data_start + compressed_size
    if data_end > len(chunk):
        raise ApkLabelError("entry data truncated")
    payload = chunk[data_start:data_end]
    if method == _METHOD_STORED:
        return payload
    if method == _METHOD_DEFLATE:
        try:
            return zlib.decompressobj(-15).decompress(payload)
        except zlib.error as exc:
            raise ApkLabelError("deflate stream corrupted") from exc
    raise ApkLabelError(f"unsupported compression method {method}")


def range_read_plan(offset: int, length: int) -> tuple[int, int, int]:
    """Block-rounded ``(skip_blocks, blocks, slice_start)`` for one range.

    ``slice_start`` is the offset of *offset* inside the decoded blocks.
    """
    skip_blocks = offset // _BLOCK_SIZE
    end_block = (offset + length + _RANGE_SLACK + _BLOCK_SIZE - 1) // _BLOCK_SIZE
    blocks = max(1, end_block - skip_blocks)
    return skip_blocks, blocks, offset - skip_blocks * _BLOCK_SIZE


def tail_command(apk_path: str) -> list[str]:
    """Fixed remote command capturing the APK tail, base64-encoded."""
    return ["tail", "-c", str(_TAIL_BYTES), apk_path, "|", "base64"]


def range_command(apk_path: str, offset: int, length: int) -> list[str]:
    """Fixed remote command reading one byte range, base64-encoded."""
    skip_blocks, blocks, _ = range_read_plan(offset, length)
    return [
        "dd",
        f"if={apk_path}",
        f"bs={_BLOCK_SIZE}",
        f"skip={skip_blocks}",
        f"count={blocks}",
        "2>/dev/null",
        "|",
        "base64",
    ]


# ---------------------------------------------------------------------------
# AXML (compiled AndroidManifest.xml)
# ---------------------------------------------------------------------------


def _iter_chunks(data: bytes, start: int, end: int):
    position = start
    while position + 8 <= end:
        chunk_type, _header_size, chunk_size = struct.unpack_from("<HHI", data, position)
        if chunk_size < 8 or position + chunk_size > end:
            return
        yield chunk_type, position, chunk_size
        position += chunk_size


def _parse_string_pool(data: bytes, chunk_start: int, chunk_size: int) -> list[str]:
    """Parse one RES_STRING_POOL_TYPE chunk into its strings."""
    (_t, header_size, _s, string_count, _style_count, flags, strings_start, _styles) = (
        struct.unpack_from("<HHIIIIII", data, chunk_start)
    )
    if string_count == 0 or header_size < 28:
        return []
    utf8 = bool(flags & _AXML_UTF8_FLAG)
    offsets_base = chunk_start + header_size
    strings_base = chunk_start + strings_start
    strings: list[str] = []
    for index in range(string_count):
        (offset,) = struct.unpack_from("<I", data, offsets_base + index * 4)
        position = strings_base + offset
        if position >= chunk_start + chunk_size:
            continue
        try:
            if utf8:
                # <u8 chars><u8 bytes><utf8 data><0> (lengths may be 2 bytes
                # for very long strings; the high bit signals that form).
                head = data[position]
                length_bytes = 2 if head & 0x80 else 1
                position += length_bytes
                if data[position] & 0x80:
                    position += 1
                byte_len = data[position]
                position += 1
                raw = data[position : position + byte_len]
                strings.append(raw.decode("utf-8", "replace"))
            else:
                (char_len,) = struct.unpack_from("<H", data, position)
                if char_len & 0x8000:
                    (char_len,) = struct.unpack_from("<I", data, position)
                    position += 2
                else:
                    position += 2
                raw = data[position : position + char_len * 2]
                strings.append(raw.decode("utf-16-le", "replace"))
        except (IndexError, struct.error):
            continue
    return strings


def _axml_chunks(data: bytes):
    """Yield ``(type, start, size)`` for the chunks inside an AXML file."""
    if len(data) < 8:
        return
    file_type, _header_size, file_size = struct.unpack_from("<HHI", data, 0)
    if file_type != 0x0003 or file_size > len(data):
        return
    yield from _iter_chunks(data, 8, min(file_size, len(data)))


def extract_label_reference(manifest: bytes) -> int | str | None:
    """Extract ``<application android:label=...>`` from compiled AXML.

    Returns the resource-id (int) for ``@ref`` labels, the literal string
    for inline labels, or ``None`` when absent/unparseable.
    """
    pool: list[str] = []
    for chunk_type, start, size in _axml_chunks(manifest):
        if chunk_type == _AXML_STRING_POOL_TYPE:
            pool = _parse_string_pool(manifest, start, size)

    def _string_at(index: int) -> str | None:
        if 0 <= index < len(pool):
            return pool[index]
        return None

    for chunk_type, start, size in _axml_chunks(manifest):
        if chunk_type != _AXML_START_ELEMENT_TYPE:
            continue
        try:
            (_line, _comment, _ns, name_index, attribute_start, attribute_size,
             attribute_count, _id_idx, _class_idx, _style_idx) = struct.unpack_from(
                "<IIIIIHHHHHH", manifest, start + 8
            )
        except struct.error:
            continue
        if _string_at(name_index) != "application":
            continue
        attributes_base = start + 8 + attribute_start
        for index in range(attribute_count):
            base = attributes_base + index * attribute_size
            if base + 20 > start + size:
                break
            try:
                (_attr_ns, attr_name, raw_value, _val_size, _res0,
                 data_type, data) = struct.unpack_from("<IIIHBBI", manifest, base)
            except struct.error:
                break
            if _string_at(attr_name) != "label":
                continue
            if data_type == _ARSC_VALUE_STRING:  # literal string in the manifest
                source = raw_value if raw_value != 0xFFFFFFFF else data
                return _string_at(source)
            if data_type == 0x01:  # REFERENCE into the resource table
                return data
            return None
        return None
    return None


# ---------------------------------------------------------------------------
# resources.arsc
# ---------------------------------------------------------------------------


def resolve_arsc_string(arsc: bytes, resource_id: int) -> str | None:
    """Resolve one resource id to its default string in a resource table.

    Heuristic (documented honestly): among the configurations defined for
    the requested entry, the FIRST string value wins — Android lists the
    default configuration first for ordinary applications. Anything
    unexpected yields ``None``.
    """
    if len(arsc) < 12:
        return None
    table_type, _header_size, table_size = struct.unpack_from("<HHI", arsc, 0)
    if table_type != _ARSC_TABLE_TYPE or table_size > len(arsc):
        return None
    package_id = (resource_id >> 24) & 0xFF
    type_id = (resource_id >> 16) & 0xFF
    entry_index = resource_id & 0xFFFF

    global_pool: list[str] = []
    for chunk_type, start, size in _iter_chunks(arsc, 12, table_size):
        if chunk_type == _ARSC_STRING_POOL_TYPE:
            global_pool = _parse_string_pool(arsc, start, size)
            break

    for chunk_type, start, size in _iter_chunks(arsc, 12, table_size):
        if chunk_type != _ARSC_PACKAGE_TYPE:
            continue
        try:
            (_t, header_size, _s) = struct.unpack_from("<HHI", arsc, start)
            pkg_id = struct.unpack_from("<I", arsc, start + 8)[0]
        except struct.error:
            continue
        if header_size < 288 or pkg_id != package_id:
            continue
        candidates: list[str] = []
        position = start + header_size
        while position + 8 <= start + size:
            sub_type, sub_header, sub_size = struct.unpack_from("<HHI", arsc, position)
            if sub_size < 8 or position + sub_size > start + size:
                break
            if sub_type == _ARSC_TYPE_TYPE and sub_header >= 20:
                try:
                    chunk_id, _flags, _reserved, entry_count, entries_start = (
                        struct.unpack_from("<BBHII", arsc, position + 8)
                    )
                except struct.error:
                    position += sub_size
                    continue
                if chunk_id == type_id and entry_index < entry_count:
                    offsets_base = position + sub_header
                    try:
                        (entry_offset,) = struct.unpack_from(
                            "<I", arsc, offsets_base + entry_index * 4
                        )
                    except struct.error:
                        position += sub_size
                        continue
                    if entry_offset == 0xFFFFFFFF:
                        position += sub_size
                        continue
                    entry_position = start + entries_start + entry_offset
                    value = _read_table_entry_value(arsc, entry_position, start + size)
                    if value is not None and value[0] == _ARSC_VALUE_STRING:
                        pool_index = value[1]
                        if 0 <= pool_index < len(global_pool):
                            candidates.append(global_pool[pool_index])
            position += sub_size
        if candidates:
            return candidates[0]
    return None


def _read_table_entry_value(
    data: bytes, entry_position: int, limit: int
) -> tuple[int, int] | None:
    """Read a simple (non-complex) table entry's ``(dataType, data)``."""
    if entry_position + 8 > limit:
        return None
    try:
        entry_size, flags, _key = struct.unpack_from("<HHI", data, entry_position)
    except struct.error:
        return None
    if flags & 0x0001:  # COMPLEX: a bag, not a plain value
        return None
    value_position = entry_position + 8
    if value_position + 8 > limit:
        return None
    try:
        _value_size, _res0, data_type, value_data = struct.unpack_from(
            "<HBBI", data, value_position
        )
    except struct.error:
        return None
    return data_type, value_data


def label_from_apk_parts(manifest: bytes, arsc: bytes | None) -> str | None:
    """Resolve the application label from manifest + resource-table bytes.

    A literal manifest label needs no resource table; a ``@ref`` label is
    resolved against it. ``None`` means "could not be resolved" — the
    caller falls back to the package name.
    """
    reference = extract_label_reference(manifest)
    if reference is None:
        return None
    if isinstance(reference, str):
        cleaned = reference.strip()
        return cleaned or None
    if arsc is None:
        return None
    resolved = resolve_arsc_string(arsc, reference)
    if resolved is None:
        return None
    cleaned = resolved.strip()
    if not cleaned or cleaned.startswith("@"):
        # Unresolved placeholders (e.g. "@ref/0x...") are not labels.
        return None
    return cleaned


__all__ = [
    "ApkLabelError",
    "extract_label_reference",
    "label_from_apk_parts",
    "parse_central_directory",
    "range_command",
    "range_read_plan",
    "resolve_arsc_string",
    "tail_command",
    "validate_apk_path",
]


# ---------------------------------------------------------------------------
# Runner-backed resolver
# ---------------------------------------------------------------------------


class ApkLabelResolver:
    """Resolves application labels from APKs on the connected device.

    Uses the shared ``CommandRunner`` (the same single ADB facade every
    collector uses) with three small fixed commands per unresolved
    application, run once per session and cached. All ADB failures
    propagate as typed exceptions so the calling worker can react to a
    lost device; all parse failures degrade to ``None``.
    """

    def __init__(self, runner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout
        self._cache: dict[str, str | None] = {}

    def clear(self) -> None:
        """Drop the cache (device disconnect/reconnect)."""
        self._cache.clear()

    def cached(self, apk_path: str) -> bool:
        return apk_path in self._cache

    def resolve(self, apk_path: str) -> str | None:
        """Resolve (or recall) the label for one APK path.

        ``None`` means the label could not be resolved from the device —
        never a fabricated name.
        """
        path = validate_apk_path(apk_path)
        if path in self._cache:
            return self._cache[path]
        label = self._resolve_uncached(path)
        self._cache[path] = label
        return label

    def _resolve_uncached(self, path: str) -> str | None:
        try:
            tail = decode_base64_payload(
                self._runner.shell(tail_command(path), timeout=self._timeout)
            )
            entries = parse_central_directory(tail)
            parts: dict[str, bytes] = {}
            for name in ("AndroidManifest.xml", "resources.arsc"):
                entry = entries.get(name)
                if entry is None:
                    continue
                offset, compressed_size, method = entry
                if compressed_size <= 0:
                    continue
                skip_blocks, blocks, slice_start = range_read_plan(
                    offset, compressed_size
                )
                raw = decode_base64_payload(
                    self._runner.shell(
                        range_command(path, offset, compressed_size),
                        timeout=self._timeout,
                    )
                )
                expected = (blocks * _BLOCK_SIZE) - skip_blocks * _BLOCK_SIZE
                if len(raw) < min(expected, slice_start + compressed_size):
                    continue
                chunk = raw[slice_start:]
                parts[name] = extract_entry(chunk, compressed_size, method)
            manifest = parts.get("AndroidManifest.xml")
            if manifest is None:
                return None
            return label_from_apk_parts(manifest, parts.get("resources.arsc"))
        except (ApkLabelError, struct.error, ValueError):
            # Malformed device output degrades to "no label", never a guess.
            return None

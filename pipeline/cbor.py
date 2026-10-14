"""A small CBOR decoder (RFC 8949), enough for the values WoW's C_EncodingUtil.SerializeCBOR
writes: integers, byte and text strings, arrays, maps, floats, true/false/nil.

Lua strings come out of the client as CBOR byte strings; they are decoded as UTF-8 here.
Arrays become Python lists and maps become dicts, keys as written (Lua integer keys stay ints).
"""

from __future__ import annotations

import struct


class CBORError(ValueError):
    """The bytes are not CBOR this decoder understands."""


def loads(data: bytes):
    value, end = _item(data, 0)
    if end != len(data):
        raise CBORError(f"{len(data) - end} trailing bytes after the CBOR value")
    return value


def _length(data: bytes, pos: int, info: int) -> tuple[int, int]:
    if info < 24:
        return info, pos
    sizes = {24: 1, 25: 2, 26: 4, 27: 8}
    if info not in sizes:
        raise CBORError(f"unsupported length encoding {info} at byte {pos - 1}")
    size = sizes[info]
    if pos + size > len(data):
        raise CBORError("truncated length")
    return int.from_bytes(data[pos:pos + size], "big"), pos + size


def _item(data: bytes, pos: int):
    if pos >= len(data):
        raise CBORError("truncated value")
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if major == 7:
        if info == 20:
            return False, pos
        if info == 21:
            return True, pos
        if info in (22, 23):
            return None, pos
        formats = {25: (">e", 2), 26: (">f", 4), 27: (">d", 8)}
        if info in formats:
            fmt, size = formats[info]
            return struct.unpack(fmt, data[pos:pos + size])[0], pos + size
        raise CBORError(f"unsupported simple value {info}")
    if info == 31:
        raise CBORError("indefinite-length items are not used by the client")
    n, pos = _length(data, pos, info)
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        raw = data[pos:pos + n]
        if len(raw) != n:
            raise CBORError("truncated string")
        return raw.decode("utf-8"), pos + n
    if major == 4:
        items = []
        for _ in range(n):
            value, pos = _item(data, pos)
            items.append(value)
        return items, pos
    if major == 5:
        mapping = {}
        for _ in range(n):
            key, pos = _item(data, pos)
            value, pos = _item(data, pos)
            mapping[key] = value
        return mapping, pos
    # major 6: a tag. Its meaning does not matter for these values; keep the tagged item.
    return _item(data, pos)

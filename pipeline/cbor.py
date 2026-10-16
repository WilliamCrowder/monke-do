"""A small CBOR decoder (RFC 8949), enough for the values WoW's C_EncodingUtil.SerializeCBOR
writes: integers, byte and text strings, arrays, maps, floats, true/false/nil.

Lua strings come out of the client as CBOR byte strings; they are decoded as UTF-8 here.
Arrays become Python lists and maps become dicts, keys as written (Lua integer keys stay ints).

The input is downloaded data, so the decoder is strict and cheap to refuse with: every failure
is a CBORError (never RecursionError, struct.error, TypeError or UnicodeDecodeError), nesting is
capped, a declared length is checked against the bytes left before anything is built, and
anything the client never writes (tags, indefinite lengths, one-byte simple values) is refused.
Checked against QuestieDB v1.0.6: no tags, no text strings, nesting at most 5 deep.
"""

from __future__ import annotations

import struct

MAX_DEPTH = 32  # arrays and maps inside each other; QuestieDB's values nest 5 deep

_SIZES = {24: 1, 25: 2, 26: 4, 27: 8}
_FLOATS = {25: (">e", 2), 26: (">f", 4), 27: (">d", 8)}


class CBORError(ValueError):
    """The bytes are not CBOR this decoder understands."""


def loads(data: bytes):
    data = bytes(data)
    value, end = _item(data, 0, 0)
    if end != len(data):
        raise CBORError(f"{len(data) - end} trailing bytes after the CBOR value")
    return value


def _length(data: bytes, pos: int, info: int) -> tuple[int, int]:
    if info < 24:
        return info, pos
    if info == 31:
        raise CBORError(f"indefinite-length item at byte {pos - 1}: the client never writes one")
    if info not in _SIZES:
        raise CBORError(f"reserved length encoding {info} at byte {pos - 1}")
    size = _SIZES[info]
    if pos + size > len(data):
        raise CBORError(f"truncated length at byte {pos - 1}")
    return int.from_bytes(data[pos:pos + size], "big"), pos + size


def _simple(data: bytes, pos: int, info: int):
    if info == 20:
        return False, pos
    if info == 21:
        return True, pos
    if info in (22, 23):  # null and undefined: both are Lua's nil
        return None, pos
    if info in _FLOATS:
        fmt, size = _FLOATS[info]
        if pos + size > len(data):
            raise CBORError(f"truncated float at byte {pos - 1}")
        return struct.unpack(fmt, data[pos:pos + size])[0], pos + size
    if info == 31:
        raise CBORError(f"break byte at {pos - 1} outside an indefinite-length item")
    raise CBORError(f"unsupported simple value {info} at byte {pos - 1}")


def _item(data: bytes, pos: int, depth: int):
    if depth > MAX_DEPTH:
        raise CBORError(f"values nested more than {MAX_DEPTH} deep at byte {pos}")
    if pos >= len(data):
        raise CBORError("truncated value")
    start = pos
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if major == 7:
        return _simple(data, pos, info)
    n, pos = _length(data, pos, info)
    left = len(data) - pos
    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        if n > left:
            raise CBORError(f"truncated string at byte {start}: it declares {n} bytes, {left} are left")
        try:
            return data[pos:pos + n].decode("utf-8"), pos + n
        except UnicodeDecodeError as exc:
            raise CBORError(f"string at byte {start} is not valid UTF-8 ({exc.reason})") from None
    if major == 4:
        if n > left:  # every item takes at least one byte
            raise CBORError(f"truncated array at byte {start}: it declares {n} items, {left} bytes are left")
        items = []
        for _ in range(n):
            value, pos = _item(data, pos, depth + 1)
            items.append(value)
        return items, pos
    if major == 5:
        if n > left // 2:  # every entry takes at least two bytes
            raise CBORError(f"truncated map at byte {start}: it declares {n} entries, {left} bytes are left")
        mapping = {}
        for _ in range(n):
            key_at = pos
            key, pos = _item(data, pos, depth + 1)
            if isinstance(key, (list, dict)):
                raise CBORError(f"map key at byte {key_at} is an array or a map; only numbers, "
                                "strings, booleans and nil are keys")
            value, pos = _item(data, pos, depth + 1)
            mapping[key] = value
        return mapping, pos
    # major 6: SerializeCBOR writes no tags, so a tag means this is not its output.
    raise CBORError(f"tag {n} at byte {start} is not used by the client")

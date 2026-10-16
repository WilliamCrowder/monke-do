"""pipeline.cbor on hostile input: every failure is a CBORError, found early and cheaply.

The release is downloaded data. A decoder that answers garbage with RecursionError,
struct.error or a million-element list would turn one bad value into a crash or a stall.
"""

from __future__ import annotations

import math
import random
import struct

import pytest

from pipeline import cbor

LIMIT = 32  # cbor.MAX_DEPTH; QuestieDB's values nest 5 deep


def deep_array(depth: int) -> bytes:
    return b"\x81" * depth + b"\x00"  # [[[...[0]...]]]


WELL_FORMED = [
    ("0", b"\x00", 0),
    ("23", b"\x17", 23),
    ("24 in one byte", b"\x18\x18", 24),
    ("2^64-1", b"\x1b" + b"\xff" * 8, 2 ** 64 - 1),
    ("-2^64", b"\x3b" + b"\xff" * 8, -(2 ** 64)),
    ("-1", b"\x20", -1),
    ("byte string", b"\x43abc", "abc"),  # Lua strings arrive as byte strings
    ("text string", b"\x63abc", "abc"),  # a text string reads the same
    ("empty array", b"\x80", []),
    ("empty map", b"\xa0", {}),
    ("false", b"\xf4", False),
    ("true", b"\xf5", True),
    ("null", b"\xf6", None),
    ("undefined", b"\xf7", None),  # there is no other nil
    ("half 1.0", b"\xf9\x3c\x00", 1.0),
    ("half -2.0", b"\xf9\xc0\x00", -2.0),
    ("largest half", b"\xf9\x7b\xff", 65504.0),
    ("smallest subnormal half", b"\xf9\x00\x01", 2.0 ** -24),
    ("half infinity", b"\xf9\x7c\x00", math.inf),
    ("single 1.5", b"\xfa\x3f\xc0\x00\x00", 1.5),
    ("double -0.1", b"\xfb" + struct.pack(">d", -0.1), -0.1),
    ("a quest-shaped map", b"\xa2\x01\x41x\x41p\x82\x01\xf6", {1: "x", "p": [1, None]}),
]


@pytest.mark.parametrize(("data", "value"), [pytest.param(d, v, id=label) for label, d, v in WELL_FORMED])
def test_well_formed_values(data: bytes, value) -> None:
    assert cbor.loads(data) == value


def test_half_precision_nan() -> None:
    assert math.isnan(cbor.loads(b"\xf9\x7e\x00"))


def test_nesting_up_to_the_limit_is_fine() -> None:
    assert cbor.MAX_DEPTH == LIMIT
    value = cbor.loads(deep_array(LIMIT))
    for _ in range(LIMIT):
        value = value[0]
    assert value == 0


HOSTILE = [
    ("empty input", b"", "truncated"),
    ("uint missing its length byte", b"\x18", "truncated"),
    ("uint16 cut short", b"\x19\x01", "truncated"),
    ("string cut short", b"\x43ab", "truncated"),
    ("array cut short", b"\x82\x00", "truncated"),
    ("map without its value", b"\xa1\x00", "truncated"),
    ("half float cut short", b"\xf9\x3c", "truncated"),
    ("single float cut short", b"\xfa\x00\x00", "truncated"),
    ("double cut short", b"\xfb\x00", "truncated"),
    ("trailing bytes", b"\x00\x00", "trailing"),
    ("indefinite array", b"\x9f\x00\xff", "indefinite"),
    ("indefinite map", b"\xbf\xff", "indefinite"),
    ("indefinite byte string", b"\x5f\xff", "indefinite"),
    ("indefinite text string", b"\x7f\xff", "indefinite"),
    ("a lone break byte", b"\xff", "break"),
    ("reserved length encoding", b"\x1c", "length"),
    ("one-byte simple value", b"\xf8\x20", "simple"),
    ("invalid UTF-8", b"\x42\xff\xfe", "UTF-8"),
    ("array as a map key", b"\xa1\x80\x00", "key"),
    ("map as a map key", b"\xa1\xa0\x00", "key"),
    ("tag 0 (date string)", b"\xc0\x60", "tag"),
    ("tag 2 (bignum)", b"\xc2\x42\x01\x00", "tag"),
    ("self-describe tag", b"\xd9\xd9\xf7\x00", "tag"),
    ("arrays nested one too deep", deep_array(LIMIT + 1), "deep"),
    ("arrays nested 100,000 deep", deep_array(100_000), "deep"),
    ("maps nested 5,000 deep", b"\xa1\x00" * 5000 + b"\x00", "deep"),
    ("tags nested 100,000 deep", b"\xc0" * 100_000 + b"\x00", "tag"),
]


@pytest.mark.parametrize(("data", "message"), [pytest.param(d, m, id=label) for label, d, m in HOSTILE])
def test_hostile_input_is_a_cbor_error(data: bytes, message: str) -> None:
    with pytest.raises(cbor.CBORError, match=message):
        cbor.loads(data)


TOO_LONG = [
    ("array of 2^32-1", b"\x9a\xff\xff\xff\xff" + b"\x00" * 100_000, "4294967295 items"),
    ("array of 2^64-1", b"\x9b" + b"\xff" * 8 + b"\x00", "18446744073709551615 items"),
    ("map of 2^32-1", b"\xba\xff\xff\xff\xff" + b"\x00" * 1000, "4294967295 entries"),
    ("string of 2^64-1", b"\x5b" + b"\xff" * 8 + b"ab", "18446744073709551615 bytes"),
]


@pytest.mark.parametrize(("data", "count"), [pytest.param(d, c, id=label) for label, d, c in TOO_LONG])
def test_a_declared_length_longer_than_the_input_fails_before_any_work(data: bytes, count: str) -> None:
    """Every item takes at least one byte, so a count the input cannot hold is refused at
    once, instead of after building a list as long as the input."""
    with pytest.raises(cbor.CBORError, match=count):
        cbor.loads(data)


def _valid_samples() -> list[bytes]:
    return [
        b"\xa3\x01\x51Red Silk Bandanas\x04\x0e\x41p\x1a\x02\x00\x0c\x86",
        b"\x81\x82\x83\x19\x0a\x01\xf6\x00\x19\x0a\x0e",
        b"\x82\xf9\x3c\x00\xfb" + struct.pack(">d", 1.25),
        b"\xa1\x03\x81\x83\x19\x03\x93\xf6\x00",
    ]


def test_no_input_raises_anything_but_cbor_error() -> None:
    """All one- and two-byte inputs, every truncation of some real-shaped values, and a fixed
    sample of random and mutated bytes: each either decodes or raises CBORError."""
    inputs: list[bytes] = [bytes([a]) for a in range(256)]
    inputs += [bytes([a, b]) for a in range(256) for b in range(256)]
    for sample in _valid_samples():
        assert cbor.loads(sample) is not None
        inputs += [sample[:i] for i in range(len(sample))]
    rng = random.Random(8949)
    for _ in range(20_000):
        inputs.append(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 16))))
    for sample in _valid_samples():
        for _ in range(2_000):
            mutated = bytearray(sample)
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
            inputs.append(bytes(mutated))
    for data in inputs:
        try:
            cbor.loads(data)
        except cbor.CBORError:
            pass

"""Parse Lua table literals without running any Lua.

Questie ships its database as Lua source: a key enum (`QuestieDB.questKeys = {...}`)
and a long string holding `return { [214] = {...}, ... }`. We only ever need the
data, and running downloaded code to get it would be a needless risk, so this is a
small recursive-descent parser for the literal subset of Lua: tables, strings,
numbers, nil, true and false.

How values map to Python:

- nil -> None, true/false -> bool, numbers -> int or float, strings -> str
- every table -> dict. Positional entries get the integer keys 1..n exactly as
  Lua would number them, and nil entries are left out. So for
  `{ "a", nil, {1} }` the result is `{1: "a", 3: {1: 1}}` and `row.get(8)` is an
  exact lookup by Questie key number.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

type LuaValue = None | bool | int | float | str | dict

# Whitespace and comments. The block-comment branch has to come before the
# line-comment branch, otherwise `--[[ ... ]]` would be read as a line comment.
_SKIP = re.compile(r"(?:\s+|--\[(=*)\[.*?\]\1\]|--[^\n]*)*", re.S)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?\s*(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_DOUBLE_QUOTED = re.compile(r'"((?:[^"\\\n]|\\.)*)"', re.S)
_SINGLE_QUOTED = re.compile(r"'((?:[^'\\\n]|\\.)*)'", re.S)
_LONG_OPEN = re.compile(r"\[(=*)\[")
_ESCAPE = re.compile(r"\\(\d{1,3}|\r\n|.)", re.S)
# Everything that matters when skipping over a value without building it.
_STRUCTURE = re.compile(r"[{}\"']|--|\[=*\[")

_SIMPLE_ESCAPES = {
    "n": b"\n", "t": b"\t", "r": b"\r", "a": b"\a", "b": b"\b", "f": b"\f", "v": b"\v",
    "\\": b"\\", '"': b'"', "'": b"'", "\n": b"\n", "\r\n": b"\n",
}
_LITERALS = {"nil": None, "true": True, "false": False}


class LuaParseError(ValueError):
    """The text is not a Lua literal this parser understands."""


def _unescape(raw: str) -> str:
    r"""Resolve backslash escapes. `\ddd` is a byte, so decoding happens at the end:
    Lua files spell UTF-8 characters as several `\ddd` escapes in a row."""
    if "\\" not in raw:
        return raw
    out = bytearray()
    pos = 0
    for match in _ESCAPE.finditer(raw):
        out += raw[pos:match.start()].encode("utf-8")
        code = match.group(1)
        if code[0].isdigit():
            value = int(code)
            if value > 255:
                raise LuaParseError(f"escape \\{code} is larger than a byte")
            out.append(value)
        else:
            # Lua 5.1 turns an unknown escape such as \q into the bare character.
            out += _SIMPLE_ESCAPES.get(code, code.encode("utf-8"))
        pos = match.end()
    out += raw[pos:].encode("utf-8")
    return out.decode("utf-8", errors="replace")


def _to_number(token: str) -> int | float:
    token = token.replace(" ", "").replace("\t", "")
    sign = -1 if token.startswith("-") else 1
    digits = token.lstrip("-")
    if digits[:2] in ("0x", "0X"):
        return sign * int(digits, 16)
    if any(c in digits for c in ".eE"):
        return sign * float(digits)
    return sign * int(digits)


class _Parser:
    """A cursor over the source text. One instance parses one value or one file."""

    def __init__(self, text: str, pos: int = 0) -> None:
        self.text = text
        self.pos = pos

    # -- helpers -----------------------------------------------------------

    def error(self, message: str) -> LuaParseError:
        line = self.text.count("\n", 0, self.pos) + 1
        near = self.text[self.pos:self.pos + 30].replace("\n", "\\n")
        return LuaParseError(f"{message} at line {line} (offset {self.pos}), near {near!r}")

    def skip_space(self) -> None:
        self.pos = _SKIP.match(self.text, self.pos).end()

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, char: str) -> None:
        self.skip_space()
        if self.peek() != char:
            raise self.error(f"expected {char!r}")
        self.pos += 1

    def skip_return(self) -> None:
        """Questie's long strings are chunks: `return { ... }`."""
        self.skip_space()
        if self.text.startswith("return", self.pos) and not _NAME.match(self.text, self.pos + 6):
            self.pos += 6
        self.skip_space()

    # -- values ------------------------------------------------------------

    def value(self, limit: int | None = None) -> LuaValue:
        self.skip_space()
        char = self.peek()
        if char == "":
            raise self.error("unexpected end of input")
        if char == "{":
            return self.table(limit)
        if char == '"' or char == "'":
            return self.string()
        if char.isdigit() or char in "-.":
            return self.number()
        if char == "[":
            return self.long_string()
        match = _NAME.match(self.text, self.pos)
        if match and match.group() in _LITERALS:
            self.pos = match.end()
            return _LITERALS[match.group()]
        raise self.error("expected a literal value (expressions and variables are not supported)")

    def string(self) -> str:
        pattern = _DOUBLE_QUOTED if self.peek() == '"' else _SINGLE_QUOTED
        match = pattern.match(self.text, self.pos)
        if not match:
            raise self.error("unterminated string")
        self.pos = match.end()
        return _unescape(match.group(1))

    def number(self) -> int | float:
        match = _NUMBER.match(self.text, self.pos)
        if not match:
            raise self.error("malformed number")
        self.pos = match.end()
        return _to_number(match.group())

    def long_string(self) -> str:
        match = _LONG_OPEN.match(self.text, self.pos)
        if not match:
            raise self.error("expected a value")
        closer = "]" + match.group(1) + "]"
        end = self.text.find(closer, match.end())
        if end < 0:
            raise self.error("unterminated long string")
        self.pos = end + len(closer)
        body = self.text[match.end():end]
        # Lua drops one newline directly after the opening bracket.
        if body.startswith("\r\n"):
            return body[2:]
        return body[1:] if body.startswith("\n") else body

    # -- tables ------------------------------------------------------------

    def table(self, limit: int | None = None) -> dict:
        """Parse `{...}`. With `limit`, stop building after positional field `limit`
        and skip to the closing brace; the big NPC and item rows are mostly spawn
        coordinates we never read."""
        self.pos += 1  # the opening brace
        result: dict = {}
        index = 0
        while True:
            entry = self.entry()
            if entry is None:
                return result
            key, value = entry
            if key is None:
                index += 1
                key = index
            if value is not None:
                result[key] = value
            if limit is not None and index >= limit:
                self.skip_to_close()
                return result

    def entry(self, limit: int | None = None) -> tuple[object, LuaValue] | None:
        """Read one table field plus its separator. Returns (key, value), where key is
        None for a positional field, or None when the closing brace was reached.
        `limit` applies to the field's value when that value is a table."""
        self.skip_space()
        char = self.peek()
        if char == "}":
            self.pos += 1
            return None
        if char == "":
            raise self.error("unterminated table")
        key: object = None
        if char == "[" and not _LONG_OPEN.match(self.text, self.pos):
            self.pos += 1
            key = self.value()
            if isinstance(key, float) and key.is_integer():
                key = int(key)  # Lua treats [1.0] and [1] as the same key
            if key is None or isinstance(key, dict):
                raise self.error("table key must be a number, string or boolean")
            self.expect("]")
            self.expect("=")
        elif (name := _NAME.match(self.text, self.pos)) is not None:
            key = self.name_key(name)
        value = self.value(limit)
        self.skip_space()
        char = self.peek()
        if char == "," or char == ";":
            self.pos += 1
        elif char != "}":
            raise self.error("expected ',' or '}'")
        return key, value

    def name_key(self, name: re.Match[str]) -> str | None:
        """`name = value` has a key; a bare `nil`/`true`/`false` is a positional value."""
        after = _SKIP.match(self.text, name.end()).end()
        if self.text[after:after + 1] == "=" and self.text[after:after + 2] != "==":
            self.pos = after + 1
            return name.group()
        return None

    def skip_to_close(self) -> None:
        """From inside a table, move just past its closing brace without building anything.
        Strings and comments are honoured so a brace inside them is not counted."""
        depth = 1
        while depth:
            match = _STRUCTURE.search(self.text, self.pos)
            if not match:
                raise self.error("unterminated table")
            token = match.group()
            self.pos = match.start()
            if token == "{":
                depth += 1
                self.pos = match.end()
            elif token == "}":
                depth -= 1
                self.pos = match.end()
            elif token == "--":
                self.skip_space()
            elif token[0] == "[":
                self.long_string()
            else:
                self.string()


def parse_at(text: str, pos: int = 0) -> tuple[LuaValue, int]:
    """Parse one value starting at `pos`. Returns the value and the offset just after it."""
    parser = _Parser(text, pos)
    value = parser.value()
    return value, parser.pos


def parse(text: str) -> LuaValue:
    """Parse a whole literal, with an optional leading `return`. Trailing junk is an error."""
    parser = _Parser(text)
    parser.skip_return()
    value = parser.value()
    parser.skip_space()
    if parser.pos != len(text):
        raise parser.error("unexpected text after the value")
    return value


def iter_rows(text: str, *, max_index: int | None = None) -> Iterator[tuple[object, LuaValue]]:
    """Yield `(key, value)` for each entry of the outermost table, one at a time.

    This is how the Questie data files are read: `return { [214] = {...}, ... }` with
    thousands of rows. Rows are found by real parsing, not by line structure, so a row
    may span lines or share one. `max_index` is passed to each row table: only its
    positional fields 1..max_index are built (enough to read `name` from a 2 MB file
    in a fraction of a second). nil-valued entries are not yielded.
    """
    parser = _Parser(text)
    parser.skip_return()
    if parser.peek() != "{":
        raise parser.error("expected a table")
    parser.pos += 1
    index = 0
    while True:
        entry = parser.entry(max_index)
        if entry is None:
            return
        key, value = entry
        if key is None:
            index += 1
            key = index
        if value is not None:
            yield key, value


_HIDING = re.compile(r"--|[\"']|\[=*\[")


def _find_assignment(text: str, name: str, opener: str) -> int:
    """Offset of the value in the first real `name = <opener>...`. An assignment that
    sits inside a comment or a string does not count, however much it looks like one."""
    pattern = re.compile(re.escape(name) + r"\s*=\s*(?=" + opener + ")")
    parser = _Parser(text)
    while True:
        match = pattern.search(text, parser.pos)
        if not match:
            raise LuaParseError(f"no assignment to {name!r} found")
        while parser.pos <= match.start():
            hiding = _HIDING.search(text, parser.pos, match.start())
            if not hiding:
                return match.end()
            parser.pos = hiding.start()
            token = hiding.group()
            if token == "--":
                parser.skip_space()
            elif token[0] == "[":
                parser.long_string()
            else:
                parser.string()


def extract_long_string(text: str, name: str) -> str:
    """Return the body of `name = [[ ... ]]` (any `[=[` level). `name` may be dotted,
    such as `QuestieDB.questData`. The body is returned as written, not parsed."""
    return _Parser(text, _find_assignment(text, name, r"\[=*\[")).long_string()


def parse_key_enum(text: str, name: str) -> dict[str, int]:
    """Parse `name = { ['key'] = 1, ... }` into `{"key": 1}`.

    Questie documents sub-keys as commented-out lines inside the enum
    (`--['creatureStart'] = 1`). Comments are skipped by the parser, so those never
    show up here and cannot shadow a real key.
    """
    table, _ = parse_at(text, _find_assignment(text, name, r"\{"))
    enum: dict[str, int] = {}
    for key, value in table.items():
        if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int):
            raise LuaParseError(f"{name}: expected string keys and integer values, got {key!r} = {value!r}")
        enum[key] = value
    return enum

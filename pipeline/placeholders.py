"""Bring quest-text placeholders to one spelling (contract section 4, "Placeholders").

The game client writes `$N`, `$C`, `$R`, `$B` and `$Ghis:her;` in any letter case,
and web sites render the same tokens as `<name>`, `<class>`, `<race>` and
`<his/her>`. Texts from different sources are compared to find quests Forever
rewrote, so every source has to land on the same canonical form first:

    $n name   $c class   $r race   $b line break   $gmale:female; gender choice

Anything that is not a placeholder is left exactly as it was.
"""

from __future__ import annotations

import re

# `$G his : her ;` in any case, with the optional spaces some data sources add.
_GENDER_TOKEN = re.compile(r"\$[gG]\s*([^:;$]*?)\s*:\s*([^:;$]*?)\s*;")
_SIMPLE_TOKEN = re.compile(r"\$([NCRB])")

_WEB_NAMED = {"name": "$n", "class": "$c", "race": "$r"}
_WEB_NAMED_PATTERN = re.compile(r"<(name|class|race)>", re.IGNORECASE)
# <his/her>, <brother/sister>, <Lord/Lady>. Only plain words are accepted on both
# sides so that stray HTML such as </p> or <a href="x/y"> can never match.
_WEB_GENDER_PATTERN = re.compile(r"<([A-Za-z][A-Za-z' -]*)/([A-Za-z][A-Za-z' -]*)>")


def canonical_tokens(text: str) -> str:
    """Lower-case the client's own tokens: `$N` -> `$n`, `$G a:b;` -> `$ga:b;`.

    This is all a source needs when its text comes from game data (Questie), where an
    angle bracket is part of the text and not a rendered placeholder.
    """
    text = _GENDER_TOKEN.sub(lambda m: f"$g{m.group(1)}:{m.group(2)};", text)
    return _SIMPLE_TOKEN.sub(lambda m: "$" + m.group(1).lower(), text)


def from_web(text: str) -> str:
    """Map a web page's rendering back to client tokens: `<name>` -> `$n`,
    and the generic rule `<x/y>` -> `$gx:y;`."""
    text = _WEB_NAMED_PATTERN.sub(lambda m: _WEB_NAMED[m.group(1).lower()], text)
    return _WEB_GENDER_PATTERN.sub(lambda m: f"$g{m.group(1).strip()}:{m.group(2).strip()};", text)


def normalise(text: str | None) -> str | None:
    """The full normalisation for text of unknown origin. None and blank stay None,
    because the database stores missing text as NULL and never as ''."""
    if text is None or not text.strip():
        return None
    return canonical_tokens(from_web(text))

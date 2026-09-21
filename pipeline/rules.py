"""Rule-based task bullets: the Python mirror of the addon's `Rules.lua` templates.

The exporter uses these when a quest has no usable LLM summary (rejected, errored,
or no prose to summarise), so the shipped database never depends on the LLM being
right. Target names are used exactly as given: pluralising "Kobold Vermin" or
"Red Silk Bandana" correctly needs a dictionary we do not have, and "Bonk 8 Kobold
Vermin." is the house style anyway.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

MONKE = "monke"
PLAIN = "plain"
VOICES = (MONKE, PLAIN)

# type -> (monke verb, plain verb) for the "verb [n] name." family.
_VERBS = {
    "monster": ("Bonk", "Kill"),
    "item": ("Grab", "Collect"),
    "object": ("Poke", "Use"),
}
# Types whose only useful content is a free-text description.
_TEXT_TYPES = ("event", "spell", "log", "player", "progressbar")

# In-game reputation standings, used to pull "Honored" out of an objective text.
STANDINGS = (
    "Hated", "Hostile", "Unfriendly", "Neutral", "Friendly", "Honored", "Revered", "Exalted",
)
_STANDING_RE = re.compile(r"\b(" + "|".join(STANDINGS) + r")\b", re.IGNORECASE)

_GENERIC_TASK = {MONKE: "Do the quest thing.", PLAIN: "Complete the objective."}
_TURNIN_GENERIC = {MONKE: "Go back. Get shiny.", PLAIN: "Turn in the quest."}
_TURNIN_NPC = {MONKE: "Go back to {npc}.", PLAIN: "Return to {npc}."}

# Quest tags that mean "do not try this alone" even without a suggested size.
_TAG_LINES = {
    "dungeon": {MONKE: "Dungeon time. Bring friends.", PLAIN: "Dungeon quest: bring a full group."},
    "raid": {MONKE: "Raid time. Bring many many friends.", PLAIN: "Raid quest: bring a raid group."},
    "elite": {MONKE: "Big danger. Bring friends.", PLAIN: "Elite quest: a group is recommended."},
    "group": {MONKE: "Big danger. Bring friends.", PLAIN: "Group quest: a group is recommended."},
}


def field(row: Any, key: str, default: Any = None) -> Any:
    """Read `key` from a dict, an sqlite3.Row or a dataclass such as db.Objective.

    Objectives reach this module from three places (the DB, tests, QuestContext), and
    forcing callers to convert first would just move this function into each of them.
    """
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        value = row[key]  # sqlite3.Row
    except (TypeError, IndexError, KeyError):
        value = getattr(row, key, default)
    return default if value is None else value


def _check_voice(voice: str) -> None:
    if voice not in VOICES:
        raise ValueError(f"unknown voice {voice!r}; expected one of {VOICES}")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _sentence(text: str) -> str:
    """End `text` with exactly one terminator, so 'Find Bob.' never becomes 'Find Bob..'."""
    text = text.rstrip()
    if text.endswith(("!", "?")):
        return text
    return text.rstrip(". ") + "."


def _amount(row: Any) -> int:
    try:
        return max(1, int(field(row, "amount", 1)))
    except (TypeError, ValueError):
        return 1


def _text_task(text: str, voice: str) -> str:
    if not text:
        return _GENERIC_TASK[voice]
    return _sentence(f"Do the thing: {text}" if voice == MONKE else text)


def _reputation_task(row: Any, voice: str) -> str:
    faction = _clean(field(row, "target_name"))
    text = _clean(field(row, "text"))
    if not faction:
        return _text_task(text, voice)
    if voice == MONKE:
        return f"Make {faction} like ape."
    standing = _STANDING_RE.search(text)
    if standing:
        return f"Reach {standing.group(1).capitalize()} with {faction}."
    return f"Earn reputation with {faction}."


def task_for(objective_row: Any, voice: str) -> str:
    """One bullet for one structured objective, in the given voice."""
    _check_voice(voice)
    kind = field(objective_row, "type", "")
    name = _clean(field(objective_row, "target_name"))
    text = _clean(field(objective_row, "text"))
    if kind == "reputation":
        return _reputation_task(objective_row, voice)
    if kind in _VERBS and name:
        verb = _VERBS[kind][VOICES.index(voice)]
        n = _amount(objective_row)
        return f"{verb} {n} {name}." if n > 1 else f"{verb} {name}."
    # Free-text types, unknown types, and verb types whose target has no name.
    return _text_task(text or name, voice)


def turnin_line(turnin_npc: str | None, voice: str) -> str:
    """The closing bullet. Generic when no source names the turn-in NPC."""
    _check_voice(voice)
    npc = _clean(turnin_npc)
    return _TURNIN_NPC[voice].format(npc=npc) if npc else _TURNIN_GENERIC[voice]


def tasks_for(objectives: Iterable[Any], turnin_npc: str | None, voice: str) -> list[str]:
    """Objective bullets in objective order, then the turn-in line last.

    The first len(objectives) entries map 1:1 to the objectives, which is what the
    exported `n` field promises the addon.
    """
    _check_voice(voice)
    return [task_for(o, voice) for o in objectives] + [turnin_line(turnin_npc, voice)]


def group_line(group_size: int | None, tag: str | None, voice: str) -> str | None:
    """'Bring friends' line, or None when the quest is fine solo.

    Mirrors contract rendering rule 5: shown for a suggested size above 1, or for an
    Elite, Group, Dungeon or Raid tag.
    """
    _check_voice(voice)
    if group_size is not None and group_size > 1:
        if voice == MONKE:
            # The size counts the player, so a group of 3 is 2 friends. Same as Voice.lua.
            friends = group_size - 1
            return "Bring a friend. Big danger." if friends == 1 else f"Bring {friends} friends. Big danger."
        return f"Suggested group: {group_size} players."
    lines = _TAG_LINES.get(_clean(tag).lower())
    return lines[voice] if lines else None

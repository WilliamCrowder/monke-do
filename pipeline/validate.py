"""Validator for one LLM summary (docs/DATA_CONTRACT.md section 6).

Every error string is written so it can be pasted back to the model verbatim as
feedback, and so a human reading pipeline/review.py output understands it without
opening this file. An empty list means the summary may ship.

The checks are deliberately mechanical. They cannot tell whether lore is *good*,
only whether it breaks a promise the addon makes to players: right numbers, short
text, no invented geography, PG language, a turn-in line, and nothing the game
client would render as garbage.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from pipeline import db
from pipeline.rules import field as _get

SUMMARY_KEYS = ("lore_monke", "lore_plain", "tasks", "group_line")
MAX_LORE_CHARS = 160  # exclusive: lore must be *under* this many characters
MAX_LORE_SENTENCES = 2

# --------------------------------------------------------------------------- context


@dataclass
class QuestContext:
    """Everything the summarizer and the validator may know about one quest."""

    id: int
    title: str | None = None
    detail: str | None = None
    objectives_text: str | None = None
    progress: str | None = None
    complete: str | None = None
    turnin_npc: str | None = None
    objectives: list[Any] = field(default_factory=list)  # dicts, sqlite3.Row or db.Objective
    group_size: int | None = None
    tag: str | None = None

    def names(self) -> list[str]:
        """Proper nouns the game itself supplies: objective targets and the turn-in NPC."""
        found = [_get(o, "target_name") for o in self.objectives] + [self.turnin_npc]
        return [n for n in found if n]

    def source_text(self) -> str:
        """All prose and names joined. The only vocabulary a summary may draw places from."""
        parts = [self.title, self.detail, self.objectives_text, self.progress, self.complete]
        parts += [_get(o, "text") for o in self.objectives]
        parts += self.names()
        return "\n".join(p for p in parts if p)

    def has_prose(self) -> bool:
        """False when there is nothing to summarise (title-only quests)."""
        return bool(self.detail or self.objectives_text)


def load_context(conn: sqlite3.Connection, quest: sqlite3.Row | int) -> QuestContext:
    """Build the context for a `quests` row (or quest id) from the pipeline database."""
    if isinstance(quest, int):
        row = conn.execute("SELECT * FROM quests WHERE id = ?", (quest,)).fetchone()
        if row is None:
            raise KeyError(f"quest {quest} is not in the quests table")
        quest = row
    meta = conn.execute(
        "SELECT group_size, tag FROM quest_meta WHERE quest_id = ?", (quest["id"],)
    ).fetchone()
    return QuestContext(
        id=quest["id"],
        title=quest["title"],
        detail=quest["detail"],
        objectives_text=quest["objectives_text"],
        progress=quest["progress"],
        complete=quest["complete"],
        turnin_npc=quest["turnin_npc"],
        objectives=[dict(o) for o in db.get_objectives(conn, quest["id"])],
        group_size=meta["group_size"] if meta is not None else None,
        tag=meta["tag"] if meta is not None else None,
    )


# --------------------------------------------------------------------------- word lists

# Words the narrator may capitalise mid-sentence without them being a place or a name.
CAPITALISED_ALLOWLIST = frozenset({
    "monke", "ape", "i", "i'm", "i'll", "i've", "i'd", "ooga", "booga", "ook", "eek",
    "bonk", "grab", "poke", "smash", "shiny", "banana", "ok",
})

# Keep it PG. One constant so a human can extend it; checked on word boundaries, case
# insensitively, including simple inflections (-s, -es, -ed, -ing).
PROFANITY_BLOCKLIST = (
    # swearing
    "fuck", "fucker", "fuckin", "motherfucker", "shit", "shitty", "bullshit", "crap", "crappy",
    "piss", "pissed", "pisser", "damn", "dammit", "goddamn", "hell", "bugger", "bollocks",
    "wank", "wanker", "arse", "arsehole", "ass", "asshole", "jackass", "dumbass", "butt",
    "butthole", "bastard", "bitch", "slut", "whore", "skank", "douche", "douchebag", "prick",
    "dick", "dickhead", "cock", "cocksucker", "pussy", "cunt", "twat", "tits", "boob", "boobs",
    "penis", "vagina", "dildo", "jizz", "cum", "porn", "horny", "sexy",
    # slurs and insults aimed at the player's mind or body (the joke is never on the player)
    "retard", "retarded", "spaz", "spastic", "cripple", "moron", "idiot", "imbecile",
    "nigger", "nigga", "negro", "faggot", "fag", "dyke", "tranny", "shemale", "kike", "spic",
    "chink", "gook", "wetback", "paki", "coon", "gypsy", "gyp", "raghead", "towelhead",
    "homo", "lesbo", "nazi",
)

# Always passes, even if a later blocklist edit or the inflection rule would catch it:
# the narrator's own rough-and-tumble words, and innocent words that look like an
# inflected blocklist entry ("spices" is not "spic" + "es").
PROFANITY_ALLOWLIST = frozenset({
    "bonk", "bonks", "bonked", "bonking", "smash", "smashes", "smashed", "smashing",
    "whack", "thump", "stomp", "stinky", "smelly", "dumb", "silly", "poke", "pokes",
    "butte", "buttes", "butted", "butting", "cocked", "cocking", "pricked", "pricking",
    "spices", "spiced", "spicing",
})

_PROFANITY_RE = re.compile(
    r"^(?:" + "|".join(sorted(map(re.escape, PROFANITY_BLOCKLIST), key=len, reverse=True))
    + r")(?:s|es|ed|ing)?$",
    re.IGNORECASE,
)

# north, south-east, northwestern, eastward(s), southerly, westbound ...
_DIRECTION_RE = re.compile(
    r"\b(?:north|south|east|west)(?:[- ]?(?:east|west))?(?:ern|erly|wards?|bound)?\b",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F][A-Za-z\u00C0-\u024F'\u2019]*")
_PLACEHOLDER_RE = re.compile(r"\$[A-Za-z]")
_PROGRESS_RE = re.compile(r"\(?\b\d+\s*/\s*\d+\b\)?")
_BULLET_LEAD_RE = re.compile(r"^\s*(?:[-*\u2022\u00B7\u2013\u2014\u25AA\u25E6\u2023\u25CF\u25CB>]|\d+[.)]\s)")
_BULLET_GLYPHS = "\u2022\u25AA\u25E6\u2023\u25CF\u25CB"

# Abbreviations whose full stop does not end a sentence.
_ABBREVIATIONS = (
    "mr", "mrs", "ms", "dr", "st", "lt", "sgt", "cpl", "capt", "cmdr", "col", "gen", "prof",
    "jr", "sr", "vs", "etc", "no", "e.g", "i.e",
)
_ABBREVIATION_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\.", re.IGNORECASE
)
_SENTENCE_END_RE = re.compile(r"[.!?]+[\"'\u2019\u201D)\]]*(?:\s+|$)")
# A word starts a sentence when what precedes it (ignoring quotes/brackets) ends like this.
_SENTENCE_START_CHARS = ".!?:\u2026"
_OPENERS = " \t\"'\u2018\u201C(["


# --------------------------------------------------------------------------- helpers


def count_sentences(text: str) -> int:
    """Count sentences without being fooled by '...', 'Mr.', 'J. R.' or '1.5'.

    Robust rather than perfect: the goal is telling one or two short sentences from a
    paragraph, so anything ambiguous is resolved towards *fewer* sentences.
    """
    text = text.replace("\u2026", " ")
    text = re.sub(r"\.{2,}", " ", text)                   # ellipsis is a pause, not an end
    text = _ABBREVIATION_RE.sub(r"\1", text)              # Mr. -> Mr
    text = re.sub(r"\b([A-Za-z])\.(?=\s|$)", r"\1", text)  # initials: J. R. -> J R
    text = re.sub(r"(?<=\d)\.(?=\d)", "", text)           # decimals: 1.5 -> 15
    parts = _SENTENCE_END_RE.split(text)
    return sum(1 for p in parts if re.search(r"\w", p))


def _words(text: str) -> list[re.Match[str]]:
    return list(_WORD_RE.finditer(text))


def _normalise(word: str) -> str:
    word = word.lower().replace("\u2019", "'")
    return word[:-2] if word.endswith("'s") else word.rstrip("'")


def _vocabulary(text: str) -> set[str]:
    """Lower-cased words of `text`, with hyphenated words also split into their parts."""
    return {_normalise(m.group()) for m in _words(text.replace("-", " "))}


def _known(word: str, vocabulary: set[str]) -> bool:
    """True when `word` is in the source, allowing for a plural the model added or dropped."""
    w = _normalise(word)
    candidates = {w, w + "s", w + "es"}
    if w.endswith("es"):
        candidates.add(w[:-2])
    if w.endswith("s"):
        candidates.add(w[:-1])
    return bool(candidates & vocabulary)


def _direction(match: re.Match[str]) -> str:
    """'North-West' and 'north west' are the same word as 'northwest'."""
    return re.sub(r"[- ]", "", match.group().lower())


def _starts_sentence(text: str, start: int) -> bool:
    before = text[:start].rstrip(_OPENERS)
    return not before or before[-1] in _SENTENCE_START_CHARS


def _fields(summary: dict) -> list[tuple[str, str]]:
    """(label, text) for every string the player could see, labels 1-based like the contract."""
    out = [("lore_monke", summary["lore_monke"]), ("lore_plain", summary["lore_plain"])]
    out += [(f"tasks[{i}]", t) for i, t in enumerate(summary["tasks"], start=1)]
    if summary["group_line"]:
        out.append(("group_line", summary["group_line"]))
    return out


def _mask_names(text: str, names: list[str]) -> str:
    """Blank out game-supplied names so an NPC called 'Dirty Dick' is not our profanity."""
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return text


# --------------------------------------------------------------------------- checks


def _check_shape(summary: Any) -> list[str]:
    if not isinstance(summary, dict):
        return ["The output must be one JSON object with the keys lore_monke, lore_plain, "
                "tasks and group_line."]
    errors = [f"Unknown key {k!r}: only lore_monke, lore_plain, tasks and group_line are allowed."
              for k in summary if k not in SUMMARY_KEYS]
    errors += [f"Missing key {k!r}." for k in SUMMARY_KEYS if k not in summary]
    for key in ("lore_monke", "lore_plain"):
        if key in summary and (not isinstance(summary[key], str) or not summary[key].strip()):
            errors.append(f"{key} must be a non-empty string.")
    if "tasks" in summary:
        tasks = summary["tasks"]
        if not isinstance(tasks, list) or not tasks:
            errors.append("tasks must be a non-empty list of strings.")
        elif any(not isinstance(t, str) or not t.strip() for t in tasks):
            errors.append("Every entry of tasks must be a non-empty string.")
    group = summary.get("group_line")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        errors.append("group_line must be a non-empty string or null.")
    if not errors:
        errors += [f"{label} must be a single line without line breaks."
                   for label, text in _fields(summary) if "\n" in text or "\r" in text]
    return errors


def _check_counts(summary: dict, ctx: QuestContext) -> list[str]:
    tasks = summary["tasks"]
    k = len(ctx.objectives)
    needed = k + (1 if ctx.turnin_npc else 0)
    if len(tasks) < needed:
        extra = " plus the turn-in line" if ctx.turnin_npc else ""
        return [f"tasks has {len(tasks)} entries but needs at least {needed}: one per structured "
                f"objective ({k}), in order{extra}."]
    errors = []
    for i, objective in enumerate(ctx.objectives, start=1):
        amount = _get(objective, "amount", 1)
        if amount <= 1 or _get(objective, "amount_source", "default") == "default":
            continue
        if not re.search(rf"(?<!\d){amount}(?!\d)", tasks[i - 1]):
            name = _get(objective, "target_name") or _get(objective, "text") or "objective"
            errors.append(f"tasks[{i}] must contain the number {amount} as digits, because "
                          f"objective {i} is {name} x{amount}. It was: {tasks[i - 1]!r}")
    return errors


def _check_lore(summary: dict) -> list[str]:
    errors = []
    for key in ("lore_monke", "lore_plain"):
        text = summary[key]
        if len(text) >= MAX_LORE_CHARS:
            errors.append(f"{key} is {len(text)} characters; it must be under {MAX_LORE_CHARS}.")
        sentences = count_sentences(text)
        if not 1 <= sentences <= MAX_LORE_SENTENCES:
            errors.append(f"{key} has {sentences} sentences; it must have 1 or "
                          f"{MAX_LORE_SENTENCES}.")
    return errors


def _check_invention(summary: dict, ctx: QuestContext) -> list[str]:
    source = ctx.source_text()
    vocabulary = _vocabulary(source)
    source_directions = {_direction(m) for m in _DIRECTION_RE.finditer(source)}
    errors = []
    for label, text in _fields(summary):
        for m in _DIRECTION_RE.finditer(text):
            if _direction(m) not in source_directions:
                errors.append(f"{label} uses the direction {m.group()!r}, which is not in the "
                              "quest text. Do not give directions the quest text does not give.")
        invented = []
        for m in _words(text):
            word = m.group()
            if not word[0].isupper() or _starts_sentence(text, m.start()):
                continue
            if _normalise(word) in CAPITALISED_ALLOWLIST or _DIRECTION_RE.fullmatch(word):
                continue
            if not _known(word, vocabulary):
                invented.append(word)
        if invented:
            errors.append(f"{label} contains capitalised word(s) that are not in the quest text: "
                          f"{', '.join(dict.fromkeys(invented))}. Do not invent places or names, "
                          "and do not use capitals for emphasis.")
    return errors


def _check_profanity(summary: dict, ctx: QuestContext) -> list[str]:
    errors = []
    for label, text in _fields(summary):
        bad = [m.group() for m in _words(_mask_names(text, ctx.names()))
               if _normalise(m.group()) not in PROFANITY_ALLOWLIST
               and _PROFANITY_RE.match(_normalise(m.group()))]
        if bad:
            errors.append(f"{label} contains language that is not PG: "
                          f"{', '.join(dict.fromkeys(bad))}. Rephrase without it.")
    return errors


def _check_turnin(summary: dict, ctx: QuestContext) -> list[str]:
    npc = ctx.turnin_npc
    if npc and npc.lower() not in summary["tasks"][-1].lower():
        return [f"The last entry of tasks must be the turn-in line and name the turn-in NPC "
                f"{npc!r}. It was: {summary['tasks'][-1]!r}"]
    return []


def _check_markup(summary: dict) -> list[str]:
    errors = []
    for label, text in _fields(summary):
        if _PLACEHOLDER_RE.search(text):
            errors.append(f"{label} contains a Blizzard placeholder such as $n, $c, $r, $g or $b. "
                          "Address the player as 'you' and drop the placeholder.")
        if "|" in text:
            errors.append(f"{label} contains a '|' character or UI escape code (|c, |r, |T, |H, "
                          "|n). Plain text only.")
    return errors


def _check_task_format(summary: dict) -> list[str]:
    errors = []
    for i, task in enumerate(summary["tasks"], start=1):
        if _PROGRESS_RE.search(task):
            errors.append(f"tasks[{i}] contains a progress count like 3/15. The addon adds live "
                          "progress itself; write only the total.")
        if _BULLET_LEAD_RE.match(task) or any(g in task for g in _BULLET_GLYPHS):
            errors.append(f"tasks[{i}] starts with a bullet, dash or list number. Write the bare "
                          "sentence; the addon draws the bullets.")
    return errors


def validate(summary: dict, ctx: QuestContext) -> list[str]:
    """Return every rule the summary breaks, as feedback-ready sentences. [] means valid."""
    errors = _check_shape(summary)
    if errors:
        return errors  # the remaining checks assume the shape
    return (
        _check_counts(summary, ctx)
        + _check_lore(summary)
        + _check_invention(summary, ctx)
        + _check_profanity(summary, ctx)
        + _check_turnin(summary, ctx)
        + _check_markup(summary)
        + _check_task_format(summary)
    )

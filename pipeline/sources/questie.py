"""Questie's Classic quest database as a source (contract section 5).

What this source has, verified against the real files on 2026-09-21: quest title,
the short objectives sentence, who takes the quest in, structured objective
targets, quest level, required level and quest flags. What it does NOT have: the
long description, progress text, completion text, or objective amounts. So
`detail`, `progress` and `complete` always stay None here, and amounts are read
out of the objectives sentence ("bring her 10 Red Silk Bandanas") when possible.

Exactly four files are pulled from github.com/Questie/QuestieDB, once, into
`raw_dir/questie/`. The repository is never cloned. The files are Lua source and
are parsed by `pipeline.luatable`, never executed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline import db, luatable
from pipeline.placeholders import canonical_tokens

SOURCE = "questie"
PRIORITY = 2
NEEDS_NETWORK = True
OPTIONS: tuple[str, ...] = ()  # extra keyword options load() accepts (see sources.load_all)

KNOWN_IDS_BUILD = "questie-classic"
BASE_URL = "https://raw.githubusercontent.com/Questie/QuestieDB/master/data/Classic/"
USER_AGENT = "MonkeDoPipeline/0.1"


@dataclass(frozen=True)
class DataFile:
    """One Questie DB file: where its key enum and its data long-string live."""

    filename: str
    keys_name: str
    data_name: str


QUEST_DB = DataFile("classicQuestDB.lua", "QuestieDB.questKeys", "QuestieDB.questData")
NPC_DB = DataFile("classicNpcDB.lua", "QuestieDB.npcKeys", "QuestieDB.npcData")
ITEM_DB = DataFile("classicItemDB.lua", "QuestieDB.itemKeys", "QuestieDB.itemData")
OBJECT_DB = DataFile("classicObjectDB.lua", "QuestieDB.objectKeys", "QuestieDB.objectData")
ALL_FILES = (QUEST_DB, NPC_DB, ITEM_DB, OBJECT_DB)

# Positions inside the `finishedBy` and `objectives` fields. Questie documents these
# only as commented-out lines in the key enum, so they cannot be read from the file.
FINISHED_BY_NPCS, FINISHED_BY_OBJECTS = 1, 2
OBJ_CREATURE, OBJ_OBJECT, OBJ_ITEM, OBJ_REPUTATION, OBJ_KILL_CREDIT, OBJ_SPELL = 1, 2, 3, 4, 5, 6


# --------------------------------------------------------------------------
# Download and cache
# --------------------------------------------------------------------------

@dataclass
class Download:
    """Reply to a conditional GET. `not_modified` means the cached copy is current."""

    content: bytes = b""
    etag: str | None = None
    not_modified: bool = False


Fetch = Callable[[str, str | None], Download]  # (url, etag of the cached copy) -> Download


def http_fetch(url: str, etag: str | None) -> Download:
    """The real network fetch. Tests pass their own function instead."""
    import httpx  # imported here so offline runs and tests never need it

    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    reply = httpx.get(url, headers=headers, follow_redirects=True, timeout=120)
    if reply.status_code == 304:
        return Download(etag=etag, not_modified=True)
    reply.raise_for_status()
    return Download(content=reply.content, etag=reply.headers.get("ETag"))


def _read_manifest(cache_dir: Path) -> dict:
    path = cache_dir / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_cache(raw_dir: Path, *, offline: bool, fetch: Fetch, notes: list[str]) -> Path:
    """Make sure the four files are in `raw_dir/questie/` and return that directory.

    Offline never touches the network and fails loudly when a file is missing. Online
    sends the stored ETag, so an unchanged 2 MB file costs one small request.
    """
    cache_dir = Path(raw_dir) / "questie"
    if offline:
        missing = [f.filename for f in ALL_FILES if not (cache_dir / f.filename).exists()]
        if missing:
            raise FileNotFoundError(
                f"Questie cache is incomplete in {cache_dir}: missing {', '.join(missing)}. "
                "Run the questie source once without offline mode to download them."
            )
        return cache_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(cache_dir)
    for data_file in ALL_FILES:
        path = cache_dir / data_file.filename
        known = manifest.get(data_file.filename, {}) if path.exists() else {}
        try:
            download = fetch(BASE_URL + data_file.filename, known.get("etag"))
        except Exception as error:  # noqa: BLE001 - any network failure: fall back to the cache
            if not path.exists():
                raise
            notes.append(f"{data_file.filename}: download failed ({error}); using the cached copy")
            continue
        if download.not_modified:
            continue
        path.write_bytes(download.content)
        manifest[data_file.filename] = {
            "url": BASE_URL + data_file.filename,
            "etag": download.etag,
            "sha256": hashlib.sha256(download.content).hexdigest(),
            "bytes": len(download.content),
            "fetched_at": db.utcnow(),
        }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return cache_dir


# --------------------------------------------------------------------------
# Reading the Lua files
# --------------------------------------------------------------------------

@dataclass
class Names:
    """ID -> name for the three kinds of thing a quest can point at."""

    npc: dict[int, str]
    item: dict[int, str]
    object: dict[int, str]


def load_names(path: Path, data_file: DataFile) -> dict[int, str]:
    """Read only the `name` field of every row. The key index comes from the file's own enum."""
    text = path.read_text(encoding="utf-8")
    name_index = luatable.parse_key_enum(text, data_file.keys_name)["name"]
    body = luatable.extract_long_string(text, data_file.data_name)
    names: dict[int, str] = {}
    for entity_id, row in luatable.iter_rows(body, max_index=name_index):
        name = row.get(name_index) if isinstance(row, dict) else None
        if isinstance(entity_id, int) and isinstance(name, str):
            names[entity_id] = name
    return names


def _values(table: object) -> list:
    """A parsed Lua list in order. Tolerates nil gaps and a missing (None) table."""
    if not isinstance(table, dict):
        return []
    return [table[k] for k in sorted(k for k in table if isinstance(k, int))]


# --------------------------------------------------------------------------
# Amounts from the objectives sentence
# --------------------------------------------------------------------------

_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_NUMBER_WORD = (
    r"(?:" + "|".join(_TENS) + r")(?:-(?:" + "|".join(k for k, v in _ONES.items() if v < 10) + r"))?"
    r"|" + "|".join(_ONES)
)
# A count token: digits or a number word, not glued to a word, a decimal point or a hyphen
# ("twenty-four" must not yield 4; "Reaper 6000" is handled by the caller).
_COUNT = r"(?<![\w.,-])(\d{1,4}|" + _NUMBER_WORD + r")\s+"
# Quest text likes measure words: "5 pieces of Alterac Granite", "8 bottles of Rot Hide Ichor".
_MEASURE = r"(?:[A-Za-z]+\s+of\s+)?"
# After the name: not a hyphenated continuation ("Ogre-Mages"), and not another capitalised
# word ("20 Plaguehound Runts" is not twenty Plaguehounds).
_AFTER = r"(?![\w-])(?!\s+(?-i:[A-Z]))"  # the pattern is case-insensitive; this part is not


# "Collect 7 Power Crystals of each color": one count, meant for every objective that shares
# the name. Looked for in the few words after the count.
_EACH = re.compile(r"\S+\s+(?:\S+\s+){0,4}?(?:of\s+)?each\b", re.IGNORECASE)


def _number(token: str) -> int:
    token = token.lower()
    if token.isdigit():
        return int(token)
    tens, _, ones = token.partition("-")
    if tens in _TENS:
        return _TENS[tens] + (_ONES.get(ones, 0) if ones else 0)
    return _ONES[token]


_IRREGULAR = {"man": "men", "mage": "magi", "magus": "magi", "mouse": "mice", "child": "children",
              "foot": "feet", "tooth": "teeth", "goose": "geese", "ox": "oxen"}


def _word_pattern(word: str) -> str:
    """Match a word in its singular or plural spelling: Bandana/Bandanas, Wolf/Wolves,
    Harpy/Harpies, Highwayman/Highwaymen, Mage/Magi, Antenna/Antennae. A long word also
    matches by its stem (Corrupted/Corrupt), which short words such as Drake must not, or
    Dra- would claim Dragonspawn."""
    forms = [word, word + "s", word + "es"]
    lower = word.lower()
    if lower.endswith("y"):
        forms.append(word[:-1] + "ies")
    if lower.endswith("f"):
        forms.append(word[:-1] + "ves")
    if lower.endswith("fe"):
        forms.append(word[:-2] + "ves")
    if lower.endswith("a"):
        forms.append(word + "e")
    for singular, plural in _IRREGULAR.items():
        if lower.endswith(singular):
            forms.append(word[:-len(singular)] + plural)
    escaped = [re.escape(f) for f in sorted(set(forms), key=len, reverse=True)]
    if len(word) >= 7 and word.isalpha():
        escaped.append(re.escape(word[:-2]) + r"(?-i:[a-z'])*")
    return "(?:" + "|".join(escaped) + ")"


def _pattern(words: list[str]) -> re.Pattern:
    body = r"[\s-]+".join(_word_pattern(w) for w in words)
    return re.compile(_COUNT + _MEASURE + body + _AFTER, re.IGNORECASE)


def _tails(name: str):
    """The name, then the name with leading words dropped: quest text shortens names
    ("7 Coastrunners" for Murloc Coastrunner). A lone last word only counts when it is a
    real word of four letters or more; a tail that starts after a number is never used
    ("Super Reaper 6000 Blueprints": that 6000 is part of the name)."""
    words = name.split()
    for start in range(len(words)):
        tail = words[start:]
        if start > 0 and len(tail) == 1 and not (tail[0].isalpha() and len(tail[0]) >= 4):
            return
        if start > 0 and (words[start - 1].isdigit() or words[start - 1].lower() in _ONES
                          or words[start - 1].lower() in _TENS):
            continue
        yield start == 0, tail


def _candidates(name: str | None, text: str) -> list[tuple[int, int, bool]]:
    """Every count token in `text` that could belong to `name`: (position, amount, full)."""
    if not name:
        return []
    found: dict[int, tuple[int, int, bool]] = {}
    for full, tail in _tails(name):
        for match in _pattern(tail).finditer(text):
            pos = match.start(1)
            amount = _number(match.group(1))
            if amount >= 1 and (pos not in found or full):
                found[pos] = (pos, amount, full)
    return sorted(found.values())


def infer_amounts(names: list[str | None], objectives_text: str | None) -> list[int | None]:
    """Counts for the objectives of one quest, read from its objectives sentence.

    One count token serves one objective. Full-name matches are settled first, longest
    name first, so "10 Black Dragonspawn" goes to Black Dragonspawn and not to Black Drake.
    Shortened-name matches come after; a token that two objectives can only reach that way
    ("the three pieces of Gelkak's Key") goes to neither.
    """
    result: list[int | None] = [None] * len(names)
    if not objectives_text:
        return result
    text = objectives_text
    candidates = [_candidates(n, text) for n in names]
    by_length = sorted(range(len(names)),
                       key=lambda i: (-len((names[i] or "").split()), -len(names[i] or ""), i))
    taken: set[int] = set()
    for i in by_length:
        for pos, amount, full in candidates[i]:
            if full and pos not in taken:
                taken.add(pos)
                result[i] = amount
                break
    for i in by_length:
        if result[i] is not None:
            continue
        options = [(pos, amount) for pos, amount, full in candidates[i] if not full and pos not in taken]
        if not options:
            continue
        pos, amount = options[0]
        rivals = [k for k in by_length if k != i and result[k] is None
                  and any(p == pos and not f for p, _, f in candidates[k])]
        if rivals and not _EACH.match(text, pos):
            continue
        taken.add(pos)
        result[i] = amount
        for k in rivals:  # "7 Power Crystals of each color": the count is per objective
            result[k] = amount
    return result


def infer_amount(name: str | None, objectives_text: str | None) -> int | None:
    """One objective on its own; see infer_amounts."""
    return infer_amounts([name], objectives_text)[0]


# --------------------------------------------------------------------------
# One quest row -> QuestRow, objectives, meta
# --------------------------------------------------------------------------

@dataclass
class _Draft:
    """An objective before numbering: what kind, which target, Questie's custom text."""

    type: str
    target_id: int | None
    target_name: str | None
    text: str | None = None
    counted: bool = True  # False for reputation and spells, which have no "N things" amount


def _simple_drafts(entries: object, type_: str, names: dict[int, str]) -> list[_Draft]:
    """creature/object/item objectives: `{ {id, text?, icon?}, ... }`."""
    drafts = []
    for entry in _values(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get(1), int):
            continue
        text = entry.get(2) if isinstance(entry.get(2), str) else None
        drafts.append(_Draft(type_, entry[1], names.get(entry[1]), text))
    return drafts


def _kill_credit_drafts(entries: object, names: Names) -> list[_Draft]:
    """killCredit: `{ { {npcIDs...}, baseCreatureID, baseCreatureText, icon }, ... }`.
    Several NPCs count for one objective line; the base creature names that line."""
    drafts = []
    for entry in _values(entries):
        if not isinstance(entry, dict):
            continue
        base_id = entry.get(2) if isinstance(entry.get(2), int) else None
        text = entry.get(3) if isinstance(entry.get(3), str) else None
        name = text or (names.npc.get(base_id) if base_id is not None else None)
        drafts.append(_Draft("monster", base_id, name, text))
    return drafts


def _spell_drafts(entries: object) -> list[_Draft]:
    """spell: `{ {spellID, text, itemID}, ... }`. There is no spell name table to resolve."""
    drafts = []
    for entry in _values(entries):
        if isinstance(entry, dict) and isinstance(entry.get(1), int):
            text = entry.get(2) if isinstance(entry.get(2), str) else None
            drafts.append(_Draft("spell", entry[1], None, text, counted=False))
    return drafts


def build_objectives(
    quest_id: int, field: object, objectives_text: str | None, names: Names,
    trigger_end: object = None,
) -> list[db.Objective]:
    """Questie's `objectives` and `triggerEnd` fields -> contract objectives, numbered from 1.

    Order: monsters, kill credits, objects, items, reputation, spell, then the trigger. The
    reputation value is a standing threshold, not a count of things, so it never becomes
    `amount`. `triggerEnd = { text, {zone = coords} }` is the "Scout through the Fargodeep
    Mine" kind of objective: the game shows its text as an event line in the quest log.
    """
    drafts: list[_Draft] = []
    if isinstance(field, dict):
        drafts += _simple_drafts(field.get(OBJ_CREATURE), "monster", names.npc)
        drafts += _kill_credit_drafts(field.get(OBJ_KILL_CREDIT), names)
        drafts += _simple_drafts(field.get(OBJ_OBJECT), "object", names.object)
        drafts += _simple_drafts(field.get(OBJ_ITEM), "item", names.item)
        reputation = field.get(OBJ_REPUTATION)
        if isinstance(reputation, dict) and isinstance(reputation.get(1), int):
            drafts.append(_Draft("reputation", reputation[1], None, counted=False))
        drafts += _spell_drafts(field.get(OBJ_SPELL))
    trigger_text = trigger_end.get(1) if isinstance(trigger_end, dict) else None
    if isinstance(trigger_text, str) and trigger_text.strip():
        drafts.append(_Draft("event", None, None, canonical_tokens(trigger_text.strip()), counted=False))

    amounts = infer_amounts([d.target_name if d.counted else None for d in drafts], objectives_text)
    objectives = []
    for idx, (draft, amount) in enumerate(zip(drafts, amounts), start=1):
        objectives.append(db.Objective(
            quest_id=quest_id, idx=idx, type=draft.type, target_id=draft.target_id,
            target_name=draft.target_name, amount=amount or 1,
            amount_source="text" if amount else "default", text=draft.text, source=SOURCE,
        ))
    return objectives


def turnin_name(finished_by: object, names: Names) -> str | None:
    """`finishedBy = { {npcIDs...}, {objectIDs...} }`: first NPC with a name, else first object."""
    return turnin(finished_by, None, names)[0]


def turnin(finished_by: object, started_by: object, names: Names) -> tuple[str | None, str | None]:
    """The turn-in name and what it is: "giver" when the quest is handed back to an NPC who
    also offers it ("Go back to"), "other" when it is a different NPC ("Go see"), "object"
    for a mailbox, altar or barrel. `startedBy = { {npcIDs...}, {objectIDs...}, {itemIDs...} }`."""
    if not isinstance(finished_by, dict):
        return None, None
    starters = set()
    if isinstance(started_by, dict):
        starters = {i for i in _values(started_by.get(FINISHED_BY_NPCS)) if isinstance(i, int)}
    for entity_id in _values(finished_by.get(FINISHED_BY_NPCS)):
        if entity_id in names.npc:
            return names.npc[entity_id], "giver" if entity_id in starters else "other"
    for entity_id in _values(finished_by.get(FINISHED_BY_OBJECTS)):
        if entity_id in names.object:
            return names.object[entity_id], "object"
    return None, None


def _joined_text(value: object) -> str | None:
    """`objectivesText` is a list of strings (occasionally a bare string); join with a space."""
    parts = [value] if isinstance(value, str) else [p for p in _values(value) if isinstance(p, str)]
    text = db.clean(" ".join(parts))
    return canonical_tokens(text) if text else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# --------------------------------------------------------------------------
# load()
# --------------------------------------------------------------------------

def load(
    conn: sqlite3.Connection, raw_dir: Path, *, offline: bool = False, fetch: Fetch = http_fetch
) -> db.SourceResult:
    """Download (or reuse) the four files, then write rows, objectives, meta and known IDs."""
    result = db.SourceResult(source=SOURCE)
    cache_dir = ensure_cache(Path(raw_dir), offline=offline, fetch=fetch, notes=result.notes)
    fetched_at = _read_manifest(cache_dir).get(QUEST_DB.filename, {}).get("fetched_at") or db.utcnow()

    names = Names(
        npc=load_names(cache_dir / NPC_DB.filename, NPC_DB),
        item=load_names(cache_dir / ITEM_DB.filename, ITEM_DB),
        object=load_names(cache_dir / OBJECT_DB.filename, OBJECT_DB),
    )
    text = (cache_dir / QUEST_DB.filename).read_text(encoding="utf-8")
    keys = luatable.parse_key_enum(text, QUEST_DB.keys_name)
    body = luatable.extract_long_string(text, QUEST_DB.data_name)
    wanted = ("name", "startedBy", "finishedBy", "requiredLevel", "questLevel", "objectivesText",
              "objectives", "questFlags")
    missing = [k for k in wanted if k not in keys]
    if missing:
        raise ValueError(f"{QUEST_DB.filename}: key enum lacks {missing}; Questie changed its format")
    last_needed = max(keys[k] for k in wanted + (("triggerEnd",) if "triggerEnd" in keys else ()))

    quest_ids: list[int] = []
    without_text = 0
    for quest_id, row in luatable.iter_rows(body, max_index=last_needed):
        if not isinstance(quest_id, int) or not isinstance(row, dict):
            continue
        quest_ids.append(quest_id)
        title = row.get(keys["name"])
        title = canonical_tokens(title) if isinstance(title, str) and title.strip() else None
        objectives_text = _joined_text(row.get(keys["objectivesText"]))
        db.upsert_meta(
            conn, quest_id, SOURCE,
            level=_int_or_none(row.get(keys["questLevel"])),
            required_level=_int_or_none(row.get(keys["requiredLevel"])),
            flags=_int_or_none(row.get(keys["questFlags"])),
        )
        if title is None and objectives_text is None:
            without_text += 1
            continue
        turnin_npc, turnin_kind = turnin(row.get(keys["finishedBy"]), row.get(keys["startedBy"]), names)
        quest_row = db.QuestRow(
            id=quest_id, source=SOURCE, title=title, objectives_text=objectives_text,
            turnin_npc=turnin_npc, turnin_kind=turnin_kind, fetched_at=fetched_at,
        )
        if db.upsert_source_row(conn, quest_row):
            result.rows_written += 1
        else:
            result.rows_skipped += 1
        trigger_end = row.get(keys["triggerEnd"]) if "triggerEnd" in keys else None
        objectives = build_objectives(
            quest_id, row.get(keys["objectives"]), objectives_text, names, trigger_end)
        if objectives:
            db.replace_objectives(conn, quest_id, objectives)
            result.objectives_written += len(objectives)

    result.known_ids = db.add_known_ids(conn, quest_ids, KNOWN_IDS_BUILD)
    result.notes.append(
        f"{len(quest_ids)} quest IDs, {len(names.npc)} NPC, {len(names.item)} item and "
        f"{len(names.object)} object names read"
    )
    if without_text:
        result.notes.append(f"{without_text} quests have neither a title nor objectives text; no row written")
    return result

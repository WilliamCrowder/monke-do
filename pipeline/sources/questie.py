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

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_COUNT = r"(?<![\w.,])(\d{1,4}|" + "|".join(_NUMBER_WORDS) + r")\s+"
# Quest text likes measure words: "5 pieces of Alterac Granite", "8 bottles of Rot Hide Ichor".
_MEASURE = r"(?:[A-Za-z]+\s+of\s+)?"


def _word_pattern(word: str) -> str:
    """Match a word by its stem so plurals still hit: Bandana/Bandanas, Wolf/Wolves.
    Dropping the last two letters covers -f/-ves and -y/-ies without a word list."""
    stem = word if len(word) <= 3 else word[:max(3, len(word) - 2)]
    return re.escape(stem) + r"[\w']*"


def _count_before(words: list[str], objectives_text: str) -> int | None:
    pattern = _COUNT + _MEASURE + r"[\s-]+".join(_word_pattern(w) for w in words)
    match = re.search(pattern, objectives_text, re.IGNORECASE)
    if not match:
        return None
    count = match.group(1).lower()
    amount = _NUMBER_WORDS.get(count) or int(count)
    return amount if amount >= 1 else None


def infer_amount(name: str | None, objectives_text: str | None) -> int | None:
    """Find a count written directly before `name` in the sentence, or None.

    "bring her 10 Red Silk Bandanas" + "Red Silk Bandana" -> 10. Every word is matched
    by stem because the plural is not always on the last word ("Chunks of Boar Meat").
    Quest text also shortens names ("7 Coastrunners" for Murloc Coastrunner), so when
    the full name is not there, leading words are dropped one at a time. The last
    word alone only counts when it is a real word of four letters or more.
    """
    if not name or not objectives_text:
        return None
    words = name.split()
    for start in range(len(words)):
        tail = words[start:]
        if start > 0 and len(tail) == 1 and not (tail[0].isalpha() and len(tail[0]) >= 4):
            break
        if start > 0 and (words[start - 1].isdigit() or words[start - 1].lower() in _NUMBER_WORDS):
            continue  # "Super Reaper 6000 Blueprints": that 6000 is part of the name
        amount = _count_before(tail, objectives_text)
        if amount is not None:
            return amount
    return None


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

    objectives = []
    for idx, draft in enumerate(drafts, start=1):
        amount = infer_amount(draft.target_name, objectives_text) if draft.counted else None
        objectives.append(db.Objective(
            quest_id=quest_id, idx=idx, type=draft.type, target_id=draft.target_id,
            target_name=draft.target_name, amount=amount or 1,
            amount_source="text" if amount else "default", text=draft.text, source=SOURCE,
        ))
    return objectives


def turnin_name(finished_by: object, names: Names) -> str | None:
    """`finishedBy = { {npcIDs...}, {objectIDs...} }`: first NPC with a name, else first object."""
    if not isinstance(finished_by, dict):
        return None
    for ids, table in ((finished_by.get(FINISHED_BY_NPCS), names.npc),
                       (finished_by.get(FINISHED_BY_OBJECTS), names.object)):
        for entity_id in _values(ids):
            if entity_id in table:
                return table[entity_id]
    return None


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
    wanted = ("name", "finishedBy", "requiredLevel", "questLevel", "objectivesText",
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
        quest_row = db.QuestRow(
            id=quest_id, source=SOURCE, title=title, objectives_text=objectives_text,
            turnin_npc=turnin_name(row.get(keys["finishedBy"]), names), fetched_at=fetched_at,
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

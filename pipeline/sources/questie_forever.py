"""QuestieDB's Forever release as a source (contract section 5).

QuestieDB publishes a built database per game flavour with every release
(github.com/Questie/QuestieDB/releases). `QuestieDB-Forever.zip` is what Questie in the Forever
client reads: the vanilla quests with Forever's corrections folded in, plus the quests new in
Forever (IDs 90000 and up), which the `data/Classic` and `data/Forever` source files on master
do not hold. It has the same fields as the Classic files the `questie` source reads (title,
objectives sentence, givers and finishers, objectives, levels, flags), so rows are written by
`questie.write_quest`.

Provenance, from QuestieDB's docs/forever-delta-base.md: the new quests come from an offline
import of Wowhead's Forever pages, then traces from players' clients and hand corrections.
Monke Do does not fetch Wowhead itself; it reads QuestieDB's published GPL-3 release.

The release is pinned (`RELEASE`), so a rebuild gives the same data. Updating is: bump
`RELEASE` (or pass `--questie-release <tag>` to try one), run the pipeline, write summaries for
what is new or changed.

Storage, verified on v1.0.6: the database sits in `QuestieDB/QuestieDB_Forever.toc` as addon
metadata lines, `## X-<Entity>-<id>-<field>: <base64 CBOR>`. Field `S` is the scalar row (a map
of field index -> number or string, plus `p`, a bit mask of which table fields exist); a table
field is its own key. A value too long for one line is `~N~`, with the parts in `<key>-1` ..
`<key>-N`. The zip is read, never extracted, and nothing in it is executed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

from pipeline import cbor, db
from pipeline.sources import questie

SOURCE = "questie_forever"
PRIORITY = 2
NEEDS_NETWORK = True
OPTIONS: tuple[str, ...] = ("questie_release",)

RELEASE = "v1.0.6"
ASSET = "QuestieDB-Forever.zip"
TOC = "QuestieDB/QuestieDB_Forever.toc"
RELEASE_URL = "https://github.com/Questie/QuestieDB/releases/download/{tag}/" + ASSET
KNOWN_IDS_BUILD = "questie-forever"

# QuestieDB's src/meta/questMeta.lua (the same indices as Questie's questKeys).
QUEST_KEYS = {
    "name": 1, "startedBy": 2, "finishedBy": 3, "requiredLevel": 4, "questLevel": 5,
    "objectivesText": 8, "triggerEnd": 9, "objectives": 10, "questFlags": 23,
}
TABLE_FIELDS = ("startedBy", "finishedBy", "objectivesText", "triggerEnd", "objectives")
NAME_FIELD = 1  # npcMeta, itemMeta and objectMeta all keep the name at 1

_LINE = re.compile(r"^## (X-[^:]+): (.*)$")
_CHUNKS = re.compile(r"^~(\d+)~$")
_SCALAR_KEY = re.compile(r"^X-(Quest|Npc|Item|Object)-(\d+)-S$")


# --------------------------------------------------------------------------
# Download and cache
# --------------------------------------------------------------------------

def http_fetch(url: str, etag: str | None) -> questie.Download:
    """The real network fetch. Tests pass their own function instead."""
    import httpx  # imported here so offline runs and tests never need it

    reply = httpx.get(url, headers={"User-Agent": questie.USER_AGENT}, follow_redirects=True, timeout=300)
    reply.raise_for_status()
    return questie.Download(content=reply.content, etag=reply.headers.get("ETag"))


def ensure_cache(raw_dir: Path, tag: str, *, offline: bool, fetch: questie.Fetch) -> Path:
    """The release zip in `raw_dir/questie_forever/<tag>/`, downloaded once. A tag names one
    build, so a cached copy is never fetched again."""
    folder = Path(raw_dir) / SOURCE / tag
    path = folder / ASSET
    if path.exists():
        return path
    if offline:
        raise FileNotFoundError(
            f"QuestieDB {tag} is not cached in {folder}. Run the questie_forever source once "
            "without offline mode to download it.")
    url = RELEASE_URL.format(tag=tag)
    download = fetch(url, None)
    zipfile.ZipFile(io.BytesIO(download.content)).getinfo(TOC)  # a wrong asset fails here, not later
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(download.content)
    (folder / "manifest.json").write_text(json.dumps({
        "url": url, "etag": download.etag, "bytes": len(download.content),
        "sha256": hashlib.sha256(download.content).hexdigest(), "fetched_at": db.utcnow(),
    }, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Reading the metadata store
# --------------------------------------------------------------------------

def read_store(toc_text: str) -> dict[str, str]:
    """`X-` key -> stored value, with chunked values put back together."""
    raw: dict[str, str] = {}
    for line in toc_text.splitlines():
        match = _LINE.match(line)
        if match:
            raw[match.group(1)] = match.group(2).strip()
    store: dict[str, str] = {}
    for key, value in raw.items():
        chunks = _CHUNKS.match(value)
        if chunks:
            parts = [raw.get(f"{key}-{i}") for i in range(1, int(chunks.group(1)) + 1)]
            if any(part is None for part in parts):
                raise ValueError(f"{key} declares {chunks.group(1)} parts but some are missing")
            value = "".join(parts)
        store[key] = value
    return store


def decode(value: str):
    return cbor.loads(base64.b64decode(value + "=" * (-len(value) % 4)))


def as_lua(value):
    """CBOR lists -> dicts keyed 1, 2, ... (nil holes dropped), the shape `pipeline.luatable`
    gives, so `questie`'s helpers read both sources the same way."""
    if isinstance(value, list):
        return {i: as_lua(v) for i, v in enumerate(value, start=1) if v is not None}
    if isinstance(value, dict):
        return {k: as_lua(v) for k, v in value.items() if v is not None}
    return value


def entity_ids(store: dict[str, str], entity: str) -> list[int]:
    return sorted(int(m.group(2)) for key in store
                  if (m := _SCALAR_KEY.match(key)) and m.group(1) == entity)


def names_of(store: dict[str, str], entity: str) -> dict[int, str]:
    names: dict[int, str] = {}
    for entity_id in entity_ids(store, entity):
        row = decode(store[f"X-{entity}-{entity_id}-S"])
        name = row.get(NAME_FIELD) if isinstance(row, dict) else None
        if isinstance(name, str) and name.strip():
            names[entity_id] = name
    return names


def quest_row(store: dict[str, str], quest_id: int) -> dict:
    """Field index -> value for the fields `questie.write_quest` reads."""
    scalars = decode(store[f"X-Quest-{quest_id}-S"])
    row = {k: v for k, v in scalars.items() if isinstance(k, int)} if isinstance(scalars, dict) else {}
    for field in TABLE_FIELDS:
        index = QUEST_KEYS[field]
        stored = store.get(f"X-Quest-{quest_id}-{index}")
        if stored is not None:
            row[index] = as_lua(decode(stored))
    return row


# --------------------------------------------------------------------------
# load()
# --------------------------------------------------------------------------

def load(
    conn: sqlite3.Connection, raw_dir: Path, *, offline: bool = False,
    questie_release: str | None = None, fetch: questie.Fetch = http_fetch,
) -> db.SourceResult:
    """Read the pinned release (downloading it once), then write rows, objectives, meta and
    known IDs exactly as the `questie` source does."""
    result = db.SourceResult(source=SOURCE)
    tag = questie_release or RELEASE
    path = ensure_cache(Path(raw_dir), tag, offline=offline, fetch=fetch)
    manifest = path.parent / "manifest.json"
    fetched_at = (json.loads(manifest.read_text(encoding="utf-8")).get("fetched_at")
                  if manifest.exists() else None) or db.utcnow()

    store = read_store(zipfile.ZipFile(path).read(TOC).decode("utf-8"))
    flavor = store.get("X-Flavor")
    if flavor not in (None, "Forever"):
        raise ValueError(f"{ASSET} {tag} says it is for {flavor!r}, not Forever")
    names = questie.Names(
        npc=names_of(store, "Npc"), item=names_of(store, "Item"), object=names_of(store, "Object"))

    quest_ids = entity_ids(store, "Quest")
    without_text = 0
    for quest_id in quest_ids:
        row = quest_row(store, quest_id)
        if not questie.write_quest(conn, result, quest_id, row, QUEST_KEYS, names, fetched_at, SOURCE):
            without_text += 1

    result.known_ids = db.add_known_ids(conn, quest_ids, KNOWN_IDS_BUILD)
    new = sum(1 for i in quest_ids if i >= db.NEW_ID_THRESHOLD)
    result.notes.append(
        f"QuestieDB {tag} (commit {store.get('X-BUILD-COMMIT', '?')[:12]}): {len(quest_ids)} quest IDs, "
        f"{new} of them new in Forever; {len(names.npc)} NPC, {len(names.item)} item and "
        f"{len(names.object)} object names")
    if without_text:
        result.notes.append(f"{without_text} quests have neither a title nor objectives text; no row written")
    return result

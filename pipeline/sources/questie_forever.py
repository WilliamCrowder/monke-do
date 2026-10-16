"""QuestieDB's Forever release as a source (contract section 5).

QuestieDB publishes a built database per game flavour with every release
(github.com/Questie/QuestieDB/releases). `QuestieDB-Forever.zip` is what Questie in the Forever
client reads: the vanilla quests with Forever's corrections folded in, plus the quests new in
Forever (most with IDs of 90000 and up, some below), which the `data/Classic` and `data/Forever`
source files on master do not hold. It has the same fields as the Classic files the `questie`
source reads (title, objectives sentence, givers and finishers, objectives, levels, flags), so
rows are written by `questie.write_quest`.

Provenance, from QuestieDB's docs/forever-delta-base.md: the new quests come from an offline
import of Wowhead's Forever pages, then traces from players' clients and hand corrections.
Monke Do does not fetch Wowhead itself; it reads QuestieDB's published GPL-3 release.

The release is pinned by tag and by content (`RELEASE`, `RELEASE_SHA256`, `RELEASE_BYTES`), so a
rebuild gives the same data: the download must match the digest before it is cached (written to
a `.part` file, then renamed), and the cached copy is checked again before every load. Updating
is: bump all three (or pass `--questie-release <tag>` to try one: an unpinned tag is checked only
against its own first download), run the pipeline, write summaries for what is new or changed.

Each load is authoritative: rows and objectives an earlier load wrote for quests this release no
longer has (or has without text) are deleted, and so is everything the Classic `questie` source
wrote. Both have priority 2, and leftovers of one would otherwise fill the gaps of the other.

Storage, verified on v1.0.6: the database sits in `QuestieDB/QuestieDB_Forever.toc` as addon
metadata lines, `## X-<Entity>-<id>-<field>: <base64 CBOR>`. Field `S` is the scalar row (a map
of field index -> number or string, plus `p`, a bit mask of which table fields exist); a table
field is its own key. A value too long for one line is `~N~`, with the parts in `<key>-1` ..
`<key>-N`. The zip is read, never extracted, and nothing in it is executed. Some `S` rows are
Lua sequences, which CBOR writes as arrays: those are not read (a note counts them).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
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
CONFLICTS: tuple[str, ...] = ("questie",)  # the Classic files: the same database, older

RELEASE = "v1.0.6"
# The pinned release, byte for byte. A tag can be moved and an asset replaced; these cannot.
RELEASE_SHA256 = "d78b066c362eaf28258d9e2d041c0a7b03d6943a2dfc741dec70c6bfd8e1fc27"
RELEASE_BYTES = 13_514_513
ASSET = "QuestieDB-Forever.zip"
TOC = "QuestieDB/QuestieDB_Forever.toc"
RELEASE_URL = "https://github.com/Questie/QuestieDB/releases/download/{tag}/" + ASSET
KNOWN_IDS_BUILD = "questie-forever"
MAX_TOC_BYTES = 128 * 1024 * 1024  # what the TOC may unpack to; v1.0.6's is 15.9 MB
MAX_PARTS = 10_000  # parts of one chunked value; v1.0.6 splits values into at most 236

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


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest(), path.stat().st_size


def _expected(tag: str, folder: Path) -> tuple[str, int] | None:
    """What the release must be: the pin for the pinned tag, else what its first download was."""
    if tag == RELEASE:
        return RELEASE_SHA256, RELEASE_BYTES
    manifest = folder / "manifest.json"
    if not manifest.exists():
        return None
    record = json.loads(manifest.read_text(encoding="utf-8"))
    return record.get("sha256"), record.get("bytes")


def check_cached(path: Path, tag: str) -> None:
    """Refuse a cached copy that is not the release it should be (corrupted, cut short, or
    replaced). Run before every load, offline or not."""
    folder = path.parent
    expected = _expected(tag, folder)
    if expected is None:
        raise ValueError(f"QuestieDB {tag} in {folder} cannot be checked: the tag is not pinned and "
                         "there is no manifest. Delete the folder to download it again.")
    digest, size = _file_digest(path)
    if (digest, size) != expected:
        what = "the pinned release" if tag == RELEASE else "the copy first downloaded"
        raise ValueError(f"QuestieDB {tag} in {folder} is not {what}: sha256 {digest}, {size} bytes; "
                         f"expected sha256 {expected[0]}, {expected[1]} bytes. Delete the folder to "
                         "download it again.")


def _toc_info(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    try:
        info = archive.getinfo(TOC)
    except KeyError:
        raise ValueError(f"{ASSET} has no {TOC}: it is not the asset this source reads") from None
    if info.file_size > MAX_TOC_BYTES:
        raise ValueError(f"{TOC} unpacks to {info.file_size} bytes, more than the {MAX_TOC_BYTES} allowed")
    return info


def read_toc(path: Path) -> str:
    """The TOC's text. Its size is checked before it is unpacked, and the read is capped too."""
    with zipfile.ZipFile(path) as archive:
        info = _toc_info(archive)
        with archive.open(info) as handle:
            data = handle.read(MAX_TOC_BYTES + 1)
    if len(data) > MAX_TOC_BYTES:
        raise ValueError(f"{TOC} unpacks to more than the {MAX_TOC_BYTES} allowed")
    return data.decode("utf-8")


def ensure_cache(raw_dir: Path, tag: str, *, offline: bool, fetch: questie.Fetch) -> Path:
    """The release zip in `raw_dir/questie_forever/<tag>/`, downloaded once and checked always.

    A tag names one build, so a cached copy is never fetched again; it is checked against the pin
    (or, for an unpinned tag, its manifest) instead. A download that is not the pinned release is
    refused before anything is written. The zip goes to a `.part` file first and is renamed when
    complete, so a crash never leaves a half-written file under the real name."""
    folder = Path(raw_dir) / SOURCE / tag
    path = folder / ASSET
    if path.exists():
        check_cached(path, tag)
        return path
    if offline:
        raise FileNotFoundError(
            f"QuestieDB {tag} is not cached in {folder}. Run the questie_forever source once "
            "without offline mode to download it.")
    url = RELEASE_URL.format(tag=tag)
    download = fetch(url, None)
    content = download.content
    digest, size = hashlib.sha256(content).hexdigest(), len(content)
    if tag == RELEASE and (digest, size) != (RELEASE_SHA256, RELEASE_BYTES):
        raise ValueError(f"the download of QuestieDB {tag} is not the pinned release: sha256 {digest}, "
                         f"{size} bytes; expected sha256 {RELEASE_SHA256}, {RELEASE_BYTES} bytes. The tag "
                         "or its asset changed upstream; nothing was cached.")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        _toc_info(archive)  # a wrong or oversized asset fails here, not later
    folder.mkdir(parents=True, exist_ok=True)
    # The manifest first: a zip under the real name always has the record it is checked against.
    (folder / "manifest.json").write_text(json.dumps({
        "url": url, "etag": download.etag, "bytes": size, "sha256": digest,
        "pinned": tag == RELEASE, "fetched_at": db.utcnow(),
    }, indent=2), encoding="utf-8")
    part = folder / (ASSET + ".part")
    part.write_bytes(content)
    os.replace(part, path)
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
    limit = min(MAX_PARTS, len(raw))  # every part is a line of its own
    for key, value in raw.items():
        chunks = _CHUNKS.match(value)
        if chunks:
            digits = chunks.group(1)
            if len(digits) > len(str(MAX_PARTS)) or not 1 <= int(digits) <= limit:
                raise ValueError(f"{key} declares {digits} parts; a value is split into 1 to {limit} "
                                 "parts, each on a line of its own")
            parts = [raw.get(f"{key}-{i}") for i in range(1, int(digits) + 1)]
            if any(part is None for part in parts):
                raise ValueError(f"{key} declares {digits} parts but some are missing")
            value = "".join(parts)
        store[key] = value
    return store


def decode(value: str, key: str = "a value"):
    """One stored value: base64 (the standard alphabet, nothing else) holding one CBOR item."""
    try:
        data = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
    except binascii.Error as exc:
        raise ValueError(f"{key} is not base64 ({exc})") from None
    try:
        return cbor.loads(data)
    except cbor.CBORError as exc:
        raise cbor.CBORError(f"{key}: {exc}") from None


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


def _scalars(store: dict[str, str], entity: str, entity_id: int):
    """The decoded S row, field index -> value. A row holding only fields 1..n comes as a CBOR
    array (a Lua sequence); it reads the same way, field 1 first (v1.0.6 has 3,140 of them)."""
    key = f"X-{entity}-{entity_id}-S"
    row = decode(store[key], key)
    if isinstance(row, list):
        row = as_lua(row)
    return row


def names_of(store: dict[str, str], entity: str) -> dict[int, str]:
    names: dict[int, str] = {}
    for entity_id in entity_ids(store, entity):
        row = _scalars(store, entity, entity_id)
        name = row.get(NAME_FIELD) if isinstance(row, dict) else None
        if isinstance(name, str) and name.strip():
            names[entity_id] = name
    return names


def quest_row(store: dict[str, str], quest_id: int) -> dict:
    """Field index -> value for the fields `questie.write_quest` reads."""
    scalars = _scalars(store, "Quest", quest_id)
    row = {k: v for k, v in scalars.items() if isinstance(k, int)} if isinstance(scalars, dict) else {}
    for field in TABLE_FIELDS:
        index = QUEST_KEYS[field]
        key = f"X-Quest-{quest_id}-{index}"
        stored = store.get(key)
        if stored is not None:
            row[index] = as_lua(decode(stored, key))
    return row


# --------------------------------------------------------------------------
# load()
# --------------------------------------------------------------------------

def load(
    conn: sqlite3.Connection, raw_dir: Path, *, offline: bool = False,
    questie_release: str | None = None, fetch: questie.Fetch = http_fetch,
) -> db.SourceResult:
    """Read the pinned release (downloading it once, checking it every time), then write rows,
    objectives, meta and known IDs exactly as the `questie` source does."""
    result = db.SourceResult(source=SOURCE)
    tag = questie_release or RELEASE
    path = ensure_cache(Path(raw_dir), tag, offline=offline, fetch=fetch)
    if tag != RELEASE:
        result.notes.append(f"QuestieDB {tag} is not pinned (the pinned release is {RELEASE}): it is "
                            "checked only against its own first download. Pin its SHA-256 and size "
                            "before shipping data from it.")
    manifest = path.parent / "manifest.json"
    fetched_at = (json.loads(manifest.read_text(encoding="utf-8")).get("fetched_at")
                  if manifest.exists() else None) or db.utcnow()

    store = read_store(read_toc(path))
    flavor = store.get("X-Flavor")
    if flavor not in (None, "Forever"):
        raise ValueError(f"{ASSET} {tag} says it is for {flavor!r}, not Forever")
    purged = db.purge_source(conn, questie.SOURCE, questie.KNOWN_IDS_BUILD)
    if purged:
        result.notes.append(f"removed {purged} rows the Classic {questie.SOURCE} source left: the two never mix")
    names = questie.Names(
        npc=names_of(store, "Npc"), item=names_of(store, "Item"),
        object=names_of(store, "Object"))

    quest_ids = entity_ids(store, "Quest")
    written: list[int] = []
    without_text = 0
    for quest_id in quest_ids:
        row = quest_row(store, quest_id)
        if questie.write_quest(conn, result, quest_id, row, QUEST_KEYS, names, fetched_at, SOURCE):
            written.append(quest_id)
        else:
            without_text += 1

    questie.note_pruned(result, *db.prune_source(conn, SOURCE, written))
    result.known_ids = db.replace_known_ids(conn, quest_ids, KNOWN_IDS_BUILD)
    new = sum(1 for i in quest_ids if db.is_new_quest(i))
    result.notes.append(
        f"QuestieDB {tag} (commit {store.get('X-BUILD-COMMIT', '?')[:12]}): {len(quest_ids)} quest IDs, "
        f"{new} of them new in Forever; {len(names.npc)} NPC, {len(names.item)} item and "
        f"{len(names.object)} object names")
    if without_text:
        result.notes.append(f"{without_text} quests have neither a title nor objectives text; no row written")
    return result

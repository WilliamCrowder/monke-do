"""SQLite schema and helpers. The single definition of docs/DATA_CONTRACT.md section 4.

Source modules and the summarizer go through these helpers instead of writing SQL
of their own, so the contract lives in one place.
"""

from __future__ import annotations

import functools
import hashlib
import re
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3
# Every quest ID in Classic Questie, committed (`questie.write_classic_ids` rebuilds it). A quest
# it lacks is new in Forever whatever its ID: most new quests are 90000 and up, but not all.
CLASSIC_IDS_FILE = Path(__file__).resolve().parent / "classic_quest_ids.txt"

TEXT_FIELDS = ("title", "detail", "objectives_text", "progress", "complete")

# Lower number wins. Unknown sources sort last among text sources.
SOURCE_PRIORITY = {
    "wowforevertalents": 1,
    "questie": 2,
    "questie_forever": 2,
    "wago": 3,
}
DEFAULT_TEXT_PRIORITY = 1  # any other Forever web source

OBJECTIVE_TYPES = (
    "monster", "item", "object", "event", "spell", "reputation", "log", "player", "progressbar",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_rows (
    id              INTEGER NOT NULL,
    source          TEXT    NOT NULL,
    title           TEXT,
    detail          TEXT,
    objectives_text TEXT,
    progress        TEXT,
    complete        TEXT,
    turnin_npc      TEXT,
    turnin_kind     TEXT,               -- 'giver' | 'other' | 'object' | NULL (unknown)
    fetched_at      TEXT    NOT NULL,
    text_hash       TEXT    NOT NULL,
    PRIMARY KEY (id, source)
);
CREATE TABLE IF NOT EXISTS quests (
    id              INTEGER PRIMARY KEY,
    title           TEXT,
    detail          TEXT,
    objectives_text TEXT,
    progress        TEXT,
    complete        TEXT,
    turnin_npc      TEXT,
    turnin_kind     TEXT,
    source          TEXT    NOT NULL,
    fetched_at      TEXT    NOT NULL,
    text_hash       TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS text_diffs (
    n           INTEGER PRIMARY KEY AUTOINCREMENT,
    id          INTEGER NOT NULL,
    field       TEXT    NOT NULL,
    source_a    TEXT    NOT NULL,
    source_b    TEXT    NOT NULL,
    text_a      TEXT,
    text_b      TEXT,
    logged_at   TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS objectives (
    quest_id      INTEGER NOT NULL,
    idx           INTEGER NOT NULL,
    type          TEXT    NOT NULL,
    target_id     INTEGER,
    target_name   TEXT,
    amount        INTEGER NOT NULL DEFAULT 1,
    amount_source TEXT    NOT NULL DEFAULT 'default',
    text          TEXT,
    source        TEXT    NOT NULL,
    PRIMARY KEY (quest_id, idx)
);
CREATE TABLE IF NOT EXISTS quest_meta (
    quest_id       INTEGER PRIMARY KEY,
    level          INTEGER,
    required_level INTEGER,
    xp             INTEGER,
    flags          INTEGER,
    group_size     INTEGER,
    tag            TEXT,
    source         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS known_ids (
    id    INTEGER NOT NULL,
    build TEXT    NOT NULL,
    PRIMARY KEY (id, build)
);
CREATE TABLE IF NOT EXISTS summaries (
    quest_id       INTEGER NOT NULL,
    text_hash      TEXT    NOT NULL,
    prompt_version TEXT    NOT NULL,
    model          TEXT,
    json           TEXT,
    status         TEXT    NOT NULL,   -- 'ok' | 'rejected' | 'error'
    errors         TEXT,               -- JSON list of validator messages
    attempts       INTEGER NOT NULL DEFAULT 1,
    context_hash   TEXT,               -- fingerprint of everything the writer was shown
    created_at     TEXT    NOT NULL,
    PRIMARY KEY (quest_id, text_hash, prompt_version)
);
CREATE TABLE IF NOT EXISTS pipeline_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@dataclass
class QuestRow:
    """One quest as seen by one source. Missing text is None, never ''."""

    id: int
    source: str
    title: str | None = None
    detail: str | None = None
    objectives_text: str | None = None
    progress: str | None = None
    complete: str | None = None
    turnin_npc: str | None = None
    turnin_kind: str | None = None  # 'giver' | 'other' (a different NPC) | 'object'
    fetched_at: str | None = None


@dataclass
class Objective:
    quest_id: int
    idx: int
    type: str
    target_id: int | None = None
    target_name: str | None = None
    amount: int = 1
    amount_source: str = "default"
    text: str | None = None
    source: str = ""


@dataclass
class SourceResult:
    """What a source module's load() returns."""

    source: str
    rows_written: int = 0
    rows_skipped: int = 0  # unchanged text_hash
    objectives_written: int = 0
    known_ids: int = 0
    notes: list[str] = field(default_factory=list)


# Columns added after the first databases were built. CREATE TABLE IF NOT EXISTS leaves an
# old table alone, so they are added here; the data is rebuilt from the raw cache anyway.
_ADDED_COLUMNS = (
    ("source_rows", "turnin_kind", "TEXT"),
    ("quests", "turnin_kind", "TEXT"),
    ("summaries", "context_hash", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, kind in _ADDED_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.commit()


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_classic_ids(path: str | Path) -> frozenset[int]:
    """A Classic ID list file: one quest ID per line, '#' lines are comments."""
    ids = set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.isdigit():
            raise ValueError(f"{path}:{number}: expected a quest ID, found {line!r}")
        ids.add(int(line))
    return frozenset(ids)


@functools.cache
def classic_quest_ids() -> frozenset[int]:
    """The vanilla quests: every quest ID in Classic Questie (CLASSIC_IDS_FILE)."""
    return read_classic_ids(CLASSIC_IDS_FILE)


def is_new_quest(quest_id: int, classic: Collection[int] | None = None) -> bool:
    """True for a quest new in Forever: one Classic Questie does not have. `classic` replaces
    the committed list (tests, or a caller that already holds it)."""
    return quest_id not in (classic if classic is not None else classic_quest_ids())


_WS = re.compile(r"\s+")


def clean(text: str | None) -> str | None:
    """Collapse whitespace, strip, and turn '' into None."""
    if text is None:
        return None
    text = _WS.sub(" ", text).strip()
    return text or None


def text_hash(row: QuestRow | sqlite3.Row | dict) -> str:
    get = (lambda k: getattr(row, k)) if isinstance(row, QuestRow) else (lambda k: row[k])
    joined = "\x1f".join(clean(get(f)) or "" for f in TEXT_FIELDS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def priority_of(source: str) -> int:
    return SOURCE_PRIORITY.get(source, DEFAULT_TEXT_PRIORITY)


def upsert_source_row(conn: sqlite3.Connection, row: QuestRow) -> bool:
    """Insert or update one (id, source) row. Returns False when the text is unchanged."""
    for f in TEXT_FIELDS + ("turnin_npc",):
        setattr(row, f, clean(getattr(row, f)))
    h = text_hash(row)
    if row.turnin_kind not in (None, "giver", "other", "object"):
        raise ValueError(f"quest {row.id}: unknown turnin_kind {row.turnin_kind!r}")
    old = conn.execute(
        "SELECT text_hash, turnin_npc, turnin_kind FROM source_rows WHERE id = ? AND source = ?",
        (row.id, row.source),
    ).fetchone()
    if (old is not None and old["text_hash"] == h and old["turnin_npc"] == row.turnin_npc
            and old["turnin_kind"] == row.turnin_kind):
        return False
    conn.execute(
        """INSERT OR REPLACE INTO source_rows
           (id, source, title, detail, objectives_text, progress, complete,
            turnin_npc, turnin_kind, fetched_at, text_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row.id, row.source, row.title, row.detail, row.objectives_text, row.progress,
         row.complete, row.turnin_npc, row.turnin_kind, row.fetched_at or utcnow(), h),
    )
    return True


def replace_objectives(conn: sqlite3.Connection, quest_id: int, objectives: list[Objective]) -> bool:
    """Replace a quest's structured objectives. Returns False when the existing rows won.

    Rows with db2 amounts (wago) beat rows without, but wago rows carry no names: a db2
    row that replaces a named row of the same type and target keeps that row's name and
    wording, so the rule-based bullets do not lose their verb and count.
    """
    existing = get_objectives(conn, quest_id)
    existing_is_db2 = any(o["amount_source"] == "db2" for o in existing)
    incoming_is_db2 = any(o.amount_source == "db2" for o in objectives)
    if existing_is_db2 and not incoming_is_db2:
        return False
    for o in objectives:
        if o.type not in OBJECTIVE_TYPES:
            raise ValueError(f"quest {quest_id}: unknown objective type {o.type!r}")
    if incoming_is_db2 and existing and not existing_is_db2:
        by_target = {(row["type"], row["target_id"]): row for row in existing if row["target_id"] is not None}
        by_idx = {row["idx"]: row for row in existing}
        for o in objectives:
            match = by_target.get((o.type, o.target_id)) if o.target_id is not None else None
            if match is None and by_idx.get(o.idx) is not None and by_idx[o.idx]["type"] == o.type:
                match = by_idx[o.idx]
            if match is not None:
                o.target_name = o.target_name or match["target_name"]
                o.text = o.text or match["text"]
    conn.execute("DELETE FROM objectives WHERE quest_id = ?", (quest_id,))
    for o in objectives:
        conn.execute(
            """INSERT INTO objectives
               (quest_id, idx, type, target_id, target_name, amount, amount_source, text, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (quest_id, o.idx, o.type, o.target_id, clean(o.target_name), o.amount,
             o.amount_source, clean(o.text), o.source),
        )
    return True


def upsert_meta(conn: sqlite3.Connection, quest_id: int, source: str, **fields) -> None:
    """Merge metadata: a new non-null value replaces the old one, a null never does."""
    cols = ("level", "required_level", "xp", "flags", "group_size", "tag")
    unknown = set(fields) - set(cols)
    if unknown:
        raise ValueError(f"unknown quest_meta fields: {sorted(unknown)}")
    old = conn.execute("SELECT * FROM quest_meta WHERE quest_id = ?", (quest_id,)).fetchone()
    merged = {c: (old[c] if old is not None else None) for c in cols}
    for c, v in fields.items():
        if v is not None:
            merged[c] = v
    conn.execute(
        """INSERT OR REPLACE INTO quest_meta
           (quest_id, level, required_level, xp, flags, group_size, tag, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (quest_id, *(merged[c] for c in cols), source),
    )


def add_known_ids(conn: sqlite3.Connection, ids, build: str) -> int:
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO known_ids (id, build) VALUES (?, ?)", ((int(i), build) for i in ids)
    )
    return conn.total_changes - before


def replace_known_ids(conn: sqlite3.Connection, ids, build: str) -> int:
    """Make `build`'s ID list exactly `ids`: IDs a newer copy no longer has are dropped.
    Returns how many IDs were added, like add_known_ids."""
    keep = {int(i) for i in ids}
    gone = [(r[0], build) for r in conn.execute("SELECT id FROM known_ids WHERE build = ?", (build,))
            if r[0] not in keep]
    conn.executemany("DELETE FROM known_ids WHERE id = ? AND build = ?", gone)
    return add_known_ids(conn, sorted(keep), build)


def prune_source(conn: sqlite3.Connection, source: str, keep_ids) -> tuple[int, int]:
    """A load is authoritative for its own source: delete `source`'s rows and objectives for
    every quest ID it did not write this time (gone from the source, or left without text),
    so the database never depends on what an older copy of the source said.

    Returns (source rows deleted, quests whose objectives were deleted).
    """
    keep = set(keep_ids)
    rows = [(r[0], source) for r in conn.execute("SELECT id FROM source_rows WHERE source = ?", (source,))
            if r[0] not in keep]
    conn.executemany("DELETE FROM source_rows WHERE id = ? AND source = ?", rows)
    objectives = [(r[0], source) for r in conn.execute(
        "SELECT DISTINCT quest_id FROM objectives WHERE source = ?", (source,)) if r[0] not in keep]
    conn.executemany("DELETE FROM objectives WHERE quest_id = ? AND source = ?", objectives)
    return len(rows), len(objectives)


def purge_source(conn: sqlite3.Connection, source: str, known_ids_build: str | None = None) -> int:
    """Delete everything `source` ever wrote: its rows, its objectives and, with
    `known_ids_build`, its ID list. For a source that another one replaces (the Classic Questie
    files and the Forever release are two versions of one database at one priority), so the
    leftovers of one never fill the gaps of the other. Quest metadata is merged across sources
    by design and stays. Returns the number of source rows deleted."""
    deleted = conn.execute("DELETE FROM source_rows WHERE source = ?", (source,)).rowcount
    conn.execute("DELETE FROM objectives WHERE source = ?", (source,))
    if known_ids_build is not None:
        conn.execute("DELETE FROM known_ids WHERE build = ?", (known_ids_build,))
    return deleted


def resolve_quests(conn: sqlite3.Connection) -> dict:
    """Rebuild `quests` from `source_rows` by source priority, logging text diffs.

    The winner is the highest-priority source with any text for the ID (newest fetched_at
    within one priority). Fields the winner lacks are filled from the next source.
    """
    stats = {"quests": 0, "diffs": 0, "filled_fields": 0}
    conn.execute("DELETE FROM quests")
    conn.execute("DELETE FROM text_diffs")
    ids = [r[0] for r in conn.execute("SELECT DISTINCT id FROM source_rows ORDER BY id")]
    now = utcnow()
    for qid in ids:
        rows = conn.execute("SELECT * FROM source_rows WHERE id = ?", (qid,)).fetchall()
        rows = [r for r in rows if any(r[f] for f in TEXT_FIELDS)]
        if not rows:
            continue
        rows.sort(key=lambda r: r["fetched_at"], reverse=True)  # newest first (stable)
        rows.sort(key=lambda r: priority_of(r["source"]))
        winner = rows[0]
        merged = {f: winner[f] for f in TEXT_FIELDS + ("turnin_npc", "turnin_kind")}
        for other in rows[1:]:
            for f in TEXT_FIELDS + ("turnin_npc",):
                if merged[f] is None and other[f] is not None:
                    merged[f] = other[f]
                    stats["filled_fields"] += 1
                    if f == "turnin_npc":
                        merged["turnin_kind"] = other["turnin_kind"]  # travels with the name
                elif (
                    f in TEXT_FIELDS
                    and winner[f] is not None
                    and other[f] is not None
                    and clean(winner[f]) != clean(other[f])
                ):
                    conn.execute(
                        """INSERT INTO text_diffs
                           (id, field, source_a, source_b, text_a, text_b, logged_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (qid, f, winner["source"], other["source"], winner[f], other[f], now),
                    )
                    stats["diffs"] += 1
        conn.execute(
            """INSERT INTO quests
               (id, title, detail, objectives_text, progress, complete, turnin_npc,
                turnin_kind, source, fetched_at, text_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (qid, merged["title"], merged["detail"], merged["objectives_text"],
             merged["progress"], merged["complete"], merged["turnin_npc"], merged["turnin_kind"],
             winner["source"], winner["fetched_at"], text_hash(merged)),
        )
        stats["quests"] += 1
    conn.commit()
    return stats


def reconcile_amounts(conn: sqlite3.Connection, infer_amounts) -> int:
    """Re-read sentence-parsed amounts against the sentence that won resolve_quests.

    Questie parses counts from its own objectives sentence. When a higher-priority source
    supplies a different sentence for the same quest (Forever rewrote it), those counts
    may be stale, so every non-db2 counted objective is inferred again from the winning
    sentence. `infer_amounts(names, sentence) -> [amount | None]` comes from the questie
    module; passing it in keeps db.py free of source imports. Returns rows changed.
    """
    changed = 0
    quests = conn.execute(
        """SELECT q.id, q.objectives_text FROM quests q
           WHERE q.objectives_text IS NOT NULL
             AND EXISTS (SELECT 1 FROM objectives o
                         WHERE o.quest_id = q.id AND o.amount_source != 'db2')"""
    ).fetchall()
    for quest in quests:
        rows = get_objectives(conn, quest["id"])
        if any(r["amount_source"] == "db2" for r in rows):
            continue
        countable = [r["target_name"] if r["type"] in ("monster", "item", "object") else None for r in rows]
        amounts = infer_amounts(countable, quest["objectives_text"])
        for row, amount in zip(rows, amounts):
            if countable[rows.index(row)] is None:
                continue
            new_amount, new_source = (amount, "text") if amount else (1, "default")
            if (row["amount"], row["amount_source"]) != (new_amount, new_source):
                conn.execute(
                    "UPDATE objectives SET amount = ?, amount_source = ? WHERE quest_id = ? AND idx = ?",
                    (new_amount, new_source, quest["id"], row["idx"]),
                )
                changed += 1
    return changed


def get_objectives(conn: sqlite3.Connection, quest_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM objectives WHERE quest_id = ? ORDER BY idx", (quest_id,)
    ).fetchall()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO pipeline_meta (key, value) VALUES (?, ?)", (key, value))


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM pipeline_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default

"""SQLite schema and helpers. The single definition of docs/DATA_CONTRACT.md section 4.

Source modules and the summarizer go through these helpers instead of writing SQL
of their own, so the contract lives in one place.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3
NEW_ID_THRESHOLD = 90000  # Forever-new quests use high IDs; vanilla IDs are below this.

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


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    old = conn.execute(
        "SELECT text_hash, turnin_npc FROM source_rows WHERE id = ? AND source = ?",
        (row.id, row.source),
    ).fetchone()
    if old is not None and old["text_hash"] == h and old["turnin_npc"] == row.turnin_npc:
        return False
    conn.execute(
        """INSERT OR REPLACE INTO source_rows
           (id, source, title, detail, objectives_text, progress, complete,
            turnin_npc, fetched_at, text_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row.id, row.source, row.title, row.detail, row.objectives_text, row.progress,
         row.complete, row.turnin_npc, row.fetched_at or utcnow(), h),
    )
    return True


def replace_objectives(conn: sqlite3.Connection, quest_id: int, objectives: list[Objective]) -> None:
    """Replace a quest's structured objectives. db2 amounts are never overwritten by weaker ones."""
    existing = conn.execute(
        "SELECT amount_source FROM objectives WHERE quest_id = ? LIMIT 1", (quest_id,)
    ).fetchone()
    incoming_is_db2 = any(o.amount_source == "db2" for o in objectives)
    if existing is not None and existing["amount_source"] == "db2" and not incoming_is_db2:
        return
    conn.execute("DELETE FROM objectives WHERE quest_id = ?", (quest_id,))
    for o in objectives:
        if o.type not in OBJECTIVE_TYPES:
            raise ValueError(f"quest {quest_id}: unknown objective type {o.type!r}")
        conn.execute(
            """INSERT INTO objectives
               (quest_id, idx, type, target_id, target_name, amount, amount_source, text, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (quest_id, o.idx, o.type, o.target_id, clean(o.target_name), o.amount,
             o.amount_source, clean(o.text), o.source),
        )


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
        merged = {f: winner[f] for f in TEXT_FIELDS + ("turnin_npc",)}
        for other in rows[1:]:
            for f in TEXT_FIELDS + ("turnin_npc",):
                if merged[f] is None and other[f] is not None:
                    merged[f] = other[f]
                    stats["filled_fields"] += 1
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
                source, fetched_at, text_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (qid, merged["title"], merged["detail"], merged["objectives_text"],
             merged["progress"], merged["complete"], merged["turnin_npc"],
             winner["source"], winner["fetched_at"], text_hash(merged)),
        )
        stats["quests"] += 1
    conn.commit()
    return stats


def get_objectives(conn: sqlite3.Connection, quest_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM objectives WHERE quest_id = ? ORDER BY idx", (quest_id,)
    ).fetchall()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO pipeline_meta (key, value) VALUES (?, ?)", (key, value))


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM pipeline_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default

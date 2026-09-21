"""How much of the game the database covers, as a plain-text report.

The number that matters most is the "missing lore backlog": quest IDs we know exist
(from Questie or a wago build) for which no source has given us any text yet. Quest
lore is sent by the server and cannot be listed by ID in-game, so that backlog is
expected to be non-empty. It is the to-do list for the next source.
"""

from __future__ import annotations

import sqlite3

from pipeline import db

_PRESENCE_FIELDS = ("detail", "objectives_text", "progress", "complete", "turnin_npc")
_AMOUNT_SOURCES = ("db2", "text", "default")
_LABEL_WIDTH = 34


def _count(conn: sqlite3.Connection, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def missing_lore(conn: sqlite3.Connection) -> list[int]:
    """Known quest IDs with no row in `quests`, ascending."""
    rows = conn.execute(
        "SELECT DISTINCT id FROM known_ids WHERE id NOT IN (SELECT id FROM quests) ORDER BY id"
    )
    return [row[0] for row in rows]


def _line(label: str, value: int | str, indent: int = 0) -> str:
    label = " " * indent + label
    return f"{label:<{_LABEL_WIDTH}}{value:>8}"


def report(conn: sqlite3.Connection) -> str:
    """The whole report as one string. Reads only; call after `resolve_quests`."""
    threshold = db.NEW_ID_THRESHOLD
    total = _count(conn, "SELECT COUNT(*) FROM quests")
    lines = [
        "Monke Do coverage",
        "=================",
        _line("Quests with text", total),
        _line(f"vanilla (id < {threshold})", _count(conn, "SELECT COUNT(*) FROM quests WHERE id < ?", threshold), 2),
        _line(f"new (id >= {threshold})", _count(conn, "SELECT COUNT(*) FROM quests WHERE id >= ?", threshold), 2),
        "",
        "Rows per source",
    ]
    per_source = conn.execute(
        "SELECT source, COUNT(*) FROM source_rows GROUP BY source ORDER BY source"
    ).fetchall()
    lines += [_line(row[0], row[1], 2) for row in per_source] or [_line("(none)", 0, 2)]

    lines += ["", "Quests that have"]
    for field in _PRESENCE_FIELDS:  # names come from the tuple above, never from input
        lines.append(_line(field, _count(conn, f"SELECT COUNT(*) FROM quests WHERE {field} IS NOT NULL"), 2))

    lines += ["", "Objectives by amount_source"]
    lines.append(_line("quests with objectives", _count(conn, "SELECT COUNT(DISTINCT quest_id) FROM objectives"), 2))
    for amount_source in _AMOUNT_SOURCES:
        lines.append(_line(
            amount_source,
            _count(conn, "SELECT COUNT(*) FROM objectives WHERE amount_source = ?", amount_source), 2,
        ))

    lines += ["", _line("Text diffs between sources", _count(conn, "SELECT COUNT(*) FROM text_diffs"))]

    lines += ["", "Known quest IDs per build"]
    per_build = conn.execute("SELECT build, COUNT(*) FROM known_ids GROUP BY build ORDER BY build").fetchall()
    lines += [_line(row[0], row[1], 2) for row in per_build] or [_line("(none)", 0, 2)]

    backlog = missing_lore(conn)
    lines += ["", _line("Missing lore backlog", len(backlog))]
    lines.append("  known IDs with no text from any source")
    if backlog:
        shown = ", ".join(str(i) for i in backlog[:10])
        lines.append(f"  first IDs: {shown}{' ...' if len(backlog) > 10 else ''}")
    return "\n".join(lines)

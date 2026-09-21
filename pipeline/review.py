"""Human review sample: the page someone reads before each release.

The validator catches mechanical mistakes; only a person can tell whether the lore is
faithful and the jokes land kindly. This writes a fixed, seeded sample so two people
reviewing the same database read the same quests, with Forever-new quests (ids of
90000 and up) sampled separately because no earlier release has vetted them.
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from pipeline import db, rules
from pipeline.llm.summarize import get_summary

_SOURCE_FIELDS = (("Detail", "detail"), ("Objectives text", "objectives_text"),
                  ("Progress", "progress"), ("Complete", "complete"))


def pick_ids(
    conn: sqlite3.Connection, *, n_random: int, n_new: int, seed: int, prompt_version: str
) -> list[int]:
    """`n_new` Forever-new quests plus `n_random` from the rest, all with a summary row.

    Falls back to every quest when nothing has been summarised yet, so the file is
    still useful for eyeballing source text early in a project.
    """
    summarised = [r["id"] for r in conn.execute(
        """SELECT q.id FROM quests q JOIN summaries s
           ON s.quest_id = q.id AND s.text_hash = q.text_hash AND s.prompt_version = ?
           ORDER BY q.id""", (prompt_version,))]
    pool = summarised or [r["id"] for r in conn.execute("SELECT id FROM quests ORDER BY id")]
    rng = random.Random(seed)
    new = [i for i in pool if i >= db.NEW_ID_THRESHOLD]
    picked_new = rng.sample(new, min(n_new, len(new)))
    taken = set(picked_new)
    rest = [i for i in pool if i not in taken]
    picked_random = rng.sample(rest, min(n_random, len(rest)))
    return sorted(picked_new + picked_random)


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() or [""])


def _status_line(row: sqlite3.Row | None) -> str:
    if row is None:
        return "no summary (rule-based fallback)"
    return f"{row['status']} (model {row['model'] or '?'}, attempts {row['attempts']})"


def _summary_of(row: sqlite3.Row | None) -> dict:
    try:
        parsed = json.loads(row["json"]) if row is not None and row["json"] else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def render_quest(conn: sqlite3.Connection, quest: sqlite3.Row, prompt_version: str) -> str:
    """One quest as a markdown section: source text first, then what players would read."""
    row = get_summary(conn, quest["id"], quest["text_hash"], prompt_version)
    summary = _summary_of(row)
    objectives = db.get_objectives(conn, quest["id"])
    out = [f"## {quest['id']}: {quest['title'] or '(untitled)'}", ""]
    out += [f"- Validator status: {_status_line(row)}",
            f"- Source: {quest['source']}; turn-in NPC: {quest['turnin_npc'] or 'unknown'}"]
    errors = json.loads(row["errors"]) if row is not None and row["errors"] else []
    out += [f"- Validator error: {e}" for e in errors]
    out.append("")
    for label, key in _SOURCE_FIELDS:
        if quest[key]:
            out += [f"**{label}**", "", _quote(quest[key]), ""]
    if objectives:
        out += ["**Structured objectives**", ""]
        out += [f"{o['idx']}. {o['type']}: {o['target_name'] or o['text'] or '(unnamed)'} "
                f"x{o['amount']} ({o['amount_source']})" for o in objectives]
        out.append("")
    out += ["**Monke lore**", "", _quote(str(summary.get("lore_monke") or "(none)")), "",
            "**Plain lore**", "", _quote(str(summary.get("lore_plain") or "(none)")), ""]
    shipped = row is not None and row["status"] == "ok" and isinstance(summary.get("tasks"), list)
    tasks = summary["tasks"] if shipped else rules.tasks_for(objectives, quest["turnin_npc"],
                                                             rules.MONKE)
    out += ["**Tasks**" if shipped else "**Tasks (rule-based fallback, this is what ships)**", ""]
    out += [f"- {t}" for t in tasks]
    if summary.get("group_line"):
        out += ["", f"**Group line:** {summary['group_line']}"]
    if not shipped and isinstance(summary.get("tasks"), list):
        out += ["", "**Rejected LLM tasks**", ""] + [f"- {t}" for t in summary["tasks"]]
    return "\n".join(out) + "\n"


def write_sample(
    conn: sqlite3.Connection,
    path: Path,
    *,
    n_random: int = 50,
    n_new: int = 50,
    seed: int = 0,
    prompt_version: str = "v1",
) -> int:
    """Write the review file and return how many quests it holds. Same seed, same file."""
    ids = pick_ids(conn, n_random=n_random, n_new=n_new, seed=seed, prompt_version=prompt_version)
    new = sum(1 for i in ids if i >= db.NEW_ID_THRESHOLD)
    parts = [
        "# Monke Do review sample\n",
        f"{len(ids)} quests ({new} Forever-new, {len(ids) - new} other), seed {seed}, "
        f"prompt {prompt_version}.\n",
        "Check each one: is the lore true to the source text, is it kind to the player, and "
        "do the task numbers match?\n",
    ]
    for quest_id in ids:
        quest = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
        parts.append(render_quest(conn, quest, prompt_version))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\n".join(parts).encode("utf-8"))
    return len(ids)

"""review.write_sample: a deterministic, human-readable sample of what would ship."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import db, review
from pipeline.llm import summarize


def make_db(n_vanilla: int = 30, n_new: int = 10):
    conn = db.connect()
    ids = list(range(1, n_vanilla + 1)) + list(range(90001, 90001 + n_new))
    for quest_id in ids:
        db.upsert_source_row(conn, db.QuestRow(
            id=quest_id, source="questie", title=f"Quest {quest_id}",
            detail=f"Long story number {quest_id}.\nSecond line.",
            objectives_text=f"Kill 5 Rat {quest_id}.", turnin_npc="Bob",
        ))
        db.replace_objectives(conn, quest_id, [db.Objective(
            quest_id=quest_id, idx=1, type="monster", target_name=f"Rat {quest_id}", amount=5,
            amount_source="text", source="questie")])
    db.resolve_quests(conn)
    for quest_id in ids:
        quest = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
        rejected = quest_id % 7 == 0
        summary = {"lore_monke": f"Rats bad {quest_id}.", "lore_plain": f"Rats are bad {quest_id}.",
                   "tasks": [f"Bonk 5 Rat {quest_id}.", "Go back to Bob."],
                   "group_line": "Bring friends." if quest_id == 90001 else None}
        summarize.save_summary(
            conn, quest_id, quest["text_hash"], "v1", model="fake", summary_json=json.dumps(summary),
            status="rejected" if rejected else "ok",
            errors=["tasks[1] is sad."] if rejected else [], attempts=3 if rejected else 1)
    return conn


def test_sample_sizes_and_new_quest_share(tmp_path: Path) -> None:
    path = tmp_path / "out" / "review.md"
    count = review.write_sample(make_db(), path, n_random=8, n_new=4, seed=1)
    text = path.read_text(encoding="utf-8")
    assert count == 12 == text.count("\n## ")
    headings = [int(line[3:].split(":")[0]) for line in text.splitlines() if line.startswith("## ")]
    assert headings == sorted(headings)
    assert sum(1 for i in headings if i >= 90000) >= 4  # at least the dedicated new-quest share


def test_same_seed_same_bytes_different_seed_different_sample(tmp_path: Path) -> None:
    conn = make_db()
    for name, seed in (("a", 3), ("b", 3), ("c", 4)):
        review.write_sample(conn, tmp_path / f"{name}.md", n_random=5, n_new=2, seed=seed)
    a, b, c = ((tmp_path / f"{n}.md").read_bytes() for n in "abc")
    assert a == b
    assert a != c
    assert b"\r" not in a


def test_sample_is_capped_by_what_exists(tmp_path: Path) -> None:
    assert review.write_sample(make_db(3, 1), tmp_path / "r.md") == 4


def test_each_quest_shows_source_lore_tasks_and_status(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    review.write_sample(make_db(8, 1), path, n_random=50, n_new=50)
    text = path.read_text(encoding="utf-8")
    ok = text.split("## 3: Quest 3")[1].split("\n## ")[0]
    assert "Validator status: ok (model fake, attempts 1)" in ok
    assert "> Long story number 3. Second line." in ok  # db.clean collapses whitespace
    assert "> Kill 5 Rat 3." in ok
    assert "1. monster: Rat 3 x5 (text)" in ok
    assert "**Monke lore**\n\n> Rats bad 3." in ok
    assert "**Plain lore**\n\n> Rats are bad 3." in ok
    assert "**Tasks**\n\n- Bonk 5 Rat 3.\n- Go back to Bob." in ok
    assert "turn-in NPC: Bob" in ok

    rejected = text.split("## 7: Quest 7")[1].split("\n## ")[0]
    assert "Validator status: rejected (model fake, attempts 3)" in rejected
    assert "- Validator error: tasks[1] is sad." in rejected
    assert "rule-based fallback, this is what ships" in rejected
    assert "**Rejected LLM tasks**" in rejected

    assert "**Group line:** Bring friends." in text.split("## 90001: Quest 90001")[1]


def test_without_any_summaries_the_sample_falls_back_to_all_quests(tmp_path: Path) -> None:
    conn = make_db(5, 0)
    conn.execute("DELETE FROM summaries")
    path = tmp_path / "review.md"
    assert review.write_sample(conn, path, n_random=3, n_new=3) == 3
    text = path.read_text(encoding="utf-8")
    assert "no summary (rule-based fallback)" in text
    assert "- Bonk 5 Rat" in text

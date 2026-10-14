"""The command line's safety rails: nothing here touches the network or an LLM."""

import json
from pathlib import Path

import pytest

from pipeline import cli, db


@pytest.fixture
def quiet_dirs(tmp_path: Path, monkeypatch) -> Path:
    """Point every path the CLI writes at a temp folder."""
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "Data")
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(cli, "SUMMARIES_DIR", tmp_path / "summaries")
    return tmp_path


def _farm_db(path: Path) -> None:
    conn = db.connect(path)
    db.upsert_source_row(conn, db.QuestRow(id=9001, source="questie", title="Rats",
                                           objectives_text="Kill rats for Farmer Bo.", turnin_npc="Farmer Bo"))
    db.upsert_source_row(conn, db.QuestRow(id=9002, source="questie", title="Wolves",
                                           objectives_text="Kill wolves for Ranger Pell.", turnin_npc="Ranger Pell"))
    db.resolve_quests(conn)
    conn.close()


def test_summarize_always_applies_the_committed_summaries(quiet_dirs: Path, capsys) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    folder = quiet_dirs / "summaries"
    folder.mkdir()
    (folder / "2026-09.jsonl").write_text(
        json.dumps({"id": 9001, "lore_monke": "Farmer Bo hate rats.", "lore_plain": "Farmer Bo has rats.",
                    "tasks": ["Bonk rats.", "Go back to Farmer Bo."], "group_line": None}) + "\n"
        # Written for an older version of the quest: the turn-in NPC changed since.
        + json.dumps({"id": 9002, "lore_monke": "Wolves bad.", "lore_plain": "Wolves are bad.",
                      "tasks": ["Bonk wolves.", "Go back to Old Pell."], "group_line": None})
        + "\n", encoding="utf-8")
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert "written summaries (1 files)" in capsys.readouterr().out
    conn = db.connect(path)
    status = dict(conn.execute("SELECT quest_id, status FROM summaries").fetchall())
    assert status[9001] == "ok"
    assert status[9002] == "rejected"  # stale: `requests --rejected` hands it to a writer
    conn.close()


def test_provider_file_still_needs_a_file(quiet_dirs: Path) -> None:
    with pytest.raises(SystemExit, match="needs --summaries-file"):
        cli.main(["--db", str(quiet_dirs / "db.sqlite"), "summarize", "--provider", "file"])


def test_export_refuses_an_empty_database(quiet_dirs: Path, capsys) -> None:
    status = cli.main(["--db", str(quiet_dirs / "db.sqlite"), "export"])
    assert status == 1
    assert "refusing to export" in capsys.readouterr().out
    assert not (quiet_dirs / "Data").exists()


def test_export_refuses_a_collapse_unless_forced(quiet_dirs: Path, capsys) -> None:
    data = quiet_dirs / "Data"
    data.mkdir()
    (data / "MonkeDB_Meta.lua").write_text('MonkeDB_Meta = { count = 4000 }\n', encoding="utf-8")
    path = quiet_dirs / "db.sqlite"
    conn = db.connect(path)
    db.upsert_source_row(conn, db.QuestRow(id=214, source="questie", title="Red Silk Bandanas",
                                           objectives_text="Bring 10 Red Silk Bandanas.", turnin_npc="Scout Riell"))
    db.resolve_quests(conn)
    conn.close()
    assert cli.main(["--db", str(path), "export"]) == 1
    assert "4000 records shipped" in capsys.readouterr().out
    assert cli.main(["--db", str(path), "export", "--force"]) == 0
    assert "[214]" in (data / "MonkeDB.lua").read_text(encoding="utf-8")


def test_check_exits_non_zero_when_a_summary_fails(quiet_dirs: Path) -> None:
    path = quiet_dirs / "db.sqlite"
    conn = db.connect(path)
    db.upsert_source_row(conn, db.QuestRow(id=214, source="questie", title="Red Silk Bandanas",
                                           objectives_text="Bring 10 Red Silk Bandanas.", turnin_npc="Scout Riell"))
    db.resolve_quests(conn)
    conn.close()
    good = quiet_dirs / "good.jsonl"
    good.write_text(json.dumps({"id": 214, "lore_monke": "Scout Riell want hankies.",
                                "lore_plain": "Scout Riell wants bandanas.",
                                "tasks": ["Grab 10 Red Silk Bandana.", "Go back to Scout Riell."],
                                "group_line": None}) + "\n", encoding="utf-8")
    bad = quiet_dirs / "bad.jsonl"
    bad.write_text(json.dumps({"id": 214, "lore_monke": "Go north.", "lore_plain": "Go north.",
                               "tasks": ["Grab 10 Red Silk Bandana."], "group_line": None}) + "\n",
                   encoding="utf-8")
    assert cli.main(["--db", str(path), "check", "--summaries-file", str(good)]) == 0
    assert cli.main(["--db", str(path), "check", "--summaries-file", str(bad)]) == 1

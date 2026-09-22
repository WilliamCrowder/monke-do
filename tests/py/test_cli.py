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
    return tmp_path


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

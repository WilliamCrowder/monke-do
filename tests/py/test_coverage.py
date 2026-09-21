import re
from pathlib import Path

from pipeline import coverage, db
from pipeline.sources import load_all

FIXTURES = Path(__file__).parent / "fixtures"


def _number(report, label):
    match = re.search(rf"^\s*{re.escape(label)}\s+(\d+)\s*$", report, re.MULTILINE)
    assert match, f"no line {label!r} in:\n{report}"
    return int(match.group(1))


def _database():
    conn = db.connect()
    load_all(conn, ["questie"], FIXTURES, offline=True)
    # A Forever web source on top: one rewritten vanilla quest and one new quest.
    db.upsert_source_row(conn, db.QuestRow(
        id=214, source="wowforevertalents", title="Red Silk Bandanas",
        objectives_text="Scout Riell wants 12 Red Silk Bandanas.", detail="Invented detail.",
        progress="Any luck?", complete="Well done.",
    ))
    db.upsert_source_row(conn, db.QuestRow(id=95001, source="wowforevertalents", title="The Missing Lantern"))
    db.add_known_ids(conn, [214, 9001, 95001, 95002, 95003], "1.60.1.69913")
    db.replace_objectives(conn, 95001, [
        db.Objective(quest_id=95001, idx=1, type="item", amount=3, amount_source="db2", source="wago"),
    ])
    db.resolve_quests(conn)
    return conn


def test_missing_lore_is_known_ids_without_a_quest():
    conn = _database()
    # 9007 is a Questie ID with no text at all; 95002 and 95003 are only known from the build.
    assert coverage.missing_lore(conn) == [9007, 95002, 95003]


def test_report_numbers():
    report = coverage.report(_database())
    assert _number(report, "Quests with text") == 8
    assert _number(report, "vanilla (id < 90000)") == 7
    assert _number(report, "new (id >= 90000)") == 1
    assert _number(report, "questie") == 7
    assert _number(report, "wowforevertalents") == 2
    assert _number(report, "detail") == 1
    assert _number(report, "objectives_text") == 6  # 9004 and 95001 have a title only
    assert _number(report, "progress") == 1
    assert _number(report, "complete") == 1
    assert _number(report, "turnin_npc") == 7
    assert _number(report, "quests with objectives") == 7
    assert _number(report, "db2") == 1
    assert _number(report, "text") == 7
    assert _number(report, "default") == 4
    assert _number(report, "Text diffs between sources") == 1  # 10 bandanas versus 12
    assert _number(report, "questie-classic") == 8
    assert _number(report, "1.60.1.69913") == 5
    assert _number(report, "Missing lore backlog") == 3
    assert "first IDs: 9007, 95002, 95003" in report


def test_report_on_an_empty_database():
    report = coverage.report(db.connect())
    assert _number(report, "Quests with text") == 0
    assert _number(report, "Missing lore backlog") == 0
    assert "first IDs" not in report
    assert coverage.missing_lore(db.connect()) == []


def test_long_backlog_is_abbreviated():
    conn = db.connect()
    db.add_known_ids(conn, range(1, 40), "some-build")
    report = coverage.report(conn)
    assert _number(report, "Missing lore backlog") == 39
    assert "first IDs: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 ..." in report

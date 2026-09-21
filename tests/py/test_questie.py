import hashlib
import json
from pathlib import Path

import pytest

from pipeline import db
from pipeline.sources import questie

FIXTURES = Path(__file__).parent / "fixtures"  # holds questie/<the four files>, used as raw_dir


@pytest.fixture
def loaded():
    conn = db.connect()
    result = questie.load(conn, FIXTURES, offline=True)
    return conn, result


def _objectives(conn, quest_id):
    return [
        (o["idx"], o["type"], o["target_id"], o["target_name"], o["amount"], o["amount_source"], o["text"])
        for o in db.get_objectives(conn, quest_id)
    ]


def test_counts(loaded):
    conn, result = loaded
    assert result.source == "questie"
    assert result.rows_written == 7  # 9007 has no text at all, the commented-out 9999 does not exist
    assert result.rows_skipped == 0
    assert result.known_ids == 8
    assert result.objectives_written == 1 + 2 + 3 + 3 + 1 + 1
    assert any("neither a title nor objectives text" in note for note in result.notes)
    known = [r[0] for r in conn.execute("SELECT id FROM known_ids WHERE build = 'questie-classic' ORDER BY id")]
    assert known == [214, 9001, 9002, 9003, 9004, 9005, 9006, 9007]


def test_real_row_214(loaded):
    conn, _ = loaded
    row = conn.execute("SELECT * FROM source_rows WHERE id = 214").fetchone()
    assert row["source"] == "questie"
    assert row["title"] == "Red Silk Bandanas"
    assert row["objectives_text"] == (
        "Scout Riell at the Sentinel Hill Tower wants you to bring her 10 Red Silk Bandanas."
    )
    assert row["turnin_npc"] == "Scout Riell"
    # Questie has no long description, progress or completion text.
    assert row["detail"] is None and row["progress"] is None and row["complete"] is None
    assert _objectives(conn, 214) == [(1, "item", 915, "Red Silk Bandana", 10, "text", None)]
    meta = conn.execute("SELECT * FROM quest_meta WHERE quest_id = 214").fetchone()
    assert (meta["level"], meta["required_level"], meta["flags"], meta["source"]) == (17, 14, 8, "questie")


def test_monsters_with_irregular_plural_and_custom_text(loaded):
    conn, _ = loaded
    assert _objectives(conn, 9001) == [
        (1, "monster", 9201, "Gray Wolf", 8, "text", None),
        (2, "monster", 9202, "Ridge Stalker", 5, "text", "Ridge Stalker slain"),
    ]
    assert conn.execute("SELECT flags FROM quest_meta WHERE quest_id = 9001").fetchone()[0] == 0x10


def test_objects_come_before_items_and_object_turnin(loaded):
    conn, _ = loaded
    assert _objectives(conn, 9002) == [
        (1, "object", 9302, "Sunken Crate", 1, "default", "Search the sunken crate"),
        (2, "item", 9401, "Chunk of Mossy Bark", 6, "text", None),   # plural on the first word
        (3, "item", 9402, "Bog Iron", 4, "text", None),              # "4 pieces of Bog Iron"
    ]
    turnin = conn.execute("SELECT turnin_npc FROM source_rows WHERE id = 9002").fetchone()[0]
    assert turnin == "Old Signpost"


def test_kill_credit_reputation_and_spell(loaded):
    conn, _ = loaded
    assert _objectives(conn, 9003) == [
        (1, "monster", 9203, "Marsh Raider", 12, "text", "Marsh Raider"),
        (2, "reputation", 59, None, 1, "default", None),  # 3000 is a standing, not a count
        (3, "spell", 7001, None, 1, "default", "Learn the warden's ritual"),
    ]
    assert conn.execute("SELECT turnin_npc FROM source_rows WHERE id = 9003").fetchone()[0] == 'Elder "Two-Braids" Moss'


def test_title_only_quest_and_multi_part_text(loaded):
    conn, _ = loaded
    quiet = conn.execute("SELECT * FROM source_rows WHERE id = 9004").fetchone()
    assert quiet["title"] == "A Quiet Word" and quiet["objectives_text"] is None
    assert _objectives(conn, 9004) == []

    halla = conn.execute("SELECT * FROM source_rows WHERE id = 9005").fetchone()
    assert halla["title"] == "Halla's Request"
    assert halla["objectives_text"] == "Kill 7 Coastrunners, $n. Then report to Warden Halla.$b"
    # The sentence shortens "Tide Coastrunner" to "Coastrunners".
    assert _objectives(conn, 9005) == [(1, "monster", 9205, "Tide Coastrunner", 7, "text", None)]


def test_a_number_inside_the_name_is_not_an_amount(loaded):
    conn, _ = loaded
    assert _objectives(conn, 9006) == [(1, "item", 9404, "Reaper 6000 Blueprints", 1, "default", None)]


def test_second_load_skips_unchanged_rows(loaded):
    conn, _ = loaded
    again = questie.load(conn, FIXTURES, offline=True)
    assert (again.rows_written, again.rows_skipped, again.known_ids) == (0, 7, 0)


@pytest.mark.parametrize(("name", "text", "expected"), [
    ("Red Silk Bandana", "bring her 10 Red Silk Bandanas.", 10),
    ("Tumbled Crystal", "Collect 8 Tumbled Crystals for him", 8),
    ("Defias Trapper", "wants you to kill 15 Defias Trappers.", 15),
    ("Young Wolf", "Kill 8 young wolves", 8),
    ("Harpy", "Slay 6 Harpies", 6),
    ("Chunk of Boar Meat", "Bring 4 Chunks of Boar Meat", 4),
    ("Alterac Granite", "wants 5 pieces of Alterac Granite.", 5),
    ("Murloc Coastrunner", "Kill 7 Tidehunters and 3 Coastrunners", 3),
    ("Linen Cloth", "Bring twelve Linen Cloth", 12),
    ("Linen Cloth", "Bring some Linen Cloth", None),
    ("Linen Cloth", "Bring 6 Wool Cloth", None),
    ("Super Reaper 6000 Blueprints", "Get the Super Reaper 6000 Blueprints", None),
    ("Page 16", "Bring pages 10, 11, 14 and 16", None),
    (None, "Kill 5 things", None),
    ("Thing", None, None),
])
def test_infer_amount(name, text, expected):
    assert questie.infer_amount(name, text) == expected


def test_offline_without_a_cache_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="classicQuestDB.lua"):
        questie.load(db.connect(), tmp_path, offline=True)


def _fixture_fetch(calls):
    """A fake network: serves the fixture files and records (filename, etag sent)."""
    def fetch(url, etag):
        filename = url.rsplit("/", 1)[1]
        calls.append((filename, etag))
        if etag == f'"etag-{filename}"':
            return questie.Download(etag=etag, not_modified=True)
        content = (FIXTURES / "questie" / filename).read_bytes()
        return questie.Download(content=content, etag=f'"etag-{filename}"')
    return fetch


def test_download_caches_four_files_and_writes_a_manifest(tmp_path):
    calls = []
    conn = db.connect()
    result = questie.load(conn, tmp_path, fetch=_fixture_fetch(calls))
    assert result.rows_written == 7
    assert [c[0] for c in calls] == [
        "classicQuestDB.lua", "classicNpcDB.lua", "classicItemDB.lua", "classicObjectDB.lua",
    ]
    assert all(etag is None for _, etag in calls)
    manifest = json.loads((tmp_path / "questie" / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["classicQuestDB.lua"]
    cached = (tmp_path / "questie" / "classicQuestDB.lua").read_bytes()
    assert entry["sha256"] == hashlib.sha256(cached).hexdigest()
    assert entry["etag"] == '"etag-classicQuestDB.lua"'
    assert entry["url"].startswith("https://raw.githubusercontent.com/Questie/QuestieDB/")
    # Rows carry the download time, not the time of this particular run.
    fetched_at = conn.execute("SELECT fetched_at FROM source_rows WHERE id = 214").fetchone()[0]
    assert fetched_at == entry["fetched_at"]

    # Second online run: the stored ETags are sent, nothing is downloaded again.
    calls.clear()
    questie.load(conn, tmp_path, fetch=_fixture_fetch(calls))
    assert [etag for _, etag in calls] == [f'"etag-{name}"' for name, _ in calls]
    assert json.loads((tmp_path / "questie" / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_network_failure_falls_back_to_the_cache_with_a_note(tmp_path):
    questie.load(db.connect(), tmp_path, fetch=_fixture_fetch([]))

    def broken(url, etag):
        raise OSError("network is down")

    result = questie.load(db.connect(), tmp_path, fetch=broken)
    assert result.rows_written == 7
    assert sum("using the cached copy" in note for note in result.notes) == 4
    with pytest.raises(OSError):
        questie.load(db.connect(), tmp_path / "empty", fetch=broken)


def test_field_positions_come_from_the_files_own_key_enum(tmp_path):
    cache = tmp_path / "questie"
    cache.mkdir()
    for name in ("classicNpcDB.lua", "classicItemDB.lua", "classicObjectDB.lua"):
        (cache / name).write_bytes((FIXTURES / "questie" / name).read_bytes())
    # Same data as row 214, but with the columns in a different order.
    (cache / "classicQuestDB.lua").write_text(
        """QuestieDB.questKeys = {
            ['objectivesText'] = 1, ['name'] = 2, ['questFlags'] = 3, ['objectives'] = 4,
            ['questLevel'] = 5, ['requiredLevel'] = 6, ['finishedBy'] = 7,
        }
        QuestieDB.questData = [[return {
        [214] = {{"Bring her 10 Red Silk Bandanas."},"Red Silk Bandanas",8,{nil,nil,{{915}}},17,14,{{820}}},
        }]]""",
        encoding="utf-8",
    )
    conn = db.connect()
    questie.load(conn, tmp_path, offline=True)
    row = conn.execute("SELECT * FROM source_rows WHERE id = 214").fetchone()
    assert (row["title"], row["turnin_npc"]) == ("Red Silk Bandanas", "Scout Riell")
    assert _objectives(conn, 214) == [(1, "item", 915, "Red Silk Bandana", 10, "text", None)]
    meta = conn.execute("SELECT * FROM quest_meta WHERE quest_id = 214").fetchone()
    assert (meta["level"], meta["required_level"], meta["flags"]) == (17, 14, 8)


def test_trigger_end_becomes_an_event_objective():
    """Real row 62: no `objectives`, only `triggerEnd = {"Scout through the Fargodeep Mine", {...}}`."""
    names = questie.Names(npc={}, item={}, object={})
    trigger = {1: "Scout through the Fargodeep Mine", 2: {12: {1: {1: 40.56, 2: 82.26}}}}
    objectives = questie.build_objectives(62, None, "Explore the Fargodeep Mine.", names, trigger)
    assert [(o.idx, o.type, o.text, o.amount, o.amount_source) for o in objectives] == [
        (1, "event", "Scout through the Fargodeep Mine", 1, "default")]


def test_trigger_end_comes_after_the_other_objectives():
    names = questie.Names(npc={9201: "Gray Wolf"}, item={}, object={})
    field = {1: {1: {1: 9201}}}
    objectives = questie.build_objectives(1, field, "Kill 8 Gray Wolves and scout the den.", names,
                                          {1: "Scout the den"})
    assert [(o.idx, o.type, o.amount) for o in objectives] == [(1, "monster", 8), (2, "event", 1)]

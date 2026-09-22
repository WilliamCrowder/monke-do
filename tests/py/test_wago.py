from pathlib import Path

import pytest

from pipeline import db
from pipeline.sources import wago

FIXTURES = Path(__file__).parent / "fixtures" / "wago"
NOT_FOUND = wago.Reply(404, '{"errors":"Table not found."}')  # what wago really sends
FOREVER = "1.60.1.69913"
ERA = "1.15.8.63829"


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeWago:
    """Answers from a dict of URL -> Reply and records every URL asked for."""

    def __init__(self, replies):
        self.replies = replies
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return self.replies.get(url, NOT_FOUND)


def _csv_url(table, build):
    return f"https://wago.tools/db2/{table}/csv?build={build}"


def test_build_not_on_wago_falls_back_to_classic_era_ids(tmp_path):
    fake = FakeWago({
        "https://wago.tools/api/builds": wago.Reply(200, _read("builds.json")),
        _csv_url("QuestV2", ERA): wago.Reply(200, _read("QuestV2_era.csv")),
    })
    conn = db.connect()
    result = wago.load(conn, tmp_path, fetch=fake)

    assert fake.urls == [
        _csv_url("QuestV2", FOREVER), _csv_url("QuestObjective", FOREVER),
        _csv_url("QuestV2CliTask", FOREVER), "https://wago.tools/api/builds", _csv_url("QuestV2", ERA),
    ]
    assert result.known_ids == 4 and result.objectives_written == 0
    assert result.rows_written == 0  # structure only, never text rows
    assert conn.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] == 0
    ids = conn.execute("SELECT id, build FROM known_ids ORDER BY id").fetchall()
    assert [tuple(r) for r in ids] == [(214, ERA), (9001, ERA), (9002, ERA), (95001, ERA)]
    notes = "\n".join(result.notes)
    assert notes.count("table absent") == 3 and "Table not found." in notes
    assert f"quest IDs come from wow_classic_era {ERA} instead" in notes
    # Only real CSV is cached, under <build>/<Table>.csv. An absent table leaves a marker
    # so it is not asked for again on every run.
    assert (tmp_path / "wago" / ERA / "QuestV2.csv").exists()
    assert sorted(p.name for p in (tmp_path / "wago" / FOREVER).iterdir()) == [
        "QuestObjective.absent", "QuestV2.absent", "QuestV2CliTask.absent"]

    again = wago.load(db.connect(), tmp_path, fetch=fake)  # a second run within a day
    assert fake.urls[5:] == []  # nothing was asked for again
    assert sum("asked again in a day" in n for n in again.notes) == 3
    assert (tmp_path / "wago" / "builds.json").exists()


def test_offline_rerun_uses_only_the_cache(tmp_path):
    fake = FakeWago({
        "https://wago.tools/api/builds": wago.Reply(200, _read("builds.json")),
        _csv_url("QuestV2", ERA): wago.Reply(200, _read("QuestV2_era.csv")),
    })
    wago.load(db.connect(), tmp_path, fetch=fake)

    def no_network(url):
        raise AssertionError(f"offline run asked for {url}")

    conn = db.connect()
    result = wago.load(conn, tmp_path, offline=True, fetch=no_network)
    assert result.known_ids == 4
    assert any("not in the cache (offline)" in note for note in result.notes)


def test_offline_with_an_empty_cache_writes_nothing(tmp_path):
    result = wago.load(db.connect(), tmp_path, offline=True, fetch=lambda url: NOT_FOUND)
    assert result.known_ids == 0
    assert any("build list not in the cache" in note for note in result.notes)


def test_full_tables_when_the_build_exists(tmp_path):
    fake = FakeWago({
        _csv_url("QuestV2", FOREVER): wago.Reply(200, _read("QuestV2.csv")),
        _csv_url("QuestObjective", FOREVER): wago.Reply(200, _read("QuestObjective.csv")),
        _csv_url("QuestV2CliTask", FOREVER): wago.Reply(200, _read("QuestV2CliTask.csv")),
    })
    conn = db.connect()
    result = wago.load(conn, tmp_path, build=FOREVER, fetch=fake)

    assert "https://wago.tools/api/builds" not in fake.urls  # no fallback needed
    assert result.known_ids == 4
    builds = {r[0] for r in conn.execute("SELECT DISTINCT build FROM known_ids")}
    assert builds == {FOREVER}

    rows = [tuple(o)[1:] for o in db.get_objectives(conn, 95001)]
    assert rows == [
        # ordered by OrderIndex, not by file order; the Flags=8 (hidden) row is left out,
        # the Flags=2 (sequenced) row is kept
        (1, "monster", 9201, None, 8, "db2", "Gray Wolf slain", "wago"),
        (2, "item", 9402, None, 4, "db2", "Bog Iron, smelted", "wago"),
        (3, "monster", 9101, None, 1, "db2", "Speak with Warden Halla", "wago"),
    ]
    rows = [tuple(o)[1:] for o in db.get_objectives(conn, 95002)]
    assert rows == [
        (1, "reputation", 59, None, 1, "db2", None, "wago"),      # 3000 standing is not a count
        (2, "progressbar", None, None, 1, "db2", "Fill the bar", "wago"),
        (3, "event", None, None, 2, "db2", "Something from the future", "wago"),  # unknown type 99
    ]
    assert result.objectives_written == 6
    assert any("1 hidden QuestObjective rows" in note for note in result.notes)

    meta = conn.execute("SELECT * FROM quest_meta WHERE quest_id = 95001").fetchone()
    assert (meta["required_level"], meta["tag"], meta["source"]) == (15, "Dungeon", "wago")
    assert conn.execute("SELECT COUNT(*) FROM quest_meta WHERE quest_id = 95002").fetchone()[0] == 0


def test_db2_amounts_are_not_overwritten_by_a_weaker_source(tmp_path):
    fake = FakeWago({_csv_url("QuestObjective", FOREVER): wago.Reply(200, _read("QuestObjective.csv"))})
    conn = db.connect()
    wago.load(conn, tmp_path, fetch=fake)
    guess = db.Objective(quest_id=95001, idx=1, type="monster", amount=99, amount_source="text", source="questie")
    db.replace_objectives(conn, 95001, [guess])
    assert db.get_objectives(conn, 95001)[0]["amount"] == 8


def test_missing_columns_are_tolerated():
    by_quest, hidden = wago.objectives_by_quest(wago.read_csv("ID,QuestID,Type\n7,95009,1\n8,,1\n"))
    assert hidden == 0 and list(by_quest) == [95009]
    only = by_quest[95009][0]
    assert (only.idx, only.type, only.amount, only.amount_source, only.target_id, only.text) == (
        1, "item", 1, "db2", None, None)
    assert wago.meta_from_cli_task({"ID": "1"}) == {}
    assert wago.quest_ids(wago.read_csv("ID,UniqueBitFlag\n5,1\nx,2\n")) == [5]


@pytest.mark.parametrize(("type_id", "expected"), [
    (0, "monster"), (1, "item"), (2, "object"), (3, "monster"), (5, "spell"), (6, "reputation"),
    (7, "reputation"), (18, "reputation"), (8, "log"), (9, "player"), (10, "event"), (19, "event"),
    (20, "event"), (14, "event"), (15, "progressbar"), (4, "event"), (21, "monster"),
])
def test_type_mapping(type_id, expected):
    by_quest, _ = wago.objectives_by_quest([{"QuestID": "1", "Type": str(type_id)}])
    assert by_quest[1][0].type == expected
    assert expected in db.OBJECTIVE_TYPES


@pytest.mark.parametrize(("body", "is_csv"), [
    ("ID,UniqueBitFlag\n1,2\n", True),
    ('"ID","Name_lang"\n1,"x"\n', True),
    ('{"errors":"Table not found."}', False),
    ("<!DOCTYPE html><html>", False),
    ("", False),
    ("Name,Other\n", False),
])
def test_looks_like_csv(body, is_csv):
    assert wago.looks_like_csv(body) is is_csv


def test_http_errors_count_as_absent(tmp_path):
    fake = FakeWago({
        _csv_url("QuestV2", FOREVER): wago.Reply(404, "Not Found"),
        # a success status with the JSON error body must not be mistaken for CSV either
        _csv_url("QuestV2CliTask", FOREVER): wago.Reply(200, '{"errors":"Table not found."}'),
        # what wago really sends for a build it has never heard of
        _csv_url("QuestObjective", FOREVER): wago.Reply(404, "<!DOCTYPE html> <html lang=\"en\"> <head>"),
    })
    fake.replies["https://wago.tools/api/builds"] = wago.Reply(500, "oops")
    result = wago.load(db.connect(), tmp_path, fetch=fake)
    assert result.known_ids == 0
    assert any("HTTP 404: Not Found" in note for note in result.notes)
    assert any("HTTP 404: an HTML page" in note for note in result.notes)
    assert any("HTTP 200: {" in note for note in result.notes)
    assert any("build list: HTTP 500" in note for note in result.notes)
    assert not (tmp_path / "wago" / FOREVER / "QuestV2.csv").exists()


def test_refusals_stop_the_source_instead_of_counting_as_absent(tmp_path):
    fake = FakeWago({_csv_url("QuestV2", FOREVER): wago.Reply(429, "slow down")})
    with pytest.raises(wago.Refused, match="429"):
        wago.load(db.connect(), tmp_path, fetch=fake)
    assert fake.urls == [_csv_url("QuestV2", FOREVER)]  # nothing after the refusal


def test_build_strings_are_validated_before_they_become_paths(tmp_path):
    with pytest.raises(ValueError, match="not a game build"):
        wago.load(db.connect(), tmp_path, build="9.9.9.9/../../escaped", fetch=FakeWago({}))
    fake = FakeWago({
        _csv_url("QuestV2", FOREVER): wago.Reply(404, "no"),
        "https://wago.tools/api/builds": wago.Reply(200, '{"wow_classic_era": [{"version": "9.9.9.99999/../../out"}]}'),
    })
    result = wago.load(db.connect(), tmp_path, fetch=fake)
    assert any("no product" in n or "no fallback" in n for n in result.notes)
    assert not any("escaped" in str(p) or "out" == p.name for p in tmp_path.rglob("*"))


@pytest.mark.parametrize("body", [wago.BOM + "ID,UniqueBitFlag" + chr(10) + "1,2", "ID,UniqueBitFlag" + chr(10) + "1,2"])
def test_a_byte_order_mark_does_not_hide_a_csv(body):
    assert wago.looks_like_csv(body)

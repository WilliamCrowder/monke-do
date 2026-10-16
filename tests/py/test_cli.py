"""The command line's safety rails: nothing here touches the network or an LLM."""

import json
from pathlib import Path

import pytest

from pipeline import cli, db, validate
from pipeline.llm import providers, summarize

STAMP_KEYS = ("prompt_version", "text_hash", "context_hash")


@pytest.fixture
def quiet_dirs(tmp_path: Path, monkeypatch) -> Path:
    """Point every path the CLI writes at a temp folder. ROOT stays the repository on purpose:
    the CLI must not assume its folders live under it."""
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "Data")
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(cli, "SUMMARIES_DIR", tmp_path / "summaries")
    return tmp_path


@pytest.fixture
def paid(monkeypatch) -> list[int]:
    """`--provider batch` without the API: an unpaid stand-in, so no response log is written.
    Returns the quest ids it was asked for."""
    asked: list[int] = []

    def answer(request: providers.SummaryRequest) -> str:
        asked.append(request.quest_id)
        npc = request.user.split("Turn-in NPC: ")[1].split(" (")[0].splitlines()[0]
        return json.dumps({"lore_monke": "Paid monke.", "lore_plain": "Paid plain.",
                           "tasks": [f"Go back to {npc}."], "group_line": None})

    monkeypatch.setattr(cli, "_make_provider", lambda args: providers.FakeProvider(answer, model="paid-fake"))
    return asked


def _farm_db(path: Path) -> None:
    conn = db.connect(path)
    db.upsert_source_row(conn, db.QuestRow(id=9001, source="questie", title="Rats",
                                           objectives_text="Kill rats for Farmer Bo.", turnin_npc="Farmer Bo"))
    db.upsert_source_row(conn, db.QuestRow(id=9002, source="questie", title="Wolves",
                                           objectives_text="Kill wolves for Ranger Pell.", turnin_npc="Ranger Pell"))
    db.resolve_quests(conn)
    conn.close()


def _stamp(path: Path, quest_id: int, prompt_version: str = "v1") -> dict:
    """What `requests` hands a writer for the quest as it is now."""
    conn = db.connect(path)
    quest = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
    stamp = {"prompt_version": prompt_version, "text_hash": quest["text_hash"],
             "context_hash": validate.load_context(conn, quest).fingerprint()}
    conn.close()
    return stamp


def _line(quest_id: int, npc: str, lore: str, stamp: dict | None = None, tasks: list[str] | None = None) -> str:
    return json.dumps({"id": quest_id, **(stamp or {}), "lore_monke": lore, "lore_plain": lore,
                       "tasks": tasks or [f"Go back to {npc}."], "group_line": None}) + "\n"


def _commit(folder: Path, name: str, *lines: str) -> Path:
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _statuses(path: Path) -> dict:
    conn = db.connect(path)
    out = {r["quest_id"]: (r["status"], r["model"]) for r in conn.execute("SELECT * FROM summaries")}
    conn.close()
    return out


def _shipped(folder: Path) -> str:
    return (folder / "Data" / "MonkeDB.lua").read_text(encoding="utf-8")


# ---------------------------------------------------------------- committed summaries carry a stamp


def test_committed_summaries_apply_only_to_the_quest_they_were_written_for(quiet_dirs: Path, capsys) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    conn = db.connect(path)
    db.upsert_source_row(conn, db.QuestRow(id=9003, source="questie", title="Shrine Bauble",
                                           objectives_text="Take the Shrine Bauble to Tajarri.",
                                           turnin_npc="Tajarri", turnin_kind="other"))
    db.replace_objectives(conn, 9003, [db.Objective(9003, 1, "item", None, "Shrine Bauble", 1, "default",
                                                    None, "questie")])
    db.resolve_quests(conn)
    conn.close()
    written_for = _stamp(path, 9003)
    # Then the quest changed: the bauble is an object to use now. The old summary still
    # passes the validator, which is exactly why the stamp has to catch it.
    conn = db.connect(path)
    db.replace_objectives(conn, 9003, [db.Objective(9003, 1, "object", None, "Shrine Bauble", 1, "default",
                                                    None, "questie")])
    conn.commit()
    conn.close()
    old_npc = {**_stamp(path, 9002), "context_hash": "0123456789abcdef"}  # written when Old Pell took it in
    _commit(quiet_dirs / "summaries", "2026-09.jsonl",
            _line(9001, "Farmer Bo", "Farmer Bo hate rats.", _stamp(path, 9001)),
            _line(9002, "Old Pell", "Wolves bad.", old_npc),
            _line(9003, "Tajarri", "Monke carry Shrine Bauble to Tajarri.", written_for,
                  tasks=["Grab Shrine Bauble.", "Go see Tajarri."]))

    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert "written for another version of the quest: 2 quests" in capsys.readouterr().out
    assert _statuses(path) == {9001: ("ok", "file:2026-09.jsonl")}  # the stale ones are not even rejected
    assert cli.main(["--db", str(path), "export", "--build", "b"]) == 0
    assert 'l = "Farmer Bo hate rats."' in _shipped(quiet_dirs)
    bauble = next(line for line in _shipped(quiet_dirs).splitlines() if "[9003]" in line)
    assert "l = " not in bauble and "Grab Shrine Bauble." not in bauble  # rule-based tasks instead
    out = quiet_dirs / "requests.jsonl"
    assert cli.main(["--db", str(path), "requests", "--out", str(out)]) == 0
    assert [json.loads(r)["id"] for r in out.read_text(encoding="utf-8").splitlines()] == [9002, 9003]


def test_an_unstamped_committed_line_waits_for_check_to_stamp_it(quiet_dirs: Path, capsys) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    committed = _commit(quiet_dirs / "summaries", "2026-11.jsonl",
                        _line(9001, "Farmer Bo", "Farmer Bo hate rats."),
                        _line(9002, "Old Pell", "Wolves bad."))
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert "no stamp: 2 quests" in capsys.readouterr().out
    assert _statuses(path) == {}

    assert cli.main(["--db", str(path), "check", "--summaries-file", str(committed), "--stamp"]) == 1  # 9002 fails
    lines = [json.loads(r) for r in committed.read_text(encoding="utf-8").splitlines()]
    assert list(lines[0])[:4] == ["id", *STAMP_KEYS]
    assert {k: lines[0][k] for k in STAMP_KEYS} == _stamp(path, 9001)
    assert lines[0]["lore_monke"] == "Farmer Bo hate rats."
    assert "context_hash" not in lines[1]  # it failed, so it stays unstamped
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert _statuses(path) == {9001: ("ok", "file:2026-11.jsonl")}


def test_a_new_prompt_version_never_reuses_lines_written_for_another(quiet_dirs: Path, monkeypatch, paid) -> None:
    prompts = quiet_dirs / "prompts"
    prompts.mkdir()
    for version in ("v1", "v2"):
        (prompts / f"{version}.md").write_text(summarize.load_prompt("v1"), encoding="utf-8")
    monkeypatch.setattr(summarize, "PROMPTS_DIR", prompts)
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    _commit(quiet_dirs / "summaries", "2026-09.jsonl",
            _line(9001, "Farmer Bo", "Written with v1.", _stamp(path, 9001)))
    assert cli.main(["--db", str(path), "summarize", "--provider", "batch", "--prompt-version", "v2",
                     "--ids", "9001"]) == 0
    assert paid == [9001]
    conn = db.connect(path)
    rows = [(r["prompt_version"], r["model"], json.loads(r["json"])["lore_monke"])
            for r in conn.execute("SELECT * FROM summaries")]
    conn.close()
    assert rows == [("v2", "paid-fake", "Paid monke.")]


# ---------------------------------------------------------------- rejected rows are not sticky


def test_a_fix_committed_later_replaces_a_rejected_summary(quiet_dirs: Path) -> None:
    """README, updating from a new release: run, have the rejected ones rewritten, commit, run."""
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    stamp = _stamp(path, 9002)
    folder = quiet_dirs / "summaries"
    _commit(folder, "2026-10_v1.0.6.jsonl", _line(9002, "Old Pell", "Wolves bad.", stamp))  # a writer's slip
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert _statuses(path)[9002][0] == "rejected"
    _commit(folder, "2026-11_v1.0.7.jsonl", _line(9002, "Ranger Pell", "Wolves bad, Ranger Pell say.", stamp))
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert _statuses(path)[9002] == ("ok", "file:2026-11_v1.0.7.jsonl")
    assert cli.main(["--db", str(path), "export", "--build", "b"]) == 0
    assert 'l = "Wolves bad, Ranger Pell say."' in _shipped(quiet_dirs)


def test_retry_rejected_with_a_paid_provider_skips_the_committed_text(quiet_dirs: Path, paid) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    _commit(quiet_dirs / "summaries", "2026-10.jsonl",
            _line(9001, "Farmer Bo", "Farmer Bo hate rats.", _stamp(path, 9001)),
            _line(9002, "Old Pell", "Wolves bad.", _stamp(path, 9002)))
    assert cli.main(["--db", str(path), "summarize", "--provider", "batch"]) == 0
    assert paid == [] and _statuses(path)[9002][0] == "rejected"  # not paid for unasked...
    assert cli.main(["--db", str(path), "summarize", "--provider", "batch", "--retry-rejected"]) == 0
    assert paid == [9002]  # ...but asked for, it reaches the provider instead of the same old text
    assert _statuses(path) == {9001: ("ok", "file:2026-10.jsonl"), 9002: ("ok", "paid-fake")}
    assert cli.main(["--db", str(path), "summarize"]) == 0  # a later plain run keeps what was paid for
    assert _statuses(path)[9002] == ("ok", "paid-fake")


# ---------------------------------------------------------------- --limit and --ids, the lore guard


@pytest.mark.parametrize("flags", [["--limit", "2"], ["--ids", "9001"]])
def test_limit_and_ids_never_cap_the_committed_summaries(quiet_dirs: Path, paid, flags) -> None:
    path = quiet_dirs / "db.sqlite"
    conn = db.connect(path)
    for i in range(6):
        db.upsert_source_row(conn, db.QuestRow(id=9001 + i, source="questie_forever", title=f"Q{i}",
                                               objectives_text=f"Talk to Npc{i}.", turnin_npc=f"Npc{i}",
                                               turnin_kind="giver"))
    db.resolve_quests(conn)
    conn.close()
    _commit(quiet_dirs / "summaries", "2026-10.jsonl",
            *[_line(9001 + i, f"Npc{i}", f"Committed {i}.", _stamp(path, 9001 + i)) for i in range(6)])
    assert cli.main(["--db", str(path), "summarize", "--provider", "batch", *flags]) == 0
    assert paid == []  # all six were covered for free
    assert sorted(_statuses(path)) == list(range(9001, 9007))


def test_export_refuses_to_lose_much_lore_unless_forced(quiet_dirs: Path, capsys) -> None:
    path = quiet_dirs / "db.sqlite"
    conn = db.connect(path)
    for i in range(10):
        db.upsert_source_row(conn, db.QuestRow(id=9001 + i, source="questie_forever", title=f"Q{i}",
                                               objectives_text=f"Talk to Npc{i}.", turnin_npc=f"Npc{i}"))
    db.resolve_quests(conn)
    for quest in conn.execute("SELECT * FROM quests").fetchall():
        summary = {"lore_monke": "Talk.", "lore_plain": "Talk.", "tasks": [f"Go back to {quest['turnin_npc']}."],
                   "group_line": None}
        summarize.save_summary(conn, quest["id"], quest["text_hash"], "v1", model="test",
                               summary_json=json.dumps(summary), status="ok", errors=[], attempts=1,
                               context_hash=validate.load_context(conn, quest).fingerprint())
    conn.commit()
    conn.close()
    assert cli.main(["--db", str(path), "export", "--build", "b"]) == 0  # ships 10 records with lore

    def drop_lore(below: int) -> None:
        conn = db.connect(path)
        conn.execute("DELETE FROM summaries WHERE quest_id >= ?", (below,))
        conn.commit()
        conn.close()

    drop_lore(9010)  # one of ten: a normal day after a release
    assert cli.main(["--db", str(path), "export", "--build", "b"]) == 0
    drop_lore(9003)  # seven of nine: --limit, a missing folder, every stamp stale
    capsys.readouterr()
    assert cli.main(["--db", str(path), "export", "--build", "b"]) == 1
    out = capsys.readouterr().out
    assert "refusing to export" in out and "2 records with lore against 9 shipped" in out
    assert _shipped(quiet_dirs).count(" l = ") == 9  # untouched
    assert cli.main(["--db", str(path), "export", "--build", "b", "--force"]) == 0
    assert _shipped(quiet_dirs).count(" l = ") == 2


# ---------------------------------------------------------------- several committed files


def test_a_later_release_file_wins_in_version_order_not_name_order(quiet_dirs: Path) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    stamp = _stamp(path, 9001)
    folder = quiet_dirs / "summaries"
    _commit(folder, "2026-10_questiedb-v1.0.10.jsonl", _line(9001, "Farmer Bo", "From v1.0.10.", stamp))
    _commit(folder, "2026-10_questiedb-v1.0.6.jsonl", _line(9001, "Farmer Bo", "From v1.0.6.", stamp))
    assert [p.name for p in cli._summary_files([str(folder)])] == [
        "2026-10_questiedb-v1.0.6.jsonl", "2026-10_questiedb-v1.0.10.jsonl"]
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert _statuses(path)[9001] == ("ok", "file:2026-10_questiedb-v1.0.10.jsonl")


def test_every_committed_summary_line_is_stamped() -> None:
    """An unstamped line is never applied: in the repository it is lore nobody can ship."""
    files = sorted(cli.SUMMARIES_DIR.glob("*.jsonl"))
    assert files
    for path in files:
        for number, _quest_id, record in providers.iter_summary_lines(path):
            assert providers.stamp_of(record, f"{path.name}:{number}: ") is not None, f"{path.name}:{number}"


# ---------------------------------------------------------------- requests and check


def test_requests_carry_the_stamp_and_include_rows_whose_quest_changed(quiet_dirs: Path) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    conn = db.connect(path)
    quest = conn.execute("SELECT * FROM quests WHERE id = 9001").fetchone()
    # An ok row written before the quest's objectives changed: same text, other context.
    summarize.save_summary(conn, 9001, quest["text_hash"], "v1", model="file:old.jsonl", summary_json="{}",
                           status="ok", errors=[], attempts=1, context_hash="0123456789abcdef")
    conn.commit()
    conn.close()
    out = quiet_dirs / "requests.jsonl"
    assert cli.main(["--db", str(path), "requests", "--out", str(out)]) == 0
    records = {r["id"]: r for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
    assert sorted(records) == [9001, 9002]  # the export would not ship 9001's row, so it is asked again
    assert {k: records[9002][k] for k in STAMP_KEYS} == _stamp(path, 9002)


def test_check_refuses_a_line_written_for_another_version_of_the_quest(quiet_dirs: Path, capsys) -> None:
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    good = _commit(quiet_dirs, "good.jsonl", _line(9001, "Farmer Bo", "Farmer Bo hate rats.", _stamp(path, 9001)))
    other_text = {**_stamp(path, 9001), "text_hash": "0123456789abcdef"}
    stale = _commit(quiet_dirs, "stale.jsonl", _line(9001, "Farmer Bo", "Farmer Bo hate rats.", other_text))
    assert cli.main(["--db", str(path), "check", "--summaries-file", str(good)]) == 0
    capsys.readouterr()
    assert cli.main(["--db", str(path), "check", "--summaries-file", str(stale)]) == 1
    failure = json.loads(capsys.readouterr().out.splitlines()[0])
    assert failure["id"] == 9001 and "another version of the quest" in failure["errors"][0]
    assert "quest text" in failure["errors"][0]  # and says what changed


def test_check_out_writes_the_file_to_commit(quiet_dirs: Path, capsys) -> None:
    """Drafts plus an editor's fixes in, one stamped line per passing quest out."""
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    drafts = _commit(quiet_dirs / "translate", "out.jsonl",
                     _line(9001, "Farmer Bo", "Farmer Bo hate rats."), _line(9002, "Old Pell", "Wolves bad."))
    fixes = _commit(quiet_dirs / "translate", "fix.jsonl", _line(9002, "Ranger Pell", "Wolves bad, Ranger Pell say."))
    out = quiet_dirs / "summaries" / "2026-11_v1.0.7.jsonl"
    assert cli.main(["--db", str(path), "check", "--summaries-file", str(drafts), "--summaries-file", str(fixes),
                     "--out", str(out)]) == 0
    written = [json.loads(r) for r in out.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in written] == [9001, 9002]
    assert written[1]["lore_monke"] == "Wolves bad, Ranger Pell say."  # the fix, not the draft
    assert all({k: r[k] for k in STAMP_KEYS} == _stamp(path, r["id"]) for r in written)
    assert "context_hash" not in drafts.read_text(encoding="utf-8")  # the inputs are left alone
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert _statuses(path) == {9001: ("ok", f"file:{out.name}"), 9002: ("ok", f"file:{out.name}")}


def test_the_flow_for_a_changed_quest_ends_with_its_new_summary_shipped(quiet_dirs: Path) -> None:
    """README: run; `requests` for what changed; a writer answers; `check`; commit; run."""
    path = quiet_dirs / "db.sqlite"
    _farm_db(path)
    folder = quiet_dirs / "summaries"
    old = {**_stamp(path, 9002), "context_hash": "0123456789abcdef"}  # before the turn-in NPC changed
    _commit(folder, "2026-10_v1.0.6.jsonl", _line(9002, "Old Pell", "Wolves bad.", old))
    assert cli.main(["--db", str(path), "summarize"]) == 0
    requests = quiet_dirs / "requests.jsonl"
    assert cli.main(["--db", str(path), "requests", "--out", str(requests)]) == 0
    records = {r["id"]: r for r in map(json.loads, requests.read_text(encoding="utf-8").splitlines())}
    record = records[9002]  # 9001 is there too: nothing was ever written for it
    assert "Ranger Pell" in record["request"]
    answer = _commit(quiet_dirs, "answer.jsonl",  # the writer copies the stamp from the request
                     _line(9002, "Ranger Pell", "Wolves bad, Ranger Pell say.", {k: record[k] for k in STAMP_KEYS}))
    assert cli.main(["--db", str(path), "check", "--summaries-file", str(answer)]) == 0
    (folder / "2026-11_v1.0.7.jsonl").write_bytes(answer.read_bytes())
    assert cli.main(["--db", str(path), "summarize"]) == 0
    assert cli.main(["--db", str(path), "export", "--build", "b"]) == 0
    assert 'l = "Wolves bad, Ranger Pell say."' in _shipped(quiet_dirs)


# ---------------------------------------------------------------- the older rails


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

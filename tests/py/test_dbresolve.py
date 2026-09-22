"""db.resolve_quests: which source wins, how gaps are filled, and what gets logged."""

from pipeline import db


def _row(quest_id, source, fetched_at="2026-09-01T00:00:00Z", **text):
    return db.QuestRow(id=quest_id, source=source, fetched_at=fetched_at, **text)


def _quest(conn, quest_id):
    return conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()


def test_lower_priority_number_wins():
    conn = db.connect()
    db.upsert_source_row(conn, _row(214, "questie", title="Red Silk Bandanas", objectives_text="Bring 10."))
    db.upsert_source_row(conn, _row(214, "wowforevertalents", title="Red Silk Bandanas",
                                    objectives_text="Bring 12.", detail="Web detail."))
    stats = db.resolve_quests(conn)
    quest = _quest(conn, 214)
    assert quest["source"] == "wowforevertalents"
    assert quest["objectives_text"] == "Bring 12."
    assert quest["detail"] == "Web detail."
    assert stats["quests"] == 1


def test_insert_order_does_not_matter():
    conn = db.connect()
    db.upsert_source_row(conn, _row(7, "wowforevertalents", title="Web"))
    db.upsert_source_row(conn, _row(7, "questie", title="Questie", fetched_at="2026-09-20T00:00:00Z"))
    db.resolve_quests(conn)
    assert _quest(conn, 7)["source"] == "wowforevertalents"  # priority beats a newer fetch


def test_newest_fetch_wins_within_one_priority():
    conn = db.connect()
    db.upsert_source_row(conn, _row(5, "questie", "2026-09-01T00:00:00Z", title="Old wording"))
    db.upsert_source_row(conn, _row(5, "questie_forever", "2026-09-15T00:00:00Z", title="New wording"))
    db.resolve_quests(conn)
    quest = _quest(conn, 5)
    assert (quest["source"], quest["title"], quest["fetched_at"]) == (
        "questie_forever", "New wording", "2026-09-15T00:00:00Z")

    # An unknown source counts as a Forever web source (priority 1), also newest first.
    db.upsert_source_row(conn, _row(5, "some_new_site", "2026-09-10T00:00:00Z", title="Site A"))
    db.upsert_source_row(conn, _row(5, "wowforevertalents", "2026-09-12T00:00:00Z", title="Site B"))
    db.resolve_quests(conn)
    assert _quest(conn, 5)["source"] == "wowforevertalents"


def test_missing_fields_are_filled_from_the_next_source():
    conn = db.connect()
    db.upsert_source_row(conn, _row(9, "wowforevertalents", title="The Lantern", detail="Long text."))
    db.upsert_source_row(conn, _row(9, "questie", title="The Lantern", objectives_text="Find it.",
                                    turnin_npc="Keeper Odwin"))
    stats = db.resolve_quests(conn)
    quest = _quest(conn, 9)
    assert quest["source"] == "wowforevertalents"
    assert quest["detail"] == "Long text."
    assert quest["objectives_text"] == "Find it."      # filled from questie
    assert quest["turnin_npc"] == "Keeper Odwin"       # turn-in NPC is filled too
    assert quest["progress"] is None and quest["complete"] is None
    assert stats["filled_fields"] == 2 and stats["diffs"] == 0
    # The hash describes the merged text, so a newly filled field invalidates cached summaries.
    assert quest["text_hash"] == db.text_hash(dict(quest))
    web_only = conn.execute("SELECT text_hash FROM source_rows WHERE id = 9 AND source = 'wowforevertalents'")
    assert quest["text_hash"] != web_only.fetchone()[0]


def test_a_disagreement_is_logged_as_a_diff():
    conn = db.connect()
    db.upsert_source_row(conn, _row(214, "wowforevertalents", title="Red Silk Bandanas",
                                    objectives_text="Bring 12 bandanas."))
    db.upsert_source_row(conn, _row(214, "questie", title="Red  Silk\nBandanas ",
                                    objectives_text="Bring 10 bandanas."))
    stats = db.resolve_quests(conn)
    diffs = [tuple(d)[1:6] for d in conn.execute("SELECT * FROM text_diffs")]
    # The title differs only in whitespace: not a diff. The objectives really differ.
    assert diffs == [(214, "objectives_text", "wowforevertalents", "questie", "Bring 12 bandanas.")]
    assert stats["diffs"] == 1
    assert _quest(conn, 214)["objectives_text"] == "Bring 12 bandanas."

    db.resolve_quests(conn)  # rebuilding does not pile up duplicates
    assert conn.execute("SELECT COUNT(*) FROM text_diffs").fetchone()[0] == 1


def test_rows_without_any_text_never_become_quests():
    conn = db.connect()
    db.upsert_source_row(conn, _row(1, "questie", turnin_npc="Somebody"))
    db.upsert_source_row(conn, _row(2, "questie", title="  "))
    db.upsert_source_row(conn, _row(3, "questie", title="Real"))
    db.resolve_quests(conn)
    assert [r[0] for r in conn.execute("SELECT id FROM quests")] == [3]


def test_upsert_skips_unchanged_text_and_stores_null_not_empty():
    conn = db.connect()
    assert db.upsert_source_row(conn, _row(3, "questie", title="Same", detail="")) is True
    assert db.upsert_source_row(conn, _row(3, "questie", title=" Same ")) is False
    assert db.upsert_source_row(conn, _row(3, "questie", title="Same", turnin_npc="New NPC")) is True
    assert db.upsert_source_row(conn, _row(3, "questie", title="Changed", turnin_npc="New NPC")) is True
    stored = conn.execute("SELECT detail, title FROM source_rows WHERE id = 3").fetchone()
    assert stored["detail"] is None and stored["title"] == "Changed"


def test_db2_rows_keep_the_names_of_the_rows_they_replace():
    conn = db.connect()
    db.replace_objectives(conn, 9001, [
        db.Objective(9001, 1, "monster", 9201, "Gray Wolf", 8, "text", None, "questie"),
        db.Objective(9001, 2, "monster", 9202, "Ridge Stalker", 5, "text", "Ridge Stalkers hunted", "questie"),
    ])
    kept = db.replace_objectives(conn, 9001, [
        db.Objective(9001, 1, "monster", 9202, None, 6, "db2", None, "wago"),  # wago orders them differently
        db.Objective(9001, 2, "monster", 9201, None, 8, "db2", None, "wago"),
        db.Objective(9001, 3, "item", 9404, None, 1, "db2", None, "wago"),      # new, no name anywhere
    ])
    assert kept is True
    rows = [(o["idx"], o["target_name"], o["amount"], o["amount_source"], o["text"]) for o in db.get_objectives(conn, 9001)]
    assert rows == [(1, "Ridge Stalker", 6, "db2", "Ridge Stalkers hunted"), (2, "Gray Wolf", 8, "db2", None),
                    (3, None, 1, "db2", None)]
    # and a weaker source cannot undo db2 amounts
    assert db.replace_objectives(conn, 9001, [
        db.Objective(9001, 1, "monster", 9201, "Gray Wolf", 8, "text", None, "questie")]) is False
    assert db.get_objectives(conn, 9001)[0]["amount_source"] == "db2"


def test_amounts_follow_the_sentence_that_wins():
    from pipeline.sources.questie import infer_amounts

    conn = db.connect()
    db.upsert_source_row(conn, db.QuestRow(id=214, source="questie", title="Red Silk Bandanas",
                                           objectives_text="Bring her 10 Red Silk Bandanas.", fetched_at="2026-01-01T00:00:00Z"))
    db.replace_objectives(conn, 214, [db.Objective(214, 1, "item", 915, "Red Silk Bandana", 10, "text", None, "questie")])
    db.upsert_source_row(conn, db.QuestRow(id=214, source="wowforevertalents", title="Red Silk Bandanas",
                                           objectives_text="Scout Riell wants you to bring her 6 Red Silk Bandanas.",
                                           fetched_at="2026-02-01T00:00:00Z"))
    db.resolve_quests(conn)
    assert db.reconcile_amounts(conn, infer_amounts) == 1
    assert (db.get_objectives(conn, 214)[0]["amount"], db.get_objectives(conn, 214)[0]["amount_source"]) == (6, "text")
    assert db.reconcile_amounts(conn, infer_amounts) == 0  # settled

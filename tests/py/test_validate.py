"""One failing case and one passing twin per validator rule (contract section 6).

The plan's definition of done names five failure modes: counts, lore length and
sentences, invented directions and places, profanity, missing turn-in. They are
rules b-f below; a, g and h guard the shape and the game client's markup.
"""

from __future__ import annotations

import copy

import pytest

from pipeline import db
from pipeline.validate import QuestContext, count_sentences, load_context, validate


def ctx_214(**overrides) -> QuestContext:
    base = dict(
        id=214,
        title="Red Silk Bandanas",
        objectives_text=(
            "Scout Riell at the Sentinel Hill Tower wants you to bring her 10 Red Silk Bandanas."
        ),
        turnin_npc="Scout Riell",
        objectives=[{
            "type": "item", "target_name": "Red Silk Bandana", "amount": 10,
            "amount_source": "text", "text": None,
        }],
    )
    base.update(overrides)
    return QuestContext(**base)


def good() -> dict:
    return {
        "lore_monke": "Scout Riell want 10 Red Silk Bandanas. Monke go get.",
        "lore_plain": "Scout Riell at the Sentinel Hill Tower needs 10 Red Silk Bandanas.",
        "tasks": ["Grab 10 Red Silk Bandana.", "Go back to Scout Riell."],
        "group_line": None,
    }


def changed(**fields) -> dict:
    summary = copy.deepcopy(good())
    summary.update(fields)
    return summary


def errors_of(summary, ctx: QuestContext | None = None) -> str:
    return "\n".join(validate(summary, ctx or ctx_214()))


def test_good_summary_is_valid() -> None:
    assert validate(good(), ctx_214()) == []


# ---------------------------------------------------------------- a. shape


@pytest.mark.parametrize(
    ("summary", "fragment"),
    [
        ("not a dict", "one JSON object"),
        ({k: v for k, v in good().items() if k != "lore_plain"}, "Missing key 'lore_plain'"),
        (changed(mood="happy"), "Unknown key 'mood'"),
        (changed(lore_monke=7), "lore_monke must be a non-empty string"),
        (changed(lore_plain="  "), "lore_plain must be a non-empty string"),
        (changed(tasks=[]), "non-empty list"),
        (changed(tasks="Grab 10 Red Silk Bandana."), "non-empty list"),
        (changed(tasks=["Grab 10 Red Silk Bandana.", ""]), "non-empty string"),
        (changed(group_line=3), "group_line must be"),
        (changed(lore_monke="Monke go.\nMonke get."), "single line"),
    ],
)
def test_a_shape_rejected(summary, fragment: str) -> None:
    assert fragment in errors_of(summary)


def test_a_shape_accepts_string_group_line() -> None:
    assert validate(changed(group_line="Bring friends. Big danger."), ctx_214()) == []


# ---------------------------------------------------------------- b. counts


def test_b_wrong_number_rejected() -> None:
    errors = errors_of(changed(tasks=["Grab 100 Red Silk Bandana.", "Go back to Scout Riell."]))
    assert "tasks[1] must contain the number 10" in errors


def test_b_number_as_a_word_rejected() -> None:
    errors = errors_of(changed(tasks=["Grab ten Red Silk Bandana.", "Go back to Scout Riell."]))
    assert "the number 10" in errors


def test_b_too_few_tasks_rejected() -> None:
    assert "needs at least 2" in errors_of(changed(tasks=["Go back to Scout Riell."]))


def test_b_objective_order_matters() -> None:
    ctx = ctx_214(objectives=[
        {"type": "monster", "target_name": "Kobold Vermin", "amount": 8, "amount_source": "db2"},
        {"type": "item", "target_name": "Red Silk Bandana", "amount": 10, "amount_source": "text"},
    ])
    swapped = changed(tasks=[
        "Grab 10 Red Silk Bandana.", "Bonk 8 Kobold Vermin.", "Go back to Scout Riell.",
    ])
    ordered = changed(tasks=[
        "Bonk 8 Kobold Vermin.", "Grab 10 Red Silk Bandana.", "Go back to Scout Riell.",
    ])
    assert "tasks[1] must contain the number 8" in errors_of(swapped, ctx)
    assert "tasks[2] must contain the number 10" in errors_of(swapped, ctx)
    assert validate(ordered, ctx) == []


def test_b_default_amounts_are_not_enforced() -> None:
    ctx = ctx_214(objectives=[
        {"type": "item", "target_name": "Red Silk Bandana", "amount": 1, "amount_source": "default"},
    ])
    assert validate(good(), ctx) == []
    ctx.objectives[0]["amount"] = 5  # contradictory, but 'default' is never enforced
    assert validate(good(), ctx) == []


def test_b_no_turnin_npc_needs_one_task_fewer() -> None:
    ctx = ctx_214(turnin_npc=None, objectives_text="Bring 10 Red Silk Bandanas.")
    summary = changed(
        lore_monke="Monke need 10 Red Silk Bandanas.",
        lore_plain="Someone needs 10 Red Silk Bandanas.",
        tasks=["Grab 10 Red Silk Bandana."],
    )
    assert validate(summary, ctx) == []


# ---------------------------------------------------------------- c. lore length and sentences


def test_c_long_lore_rejected() -> None:
    long = "Scout Riell want bandanas " + "very " * 30 + "much."
    assert len(long) >= 160
    assert "it must be under 160" in errors_of(changed(lore_monke=long))


def test_c_three_sentences_rejected() -> None:
    errors = errors_of(changed(lore_plain="Scout Riell needs bandanas. Get 10. Bring them back."))
    assert "lore_plain has 3 sentences" in errors


def test_c_two_sentences_with_ellipsis_and_abbreviation_pass() -> None:
    summary = changed(lore_monke="Scout Riell want... bandanas! Monke go get.")
    assert validate(summary, ctx_214()) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ooga. Booga!", 2),
        ("Ooga booga", 1),
        ("Monke wait... then monke go.", 1),
        ("Monke wait… then monke go.", 1),
        ("Dr. Boom wants 1.5 bananas.", 1),
        ("Ask J. R. Smith. Then run!", 2),
        ('He said "go." Then he left.', 2),
        ("What?! No way. Fine.", 3),
        ("", 0),
    ],
)
def test_c_count_sentences(text: str, expected: int) -> None:
    assert count_sentences(text) == expected


# ---------------------------------------------------------------- d. invented directions, places


def test_d_invented_direction_rejected() -> None:
    errors = errors_of(changed(lore_plain="Scout Riell, north of here, needs 10 Red Silk Bandanas."))
    assert "direction 'north'" in errors


@pytest.mark.parametrize("word", ["southeast", "Northern", "westward", "south-west", "eastbound"])
def test_d_direction_variants_rejected(word: str) -> None:
    assert "direction" in errors_of(changed(lore_monke=f"Monke walk {word} for bandanas."))


def test_d_direction_from_source_passes() -> None:
    ctx = ctx_214(detail="The Defias hide in the hills to the north. Take their bandanas.")
    summary = changed(lore_monke="Bad men hide north. Monke take bandanas.")
    assert validate(summary, ctx) == []
    # 'northern' is a different claim from 'north' and is still rejected.
    assert "direction" in errors_of(changed(lore_monke="Bad men in northern hills."), ctx)


def test_d_place_names_inside_words_are_not_directions() -> None:
    ctx = ctx_214(detail="The Defias in Westfall wear them.")
    assert validate(changed(lore_plain="The Defias in Westfall wear Red Silk Bandanas."), ctx) == []


def test_d_invented_place_rejected() -> None:
    errors = errors_of(changed(lore_monke="Scout Riell want bandanas from Stormwind."))
    assert "Stormwind" in errors
    assert "not in the quest text" in errors


def test_d_capitals_for_emphasis_rejected() -> None:
    assert "BIG" in errors_of(changed(lore_monke="Scout Riell want BIG pile of bandanas."))


def test_d_known_names_voice_words_and_sentence_starts_pass() -> None:
    summary = changed(
        lore_monke="Tower lady Riell want bandanas. Monke say: Ape help, and Monke get shiny.",
        tasks=["Grab 10 Red Silk Bandana.", "Hint: Defias wear them.", "Go back to Scout Riell."],
    )
    ctx = ctx_214(detail="The Defias wear them.")
    assert validate(summary, ctx) == []


def test_d_plural_added_or_dropped_by_the_model_passes() -> None:
    ctx = ctx_214(objectives=[{
        "type": "monster", "target_name": "Defias Pillager", "amount": 10, "amount_source": "db2",
    }])
    summary = changed(
        lore_plain="Scout Riell wants 10 Defias Pillagers gone and their Bandana taken.",
        tasks=["Bonk 10 Defias Pillagers.", "Go back to Scout Riell."],
    )
    assert validate(summary, ctx) == []


# ---------------------------------------------------------------- e. profanity


@pytest.mark.parametrize("word", ["damn", "butt", "Shit", "asses", "idiot"])
def test_e_profanity_rejected(word: str) -> None:
    errors = errors_of(changed(lore_monke=f"Scout Riell want {word} bandanas."))
    assert "not PG" in errors
    assert word in errors


def test_e_allowlisted_and_lookalike_words_pass() -> None:
    summary = changed(
        lore_monke="Monke bonk and smash for bandanas. Monke pass class with grass and spices.",
    )
    assert validate(summary, ctx_214()) == []


def test_e_game_supplied_names_are_not_our_profanity() -> None:
    ctx = ctx_214(turnin_npc="Dirty Dick", objectives_text="Bring Dirty Dick 10 Red Silk Bandanas.")
    summary = changed(
        lore_monke="Dirty Dick want 10 Red Silk Bandanas.",
        lore_plain="Dirty Dick needs 10 Red Silk Bandanas.",
        tasks=["Grab 10 Red Silk Bandana.", "Go back to Dirty Dick."],
    )
    assert validate(summary, ctx) == []


# ---------------------------------------------------------------- f. turn-in


def test_f_missing_turnin_rejected() -> None:
    errors = errors_of(changed(tasks=["Grab 10 Red Silk Bandana.", "Go back. Get shiny."]))
    assert "turn-in NPC 'Scout Riell'" in errors


def test_f_turnin_not_last_rejected() -> None:
    tasks = ["Grab 10 Red Silk Bandana.", "Go back to Scout Riell.", "Hint: look on Defias."]
    ctx = ctx_214(detail="Defias wear them.")
    assert "last entry of tasks" in errors_of(changed(tasks=tasks), ctx)


def test_f_turnin_is_case_insensitive() -> None:
    summary = changed(tasks=["Grab 10 Red Silk Bandana.", "Go back to scout riell."])
    assert validate(summary, ctx_214()) == []


# ---------------------------------------------------------------- g. placeholders and UI codes


@pytest.mark.parametrize("text", ["Hello $n, get bandanas.", "Brave $c get bandanas.",
                                  "Get bandanas, $gsir:madam;.", "Get bandanas.$b"])
def test_g_placeholders_rejected(text: str) -> None:
    assert "placeholder" in errors_of(changed(lore_plain=text))


@pytest.mark.parametrize("text", ["|cffff0000Grab|r 10 Red Silk Bandana.",
                                  "Grab 10 |Hitem:1|hRed Silk Bandana|h.",
                                  "Grab 10 Red Silk Bandana.|n"])
def test_g_ui_escape_codes_rejected(text: str) -> None:
    assert "UI escape code" in errors_of(changed(tasks=[text, "Go back to Scout Riell."]))


def test_g_dollar_amounts_pass() -> None:
    assert validate(changed(lore_monke="Scout Riell pay $5 for bandanas."), ctx_214()) == []


# ---------------------------------------------------------------- h. task format


@pytest.mark.parametrize("task", ["Grab 10 Red Silk Bandana (3/10).", "Grab Red Silk Bandana 0/10."])
def test_h_progress_counts_rejected(task: str) -> None:
    assert "progress count" in errors_of(changed(tasks=[task, "Go back to Scout Riell."]))


@pytest.mark.parametrize("task", ["- Grab 10 Red Silk Bandana.", "• Grab 10 Red Silk Bandana.",
                                  "* Grab 10 Red Silk Bandana.", "1. Grab 10 Red Silk Bandana."])
def test_h_bullets_rejected(task: str) -> None:
    assert "bullet" in errors_of(changed(tasks=[task, "Go back to Scout Riell."]))


def test_h_task_starting_with_its_number_passes() -> None:
    summary = changed(tasks=["10 Red Silk Bandana. Grab.", "Go back to Scout Riell."])
    assert validate(summary, ctx_214()) == []


# ---------------------------------------------------------------- context


def test_source_text_joins_prose_and_names() -> None:
    ctx = ctx_214(detail="Detail.", progress="Progress?", complete="Complete!")
    text = ctx.source_text()
    for part in ("Red Silk Bandanas", "Detail.", "Sentinel Hill", "Progress?", "Complete!",
                 "Red Silk Bandana", "Scout Riell"):
        assert part in text


def test_load_context_from_db() -> None:
    conn = db.connect()
    db.upsert_source_row(conn, db.QuestRow(
        id=214, source="questie", title="Red Silk Bandanas",
        objectives_text="Bring 10 Red Silk Bandanas to Scout Riell.", turnin_npc="Scout Riell",
    ))
    db.replace_objectives(conn, 214, [db.Objective(
        quest_id=214, idx=1, type="item", target_name="Red Silk Bandana", amount=10,
        amount_source="text", source="questie",
    )])
    db.upsert_meta(conn, 214, "questie", group_size=3, tag="Elite")
    db.resolve_quests(conn)
    ctx = load_context(conn, 214)
    assert (ctx.title, ctx.turnin_npc, ctx.group_size, ctx.tag) == (
        "Red Silk Bandanas", "Scout Riell", 3, "Elite",
    )
    assert ctx.objectives[0]["amount"] == 10
    assert ctx.has_prose()
    with pytest.raises(KeyError):
        load_context(conn, 999)


# ---------------------------------------------------------------- false rejections seen on real quests


def _ctx(**kwargs) -> QuestContext:
    base = dict(id=1, title="A Quest", objectives_text="Do the thing.", turnin_npc="Bob", objectives=[])
    base.update(kwargs)
    return QuestContext(**base)


def _summary(lore: str, tasks: list[str] | None = None) -> dict:
    return {"lore_monke": lore, "lore_plain": lore, "tasks": tasks or ["Go back to Bob."], "group_line": None}


def test_a_full_stop_inside_a_game_name_is_not_a_sentence_end() -> None:
    ctx = _ctx(objectives_text="Kill 14 Venture Co. Workers for Morin.", objectives=[
        {"type": "monster", "target_name": "Venture Co. Worker", "amount": 14, "amount_source": "text"}])
    lore = "Morin at the village wants 14 Venture Co. Workers killed."
    assert validate(_summary(lore, ["Bonk 14 Venture Co. Worker.", "Go back to Bob."]), ctx) == []


def test_a_blocklisted_word_that_is_part_of_a_game_name_passes() -> None:
    ctx = _ctx(title="The Temple", objectives_text="Speak with Godrick Farsan in the Temple of the Damned.",
               turnin_npc="Godrick Farsan")
    lore = "Godrick Farsan wait in Temple of the Damned. Monke go talk."
    assert validate(_summary(lore, ["Go back to Godrick Farsan."]), ctx) == []
    assert validate(_summary("These kobolds are damned annoying."), _ctx()) != []


def test_quoted_speech_may_start_with_a_capital() -> None:
    ctx = _ctx(objectives_text="Farmer Saldean wants 20 Harvest Watchers killed.", turnin_npc="Farmer Saldean")
    lore = 'Farmer Saldean say "Please kill 20 Harvest Watchers." Monke bonk!'
    assert validate(_summary(lore, ["Go back to Farmer Saldean."]), ctx) == []


def test_no_as_a_word_is_not_an_abbreviation() -> None:
    lore = "Kobolds say no. Monke bonk 10 Kobold Vermin. Bob happy."
    assert any("3 sentences" in e for e in validate(_summary(lore), _ctx()))


@pytest.mark.parametrize("task", [
    "Bonk 10 Kobold Vermin (0 of 10).", "Bonk 10 Kobold Vermin (0 out of 10).",
    "(1) Bonk 10 Kobold Vermin.", "1) Bonk 10 Kobold Vermin.", "a. Bonk 10 Kobold Vermin.",
    "[ ] Bonk 10 Kobold Vermin.", "\u2192 Bonk 10 Kobold Vermin.",
])
def test_more_progress_and_list_marker_shapes_are_rejected(task: str) -> None:
    ctx = _ctx(objectives=[{"type": "monster", "target_name": "Kobold Vermin", "amount": 10, "amount_source": "text"}])
    assert validate(_summary("Bonk kobolds.", [task, "Go back to Bob."]), ctx) != []
    assert validate(_summary("Bonk kobolds.", ["Bonk 10 Kobold Vermin.", "Go back to Bob."]), ctx) == []


def test_a_delivery_quest_must_not_say_go_back() -> None:
    ctx = _ctx(turnin_npc="Gryan Stoutmantle", turnin_kind="other",
               objectives_text="Take the note to Gryan Stoutmantle in Westfall.")
    ok = _summary("Bring the note to Gryan Stoutmantle.", ["Go see Gryan Stoutmantle."])
    assert validate(ok, ctx) == []
    bad = _summary("Bring the note to Gryan Stoutmantle.", ["Go back to Gryan Stoutmantle."])
    assert any("Go see" in e for e in validate(bad, ctx))
    giver = _ctx(turnin_npc="Gryan Stoutmantle", turnin_kind="giver",
                 objectives_text="Take the note to Gryan Stoutmantle in Westfall.")
    assert validate(bad, giver) == []

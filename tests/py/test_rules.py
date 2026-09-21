"""Rule-based bullets must match the addon's Rules.lua templates word for word."""

from __future__ import annotations

import pytest

from pipeline import db, rules


def obj(type_: str, name: str | None = None, amount: int = 1, text: str | None = None) -> dict:
    return {"type": type_, "target_name": name, "amount": amount, "text": text}


@pytest.mark.parametrize(
    ("objective", "monke", "plain"),
    [
        (obj("monster", "Kobold Vermin", 8), "Bonk 8 Kobold Vermin.", "Kill 8 Kobold Vermin."),
        (obj("monster", "Hogger"), "Bonk Hogger.", "Kill Hogger."),
        (obj("item", "Red Silk Bandana", 10), "Grab 10 Red Silk Bandana.", "Collect 10 Red Silk Bandana."),
        (obj("item", "Dusty Tome"), "Grab Dusty Tome.", "Collect Dusty Tome."),
        (obj("object", "Old Lever"), "Poke Old Lever.", "Use Old Lever."),
        (obj("object", "Rune Stone", 3), "Poke 3 Rune Stone.", "Use 3 Rune Stone."),
        (
            obj("event", text="Scout the old mine"),
            "Do the thing: Scout the old mine.",
            "Scout the old mine.",
        ),
        (obj("spell", "Holy Light"), "Do the thing: Holy Light.", "Holy Light."),
        (obj("reputation", "Argent Dawn"), "Make Argent Dawn like ape.", "Earn reputation with Argent Dawn."),
        (
            obj("reputation", "Argent Dawn", text="Reach honored with the Argent Dawn"),
            "Make Argent Dawn like ape.",
            "Reach Honored with Argent Dawn.",
        ),
    ],
)
def test_task_templates(objective: dict, monke: str, plain: str) -> None:
    assert rules.task_for(objective, "monke") == monke
    assert rules.task_for(objective, "plain") == plain


@pytest.mark.parametrize("kind", ["event", "spell", "log", "player", "progressbar"])
def test_text_types_do_not_double_the_full_stop(kind: str) -> None:
    objective = obj(kind, text="Escort the caravan to safety.")
    assert rules.task_for(objective, "monke") == "Do the thing: Escort the caravan to safety."
    assert rules.task_for(objective, "plain") == "Escort the caravan to safety."


def test_question_and_exclamation_marks_are_kept() -> None:
    assert rules.task_for(obj("event", text="Survive!"), "plain") == "Survive!"


def test_nameless_objective_falls_back_to_text_then_generic() -> None:
    assert rules.task_for(obj("monster", text="Defeat the raiders"), "monke") == (
        "Do the thing: Defeat the raiders."
    )
    assert rules.task_for(obj("monster"), "monke") == "Do the quest thing."
    assert rules.task_for(obj("monster"), "plain") == "Complete the objective."


def test_names_are_never_pluralised() -> None:
    assert rules.task_for(obj("monster", "Defias Thug", 12), "monke") == "Bonk 12 Defias Thug."


def test_tasks_for_orders_objectives_then_turnin() -> None:
    objectives = [obj("monster", "Kobold Vermin", 8), obj("item", "Red Silk Bandana", 10)]
    assert rules.tasks_for(objectives, "Scout Riell", "monke") == [
        "Bonk 8 Kobold Vermin.",
        "Grab 10 Red Silk Bandana.",
        "Go back to Scout Riell.",
    ]
    assert rules.tasks_for(objectives, "Scout Riell", "plain")[-1] == "Return to Scout Riell."


def test_turnin_without_npc_is_generic() -> None:
    assert rules.tasks_for([], None, "monke") == ["Go back. Get shiny."]
    assert rules.tasks_for([], None, "plain") == ["Turn in the quest."]


def test_accepts_dataclass_and_sqlite_rows() -> None:
    conn = db.connect()
    objective = db.Objective(
        quest_id=214, idx=1, type="item", target_name="Red Silk Bandana", amount=10,
        amount_source="text", source="test",
    )
    db.replace_objectives(conn, 214, [objective])
    row = db.get_objectives(conn, 214)[0]
    assert rules.task_for(objective, "monke") == "Grab 10 Red Silk Bandana."
    assert rules.task_for(row, "monke") == "Grab 10 Red Silk Bandana."


def test_group_line() -> None:
    assert rules.group_line(3, None, "monke") == "Bring 2 friends. Big danger."
    assert rules.group_line(2, None, "monke") == "Bring a friend. Big danger."
    assert rules.group_line(3, "Elite", "plain") == "Suggested group: 3 players."
    assert rules.group_line(None, None, "monke") is None
    assert rules.group_line(1, None, "plain") is None
    assert rules.group_line(0, "Dungeon", "monke") == "Dungeon time. Bring friends."
    assert rules.group_line(None, "raid", "plain") == "Raid quest: bring a raid group."
    assert rules.group_line(None, "Elite", "monke") == "Big danger. Bring friends."
    assert rules.group_line(None, "PvP", "monke") is None


def test_unknown_voice_is_an_error() -> None:
    with pytest.raises(ValueError):
        rules.task_for(obj("monster", "Hogger"), "pirate")

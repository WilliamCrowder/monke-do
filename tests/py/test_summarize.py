"""summarize.run: caching, retry with feedback, overrides, providers. Never touches the network.

The Anthropic providers are exercised against a fake `anthropic` module injected into
sys.modules, which also proves the real package is only imported lazily.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pipeline import db
from pipeline.llm import providers, summarize
from pipeline.llm.providers import (
    AnthropicBatchProvider,
    AnthropicDirectProvider,
    FakeProvider,
    FileProvider,
    MissingDependencyError,
    ProviderError,
    SummaryRequest,
)
from pipeline.validate import SUMMARY_KEYS, QuestContext, load_context, validate

RIELL_TEXT = "Scout Riell at the Sentinel Hill Tower wants you to bring her 10 Red Silk Bandanas."


def add_quest(conn, quest_id: int, title: str, objectives_text: str | None, npc: str | None,
              objectives: list[tuple[str, str, int]] = (), detail: str | None = None) -> None:
    db.upsert_source_row(conn, db.QuestRow(
        id=quest_id, source="questie", title=title, detail=detail,
        objectives_text=objectives_text, turnin_npc=npc,
    ))
    db.replace_objectives(conn, quest_id, [
        db.Objective(quest_id=quest_id, idx=i, type=kind, target_name=name, amount=amount,
                     amount_source="text", source="questie")
        for i, (kind, name, amount) in enumerate(objectives, start=1)
    ])


def make_db():
    conn = db.connect()
    add_quest(conn, 7, "Kobold Camp Cleanup", "Kill 8 Kobold Vermin, then return to Marshal McBride.",
              "Marshal McBride", [("monster", "Kobold Vermin", 8)])
    add_quest(conn, 214, "Red Silk Bandanas", RIELL_TEXT, "Scout Riell",
              [("item", "Red Silk Bandana", 10)])
    add_quest(conn, 300, "Title Only", None, None)
    db.resolve_quests(conn)
    return conn


GOOD = {
    7: {"lore_monke": "Kobold Vermin make mess in camp. Monke clean up.",
        "lore_plain": "Marshal McBride wants the Kobold Vermin cleared out.",
        "tasks": ["Bonk 8 Kobold Vermin.", "Go back to Marshal McBride."], "group_line": None},
    214: {"lore_monke": "Scout Riell want 10 Red Silk Bandanas. Monke go get.",
          "lore_plain": "Scout Riell needs 10 Red Silk Bandanas.",
          "tasks": ["Grab 10 Red Silk Bandana.", "Go back to Scout Riell."], "group_line": None},
}
BAD_214 = {**GOOD[214], "tasks": ["Grab some Red Silk Bandana.", "Go back to Scout Riell."]}


def good_fn(request: SummaryRequest) -> str:
    return json.dumps(GOOD[request.quest_id])


@pytest.fixture
def no_overrides(tmp_path: Path) -> Path:
    path = tmp_path / "overrides.jsonl"
    path.write_text("", encoding="utf-8")
    return path


def run(conn, provider, overrides: Path, **kwargs) -> dict:
    kwargs.setdefault("log_path", None)
    return summarize.run(conn, provider, overrides_path=overrides, **kwargs)


def row(conn, quest_id: int):
    return conn.execute("SELECT * FROM summaries WHERE quest_id = ?", (quest_id,)).fetchone()


# ---------------------------------------------------------------- prompt and user message


def prompt_examples() -> list[tuple[str, dict]]:
    """(input block, output JSON) pairs from the Examples section of prompts/v1.md."""
    text = summarize.load_prompt("v1").split("## Examples", 1)[1]
    blocks = re.findall(r"```(json)?\n(.*?)\n```", text, flags=re.DOTALL)
    inputs = [body for lang, body in blocks if not lang]
    outputs = [json.loads(body) for lang, body in blocks if lang]
    assert len(inputs) == len(outputs) == 4
    return list(zip(inputs, outputs))


EXAMPLE_CONTEXTS = [
    QuestContext(id=214, title="Red Silk Bandanas", objectives_text=RIELL_TEXT,
                 turnin_npc="Scout Riell", objectives=[
                     {"type": "item", "target_name": "Red Silk Bandana", "amount": 10,
                      "amount_source": "text"}]),
    QuestContext(
        id=90377, title="Word for the Warden",
        objectives_text=("Take Halla's Note to Warden Ostrel at the river camp, and see that Sentinel "
                         "Shaya is patched up on the way."),
        turnin_npc="Warden Ostrel", turnin_kind="other", objectives=[
            {"type": "monster", "target_name": "Sentinel Shaya", "amount": 1,
             "amount_source": "default", "text": "Heal and fortify Sentinel Shaya"}]),
    QuestContext(
        id=90412, title="Trouble at the Old Mill",
        detail=("Those Mudsnout gnolls have overrun the old mill, $n. They chewed through every "
                "sack of grain we had, and their packleader Grawl wears my mill key around his "
                "neck. Thin their numbers and get me that key. Be careful, $c: Grawl never "
                "fights alone."),
        objectives_text=("Kill 12 Mudsnout Gnolls and recover the Mill Key from Packleader Grawl, "
                         "then return to Miller Hobb."),
        turnin_npc="Miller Hobb", group_size=3, tag="Elite", objectives=[
            {"type": "monster", "target_name": "Mudsnout Gnoll", "amount": 12, "amount_source": "db2"},
            {"type": "item", "target_name": "Mill Key", "amount": 1, "amount_source": "db2"}]),
    QuestContext(
        id=90518, title="The Signal Fire",
        objectives_text="Slay 6 Ridge Stalkers, then light the Signal Fire atop Watcher's Rise.",
        objectives=[
            {"type": "monster", "target_name": "Ridge Stalker", "amount": 1,
             "amount_source": "default"},
            {"type": "event", "text": "Light the Signal Fire", "amount": 1,
             "amount_source": "default"}]),
]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_prompt_examples_match_the_real_message_format_and_pass_the_validator(index: int) -> None:
    shown_input, shown_output = prompt_examples()[index]
    ctx = EXAMPLE_CONTEXTS[index]
    assert summarize.build_user_message(ctx) == shown_input
    assert validate(shown_output, ctx) == []


def test_prompt_is_long_enough_to_cache_and_names_every_rule() -> None:
    prompt = summarize.load_prompt("v1")
    # claude-sonnet-5 only caches prefixes of 1024+ tokens; ~4 characters per token.
    assert len(prompt) > 1024 * 5
    for needle in ("Bonk", "Grab", "Poke", "Do the thing:", "Make {faction} like ape.",
                   "Go back to {npc}.", "Go back. Get shiny.", "160", "ADHD", "$n", "|c"):
        assert needle in prompt
    with pytest.raises(FileNotFoundError):
        summarize.load_prompt("v999")


def test_user_message_includes_progress_complete_and_omits_group_when_solo() -> None:
    ctx = QuestContext(id=1, title="T", detail="D", objectives_text="O", progress="P",
                       complete="C", turnin_npc=None, group_size=1, tag=None)
    assert summarize.build_user_message(ctx) == (
        "Quest 1: T\nDetail: D\nObjectives text: O\nProgress: P\nComplete: C\n"
        "Structured objectives (0):\nTurn-in NPC: unknown"
    )
    ctx.tag = "Dungeon"
    assert summarize.build_user_message(ctx).endswith("Group: tag Dungeon")


# ---------------------------------------------------------------- run: cache, retry, reject


def test_second_run_makes_zero_provider_calls(no_overrides: Path) -> None:
    conn = make_db()
    provider = FakeProvider(good_fn)
    stats = run(conn, provider, no_overrides)
    assert (stats["ok"], stats["requested"], stats["rounds"]) == (2, 2, 1)
    assert stats["skipped_no_prose"] == 1
    assert len(provider.calls) == 1 and len(provider.calls[0]) == 2  # one batched call per round
    assert row(conn, 214)["status"] == "ok"
    assert json.loads(row(conn, 214)["json"]) == GOOD[214]
    assert row(conn, 214)["model"] == "fake"
    assert row(conn, 300) is None

    again = FakeProvider(good_fn)
    stats = run(conn, again, no_overrides)
    assert again.calls == []
    assert (stats["cached"], stats["requested"], stats["rounds"]) == (2, 0, 0)


def test_retry_feeds_validator_errors_and_previous_output_back(no_overrides: Path) -> None:
    conn = make_db()
    seen: list[SummaryRequest] = []

    def fn(request: SummaryRequest) -> str:
        seen.append(request)
        if request.quest_id == 214 and request.feedback is None:
            return json.dumps(BAD_214)
        return good_fn(request)

    provider = FakeProvider(fn)
    stats = run(conn, provider, no_overrides)
    assert (stats["ok"], stats["rounds"], stats["requested"]) == (2, 2, 3)
    assert [len(c) for c in provider.calls] == [2, 1]  # only the failed quest goes round again
    retry = seen[-1]
    assert retry.quest_id == 214
    assert retry.feedback.previous_output == json.dumps(BAD_214)
    assert any("must contain the number 10" in e for e in retry.feedback.errors)
    assert "must contain the number 10" in retry.content()
    assert json.dumps(BAD_214) in retry.content()
    assert retry.content().startswith(retry.user)  # the quest block stays first
    assert (row(conn, 214)["status"], row(conn, 214)["attempts"]) == ("ok", 2)
    assert row(conn, 7)["attempts"] == 1


def test_invalid_json_is_re_prompted(no_overrides: Path) -> None:
    conn = make_db()

    def fn(request: SummaryRequest) -> str:
        return "Sure! Here you go" if request.feedback is None else good_fn(request)

    provider = FakeProvider(fn)
    run(conn, provider, no_overrides, ids=[214])
    assert "not valid JSON" in provider.calls[1][0].feedback.errors[0]
    assert row(conn, 214)["status"] == "ok"


def test_rejected_after_max_retries_and_never_asked_again(no_overrides: Path) -> None:
    conn = make_db()
    provider = FakeProvider(lambda r: json.dumps(BAD_214))
    stats = run(conn, provider, no_overrides, ids=[214])
    assert (stats["rejected"], stats["rounds"], stats["requested"]) == (1, 3, 3)
    saved = row(conn, 214)
    assert (saved["status"], saved["attempts"]) == ("rejected", 3)
    assert any("number 10" in e for e in json.loads(saved["errors"]))
    assert json.loads(saved["json"]) == BAD_214

    again = FakeProvider(good_fn)
    assert run(conn, again, no_overrides, ids=[214])["cached"] == 1
    assert again.calls == []


def test_max_retries_zero_means_one_attempt(no_overrides: Path) -> None:
    conn = make_db()
    provider = FakeProvider(lambda r: json.dumps(BAD_214))
    run(conn, provider, no_overrides, ids=[214], max_retries=0)
    assert (row(conn, 214)["status"], row(conn, 214)["attempts"]) == ("rejected", 1)


def test_errors_retry_in_run_and_are_not_cached(no_overrides: Path) -> None:
    conn = make_db()
    attempts = {"n": 0}

    def flaky(request: SummaryRequest) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ProviderError("overloaded")
        return good_fn(request)

    run(conn, FakeProvider(flaky), no_overrides, ids=[214])
    assert (row(conn, 214)["status"], row(conn, 214)["attempts"]) == ("ok", 2)

    conn = make_db()
    fatal = FakeProvider(lambda r: ProviderError("bad request", retryable=False))
    stats = run(conn, fatal, no_overrides, ids=[214])
    assert (stats["error"], stats["rounds"]) == (1, 1)
    assert row(conn, 214)["status"] == "error"
    assert json.loads(row(conn, 214)["errors"]) == ["bad request"]

    healed = FakeProvider(good_fn)
    run(conn, healed, no_overrides, ids=[214])  # 'error' rows are asked again
    assert len(healed.calls) == 1
    assert row(conn, 214)["status"] == "ok"


def test_ids_and_limit_filters(no_overrides: Path) -> None:
    conn = make_db()
    provider = FakeProvider(good_fn)
    assert run(conn, provider, no_overrides, ids=[7])["requested"] == 1
    assert row(conn, 214) is None
    conn = make_db()
    assert run(conn, FakeProvider(good_fn), no_overrides, limit=1)["requested"] == 1
    assert row(conn, 7) is not None and row(conn, 214) is None


def test_changed_quest_text_is_a_new_cache_key(no_overrides: Path) -> None:
    conn = make_db()
    run(conn, FakeProvider(good_fn), no_overrides)
    add_quest(conn, 214, "Red Silk Bandanas", RIELL_TEXT + " Hurry.", "Scout Riell",
              [("item", "Red Silk Bandana", 10)])
    db.resolve_quests(conn)
    provider = FakeProvider(good_fn)
    stats = run(conn, provider, no_overrides)
    assert [r.quest_id for r in provider.calls[0]] == [214]
    assert stats["cached"] == 1


# ---------------------------------------------------------------- overrides


def write_override(path: Path, summary: dict, quest_id: int = 214) -> Path:
    path.write_text(json.dumps({"id": quest_id, **summary}) + "\n", encoding="utf-8")
    return path


def test_overrides_win_over_the_llm_and_over_the_cache(tmp_path: Path, no_overrides: Path) -> None:
    conn = make_db()
    run(conn, FakeProvider(good_fn), no_overrides)  # the LLM answer is cached as 'ok'
    pinned = {**GOOD[214], "lore_monke": "Riell want bandanas. Monke on it."}
    provider = FakeProvider(good_fn)
    stats = run(conn, provider, write_override(tmp_path / "o.jsonl", pinned))
    assert provider.calls == []
    assert stats["overrides"] == 1
    saved = row(conn, 214)
    assert (saved["status"], saved["model"], saved["attempts"]) == ("ok", "override", 0)
    assert json.loads(saved["json"])["lore_monke"] == "Riell want bandanas. Monke on it."


def test_override_is_never_requested_from_the_provider(tmp_path: Path) -> None:
    conn = make_db()
    provider = FakeProvider(good_fn)
    run(conn, provider, write_override(tmp_path / "o.jsonl", GOOD[214]))
    assert [r.quest_id for r in provider.calls[0]] == [7]


def test_invalid_override_is_a_hard_error_naming_the_quest(tmp_path: Path) -> None:
    conn = make_db()
    with pytest.raises(summarize.OverrideError, match=r"quest 214.*\n.*number 10"):
        run(conn, FakeProvider(good_fn), write_override(tmp_path / "o.jsonl", BAD_214))


def test_removed_override_hands_the_quest_back_to_the_llm(tmp_path: Path, no_overrides: Path) -> None:
    conn = make_db()
    run(conn, FakeProvider(good_fn), write_override(tmp_path / "o.jsonl", GOOD[214]))
    provider = FakeProvider(good_fn)
    run(conn, provider, no_overrides)
    assert [r.quest_id for r in provider.calls[0]] == [214]
    assert row(conn, 214)["model"] == "fake"


def test_override_for_unknown_quest_is_ignored_and_duplicates_are_errors(tmp_path: Path) -> None:
    conn = make_db()
    path = write_override(tmp_path / "o.jsonl", GOOD[214], quest_id=99999)
    assert summarize.apply_overrides(conn, "v1", path) == set()
    line = json.dumps({"id": 214, **GOOD[214]})
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="listed twice"):
        summarize.apply_overrides(conn, "v1", path)
    with pytest.raises(FileNotFoundError):
        summarize.apply_overrides(conn, "v1", tmp_path / "missing.jsonl")


def test_shipped_overrides_file_pins_quest_214_and_is_valid() -> None:
    lines = summarize.DEFAULT_OVERRIDES_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["id"] == 214
    conn = make_db()
    assert summarize.apply_overrides(conn, "v1", None) == {214}
    assert json.loads(row(conn, 214)["json"])["tasks"] == [
        "Grab 10 Red Silk Bandana.", "Go back to Scout Riell.",
    ]


# ---------------------------------------------------------------- FileProvider


def test_file_provider_answers_from_file_without_retry(tmp_path: Path, no_overrides: Path) -> None:
    path = tmp_path / "answers.jsonl"
    path.write_text(
        "# produced by subagents\n\n"
        + json.dumps({"id": 214, **BAD_214}) + "\n"
        + json.dumps({"id": 214, **GOOD[214]}) + "\n",  # a later line replaces the earlier one
        encoding="utf-8",
    )
    conn = make_db()
    provider = FileProvider(path)
    stats = run(conn, provider, no_overrides)
    assert (stats["ok"], stats["error"], stats["not_provided"], stats["rounds"]) == (1, 0, 1, 1)
    assert (row(conn, 214)["status"], row(conn, 214)["model"]) == ("ok", "file:answers.jsonl")
    assert row(conn, 7) is None  # a partial file leaves uncovered quests for a later run


def test_file_provider_bad_answer_is_rejected_after_one_attempt(tmp_path: Path,
                                                               no_overrides: Path) -> None:
    path = tmp_path / "answers.jsonl"
    path.write_text(json.dumps({"id": 214, **BAD_214}) + "\n", encoding="utf-8")
    conn = make_db()
    stats = run(conn, FileProvider(path), no_overrides, ids=[214])
    assert (stats["rejected"], stats["rounds"]) == (1, 1)
    assert (row(conn, 214)["status"], row(conn, 214)["attempts"]) == ("rejected", 1)


def test_file_provider_reports_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "answers.jsonl"
    path.write_text('{"lore_monke": "no id"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"answers\.jsonl:1"):
        FileProvider(path)


# ---------------------------------------------------------------- raw response log


class PaidFake(FakeProvider):
    paid = True


def test_paid_responses_survive_a_deleted_database(tmp_path: Path, no_overrides: Path) -> None:
    log_path = tmp_path / "cache" / "responses.jsonl"

    def fn(request: SummaryRequest) -> str:
        if request.quest_id == 214 and request.feedback is None:
            return json.dumps(BAD_214)
        return good_fn(request)

    run(make_db(), PaidFake(fn, model="claude-sonnet-5"), no_overrides, log_path=log_path)
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 3  # every paid response

    def boom(request: SummaryRequest) -> str:
        raise AssertionError("the provider must not be called: everything is in the log")

    fresh = make_db()  # "the DB was deleted"
    provider = PaidFake(boom)
    stats = run(fresh, provider, no_overrides, log_path=log_path)
    assert provider.calls == []
    assert (stats["replayed"], stats["requested"], stats["ok"]) == (3, 0, 2)
    assert (row(fresh, 214)["status"], row(fresh, 214)["attempts"]) == ("ok", 2)
    assert row(fresh, 214)["model"] == "claude-sonnet-5"


def test_unpaid_providers_do_not_write_the_log(tmp_path: Path, no_overrides: Path) -> None:
    log_path = tmp_path / "responses.jsonl"
    run(make_db(), FakeProvider(good_fn), no_overrides, log_path=log_path)
    assert not log_path.exists()


def test_log_tolerates_a_half_written_last_line(tmp_path: Path, no_overrides: Path) -> None:
    log_path = tmp_path / "responses.jsonl"
    run(make_db(), PaidFake(good_fn), no_overrides, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write('{"quest_id": 7, "finger')
    provider = PaidFake(good_fn)
    assert run(make_db(), provider, no_overrides, log_path=log_path)["replayed"] == 2


# ---------------------------------------------------------------- Anthropic providers (faked SDK)


class FakeAPIError(Exception):
    def __init__(self, message: str = "boom", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def message(text: str, stop_reason: str = "end_turn"):
    usage = NS(input_tokens=600, output_tokens=200, cache_creation_input_tokens=0,
               cache_read_input_tokens=2000)
    return NS(content=[NS(type="thinking", thinking=""), NS(type="text", text=text)],
              stop_reason=stop_reason, usage=usage)


class FakeBatches:
    def __init__(self, polls_before_end: int, results_for) -> None:
        self.created: list[list[dict]] = []
        self.polls = 0
        self.polls_before_end = polls_before_end
        self.results_for = results_for

    def create(self, requests):
        self.created.append(list(requests))
        return NS(id=f"batch_{len(self.created)}", processing_status="in_progress")

    def retrieve(self, batch_id):
        self.polls += 1
        status = "ended" if self.polls > self.polls_before_end else "in_progress"
        return NS(id=batch_id, processing_status=status,
                  request_counts=NS(processing=1, succeeded=0, errored=0))

    def results(self, batch_id):
        return iter(self.results_for(self.created[-1] if self.created else []))


@pytest.fixture
def fake_anthropic(monkeypatch: pytest.MonkeyPatch):
    """A stand-in `anthropic` package exposing only what providers.py uses."""
    module = types.ModuleType("anthropic")
    for name in ("AuthenticationError", "PermissionDeniedError", "BadRequestError",
                 "RateLimitError", "NotFoundError", "APIStatusError", "APIConnectionError"):
        setattr(module, name, type(name, (FakeAPIError,), {}))
    module.Anthropic = lambda: pytest.fail("tests inject a client; never build a real one")
    create_params = types.ModuleType("anthropic.types.message_create_params")
    create_params.MessageCreateParamsNonStreaming = dict
    batch_params = types.ModuleType("anthropic.types.messages.batch_create_params")
    batch_params.Request = dict
    for name, mod in {
        "anthropic": module, "anthropic.types": types.ModuleType("anthropic.types"),
        "anthropic.types.message_create_params": create_params,
        "anthropic.types.messages": types.ModuleType("anthropic.types.messages"),
        "anthropic.types.messages.batch_create_params": batch_params,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return module


def requests_for(*quest_ids: int) -> list[SummaryRequest]:
    return [SummaryRequest(q, "SYSTEM PROMPT", f"Quest {q}") for q in quest_ids]


def test_batch_provider_builds_requests_polls_and_reads_results(fake_anthropic) -> None:
    def results(created):
        by_quest = {int(r["custom_id"].split("-")[0][1:]): r["custom_id"] for r in created}
        return [  # deliberately not in request order
            NS(custom_id=by_quest[300], result=NS(type="expired")),
            NS(custom_id=by_quest[214], result=NS(type="succeeded",
                                                  message=message(json.dumps(GOOD[214])))),
            NS(custom_id=by_quest[7], result=NS(
                type="errored", error=NS(type="error", error=NS(type="invalid_request_error")))),
            NS(custom_id=by_quest[8], result=NS(type="succeeded",
                                                message=message("{", stop_reason="max_tokens"))),
        ]

    batches = FakeBatches(polls_before_end=3, results_for=results)
    sleeps: list[float] = []
    provider = AnthropicBatchProvider(client=NS(messages=NS(batches=batches)), state_path=None,
                                      sleep=sleeps.append, poll_initial=10, poll_max=20,
                                      log=lambda _: None)
    out = provider.summarize_many(requests_for(7, 8, 214, 300, 301))

    assert provider.model == "claude-sonnet-5" and provider.paid
    assert sleeps == [10, 15, 20]  # backs off, capped at poll_max
    assert json.loads(out[214]) == GOOD[214]
    assert isinstance(out[7], ProviderError) and not out[7].retryable
    assert isinstance(out[8], ProviderError) and out[8].retryable
    assert isinstance(out[300], ProviderError) and out[300].retryable
    assert "no result" in str(out[301])
    assert provider.usage["cache_read_input_tokens"] == 4000

    sent = batches.created[0]
    assert len(sent) == 5 and len({r["custom_id"] for r in sent}) == 5
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", r["custom_id"]) for r in sent)
    params = sent[0]["params"]
    assert params["model"] == "claude-sonnet-5"
    assert params["system"] == [{"type": "text", "text": "SYSTEM PROMPT",
                                 "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert params["messages"] == [{"role": "user", "content": "Quest 7"}]
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"]["format"] == {"type": "json_schema",
                                                 "schema": providers.SUMMARY_SCHEMA}
    assert params["output_config"]["effort"] == "low"
    assert not {"temperature", "top_p", "top_k", "stream"} & set(params)
    assert providers.SUMMARY_SCHEMA["additionalProperties"] is False


def test_batch_provider_splits_large_runs_into_several_batches(fake_anthropic) -> None:
    def results(created):
        return [NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=message("{}")))
                for r in created]

    batches = FakeBatches(polls_before_end=0, results_for=results)
    provider = AnthropicBatchProvider(client=NS(messages=NS(batches=batches)), state_path=None,
                                      max_batch_requests=2, sleep=lambda _: None,
                                      log=lambda _: None)
    out = provider.summarize_many(requests_for(1, 2, 3))
    assert [len(b) for b in batches.created] == [2, 1]
    assert out == {1: "{}", 2: "{}", 3: "{}"}


def test_batch_provider_resumes_a_journalled_batch_instead_of_paying_twice(
        fake_anthropic, tmp_path: Path) -> None:
    state = tmp_path / "cache" / "batches.jsonl"
    request = requests_for(214)[0]

    class Interrupted(FakeBatches):
        def retrieve(self, batch_id):
            raise KeyboardInterrupt

    first = AnthropicBatchProvider(client=NS(messages=NS(batches=Interrupted(0, None))),
                                   state_path=state, log=lambda _: None)
    with pytest.raises(KeyboardInterrupt):
        first.summarize_many([request])

    def results(_created):
        return [NS(custom_id=first._key(request),
                   result=NS(type="succeeded", message=message(json.dumps(GOOD[214]))))]

    batches = FakeBatches(polls_before_end=0, results_for=results)
    second = AnthropicBatchProvider(client=NS(messages=NS(batches=batches)), state_path=state,
                                    log=lambda _: None)
    assert json.loads(second.summarize_many([request])[214]) == GOOD[214]
    assert batches.created == []  # nothing was submitted again
    third = AnthropicBatchProvider(client=NS(messages=NS(batches=batches)), state_path=state,
                                   log=lambda _: None)
    assert list(third._unfinished_batches()) == []


def test_direct_provider_maps_sdk_errors_per_request(fake_anthropic) -> None:
    calls: list[dict] = []

    def create(**params):
        calls.append(params)
        quest = params["messages"][0]["content"]
        if quest == "Quest 1":
            return message(json.dumps(GOOD[214]))
        if quest == "Quest 2":
            raise fake_anthropic.BadRequestError("schema too deep", 400)
        if quest == "Quest 3":
            raise fake_anthropic.RateLimitError("slow down", 429)
        if quest == "Quest 4":
            return message("", stop_reason="refusal")
        raise fake_anthropic.APIStatusError("overloaded", 529)

    provider = AnthropicDirectProvider(client=NS(messages=NS(create=create)))
    out = provider.summarize_many(requests_for(1, 2, 3, 4, 5))
    assert json.loads(out[1]) == GOOD[214]
    assert [out[q].retryable for q in (2, 3, 4, 5)] == [False, True, False, True]
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"

    def denied(**params):
        raise fake_anthropic.AuthenticationError("no key", 401)

    with pytest.raises(fake_anthropic.AuthenticationError):
        AnthropicDirectProvider(client=NS(messages=NS(create=denied))).summarize_many(
            requests_for(1))


@pytest.mark.parametrize("provider_class", [AnthropicBatchProvider, AnthropicDirectProvider])
def test_missing_anthropic_package_gives_install_hint(monkeypatch, provider_class) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` raise
    provider = provider_class()  # constructing is fine; only use needs the package
    with pytest.raises(MissingDependencyError, match="uv sync --extra llm"):
        provider.summarize_many(requests_for(214))


def test_anthropic_is_not_imported_by_the_pipeline_modules() -> None:
    assert "anthropic" not in sys.modules or sys.modules["anthropic"] is None


def test_the_log_never_shadows_a_summaries_file_or_a_retry(tmp_path: Path, no_overrides: Path) -> None:
    """A paid run logged a bad answer for 214. A later file run must read the file, and a
    retry that forgot the rejected row must reach the provider again."""
    log_path = tmp_path / "responses.jsonl"

    def bad_fn(request: SummaryRequest) -> str:
        return json.dumps(BAD_214) if request.quest_id == 214 else good_fn(request)

    run(make_db(), PaidFake(bad_fn), no_overrides, log_path=log_path)

    path = tmp_path / "answers.jsonl"
    path.write_text(json.dumps({"id": 214, **GOOD[214]}) + "\n", encoding="utf-8")
    conn = make_db()
    stats = run(conn, FileProvider(path), no_overrides, log_path=log_path)
    assert (stats["replayed"], row(conn, 214)["status"]) == (0, "ok")

    conn = make_db()
    provider = PaidFake(good_fn)
    stats = run(conn, provider, no_overrides, log_path=log_path, no_replay={214})
    assert 214 in [r.quest_id for batch in provider.calls for r in batch]
    assert row(conn, 214)["status"] == "ok"


def test_a_partial_collect_leaves_the_rest_of_the_batch_open(fake_anthropic, tmp_path: Path) -> None:
    """Run 1 submits two quests and dies. Run 2 asks for one of them (--ids). Run 3 asks
    for the other: it must come from the same batch, never be submitted again."""
    state = tmp_path / "cache" / "batches.jsonl"
    reqs = requests_for(214, 7)

    class Interrupted(FakeBatches):
        def retrieve(self, batch_id):
            raise KeyboardInterrupt

    first = AnthropicBatchProvider(client=NS(messages=NS(batches=Interrupted(0, None))),
                                   state_path=state, log=lambda _: None)
    with pytest.raises(KeyboardInterrupt):
        first.summarize_many(reqs)

    def results(_created):
        return [NS(custom_id=first._key(r), result=NS(type="succeeded", message=message(json.dumps(GOOD[214]))))
                for r in reqs]

    batches = FakeBatches(polls_before_end=0, results_for=results)
    second = AnthropicBatchProvider(client=NS(messages=NS(batches=batches)), state_path=state, log=lambda _: None)
    assert set(second.summarize_many([reqs[0]])) == {214}
    third = AnthropicBatchProvider(client=NS(messages=NS(batches=batches)), state_path=state, log=lambda _: None)
    assert set(third.summarize_many([reqs[1]])) == {7}
    assert batches.created == []  # both answers came from the first batch
    assert list(third._unfinished_batches()) == []


def test_direct_provider_hands_over_each_paid_answer_as_it_arrives(fake_anthropic) -> None:
    seen: list[int] = []

    def create(**params):
        if len(seen) == 1:
            raise fake_anthropic.AuthenticationError("token expired", 401)
        return message(json.dumps(GOOD[214]))

    provider = AnthropicDirectProvider(client=NS(messages=NS(create=create)))
    provider.on_result(lambda request, text: seen.append(request.quest_id))
    with pytest.raises(fake_anthropic.AuthenticationError):
        provider.summarize_many(requests_for(1, 2, 3))
    assert seen == [1]  # the one answer paid for before the failure was handed over


# ---------------------------------------------------------------- stamps: what a line was written for


def stamp_of(conn, quest_id: int, prompt_version: str = "v1") -> dict:
    """The stamp `requests` hands a writer for this quest as it is now."""
    quest = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
    return {"prompt_version": prompt_version, "text_hash": quest["text_hash"],
            "context_hash": load_context(conn, quest).fingerprint()}


def write_lines(path: Path, *lines: dict) -> Path:
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def test_a_stamped_line_answers_only_the_version_of_the_quest_it_was_written_for(
        tmp_path: Path, no_overrides: Path) -> None:
    conn = make_db()
    old = {**stamp_of(conn, 7), "context_hash": "0123456789abcdef"}  # written before the quest changed
    path = write_lines(tmp_path / "a.jsonl", {"id": 214, **stamp_of(conn, 214), **GOOD[214]},
                       {"id": 7, **old, **GOOD[7]})
    stats = run(conn, FileProvider(path, require_stamp=True), no_overrides)
    assert (stats["ok"], stats["not_provided"], stats["rejected"]) == (1, 1, 0)
    assert json.loads(row(conn, 214)["json"]) == GOOD[214]  # the stamp never reaches the validator
    assert row(conn, 7) is None  # neither applied nor saved as rejected: a writer gets it again


def test_the_newest_line_that_fits_wins(tmp_path: Path) -> None:
    conn = make_db()
    stamp = stamp_of(conn, 214)
    later_release = {**stamp, "text_hash": "fedcba9876543210"}
    a = write_lines(tmp_path / "a.jsonl", {"id": 214, **stamp, **GOOD[214], "lore_monke": "First draft."})
    b = write_lines(tmp_path / "b.jsonl", {"id": 214, **stamp, **GOOD[214], "lore_monke": "Corrected."},
                    {"id": 214, **later_release, **GOOD[214], "lore_monke": "For a later release."})
    provider = FileProvider([a, b])
    answer = provider.summarize_many([SummaryRequest(214, "S", "U", stamp=providers.Stamp(**stamp))])[214]
    assert json.loads(answer)["lore_monke"] == "Corrected."
    assert set(json.loads(answer)) == set(SUMMARY_KEYS)
    assert provider.model_for(214) == "file:b.jsonl"
    v2 = providers.Stamp(**{**stamp, "prompt_version": "v2"})
    assert isinstance(provider.summarize_many([SummaryRequest(214, "S", "U", stamp=v2)])[214],
                      providers.NotProvided)
    assert provider.stale == {214}


def test_unstamped_lines_count_only_where_stamps_are_not_required(tmp_path: Path) -> None:
    path = write_lines(tmp_path / "a.jsonl", {"id": 214, **GOOD[214]})
    request = SummaryRequest(214, "S", "U", stamp=providers.Stamp("v1", "0" * 16, "1" * 16))
    assert isinstance(FileProvider(path).summarize_many([request])[214], str)
    strict = FileProvider(path, require_stamp=True)
    assert isinstance(strict.summarize_many([request])[214], providers.NotProvided)
    assert strict.unstamped == {214}


@pytest.mark.parametrize("stamp", [
    {"text_hash": "0123456789abcdef"},
    {"prompt_version": "v1", "text_hash": "not hex at all!", "context_hash": "0123456789abcdef"},
    {"prompt_version": "", "text_hash": "0123456789abcdef", "context_hash": "0123456789abcdef"},
], ids=["part of a stamp", "not a hash", "no prompt version"])
def test_a_malformed_stamp_is_an_error_naming_the_line(tmp_path: Path, stamp: dict) -> None:
    path = write_lines(tmp_path / "a.jsonl", {"id": 214, **stamp, **GOOD[214]})
    with pytest.raises(ValueError, match=r"a\.jsonl:1"):
        FileProvider(path)


def test_a_rejected_row_is_checked_again_when_the_file_text_changes(tmp_path: Path, no_overrides: Path) -> None:
    conn = make_db()
    stamp = stamp_of(conn, 214)
    slip = write_lines(tmp_path / "a.jsonl", {"id": 214, **stamp, **BAD_214})
    run(conn, FileProvider(slip), no_overrides, ids=[214])
    assert row(conn, 214)["status"] == "rejected"
    stats = run(conn, FileProvider(slip), no_overrides, ids=[214])
    assert (stats["cached"], stats["rechecked"]) == (1, 0)  # the same text is not checked again
    fix = write_lines(tmp_path / "b.jsonl", {"id": 214, **stamp, **GOOD[214]})
    stats = run(conn, FileProvider([slip, fix]), no_overrides, ids=[214])
    assert (stats["rechecked"], stats["ok"]) == (1, 1)
    assert (row(conn, 214)["status"], row(conn, 214)["model"]) == ("ok", "file:b.jsonl")


def test_an_ok_row_from_a_file_follows_the_files_but_never_gets_worse(tmp_path: Path, no_overrides: Path) -> None:
    """A correction committed later reaches a database that already has the first draft, as it
    would a fresh clone. A later line that fails the validator does not undo a good one."""
    conn = make_db()
    stamp = stamp_of(conn, 214)
    first = write_lines(tmp_path / "a.jsonl", {"id": 214, **stamp, **GOOD[214]})
    run(conn, FileProvider(first), no_overrides, ids=[214])
    better = {**GOOD[214], "lore_monke": "Scout Riell want 10 Red Silk Bandanas back."}
    second = write_lines(tmp_path / "b.jsonl", {"id": 214, **stamp, **better})
    run(conn, FileProvider([first, second]), no_overrides, ids=[214])
    assert json.loads(row(conn, 214)["json"]) == better
    worse = write_lines(tmp_path / "c.jsonl", {"id": 214, **stamp, **BAD_214})
    stats = run(conn, FileProvider([first, second, worse]), no_overrides, ids=[214])
    assert (stats["rechecked"], stats["kept"], stats["rejected"]) == (1, 1, 0)
    assert (row(conn, 214)["status"], json.loads(row(conn, 214)["json"])) == ("ok", better)


def test_paid_rows_are_never_second_guessed_by_a_file(tmp_path: Path, no_overrides: Path) -> None:
    conn = make_db()
    run(conn, FakeProvider(good_fn, model="claude-sonnet-5"), no_overrides)
    other = {**GOOD[214], "lore_monke": "Scout Riell want 10 Red Silk Bandanas back."}
    path = write_lines(tmp_path / "a.jsonl", {"id": 214, **stamp_of(conn, 214), **other})
    stats = run(conn, FileProvider(path), no_overrides)
    assert (stats["rechecked"], stats["cached"]) == (0, 2)
    assert json.loads(row(conn, 214)["json"]) == GOOD[214]


def test_exclude_keeps_quests_out_of_a_run(no_overrides: Path) -> None:
    conn = make_db()
    provider = FakeProvider(good_fn)
    run(conn, provider, no_overrides, exclude={214})
    assert [r.quest_id for r in provider.calls[0]] == [7]
    assert row(conn, 214) is None

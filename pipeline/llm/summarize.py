"""Summarize quests with a provider, validate, re-prompt with the errors, cache forever.

Money is the design constraint. A summary is requested at most once per
(quest_id, text_hash, prompt_version); all quests of one retry round go to the
provider in a single call so the Batch API sees one big batch per round; and every
paid response is appended to a JSONL log *before* it is validated, so deleting the
SQLite file never means paying twice.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pipeline import db, rules
from pipeline.llm.providers import (
    Feedback,
    NotProvided,
    Provider,
    ProviderError,
    Result,
    Stamp,
    SummaryRequest,
    read_summary_lines,
)
from pipeline.validate import SUMMARY_KEYS, QuestContext, load_context, validate

LLM_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = LLM_DIR / "prompts"
DEFAULT_OVERRIDES_PATH = LLM_DIR / "overrides.jsonl"
DEFAULT_LOG_PATH = LLM_DIR / "cache" / "responses.jsonl"  # gitignored

OVERRIDE_MODEL = "override"
CACHED_STATUSES = ("ok", "rejected")  # 'error' rows are asked again on the next run
_AMOUNT_TYPES = ("monster", "item", "object")


class OverrideError(ValueError):
    """A hand-pinned summary in overrides.jsonl does not pass the validator."""


# --------------------------------------------------------------------------- prompt


def load_prompt(prompt_version: str = "v1") -> str:
    """The system prompt. The version is the file stem, so a new prompt is a new cache key."""
    path = PROMPTS_DIR / f"{prompt_version}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file for version {prompt_version!r}: {path}")
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _objective_line(objective: object) -> str:
    kind = rules.field(objective, "type", "?")
    name = rules.field(objective, "target_name")
    text = rules.field(objective, "text")
    amount = rules.field(objective, "amount", 1)
    parts = [kind, name or text or "(unnamed)"]
    if kind in _AMOUNT_TYPES or amount > 1:
        unconfirmed = rules.field(objective, "amount_source", "default") == "default"
        parts.append(f"x{amount}" + (" (unconfirmed)" if unconfirmed else ""))
    if name and text and text != name:
        parts.append(f"text: {text}")
    return " | ".join(parts)


def build_user_message(ctx: QuestContext) -> str:
    """One quest as the compact text block described in the system prompt.

    Deterministic on purpose: the same quest always renders to the same bytes, which is
    what lets the raw response log recognise a request it has already paid for.
    """
    lines = [f"Quest {ctx.id}: {ctx.title or '(untitled)'}"]
    for label, value in (("Detail", ctx.detail), ("Objectives text", ctx.objectives_text),
                         ("Progress", ctx.progress), ("Complete", ctx.complete)):
        if value:
            lines.append(f"{label}: {value}")
    lines.append(f"Structured objectives ({len(ctx.objectives)}):")
    lines += [f"{i}. {_objective_line(o)}" for i, o in enumerate(ctx.objectives, start=1)]
    turnin = ctx.turnin_npc or "unknown"
    if ctx.turnin_npc and ctx.turnin_kind == "other":
        turnin += " (not the quest giver)"
    elif ctx.turnin_npc and ctx.turnin_kind == "object":
        turnin += " (an object, not a person)"
    lines.append(f"Turn-in NPC: {turnin}")
    if rules.group_line(ctx.group_size, ctx.tag, rules.PLAIN) is not None:
        group = [f"size {ctx.group_size}"] if (ctx.group_size or 0) > 1 else []
        group += [f"tag {ctx.tag}"] if ctx.tag else []
        lines.append("Group: " + ", ".join(group))
    return "\n".join(lines)


# --------------------------------------------------------------------------- summaries table


def get_summary(
    conn: sqlite3.Connection, quest_id: int, text_hash: str, prompt_version: str,
    context_hash: str | None = None,
) -> sqlite3.Row | None:
    """The cached summary row for the quest's *current* text, if any.

    With `context_hash`, a row written against different objectives, a different turn-in
    NPC or different group data (the text hash covers only the prose) counts as absent:
    it is stale, and the addon would pair its bullets with the wrong live objectives.
    """
    row = conn.execute(
        "SELECT * FROM summaries WHERE quest_id = ? AND text_hash = ? AND prompt_version = ?",
        (quest_id, text_hash, prompt_version),
    ).fetchone()
    if row is not None and context_hash is not None and row["context_hash"] != context_hash:
        return None
    return row


def save_summary(
    conn: sqlite3.Connection, quest_id: int, text_hash: str, prompt_version: str, *,
    model: str, summary_json: str | None, status: str, errors: list[str], attempts: int,
    context_hash: str | None = None,
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO summaries
           (quest_id, text_hash, prompt_version, model, json, status, errors, attempts,
            context_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (quest_id, text_hash, prompt_version, model, summary_json, status,
         json.dumps(errors, ensure_ascii=False), attempts, context_hash, db.utcnow()),
    )


def canonical_json(summary: dict) -> str:
    """Stable key order, so the same summary is always the same bytes in the DB."""
    return json.dumps({k: summary[k] for k in SUMMARY_KEYS}, ensure_ascii=False)


def check_response(text: str, ctx: QuestContext) -> tuple[dict | None, list[str]]:
    """Parse and validate a raw provider response. Returns (summary or None, errors)."""
    try:
        summary = json.loads(text)
    except ValueError as exc:
        return None, [f"The output was not valid JSON ({exc}). Return exactly one JSON object."]
    return summary, validate(summary, ctx)


# --------------------------------------------------------------------------- overrides


def apply_overrides(
    conn: sqlite3.Connection, prompt_version: str = "v1", overrides_path: Path | None = None
) -> set[int]:
    """Pin hand-written summaries. They beat the LLM, but not the validator.

    The pitch example (quest 214) must render exactly as the owner wrote it, so overrides
    replace whatever is cached. They are validated like any other summary because a typo
    in a pinned line would otherwise ship to every player; that is a hard error naming
    the quest. Rows pinned by an override that has since been removed are deleted, which
    hands the quest back to the LLM on this run.
    """
    path = Path(overrides_path) if overrides_path is not None else DEFAULT_OVERRIDES_PATH
    if overrides_path is None and not path.exists():
        overrides: dict[int, dict] = {}
    else:
        overrides = read_summary_lines(path, unique=True)
    applied: set[int] = set()
    for quest_id, summary in sorted(overrides.items()):
        quest = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
        if quest is None:
            continue  # pinned for a quest this database does not know (yet)
        ctx = load_context(conn, quest)
        errors = validate(summary, ctx)
        if errors:
            raise OverrideError(
                f"override for quest {quest_id} in {path} is invalid:\n  " + "\n  ".join(errors))
        save_summary(conn, quest_id, quest["text_hash"], prompt_version, model=OVERRIDE_MODEL,
                     summary_json=canonical_json(summary), status="ok", errors=[], attempts=0,
                     context_hash=ctx.fingerprint())
        applied.add(quest_id)
    stale = [r["quest_id"] for r in conn.execute(
        "SELECT quest_id FROM summaries WHERE model = ? AND prompt_version = ?",
        (OVERRIDE_MODEL, prompt_version)) if r["quest_id"] not in applied]
    conn.executemany("DELETE FROM summaries WHERE model = ? AND prompt_version = ? AND quest_id = ?",
                     [(OVERRIDE_MODEL, prompt_version, q) for q in stale])
    conn.commit()
    return applied


# --------------------------------------------------------------------------- raw response log


class ResponseLog:
    """Append-only JSONL of raw paid responses, keyed by (quest id, request fingerprint).

    The fingerprint covers the system prompt and the full user turn including feedback,
    so replaying a log walks the same attempt chain the paid run took, and a prompt edit
    without a version bump can never resurrect an answer to a different question.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path is not None else None
        self._seen: dict[tuple[int, str], dict] = {}
        if self.path is not None and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                    self._seen[(record["quest_id"], record["fingerprint"])] = record
                except (ValueError, KeyError, TypeError):
                    continue  # a half-written last line from a crash; the rest is still good

    def get(self, request: SummaryRequest) -> dict | None:
        return self._seen.get((request.quest_id, request.fingerprint()))

    def append(self, request: SummaryRequest, response: str, *, model: str, text_hash: str,
               prompt_version: str) -> None:
        if self.path is None:
            return
        record = {
            "quest_id": request.quest_id, "fingerprint": request.fingerprint(),
            "text_hash": text_hash, "prompt_version": prompt_version, "model": model,
            "at": db.utcnow(), "response": response,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._seen[(request.quest_id, request.fingerprint())] = record


# --------------------------------------------------------------------------- run


@dataclass
class _Work:
    """One quest travelling through the retry rounds."""

    ctx: QuestContext
    text_hash: str
    user: str
    feedback: Feedback | None = None
    attempts: int = 0
    last_output: str | None = None
    model: str = ""
    stamp: Stamp | None = None  # the version of the quest being summarised
    keep_ok: bool = False  # re-checking newer file text against an ok row: keep the row unless it passes


def _superseded(offered: dict | None, cached: sqlite3.Row) -> bool:
    """True when a file now holds other text for this version of the quest than the cached row.

    That re-checks a rejected row (whoever wrote it) once a fix is committed, and keeps an ok row
    a file wrote in step with the files, so an old database ships what a fresh clone would. An
    ok row from a paid provider is never second-guessed by a file, and pinned overrides never
    reach here.
    """
    if offered is None:
        return False
    if cached["status"] == "ok" and not str(cached["model"] or "").startswith("file:"):
        return False
    try:
        return json.loads(cached["json"] or "null") != offered
    except ValueError:
        return True


def _pending(
    conn: sqlite3.Connection, prompt_version: str, ids: Iterable[int] | None, limit: int | None,
    pinned: set[int], stats: dict, provider: Provider | None = None, exclude: set[int] = frozenset(),
) -> dict[int, _Work]:
    wanted = set(ids) if ids is not None else None
    offer = getattr(provider, "offer", None)
    pending: dict[int, _Work] = {}
    for quest in conn.execute("SELECT * FROM quests ORDER BY id").fetchall():
        quest_id = quest["id"]
        if (wanted is not None and quest_id not in wanted) or quest_id in pinned or quest_id in exclude:
            continue
        stats["quests"] += 1
        ctx = load_context(conn, quest)
        if not ctx.has_prose():
            stats["skipped_no_prose"] += 1
            continue
        stamp = Stamp(prompt_version, quest["text_hash"], ctx.fingerprint())
        cached = get_summary(conn, quest_id, quest["text_hash"], prompt_version, stamp.context_hash)
        recheck = False
        if cached is not None and cached["status"] in CACHED_STATUSES:
            recheck = offer is not None and _superseded(offer(quest_id, stamp), cached)
            if not recheck:
                stats["cached"] += 1
                continue
        if limit is None or len(pending) < limit:
            pending[quest_id] = _Work(ctx, quest["text_hash"], build_user_message(ctx), stamp=stamp,
                                      keep_ok=recheck and cached["status"] == "ok")
            stats["rechecked"] += recheck
    return pending


def _ask(
    provider: Provider, requests: list[SummaryRequest], pending: dict[int, _Work],
    log: ResponseLog, prompt_version: str, stats: dict, no_replay: set[int] = frozenset(),
) -> dict[int, Result]:
    """Answer requests from the raw log where possible, from the provider otherwise.

    The log only stands in for a paid provider: a summaries file must always be read,
    and a quest the caller wants asked again (`no_replay`) goes to the provider even if
    an earlier paid answer is on file.
    """
    results: dict[int, Result] = {}
    to_send = []
    for request in requests:
        logged = log.get(request) if provider.paid and request.quest_id not in no_replay else None
        if logged is None:
            to_send.append(request)
            continue
        results[request.quest_id] = logged["response"]
        pending[request.quest_id].model = logged.get("model") or provider.model
        stats["replayed"] += 1
    if to_send:
        logged_early: set[int] = set()

        def keep(request: SummaryRequest, response: str) -> None:
            # Paid answers reach the log as they arrive; an interrupted run loses nothing.
            work = pending[request.quest_id]
            log.append(request, response, model=provider.model, text_hash=work.text_hash,
                       prompt_version=prompt_version)
            logged_early.add(request.quest_id)

        if provider.paid and hasattr(provider, "on_result"):
            provider.on_result(keep)
        try:
            answers = provider.summarize_many(to_send)
        finally:
            if provider.paid and hasattr(provider, "on_result"):
                provider.on_result(None)
        stats["requested"] += len(to_send)
        model_for = getattr(provider, "model_for", None)  # a file names the file that answered
        for request in to_send:
            result = answers.get(request.quest_id, ProviderError("the provider returned nothing"))
            work = pending[request.quest_id]
            work.model = model_for(request.quest_id) if model_for is not None else provider.model
            if isinstance(result, str) and provider.paid and request.quest_id not in logged_early:
                log.append(request, result, model=provider.model, text_hash=work.text_hash,
                           prompt_version=prompt_version)
            results[request.quest_id] = result
    return results


def _settle(work: _Work, result: Result, may_retry: bool) -> tuple[str, list[str]] | None:
    """Decide one quest's fate after an attempt. None means: go round again."""
    if isinstance(result, Exception):
        if may_retry and getattr(result, "retryable", True):
            return None
        return "error", [str(result) or type(result).__name__]
    summary, errors = check_response(result, work.ctx)
    work.last_output = canonical_json(summary) if summary is not None and not errors else result
    if not errors:
        return "ok", []
    if may_retry:
        work.feedback = Feedback(previous_output=result, errors=tuple(errors))
        return None
    return "rejected", errors


def run(
    conn: sqlite3.Connection,
    provider: Provider,
    *,
    prompt_version: str = "v1",
    ids: Iterable[int] | None = None,
    limit: int | None = None,
    max_retries: int = 2,
    overrides_path: Path | None = None,
    log_path: Path | None = DEFAULT_LOG_PATH,
    no_replay: Iterable[int] = (),
    exclude: Iterable[int] = (),
) -> dict:
    """Fill `summaries` for every quest that needs one. Returns counters for the CLI.

    `limit` caps how many quests are sent to the provider in this run. `log_path=None`
    turns the raw response log off (tests); `overrides_path=None` means the default
    pipeline/llm/overrides.jsonl. Quests in `no_replay` are asked again even when the
    raw log holds an answer (the CLI passes the ids it forgot with --retry-rejected), and
    quests in `exclude` are left out (the CLI keeps those ids away from the committed files
    when a paid provider is to answer them).

    Every request carries the stamp of the quest as it is now, which is all a file can answer
    for. When the provider is a file whose text for a quest differs from the cached row (a fix
    committed after a rejection, a correction to a draft), the quest is checked again
    (`rechecked`); an ok row stays unless the new text passes too (`kept`).
    """
    no_replay = set(no_replay)
    stats = dict.fromkeys(("quests", "overrides", "cached", "skipped_no_prose", "pending",
                           "rechecked", "requested", "replayed", "rounds", "ok", "rejected", "kept",
                           "error", "not_provided"), 0)
    system = load_prompt(prompt_version)
    pinned = apply_overrides(conn, prompt_version, overrides_path)
    stats["overrides"] = len(pinned)
    pending = _pending(conn, prompt_version, ids, limit, pinned, stats, provider, set(exclude))
    stats["pending"] = len(pending)
    log = ResponseLog(log_path)

    for round_no in range(max_retries + 1):
        if not pending:
            break
        stats["rounds"] += 1
        requests = [SummaryRequest(qid, system, w.user, w.feedback, stamp=w.stamp)
                    for qid, w in pending.items()]
        results = _ask(provider, requests, pending, log, prompt_version, stats, no_replay)
        may_retry = round_no < max_retries and provider.supports_feedback
        for quest_id, result in results.items():
            work = pending[quest_id]
            if isinstance(result, NotProvided):
                # A partial summaries file: leave the quest untouched for a later run
                # instead of filling the table with thousands of "not provided" rows.
                stats["not_provided"] += 1
                del pending[quest_id]
                continue
            work.attempts += 1
            verdict = _settle(work, result, may_retry)
            if verdict is None:
                continue
            status, errors = verdict
            if work.keep_ok and status != "ok":
                stats["kept"] += 1  # a file's newer text failed: the ok row it would replace stays
                del pending[quest_id]
                continue
            save_summary(conn, quest_id, work.text_hash, prompt_version, model=work.model,
                         summary_json=work.last_output, status=status, errors=errors,
                         attempts=work.attempts, context_hash=work.ctx.fingerprint())
            stats[status] += 1
            del pending[quest_id]
        conn.commit()  # a crash in a later round keeps what this round settled
    return stats

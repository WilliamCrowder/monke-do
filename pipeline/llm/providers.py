"""Summary providers: where the text of a summary comes from.

`summarize.run` only knows the `Provider` protocol, so the same validate/retry/cache
loop serves the paid Anthropic API, a JSONL file written by someone else, and tests.

The `anthropic` package is an optional extra. It is imported lazily, inside the two
providers that need it, so everything else (and every test) runs without it. No code
here ever reads or handles an API key: `anthropic.Anthropic()` resolves credentials
from the environment by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

DEFAULT_MODEL = "claude-sonnet-5"  # chosen by the project owner; override per provider
DEFAULT_MAX_TOKENS = 4096  # the JSON is ~200 tokens; the rest is headroom for adaptive thinking
DEFAULT_EFFORT = "low"     # short, scoped rewriting task; raise it if review finds shallow lore
MAX_BATCH_REQUESTS = 10_000  # API limit is 100,000 requests or 256 MB per batch
# Journal of submitted batches, beside the raw response log (pipeline/llm/cache/ is gitignored).
DEFAULT_BATCH_STATE_PATH = Path(__file__).resolve().parent / "cache" / "batches.jsonl"

# Structured output schema (output_config.format). Every object needs
# additionalProperties: false; length and item-count limits are not supported by the
# API, so pipeline/validate.py enforces those.
SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lore_monke": {"type": "string"},
        "lore_plain": {"type": "string"},
        "tasks": {"type": "array", "items": {"type": "string"}},
        "group_line": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["lore_monke", "lore_plain", "tasks", "group_line"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- stamps

# What a summary line was written for, stored in the line beside the four summary keys and
# stripped before validation. The names are the `summaries` table's columns.
STAMP_KEYS = ("prompt_version", "text_hash", "context_hash")
_HASH = re.compile(r"[0-9a-f]{16}")


@dataclass(frozen=True)
class Stamp:
    """The version of a quest a summary was written for: the prompt version, the quest's text
    hash (db.text_hash) and the fingerprint of everything the writer was shown
    (QuestContext.fingerprint). `requests` hands it to a writer; a line that carries it answers
    only a request for the same version of the quest."""

    prompt_version: str
    text_hash: str
    context_hash: str

    def as_dict(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in STAMP_KEYS}

    def differences(self, now: Stamp) -> list[str]:
        """How the quest as it is `now` differs from the version this stamp names, in words."""
        out = []
        if self.prompt_version != now.prompt_version:
            out.append(f"prompt {self.prompt_version}, not {now.prompt_version}")
        if self.text_hash != now.text_hash:
            out.append("other quest text")
        elif self.context_hash != now.context_hash:
            out.append("other objectives, turn-in or group data")
        return out


def stamp_of(record: dict, where: str = "") -> Stamp | None:
    """The stamp in a summary line, or None for a line without one. Part of a stamp, or a value
    unlike what `requests` writes, is an error naming `where` (a "path:line: " prefix)."""
    present = [key for key in STAMP_KEYS if key in record]
    if not present:
        return None
    if len(present) != len(STAMP_KEYS):
        missing = [key for key in STAMP_KEYS if key not in record]
        raise ValueError(f"{where}a stamp needs {', '.join(STAMP_KEYS)}; this line lacks {', '.join(missing)}")
    version, text_hash, context_hash = (record[key] for key in STAMP_KEYS)
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{where}prompt_version must be a non-empty string")
    for key, value in (("text_hash", text_hash), ("context_hash", context_hash)):
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            raise ValueError(f"{where}{key} must be 16 lower-case hex digits, as `requests` writes it")
    return Stamp(version, text_hash, context_hash)


def strip_stamp(record: dict) -> dict:
    """The line without its stamp: what the validator sees."""
    return {key: value for key, value in record.items() if key not in STAMP_KEYS}


# --------------------------------------------------------------------------- requests


@dataclass(frozen=True)
class Feedback:
    """Why the previous attempt was rejected, fed back so the model can fix it."""

    previous_output: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class SummaryRequest:
    quest_id: int
    system: str
    user: str
    feedback: Feedback | None = None
    stamp: Stamp | None = None  # the version of the quest asked about; a file answers only for it

    def content(self) -> str:
        """The full user turn. Feedback is appended to the same turn rather than sent as
        an assistant turn plus a second user turn: it keeps every request single-shot
        (which the Batch API needs) and never replays model output as if it were ours."""
        if self.feedback is None:
            return self.user
        complaints = "\n".join(f"- {e}" for e in self.feedback.errors)
        return (
            f"{self.user}\n\n"
            f"Your previous answer was rejected:\n{self.feedback.previous_output}\n\n"
            f"The validator said:\n{complaints}\n\n"
            "Return the complete corrected JSON object."
        )

    def fingerprint(self) -> str:
        """Identity of this exact request, used to find already-paid-for responses."""
        joined = "\x1f".join((self.system, self.content()))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


class ProviderError(Exception):
    """A per-quest failure. `retryable` says whether asking again could help."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class NotProvided(ProviderError):
    """The provider has no answer for this quest and never will during this run."""

    def __init__(self, message: str = "not provided") -> None:
        super().__init__(message, retryable=False)


class MissingDependencyError(RuntimeError):
    """The optional `anthropic` package is not installed."""


Result = str | Exception


@runtime_checkable
class Provider(Protocol):
    """`model` is stored with each summary. `paid` makes `run` keep a raw response log.
    `supports_feedback` is False for providers that cannot answer a re-prompt."""

    model: str
    paid: bool
    supports_feedback: bool

    def summarize_many(self, requests: list[SummaryRequest]) -> dict[int, Result]: ...


# --------------------------------------------------------------------------- offline providers


class FakeProvider:
    """Test double: `fn(request)` returns the raw response text or raises/returns an Exception."""

    paid = False
    supports_feedback = True

    def __init__(self, fn: Callable[[SummaryRequest], Result], model: str = "fake") -> None:
        self.fn = fn
        self.model = model
        self.calls: list[list[SummaryRequest]] = []

    def summarize_many(self, requests: list[SummaryRequest]) -> dict[int, Result]:
        self.calls.append(list(requests))
        out: dict[int, Result] = {}
        for request in requests:
            try:
                out[request.quest_id] = self.fn(request)
            except Exception as exc:  # noqa: BLE001 - a test double reports, never crashes the run
                out[request.quest_id] = exc
        return out


def iter_summary_lines(path: Path) -> Iterator[tuple[int, int, dict]]:
    """(line number, quest id, the rest of the line) for every summary line, in file order:
    `{"id": 214, "lore_monke": ..., "tasks": [...], ...}`, optionally with a stamp.

    Shared by FileProvider, `check` and the overrides file so all accept the same format.
    Blank lines and lines starting with '#' are skipped.
    """
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
                quest_id = int(record.pop("id"))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(f"{path}:{number}: expected a JSON object with an integer "
                                 f"'id' ({exc})") from exc
            yield number, quest_id, record


def read_summary_lines(path: Path, *, unique: bool = False) -> dict[int, dict]:
    """Summary lines as {id: the rest of the line}. With `unique`, a repeated id is an error
    (a pinned override listed twice is a mistake); otherwise the last line wins (an appended
    correction replaces the earlier attempt)."""
    out: dict[int, dict] = {}
    for number, quest_id, record in iter_summary_lines(path):
        if unique and quest_id in out:
            raise ValueError(f"{path}:{number}: quest {quest_id} is listed twice")
        out[quest_id] = record
    return out


@dataclass(frozen=True)
class SummaryLine:
    """One line of a summaries file: where it is, the summary it holds, and its stamp."""

    path: Path
    number: int
    summary: dict  # the line without its id and its stamp
    stamp: Stamp | None

    @property
    def file(self) -> str:
        return self.path.name


class FileProvider:
    """Answers from JSONL files produced elsewhere, for example by Claude Code subagents.

    A line may carry a stamp (STAMP_KEYS): the version of the quest it was written for, as
    `requests` handed it to the writer. A stamped line answers only a request for that same
    version, so a quest that changed since gets NotProvided, never text written for its old
    objectives or turn-in. Of the lines that fit, the newest wins (files in the order given,
    lines in file order): a correction file overrides first drafts, and a line written for
    another release waits for that release. An unstamped line fits any version unless
    `require_stamp` (the committed folder, where every line must say what it was written for).

    A file cannot react to validator feedback, so `run` does not re-prompt it, and quests no
    line fits come back as NotProvided: they stay uncached and are picked up by a later run
    once a file (or a paid provider) covers them. `stale` and `unstamped` collect the quests
    that had lines but none that fit, for the CLI to report.
    """

    paid = False
    supports_feedback = False

    def __init__(self, paths: str | Path | Iterable[str | Path], *, require_stamp: bool = False) -> None:
        self.paths = [Path(paths)] if isinstance(paths, (str, Path)) else [Path(p) for p in paths]
        if not self.paths:
            raise ValueError("FileProvider needs at least one file")
        self.require_stamp = require_stamp
        self.model = "file:" + "+".join(path.name for path in self.paths)
        self._lines: dict[int, list[SummaryLine]] = {}
        for path in self.paths:
            for number, quest_id, record in iter_summary_lines(path):
                stamp = stamp_of(record, f"{path}:{number}: ")
                self._lines.setdefault(quest_id, []).append(
                    SummaryLine(path, number, strip_stamp(record), stamp))
        self._answered: dict[int, SummaryLine] = {}
        self.stale: set[int] = set()
        self.unstamped: set[int] = set()

    def quest_ids(self) -> list[int]:
        return sorted(self._lines)

    def lines_for(self, quest_id: int) -> list[SummaryLine]:
        """Every line for the quest, oldest first."""
        return list(self._lines.get(quest_id, ()))

    def pick(self, quest_id: int, stamp: Stamp | None) -> SummaryLine | None:
        """The newest line written for this version of the quest, or None."""
        for line in reversed(self._lines.get(quest_id, ())):
            if line.stamp is None:
                if not self.require_stamp:
                    return line
            elif line.stamp == stamp:
                return line
        return None

    def offer(self, quest_id: int, stamp: Stamp | None) -> dict | None:
        """The summary this provider would answer with, without answering (summarize.run uses
        it to tell whether a cached row is still what the files say)."""
        line = self.pick(quest_id, stamp)
        return dict(line.summary) if line is not None else None

    def model_for(self, quest_id: int) -> str:
        """`file:<name>` of the file whose line answered the quest."""
        line = self._answered.get(quest_id)
        return f"file:{line.file}" if line is not None else self.model

    def summarize_many(self, requests: list[SummaryRequest]) -> dict[int, Result]:
        out: dict[int, Result] = {}
        for request in requests:
            line = None if request.feedback is not None else self.pick(request.quest_id, request.stamp)
            if line is None:
                out[request.quest_id] = NotProvided(self._why_not(request))
                continue
            self._answered[request.quest_id] = line
            out[request.quest_id] = json.dumps(line.summary, ensure_ascii=False)
        return out

    def _why_not(self, request: SummaryRequest) -> str:
        lines = self._lines.get(request.quest_id, ())
        if request.feedback is not None:
            return f"quest {request.quest_id}: a file cannot answer validator feedback"
        if not lines:
            return f"quest {request.quest_id} is in none of the files"
        if all(line.stamp is None for line in lines):
            self.unstamped.add(request.quest_id)
            return f"quest {request.quest_id}: its lines have no stamp"
        self.stale.add(request.quest_id)
        return f"quest {request.quest_id}: its lines were written for another version of the quest"


# --------------------------------------------------------------------------- Anthropic providers


def _import_anthropic() -> Any:
    try:
        import anthropic  # noqa: PLC0415 - optional extra, imported only when used
    except ImportError as exc:
        raise MissingDependencyError(
            "The 'anthropic' package is not installed. It is an optional extra: run "
            "`uv sync --extra llm`, then set ANTHROPIC_API_KEY in your environment."
        ) from exc
    return anthropic


class _AnthropicBase:
    """Request building and response reading shared by the batch and direct providers."""

    paid = True
    supports_feedback = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str = DEFAULT_EFFORT,
        cache_ttl: str = "5m",
        client: Any = None,
    ) -> None:
        if cache_ttl not in ("5m", "1h"):
            raise ValueError("cache_ttl must be '5m' or '1h'")
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.cache_ttl = cache_ttl
        self._client = client
        # Summed API usage, so the CLI can print cost and confirm cache_read_input_tokens > 0.
        self.usage: dict[str, int] = {}
        # Called with (request, response_text) as each paid answer arrives, so the caller can
        # write it to disk before the run can be interrupted. Set by summarize.run.
        self._on_result: Callable[[SummaryRequest, str], None] | None = None

    def on_result(self, callback: Callable[[SummaryRequest, str], None] | None) -> None:
        self._on_result = callback

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _import_anthropic().Anthropic()  # credentials come from the environment
        return self._client

    def _params(self, request: SummaryRequest) -> dict[str, Any]:
        """Messages API parameters for one quest.

        The system prompt is byte-identical for every quest and carries the cache
        breakpoint; everything that varies lives in the user turn after it. No sampling
        parameters: claude-sonnet-5 rejects non-default temperature/top_p/top_k.
        """
        cache_control: dict[str, str] = {"type": "ephemeral"}
        if self.cache_ttl == "1h":
            cache_control["ttl"] = "1h"
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": request.system, "cache_control": cache_control}],
            "messages": [{"role": "user", "content": request.content()}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA},
            },
        }

    def _read_message(self, message: Any) -> Result:
        """Text of a finished message, or the reason it cannot be used."""
        self._add_usage(getattr(message, "usage", None))
        stop = getattr(message, "stop_reason", None)
        if stop == "refusal":
            return ProviderError("the model refused this quest", retryable=False)
        if stop == "max_tokens":
            return ProviderError("the response hit max_tokens before the JSON was complete")
        text = next((b.text for b in message.content if b.type == "text"), "")
        return text if text.strip() else ProviderError("the response had no text block")

    def _add_usage(self, usage: Any) -> None:
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens"):
            self.usage[key] = self.usage.get(key, 0) + int(getattr(usage, key, 0) or 0)


class AnthropicDirectProvider(_AnthropicBase):
    """One Messages API call per quest: full price, immediate. For small `--ids` runs."""

    def summarize_many(self, requests: list[SummaryRequest]) -> dict[int, Result]:
        anthropic = _import_anthropic()
        out: dict[int, Result] = {}
        for request in requests:
            try:
                out[request.quest_id] = self._read_message(
                    self.client.messages.create(**self._params(request)))
                if self._on_result is not None and isinstance(out[request.quest_id], str):
                    self._on_result(request, out[request.quest_id])
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                raise  # every further call would fail the same way: stop the run
            except anthropic.BadRequestError as exc:
                out[request.quest_id] = ProviderError(f"bad request: {exc.message}", retryable=False)
            except anthropic.RateLimitError as exc:  # the SDK already retried with backoff
                out[request.quest_id] = ProviderError(f"rate limited: {exc.message}")
            except anthropic.APIStatusError as exc:
                out[request.quest_id] = ProviderError(
                    f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500)
            except anthropic.APIConnectionError as exc:
                out[request.quest_id] = ProviderError(f"network error: {exc}")
        return out


class AnthropicBatchProvider(_AnthropicBase):
    """Message Batches API: half price, asynchronous (usually under an hour, at most 24).

    Submitted batch ids are journalled to `state_path` before polling starts. If the
    process dies while waiting, the next call finds the batch again and collects its
    results instead of paying for the same requests twice.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str = DEFAULT_EFFORT,
        cache_ttl: str = "1h",  # a batch can outlive the 5-minute cache; hits are best-effort
        client: Any = None,
        state_path: str | Path | None = DEFAULT_BATCH_STATE_PATH,  # None turns the journal off
        poll_initial: float = 10.0,
        poll_max: float = 120.0,
        max_batch_requests: int = MAX_BATCH_REQUESTS,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ) -> None:
        super().__init__(model, max_tokens=max_tokens, effort=effort, cache_ttl=cache_ttl,
                         client=client)
        self.state_path = Path(state_path) if state_path is not None else None
        self.poll_initial = poll_initial
        self.poll_max = poll_max
        self.max_batch_requests = max_batch_requests
        self._sleep = sleep
        self._log = log

    # -- public

    def summarize_many(self, requests: list[SummaryRequest]) -> dict[int, Result]:
        anthropic = _import_anthropic()  # fail before any work, with the install hint
        out: dict[int, Result] = {}
        by_fingerprint = {self._key(r): r for r in requests}
        for batch_id, keys in list(self._unfinished_batches()):
            wanted = {k: by_fingerprint.pop(k) for k in keys if k in by_fingerprint}
            if not wanted:
                continue
            self._log(f"resuming batch {batch_id} ({len(wanted)} requests)")
            try:
                out.update(self._collect(batch_id, wanted))
            except anthropic.NotFoundError:  # results are kept 29 days; older ones are gone
                self._journal({"batch_id": batch_id, "done": True})
                by_fingerprint.update(wanted)
            if self._on_result is not None:  # hand the paid answers over before the next batch
                for request in wanted.values():
                    result = out.get(request.quest_id)
                    if isinstance(result, str):
                        self._on_result(request, result)
        fresh = list(by_fingerprint.values())
        for start in range(0, len(fresh), self.max_batch_requests):
            chunk = {self._key(r): r for r in fresh[start:start + self.max_batch_requests]}
            collected = self._collect(self._submit(chunk), chunk)
            out.update(collected)
            if self._on_result is not None:
                for request in chunk.values():
                    result = collected.get(request.quest_id)
                    if isinstance(result, str):
                        self._on_result(request, result)
        return out

    # -- steps

    def _key(self, request: SummaryRequest) -> str:
        """custom_id: unique in the batch, and recognisable after a crash. [A-Za-z0-9_-]{1,64}."""
        return f"q{request.quest_id}-{request.fingerprint()}"

    def _submit(self, chunk: dict[str, SummaryRequest]) -> str:
        from anthropic.types.message_create_params import (  # noqa: PLC0415
            MessageCreateParamsNonStreaming,
        )
        from anthropic.types.messages.batch_create_params import Request  # noqa: PLC0415

        batch = self.client.messages.batches.create(requests=[
            Request(custom_id=key, params=MessageCreateParamsNonStreaming(**self._params(request)))
            for key, request in chunk.items()
        ])
        self._journal({"batch_id": batch.id, "model": self.model, "keys": sorted(chunk)})
        self._log(f"submitted batch {batch.id} ({len(chunk)} requests)")
        return batch.id

    def _wait(self, batch_id: str) -> None:
        """Poll until the batch has ended, backing off so an hour-long wait is ~40 calls."""
        delay = self.poll_initial
        while True:
            batch = self.client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                return
            counts = batch.request_counts
            self._log(f"batch {batch_id}: {batch.processing_status}, "
                      f"{counts.processing} processing, {counts.succeeded} done")
            self._sleep(delay)
            delay = min(delay * 1.5, self.poll_max)

    def _collect(self, batch_id: str, chunk: dict[str, SummaryRequest]) -> dict[int, Result]:
        self._wait(batch_id)
        out: dict[int, Result] = {}
        # Results arrive in any order: key by custom_id, never by position.
        for entry in self.client.messages.batches.results(batch_id):
            request = chunk.get(entry.custom_id)
            if request is not None:
                out[request.quest_id] = self._read_result(entry.result)
        for request in chunk.values():
            out.setdefault(request.quest_id, ProviderError("the batch returned no result"))
        # Only the keys handed over are done. A resumed batch collected for a subset of its
        # requests (--ids, --limit) stays open for the rest, whose results were paid for.
        self._journal({"batch_id": batch_id, "delivered": sorted(chunk)})
        return out

    def _read_result(self, result: Any) -> Result:
        match result.type:
            case "succeeded":
                return self._read_message(result.message)
            case "errored":
                kind = _error_type(result.error)
                return ProviderError(f"batch request failed: {kind}",
                                     retryable="invalid_request" not in kind)
            case "canceled" | "expired":
                return ProviderError(f"batch request {result.type}")
            case other:
                return ProviderError(f"unknown batch result type {other!r}")

    # -- journal

    def _journal(self, record: dict) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _unfinished_batches(self) -> Iterator[tuple[str, list[str]]]:
        if self.state_path is None or not self.state_path.exists():
            return
        submitted: dict[str, list[str]] = {}
        for line in self.state_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line) if line.strip() else {}
            if record.get("done"):
                submitted.pop(record["batch_id"], None)
            elif "delivered" in record and record["batch_id"] in submitted:
                left = [k for k in submitted[record["batch_id"]] if k not in set(record["delivered"])]
                if left:
                    submitted[record["batch_id"]] = left
                else:
                    submitted.pop(record["batch_id"])
            elif "batch_id" in record and record.get("model") == self.model:
                submitted[record["batch_id"]] = record["keys"]
        yield from submitted.items()


def _error_type(error: Any) -> str:
    """'invalid_request_error', 'overloaded_error', ... from a batch error in either nesting."""
    inner = getattr(error, "error", None)
    return str(getattr(inner, "type", None) or getattr(error, "type", None) or "unknown_error")

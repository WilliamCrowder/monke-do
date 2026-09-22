"""Command line for the pipeline: `python -m pipeline <command>`.

`run` is the one command the plan asks for: raw sources to MonkeDB.lua. The other commands
are its steps, for when only one of them needs repeating.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import coverage, db, export, review
from .llm import providers, summarize
from .sources import DEFAULT_SOURCES, load_all
from .sources import wago as wago_source

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "pipeline" / "db.sqlite"
RAW_DIR = ROOT / "pipeline" / "sources" / "raw"
OUT_DIR = ROOT / "pipeline" / "out"
DATA_DIR = ROOT / "addon" / "MonkeDo" / "Data"

PROVIDERS = ("none", "batch", "direct", "file")
NEWLINE = chr(10)


def _say(text: str = "") -> None:
    print(text, flush=True)


def _structure_build(conn) -> str | None:
    """The game build the quest ID list came from (wago), if any was loaded."""
    row = conn.execute(
        "SELECT build FROM known_ids WHERE build NOT LIKE 'questie%' "
        "GROUP BY build ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    return row["build"] if row is not None else None


def _summary_files(paths: list[str]) -> list[Path]:
    """Files as given; a folder means every *.jsonl in it, sorted by name."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files += sorted(path.glob("*.jsonl"))
        elif path.exists():
            files.append(path)
        else:
            raise SystemExit(f"no such summaries file or folder: {path}")
    return files


def _merged_summaries(paths: list[str]) -> Path:
    """One JSONL from several. A later file replaces an earlier one's line for the same
    quest, which is how a folder of corrections overrides a folder of first drafts."""
    files = _summary_files(paths)
    if len(files) == 1:
        return files[0]
    merged: dict[int, dict] = {}
    for path in files:
        merged.update(providers.read_summary_lines(path))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "summaries_merged.jsonl"
    with out.open("w", encoding="utf-8", newline=NEWLINE) as handle:
        for quest_id in sorted(merged):
            handle.write(json.dumps({"id": quest_id, **merged[quest_id]}, ensure_ascii=False) + NEWLINE)
    _say(f"  merged {len(files)} files, {len(merged)} quests -> {out.relative_to(ROOT)}")
    return out


def _ids(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(part) for part in value.replace(",", " ").split()]


# --------------------------------------------------------------------------- steps


def step_load(conn, args) -> int:
    names = [n.strip() for n in args.sources.split(",") if n.strip()]
    _say(f"== load: {', '.join(names)}{' (offline)' if args.offline else ''}")
    results = load_all(conn, names, RAW_DIR, offline=args.offline, build=args.wago_build)
    failed = 0
    for result in results:
        _say(f"  {result.source}: {result.rows_written} rows written, {result.rows_skipped} unchanged, "
             f"{result.objectives_written} objectives, {result.known_ids} known ids")
        for note in result.notes:
            _say(f"    note: {note}")
            failed += note.startswith("FAILED")
    build = _structure_build(conn)
    if build:
        _say(f"  structure build: {build}")
    if failed:
        _say(f"  {failed} source(s) FAILED; the rest were loaded. Exit status will be 1.")
    return 1 if failed else 0


def _make_provider(args):
    if args.provider == "batch":
        return providers.AnthropicBatchProvider(model=args.model, state_path=OUT_DIR / "batches.json")
    if args.provider == "direct":
        return providers.AnthropicDirectProvider(model=args.model)
    if args.provider == "file":
        if not args.summaries_file:
            raise SystemExit("--provider file needs --summaries-file")
        return providers.FileProvider(_merged_summaries(args.summaries_file))
    raise SystemExit(f"unknown provider {args.provider!r}")


def step_summarize(conn, args) -> None:
    _say(f"== summarize: provider {args.provider}, prompt {args.prompt_version}")
    forgotten: list[int] = []
    if args.retry_rejected:
        forgotten = [r[0] for r in conn.execute(
            "SELECT quest_id FROM summaries WHERE status = 'rejected' AND prompt_version = ?",
            (args.prompt_version,))]
        conn.execute("DELETE FROM summaries WHERE status = 'rejected' AND prompt_version = ?",
                     (args.prompt_version,))
        conn.commit()
        _say(f"  forgot {len(forgotten)} rejected summaries so they are requested again")
    if args.provider == "none":
        pinned = summarize.apply_overrides(conn, args.prompt_version)
        _say(f"  no LLM provider: {len(pinned)} pinned overrides applied, everything else exports "
             "rule-based tasks only.")
        _say("  Use --provider batch to write lore (needs ANTHROPIC_API_KEY and `uv sync --extra llm`).")
        return
    stats = summarize.run(conn, _make_provider(args), prompt_version=args.prompt_version,
                          ids=_ids(args.ids), limit=args.limit, max_retries=args.max_retries,
                          no_replay=forgotten)
    _say("  " + ", ".join(f"{key} {value}" for key, value in stats.items()))


def _shipped_count() -> int | None:
    """The record count in the MonkeDB_Meta.lua that is there now, if any."""
    try:
        text = (DATA_DIR / export.META_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"count = (\d+)", text)
    return int(match.group(1)) if match else None


def step_export(conn, args) -> int:
    build = args.build or _structure_build(conn) or "unknown"
    _say(f"== export: build {build}")
    total = conn.execute("SELECT COUNT(*) FROM quests").fetchone()[0]
    shipped = _shipped_count()
    # The Data files are tracked and ship to players. An empty database (a fresh clone with
    # no raw cache, a failed source) must not overwrite them with nothing.
    if total == 0:
        _say("  refusing to export: the quests table is empty (did the sources load?)")
        return 1
    if shipped and total < shipped // 2 and not args.force:
        _say(f"  refusing to export: {total} quests now against {shipped} records shipped before. "
             "Pass --force if that is intended.")
        return 1
    result = export.write(conn, DATA_DIR, build=build, prompt_version=args.prompt_version)
    _say(export.format_coverage(result))
    return 0


def step_coverage(conn, args) -> None:
    _say("== coverage")
    _say(coverage.report(conn))
    missing = coverage.missing_lore(conn)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "missing_lore.txt"
    path.write_text("\n".join(str(i) for i in missing) + ("\n" if missing else ""), encoding="utf-8")
    _say(f"  missing-lore backlog: {len(missing)} ids -> {path.relative_to(ROOT)}")


def step_review(conn, args) -> None:
    path = OUT_DIR / "review.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    count = review.write_sample(conn, path, seed=args.seed, prompt_version=args.prompt_version)
    _say(f"== review: {count} quests -> {path.relative_to(ROOT)} (read this before a release)")


# ------------------------------------------------------------- helpers for outside writers


def step_requests(conn, args) -> None:
    """Dump what a summary writer needs, for writers that are not an API call."""
    ids = set(_ids(args.ids) or [])
    rejected_only = args.rejected
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for quest in conn.execute("SELECT * FROM quests ORDER BY id").fetchall():
        if ids and quest["id"] not in ids:
            continue
        ctx = summarize.load_context(conn, quest)
        if not ctx.has_prose():
            continue
        cached = summarize.get_summary(conn, quest["id"], quest["text_hash"], args.prompt_version)
        if rejected_only:
            if cached is None or cached["status"] != "rejected":
                continue
        elif cached is not None and cached["status"] in ("ok", "rejected"):
            continue
        record = {"id": quest["id"], "request": summarize.build_user_message(ctx)}
        if rejected_only:
            record["previous_output"] = cached["json"]
            record["errors"] = json.loads(cached["errors"] or "[]")
        records.append(record)

    def dump(path: Path, chunk: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in chunk:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    if args.chunk_size:
        folder = Path(args.out) if args.out else OUT_DIR / "requests"
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob("chunk_*.jsonl"):
            stale.unlink()
        count = 0
        for start in range(0, len(records), args.chunk_size):
            count += 1
            dump(folder / f"chunk_{count:03d}.jsonl", records[start:start + args.chunk_size])
        _say(f"== requests: {len(records)} quests in {count} chunks -> {folder}")
        return
    out = Path(args.out) if args.out else OUT_DIR / "requests.jsonl"
    dump(out, records)
    _say(f"== requests: {len(records)} quests -> {out}")


def step_check(conn, args) -> int:
    """Validate a summaries JSONL without storing anything. One JSON line per failing quest."""
    from .validate import load_context, validate

    from .validate import sentence_initial_capitals

    summaries = providers.read_summary_lines(_merged_summaries(args.summaries_file))
    failed = 0
    suspects: dict[str, list[int]] = {}
    lowercase_seen: set[str] = set()
    for summary in summaries.values():
        for text in [summary.get("lore_monke", ""), summary.get("lore_plain", ""),
                     summary.get("group_line") or ""] + list(summary.get("tasks") or []):
            lowercase_seen.update(w for w in re.findall(r"[a-z][a-z']*", str(text)))
    for quest_id, summary in sorted(summaries.items()):
        quest = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
        if quest is None:
            errors = ["unknown quest id"]
        else:
            ctx = load_context(conn, quest)
            errors = validate(summary, ctx)
            if not errors:
                for word in sentence_initial_capitals(summary, ctx):
                    if word.lower() not in lowercase_seen:
                        suspects.setdefault(word, []).append(quest_id)
        if errors:
            failed += 1
            _say(json.dumps({"id": quest_id, "errors": errors}, ensure_ascii=False))
    if suspects:
        listed = ", ".join(f"{w} ({', '.join(map(str, ids[:5]))})" for w, ids in sorted(suspects.items()))
        _say(f"== words to eyeball (capitalised at a sentence start, never seen in lower case, "
             f"not in the quest text; invented names hide here): {listed}")
    _say(f"== check: {len(summaries)} summaries, {failed} failed")
    return 1 if failed else 0


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite file (default pipeline/db.sqlite)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, *, load=False, llm=False, out=False):
        p.add_argument("--prompt-version", default="v1")
        if load:
            p.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                           help="comma list; web sources run only when named here")
            p.add_argument("--offline", action="store_true", help="use cached raw files, no network")
            p.add_argument("--wago-build", default=wago_source.DEFAULT_BUILD)
        if llm:
            p.add_argument("--provider", choices=PROVIDERS, default="none")
            p.add_argument("--model", default=providers.DEFAULT_MODEL)
            p.add_argument("--summaries-file", action="append",
                           help="JSONL file or folder for --provider file; repeat it, later ones win")
            p.add_argument("--ids", help="only these quest ids, comma or space separated")
            p.add_argument("--limit", type=int, help="send at most this many quests this run")
            p.add_argument("--max-retries", type=int, default=2)
            p.add_argument("--retry-rejected", action="store_true",
                           help="forget rejected summaries first so they are requested again")
        if out:
            p.add_argument("--build", help="game build for MonkeDB_Meta (default: what wago loaded)")
            p.add_argument("--force", action="store_true",
                           help="export even when the record count collapsed against the shipped files")
            p.add_argument("--seed", type=int, default=0, help="review sample seed")

    add_common(sub.add_parser("run", help="load, summarize, export, coverage, review"),
               load=True, llm=True, out=True)
    add_common(sub.add_parser("load", help="run source modules into SQLite"), load=True)
    add_common(sub.add_parser("summarize", help="fill the summaries table"), llm=True)
    add_common(sub.add_parser("export", help="write addon/MonkeDo/Data/*.lua"), out=True)
    add_common(sub.add_parser("coverage", help="print the coverage report"))
    add_common(sub.add_parser("review", help="write the human spot-check sample"), out=True)
    requests = sub.add_parser("requests", help="dump summary requests as JSONL for an outside writer")
    add_common(requests)
    requests.add_argument("--ids")
    requests.add_argument("--out", help="file, or folder with --chunk-size")
    requests.add_argument("--chunk-size", type=int, help="split into chunk_NNN.jsonl files of this size")
    requests.add_argument("--rejected", action="store_true",
                          help="only rejected quests, with the validator errors and previous output")
    check = sub.add_parser("check", help="validate a summaries JSONL; stores nothing")
    add_common(check)
    check.add_argument("--summaries-file", action="append", required=True)
    return parser


STEPS = {
    "run": (step_load, step_summarize, step_export, step_coverage, step_review),
    "load": (step_load, step_coverage),
    "summarize": (step_summarize,),
    "export": (step_export,),
    "coverage": (step_coverage,),
    "review": (step_review,),
    "requests": (step_requests,),
    "check": (step_check,),
}


def main(argv: list[str] | None = None) -> int:
    # Quest text is UTF-8; a Windows console or a pipe may not be. Never crash on output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args(argv)
    conn = db.connect(args.db)
    status = 0
    try:
        for step in STEPS[args.command]:
            status = max(status, step(conn, args) or 0)
            conn.commit()
            if status and step is step_load and args.command == "run":
                _say("stopping before summarize/export because a source failed")
                break
    finally:
        conn.close()
    return status


if __name__ == "__main__":
    sys.exit(main())

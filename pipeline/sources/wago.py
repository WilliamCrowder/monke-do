"""wago.tools DB2 exports as a source of quest STRUCTURE (contract section 5).

This source never writes text rows. It gives three things:

- `QuestV2`         -> every quest ID in a game build (`known_ids`)
- `QuestObjective`  -> structured objectives with real amounts (`amount_source="db2"`)
- `QuestV2CliTask`  -> a little metadata (quest tag, minimum level) when the columns exist

What a real run found on 2026-09-21 (this corrects the older note in the data contract):

- The Forever beta IS on wago, under the product `wow_classic_beta`, as builds
  1.60.1.69876, .69893 and .69913. `QuestV2` for 1.60.1.69913 has the columns
  `ID, UniqueBitFlag, UiQuestDetailsThemeID` and 6,600 IDs, 1,742 of them at 90000 or above.
- `QuestObjective` and `QuestV2CliTask` do not exist for that build: HTTP 404 with the
  JSON body `{"errors":"Table not found."}`. Classic Era has no `QuestObjective` either.
- A build wago does not know at all answers HTTP 404 with an HTML page.

Checked again on 2026-10-13: build 1.60.1.70338 has 6,610 IDs, 1,752 of them at 90000 or above,
and still no `QuestObjective` or `QuestV2CliTask` (now HTTP 400 with the same JSON body).

All of these count as "table absent". When `QuestV2` is absent for the requested build,
the ID list of the newest `fallback_product` build is used instead and a note says so.
The build is a parameter, so nothing here changes when wago gains more Forever tables.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline import db

SOURCE = "wago"
PRIORITY = 3
NEEDS_NETWORK = True
OPTIONS: tuple[str, ...] = ("build", "fallback_product")

DEFAULT_BUILD = "1.60.1.70338"
DEFAULT_FALLBACK_PRODUCT = "wow_classic_era"
BASE_URL = "https://wago.tools"
USER_AGENT = "MonkeDoPipeline/0.1"
MIN_INTERVAL = 2.0  # seconds between requests to wago.tools, like every other fetcher here
TABLES = ("QuestV2", "QuestObjective", "QuestV2CliTask")
BOM = chr(0xFEFF)  # some CSV exports start with a byte order mark
# A game build looks like 1.60.1.69913. Anything else is refused before it becomes a URL
# parameter or a cache directory name (the build list is downloaded data).
BUILD_RE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,7}")
# An absent table is asked for again after this long, not on every run.
ABSENT_RECHECK_SECONDS = 24 * 3600


class Refused(RuntimeError):
    """wago.tools answered 403 or 429: stop this source rather than ask again."""


def is_build(value: object) -> bool:
    return isinstance(value, str) and BUILD_RE.fullmatch(value) is not None

# QuestObjective.Type -> the in-game objective type strings of the contract.
# Numbers as in TrinityCore's QuestObjectiveType. Anything not listed is "event".
OBJECTIVE_TYPES = {
    0: "monster", 1: "item", 2: "object", 3: "monster",  # 3 is "talk to"
    5: "spell", 6: "reputation", 7: "reputation", 18: "reputation",
    8: "log",  # money
    9: "player", 10: "event", 19: "event", 20: "event", 14: "event", 15: "progressbar",
    21: "monster",  # kill with label: a kill count, so it gets the "Bonk" template
}
# For these the Amount column is a standing, a sum of copper or a percentage. It is
# not "N things", and the summary validator demands every amount above 1 in the task
# line, so they are stored as 1. The real wording stays available in `text`.
UNCOUNTED_TYPES = ("reputation", "log", "progressbar")

# QuestObjective.Flags, checked against TrinityCore QuestDef.h (QuestObjectiveFlags):
# 0x02 is SEQUENCED ("not displayed until all previous objectives are completed"),
# which is NOT hidden, so those rows are kept. 0x08 is HIDDEN ("never displayed in
# quest log") and 0x40 is PART_OF_PROGRESS_BAR ("hidden objective used to calculate
# progress bar percent"); both are left out because idx must match what the player sees.
FLAG_HIDDEN = 0x08
FLAG_PART_OF_PROGRESS_BAR = 0x40

# QuestInfo.db2 IDs for the tags the addon's group line cares about.
QUEST_INFO_TAGS = {1: "Group", 41: "PvP", 62: "Raid", 81: "Dungeon", 85: "Heroic", 88: "Raid", 89: "Raid"}


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

@dataclass
class Reply:
    status: int
    text: str


Fetch = Callable[[str], Reply]


class ThrottledFetch:
    """The real HTTP GET, at most one request per `min_interval` seconds."""

    def __init__(self, min_interval: float = MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def __call__(self, url: str) -> Reply:
        import httpx  # imported here so offline runs and tests never need it

        wait = self._last + self.min_interval - time.monotonic()
        if self._last and wait > 0:
            time.sleep(wait)
        try:
            reply = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120)
        finally:
            self._last = time.monotonic()
        return Reply(reply.status_code, reply.text)


def looks_like_csv(text: str) -> bool:
    """wago answers a missing table with JSON (and sometimes an HTML error page)
    while still using a success status, so the body has to be looked at."""
    head = text.lstrip(BOM).lstrip()[:200]
    if not head or head[0] in "{[<":
        return False
    header = head.splitlines()[0]
    return "ID" in [cell.strip().strip('"') for cell in header.split(",")]


def table_csv(
    table: str, build: str, cache_dir: Path, *, offline: bool, fetch: Fetch, notes: list[str]
) -> str | None:
    """CSV text of one table for one build, or None when the table is absent.

    A build's table never changes, so a cached copy is always used. An absent table
    is asked for again on the next online run: that is how Forever will show up.
    """
    if not is_build(build):
        raise ValueError(f"not a game build: {build!r}")
    path = cache_dir / build / f"{table}.csv"
    absent = cache_dir / build / f"{table}.absent"
    if path.exists():
        return path.read_text(encoding="utf-8").lstrip(BOM)
    if offline:
        notes.append(f"{table} for build {build}: not in the cache (offline)")
        return None
    if absent.exists() and time.time() - absent.stat().st_mtime < ABSENT_RECHECK_SECONDS:
        notes.append(f"{table} for build {build}: absent at the last check; asked again in a day")
        return None
    reply = fetch(f"{BASE_URL}/db2/{table}/csv?build={build}")
    if reply.status in (403, 429):
        raise Refused(f"wago.tools answered HTTP {reply.status} for {table}; stopping the wago source")
    if reply.status != 200 or not looks_like_csv(reply.text):
        body = " ".join(reply.text.split())
        reason = "an HTML page" if body.startswith("<") else body[:80]
        notes.append(f"{table} for build {build}: table absent (HTTP {reply.status}: {reason})")
        absent.parent.mkdir(parents=True, exist_ok=True)
        absent.write_text(f"HTTP {reply.status}" + chr(10), encoding="utf-8")
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    text = reply.text.lstrip(BOM)
    path.write_text(text, encoding="utf-8")
    return text


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


def newest_build(
    product: str, cache_dir: Path, *, offline: bool, fetch: Fetch, notes: list[str]
) -> str | None:
    """Newest version of `product` from wago's build list (product -> [{version, ...}])."""
    path = cache_dir / "builds.json"
    fresh = path.exists() and time.time() - path.stat().st_mtime < ABSENT_RECHECK_SECONDS
    if offline or fresh:
        if not path.exists():
            notes.append("build list not in the cache (offline); no fallback build")
            return None
        text = path.read_text(encoding="utf-8")
    else:
        reply = fetch(f"{BASE_URL}/api/builds")
        if reply.status in (403, 429):
            raise Refused(f"wago.tools answered HTTP {reply.status} for the build list; stopping the wago source")
        if reply.status != 200:
            notes.append(f"build list: HTTP {reply.status}; no fallback build")
            return None
        text = reply.text
    try:
        builds = json.loads(text)
        versions = [b["version"] for b in builds.get(product, []) if is_build(b.get("version"))]
    except (ValueError, AttributeError, TypeError, KeyError):
        notes.append("build list: unexpected format; no fallback build")
        return None
    if not (offline or fresh):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if not versions:
        notes.append(f"build list has no product {product!r}; no fallback build")
        return None
    return max(versions, key=_version_key)


# --------------------------------------------------------------------------
# CSV -> database values (pure functions)
# --------------------------------------------------------------------------

def read_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip(BOM))))


def _int(row: dict[str, str], column: str, default: int | None = None) -> int | None:
    """Columns are looked up by header name and may be missing in some builds."""
    try:
        return int(row[column])
    except (KeyError, ValueError, TypeError):
        return default


def quest_ids(rows: list[dict[str, str]]) -> list[int]:
    return [i for i in (_int(row, "ID") for row in rows) if i is not None]


def objectives_by_quest(rows: list[dict[str, str]]) -> tuple[dict[int, list[db.Objective]], int]:
    """Group QuestObjective rows per quest, ordered by OrderIndex, numbered from 1.
    Returns the objectives and how many hidden rows were left out."""
    grouped: dict[int, list[tuple[int, int, dict[str, str]]]] = {}
    hidden = 0
    for row in rows:
        quest_id = _int(row, "QuestID")
        if quest_id is None:
            continue
        if (_int(row, "Flags", 0) or 0) & (FLAG_HIDDEN | FLAG_PART_OF_PROGRESS_BAR):
            hidden += 1
            continue
        order = (_int(row, "OrderIndex", 0) or 0, _int(row, "ID", 0) or 0)
        grouped.setdefault(quest_id, []).append((*order, row))

    result: dict[int, list[db.Objective]] = {}
    for quest_id, entries in grouped.items():
        entries.sort(key=lambda entry: entry[:2])
        objectives = []
        for idx, (_, _, row) in enumerate(entries, start=1):
            type_ = OBJECTIVE_TYPES.get(_int(row, "Type", -1), "event")
            amount = _int(row, "Amount", 1) or 1
            objectives.append(db.Objective(
                quest_id=quest_id, idx=idx, type=type_, target_id=_int(row, "ObjectID") or None,  # 0 = none
                amount=1 if type_ in UNCOUNTED_TYPES else max(1, amount),
                amount_source="db2", text=row.get("Description_lang") or None, source=SOURCE,
            ))
        result[quest_id] = objectives
    return result, hidden


def meta_from_cli_task(row: dict[str, str]) -> dict[str, int | str]:
    """Whatever quest_meta fields a QuestV2CliTask row can give. Every column is optional."""
    meta: dict[str, int | str] = {}
    min_level = _int(row, "FiltMinLevel")
    if min_level is not None and min_level > 0:
        meta["required_level"] = min_level
    tag = QUEST_INFO_TAGS.get(_int(row, "QuestInfoID", 0) or 0)
    if tag:
        meta["tag"] = tag
    return meta


# --------------------------------------------------------------------------
# load()
# --------------------------------------------------------------------------

def load(
    conn: sqlite3.Connection,
    raw_dir: Path,
    *,
    offline: bool = False,
    build: str = DEFAULT_BUILD,
    fallback_product: str = DEFAULT_FALLBACK_PRODUCT,
    fetch: Fetch | None = None,
) -> db.SourceResult:
    result = db.SourceResult(source=SOURCE)
    notes = result.notes
    cache_dir = Path(raw_dir) / "wago"
    fetch = fetch or ThrottledFetch()
    tables = {
        table: table_csv(table, build, cache_dir, offline=offline, fetch=fetch, notes=notes)
        for table in TABLES
    }

    ids_build = build
    quest_v2 = tables["QuestV2"]
    if quest_v2 is None:
        fallback = newest_build(fallback_product, cache_dir, offline=offline, fetch=fetch, notes=notes)
        if fallback and fallback != build:
            quest_v2 = table_csv("QuestV2", fallback, cache_dir, offline=offline, fetch=fetch, notes=notes)
            if quest_v2 is not None:
                ids_build = fallback
                notes.append(
                    f"QuestV2 is not on wago for build {build}; quest IDs come from "
                    f"{fallback_product} {fallback} instead"
                )
    if quest_v2 is not None:
        result.known_ids = db.add_known_ids(conn, quest_ids(read_csv(quest_v2)), ids_build)

    if tables["QuestObjective"] is not None:
        by_quest, hidden = objectives_by_quest(read_csv(tables["QuestObjective"]))
        for quest_id, objectives in by_quest.items():
            db.replace_objectives(conn, quest_id, objectives)
            result.objectives_written += len(objectives)
        if hidden:
            notes.append(f"{hidden} hidden QuestObjective rows left out (Flags 0x08 or 0x40)")

    if tables["QuestV2CliTask"] is not None:
        with_meta = 0
        for row in read_csv(tables["QuestV2CliTask"]):
            quest_id = _int(row, "ID")
            meta = meta_from_cli_task(row)
            if quest_id is not None and meta:
                db.upsert_meta(conn, quest_id, SOURCE, **meta)
                with_meta += 1
        notes.append(f"QuestV2CliTask: metadata for {with_meta} quests")
    return result

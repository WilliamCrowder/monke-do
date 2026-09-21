"""wowforevertalents.com: a fan-run site that reads quests out of the Forever beta client.

BEFORE THE FIRST REAL RUN: ask the site's owner for permission (a requirement of the
build plan). This module never runs by default. It runs only when the source name
`wowforevertalents` is given explicitly in `--sources`, and never from tests or CI.

What was looked at, on 2026-09-21, with six polite requests (robots.txt, the two
sitemap files, the quest index and two quest pages):

- robots.txt allows `/` and disallows `/api/`. This module never asks for `/api/`.
- The quest index is `/quests/`. Every quest is a link `a.qh-name` whose href is
  `/quests/<slug>-<questID>/`. 75 quests were listed, 15 of them new in Forever.
- A quest page is `article.qi`:
    `h1`                      title (a trailing `<i class="mark new">` star is decoration)
    `p.qi-by`                 "Level 22 · can be taken from level 15 · Dungeon quest in ..."
    `p.qp-summary`            the short objectives sentence
    `h2.qp-h` "Objectives"    then `ul.qp-obj > li`, one line per objective, text only
    `h2.qp-h` "Who takes it in"  then `ul.qp-npcs > li` with `span.qp-role`
                              ("Turned in to") and `b.qp-npc` (the name)
    `h2.qp-h` "Description"   then one `p.qp-text` per paragraph
    `h2.qp-h` "Rewards"       items, `span.qp-xp` with the XP, reputation badges
  Placeholders are rendered as `<name>` and so on (escaped in the HTML).

NOT VERIFIED: neither sampled page had progress or completion text, so the heading
names for those ("Progress", "Completion") are a best guess. `SECTION_FIELDS` is the
one place to fix when a real page shows otherwise. The objective lines carry no type
and no target ID, so this module writes no `objectives` rows.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from pipeline import db
from pipeline.placeholders import normalise
from pipeline.sources.forever_web import (
    FetchError, NotCached, PoliteFetcher, RobotsDisallowed, StopFetching,
)

SOURCE = "wowforevertalents"
PRIORITY = 1
NEEDS_NETWORK = True
OPTIONS: tuple[str, ...] = ()

BASE_URL = "https://wowforevertalents.com"
INDEX_PATH = "/quests/"
INDEX_MAX_AGE = 24 * 3600.0      # look for newly listed quests once a day at most
PAGE_MAX_AGE = 7 * 24 * 3600.0   # beta text changes; re-read a quest page weekly at most

_QUEST_PATH = re.compile(r"^/quests/[^/]*?-(\d+)/?$")
# Lower-cased heading text -> QuestRow field. See NOT VERIFIED above.
SECTION_FIELDS = {"description": "detail", "progress": "progress", "completion": "complete"}
_TAGS = {"dungeon": "Dungeon", "raid": "Raid", "battleground": "PvP", "group": "Group", "elite": "Elite"}


def quest_id_from_url(url: str) -> int | None:
    match = _QUEST_PATH.match(urlsplit(url).path)
    return int(match.group(1)) if match else None


def parse_index(html: str) -> list[str]:
    """Absolute URLs of every quest page linked from the index, in page order, no repeats."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for link in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, link["href"])
        if urlsplit(url).netloc != urlsplit(BASE_URL).netloc:
            continue
        if quest_id_from_url(url) is not None and url not in urls:
            urls.append(url)
    return urls


def _text(node: Tag | None) -> str | None:
    """Visible text of a node with placeholders normalised. `<br>` is the client's `$b`."""
    if node is None:
        return None
    for line_break in node.find_all("br"):
        line_break.replace_with("$b")
    return normalise(db.clean(node.get_text()))


def _section_paragraphs(heading: Tag) -> list[str]:
    """The `p.qp-text` paragraphs between this heading and the next one."""
    paragraphs = []
    for sibling in heading.find_next_siblings():
        if sibling.name == "h2":
            break
        if sibling.name == "p" and "qp-text" in (sibling.get("class") or []):
            text = _text(sibling)
            if text:
                paragraphs.append(text)
    return paragraphs


def _turnin_npc(article: Tag) -> str | None:
    for item in article.select("ul.qp-npcs li"):
        role = item.select_one(".qp-role")
        if role is not None and "turned in" in role.get_text().lower():
            return db.clean(item.select_one(".qp-npc").get_text()) if item.select_one(".qp-npc") else None
    return None


def parse_quest(html: str, url: str) -> db.QuestRow | None:
    """One quest page -> QuestRow, or None when the page is not a quest page.

    Paragraphs are joined with `$b$b`, which is how the client itself separates them,
    so the text compares equal to a client-format source.
    """
    quest_id = quest_id_from_url(url)
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.qi")
    if quest_id is None or article is None:
        return None
    heading = article.find("h1")
    if heading is not None:
        for mark in heading.select("i.mark"):
            mark.decompose()
    row = db.QuestRow(
        id=quest_id, source=SOURCE, title=_text(heading),
        objectives_text=_text(article.select_one("p.qp-summary")),
        turnin_npc=_turnin_npc(article),
    )
    for section in article.select("h2.qp-h"):
        name = (section.get_text() or "").strip().lower()
        field = next((f for key, f in SECTION_FIELDS.items() if key in name), None)
        paragraphs = _section_paragraphs(section) if field else []
        if paragraphs:
            setattr(row, field, "$b$b".join(paragraphs))
    if row.title is None and row.detail is None and row.objectives_text is None:
        return None
    return row


def parse_meta(html: str) -> dict[str, int | str]:
    """Level, required level, tag, XP and group size, where the page states them."""
    soup = BeautifulSoup(html, "html.parser")
    meta: dict[str, int | str] = {}
    byline = soup.select_one("p.qi-by")
    byline_text = byline.get_text(" ") if byline else ""
    if match := re.search(r"\bLevel (\d+)", byline_text):
        meta["level"] = int(match.group(1))
    if match := re.search(r"from level (\d+)", byline_text):
        meta["required_level"] = int(match.group(1))
    if match := re.search(r"\b(Dungeon|Raid|Battleground|Group|Elite) quest", byline_text, re.IGNORECASE):
        meta["tag"] = _TAGS[match.group(1).lower()]
    xp = soup.select_one(".qp-xp")
    if xp is not None and (digits := re.sub(r"\D", "", xp.get_text())):
        meta["xp"] = int(digits)
    take = soup.select_one("p.qp-take")
    if take is not None and (match := re.search(r"(\d+) players", take.get_text(" "))):
        meta["group_size"] = int(match.group(1))
    return meta


def load(
    conn: sqlite3.Connection, raw_dir: Path, *, offline: bool = False,
    fetcher: PoliteFetcher | None = None,
) -> db.SourceResult:
    """Read the index, then each quest page, politely. A 403 or 429 ends the run but
    keeps everything written so far."""
    result = db.SourceResult(source=SOURCE)
    fetcher = fetcher or PoliteFetcher(BASE_URL, Path(raw_dir) / SOURCE, offline=offline)
    skipped = 0
    try:
        index = fetcher.get(INDEX_PATH, max_age=INDEX_MAX_AGE)
        urls = parse_index(index.html)
        for url in urls:
            try:
                page = fetcher.get(url, max_age=PAGE_MAX_AGE)
            except (NotCached, RobotsDisallowed, FetchError) as problem:
                skipped += 1
                if skipped <= 5:
                    result.notes.append(str(problem))
                continue
            row = parse_quest(page.html, url)
            if row is None:
                result.notes.append(f"{url}: not recognised as a quest page")
                continue
            row.fetched_at = page.fetched_at
            if db.upsert_source_row(conn, row):
                result.rows_written += 1
            else:
                result.rows_skipped += 1
            meta = parse_meta(page.html)
            if meta:
                db.upsert_meta(conn, row.id, SOURCE, **meta)
        result.notes.append(f"{len(urls)} quests listed, {skipped} pages skipped, "
                            f"{fetcher.requests_made} requests made")
    except StopFetching as stop:
        result.notes.append(f"stopped early: {stop}")
    return result

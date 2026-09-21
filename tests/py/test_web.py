"""The web source, tested without any network: synthetic HTML and a fake transport."""

import os
import time
from pathlib import Path

import pytest

from pipeline import db
from pipeline.sources import forever_web
from pipeline.sources.forever_web import (
    FetchError, NotCached, PoliteFetcher, RobotsDisallowed, StopFetching,
)
from pipeline.sources.sites import wowforevertalents as site

FIXTURES = Path(__file__).parent / "fixtures" / "web"
BASE = "https://wowforevertalents.com"
NEW_URL = f"{BASE}/quests/the-missing-lantern-95001/"
OLD_URL = f"{BASE}/quests/red-silk-bandanas-214/"
ROBOTS = "User-agent: *\nAllow: /\nDisallow: /api/\n"


def _read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeSite:
    """A transport that answers from a dict and records what was asked, and when."""

    def __init__(self, pages, fake_time=None):
        self.pages = pages
        self.time = fake_time
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, self.time.now if self.time else None, headers.get("User-Agent")))
        return self.pages.get(url, (404, "not found"))


def _site_pages():
    return {
        f"{BASE}/robots.txt": (200, ROBOTS),
        f"{BASE}/quests/": (200, _read("index.html")),
        NEW_URL: (200, _read("quest_new.html")),
        OLD_URL: (200, _read("quest_old.html")),
    }


def _fetcher(tmp_path, pages, **kwargs):
    fake_time = FakeTime()
    transport = FakeSite(pages, fake_time)
    fetcher = PoliteFetcher(BASE, tmp_path / "cache", transport=transport,
                            sleep=fake_time.sleep, clock=fake_time.clock, **kwargs)
    return fetcher, transport, fake_time


# -- pure parsers ------------------------------------------------------------

def test_parse_index_lists_each_quest_once_and_only_this_site():
    assert site.parse_index(_read("index.html")) == [NEW_URL, OLD_URL]


def test_quest_id_from_url():
    assert site.quest_id_from_url(NEW_URL) == 95001
    assert site.quest_id_from_url(f"{BASE}/quests/light-s-justice-92421") == 92421
    assert site.quest_id_from_url(f"{BASE}/quests/") is None
    assert site.quest_id_from_url(f"{BASE}/dungeons/mossy-hollow-12/") is None


def test_parse_quest_new_in_forever():
    row = site.parse_quest(_read("quest_new.html"), NEW_URL)
    assert (row.id, row.source) == (95001, "wowforevertalents")
    assert row.title == "The Missing Lantern"  # the decorative star is not part of the title
    assert row.objectives_text == (
        "Find the keeper's lantern in Mossy Hollow and bring 3 Lantern Shards to Keeper Odwin."
    )
    assert row.detail == (
        "The lantern went dark three nights ago, $n.$b$b"
        "No $r has dared the hollow since. My $gbrother:sister; in arms, will you go?$b"
        "Take this, $c, and tell them $ghis:her; keeper sent you."
    )
    assert row.progress == "Is the hollow still dark?"
    assert row.complete == "You found it! The light will hold, thanks to you."
    assert row.turnin_npc == "Keeper Odwin"  # "Given by" is a different role
    assert "Rewards" not in (row.detail + row.complete)
    assert "must not become quest text" not in (row.detail + row.progress + row.complete)


def test_parse_quest_with_fewer_sections():
    row = site.parse_quest(_read("quest_old.html"), OLD_URL)
    assert row.id == 214 and row.title == "Red Silk Bandanas"
    assert row.detail == "An invented description for the fixture."
    assert row.progress is None and row.complete is None and row.turnin_npc is None


def test_parse_quest_rejects_other_pages():
    assert site.parse_quest(_read("index.html"), f"{BASE}/quests/") is None
    assert site.parse_quest(_read("index.html"), NEW_URL) is None
    assert site.parse_quest("<html><body><article class='qi'></article></body></html>", NEW_URL) is None


def test_parse_meta():
    assert site.parse_meta(_read("quest_new.html")) == {
        "level": 22, "required_level": 15, "tag": "Dungeon", "xp": 2200, "group_size": 5,
    }
    assert site.parse_meta(_read("quest_old.html")) == {"level": 17, "required_level": 14, "xp": 900}
    assert site.parse_meta("<html></html>") == {}


# -- PoliteFetcher -------------------------------------------------------------

def test_robots_first_then_two_seconds_between_requests(tmp_path):
    fetcher, transport, fake_time = _fetcher(tmp_path, _site_pages())
    fetcher.get("/quests/")
    fake_time.now += 0.5  # some parsing time passes; the fetcher must wait out the rest
    fetcher.get(NEW_URL)
    urls = [call[0] for call in transport.calls]
    assert urls == [f"{BASE}/robots.txt", f"{BASE}/quests/", NEW_URL]
    times = [call[1] for call in transport.calls]
    assert all(later - earlier >= 2.0 for earlier, later in zip(times, times[1:]))
    assert fake_time.sleeps == [2.0, 1.5]
    assert {call[2] for call in transport.calls} == {"MonkeDoPipeline/0.1"}


def test_disallowed_url_is_never_requested(tmp_path):
    fetcher, transport, _ = _fetcher(tmp_path, _site_pages())
    with pytest.raises(RobotsDisallowed):
        fetcher.get("/api/quests.json")
    assert [call[0] for call in transport.calls] == [f"{BASE}/robots.txt"]
    with pytest.raises(ValueError, match="one fetcher serves one site"):
        fetcher.get("https://www.wowhead.com/quest=214")


@pytest.mark.parametrize(("robots", "path", "allowed"), [
    (["User-agent: *", "Allow: /", "Disallow: /api/"], "/api/quests.json", False),  # the real site's order
    (["User-agent: *", "Disallow: /api/", "Allow: /"], "/api/quests.json", False),
    (["User-agent: *", "Allow: /", "Disallow: /api/"], "/quests/", True),
    (["User-agent: *", "Disallow: /", "Allow: /quests/"], "/quests/x-1/", True),
    (["User-agent: *", "Disallow: /", "Allow: /quests/"], "/talents/", False),
    (["User-agent: *", "Disallow: /quests/", "Allow: /quests/"], "/quests/x-1/", True),  # tie: allow wins
    (["User-agent: MonkeDoPipeline", "Disallow: /", "", "User-agent: *", "Allow: /"], "/quests/", False),
])
def test_robots_longest_rule_wins(tmp_path, robots, path, allowed):
    pages = _site_pages()
    pages[f"{BASE}/robots.txt"] = (200, chr(10).join(robots))
    pages[f"{BASE}{path}"] = (200, "<html></html>")
    fetcher, _, _ = _fetcher(tmp_path, pages)
    if allowed:
        assert fetcher.get(path).from_cache is False
    else:
        with pytest.raises(RobotsDisallowed):
            fetcher.get(path)


def test_pages_are_cached_on_disk_and_served_from_there(tmp_path):
    fetcher, transport, _ = _fetcher(tmp_path, _site_pages())
    first = fetcher.get(NEW_URL)
    again = fetcher.get(NEW_URL)
    assert (first.from_cache, again.from_cache) == (False, True)
    assert again.html == first.html and again.fetched_at == first.fetched_at
    assert fetcher.requests_made == 2  # robots.txt and the page, once

    # A new fetcher (the next run) finds the same cache and makes no request at all.
    second_run, transport2, _ = _fetcher(tmp_path, _site_pages())
    assert second_run.get(NEW_URL).from_cache is True
    assert transport2.calls == []
    names = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert len(names) == 2 and "index.json" in names and all(len(n) <= 25 for n in names)


def test_max_age_refetches_a_stale_page(tmp_path):
    fetcher, transport, _ = _fetcher(tmp_path, _site_pages())
    fetcher.get(NEW_URL)
    cached = next(p for p in (tmp_path / "cache").iterdir() if p.suffix == ".html")
    old = time.time() - 10 * 24 * 3600
    os.utime(cached, (old, old))
    assert fetcher.get(NEW_URL, max_age=30 * 24 * 3600).from_cache is True
    assert fetcher.get(NEW_URL, max_age=24 * 3600).from_cache is False
    assert [call[0] for call in transport.calls].count(NEW_URL) == 2


@pytest.mark.parametrize("status", [403, 429])
def test_403_or_429_stops_the_whole_run(tmp_path, status):
    pages = _site_pages()
    pages[NEW_URL] = (status, "go away")
    fetcher, transport, _ = _fetcher(tmp_path, pages)
    with pytest.raises(StopFetching, match=str(status)):
        fetcher.get(NEW_URL)
    with pytest.raises(StopFetching):
        fetcher.get(OLD_URL)  # no further request is made, not even for a different page
    assert [call[0] for call in transport.calls] == [f"{BASE}/robots.txt", NEW_URL]
    assert list((tmp_path / "cache").glob("*.html")) == []  # the refusal page is not cached


def test_other_errors_skip_one_page_only(tmp_path):
    fetcher, _, _ = _fetcher(tmp_path, _site_pages())
    with pytest.raises(FetchError, match="404"):
        fetcher.get("/quests/gone-1/")
    assert fetcher.get(OLD_URL).from_cache is False


def test_robots_edge_cases(tmp_path):
    pages = _site_pages()
    del pages[f"{BASE}/robots.txt"]  # 404: no rules, everything allowed
    fetcher, _, _ = _fetcher(tmp_path / "a", pages)
    assert fetcher.get(OLD_URL).html

    pages[f"{BASE}/robots.txt"] = (503, "down")  # rules unknown: do not guess
    fetcher, transport, _ = _fetcher(tmp_path / "b", pages)
    with pytest.raises(StopFetching):
        fetcher.get(OLD_URL)
    assert len(transport.calls) == 1

    pages[f"{BASE}/robots.txt"] = (200, "User-agent: *\nCrawl-delay: 7\nDisallow: /api/\n")
    fetcher, transport, fake_time = _fetcher(tmp_path / "c", pages)
    fetcher.get(OLD_URL)
    assert fake_time.sleeps == [7.0]


def test_offline_never_touches_the_network(tmp_path):
    online, _, _ = _fetcher(tmp_path, _site_pages())
    online.get(NEW_URL)

    def no_network(url, headers):
        raise AssertionError(f"offline fetcher asked for {url}")

    offline = PoliteFetcher(BASE, tmp_path / "cache", offline=True, transport=no_network)
    assert offline.get(NEW_URL).from_cache is True
    with pytest.raises(NotCached):
        offline.get(OLD_URL)


def test_default_interval_is_two_seconds():
    assert PoliteFetcher(BASE, Path("unused")).min_interval == 2.0
    assert "Wowhead" in forever_web.__doc__  # the no-scraping note stays where contributors look


# -- the site module's load() ------------------------------------------------------

def test_load_writes_rows_and_meta(tmp_path):
    fetcher, transport, _ = _fetcher(tmp_path, _site_pages())
    conn = db.connect()
    result = site.load(conn, tmp_path, fetcher=fetcher)
    assert (result.source, result.rows_written, result.rows_skipped) == ("wowforevertalents", 2, 0)
    assert not any("/api/" in call[0] for call in transport.calls)
    row = conn.execute("SELECT * FROM source_rows WHERE id = 95001").fetchone()
    assert row["source"] == "wowforevertalents" and row["turnin_npc"] == "Keeper Odwin"
    assert row["detail"].startswith("The lantern went dark three nights ago, $n.")
    meta = conn.execute("SELECT * FROM quest_meta WHERE quest_id = 95001").fetchone()
    assert (meta["level"], meta["required_level"], meta["xp"], meta["group_size"], meta["tag"]) == (
        22, 15, 2200, 5, "Dungeon")
    assert conn.execute("SELECT COUNT(*) FROM objectives").fetchone()[0] == 0

    again = site.load(conn, tmp_path, fetcher=fetcher)
    assert (again.rows_written, again.rows_skipped) == (0, 2)


def test_load_stops_cleanly_on_429_and_keeps_earlier_rows(tmp_path):
    pages = _site_pages()
    pages[OLD_URL] = (429, "slow down")
    fetcher, _, _ = _fetcher(tmp_path, pages)
    conn = db.connect()
    result = site.load(conn, tmp_path, fetcher=fetcher)
    assert result.rows_written == 1
    assert any("stopped early: HTTP 429" in note for note in result.notes)
    assert [r[0] for r in conn.execute("SELECT id FROM source_rows")] == [95001]


def test_load_offline_from_a_seeded_cache(tmp_path):
    seed = PoliteFetcher(BASE, tmp_path / "wowforevertalents", offline=True)
    seed.store("/quests/", _read("index.html"), "2026-09-20T10:00:00Z")
    seed.store(NEW_URL, _read("quest_new.html"), "2026-09-20T10:00:05Z")
    conn = db.connect()
    result = site.load(conn, tmp_path, offline=True)
    assert result.rows_written == 1  # the second quest page is not cached: skipped, not fatal
    assert any("1 pages skipped" in note for note in result.notes)
    fetched_at = conn.execute("SELECT fetched_at FROM source_rows WHERE id = 95001").fetchone()[0]
    assert fetched_at == "2026-09-20T10:00:05Z"
    with pytest.raises(NotCached):
        site.load(db.connect(), tmp_path / "nothing-here", offline=True)

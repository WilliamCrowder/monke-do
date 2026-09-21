"""Shared polite-fetch machinery for Forever fan sites (contract section 5).

One module per site lives in `pipeline/sources/sites/`. Each of them gets its pages
through `PoliteFetcher`, which is where the rules of the contract are enforced once:

- robots.txt is checked (urllib.robotparser) before every request
- at least 2 seconds between requests, more if robots.txt asks for a crawl delay
- raw HTML is cached on disk, keyed by URL, and served from there when present
- HTTP 403 or 429 raises `StopFetching`, which ends the whole source run cleanly
- web sources run only when named explicitly in `--sources`, never from tests or CI

Adding a site: copy `sites/wowforevertalents.py`, write `parse_index` and
`parse_quest` as pure functions with a synthetic fixture test, register the module
in `pipeline/sources/__init__.py`, and ask the site's owner before the first run.

NOTE FOR CONTRIBUTORS: do NOT add a Wowhead fetcher here. Wowhead's terms of use
forbid scraping, and this project keeps to them. Linking to Wowhead is fine;
fetching its pages from this pipeline is not.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pipeline import db

DEFAULT_USER_AGENT = "MonkeDoPipeline/0.1"

# (url, headers) -> (status code, body text). Tests pass a fake; the default uses httpx.
Transport = Callable[[str, dict[str, str]], tuple[int, str]]


class StopFetching(Exception):
    """The site told us to go away (HTTP 403 or 429). Make no further requests this run."""


class RobotsDisallowed(Exception):
    """robots.txt does not allow this URL. Skip it; other URLs may still be fine."""


class NotCached(Exception):
    """Offline mode and the page is not in the cache."""


class FetchError(Exception):
    """Any other failed request for one page (404, 500, ...). Skip the page."""


@dataclass
class Page:
    url: str
    html: str
    fetched_at: str  # UTC ISO 8601, when the page came off the network
    from_cache: bool


def _httpx_transport(url: str, headers: dict[str, str]) -> tuple[int, str]:
    import httpx  # imported here so offline runs and tests never need it

    reply = httpx.get(url, headers=headers, follow_redirects=True, timeout=60)
    return reply.status_code, reply.text


def most_specific_rule_first(parser: urllib.robotparser.RobotFileParser) -> None:
    """Make `can_fetch` follow RFC 9309, where the longest matching rule wins.

    urllib.robotparser takes the FIRST matching rule instead. For the very common
    `Allow: /` followed by `Disallow: /api/` it would allow everything, /api/ included.
    Sorting each group's rules by path length (Allow first on a tie, as the RFC says)
    turns first-match into longest-match. robotparser does not know `*` and `$`
    wildcards at all; such rules are compared literally.
    """
    groups = list(parser.entries)
    if parser.default_entry is not None:
        groups.append(parser.default_entry)
    for group in groups:
        group.rulelines.sort(key=lambda rule: (len(rule.path), rule.allowance), reverse=True)


class PoliteFetcher:
    """GET pages of one site slowly, obeying robots.txt, with an on-disk cache."""

    def __init__(
        self,
        base_url: str,
        cache_dir: Path,
        min_interval: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        *,
        max_age: float | None = None,
        offline: bool = False,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.user_agent = user_agent
        self.max_age = max_age  # seconds; None means a cached page never expires
        self.offline = offline
        self._transport = transport or _httpx_transport
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._robots: urllib.robotparser.RobotFileParser | None = None
        self._stopped: str | None = None
        self.requests_made = 0

    # -- cache ---------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        # Short, fixed-length names: the repository sits under a long Windows path.
        return self.cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:20] + ".html")

    def _index(self) -> dict:
        path = self.cache_dir / "index.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def store(self, url: str, html: str, fetched_at: str | None = None) -> None:
        """Put a page into the cache. Also how tests and manual saves seed it."""
        url = self.absolute(url)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(url)
        path.write_text(html, encoding="utf-8")
        index = self._index()
        index[path.name] = {"url": url, "fetched_at": fetched_at or db.utcnow()}
        (self.cache_dir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")

    def _cached(self, url: str, max_age: float | None) -> Page | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        if not self.offline and max_age is not None and time.time() - path.stat().st_mtime > max_age:
            return None
        fetched_at = self._index().get(path.name, {}).get("fetched_at") or db.utcnow()
        return Page(url, path.read_text(encoding="utf-8"), fetched_at, from_cache=True)

    # -- network -------------------------------------------------------------

    def absolute(self, url: str) -> str:
        url = urljoin(self.base_url, url)
        if urlsplit(url).netloc != urlsplit(self.base_url).netloc:
            raise ValueError(f"{url} is not on {self.base_url}; one fetcher serves one site")
        return url

    def _request(self, url: str) -> tuple[int, str]:
        """One throttled GET. 403 and 429 end the run for every later URL too."""
        if self._stopped:
            raise StopFetching(self._stopped)
        if self._last_request is not None:
            wait = self._last_request + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            status, text = self._transport(url, {"User-Agent": self.user_agent})
        finally:
            self._last_request = self._clock()
            self.requests_made += 1
        if status in (403, 429):
            self._stopped = f"HTTP {status} from {url}"
            raise StopFetching(self._stopped)
        return status, text

    def _load_robots(self) -> urllib.robotparser.RobotFileParser:
        """Fetch robots.txt once per run, through the same throttle as everything else."""
        if self._robots is not None:
            return self._robots
        robots_url = urljoin(self.base_url, "/robots.txt")
        status, text = self._request(robots_url)
        parser = urllib.robotparser.RobotFileParser(robots_url)
        if status == 200:
            parser.parse(text.splitlines())
        elif 400 <= status < 500:
            parser.parse([])  # no robots.txt: everything is allowed
        else:
            self._stopped = f"robots.txt answered HTTP {status}; the rules are unknown"
            raise StopFetching(self._stopped)
        most_specific_rule_first(parser)
        delay = parser.crawl_delay(self.user_agent)
        if delay is not None and float(delay) > self.min_interval:
            self.min_interval = float(delay)
        self._robots = parser
        return parser

    def get(self, url: str, *, max_age: float | None = None) -> Page:
        """The page at `url` (absolute, or relative to the site), from cache when possible."""
        url = self.absolute(url)
        page = self._cached(url, max_age if max_age is not None else self.max_age)
        if page is not None:
            return page
        if self.offline:
            raise NotCached(f"{url} is not in {self.cache_dir} and offline mode is on")
        if not self._load_robots().can_fetch(self.user_agent, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        status, text = self._request(url)
        if status != 200:
            raise FetchError(f"HTTP {status} from {url}")
        fetched_at = db.utcnow()
        self.store(url, text, fetched_at)
        return Page(url, text, fetched_at, from_cache=False)

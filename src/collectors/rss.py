"""RSS and Atom collector. Feed first, article body via trafilatura when the
feed only carries a short summary."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import feedparser
import requests
import trafilatura

from ..schema import Item, make_item, strip_html, truncate_text, utcnow

log = logging.getLogger("collectors.rss")

USER_AGENT = "daily-brief/0.1 (personal RSS digest; +https://github.com/klhpicture-jpg/daily-brief)"
# Some publishers (Cloudflare fronted sites, Substack) answer 403 to anything that
# is not a browser. We try the polite agent first and fall back once.
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
FEED_TIMEOUT = 15
BODY_TIMEOUT = 10
SUMMARY_IS_ENOUGH = 600      # chars; above this, skip the body fetch entirely
MAX_ENTRIES_PER_FEED = 25
# Status codes that usually mean "you do not look like a browser", not "go away".
RETRY_AS_BROWSER = {403, 406, 429, 503}
# Ask for a feed explicitly. Some servers hand an HTML page to anyone who does not.
FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"

def fetch(url: str, timeout: int = FEED_TIMEOUT, browser: bool = False) -> requests.Response:
    """GET a URL, retried once as a browser when the server turns us away."""
    agent = BROWSER_AGENT if browser else USER_AGENT
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": agent, "Accept": FEED_ACCEPT})
    if not browser and resp.status_code in RETRY_AS_BROWSER:
        log.info("%s answered %d, retrying with a browser user agent", url, resp.status_code)
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": BROWSER_AGENT, "Accept": "*/*"})
    resp.raise_for_status()
    return resp


def fetch_feed(url: str, timeout: int = FEED_TIMEOUT):
    """Fetch and parse a feed.

    A bot wall answers 200 with an HTML page rather than an error, so a parse
    that finds no entries is not proof the feed is dead. Ask once more as a
    browser before believing it.
    """
    parsed = feedparser.parse(fetch(url, timeout).content)
    if parsed.entries:
        return parsed
    retry = feedparser.parse(fetch(url, timeout, browser=True).content)
    if retry.entries:
        log.info("%s only serves its feed to a browser user agent", url)
        return retry
    return parsed


def _read_feed(url: str):
    if url.startswith("file://"):
        return feedparser.parse(Path(url[len("file://"):]).read_bytes())
    return fetch_feed(url)


def fetch_body(url: str) -> str:
    """Full article text, or empty string. Never raises."""
    try:
        resp = fetch(url, timeout=BODY_TIMEOUT)
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False, url=url)
        return text or ""
    except (requests.RequestException, ValueError) as exc:
        log.warning("body fetch failed for %s: %s: %s", url, type(exc).__name__, exc)
        return ""


def _entry_text(entry) -> str:
    content = entry.get("content") or []
    if content and content[0].get("value"):
        return strip_html(content[0]["value"])
    return strip_html(entry.get("summary") or entry.get("description") or "")


def collect_feed(feed: dict, since: datetime) -> list[Item]:
    name = feed.get("name") or feed.get("url")
    url = feed["url"]
    source_type = feed.get("source_type", "rss")
    now = utcnow()
    parsed = _read_feed(url)
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"feed did not parse: {parsed.bozo_exception}")

    items: list[Item] = []
    for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
        link = entry.get("link") or ""
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        item = make_item(
            source=name,
            source_type=source_type,
            title=entry.get("title") or "",
            url=link,
            published_at=published,
            author=entry.get("author"),
            text=_entry_text(entry),
            meta={"feed": url, "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")]},
            collected_at=now,
        )
        if item.published_at < since:
            continue
        if source_type == "podcast":
            enclosures = [e for e in entry.get("enclosures", []) if (e.get("type") or "").startswith("audio/")]
            if enclosures:
                item.meta["audio_url"] = enclosures[0].get("href")
            item.meta["duration"] = entry.get("itunes_duration")
        elif len(item.text) < SUMMARY_IS_ENOUGH and link and not url.startswith("file://"):
            body = fetch_body(link)
            if len(body) > len(item.text):
                item.text = truncate_text(body)
                item.meta["body_fetched"] = True
        items.append(item)
    return items


def collect(config: list[dict], since: datetime) -> list[Item]:
    """Whole-section entry point. main() prefers the per-feed units."""
    out: list[Item] = []
    for feed in config or []:
        out.extend(collect_feed(feed, since))
    return out

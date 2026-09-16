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
FEED_TIMEOUT = 15
BODY_TIMEOUT = 10
SUMMARY_IS_ENOUGH = 600      # chars; above this, skip the body fetch entirely
MAX_ENTRIES_PER_FEED = 25


def _read_feed(url: str) -> bytes:
    if url.startswith("file://"):
        return Path(url[len("file://"):]).read_bytes()
    resp = requests.get(url, timeout=FEED_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.content


def fetch_body(url: str) -> str:
    """Full article text, or empty string. Never raises."""
    try:
        resp = requests.get(url, timeout=BODY_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
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
    now = utcnow()
    parsed = feedparser.parse(_read_feed(url))
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"feed did not parse: {parsed.bozo_exception}")

    items: list[Item] = []
    for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
        link = entry.get("link") or ""
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        item = make_item(
            source=name,
            source_type="rss",
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
        if len(item.text) < SUMMARY_IS_ENOUGH and link and not url.startswith("file://"):
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

"""One item schema for every collector, plus the normalize helpers.

Collectors are dumb: they build Items through make_item() and nothing else.
Intelligence (ranking, writing) lives downstream and only ever sees Items.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as dateparser

TEXT_LIMIT = 8000
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid"}
SOURCE_TYPES = ("rss", "podcast", "web", "linkedin", "twitter")


@dataclass
class Item:
    hash: str                # sha256 of canonical url, or of title+source when no url
    source: str              # "The Verge", "Lenny's Podcast", "competitor.com"
    source_type: str         # rss | podcast | web | linkedin | twitter
    title: str
    url: str
    published_at: datetime   # tz-aware UTC, falls back to collection time
    author: str | None
    text: str                # body, transcript, or post content, max 8000 chars
    meta: dict = field(default_factory=dict)
    # Filled in by the ranker, never by a collector.
    score: int | None = None
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        return d


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None, fallback: datetime | None = None) -> datetime:
    """Return a tz-aware UTC datetime. Naive input is assumed to be UTC."""
    if dt is None:
        return fallback or utcnow()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_datetime(value: Any, fallback: datetime | None = None) -> datetime:
    """Parse a string, struct_time or datetime into tz-aware UTC. Never raises."""
    if value is None or value == "":
        return ensure_utc(None, fallback)
    if isinstance(value, datetime):
        return ensure_utc(value, fallback)
    try:
        if hasattr(value, "tm_year"):  # time.struct_time from feedparser, already UTC
            return datetime(*value[:6], tzinfo=timezone.utc)
        return ensure_utc(dateparser.parse(str(value)), fallback)
    except (ValueError, OverflowError, TypeError):
        return ensure_utc(None, fallback)


def canonicalize_url(url: str) -> str:
    """Strip utm_*, click ids, trailing slash and fragment. Removes most duplicates."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.netloc:
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    path = re.sub(r"/+$", "", parts.path) or ""
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(query), ""))


def make_hash(url: str, title: str = "", source: str = "") -> str:
    canonical = canonicalize_url(url)
    basis = canonical if canonical else f"{title.strip().lower()}|{source.strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")


def strip_html(value: str | None) -> str:
    """Cheap tag stripper for feed summaries. Trafilatura handles real pages."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value.replace("</p>", "\n").replace("<br", "\n<br"))
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _NL_RE.sub("\n\n", text).strip()


def truncate_text(text: str | None, limit: int = TEXT_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def make_item(
    *,
    source: str,
    source_type: str,
    title: str,
    url: str,
    published_at: Any = None,
    author: str | None = None,
    text: str = "",
    meta: dict | None = None,
    collected_at: datetime | None = None,
) -> Item:
    """The only way a collector should build an Item. Normalizes everything."""
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source_type {source_type!r}, expected one of {SOURCE_TYPES}")
    clean_url = canonicalize_url(url)
    clean_title = " ".join((title or "").split()) or "(untitled)"
    return Item(
        hash=make_hash(clean_url, clean_title, source),
        source=source.strip(),
        source_type=source_type,
        title=clean_title,
        url=clean_url,
        published_at=parse_datetime(published_at, collected_at),
        author=(author or "").strip() or None,
        text=truncate_text(text),
        meta=dict(meta or {}),
    )

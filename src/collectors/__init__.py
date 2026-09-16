"""Collector registry and the safe_run wrapper.

Every collector module exposes collect(config, since) -> list[Item]. The
registry turns sources.yaml into small isolated units (one per feed, page or
account) so that one dead source only costs that source, never the digest.
"""
from __future__ import annotations

import importlib
import logging
import time
import traceback
from datetime import datetime
from typing import Callable

from ..schema import Item

log = logging.getLogger("collectors")

Unit = tuple[str, Callable[..., list[Item]], dict]


def _short(exc: Exception, limit: int = 120) -> str:
    """Root cause first, one line, short enough for the page footer."""
    root = exc
    while root.__cause__ is not None or root.__context__ is not None:
        root = root.__cause__ or root.__context__
    text = str(root) if str(root) else str(exc)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def safe_run(name: str, fn: Callable[..., list[Item]], *args, **kwargs) -> tuple[list[Item], str | None]:
    """Run a collector. Never raise. Return (items, error_message)."""
    started = time.monotonic()
    try:
        items = list(fn(*args, **kwargs) or [])
    except Exception as exc:  # noqa: BLE001, isolation is the point here
        log.error("%s failed: %s: %s", name, type(exc).__name__, exc)
        log.debug("%s traceback:\n%s", name, traceback.format_exc())
        return [], f"{name}: {type(exc).__name__}: {_short(exc)}"
    log.info("%s: %d items in %.1fs", name, len(items), time.monotonic() - started)
    return items, None


def _module(name: str):
    try:
        return importlib.import_module(f".{name}", __package__)
    except ImportError as exc:
        log.info("collector %s not available yet (%s), skipping", name, exc)
        return None


def units(sources: dict) -> list[Unit]:
    """Expand sources.yaml into (label, callable, config) units to run."""
    out: list[Unit] = []

    rss = _module("rss")
    if rss:
        for feed in sources.get("rss") or []:
            out.append((f"RSS: {feed.get('name', feed.get('url'))}", rss.collect_feed, feed))

    podcast = _module("podcast")
    for feed in sources.get("podcasts") or []:
        label = f"Podcast: {feed.get('name', feed.get('feed'))}"
        if podcast:
            out.append((label, podcast.collect_feed, feed))
        elif rss:
            # Phase 2 is not built yet: read the show notes through the RSS collector, free.
            out.append((label, rss.collect_feed, {**feed, "url": feed["feed"], "source_type": "podcast"}))

    watch = _module("firecrawl_watch")
    if watch:
        for page in sources.get("web_watch") or []:
            out.append((f"Watch: {page.get('name', page.get('url'))}", watch.collect_page, page))

    linkedin_cfg = sources.get("linkedin") or {}
    if linkedin_cfg.get("enabled"):
        linkedin = _module("linkedin")
        if linkedin:
            out.append(("LinkedIn", linkedin.collect, linkedin_cfg))

    twitter_cfg = sources.get("twitter") or {}
    if twitter_cfg.get("enabled"):
        twitter = _module("twitter")
        if twitter:
            out.append(("Twitter", twitter.collect, twitter_cfg))

    return out


def run_all(sources: dict, since: datetime) -> tuple[list[Item], list[str]]:
    items: list[Item] = []
    errors: list[str] = []
    for label, fn, cfg in units(sources):
        got, err = safe_run(label, fn, cfg, since)
        items.extend(got)
        if err:
            errors.append(err)
    return items, errors

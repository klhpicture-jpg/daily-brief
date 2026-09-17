"""Verify every feed in a profile's sources.yaml: HTTP 200, parses, has entries,
and for podcasts that the enclosures are audio.

    python scripts/check_feeds.py                 # the daily brief
    python scripts/check_feeds.py --profile id    # the weekly industry brief
    python scripts/check_feeds.py --podcasts      # only podcasts
    python scripts/check_feeds.py --url https://example.org/feed   # probe one candidate
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config  # noqa: E402
from src.collectors.rss import fetch, fetch_feed  # noqa: E402


def describe(url: str) -> str:
    """Say what the server actually returned, so a dead feed is not a guessing game."""
    try:
        resp = fetch(url, timeout=20)
    except requests.RequestException as exc:
        return f"and a second look failed too: {type(exc).__name__}"
    kind = resp.headers.get("Content-Type", "unknown").split(";")[0]
    title = re.search(r"<title[^>]*>(.*?)</title>", resp.text[:4000], re.I | re.S)
    page = f', page titled "{" ".join(title.group(1).split())[:60]}"' if title else ""
    return f"served {kind}{page}"


def check(url: str, want_audio: bool) -> tuple[bool, str]:
    try:
        parsed = fetch_feed(url, timeout=20)
    except requests.HTTPError as exc:
        return False, f"HTTP {exc.response.status_code}"
    except requests.RequestException as exc:
        return False, f"request failed: {type(exc).__name__}: {exc}"
    if parsed.bozo and not parsed.entries:
        return False, f"not a feed, {describe(url)}"
    if not parsed.entries:
        return False, "feed has no entries"
    newest = parsed.entries[0].get("published") or parsed.entries[0].get("updated") or "no date"
    if want_audio:
        audio = [
            e for e in parsed.entries[:5]
            if any((enc.get("type") or "").startswith("audio/") for enc in e.get("enclosures", []))
        ]
        if not audio:
            return False, "no audio enclosures in the newest 5 entries"
    return True, f"{len(parsed.entries)} entries, newest {newest}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="daily", help="which brief's sources to check")
    p.add_argument("--url", action="append", default=[], help="probe one URL instead of a profile, repeatable")
    p.add_argument("--podcasts", action="store_true", help="only check podcast feeds")
    p.add_argument("--rss", action="store_true", help="only check rss feeds")
    args = p.parse_args()
    failures = 0
    rows: list[tuple[str, str, bool]] = []
    if args.url:
        rows = [(u, u, False) for u in args.url]
        for name, url, want_audio in rows:
            ok, detail = check(url, want_audio)
            failures += 0 if ok else 1
            print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")
        return 1 if failures else 0
    sources = config.load_sources(config.profile(args.profile))
    if not args.podcasts:
        rows += [(f["name"], f["url"], False) for f in sources.get("rss") or []]
    if not args.rss:
        rows += [(f["name"], f["feed"], True) for f in sources.get("podcasts") or []]
    for name, url, want_audio in rows:
        ok, detail = check(url, want_audio)
        failures += 0 if ok else 1
        print(f"{'OK  ' if ok else 'FAIL'} {name:32s} {detail}")
    print(f"\n{len(rows) - failures}/{len(rows)} feeds ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

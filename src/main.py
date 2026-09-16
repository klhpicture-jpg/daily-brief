"""Orchestrator. One run = collect, dedupe, rank, write, render, deliver, save."""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, deliver, digest, rank, render
from .render import DAYS, MONTHS
from .collectors import run_all
from .llm import Usage
from .schema import utcnow
from .state import State, append_run_log

log = logging.getLogger("main")

LOCAL_TZ = ZoneInfo("Europe/Copenhagen")
MAX_LOOKBACK = timedelta(days=7)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build and deliver today's digest.")
    p.add_argument("--dry-run", action="store_true", help="no delivery, no state write, page written to a temp path")
    p.add_argument("--no-llm", action="store_true", help="stub the LLM with deterministic fake output")
    p.add_argument("--since", help="collect items published after this date (YYYY-MM-DD)")
    p.add_argument("--out", help="write pages here instead of docs/ (implies nothing else)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def resolve_since(state: State, override: str | None, now: datetime) -> datetime:
    if override:
        return datetime.strptime(override, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = state.last_run
    if last is None:
        return now - timedelta(hours=24)
    if now - last > MAX_LOOKBACK:
        log.warning("last run was %s, capping lookback at %d days", last.date(), MAX_LOOKBACK.days)
        return now - MAX_LOOKBACK
    return last


def run(args: argparse.Namespace) -> int:
    now = utcnow()
    today = now.astimezone(LOCAL_TZ).date()
    usage = Usage()
    errors: list[str] = []

    # 1. Load config and state.
    topics = config.load_topics()
    topics_text = config.topics_text()
    learned = config.learned_text()
    sources = config.load_sources()
    state = State(config.STATE_DIR / "seen.json").load()

    # 2. Window.
    since = resolve_since(state, args.since, now)
    log.info("collecting items published since %s", since.isoformat(timespec="minutes"))

    # 3. Collect, isolated per source.
    collected, errors = run_all(sources, since)
    log.info("collected %d items, %d collector errors", len(collected), len(errors))

    # 4. Drop seen hashes, and duplicates within this run.
    fresh: list = []
    seen_now: set[str] = set()
    for item in collected:
        if state.has(item.hash) or item.hash in seen_now:
            continue
        seen_now.add(item.hash)
        fresh.append(item)
    log.info("%d new items after dedupe", len(fresh))

    # 5. Rank and filter.
    if args.no_llm:
        rank.rank_fake(fresh, topics)
    else:
        rank.rank_items(fresh, topics_text, learned, config.rank_model(), usage)
    kept = rank.select(fresh)
    log.info("kept %d items", len(kept))

    # 6. Write.
    if args.no_llm:
        written = digest.write_fake(kept, topics)
    else:
        written = digest.write_digest(kept, topics_text, topics, config.write_model(), usage)

    # 7. Render.
    counts = {"collected": len(collected), "new": len(fresh), "ranked": len(fresh), "kept": len(kept)}
    page = render.render_page(
        digest=written, items=kept, day=today, repo=config.repo(), errors=errors,
        cost_usd=usage.cost_usd, counts=counts, now=now,
    )
    if args.out:
        out_dir = Path(args.out)
    elif args.dry_run:
        out_dir = Path(tempfile.mkdtemp(prefix="daily-brief-"))
    else:
        out_dir = config.DOCS_DIR
    paths = render.write_pages(page, out_dir, today)
    log.info("page written to %s (%d bytes)", paths["daily"], len(page.encode("utf-8")))
    page_url = f"{config.pages_base_url()}/{today.isoformat()}.html"

    # 8. Deliver.
    lines = [t["line"] for t in written.get("top3", [])]
    more = max(0, len(kept) - len(lines))
    date_label = f"{DAYS[today.weekday()][:3]} {today.day}. {MONTHS[today.month - 1][:3]}"
    message = deliver.build_message(date_label, written["headline"], lines, more, page_url)
    log.info("message (%d chars):\n%s", len(message), message)
    delivery_error = None
    if args.dry_run:
        log.info("dry run: not delivering, not writing state")
    else:
        try:
            deliver.send_digest(date_label, written["headline"], lines, more, page_url)
        except Exception as exc:  # noqa: BLE001, state must still be saved
            delivery_error = f"delivery: {type(exc).__name__}: {str(exc)[:200]}"
            log.error(delivery_error)

    # 9 and 10. Remember every collected hash, save state, log the run.
    record = {
        "run_at": now.isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "since": since.isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "no_llm": args.no_llm,
        **counts,
        "errors": errors + ([delivery_error] if delivery_error else []),
        "llm_calls": usage.calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost_usd, 4),
    }
    if not args.dry_run:
        state.add((it.hash for it in collected), now)
        state.prune(now)
        state.mark_run(now)
        state.save()
        append_run_log(config.STATE_DIR / "runs.jsonl", record)
    log.info("run summary: %s", record)
    return 1 if delivery_error else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("trafilatura").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

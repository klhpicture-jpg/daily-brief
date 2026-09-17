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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build and deliver an edition of a brief.")
    p.add_argument("--profile", default="daily", choices=sorted(config.PROFILES), help="which brief to build")
    p.add_argument("--dry-run", action="store_true", help="no delivery, no state write, page written to a temp path")
    p.add_argument("--no-llm", action="store_true", help="stub the LLM with deterministic fake output")
    p.add_argument("--since", help="collect items published after this date (YYYY-MM-DD)")
    p.add_argument("--ignore-seen", action="store_true", help="do not drop items already shown (testing)")
    p.add_argument("--out", help="write pages here instead of docs/ (implies nothing else)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def resolve_since(state: State, override: str | None, now: datetime, lookback: timedelta) -> datetime:
    """The window this edition covers: since the last run, capped at the
    profile's lookback so a long gap does not drag in stale items."""
    if override:
        return datetime.strptime(override, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = state.last_run
    if last is None:
        return now - lookback
    if now - last > lookback:
        log.warning("last run was %s, capping the window at %s", last.date(), lookback)
        return now - lookback
    return last


def run(args: argparse.Namespace) -> int:
    profile = config.profile(args.profile)
    now = utcnow()
    today = now.astimezone(LOCAL_TZ).date()
    usage = Usage()
    errors: list[str] = []
    log.info("building the %s edition (%s)", profile.name, profile.title)

    # 1. Load config and state.
    topics = config.load_topics(profile)
    topics_text = config.topics_text(profile)
    learned = config.learned_text(profile)
    sources = config.load_sources(profile)
    state = State(profile.state_dir / "seen.json").load()

    # 2. Window.
    since = resolve_since(state, args.since, now, profile.lookback)
    log.info("collecting items published since %s", since.isoformat(timespec="minutes"))

    # 3. Collect, isolated per source.
    collected, errors = run_all(sources, since)
    log.info("collected %d items, %d collector errors", len(collected), len(errors))

    # 4. Drop seen hashes, and duplicates within this run.
    fresh: list = []
    seen_now: set[str] = set()
    for item in collected:
        if (state.has(item.hash) and not args.ignore_seen) or item.hash in seen_now:
            continue
        seen_now.add(item.hash)
        fresh.append(item)
    log.info("%d new items after dedupe", len(fresh))

    # 5. Rank and filter.
    if args.no_llm:
        rank.rank_fake(fresh, topics)
    else:
        rank.rank_items(fresh, topics_text, learned, config.rank_model(), usage)
    kept = rank.select(fresh, topics, profile.max_items)
    log.info("kept %d items", len(kept))

    # 6. Nothing worth reading means no page and no message. Silence is the feature.
    if not kept:
        log.info("nothing cleared the bar, not writing a page and not delivering")
        record = _record(args, profile, now, today, since, counts_of(collected, fresh, kept), errors, usage, None, delivered=False)
        _remember(args, state, collected, now, profile, record)
        log.info("run summary: %s", record)
        return 0

    # 7. Write.
    if args.no_llm:
        written = digest.write_fake(kept, topics)
    else:
        written = digest.write_digest(kept, topics_text, topics, config.write_model(), usage)

    # 8. Render.
    counts = counts_of(collected, fresh, kept)
    page = render.render_page(
        digest=written, items=kept, day=today, repo=config.repo(), errors=errors,
        cost_usd=usage.cost_usd, unpriced=usage.unpriced, counts=counts, now=now, title=profile.title,
    )
    if args.out:
        out_dir = Path(args.out)
    elif args.dry_run:
        out_dir = Path(tempfile.mkdtemp(prefix=f"{profile.name}-brief-"))
    else:
        out_dir = profile.docs_dir
    paths = render.write_pages(page, out_dir, today, profile.title)
    log.info("page written to %s (%d bytes)", paths["daily"], len(page.encode("utf-8")))
    page_url = config.page_url(profile, today)

    # 9. Deliver.
    lines = [t["line"] for t in written.get("top3", [])]
    more = max(0, len(kept) - len(lines))
    date_label = f"{DAYS[today.weekday()][:3]} {today.day}. {MONTHS[today.month - 1][:3]}"
    message = deliver.build_message(date_label, written["headline"], lines, more, page_url, profile.title)
    log.info("message (%d chars):\n%s", len(message), message)
    delivery_error = None
    delivered = False
    if args.dry_run:
        log.info("dry run: not delivering, not writing state")
    else:
        try:
            deliver.send_digest(date_label, written["headline"], lines, more, page_url, profile.title)
            delivered = True
        except Exception as exc:  # noqa: BLE001, state must still be saved
            delivery_error = f"delivery: {type(exc).__name__}: {str(exc)[:200]}"
            log.error(delivery_error)

    # 10. Remember every collected hash, save state, log the run.
    record = _record(args, profile, now, today, since, counts, errors, usage, delivery_error, delivered)
    _remember(args, state, collected, now, profile, record)
    log.info("run summary: %s", record)
    return 1 if delivery_error else 0


def counts_of(collected: list, fresh: list, kept: list) -> dict:
    return {"collected": len(collected), "new": len(fresh), "ranked": len(fresh), "kept": len(kept)}


def _record(args, profile, now, today, since, counts, errors, usage, delivery_error, delivered) -> dict:
    return {
        "profile": profile.name,
        "run_at": now.isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "since": since.isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "no_llm": args.no_llm,
        "ignore_seen": args.ignore_seen,
        "delivered": delivered,
        **counts,
        "errors": errors + ([delivery_error] if delivery_error else []),
        "llm_calls": usage.calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(usage.cost_usd, 4),
        "unpriced_models": usage.unpriced,
    }


def _remember(args, state: State, collected: list, now: datetime, profile, record: dict) -> None:
    """Every collected hash is remembered, ranked or not, so it never reappears."""
    if args.dry_run:
        return
    state.add((it.hash for it in collected), now)
    state.prune(now)
    state.mark_run(now)
    state.save()
    append_run_log(profile.state_dir / "runs.jsonl", record)


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

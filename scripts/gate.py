"""Decide whether this workflow slot should build an edition.

Two UTC cron slots fire for every brief so that one of them lands at the wanted
local time whatever DST is doing. GitHub starts scheduled runs late often,
sometimes by three hours, so the gate accepts any scheduled run from the opening
hour until midnight and uses a marker file to keep it to one per period.
A weekly brief additionally has to land on its weekday.

    python scripts/gate.py --marker state/last_scheduled.txt --from-hour 18
    python scripts/gate.py --marker state/id/last_scheduled.txt --from-hour 7 --weekly --weekday 0

Prints GitHub Actions outputs (run, reason) to stdout.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Copenhagen")
DAY_NAMES = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]


def period_key(now: datetime, weekly: bool) -> str:
    """What counts as 'already done'. A date for daily, an ISO week for weekly."""
    if weekly:
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    return now.date().isoformat()


def read_marker(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def decide(event: str, now: datetime, marker: str, from_hour: int, weekly: bool = False,
           weekday: int | None = None) -> tuple[bool, str]:
    """Return (should_run, reason)."""
    if event != "schedule":
        return True, f"manual run ({event})"
    key = period_key(now, weekly)
    if marker == key:
        return False, f"already delivered for {key}"
    if weekday is not None and now.weekday() != weekday:
        return False, f"it is {DAY_NAMES[now.weekday()]}, this brief runs on {DAY_NAMES[weekday]}"
    if now.hour < from_hour:
        return False, f"local time is {now:%H:%M}, the window opens at {from_hour:02d}:00"
    return True, f"local time is {now:%H:%M}, inside the window for {key}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--marker", default="state/last_scheduled.txt", help="file holding the last delivered period")
    p.add_argument("--from-hour", type=int, default=18, help="local hour the window opens")
    p.add_argument("--weekly", action="store_true", help="one delivery per ISO week instead of per day")
    p.add_argument("--weekday", type=int, help="0 is Monday. Only run on this weekday")
    args = p.parse_args(argv)

    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    now = datetime.now(TZ)
    run, reason = decide(event, now, read_marker(Path(args.marker)), args.from_hour, args.weekly, args.weekday)
    print(f"run={'true' if run else 'false'}")
    print(f"reason={reason}")
    print(f"period={period_key(now, args.weekly)}")
    print(f"{'RUNNING' if run else 'SKIPPING'}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

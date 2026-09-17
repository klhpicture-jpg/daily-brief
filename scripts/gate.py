"""Decide whether this workflow slot should build the digest.

Two UTC cron slots fire every day so that one of them lands at 18:25
Europe/Copenhagen whatever DST is doing. GitHub starts scheduled runs late
often, sometimes by three hours, so this gate accepts any scheduled run from
18:00 local until midnight and uses a marker file to keep it to one per day.
Manual runs always go through.

Prints GitHub Actions outputs (run, reason) to stdout.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Copenhagen")
WINDOW_OPENS = 18  # local hour
MARKER = Path("state/last_scheduled.txt")


def read_marker(path: Path = MARKER) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def decide(event: str, now: datetime, marker: str) -> tuple[bool, str]:
    """Return (should_run, reason)."""
    if event != "schedule":
        return True, f"manual run ({event})"
    if marker == now.date().isoformat():
        return False, f"today's digest was already delivered, marker says {marker}"
    if now.hour < WINDOW_OPENS:
        return False, f"local time is {now:%H:%M}, the window opens at {WINDOW_OPENS:02d}:00"
    return True, f"local time is {now:%H:%M}, inside the evening window"


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    now = datetime.now(TZ)
    run, reason = decide(event, now, read_marker())
    print(f"run={'true' if run else 'false'}")
    print(f"reason={reason}")
    print(f"{'RUNNING' if run else 'SKIPPING'}: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

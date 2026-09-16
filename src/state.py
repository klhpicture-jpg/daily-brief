"""Seen-hash store and run log. Plain JSON, committed back to the repo."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger("state")

RETENTION_DAYS = 90


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"last_run": None, "seen": {}}

    def load(self) -> "State":
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            self.data["last_run"] = loaded.get("last_run")
            self.data["seen"] = dict(loaded.get("seen") or {})
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=0, sort_keys=True)
            fh.write("\n")
        tmp.replace(self.path)

    @property
    def last_run(self) -> datetime | None:
        raw = self.data.get("last_run")
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def mark_run(self, when: datetime) -> None:
        self.data["last_run"] = when.astimezone(timezone.utc).isoformat()

    def has(self, item_hash: str) -> bool:
        return item_hash in self.data["seen"]

    def add(self, hashes: Iterable[str], when: datetime) -> None:
        stamp = when.astimezone(timezone.utc).isoformat()
        for h in hashes:
            self.data["seen"].setdefault(h, stamp)

    def prune(self, now: datetime, days: int = RETENTION_DAYS) -> int:
        cutoff = now.astimezone(timezone.utc) - timedelta(days=days)
        before = len(self.data["seen"])
        self.data["seen"] = {
            h: seen for h, seen in self.data["seen"].items()
            if datetime.fromisoformat(seen) >= cutoff
        }
        dropped = before - len(self.data["seen"])
        if dropped:
            log.info("pruned %d seen hashes older than %d days", dropped, days)
        return dropped


def append_run_log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")

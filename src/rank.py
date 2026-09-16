"""Stage 1: a cheap model scores every collected item 0 to 5."""
from __future__ import annotations

import json
import logging
import re

from .llm import Usage, chat_json, no_dashes
from .schema import Item

log = logging.getLogger("rank")

BATCH_SIZE = 20
TEXT_PREVIEW = 1200
KEEP_THRESHOLD = 3
FALLBACK_THRESHOLD = 2
MIN_ITEMS = 5
MAX_ITEMS = 15
DEFAULT_SCORE = 2

SCORING_GUIDE = """Score each item from 0 to 5 for the reader described below:
5 = the reader would be annoyed to miss this
4 = clearly relevant and actionable
3 = relevant context
2 = tangential
1 = off topic
0 = noise or pure promotion"""

SYSTEM_TEMPLATE = """You rank news items for one specific reader. Be strict: most items are a 1 or 2.

{scoring_guide}

The reader's brief (verbatim from their topics file):
---
{topics}
---
{learned_block}
Return strict JSON only, shaped exactly like:
{{"scores": [{{"i": 0, "score": 3, "why": "one short sentence"}}, ...]}}
Include every input index exactly once. "why" is one concrete sentence, max 20 words, no em dashes."""


def build_system_prompt(topics_text: str, learned_text: str = "") -> str:
    learned_block = ""
    if learned_text.strip():
        learned_block = f"\nRules learned from the reader's past feedback (apply them):\n---\n{learned_text.strip()}\n---\n"
    return SYSTEM_TEMPLATE.format(scoring_guide=SCORING_GUIDE, topics=topics_text.strip(), learned_block=learned_block)


def _batch_payload(batch: list[Item]) -> str:
    rows = [
        {
            "i": i,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat(timespec="minutes"),
            "text": item.text[:TEXT_PREVIEW],
        }
        for i, item in enumerate(batch)
    ]
    return json.dumps({"items": rows}, ensure_ascii=False)


def parse_scores(data: dict, expected: int) -> dict[int, tuple[int, str]]:
    """Validate the ranker's JSON. Raises ValueError on any shape problem."""
    scores = data.get("scores")
    if not isinstance(scores, list):
        raise ValueError("missing 'scores' list")
    out: dict[int, tuple[int, str]] = {}
    for row in scores:
        if not isinstance(row, dict):
            raise ValueError("score row is not an object")
        try:
            i = int(row["i"])
            score = int(row["score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bad score row {row!r}") from exc
        if not 0 <= score <= 5 or not 0 <= i < expected:
            raise ValueError(f"score row out of range {row!r}")
        out[i] = (score, no_dashes(str(row.get("why") or "")).strip()[:160])
    missing = set(range(expected)) - set(out)
    if missing:
        raise ValueError(f"missing indices {sorted(missing)}")
    return out


def _rank_batch(batch: list[Item], system: str, model: str, usage: Usage) -> None:
    payload = _batch_payload(batch)
    for attempt in (1, 2):
        try:
            data = chat_json(model, system, payload, usage, max_output_tokens=2500, reasoning_effort="minimal", attempts=1)
            scores = parse_scores(data, len(batch))
            break
        except (RuntimeError, ValueError) as exc:
            log.warning("ranker batch failed (attempt %d/2): %s", attempt, exc)
            scores = None
    if scores is None:
        log.error("ranker gave up on a batch of %d, defaulting every item to score %d", len(batch), DEFAULT_SCORE)
        scores = {i: (DEFAULT_SCORE, "ranker failed, default score") for i in range(len(batch))}
    for i, item in enumerate(batch):
        item.score, item.why = scores[i]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _keywords(topics: dict) -> list[str]:
    words: list[str] = []
    for p in topics.get("priorities", []):
        for phrase in p.get("include", []) or []:
            words.extend(w for w in _WORD_RE.findall(str(phrase).lower()) if len(w) > 3)
    return sorted(set(words))


def rank_fake(items: list[Item], topics: dict) -> None:
    """Deterministic stand-in for --no-llm: keyword overlap with topics.yaml."""
    keywords = _keywords(topics)
    for item in items:
        haystack = f"{item.title} {item.text[:TEXT_PREVIEW]}".lower()
        hits = sorted({k for k in keywords if k in haystack})
        item.score = min(5, 1 + len(hits)) if hits else 1
        item.why = f"stub: matched {', '.join(hits[:4])}" if hits else "stub: no topic keywords matched"


def rank_items(items: list[Item], topics_text: str, learned_text: str, model: str, usage: Usage) -> None:
    system = build_system_prompt(topics_text, learned_text)
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start : start + BATCH_SIZE]
        _rank_batch(batch, system, model, usage)
        log.info("ranked %d/%d", min(start + BATCH_SIZE, len(items)), len(items))


def select(items: list[Item]) -> list[Item]:
    """Keep 3+, capped at 15. Below 5 survivors, drop the bar to 2."""
    ordered = sorted(items, key=lambda it: ((it.score or 0), it.published_at), reverse=True)
    keep = [it for it in ordered if (it.score or 0) >= KEEP_THRESHOLD]
    if len(keep) < MIN_ITEMS:
        keep = [it for it in ordered if (it.score or 0) >= FALLBACK_THRESHOLD]
    return keep[:MAX_ITEMS]

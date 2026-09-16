"""Stage 2: the expensive model writes only the survivors."""
from __future__ import annotations

import json
import logging

from .config import priority_names
from .llm import Usage, chat_json, no_dashes
from .schema import Item

log = logging.getLogger("digest")

PODCAST_SECTION = "From the podcasts"
OTHER_SECTION = "Also worth a look"
HEADLINE_MAX = 60
LINE_MAX = 90

WRITING_RULES = """Writing rules:
- No em dashes. Use commas, periods or parentheses.
- Lead with what happened, then why it matters to this reader.
- Name specific companies, numbers and dates. Delete any sentence that would survive unchanged in someone else's digest.
- No filler openers like "In today's fast moving landscape".
- If an item is thin, say so in one line rather than padding it.
- Plain text only, no markdown."""

SYSTEM_TEMPLATE = """You write a short daily digest for one reader. They read it on a phone in under two minutes.

The reader's brief (verbatim):
---
{topics}
---

{rules}

Output strict JSON only, shaped exactly like:
{{
  "headline": "one line summarising the day, max {headline_max} chars",
  "top3": [{{"item_hash": "...", "line": "max {line_max} chars, concrete, no hype"}}],
  "sections": [
    {{"title": "section title", "items": [
      {{"item_hash": "...", "summary": "2 to 3 sentences", "why_it_matters": "1 sentence, specific to this reader"}}
    ]}}
  ]
}}

Section rules:
- Use only these section titles, in this order, and skip empty ones: {sections}.
- Every item with source_type "podcast" goes in "{podcast_section}". Start its summary with a timestamped highlight (like "At 12:40, ...") when the transcript has timestamps; otherwise give the most concrete moment.
- Every other item goes in the priority section it fits best, or "{other_section}" if none fits.
- Cover every input item exactly once. Use each item_hash exactly as given.
- top3 holds the three items the reader most needs today, best first."""


def build_system_prompt(topics_text: str, topics: dict) -> str:
    sections = priority_names(topics) + [PODCAST_SECTION, OTHER_SECTION]
    return SYSTEM_TEMPLATE.format(
        topics=topics_text.strip(),
        rules=WRITING_RULES,
        headline_max=HEADLINE_MAX,
        line_max=LINE_MAX,
        sections=json.dumps(sections, ensure_ascii=False),
        podcast_section=PODCAST_SECTION,
        other_section=OTHER_SECTION,
    )


def _payload(items: list[Item]) -> str:
    rows = [
        {
            "item_hash": it.hash,
            "source": it.source,
            "source_type": it.source_type,
            "title": it.title,
            "url": it.url,
            "published_at": it.published_at.isoformat(timespec="minutes"),
            "ranker_note": it.why,
            "text": it.text,
        }
        for it in items
    ]
    return json.dumps({"items": rows}, ensure_ascii=False)


def _clip(text: str, limit: int) -> str:
    text = " ".join(no_dashes(str(text or "")).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize(data: dict, items: list[Item], topics: dict) -> dict:
    """Validate and repair the writer's JSON so the page never breaks.

    Unknown hashes are dropped, missing items get a one-line fallback, sections
    are reordered to the priority order, and length limits are enforced.
    """
    by_hash = {it.hash: it for it in items}
    order = priority_names(topics) + [PODCAST_SECTION, OTHER_SECTION]
    rank = {title: i for i, title in enumerate(order)}

    sections: dict[str, list[dict]] = {}
    covered: set[str] = set()
    for raw_section in data.get("sections") or []:
        if not isinstance(raw_section, dict):
            continue
        title = str(raw_section.get("title") or OTHER_SECTION).strip()
        if title not in rank:
            title = OTHER_SECTION
        for raw in raw_section.get("items") or []:
            if not isinstance(raw, dict):
                continue
            h = str(raw.get("item_hash") or "")
            if h not in by_hash or h in covered:
                continue
            target = PODCAST_SECTION if by_hash[h].source_type == "podcast" else title
            sections.setdefault(target, []).append(
                {
                    "item_hash": h,
                    "summary": _clip(raw.get("summary") or "", 700) or "No summary produced.",
                    "why_it_matters": _clip(raw.get("why_it_matters") or "", 240),
                }
            )
            covered.add(h)

    for it in items:
        if it.hash in covered:
            continue
        log.warning("writer skipped %s, adding a one-line fallback", it.title[:60])
        target = PODCAST_SECTION if it.source_type == "podcast" else OTHER_SECTION
        sections.setdefault(target, []).append(
            {"item_hash": it.hash, "summary": _clip(it.text, 240) or "Thin item, nothing beyond the title.", "why_it_matters": _clip(it.why, 240)}
        )

    top3: list[dict] = []
    seen: set[str] = set()
    for raw in data.get("top3") or []:
        if not isinstance(raw, dict):
            continue
        h = str(raw.get("item_hash") or "")
        if h in by_hash and h not in seen:
            top3.append({"item_hash": h, "line": _clip(raw.get("line") or by_hash[h].title, LINE_MAX)})
            seen.add(h)
        if len(top3) == 3:
            break
    for it in items:
        if len(top3) == 3:
            break
        if it.hash not in seen:
            top3.append({"item_hash": it.hash, "line": _clip(it.title, LINE_MAX)})
            seen.add(it.hash)

    headline = _clip(data.get("headline") or "", HEADLINE_MAX)
    if not headline:
        headline = _clip(top3[0]["line"], HEADLINE_MAX) if top3 else "Nothing new today"
    return {
        "headline": headline,
        "top3": top3,
        "sections": [{"title": t, "items": sections[t]} for t in sorted(sections, key=lambda t: rank[t])],
    }


def write_fake(items: list[Item], topics: dict) -> dict:
    """Deterministic stand-in for --no-llm."""
    sections: list[dict] = []
    for it in items:
        title = OTHER_SECTION
        hay = f"{it.title} {it.text[:1200]}".lower()
        for p in topics.get("priorities", []):
            if any(str(k).lower() in hay for k in (p.get("include") or [])):
                title = p["name"]
                break
        sections.append({"title": title, "items": [{"item_hash": it.hash, "summary": it.text[:300], "why_it_matters": it.why}]})
    data = {
        "headline": "Stub digest, no LLM was used",
        "top3": [{"item_hash": it.hash, "line": it.title} for it in items[:3]],
        "sections": sections,
    }
    return normalize(data, items, topics)


def write_digest(items: list[Item], topics_text: str, topics: dict, model: str, usage: Usage) -> dict:
    if not items:
        return {"headline": "Nothing new today", "top3": [], "sections": []}
    system = build_system_prompt(topics_text, topics)
    data = chat_json(model, system, _payload(items), usage, max_output_tokens=16000, reasoning_effort="low", attempts=3)
    return normalize(data, items, topics)

"""The page. Mobile first, no JavaScript, under 30KB, light and dark."""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .schema import Item

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")

CSS = """
:root{--bg:#fbfaf7;--fg:#1c1b19;--muted:#6b675f;--line:#e4e0d8;--accent:#0b5fa5;--why-bg:#f1efe8;--why-fg:#3a3730}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--fg:#ebe8e1;--muted:#a19c92;--line:#2c2b27;--accent:#7fb7ec;--why-bg:#1f1e1a;--why-fg:#d6d2c8}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background-color:var(--bg);color:var(--fg);font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;overflow-wrap:anywhere}
main{max-width:42rem;margin:0 auto;padding:0 16px 3rem}
header{padding:1.5rem 0 1rem;border-bottom:1px solid var(--line)}
header .date{color:var(--muted);font-size:.9rem;margin:0}
header h1{font-size:1.45rem;line-height:1.3;margin:.25rem 0 0}
nav.top3{margin:1rem 0 0;padding:0}
nav.top3 ol{margin:.25rem 0 0;padding-left:1.25rem}
nav.top3 li{margin:.25rem 0}
h2{font-size:1.05rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:2rem 0 .5rem}
article{padding:.75rem 0 1rem;border-bottom:1px solid var(--line)}
article h3{font-size:1.1rem;line-height:1.35;margin:0}
article h3 a{display:block;min-height:44px;padding:.4rem 0;color:var(--fg);text-decoration:none}
article h3 a:hover{color:var(--accent)}
.meta{color:var(--muted);font-size:.85rem;margin:0 0 .5rem}
.summary{margin:0 0 .6rem}
.keep{margin:0 0 .6rem;font-weight:600}
.keep span{color:var(--muted);font-weight:400;font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;margin-right:.4rem}
.why{background:var(--why-bg);color:var(--why-fg);border-left:3px solid var(--accent);padding:.5rem .75rem;margin:0 0 .6rem;font-size:.95rem}
.links{font-size:.9rem;display:flex;flex-wrap:wrap;gap:.25rem 1rem;margin:0}
.links a{color:var(--accent);text-decoration:none;min-height:44px;display:inline-flex;align-items:center}
.fb{margin-left:auto}
footer{margin-top:2rem;color:var(--muted);font-size:.85rem}
footer ul{padding-left:1.25rem;margin:.25rem 0}
a{color:var(--accent)}
.empty{color:var(--muted);margin:2rem 0}
"""


def _esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def relative_time(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    return f"{days}d ago" if days < 14 else then.strftime("%d %b")


def feedback_links(repo: str, item: Item) -> tuple[str, str]:
    base = f"https://github.com/{repo}/issues/new"
    title = quote(item.title[:120], safe="")
    good = f"{base}?labels=feedback-good&title={title}&body={item.hash}"
    bad = f"{base}?labels=feedback-bad&title={title}&body={item.hash}"
    return good, bad


def render_item(entry: dict, item: Item, repo: str, now: datetime) -> str:
    good, bad = feedback_links(repo, item)
    when = relative_time(item.published_at, now)
    author = f" · {_esc(item.author)}" if item.author else ""
    keep = f'<p class="keep"><span>Remember</span>{_esc(entry.get("remember"))}</p>' if entry.get("remember") else ""
    why = f'<p class="why">{_esc(entry.get("why_it_matters"))}</p>' if entry.get("why_it_matters") else ""
    return (
        f'<article id="i-{item.hash[:12]}">'
        f'<h3><a href="{_esc(item.url)}">{_esc(item.title)}</a></h3>'
        f'<p class="meta">{_esc(item.source)}{author} · {when}</p>'
        f'<p class="summary">{_esc(entry.get("summary"))}</p>'
        f"{keep}{why}"
        f'<p class="links"><a href="{_esc(item.url)}">Source</a>'
        f'<a class="fb" href="{good}" title="More like this">&#128077;</a>'
        f'<a href="{bad}" title="Less like this">&#128078;</a></p>'
        "</article>"
    )


def render_page(
    *,
    digest: dict,
    items: list[Item],
    day: date,
    repo: str,
    errors: list[str],
    cost_usd: float,
    counts: dict,
    now: datetime | None = None,
    archive_href: str = "archive.html",
) -> str:
    now = now or datetime.now(timezone.utc)
    by_hash = {it.hash: it for it in items}
    headline = digest.get("headline") or "Nothing new today"
    date_label = day.strftime("%A %d %B %Y")

    top3 = ""
    if digest.get("top3"):
        lis = "".join(
            f'<li><a href="#i-{t["item_hash"][:12]}">{_esc(t["line"])}</a></li>'
            for t in digest["top3"]
            if t["item_hash"] in by_hash
        )
        top3 = f"<nav class=\"top3\"><ol>{lis}</ol></nav>"

    body = []
    for section in digest.get("sections") or []:
        rows = [render_item(e, by_hash[e["item_hash"]], repo, now) for e in section["items"] if e["item_hash"] in by_hash]
        if rows:
            body.append(f"<section><h2>{_esc(section['title'])}</h2>{''.join(rows)}</section>")
    if not body:
        body.append('<p class="empty">Nothing cleared the bar today. Collectors ran, the ranker found nothing worth your time.</p>')

    failed = "".join(f"<li>{_esc(e)}</li>" for e in errors)
    failed_block = f"<p>Collectors that failed:</p><ul>{failed}</ul>" if errors else "<p>All collectors ran.</p>"
    stats = (
        f"{counts.get('collected', 0)} collected, {counts.get('new', 0)} new, "
        f"{counts.get('ranked', 0)} ranked, {counts.get('kept', 0)} kept. Estimated cost ${cost_usd:.3f}."
    )

    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"color-scheme\" content=\"light dark\"><title>{_esc(day.isoformat())} · {_esc(headline)}</title>"
        f"<style>{CSS.strip()}</style></head><body><main>"
        f"<header><p class=\"date\">{_esc(date_label)}</p><h1>{_esc(headline)}</h1>{top3}</header>"
        f"{''.join(body)}"
        f"<footer><p>{_esc(stats)}</p>{failed_block}"
        f"<p><a href=\"{_esc(archive_href)}\">Archive</a> · <a href=\"https://github.com/{_esc(repo)}\">Repo</a></p></footer>"
        "</main></body></html>\n"
    )


def render_archive(docs_dir: Path) -> str:
    days = sorted((p.stem for p in docs_dir.glob("*.html") if DATE_RE.match(p.name)), reverse=True)
    rows = "".join(f'<li><a href="{d}.html">{d}</a></li>' for d in days)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"color-scheme\" content=\"light dark\"><title>Daily brief archive</title>"
        f"<style>{CSS.strip()}</style></head><body><main><header><h1>Archive</h1></header>"
        f"<ul>{rows or '<li>No digests yet.</li>'}</ul>"
        "<footer><p><a href=\"index.html\">Latest</a></p></footer></main></body></html>\n"
    )


def write_pages(page_html: str, docs_dir: Path, day: date) -> dict[str, Path]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    daily = docs_dir / f"{day.isoformat()}.html"
    index = docs_dir / "index.html"
    archive = docs_dir / "archive.html"
    daily.write_text(page_html, encoding="utf-8")
    index.write_text(page_html, encoding="utf-8")
    archive.write_text(render_archive(docs_dir), encoding="utf-8")
    return {"daily": daily, "index": index, "archive": archive}

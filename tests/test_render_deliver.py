from datetime import date, datetime, timezone

from src import deliver, render
from src.schema import make_item


def test_message_stays_under_480():
    lines = ["x" * 300, "y" * 300, "z" * 300]
    msg = deliver.build_message("Tue 16 Sep", "h" * 200, lines, 9, "https://klhpicture-jpg.github.io/daily-brief/2026-09-16.html")
    assert len(msg) <= 480
    assert msg.endswith("+9 more: https://klhpicture-jpg.github.io/daily-brief/2026-09-16.html")
    assert msg.count("\n") == 6


def test_page_is_small_static_and_escaped(tmp_path):
    items = [
        make_item(source="<S>", source_type="rss", title=f"Title <{i}> & co", url=f"https://a.org/{i}?x=1", text="t",
                  published_at=datetime(2026, 9, 16, 5, tzinfo=timezone.utc))
        for i in range(15)
    ]
    digest = {
        "headline": "Head",
        "top3": [{"item_hash": it.hash, "line": "line"} for it in items[:3]],
        "sections": [{"title": "Sec", "items": [{"item_hash": it.hash, "summary": "s" * 400, "why_it_matters": "w" * 150} for it in items]}],
    }
    html = render.render_page(digest=digest, items=items, day=date(2026, 9, 16), repo="o/r", errors=["RSS: X: boom"], cost_usd=0.0123, counts={"kept": 15}, now=datetime(2026, 9, 16, 6, tzinfo=timezone.utc))
    assert len(html.encode()) < 30_000
    assert "<script" not in html
    assert "Title &lt;0&gt; &amp; co" in html
    assert "labels=feedback-good" in html and "labels=feedback-bad" in html
    assert "background-color:var(--bg)" in html and "prefers-color-scheme:dark" in html
    assert "RSS: X: boom" in html
    paths = render.write_pages(html, tmp_path, date(2026, 9, 16))
    assert paths["index"].read_text() == html
    assert "2026-09-16.html" in paths["archive"].read_text()

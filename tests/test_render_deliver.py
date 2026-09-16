from datetime import date, datetime, timezone

from src import deliver, render
from src.schema import make_item


def test_message_stays_under_480():
    lines = ["x" * 300, "y" * 300, "z" * 300]
    msg = deliver.build_message("Tue 16 Sep", "h" * 200, lines, 9, "https://klhpicture-jpg.github.io/daily-brief/2026-09-16.html")
    assert len(msg) <= 480
    assert msg.endswith("+9 mere: https://klhpicture-jpg.github.io/daily-brief/2026-09-16.html")
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
        "sections": [{"title": "Sec", "items": [{"item_hash": it.hash, "summary": "s" * 700, "remember": "keep <this>", "why_it_matters": "w" * 250} for it in items]}],
    }
    html = render.render_page(digest=digest, items=items, day=date(2026, 9, 16), repo="o/r", errors=["RSS: X: boom"], cost_usd=0.0123, counts={"kept": 15}, now=datetime(2026, 9, 16, 6, tzinfo=timezone.utc))
    assert len(html.encode()) < 30_000
    assert "<script" not in html
    assert "Title &lt;0&gt; &amp; co" in html
    assert "labels=feedback-good" in html and "labels=feedback-bad" in html
    assert "background-color:var(--bg)" in html and "prefers-color-scheme:dark" in html
    assert "RSS: X: boom" in html
    assert "keep &lt;this&gt;" in html
    paths = render.write_pages(html, tmp_path, date(2026, 9, 16))
    assert paths["index"].read_text() == html
    assert "2026-09-16.html" in paths["archive"].read_text()


def test_telegram_send_posts_once(monkeypatch):
    calls = []

    class Resp:
        status_code = 200
        content = b"x"

        def json(self):
            return {"ok": True, "result": {"message_id": 42}}

    monkeypatch.setenv("DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(deliver.requests, "post", lambda url, **kw: calls.append((url, kw)) or Resp())
    assert deliver.send("hello") == "42"
    assert len(calls) == 1
    assert calls[0][0].endswith("/bot" + "t" + "/sendMessage")
    assert calls[0][1]["json"] == {"chat_id": "123", "text": "hello", "disable_web_page_preview": False, "disable_notification": False}


def test_telegram_error_is_raised(monkeypatch):
    class Resp:
        status_code = 400
        content = b"x"
        text = "bad"

        def json(self):
            return {"ok": False, "description": "chat not found"}

    monkeypatch.setenv("DELIVERY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(deliver.requests, "post", lambda url, **kw: Resp())
    import pytest

    with pytest.raises(RuntimeError, match="chat not found"):
        deliver.send("hello")


def test_unknown_channel_rejected(monkeypatch):
    monkeypatch.setenv("DELIVERY_CHANNEL", "pigeon")
    import pytest

    with pytest.raises(RuntimeError, match="DELIVERY_CHANNEL"):
        deliver.send("hello")

from datetime import datetime, timezone

from src.schema import canonicalize_url, make_hash, make_item, parse_datetime, strip_html, truncate_text


def test_canonicalize_strips_tracking_and_fragment():
    a = canonicalize_url("https://Example.org/path/?utm_source=x&fbclid=y&id=2#frag")
    b = canonicalize_url("https://example.org/path?id=2")
    assert a == b == "https://example.org/path?id=2"


def test_hash_falls_back_to_title_and_source():
    assert make_hash("", "Title", "Src") == make_hash("", "title ", " src")
    assert make_hash("https://a.org/x", "t", "s") != make_hash("", "t", "s")


def test_make_item_normalizes():
    item = make_item(source="S", source_type="rss", title="  Two   words ", url="https://a.org/x/", text="x" * 9000)
    assert item.title == "Two words"
    assert item.url == "https://a.org/x"
    assert len(item.text) == 8000
    assert item.published_at.tzinfo is not None


def test_parse_datetime_never_raises():
    fallback = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert parse_datetime("garbage", fallback) == fallback
    assert parse_datetime("2026-09-15T09:00:00+02:00").hour == 7


def test_strip_html_and_truncate():
    assert strip_html("<p>Hello &amp; <b>world</b></p>") == "Hello & world"
    assert truncate_text("abcdef", 4).endswith("…")

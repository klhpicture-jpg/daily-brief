import json
from datetime import datetime, timezone
from pathlib import Path

from datetime import date
from zoneinfo import ZoneInfo

from src import render
from src.collectors import run_all
from src.collectors.rss import collect_feed
from src.main import main

FIXTURE = Path(__file__).parent / "fixtures" / "feed.xml"


def test_rss_collector_reads_fixture():
    since = datetime(2026, 9, 14, tzinfo=timezone.utc)
    items = collect_feed({"name": "Fixture", "url": f"file://{FIXTURE}"}, since)
    titles = [it.title for it in items]
    assert "Old article from last year" not in titles
    assert len(items) == 5
    shopify = [it for it in items if "Shopify" in it.title]
    assert shopify[0].hash == shopify[1].hash, "tracking params must not create two hashes"
    assert shopify[0].author == "Jane Doe"


def test_safe_run_isolates_failures():
    items, errors = run_all({"rss": [{"name": "Broken", "url": "file:///nope/missing.xml"}, {"name": "Fixture", "url": f"file://{FIXTURE}"}]}, datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert len(items) == 5
    assert len(errors) == 1 and errors[0].startswith("RSS: Broken")


def test_dry_run_no_llm_writes_a_page(tmp_path, monkeypatch):
    from src import config

    monkeypatch.setattr(config, "load_sources", lambda profile=None: {"rss": [{"name": "Fixture", "url": f"file://{FIXTURE}"}]})
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "seen.json").write_text(json.dumps({"last_run": None, "seen": {}}))
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    rc = main(["--dry-run", "--no-llm", "--since", "2026-09-14", "--out", str(tmp_path / "docs")])
    assert rc == 0
    index = (tmp_path / "docs" / "index.html").read_text()
    assert "Stub-digest" in index and 'lang="da"' in index
    today = datetime.now(ZoneInfo("Europe/Copenhagen")).date()
    assert render.danish_date(today) in index, "the page header must carry today's Danish date"
    assert "Shopify raises Plus pricing" in index
    assert (state_dir / "seen.json").read_text() == json.dumps({"last_run": None, "seen": {}}), "dry run must not touch state"


def test_podcast_feed_falls_back_to_show_notes():
    from src.collectors import units

    got = units({"podcasts": [{"name": "Pod", "feed": f"file://{FIXTURE}", "max_minutes": 60}]})
    assert len(got) == 1
    label, fn, cfg = got[0]
    items = fn(cfg, datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert items and all(it.source_type == "podcast" for it in items)
    assert not any(it.meta.get("body_fetched") for it in items)


def test_gate_tolerates_late_scheduled_runs():
    from scripts.gate import decide

    tz = ZoneInfo("Europe/Copenhagen")
    late = datetime(2026, 9, 16, 21, 36, tzinfo=tz)
    early = datetime(2026, 9, 16, 17, 25, tzinfo=tz)

    assert decide("schedule", late, "", 18)[0] is True, "a three hour delay must still deliver"
    assert decide("schedule", early, "", 18)[0] is False, "the winter slot at 17:25 local waits"
    assert decide("schedule", late, "2026-09-16", 18)[0] is False, "one delivery per day"
    assert decide("workflow_dispatch", early, "2026-09-16", 18)[0] is True, "manual runs always go"


def test_weekly_gate_runs_once_on_monday():
    from scripts.gate import decide, period_key

    tz = ZoneInfo("Europe/Copenhagen")
    monday = datetime(2026, 9, 21, 7, 25, tzinfo=tz)
    monday_late = datetime(2026, 9, 21, 10, 40, tzinfo=tz)
    tuesday = datetime(2026, 9, 22, 7, 25, tzinfo=tz)
    week = period_key(monday, weekly=True)

    assert decide("schedule", monday, "", 7, weekly=True, weekday=0)[0] is True
    assert decide("schedule", monday_late, "", 7, weekly=True, weekday=0)[0] is True, "a late Monday still delivers"
    assert decide("schedule", monday_late, week, 7, weekly=True, weekday=0)[0] is False, "one delivery per week"
    assert decide("schedule", tuesday, "", 7, weekly=True, weekday=0)[0] is False, "Tuesday is not this brief's day"
    assert period_key(datetime(2026, 9, 27, 9, 0, tzinfo=tz), weekly=True) == week, "Sunday belongs to the same week"


def test_nothing_caught_means_no_page_and_no_message(tmp_path, monkeypatch):
    """The whole point of the weekly brief: silence when the week was quiet."""
    from src import config, deliver

    empty = tmp_path / "empty.xml"
    empty.write_text('<?xml version="1.0"?><rss version="2.0"><channel><title>Quiet</title></channel></rss>')
    monkeypatch.setattr(config, "load_sources", lambda profile=None: {"rss": [{"name": "Quiet", "url": f"file://{empty}"}]})
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "seen.json").write_text(json.dumps({"last_run": None, "seen": {}}))
    monkeypatch.setattr(config, "STATE_DIR", state_dir)

    sent = []
    monkeypatch.setattr(deliver, "send_digest", lambda *a, **k: sent.append(a))
    out = tmp_path / "docs"
    rc = main(["--no-llm", "--since", "2026-09-14", "--out", str(out), "--dry-run"])
    assert rc == 0
    assert sent == [], "nothing caught means nothing sent"
    assert not out.exists(), "no page is written for an empty edition"


def test_id_profile_is_wired_end_to_end(tmp_path, monkeypatch):
    from src import config

    profile = config.profile("id")
    assert profile.title == "ID ugebrief"
    assert profile.docs_dir.name == "id" and profile.state_dir.name == "id"
    topics = config.load_topics(profile)
    sources = config.load_sources(profile)
    assert [p["name"] for p in topics["priorities"]][0] == "Konkurrenter og ejerskab"
    names = [f["name"] for f in sources["rss"]]
    assert "New Wave Group (MFN)" in names, "the listed competitor feed is the point of this brief"
    assert all(f.get("url") for f in sources["rss"]), "every source needs a url"
    assert config.page_url(profile, date(2026, 9, 21)).endswith("/id/2026-09-21.html")


def test_fetch_feed_retries_as_a_browser_when_served_html():
    """Bot walls answer 200 with a page, not an error. One retry as a browser recovers the feed."""
    from src.collectors import rss

    feed = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>Trade</title>'
            b'<item><title>Mascot opens a plant</title><link>https://example.org/a</link></item>'
            b'</channel></rss>')
    calls = []

    class Resp:
        def __init__(self, content):
            self.content, self.status_code = content, 200

        def raise_for_status(self):
            return None

    def fake_get(url, timeout=None, headers=None):
        agent = (headers or {}).get("User-Agent", "")
        calls.append(agent)
        is_browser = agent.startswith("Mozilla/")
        return Resp(feed if is_browser else b"<!DOCTYPE html><html><body>Just a moment</body></html>")

    original = rss.requests.get
    rss.requests.get = fake_get
    try:
        parsed = rss.fetch_feed("https://example.org/feed")
    finally:
        rss.requests.get = original

    assert len(parsed.entries) == 1 and parsed.entries[0].title == "Mascot opens a plant"
    assert len(calls) == 2 and not calls[0].startswith("Mozilla/") and calls[1].startswith("Mozilla/")

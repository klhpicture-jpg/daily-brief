import json
from datetime import datetime, timezone
from pathlib import Path

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

    monkeypatch.setattr(config, "load_sources", lambda: {"rss": [{"name": "Fixture", "url": f"file://{FIXTURE}"}]})
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "seen.json").write_text(json.dumps({"last_run": None, "seen": {}}))
    monkeypatch.setattr(config, "STATE_DIR", state_dir)
    rc = main(["--dry-run", "--no-llm", "--since", "2026-09-14", "--out", str(tmp_path / "docs")])
    assert rc == 0
    index = (tmp_path / "docs" / "index.html").read_text()
    assert "Stub digest" in index
    assert "Shopify raises Plus pricing" in index
    assert (state_dir / "seen.json").read_text() == json.dumps({"last_run": None, "seen": {}}), "dry run must not touch state"

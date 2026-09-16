import pytest

from src import config, digest, rank
from src.schema import make_item


def items(n=6):
    return [
        make_item(source="S", source_type="rss", title=f"Item {i} about merchandising", url=f"https://a.org/{i}", text="PIM and product content news")
        for i in range(n)
    ]


def test_parse_scores_validates_shape():
    data = {"scores": [{"i": 0, "score": 4, "why": "x \u2014 y"}, {"i": 1, "score": 2, "why": "z"}]}
    out = rank.parse_scores(data, 2)
    assert out[0] == (4, "x, y")
    with pytest.raises(ValueError):
        rank.parse_scores({"scores": [{"i": 0, "score": 9}]}, 1)
    with pytest.raises(ValueError):
        rank.parse_scores({"scores": [{"i": 0, "score": 1}]}, 2)


def test_select_drops_threshold_when_thin():
    its = items(6)
    for i, it in enumerate(its):
        it.score = 2 if i < 4 else 3
    kept = rank.select(its)
    assert len(kept) == 6
    for it in its:
        it.score = 1
    assert rank.select(its) == []


def test_select_caps_at_15():
    its = items(30)
    for it in its:
        it.score = 5
    assert len(rank.select(its)) == 15


def test_fake_pipeline_covers_every_item():
    topics = config.load_topics()
    its = items(4)
    rank.rank_fake(its, topics)
    assert all(it.score is not None for it in its)
    out = digest.write_fake(its, topics)
    covered = [e["item_hash"] for s in out["sections"] for e in s["items"]]
    assert sorted(covered) == sorted(it.hash for it in its)
    assert len(out["top3"]) == 3
    assert len(out["headline"]) <= 60


def test_normalize_repairs_bad_writer_output():
    topics = config.load_topics()
    its = items(3)
    its[1].source_type = "podcast"
    data = {
        "headline": "x" * 100,
        "top3": [{"item_hash": "bogus", "line": "no"}, {"item_hash": its[0].hash, "line": "y" * 200}],
        "sections": [{"title": "Made up section", "items": [{"item_hash": its[0].hash, "summary": "s \u2014 t", "why_it_matters": "w"}]}],
    }
    out = digest.normalize(data, its, topics)
    assert len(out["headline"]) == 60
    assert len(out["top3"]) == 3 and out["top3"][0]["item_hash"] == its[0].hash
    titles = [s["title"] for s in out["sections"]]
    assert digest.PODCAST_SECTION in titles and digest.OTHER_SECTION in titles
    assert "\u2014" not in out["sections"][-1]["items"][0]["summary"]

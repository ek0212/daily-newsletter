"""Tests for news relevance scoring and filtering."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.news import _importance_score, _is_demoted, _categorize, _deduplicate


def test_importance_score_global_story():
    """Global stories with boost keywords should score higher."""
    global_story = {
        "title": "G7 Leaders Agree on New Climate Treaty at UN Summit",
        "raw_text": "World leaders gathered for an international summit to discuss climate change and global trade policy.",
    }
    local_story = {
        "title": "Local Man Wins County Fair Pie Contest",
        "raw_text": "A resident of Smalltown won first place at the annual county fair with his apple pie.",
    }
    assert _importance_score(global_story) > _importance_score(local_story)


def test_demote_filters_celebrity():
    story = {"title": "Kardashian Family Attends Grammy Awards Red Carpet", "raw_text": ""}
    assert _is_demoted(story)


def test_demote_filters_local_crime():
    story = {"title": "Bus Crash Injures Three on Local Highway", "raw_text": ""}
    assert _is_demoted(story)


def test_demote_keeps_major_news():
    story = {"title": "Federal Reserve Raises Interest Rates", "raw_text": "The Fed raised rates by 25 basis points."}
    assert not _is_demoted(story)


def test_categorize_war():
    story = {"title": "Ukraine Strikes Russian Military Base", "raw_text": ""}
    assert _categorize(story) == "war_conflict"


def test_categorize_economy():
    story = {"title": "Fed Raises Interest Rate Amid Inflation Fears", "raw_text": ""}
    assert _categorize(story) == "economy_jobs"


def test_categorize_other():
    story = {"title": "New Recipe for Chocolate Cake Goes Viral", "raw_text": ""}
    assert _categorize(story) == "other"


def test_deduplicate():
    stories = [
        {"title": "Ukraine Strikes Russian Base in Crimea"},
        {"title": "Ukraine Strikes Russian Military Base in Crimea Region"},
        {"title": "Fed Raises Interest Rates to 22-Year High"},
    ]
    result = _deduplicate(stories)
    assert len(result) == 2  # one Ukraine dupe removed


if __name__ == "__main__":
    test_importance_score_global_story()
    test_demote_filters_celebrity()
    test_demote_filters_local_crime()
    test_demote_keeps_major_news()
    test_categorize_war()
    test_categorize_economy()
    test_categorize_other()
    test_deduplicate()
    print("All tests passed!")

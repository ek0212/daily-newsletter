"""Tests for newsletter dashboard metadata."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.newsletter import _build_issue_dashboard


def test_build_issue_dashboard_uses_counts_and_cta() -> None:
    """Dashboard exposes counts, promise, and primary CTA."""
    data = {
        "weather": {
            "current_temp": 72,
            "conditions": "Sunny",
            "feels_like": 72,
            "high": 78,
            "low": 66,
        },
        "health": {"status": "LOW", "detail": "Below seasonal average."},
        "events": [{"name": "Street fair"}],
        "news": [{"title": "Market update"}],
        "youtube": [{"title": "New episode"}],
        "ai_security": [{"title": "Agent security paper"}, {"title": "Prompt injection news"}],
        "ai_security_tldr": "Agent tooling remains the main security focus.",
    }

    result = _build_issue_dashboard(data)

    assert result["reader_promise"]
    assert result["lead_detail"] == "Agent tooling remains the main security focus."
    assert [card["label"] for card in result["cards"]] == ["Weather", "Health", "Top risk", "AI sec", "YouTube"]
    assert all(card["emoji"] for card in result["cards"])
    assert all(card["value"] for card in result["cards"])
    assert all(card["detail"] for card in result["cards"])
    assert result["cards"][3]["value"] == "0 papers"
    assert result["cards"][4]["value"] == "1"
    assert result["exceptions"] == []


def test_build_issue_dashboard_flags_high_health_and_missing_feeds() -> None:
    """Dashboard reserves callouts for real exceptions."""
    data = {
        "weather": {"current_temp": 84, "conditions": "Thunderstorms", "high": 88, "low": 74},
        "health": {"status": "HIGH", "detail": "Above seasonal average."},
        "events": [],
        "news": [],
        "youtube": [],
        "ai_security": [],
        "ai_security_tldr": "",
    }

    result = _build_issue_dashboard(data)

    callout_text = " ".join(item["text"] for item in result["exceptions"])
    assert "Weather watch" in callout_text
    assert "NYC public-health watch" in callout_text
    assert "Top news feed returned no usable stories" in callout_text
    assert "AI security feeds returned no usable updates" in callout_text


def test_build_issue_dashboard_flags_health_watch_status() -> None:
    """Emerging advisory WATCH status appears in dashboard exceptions."""
    data = {
        "weather": {"current_temp": 72, "conditions": "Sunny", "high": 78, "low": 66},
        "health": {"status": "WATCH", "detail": "2 public-health advisory item(s) flagged"},
        "events": [{"name": "Street fair"}],
        "news": [{"title": "Market update"}],
        "youtube": [{"title": "New episode"}],
        "ai_security": [{"title": "Prompt injection news"}],
        "ai_security_tldr": "",
    }

    result = _build_issue_dashboard(data)

    assert result["cards"][1]["value"] == "Watch"
    assert result["exceptions"] == [
        {
            "level": "urgent",
            "text": "NYC public-health watch: 2 public-health advisory item(s) flagged.",
        }
    ]

"""Tests for canonical newsletter email layout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.newsletter import render_html


def _sample_data(include_todos: bool = True) -> dict:
    """Return minimal render data with every optional section populated."""
    data = {
        "date": "SUNDAY, AUGUST 02, 2026",
        "issue_dashboard": {
            "lead_detail": "This week's focus: agentic ai security and ai vulnerabilities.",
            "cards": [
                {"label": "Weather", "value": "82F", "detail": "10% rain"},
                {"label": "Health", "value": "Watch", "detail": "Week ending 2026-07-25"},
                {"label": "Top risk", "value": "Low", "detail": "Normal watch"},
                {"label": "AI sec", "value": "3 papers", "detail": "Jul 30"},
                {"label": "YouTube", "value": "0", "detail": "seeded videos"},
            ],
        },
        "weather": {
            "forecast_source": "Open-Meteo model consensus + National Weather Service",
            "forecast_source_count": 11,
            "hourly": [
                {
                    "label": "9am",
                    "temp": 78,
                    "feels_like": 83,
                    "conditions": "Cloudy",
                    "precip_chance": "3%",
                    "humidity": "77%",
                    "wind": "8 mph S",
                }
            ],
        },
        "health": {
            "status": "WATCH",
            "detail": "950 cases this week - 81% below average for this time of year",
            "signals": [
                {
                    "signal": "Respiratory illness",
                    "current": "950 combined flu/COVID/RSV cases",
                    "comparison": "81% below seasonal average",
                    "practical_read": "Normal context unless symptoms/exposure apply.",
                    "status": "LOW",
                }
            ],
        },
        "news": [
            {
                "title": "Top story",
                "summary": "Concrete takeaway.",
                "link": "https://example.com/news",
                "emoji": "News",
            }
        ],
        "youtube": [
            {
                "channel": "Example Channel",
                "title": "Useful video",
                "link": "https://youtube.com/watch?v=example",
            }
        ],
        "ai_security": [
            {
                "title": "Security article",
                "summary": "Security update.",
                "link": "https://example.com/security",
                "source": "Example",
                "type": "news",
            },
            {
                "title": "Security paper",
                "link": "https://example.com/paper",
                "type": "paper",
            },
        ],
        "events": [
            {
                "name": "School Parade",
                "date": "Wed, Aug 5",
                "location": "825 7th Ave",
                "link": "https://example.com/events/school-parade",
            }
        ],
        "notes": ["Generated from live fetchers."],
        "overall_signal": "Normal watch.",
    }
    if include_todos:
        data["suggested_todos"] = [
            {
                "item": "Review one open question",
                "source_signal": "wiki/example.md",
                "next_step": "Pick one small follow-up.",
            }
        ]
    return data


def test_template_keeps_august_21_reference_order() -> None:
    """August 21 reference keeps sectioned scan blocks before optional todos."""
    html = render_html(_sample_data())

    date_pos = html.index(">SUNDAY, AUGUST 02, 2026</div>")
    title_pos = html.index(">Daily Morning Briefing</div>")

    order = [
        "NYC Weather",
        "NYC Public Health",
        "Top 3 Things",
        "NYC Events",
        "General Top News",
        "Tech YouTube / Videos",
        "AI Security Articles",
        "AI Security Papers",
        "Second Brain Suggested Todos",
        "Overall signal:",
    ]
    positions = [html.index(item) for item in order]

    assert date_pos < title_pos < positions[0]
    assert positions == sorted(positions)
    assert html.count("Second Brain Suggested Todos") == 1
    assert "https://example.com/events/school-parade" in html
    assert "https://www.google.com/search" not in html
    assert "font-size:30px;line-height:36px" in html
    assert "Cloudy</td>" in html


def test_template_omits_second_brain_section_when_absent() -> None:
    """Reference layout has no Second Brain section unless caller supplies todos."""
    html = render_html(_sample_data(include_todos=False))

    assert "Second Brain Suggested Todos" not in html
    assert "Top 3 Things" in html

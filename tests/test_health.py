"""Tests for public-health signal extraction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.health import (
    _build_advisory_item,
    _deduplicate_advisories,
    _limit_advisory_clusters,
    _looks_like_public_health_alert,
)


def test_public_health_alert_detection_is_keyword_based() -> None:
    """Outbreak detection uses alert language, not hard-coded diseases."""
    assert _looks_like_public_health_alert(
        "Health Department investigating community cluster of waterborne illness"
    )
    assert _looks_like_public_health_alert(
        "FDA investigation update: outbreak linked to contaminated produce"
    )
    assert not _looks_like_public_health_alert(
        "Health Department launches insurance coverage awareness campaign"
    )


def test_build_advisory_item_extracts_counts_and_watch_status() -> None:
    """Advisory rows expose current counts and practical risk status."""
    item = _build_advisory_item(
        "City reports outbreak of gastrointestinal illness",
        "https://example.gov/outbreak",
        "Official source",
        "The agency reports 42 cases, 5 hospitalized, and 1 death in the current cluster.",
    )

    assert item["status"] == "WATCH"
    assert item["current"] == "42 cases, 5 hospitalized, 1 death"
    assert item["source_url"] == "https://example.gov/outbreak"


def test_deduplicate_advisories_keeps_highest_score() -> None:
    """Duplicate links keep the strongest advisory summary."""
    low = {"title": "Outbreak update", "source_url": "https://example.gov/a", "_score": 1}
    high = {"title": "Outbreak update", "source_url": "https://example.gov/a", "_score": 5}

    assert _deduplicate_advisories([low, high]) == [high]


def test_limit_advisory_clusters_preserves_distinct_conditions() -> None:
    """Repeated updates from one outbreak do not crowd out a different condition."""
    items = [
        {"title": "Health Department Reports Death in Upper East Side Legionnaires Disease Cluster"},
        {"title": "Health Department Updates Upper East Side Legionnaires Disease Cluster"},
        {"title": "Health Department Lists Cooling Towers in Upper East Side Legionnaires Disease Cluster"},
        {"title": "Health Department Reports Cyclosporiasis Cases in New York City"},
    ]

    result = _limit_advisory_clusters(items, max_per_cluster=2)

    assert len(result) == 3
    assert result[-1]["title"] == "Health Department Reports Cyclosporiasis Cases in New York City"

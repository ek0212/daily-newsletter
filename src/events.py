"""Fetch major NYC events from NYC Open Data (Socrata API, no key required)."""

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

API_URL = "https://data.cityofnewyork.us/resource/tvpp-9vvx.json"

# Event types that are always major (parades/races impact streets by definition)
ALWAYS_MAJOR_TYPES = {"Parade", "Athletic Race / Tour"}

# For "Special Event" type, only include if it has a full street closure
# (filters out lawn closures, picnics, small park events)


def get_nyc_events() -> list[dict]:
    """Fetch major NYC events for the current week (today through Sunday).

    Returns list of dicts with: name, date, borough, location, event_type.
    Deduplicates by event name (same event may span multiple street segments).
    """
    try:
        today = datetime.now()
        # End of week (Sunday)
        days_until_sunday = 6 - today.weekday()  # Monday=0, Sunday=6
        if days_until_sunday < 0:
            days_until_sunday = 0
        end_of_week = today + timedelta(days=days_until_sunday)

        start = today.strftime("%Y-%m-%dT00:00:00")
        end = end_of_week.strftime("%Y-%m-%dT23:59:59")

        # Query for parades, races, and special events with street closures
        query = (
            f"(event_type in('Parade','Athletic Race / Tour') "
            f"OR (event_type='Special Event' AND street_closure_type='Full Street Closure')) "
            f"AND start_date_time >= '{start}' "
            f"AND start_date_time <= '{end}'"
        )

        resp = requests.get(
            API_URL,
            params={"$where": query, "$limit": 50, "$order": "start_date_time ASC"},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()

        if not raw:
            logger.info("No major NYC events this week")
            return []

        # Deduplicate by event name (same parade has multiple street segments)
        seen = {}
        for item in raw:
            name = item.get("event_name", "").strip()
            if not name or name in seen:
                continue
            dt = item.get("start_date_time", "")
            try:
                event_date = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                date_str = event_date.strftime("%a, %b %-d")
            except (ValueError, AttributeError):
                date_str = "This week"

            seen[name] = {
                "name": name,
                "date": date_str,
                "borough": item.get("event_borough", ""),
                "location": item.get("event_location", ""),
                "event_type": item.get("event_type", ""),
            }

        events = list(seen.values())
        logger.info("Found %d major NYC events this week", len(events))
        return events

    except Exception as e:
        logger.error("NYC events fetch failed: %s", e)
        return []

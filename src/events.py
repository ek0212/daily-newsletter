"""Fetch major NYC events from NYC Open Data (Socrata API, no key required)."""

import logging
import re
from datetime import datetime, timedelta

import requests

from src.constants import (
    EVENTS_API_LIMIT,
    HTTP_TIMEOUT_MEDIUM,
    NYC_EVENTS_API_URL,
)

logger = logging.getLogger(__name__)

API_URL = NYC_EVENTS_API_URL

# Event types that are always major (parades/races impact streets by definition)
ALWAYS_MAJOR_TYPES = {"Parade", "Athletic Race / Tour"}

# For "Special Event" type, only include if it has a full street closure
# (filters out lawn closures, picnics, small park events)


def _clean_location(raw: str) -> str:
    """Extract a concise location from verbose street-segment data.

    Turns 'EAST 43 STREET between LEXINGTON AVENUE and 3 AVENUE, ...'
    into something like 'E 43rd St & Lexington Ave'.
    """
    if not raw:
        return ""
    # Take only the first segment (before first comma that starts a new segment)
    first = raw.split(",")[0].strip()
    # Extract "X between Y and Z" → "X & Y"
    m = re.match(r"(.+?)\s+between\s+(.+?)\s+and\s+", first, re.IGNORECASE)
    if m:
        street, cross = m.group(1).strip(), m.group(2).strip()
        return f"{_title_street(street)} & {_title_street(cross)}"
    # If it's a park/venue format like "Central Park: East Meadow", keep as-is
    return _title_street(first)


def _title_street(s: str) -> str:
    """Normalize ALL-CAPS street names to title case with ordinals."""
    s = " ".join(s.split())  # collapse whitespace
    s = s.title()
    # Fix ordinals: "43 Street" → "43rd St"
    s = re.sub(r"\b(\d+)\s+Street\b", lambda m: _ordinal(m.group(1)) + " St", s)
    s = re.sub(r"\b(\d+)\s+Avenue\b", lambda m: _ordinal(m.group(1)) + " Ave", s)
    s = s.replace("Avenue", "Ave").replace("Boulevard", "Blvd")
    return s


def _ordinal(n: str) -> str:
    num = int(n)
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(num % 10 if num % 100 not in (11, 12, 13) else 0, "th")
    return f"{num}{suffix}"


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
            params={"$where": query, "$limit": EVENTS_API_LIMIT, "$order": "start_date_time ASC"},
            timeout=HTTP_TIMEOUT_MEDIUM,
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
                "location": _clean_location(item.get("event_location", "")),
                "event_type": item.get("event_type", ""),
            }

        # Only include Brooklyn and Manhattan events
        events = [e for e in seen.values() if e["borough"] in ("Manhattan", "Brooklyn")]
        logger.info("Found %d major NYC events this week (Brooklyn/Manhattan only)", len(events))
        return events

    except Exception as e:
        logger.error("NYC events fetch failed: %s", e)
        return []

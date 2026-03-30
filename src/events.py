"""Fetch nearby NYC events from NYC Open Data (Socrata API, no key required).

Filters to Manhattan events with street closures within walking distance
of Midtown (~40 min walk = ~40 blocks north/south).
"""

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

# 40 min walking ≈ 2 miles ≈ 40 blocks north/south in Manhattan
_MIDTOWN_CENTER = 53
_WALK_RADIUS_BLOCKS = 40
MIN_STREET = _MIDTOWN_CENTER - _WALK_RADIUS_BLOCKS  # ~13th St
MAX_STREET = _MIDTOWN_CENTER + _WALK_RADIUS_BLOCKS  # ~93rd St


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


def _extract_street_number(location: str) -> int | None:
    """Extract the primary street number from an event location string.

    Handles formats like:
      'WEST 26 STREET between 11 AVENUE and 10 AVENUE'
      'EAST 43 STREET between LEXINGTON AVENUE and 3 AVENUE'
      '5 AVENUE between WEST 53 STREET and WEST 56 STREET'
    Returns the numbered street (not avenue) when possible.
    """
    if not location:
        return None
    # Look for patterns like "WEST 26 STREET", "EAST 43 STREET", "53 STREET"
    street_matches = re.findall(r'(?:WEST|EAST|W|E)?\s*(\d+)\s*(?:ST(?:REET)?)\b', location, re.IGNORECASE)
    if street_matches:
        return int(street_matches[0])
    # Fallback: any number before STREET
    m = re.search(r'(\d+)\s*(?:ST(?:REET)?)\b', location, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _is_within_walking_distance(location: str) -> bool:
    """Check if event location is within walking distance of Midtown."""
    street_num = _extract_street_number(location)
    if street_num is None:
        # Can't determine street number (park, named venue, etc.)
        # Include it so we don't accidentally drop big events
        return True
    return MIN_STREET <= street_num <= MAX_STREET


def get_nyc_events() -> list[dict]:
    """Fetch nearby NYC events for the current week (today through Sunday).

    Queries Manhattan events with any street closure, then filters to
    locations within walking distance of 53rd Street.
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

        # Manhattan events with any street closure (matches the NYC Open Data filter approach)
        query = (
            f"event_borough='Manhattan' "
            f"AND street_closure_type != 'N/A' "
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
            logger.info("No nearby NYC events this week")
            return []

        # Deduplicate by event name (same parade has multiple street segments)
        seen = {}
        for item in raw:
            name = item.get("event_name", "").strip()
            if not name or name in seen:
                continue

            location_raw = item.get("event_location", "")

            # Filter to walking distance from 53rd St
            if not _is_within_walking_distance(location_raw):
                street_num = _extract_street_number(location_raw)
                logger.debug("Skipping '%s' (street %s, outside %d-%d range)",
                             name[:40], street_num, MIN_STREET, MAX_STREET)
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
                "borough": "Manhattan",
                "location": _clean_location(location_raw),
                "event_type": item.get("event_type", ""),
            }

        events = list(seen.values())
        logger.info("Found %d nearby Manhattan events this week (within %d blocks of Midtown)",
                     len(events), _WALK_RADIUS_BLOCKS)
        return events

    except Exception as e:
        logger.error("NYC events fetch failed: %s", e)
        return []

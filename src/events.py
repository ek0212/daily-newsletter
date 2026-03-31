"""Fetch nearby NYC events from NYC Open Data (Socrata API, no key required).

Filters to Manhattan events with street closures between downtown
and 90th Street.
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

# Downtown Manhattan (1st St) up to 90th Street
MIN_STREET = 0
MAX_STREET = 90

# Named streets/areas known to be above 90th St — exclude these
_FAR_UPTOWN_KEYWORDS = [
    "inwood", "isham", "dyckman", "fort tryon", "fort george",
    "washington heights", "harlem", "morningside", "cathedral",
    "broadway terrace", "nagle", "academy", "hillside",
    "seaman", "indian road", "payson", "cooper",
    "edgecombe", "convent", "hamilton terrace",
]

MAX_EVENTS_DISPLAY = 5

# Events with full street closures get priority (they actually affect your commute)
_CLOSURE_PRIORITY = {
    "Full Street Closure": 3,
    "Sidewalk and Curb Lane Closure": 2,
    "Curb Lane Only": 1,
}

# Event types that indicate large public events
_TYPE_PRIORITY = {
    "Parade": 5,
    "Athletic Race / Tour": 4,
    "Street Festival": 3,
    "Religious Event": 2,
    "Street Event": 1,
    "Special Event": 1,
    "Production Event": 0,
}

# Keywords that indicate low-interest private/commercial events
_LOW_INTEREST_KEYWORDS = [
    "private event", "invite only", "sound test", "load in", "load out",
    "setup", "strike", "filming", "production hold", "crane", "scaffold",
    "construction", "utility", "maintenance", "permit", "launch day",
    "sampling", "activation", "pop-up", "popup",
]


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


def _is_within_range(location: str) -> bool:
    """Check if event location is between downtown and 90th St."""
    # First check if location contains known far-uptown keywords
    loc_lower = location.lower()
    for kw in _FAR_UPTOWN_KEYWORDS:
        if kw in loc_lower:
            return False

    street_num = _extract_street_number(location)
    if street_num is None:
        # Can't determine street number (park, named venue, etc.)
        # Include it so we don't accidentally drop big events in
        # lower/midtown Manhattan (most permitted events are there)
        return True
    return MIN_STREET <= street_num <= MAX_STREET


def _relevance_score(name: str, event_type: str, closure_type: str) -> float:
    """Score an event's relevance. Higher = more interesting to a local reader."""
    name_lower = name.lower()

    # Penalize private/commercial/low-interest events heavily
    for kw in _LOW_INTEREST_KEYWORDS:
        if kw in name_lower:
            return -10

    score = 0.0
    score += _TYPE_PRIORITY.get(event_type, 0)
    score += _CLOSURE_PRIORITY.get(closure_type, 0)

    # Bonus for recognizable public events (markets, galas, cultural)
    public_keywords = ["parade", "marathon", "festival", "block party", "market",
                       "greenmarket", "gala", "ceremony", "awards", "way of the cross",
                       "procession", "fair", "shred-a-thon", "recycling"]
    for kw in public_keywords:
        if kw in name_lower:
            score += 3
            break

    return score


def get_nyc_events() -> list[dict]:
    """Fetch nearby NYC events for the current week (today through Sunday).

    Queries Manhattan events with any street closure, filters to walking
    distance of Midtown, ranks by relevance, and returns the top results.
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

            # Filter to downtown through 90th St
            if not _is_within_range(location_raw):
                continue

            dt = item.get("start_date_time", "")
            try:
                event_date = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                date_str = event_date.strftime("%a, %b %-d")
            except (ValueError, AttributeError):
                date_str = "This week"

            event_type = item.get("event_type", "")
            closure_type = item.get("street_closure_type", "")
            score = _relevance_score(name, event_type, closure_type)

            seen[name] = {
                "name": name,
                "date": date_str,
                "borough": "Manhattan",
                "location": _clean_location(location_raw),
                "event_type": event_type,
                "_score": score,
            }

        # Rank by relevance score and take the top N
        ranked = sorted(seen.values(), key=lambda e: e["_score"], reverse=True)
        events = ranked[:MAX_EVENTS_DISPLAY]

        # Clean up internal score field
        for e in events:
            del e["_score"]

        logger.info("Found %d Manhattan events (downtown-90th), showing top %d by relevance",
                     len(seen), len(events))
        return events

    except Exception as e:
        logger.error("NYC events fetch failed: %s", e)
        return []

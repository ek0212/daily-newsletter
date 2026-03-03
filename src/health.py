"""Fetch NYC respiratory illness levels from NYC Health Department open data."""

import csv
import io
import logging
from datetime import datetime, timedelta

import requests

from src.constants import (
    HEALTH_DEVIATION_THRESHOLD,
    HTTP_TIMEOUT_MEDIUM,
    NYC_HEALTH_BASE_URL,
)

logger = logging.getLogger(__name__)

BASE_URL = NYC_HEALTH_BASE_URL
CSVS = {
    "flu": f"{BASE_URL}/Case_data_influenza.csv",
    "covid": f"{BASE_URL}/Case_data_COVID-19.csv",
    "rsv": f"{BASE_URL}/Case_data_RSV.csv",
}

# Column names in the CSVs (second column varies)
CASE_COLUMNS = {
    "flu": "Influenza cases overall",
    "covid": "COVID-19 cases overall",
    "rsv": "RSV cases overall",
}


def _fetch_csv(url: str) -> list[dict]:
    """Fetch a CSV and return rows as list of dicts."""
    resp = requests.get(url, timeout=HTTP_TIMEOUT_MEDIUM)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return list(reader)


def _parse_cases(rows: list[dict], case_col: str) -> dict[str, int]:
    """Parse CSV rows into {date_str: case_count} dict."""
    result = {}
    for row in rows:
        date_str = row.get("date", "").strip()
        raw = row.get(case_col, "").strip()
        if date_str and raw:
            try:
                result[date_str] = int(float(raw))
            except ValueError:
                continue
    return result


def _get_week_number(date_str: str) -> int:
    """Get ISO week number from a date string."""
    return datetime.strptime(date_str, "%Y-%m-%d").isocalendar()[1]


def get_nyc_health_status() -> dict:
    """Fetch NYC respiratory illness data and compare to historical averages.

    Returns dict with status (HIGH/NORMAL/LOW), detail string, and breakdown.
    """
    try:
        all_cases = {}
        for illness, url in CSVS.items():
            try:
                rows = _fetch_csv(url)
                col = CASE_COLUMNS[illness]
                all_cases[illness] = _parse_cases(rows, col)
            except Exception as e:
                logger.warning("Failed to fetch %s data: %s", illness, e)
                all_cases[illness] = {}

        if not any(all_cases.values()):
            return {"status": "UNKNOWN", "detail": "Health data unavailable"}

        # Find the latest date across all datasets
        all_dates = set()
        for cases in all_cases.values():
            all_dates.update(cases.keys())
        if not all_dates:
            return {"status": "UNKNOWN", "detail": "Health data unavailable"}

        latest_date = max(all_dates)
        latest_week = _get_week_number(latest_date)

        # Current week's counts
        breakdown = {}
        for illness, cases in all_cases.items():
            breakdown[illness] = cases.get(latest_date, 0)
        current_total = sum(breakdown.values())

        # Historical average for the same week number (excluding current year)
        latest_year = datetime.strptime(latest_date, "%Y-%m-%d").year
        historical_totals = []
        for date_str in all_dates:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt.year < latest_year and _get_week_number(date_str) == latest_week:
                total = sum(cases.get(date_str, 0) for cases in all_cases.values())
                if total > 0:
                    historical_totals.append(total)

        if not historical_totals:
            # Not enough history — just report the numbers without comparison
            return {
                "status": "UNKNOWN",
                "detail": f"{current_total:,} respiratory cases this week (no historical baseline yet)",
                "combined_cases": current_total,
                "vs_average_pct": 0,
                "week_ending": latest_date,
                "breakdown": breakdown,
            }

        avg = sum(historical_totals) / len(historical_totals)
        pct_change = ((current_total - avg) / avg) * 100 if avg > 0 else 0

        if pct_change > HEALTH_DEVIATION_THRESHOLD:
            status = "HIGH"
        elif pct_change < -HEALTH_DEVIATION_THRESHOLD:
            status = "LOW"
        else:
            status = "NORMAL"

        # Build detail string
        if status == "HIGH":
            detail = f"{current_total:,} cases this week — {abs(pct_change):.0f}% above average for this time of year"
        elif status == "LOW":
            detail = f"{current_total:,} cases this week — {abs(pct_change):.0f}% below average for this time of year"
        else:
            detail = f"{current_total:,} cases this week — near average for this time of year"

        logger.info("NYC health status: %s (%s)", status, detail)

        return {
            "status": status,
            "detail": detail,
            "combined_cases": current_total,
            "vs_average_pct": round(pct_change, 1),
            "week_ending": latest_date,
            "breakdown": breakdown,
        }

    except Exception as e:
        logger.error("Health data fetch failed: %s", e)
        return {"status": "UNKNOWN", "detail": "Health data unavailable"}

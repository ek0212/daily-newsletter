"""Fetch NYC public-health signals from official respiratory and advisory sources."""

import csv
import html
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlencode

import feedparser
import requests

from src.constants import (
    CDC_FOOD_SAFETY_RSS_URL,
    FDA_FOODBORNE_OUTBREAKS_URL,
    HEALTH_DEVIATION_THRESHOLD,
    HTTP_TIMEOUT_MEDIUM,
    NYC_HEALTH_BASE_URL,
    NYC_HEALTH_PRESS_RELEASES_URL,
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

MAX_ADVISORY_ITEMS = 5
ADVISORY_LOOKBACK_DAYS = 30

OFFICIAL_ADVISORY_SOURCES = [
    {
        "name": "NYC Health press releases",
        "url": NYC_HEALTH_PRESS_RELEASES_URL,
        "kind": "links",
    },
    {
        "name": "FDA foodborne outbreak investigations",
        "url": FDA_FOODBORNE_OUTBREAKS_URL,
        "kind": "links",
    },
    {
        "name": "CDC food safety RSS",
        "url": CDC_FOOD_SAFETY_RSS_URL,
        "kind": "rss",
    },
]

OFFICIAL_TOPIC_PAGES = [
    {
        "name": "NYC Health Legionnaires disease",
        "url": "https://www.nyc.gov/site/doh/health/health-topics/legionnaires-disease.page",
    },
    {
        "name": "NYC Health cyclosporiasis",
        "url": "https://www.nyc.gov/site/doh/health/health-topics/cyclosporiasis.page",
    },
]

GOOGLE_NEWS_HEALTH_QUERIES = [
    '"NYC Health" (outbreak OR cluster OR "health advisory" OR "increase in cases" OR hospitalized OR deaths)',
    '("New York City" OR NYC) (outbreak OR cluster OR "health advisory") (disease OR illness OR infection)',
    '(CDC OR FDA) (outbreak OR "health alert" OR "health advisory") ("New York" OR NYC)',
]

_ALERT_KEYWORDS = re.compile(
    r"(?i)\b("
    r"outbreak|cluster|health advisory|investigat(?:e|ing|ion)|increase in cases|"
    r"reported cases|diagnosed|hospitali[sz]ed|death|deaths|illness|infection|"
    r"disease|foodborne|waterborne|parasite|bacteria|virus|contamination|recall|"
    r"pneumonia|gastrointestinal|diarrhea|vomiting|fever"
    r")\b"
)
_NOISE_KEYWORDS = re.compile(
    r"(?i)\b(campaign|celebrates|awareness|insurance coverage|vending machines|"
    r"child care|supportive housing|media campaign|study highlights|renovation|"
    r"post-outbreak response|resources?|tips|overview|reports?|improvement plan|"
    r"outbreaks of foodborne illness|investigations of foodborne illness outbreaks|"
    r"public health advisories from investigations|outbreak advisory|foodborne pathogens)\b"
)
_URGENT_KEYWORDS = re.compile(
    r"(?i)\b(death|deaths|hospitali[sz]ed|health advisory|outbreak|cluster|"
    r"contamination|recall|investigat(?:e|ing|ion)|reported cases|"
    r"increased number of cases|increase in cases|cases diagnosed)\b"
)
_COUNT_PATTERN = re.compile(
    r"(?i)\b(\d[\d,]*)\s+(cases?|people|diagnoses|diagnosed|hospitali[sz]ed|deaths?|illness(?:es)?)\b"
)
_DATE_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s+(20\d{2})\b"
)
_NAVIGATION_NOISE = re.compile(
    r"(?i)(search all nyc\.gov websites|text-size search|home covid about our health services|"
    r"skip to main content|official websites use \.gov)"
)
_TITLE_STOPWORDS = {
    "health",
    "department",
    "reports",
    "provides",
    "preliminary",
    "releases",
    "disease",
    "cluster",
    "outbreak",
    "investigation",
    "investigating",
    "community",
    "official",
    "update",
    "updates",
    "where",
    "testing",
    "upper",
    "east",
    "side",
    "mayor",
    "takes",
    "aggressive",
    "action",
    "address",
    "second",
    "preliminary",
    "list",
    "buildings",
    "ordered",
    "clean",
    "disinfect",
    "cooling",
    "towers",
    "confirms",
    "bacteria",
    "source",
    "exposure",
    "likely",
    "eliminated",
}


class _LinkExtractor(HTMLParser):
    """Extract links and visible anchor text from official HTML pages."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self._href = ""
        self._text_parts: list[str] = []
        self.links: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        self._href = attrs_dict.get("href") or ""
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        text = _normalize_text(" ".join(self._text_parts))
        if text:
            self.links.append({"title": text, "link": urljoin(self.base_url, self._href)})
        self._href = ""
        self._text_parts = []


def _normalize_text(value: str) -> str:
    """Collapse whitespace and unescape HTML entities."""
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _strip_html(value: str) -> str:
    """Convert HTML to compact plain text without scripts or styles."""
    value = re.sub(r"(?is)<(script|style).*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return _normalize_text(value)


def _looks_like_public_health_alert(text: str) -> bool:
    """Return true when text looks like an outbreak/advisory item."""
    normalized = _normalize_text(text).lower()
    if normalized in {"outbreak advisory", "foodborne pathogens", "outbreaks of foodborne illness"}:
        return False
    if not _ALERT_KEYWORDS.search(text):
        return False
    if _NOISE_KEYWORDS.search(text) and not _COUNT_PATTERN.search(text) and "recall" not in text.lower():
        return False
    return True


def _advisory_score(item: dict) -> int:
    """Rank public-health advisory items by likely practical relevance."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    score = 0
    for pattern, weight in [
        (r"(?i)\b(death|deaths)\b", 6),
        (r"(?i)\bhospitali[sz]ed\b", 5),
        (r"(?i)\b(increased number of cases|increase in cases|cases diagnosed|reported cases)\b", 4),
        (r"(?i)\b(outbreak|cluster|health advisory)\b", 4),
        (r"(?i)\b(investigat(?:e|ing|ion)|increase in cases|reported cases)\b", 3),
        (r"(?i)\b(foodborne|waterborne|parasite|bacteria|virus|contamination|recall)\b", 2),
        (r"(?i)\b(NYC|New York City|New York)\b", 2),
    ]:
        if re.search(pattern, text):
            score += weight
    if _COUNT_PATTERN.search(text):
        score += 3
    return score


def _extract_links(html_text: str, base_url: str) -> list[dict]:
    """Extract anchors from an HTML page."""
    parser = _LinkExtractor(base_url)
    parser.feed(html_text)
    return parser.links


def _fetch_text(url: str) -> str:
    """Fetch URL text with a newsletter user agent."""
    resp = requests.get(
        url,
        timeout=HTTP_TIMEOUT_MEDIUM,
        headers={"User-Agent": "DailyNewsletter/1.0"},
    )
    resp.raise_for_status()
    return resp.text


def _extract_date_label(text: str) -> str:
    """Extract first Month D, YYYY date label from text."""
    match = _DATE_PATTERN.search(text or "")
    return _normalize_text(match.group(0)) if match else ""


def _is_recent_date_label(label: str) -> bool:
    """Return true when date label is inside the advisory lookback window."""
    if not label:
        return False
    try:
        dt = datetime.strptime(label, "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - dt <= timedelta(days=ADVISORY_LOOKBACK_DAYS)


def _extract_stats(text: str) -> str:
    """Pull compact case/hospital/death counts from advisory text."""
    matches = []
    seen = set()
    for match in _COUNT_PATTERN.finditer(text):
        value = _normalize_text(match.group(0))
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        matches.append(value)
        if len(matches) == 3:
            break
    return ", ".join(matches)


def _best_sentence(title: str, text: str) -> str:
    """Choose a concise advisory sentence from title/body text."""
    candidates = re.split(r"(?<=[.!?])\s+", text)
    for sentence in candidates:
        sentence = _normalize_text(sentence)
        if len(sentence) < 40:
            continue
        if _NAVIGATION_NOISE.search(sentence):
            continue
        if _LOOKS_PRACTICAL.search(sentence):
            return sentence[:260]
    stats = _extract_stats(text)
    if stats:
        return f"{title}: {stats}."
    return title


_LOOKS_PRACTICAL = re.compile(
    r"(?i)\b(cases?|diagnosed|hospitali[sz]ed|death|deaths|outbreak|cluster|"
    r"investigat(?:e|ing|ion)|recall|contamination|symptoms?|avoid|seek)\b"
)


def _build_advisory_item(title: str, link: str, source: str, body_text: str = "", published: str = "") -> dict:
    """Build normalized advisory item for the health section."""
    title = _normalize_text(title)
    body_text = _normalize_text(body_text)
    published = published or _extract_date_label(body_text)
    stats = _extract_stats(body_text)
    current = stats or _best_sentence(title, body_text or title)
    status = "WATCH" if _URGENT_KEYWORDS.search(f"{title} {body_text}") else "INFO"
    score = _advisory_score({"title": title, "summary": body_text})
    if source.startswith("NYC Health ") and source != "NYC Health press releases":
        score += 8
    return {
        "signal": title[:110],
        "current": current[:180],
        "comparison": published or source,
        "practical_read": "Watch official updates; use symptoms/exposure guidance if relevant." if status == "WATCH" else "Awareness item; no immediate action unless exposed.",
        "status": status,
        "source": source,
        "source_url": link,
        "title": title,
        "summary": _best_sentence(title, body_text or title),
        "published": published,
        "_score": score,
    }


def _fetch_advisories_from_links(source: dict) -> list[dict]:
    """Fetch official page links and keep alert-like items."""
    try:
        page_html = _fetch_text(source["url"])
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", source["name"], e)
        return []

    advisories = []
    for link in _extract_links(page_html, source["url"])[:80]:
        title = link["title"]
        if link["link"].split("#")[0].rstrip("/") == source["url"].rstrip("/"):
            continue
        if not _looks_like_public_health_alert(title):
            continue
        body_text = ""
        try:
            body_text = _strip_html(_fetch_text(link["link"]))
        except Exception as e:
            logger.debug("Failed to fetch advisory detail %s: %s", link["link"], e)
        published = _extract_date_label(body_text)
        if published and not _is_recent_date_label(published):
            continue
        if source["name"].startswith("FDA") and not published:
            continue
        advisories.append(_build_advisory_item(title, link["link"], source["name"], body_text, published))
    return advisories


def _fetch_advisories_from_rss(source: dict) -> list[dict]:
    """Fetch RSS feed items that look like health advisories."""
    try:
        feed = feedparser.parse(source["url"])
    except Exception as e:
        logger.warning("Failed to parse %s: %s", source["name"], e)
        return []

    advisories = []
    now = datetime.now(timezone.utc)
    for entry in feed.entries[:30]:
        published = entry.get("published", "")
        try:
            dt = parsedate_to_datetime(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now - dt).days > ADVISORY_LOOKBACK_DAYS:
                continue
        except Exception:
            pass
        title = _normalize_text(entry.get("title", ""))
        summary = _strip_html(entry.get("summary", ""))
        if not _looks_like_public_health_alert(f"{title} {summary}"):
            continue
        advisories.append(
            _build_advisory_item(
                title,
                entry.get("link", source["url"]),
                source["name"],
                summary,
                published,
            )
        )
    return advisories


def _fetch_google_news_advisories() -> list[dict]:
    """Use broad news search to detect new disease names without disease-specific queries."""
    advisories = []
    now = datetime.now(timezone.utc)
    for query in GOOGLE_NEWS_HEALTH_QUERIES:
        url = "https://news.google.com/rss/search?" + urlencode(
            {
                "q": f"{query} when:30d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            }
        )
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.warning("Failed to parse health news query: %s", e)
            continue
        for entry in feed.entries[:8]:
            title = _normalize_text(entry.get("title", ""))
            summary = _strip_html(entry.get("summary", ""))
            if not _looks_like_public_health_alert(f"{title} {summary}"):
                continue
            published = entry.get("published", "")
            try:
                dt = parsedate_to_datetime(published)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if (now - dt).days > ADVISORY_LOOKBACK_DAYS:
                    continue
            except Exception:
                pass
            advisories.append(
                _build_advisory_item(
                    title,
                    entry.get("link", ""),
                    "Google News health watch",
                    summary,
                    published,
                )
            )
    return advisories


def _fetch_topic_page_advisories() -> list[dict]:
    """Fetch active official topic pages that may hold current outbreak counters."""
    advisories = []
    for source in OFFICIAL_TOPIC_PAGES:
        try:
            body_text = _strip_html(_fetch_text(source["url"]))
        except Exception as e:
            logger.warning("Failed to fetch topic page %s: %s", source["name"], e)
            continue
        if not _looks_like_public_health_alert(body_text[:4000]):
            continue
        advisories.append(
            _build_advisory_item(
                source["name"],
                source["url"],
                source["name"],
                body_text[:6000],
            )
        )
    return advisories


def _deduplicate_advisories(items: list[dict]) -> list[dict]:
    """Deduplicate advisories by title/link while keeping strongest scoring item."""
    best: dict[str, dict] = {}
    for item in items:
        title_key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
        link_key = item.get("source_url", "").split("?")[0].lower()
        key = link_key or title_key
        if not key:
            continue
        existing = best.get(key)
        if not existing or item.get("_score", 0) > existing.get("_score", 0):
            best[key] = item
    return sorted(best.values(), key=lambda item: item.get("_score", 0), reverse=True)


def _title_words(title: str) -> set[str]:
    """Extract topic words from advisory title for overlap clustering."""
    words = {word.lower() for word in re.findall(r"\b[A-Za-z][A-Za-z'’\-]{4,}\b", title)}
    words = words - _TITLE_STOPWORDS
    stems = {word[:6] for word in words if len(word) >= 8}
    return words | stems


def _limit_advisory_clusters(items: list[dict], max_per_cluster: int = 1) -> list[dict]:
    """Limit repeated updates about the same outbreak without naming diseases."""
    kept: list[dict] = []
    clusters: list[tuple[set[str], int]] = []
    for item in items:
        words = _title_words(item.get("title", ""))
        matched_index = None
        for idx, (cluster_words, count) in enumerate(clusters):
            if not words or not cluster_words:
                continue
            overlap = len(words & cluster_words) / min(len(words), len(cluster_words))
            if overlap >= 0.2:
                matched_index = idx
                if count >= max_per_cluster:
                    matched_index = -1
                break
        if matched_index == -1:
            continue
        if matched_index is None:
            clusters.append((words, 1))
        else:
            cluster_words, count = clusters[matched_index]
            clusters[matched_index] = (cluster_words | words, count + 1)
        kept.append(item)
    return kept


def _fetch_public_health_advisories() -> list[dict]:
    """Fetch broad official/advisory surfaces for emerging health exceptions."""
    items = []
    for source in OFFICIAL_ADVISORY_SOURCES:
        if source["kind"] == "rss":
            items.extend(_fetch_advisories_from_rss(source))
        else:
            items.extend(_fetch_advisories_from_links(source))
    items.extend(_fetch_topic_page_advisories())
    items.extend(_fetch_google_news_advisories())
    deduped = _deduplicate_advisories(items)
    clustered = _limit_advisory_clusters(deduped)
    logger.info("Public-health advisory watch found %d items", len(clustered))
    selected = clustered[:MAX_ADVISORY_ITEMS]
    for item in selected:
        item.pop("_score", None)
    return selected


def _overall_health_status(respiratory_status: str, advisories: list[dict]) -> str:
    """Combine respiratory baseline and advisory exceptions into one status."""
    if any(item.get("status") == "WATCH" for item in advisories):
        return "WATCH"
    return respiratory_status

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
    """Fetch NYC respiratory baseline plus broad public-health advisory watch.

    Returns:
        Dict with legacy respiratory fields plus a `signals` list for email rows.
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

        advisories = _fetch_public_health_advisories()

        if not any(all_cases.values()):
            status = _overall_health_status("UNKNOWN", advisories)
            return {
                "status": status,
                "detail": "Health data unavailable" if not advisories else f"{len(advisories)} public-health advisory item(s) found",
                "signals": advisories,
                "advisories": advisories,
            }

        # Find the latest date across all datasets
        all_dates = set()
        for cases in all_cases.values():
            all_dates.update(cases.keys())
        if not all_dates:
            status = _overall_health_status("UNKNOWN", advisories)
            return {
                "status": status,
                "detail": "Health data unavailable" if not advisories else f"{len(advisories)} public-health advisory item(s) found",
                "signals": advisories,
                "advisories": advisories,
            }

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
            respiratory_signal = {
                "signal": "Respiratory illness",
                "current": f"{current_total:,} combined flu/COVID/RSV cases",
                "comparison": "No historical baseline yet",
                "practical_read": "Use as context; watch official advisories for non-respiratory outbreaks.",
                "status": "UNKNOWN",
                "source": "NYC Health respiratory illness data",
                "source_url": BASE_URL,
            }
            signals = [respiratory_signal] + advisories
            status = _overall_health_status("UNKNOWN", advisories)
            return {
                "status": status,
                "detail": f"{current_total:,} respiratory cases this week (no historical baseline yet)",
                "combined_cases": current_total,
                "vs_average_pct": 0,
                "week_ending": latest_date,
                "breakdown": breakdown,
                "signals": signals,
                "advisories": advisories,
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

        respiratory_signal = {
            "signal": "Respiratory illness",
            "current": f"{current_total:,} combined flu/COVID/RSV cases",
            "comparison": f"{abs(pct_change):.0f}% {'above' if pct_change > 0 else 'below'} seasonal average",
            "practical_read": "Normal context unless symptoms/exposure apply." if status != "HIGH" else "Elevated respiratory signal; consider masking around vulnerable people.",
            "status": status,
            "source": "NYC Health respiratory illness data",
            "source_url": BASE_URL,
        }
        signals = [respiratory_signal] + advisories
        overall_status = _overall_health_status(status, advisories)
        if advisories:
            detail = f"{detail}; {len(advisories)} public-health advisory item(s) flagged"

        logger.info("NYC health status: %s (%s)", overall_status, detail)

        return {
            "status": overall_status,
            "respiratory_status": status,
            "detail": detail,
            "combined_cases": current_total,
            "vs_average_pct": round(pct_change, 1),
            "week_ending": latest_date,
            "breakdown": breakdown,
            "signals": signals,
            "advisories": advisories,
        }

    except Exception as e:
        logger.error("Health data fetch failed: %s", e)
        return {"status": "UNKNOWN", "detail": "Health data unavailable"}

"""Fetch top news headlines from broad, diverse sources (CNN '5 things' style).

Prioritizes the biggest stories of the day across geopolitics, economy, science,
society, and technology. Enforces topic diversity so no two stories cover the
same subject.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import trafilatura
from googlenewsdecoder import new_decoderv1

from src.constants import (
    DEDUP_OVERLAP_THRESHOLD,
    MIN_TEXT_LENGTH_SHORT,
    NEWS_FEED_LIMIT_MULTIPLIER,
)
from src.summarizer import summarize as extractive_summarize

logger = logging.getLogger(__name__)

# RSS sources — broad, major news outlets
NEWS_FEEDS = [
    # Sources chosen for trafilatura compatibility:
    # clean RSS feeds + extractable HTML, no paywalls, server-rendered pages
    {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "name": "NPR",
        "is_google": False,
    },
    {
        "url": "https://www.theguardian.com/world/rss",
        "name": "The Guardian",
        "is_google": False,
    },
    {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "name": "Al Jazeera",
        "is_google": False,
    },
    {
        "url": "http://rss.cnn.com/rss/cnn_topstories.rss",
        "name": "CNN",
        "is_google": False,
    },
    {
        "url": "https://feeds.reuters.com/reuters/topNews",
        "name": "Reuters",
        "is_google": False,
    },
    # Google News top stories (wide coverage, redirect decoding built in)
    {
        "url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "name": "Google News",
        "is_google": True,
    },
]

# Topic categories for diversity enforcement
# Each story gets tagged with a category; we try to pick at most 1 per category
_TOPIC_CATEGORIES = [
    ("war_conflict", re.compile(r'(?i)\b(?:war|attack|strike|bomb|invasion|military|missile|ceasefire|troop|iran|ukraine|russia|gaza|houthi|yemen|tariff war)\b')),
    ("politics_govt", re.compile(r'(?i)\b(?:congress|senate|house|trump|biden|executive order|legislation|supreme court|scotus|white house|dhs|shutdown|impeach|election|vote|protest|rally)\b')),
    ("economy_jobs", re.compile(r'(?i)\b(?:economy|recession|inflation|jobs?|unemployment|market|stock|dow|nasdaq|fed|interest rate|gdp|trade|tariff|401.?k|housing|rent|salary|layoff)\b')),
    ("science_space", re.compile(r'(?i)\b(?:nasa|space|moon|mars|artemis|rocket|satellite|climate|earthquake|hurricane|tornado|vaccine|pandemic|disease)\b')),
    ("tech_ai", re.compile(r'(?i)\b(?:ai\b|artificial intelligence|openai|google|apple|meta|microsoft|amazon|nvidia|robot|autonomous|cyber|hack|breach)\b')),
    ("crime_justice", re.compile(r'(?i)\b(?:shooting|murder|arrest|trial|verdict|sentence|prison|fbi|police|investigation|indictment|epstein|crime)\b')),
    ("travel_transport", re.compile(r'(?i)\b(?:airport|airline|flight|travel|faa|crash|collision|runway|train|highway|bridge)\b')),
]

# Source domains that produce low-quality or unreliable content
_BLOCKED_DOMAINS = {
    "aol.com", "wjla.com", "blockchain-council.org",
    "dailymail.co.uk", "thesun.co.uk", "nypost.com",
    "breitbart.com", "infowars.com", "naturalnews.com",
    "msn.com",  # aggregator with low-quality summaries
    "yahoo.com",  # aggregator
}

# Topics to deprioritize — celebrity gossip, sports entertainment, reality TV, local crime
_DEMOTE_KEYWORDS = re.compile(
    r'(?i)\b(?:'
    r'love island|kardashian|bachelor|bachelorette|real housewives|'
    r'celebrity|gossip|red carpet|grammy|oscar|emmy|golden globe|'
    r'nfl draft|nba trade|mlb|nhl|premier league|fifa|'
    r'flamingo land|loch lomond|bone cement|horoscope|zodiac|'
    r'retirement home|nursing home|local police|school bus|'
    r'car crash|bus crash|hit.and.run|pedestrian struck|'
    r'lottery winner|pet rescue|county fair|prom|homecoming'
    r')\b'
)

# Boost keywords — stories matching these are more likely to be globally important
_BOOST_KEYWORDS = re.compile(
    r'(?i)\b(?:'
    r'world leader|g7|g20|united nations|nato|eu|european union|'
    r'president|prime minister|summit|treaty|ceasefire|'
    r'global|international|billion|trillion|pandemic|'
    r'climate change|earthquake|hurricane|tsunami|'
    r'fed|federal reserve|wall street|recession|'
    r'nuclear|sanctions|embargo|trade war|tariff'
    r')\b'
)


def _is_blocked_source(story: dict) -> bool:
    """Return True if the story's URL domain is on the blocklist."""
    url = story.get("link", "")
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain == blocked or domain.endswith("." + blocked) for blocked in _BLOCKED_DOMAINS)
    except Exception:
        return False


def _categorize(story: dict) -> str:
    """Assign a topic category to a story. Returns category name or 'other'."""
    text = f"{story.get('title', '')} {story.get('raw_text', '')[:300]}"
    for cat_name, pattern in _TOPIC_CATEGORIES:
        if pattern.search(text):
            return cat_name
    return "other"


def _is_demoted(story: dict) -> bool:
    """Check if a story matches low-interest patterns."""
    text = f"{story.get('title', '')} {story.get('raw_text', '')[:200]}"
    return bool(_DEMOTE_KEYWORDS.search(text))


def _importance_score(story: dict) -> float:
    """Score a story's global importance. Higher = more important."""
    text = f"{story.get('title', '')} {story.get('raw_text', '')[:500]}"
    score = 0.0

    # Boost for globally important keywords
    boost_matches = len(_BOOST_KEYWORDS.findall(text))
    score += boost_matches * 2.0

    # Penalize demoted stories
    if _DEMOTE_KEYWORDS.search(text):
        score -= 10.0

    # Boost stories from multiple sources (likely big stories)
    # Boost stories with longer raw_text (more coverage = more important)
    raw_len = len(story.get("raw_text", ""))
    if raw_len > 1000:
        score += 1.0

    # Boost Google News stories (already editorially selected as top stories)
    if story.get("source") and story["source"] not in ("NPR", "The Guardian", "Al Jazeera", "CNN", "Reuters"):
        score += 1.5

    return score


def _decode_google_news_url(url: str) -> str:
    """Decode Google News protobuf-encoded URL to the real article URL."""
    try:
        result = new_decoderv1(url)
        if result.get("status"):
            decoded = result["decoded_url"]
            logger.debug("Decoded Google News URL: %s", decoded[:100])
            return decoded
    except Exception as e:
        logger.debug("Failed to decode Google News URL: %s", e)
    return url


def _fetch_article_text(url: str) -> str:
    """Fetch article page and return extracted full text."""
    try:
        # Decode Google News URL to real article URL
        if "news.google.com" in url:
            url = _decode_google_news_url(url)

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded)
            if text and len(text) > MIN_TEXT_LENGTH_SHORT:
                logger.info("Article text extracted: %d chars from %s", len(text), url[:80])
                return text
    except Exception as e:
        logger.debug("Article fetch exception: %s", e)
    logger.warning("Failed to extract article text from %s", url[:80])
    return ""


def _parse_pub_date(s: str) -> datetime:
    """Parse RSS published date string, returning a timezone-aware datetime."""
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _fetch_feed(feed_cfg: dict, limit: int) -> list[dict]:
    """Fetch stories from a single RSS feed."""
    url = feed_cfg["url"]
    name = feed_cfg["name"]
    is_google = feed_cfg.get("is_google", False)
    logger.info("Fetching news from %s", name)
    try:
        feed = feedparser.parse(url)
        stories = []
        for entry in feed.entries[:limit]:
            title = entry.get("title", "")
            source = name
            # Google News appends source after " - "
            if is_google and " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0], parts[1]
            stories.append({
                "title": title,
                "source": source,
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "raw_text": "",
            })
        logger.info("Got %d entries from %s", len(stories), name)
        return stories
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", name, e)
        return []


def _deduplicate(stories: list[dict]) -> list[dict]:
    """Remove near-duplicate stories by checking title overlap."""
    seen_titles: list[str] = []
    unique = []
    for s in stories:
        title_lower = s["title"].lower()
        # Skip if >60% word overlap with any already-seen title
        title_words = set(title_lower.split())
        is_dup = False
        for seen in seen_titles:
            seen_words = set(seen.split())
            if not title_words or not seen_words:
                continue
            overlap = len(title_words & seen_words) / min(len(title_words), len(seen_words))
            if overlap > DEDUP_OVERLAP_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            unique.append(s)
            seen_titles.append(title_lower)
    return unique


def get_top_news(count: int = 5) -> list[dict]:
    """Return the top N most important, diverse stories of the day.

    Mimics CNN's '5 things to know' format: each story covers a different
    topic (war, economy, science, politics, etc.) so the reader gets a
    broad picture of what's happening in the world.
    """
    feed_names = ", ".join(f["name"] for f in NEWS_FEEDS)
    logger.info("Fetching top %d news from %s", count, feed_names)
    # Fetch all RSS feeds in parallel
    with ThreadPoolExecutor(max_workers=len(NEWS_FEEDS)) as executor:
        feed_results = list(executor.map(
            lambda cfg: _fetch_feed(cfg, limit=count * NEWS_FEED_LIMIT_MULTIPLIER),
            NEWS_FEEDS,
        ))
    all_stories = []
    for stories in feed_results:
        all_stories.extend(stories)

    # Sort by recency, deduplicate
    all_stories.sort(key=lambda s: _parse_pub_date(s.get("published", "")), reverse=True)
    unique = _deduplicate(all_stories)

    # Filter to today-only stories (keep unparseable dates as fallback)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_stories = [s for s in unique if _parse_pub_date(s.get("published", "")).strftime("%Y-%m-%d") == today_str or _parse_pub_date(s.get("published", "")) == datetime.min.replace(tzinfo=timezone.utc)]

    # Fall back to all stories if nothing matched today
    if len(today_stories) < count:
        today_stories = unique

    # Remove blocked sources and demoted stories
    candidates = [s for s in today_stories if not _is_blocked_source(s) and not _is_demoted(s)]
    if len(candidates) < count:
        candidates = [s for s in today_stories if not _is_blocked_source(s)]
    if len(candidates) < count:
        candidates = today_stories  # don't filter if too few remain

    # Score each story for global importance
    for s in candidates:
        s["_category"] = _categorize(s)
        s["_importance"] = _importance_score(s)

    # Sort by importance (highest first), then recency as tiebreaker
    candidates.sort(key=lambda s: (s["_importance"], _parse_pub_date(s.get("published", ""))), reverse=True)

    # Select stories with topic diversity: pick the highest-importance story
    # from each category first, then fill remaining slots
    selected = []
    selected_titles = set()
    used_categories = set()

    # First pass: one story per category (most important first)
    for s in candidates:
        if len(selected) >= count:
            break
        cat = s["_category"]
        if cat not in used_categories:
            selected.append(s)
            selected_titles.add(s["title"])
            used_categories.add(cat)

    # Second pass: fill remaining slots with highest-importance remaining
    for s in candidates:
        if len(selected) >= count:
            break
        if s["title"] not in selected_titles:
            selected.append(s)
            selected_titles.add(s["title"])

    # Fetch article text for the selected stories in parallel
    if not selected:
        return [{"title": "No news available", "source": "", "link": "", "published": "", "summary": "", "raw_text": ""}]

    def _fetch_for_story(story):
        return _fetch_article_text(story["link"])

    with ThreadPoolExecutor(max_workers=min(6, len(selected))) as executor:
        texts = list(executor.map(_fetch_for_story, selected))

    for i, story in enumerate(selected):
        logger.debug("News #%d [%s] (score=%.1f): '%s' (%s)", i + 1, story["_category"], story.get("_importance", 0), story["title"], story["source"])
        story["raw_text"] = texts[i]
        story["summary"] = ""
        if story["raw_text"]:
            try:
                result = extractive_summarize(story["raw_text"], num_sentences=2, title=story.get("title", ""))
                if result:
                    story["summary"] = result
            except Exception as e:
                logger.warning("Summarize failed for '%s': %s", story["title"][:60], e)
        story.pop("_category", None)
        story.pop("_importance", None)

    with_text = sum(1 for s in selected if s["raw_text"])
    logger.info("News fetch complete: %d diverse stories, %d with article text",
                len(selected), with_text)
    return selected if selected else [{"title": "No news available", "source": "", "link": "", "published": "", "summary": "", "raw_text": ""}]

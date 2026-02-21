"""Fetch top news headlines from Google News, CNN, BBC News, and NPR RSS feeds."""

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import trafilatura
from googlenewsdecoder import new_decoderv1

logger = logging.getLogger(__name__)

# RSS sources — order matters for priority when deduplicating
NEWS_FEEDS = [
    {
        "url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "name": "Google News",
        "is_google": True,
    },
    {
        "url": "http://rss.cnn.com/rss/cnn_topstories.rss",
        "name": "CNN",
        "is_google": False,
    },
    {
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
        "name": "BBC News",
        "is_google": False,
    },
    {
        "url": "https://feeds.npr.org/1001/rss.xml",
        "name": "NPR",
        "is_google": False,
    },
]


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
            if text and len(text) > 100:
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
            if overlap > 0.6:
                is_dup = True
                break
        if not is_dup:
            unique.append(s)
            seen_titles.append(title_lower)
    return unique


def get_top_news(count: int = 5) -> list[dict]:
    """Return top news stories from multiple RSS sources with raw article text."""
    logger.info("Fetching top %d news from Google News, CNN, BBC News, NPR", count)
    all_stories = []
    for feed_cfg in NEWS_FEEDS:
        all_stories.extend(_fetch_feed(feed_cfg, limit=count * 2))

    # Sort by recency, deduplicate, take top N
    all_stories.sort(key=lambda s: _parse_pub_date(s.get("published", "")), reverse=True)
    unique = _deduplicate(all_stories)[:count]

    # Fetch article text for the selected stories
    for i, story in enumerate(unique, 1):
        logger.debug("News #%d: '%s' (%s)", i, story["title"], story["source"])
        story["raw_text"] = _fetch_article_text(story["link"])
        story["summary"] = ""

    with_text = sum(1 for s in unique if s["raw_text"])
    logger.info("News fetch complete: %d stories, %d with article text", len(unique), with_text)
    return unique if unique else [{"title": "No news available", "source": "", "link": "", "published": "", "summary": "", "raw_text": ""}]

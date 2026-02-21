"""Fetch AI security news headlines from Google News RSS search."""

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import trafilatura
from googlenewsdecoder import new_decoderv1

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "AI+security+LLM+vulnerability",
    "AI+agent+security+autonomous",
    "prompt+injection+jailbreak+AI",
    "AI+cybersecurity+startup+acquisition",
]

RELEVANCE_KEYWORDS = [
    "ai security", "llm", "ai agent", "prompt injection", "jailbreak",
    "autonomous agent", "agentic", "language model", "ai vulnerability",
    "ai threat", "generative ai", "foundation model", "ai safety",
    "large language model",
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


def _relevance_score(title: str, text: str) -> int:
    """Count AI-specific keyword matches in title + text."""
    combined = (title + " " + text).lower()
    return sum(1 for kw in RELEVANCE_KEYWORDS if kw in combined)


def get_ai_security_news(count: int = 4) -> list[dict]:
    """Return top AI security news stories from Google News RSS search."""
    logger.info("Fetching AI security news from %d search queries", len(SEARCH_QUERIES))
    try:
        seen = set()
        all_entries = []

        for query in SEARCH_QUERIES:
            try:
                url = f"https://news.google.com/rss/search?q={query}+when:7d&hl=en-US&gl=US&ceid=US:en"
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    dedup_key = entry.title.lower()[:60]
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        all_entries.append(entry)
                logger.debug("Query '%s': %d entries", query, len(feed.entries))
            except Exception as e:
                logger.warning("Failed query '%s': %s", query, e)
                continue

        logger.info("Total unique entries from all queries: %d", len(all_entries))

        # Pre-filter by title relevance before expensive article fetching
        candidates = []
        for entry in all_entries:
            title = entry.title
            if _relevance_score(title, "") >= 1:
                candidates.append(entry)
        # Limit to 3x count to avoid excessive fetching
        candidates = candidates[:count * 3]
        logger.info("Pre-filtered to %d candidates by title relevance", len(candidates))

        # Process candidates: extract text and score relevance
        scored = []
        for entry in candidates:
            title = entry.title
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0], parts[1]

            raw_text = _fetch_article_text(entry.link)
            score = _relevance_score(title, raw_text)

            if score < 1:
                logger.debug("Filtered out (score %d): %s", score, title[:60])
                continue

            scored.append({
                "title": title,
                "source": source,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": "",
                "raw_text": raw_text,
                "_score": score,
            })

        # Filter out articles older than 7 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        scored = [s for s in scored if _parse_pub_date(s.get("published", "")) >= cutoff]

        # Sort by relevance score desc, then by date desc
        scored.sort(key=lambda s: (s["_score"], _parse_pub_date(s.get("published", ""))), reverse=True)

        # Take top N and sort final results by date
        top = scored[:count]
        top.sort(key=lambda s: _parse_pub_date(s.get("published", "")), reverse=True)

        # Remove internal score field
        for item in top:
            del item["_score"]

        with_text = sum(1 for s in top if s["raw_text"])
        logger.info("AI security news complete: %d stories, %d with article text", len(top), with_text)
        return top

    except Exception as e:
        logger.error("AI security news fetch failed: %s", e)
        return [{"title": f"Error fetching AI security news: {e}", "source": "", "link": "", "published": "", "summary": "", "raw_text": ""}]

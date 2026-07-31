"""Fetch AI security news headlines from Google News RSS search and curated feeds."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import trafilatura
from googlenewsdecoder import new_decoderv1

from src.constants import (
    AI_NEWS_CANDIDATE_MULTIPLIER,
    AI_NEWS_DAYS_CUTOFF,
    GOOGLE_NEWS_SEARCH_URL,
    MIN_TEXT_LENGTH_SHORT,
)
from src.summarizer import summarize as extractive_summarize

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "AI+security+LLM+vulnerability",
    "AI+agent+security+autonomous",
    "prompt+injection+jailbreak+AI",
    "AI+cybersecurity+startup+acquisition",
]

DIRECT_AI_NEWS_FEEDS = [
    {
        "url": "https://dreyx.com/rss",
        "name": "DreyX AI News",
        "prefer_summary_text": True,
    },
]

DIRECT_FEED_ENTRY_LIMIT = 20

RELEVANCE_KEYWORDS = [
    "ai security", "llm", "ai agent", "prompt injection", "jailbreak",
    "autonomous agent", "agentic", "language model", "ai vulnerability",
    "ai threat", "generative ai", "foundation model", "ai safety",
    "large language model", "security", "vulnerability", "malware",
    "credential", "secret", "claude code", "cursor", "codex", "copilot",
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
            if text and len(text) > MIN_TEXT_LENGTH_SHORT:
                logger.info("Article text extracted: %d chars from %s", len(text), url[:80])
                return text
    except Exception as e:
        logger.debug("Article fetch exception: %s", e)
    logger.warning("Failed to extract article text from %s", url[:80])
    return ""


def _clean_rss_text(text: str) -> str:
    """Return plain text from an RSS summary or description.

    Args:
        text: Raw RSS summary text, possibly containing HTML.

    Returns:
        Whitespace-normalized plain text.
    """
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _source_from_entry(entry: dict, fallback_source: str = "") -> str:
    """Read the best source label from an RSS entry.

    Args:
        entry: A feedparser entry.
        fallback_source: Feed-level source label.

    Returns:
        A display source label.
    """
    source_detail = entry.get("source") or {}
    source_title = source_detail.get("title", "") if isinstance(source_detail, dict) else ""
    if source_title and fallback_source and source_title != fallback_source:
        return f"{fallback_source} / {source_title}"
    return source_title or fallback_source


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


def _candidate_prefilter_score(entry: dict) -> int:
    """Score an entry cheaply before fetching full article text.

    Args:
        entry: A feedparser entry.

    Returns:
        Title relevance score, with a small boost for curated direct feeds.
    """
    score = _relevance_score(entry.title, "")
    if score and entry.get("_source_name"):
        score += 1
    return score


def _fetch_direct_feed_entries(seen: set[str]) -> list[dict]:
    """Fetch entries from curated AI news RSS feeds.

    Args:
        seen: Mutable set of title dedupe keys already collected.

    Returns:
        Feed entries annotated with feed metadata.
    """
    entries = []
    for feed_cfg in DIRECT_AI_NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            feed_entries = feed.entries[:DIRECT_FEED_ENTRY_LIMIT]
            for entry in feed_entries:
                dedup_key = entry.title.lower()[:60]
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                entry["_source_name"] = feed_cfg["name"]
                entry["_prefer_summary_text"] = feed_cfg.get("prefer_summary_text", False)
                entries.append(entry)
            logger.debug("Direct feed '%s': %d entries", feed_cfg["name"], len(feed_entries))
        except Exception as e:
            logger.warning("Failed direct feed '%s': %s", feed_cfg["name"], e)
    return entries


def get_ai_security_news(count: int = 4) -> list[dict]:
    """Return top AI security news stories from search and curated RSS feeds."""
    logger.info(
        "Fetching AI security news from %d search queries and %d direct feeds",
        len(SEARCH_QUERIES),
        len(DIRECT_AI_NEWS_FEEDS),
    )
    try:
        seen = set()
        all_entries = []

        for query in SEARCH_QUERIES:
            try:
                url = f"{GOOGLE_NEWS_SEARCH_URL}?q={query}+when:{AI_NEWS_DAYS_CUTOFF}d&hl=en-US&gl=US&ceid=US:en"
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

        all_entries.extend(_fetch_direct_feed_entries(seen))
        logger.info("Total unique entries from all queries: %d", len(all_entries))

        # Pre-filter by title relevance before expensive article fetching
        candidates = []
        for entry in all_entries:
            if _candidate_prefilter_score(entry) >= 1 or entry.get("_source_name"):
                candidates.append(entry)
        candidates.sort(
            key=lambda entry: (
                _candidate_prefilter_score(entry),
                _parse_pub_date(entry.get("published", "")),
            ),
            reverse=True,
        )
        # Limit to 3x count to avoid excessive fetching
        candidates = candidates[:count * AI_NEWS_CANDIDATE_MULTIPLIER]
        logger.info("Pre-filtered to %d candidates by title relevance", len(candidates))

        # Process candidates: extract text in parallel and score relevance
        def _process_entry(entry):
            title = entry.title
            source = entry.get("_source_name", "")
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0], parts[1]
            source = _source_from_entry(entry, source)
            raw_text = ""
            if entry.get("_prefer_summary_text"):
                raw_text = _clean_rss_text(entry.get("summary", "") or entry.get("description", ""))
            if not raw_text:
                raw_text = _fetch_article_text(entry.link)
            score = _relevance_score(title, raw_text)
            return title, source, entry, raw_text, score

        with ThreadPoolExecutor(max_workers=max(1, min(6, len(candidates)))) as executor:
            processed = list(executor.map(_process_entry, candidates))

        scored = []
        for title, source, entry, raw_text, score in processed:
            if score < 1:
                logger.debug("Filtered out (score %d): %s", score, title[:60])
                continue

            summary = ""
            if raw_text:
                try:
                    summary = extractive_summarize(raw_text, num_sentences=2, title=title) or ""
                except Exception as e:
                    logger.warning("Summarize failed for '%s': %s", title[:60], e)

            scored.append({
                "title": title,
                "source": source,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": summary,
                "raw_text": raw_text,
                "_score": score,
            })

        # Filter out articles older than 7 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=AI_NEWS_DAYS_CUTOFF)
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

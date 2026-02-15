"""Fetch top news headlines from Google News RSS (no API key needed)."""

import logging
import feedparser
import trafilatura
from googlenewsdecoder import new_decoderv1

logger = logging.getLogger(__name__)


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


def get_top_news(count: int = 3) -> list[dict]:
    """Return top news stories from Google News RSS with raw article text."""
    logger.info("Fetching top %d news from Google News RSS", count)
    try:
        feed = feedparser.parse("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
        stories = []
        for i, entry in enumerate(feed.entries[:count], 1):
            title = entry.title
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0], parts[1]
            logger.debug("News #%d: '%s' (%s)", i, title, source)
            raw_text = _fetch_article_text(entry.link)
            stories.append({
                "title": title,
                "source": source,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": "",
                "raw_text": raw_text,
            })
        with_text = sum(1 for s in stories if s["raw_text"])
        logger.info("News fetch complete: %d stories, %d with article text", len(stories), with_text)
        return stories
    except Exception as e:
        return [{"title": f"Error fetching news: {e}", "source": "", "link": "", "published": "", "summary": "", "raw_text": ""}]

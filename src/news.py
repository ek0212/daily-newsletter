"""Fetch top news headlines from Google News RSS (no API key needed)."""

import feedparser
import requests
import trafilatura
from src.summarizer import summarize


def _fetch_article_summary(url: str) -> str:
    """Fetch article page and return an extractive summary."""
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = trafilatura.extract(resp.text)
        if text and len(text) > 100:
            return summarize(text, num_sentences=3)
    except Exception:
        pass
    return ""


def get_top_news(count: int = 3) -> list[dict]:
    """Return top news stories from Google News RSS."""
    try:
        feed = feedparser.parse("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
        stories = []
        for entry in feed.entries[:count]:
            title = entry.title
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0], parts[1]
            summary = _fetch_article_summary(entry.link)
            if not summary:
                summary = f"Read more at {source}" if source else ""
            stories.append({
                "title": title,
                "source": source,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": summary,
            })
        return stories
    except Exception as e:
        return [{"title": f"Error fetching news: {e}", "source": "", "link": "", "published": "", "summary": ""}]

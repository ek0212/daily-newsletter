"""Fetch top news headlines from Google News RSS (no API key needed)."""

import feedparser
import requests
import trafilatura


def _fetch_article_text(url: str) -> str:
    """Fetch article page and return extracted full text."""
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = trafilatura.extract(resp.text)
        if text and len(text) > 100:
            return text
    except Exception:
        pass
    return ""


def get_top_news(count: int = 3) -> list[dict]:
    """Return top news stories from Google News RSS with raw article text."""
    try:
        feed = feedparser.parse("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
        stories = []
        for entry in feed.entries[:count]:
            title = entry.title
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, source = parts[0], parts[1]
            raw_text = _fetch_article_text(entry.link)
            stories.append({
                "title": title,
                "source": source,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": "",
                "raw_text": raw_text,
            })
        return stories
    except Exception as e:
        return [{"title": f"Error fetching news: {e}", "source": "", "link": "", "published": "", "summary": "", "raw_text": ""}]

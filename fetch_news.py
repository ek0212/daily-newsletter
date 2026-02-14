"""
Fetch top news headlines using Google News RSS feed.
No API key required. Free and unlimited.
"""

import feedparser
from dataclasses import dataclass


@dataclass
class NewsStory:
    title: str
    description: str
    link: str
    source: str
    published: str


def fetch_top_news(count: int = 3) -> list[NewsStory]:
    """Fetch top news headlines from Google News RSS feed."""
    url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)

    stories = []
    for entry in feed.entries[:count]:
        # Google News RSS includes source in title as "Title - Source"
        title = entry.title
        source = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            title = parts[0]
            source = parts[1]

        stories.append(NewsStory(
            title=title,
            description=entry.get("summary", ""),
            link=entry.link,
            source=source,
            published=entry.get("published", ""),
        ))

    return stories


if __name__ == "__main__":
    stories = fetch_top_news(3)
    for i, story in enumerate(stories, 1):
        print(f"\n{'='*60}")
        print(f"Story #{i}: {story.title}")
        print(f"Source: {story.source}")
        print(f"Published: {story.published}")
        print(f"Link: {story.link}")

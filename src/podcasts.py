"""Fetch recent podcast episodes from RSS feeds with YouTube transcript summaries."""

import re
import feedparser
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from youtube_transcript_api import YouTubeTranscriptApi

PODCAST_FEEDS = {
    "This Week in Startups": "https://anchor.fm/s/7c624c84/podcast/rss",
    "Dwarkesh Podcast": "https://api.substack.com/feed/podcast/69345.rss",
    "Lex Fridman Podcast": "https://lexfridman.com/feed/podcast/",
}

YOUTUBE_CHANNELS = {
    "This Week in Startups": "https://www.youtube.com/feeds/videos.xml?channel_id=UCCjyq_K1Xwfg8Lndy7lKMpA",
    "Dwarkesh Podcast": "https://www.youtube.com/feeds/videos.xml?channel_id=UC1SfmNb5y0eT4hEZyNh7OHg",
    "Lex Fridman Podcast": "https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA",
}


def _fetch_youtube_videos(channel_feed_url: str) -> list[dict]:
    """Fetch recent videos from a YouTube channel RSS feed."""
    try:
        feed = feedparser.parse(channel_feed_url)
        videos = []
        for entry in feed.entries:
            video_id = entry.get("yt_videoid", "")
            if not video_id and "watch?v=" in entry.get("link", ""):
                video_id = entry["link"].split("watch?v=")[-1].split("&")[0]
            if video_id:
                videos.append({
                    "title": entry.get("title", ""),
                    "video_id": video_id,
                })
        return videos
    except Exception:
        return []


def _find_matching_video(episode_title: str, videos: list[dict], threshold: float = 0.4) -> str | None:
    """Find the best matching YouTube video for an episode title. Returns video_id or None."""
    episode_clean = re.sub(r"[^\w\s]", "", episode_title.lower())
    best_ratio = 0.0
    best_id = None

    for video in videos:
        video_clean = re.sub(r"[^\w\s]", "", video["title"].lower())
        ratio = SequenceMatcher(None, episode_clean, video_clean).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = video["video_id"]

    return best_id if best_ratio >= threshold else None


def _get_transcript_text(video_id: str) -> str | None:
    """Fetch YouTube transcript and return full text."""
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=["en"])
        full_text = " ".join(snippet.text for snippet in transcript)
        if len(full_text) < 100:
            return None
        return full_text
    except Exception:
        return None


def get_recent_episodes(days: int = 7) -> list[dict]:
    """Fetch podcast episodes from the last N days with YouTube transcript summaries."""
    cutoff = datetime.now() - timedelta(days=days)
    all_episodes = []

    # Pre-fetch YouTube video lists for all channels
    yt_videos_cache = {}
    for name, yt_url in YOUTUBE_CHANNELS.items():
        yt_videos_cache[name] = _fetch_youtube_videos(yt_url)

    for name, url in PODCAST_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])

                if published and published >= cutoff:
                    title = entry.get("title", "Untitled")

                    # Try to get YouTube transcript text
                    raw_text = ""
                    videos = yt_videos_cache.get(name, [])
                    if videos:
                        video_id = _find_matching_video(title, videos)
                        if video_id:
                            raw_text = _get_transcript_text(video_id) or ""

                    # Fall back to RSS description as raw text
                    if not raw_text:
                        raw_text = entry.get("summary", entry.get("description", ""))
                        raw_text = re.sub(r"<[^>]+>", "", raw_text)

                    all_episodes.append({
                        "podcast": name,
                        "title": title,
                        "published": published.strftime("%Y-%m-%d"),
                        "summary": "",
                        "raw_text": raw_text,
                        "link": entry.get("link", ""),
                    })
        except Exception:
            continue

    all_episodes.sort(key=lambda x: x["published"], reverse=True)
    return all_episodes

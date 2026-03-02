"""Fetch recent YouTube videos from channel feeds with transcript extraction."""

import logging
from datetime import datetime, timedelta, timezone

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)

# YouTube channel RSS feeds
YOUTUBE_CHANNELS = {
    "This Week in Startups": "https://www.youtube.com/feeds/videos.xml?channel_id=UCkkhmBWfS7pILYIk0izkc3A",
    "Dwarkesh Podcast": "https://www.youtube.com/feeds/videos.xml?channel_id=UCXl4i9dYBrFOabk0xGmbkRA",
    "Lex Fridman Podcast": "https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA",
    "AI Daily Brief": "https://www.youtube.com/feeds/videos.xml?channel_id=UCKelCK4ZaO6HeEI1KQjqzWA",
    "Morning Brew Daily": "https://www.youtube.com/feeds/videos.xml?channel_id=UCJGeBpBh9_Q0B_EKPmj14Pg",
    "Dr. Izzy Sealey": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbOhZ3HUP0eqbQgGYSMHo1w",
    "Matt Wolfe": "https://www.youtube.com/feeds/videos.xml?channel_id=UChpleBmo18P08aKCIgti38g",
    "Theo - t3.gg": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbRP3c757lWg9M-U7TyEkXA",
    "Jeff Su": "https://www.youtube.com/feeds/videos.xml?channel_id=UCwAnu01qlnVg1Ai2AbtTMaA",
}

MAX_VIDEOS = 8


def _get_transcript_text(video_id: str) -> str:
    """Fetch YouTube transcript and return full text."""
    logger.debug("Fetching transcript for video %s...", video_id)
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=["en"])
        full_text = " ".join(snippet.text for snippet in transcript)
        if len(full_text) < 100:
            return ""
        logger.info("Transcript fetched: %d chars", len(full_text))
        return full_text
    except Exception as e:
        logger.debug("Transcript unavailable for %s: %s", video_id, e)
        return ""


def get_recent_videos(days: int = 3) -> list[dict]:
    """Fetch videos from the last N days across all YouTube channels."""
    logger.info("Fetching videos from %d YouTube channels (last %d days)", len(YOUTUBE_CHANNELS), days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_videos = []

    for name, feed_url in YOUTUBE_CHANNELS.items():
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                # YouTube RSS uses <published> in ISO format
                pub_str = entry.get("published", "")
                if not pub_str:
                    continue
                try:
                    published = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    continue

                if published < cutoff:
                    continue

                video_id = entry.get("yt_videoid", "")
                if not video_id:
                    link = entry.get("link", "")
                    if "watch?v=" in link:
                        video_id = link.split("watch?v=")[-1].split("&")[0]
                if not video_id:
                    continue

                all_videos.append({
                    "channel": name,
                    "title": entry.get("title", ""),
                    "video_id": video_id,
                    "published": published.strftime("%Y-%m-%d"),
                    "published_dt": published,
                    "link": f"https://youtube.com/watch?v={video_id}",
                    "summary": "",
                    "raw_text": "",
                })
            logger.debug("Channel %s: %d entries in feed", name, len(feed.entries))
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", name, e)
            continue

    # Sort by recency, take top MAX_VIDEOS
    all_videos.sort(key=lambda v: v["published_dt"], reverse=True)
    selected = all_videos[:MAX_VIDEOS]

    # Fetch transcripts
    for video in selected:
        video["raw_text"] = _get_transcript_text(video["video_id"])
        del video["published_dt"]  # Not needed in output

    with_transcripts = sum(1 for v in selected if len(v.get("raw_text", "")) > 500)
    logger.info("YouTube complete: %d videos, %d with transcripts", len(selected), with_transcripts)
    return selected

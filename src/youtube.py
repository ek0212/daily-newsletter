"""Fetch recent YouTube videos from channel feeds with transcript extraction."""

import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests as _requests

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
_TOR_MAX_RETRIES = 5


def _rotate_tor_circuit(control_port: int = 9051) -> bool:
    """Send NEWNYM signal to Tor to get a new exit node."""
    try:
        with socket.create_connection(("127.0.0.1", control_port), timeout=5) as s:
            s.sendall(b"AUTHENTICATE\r\n")
            s.recv(256)
            s.sendall(b"SIGNAL NEWNYM\r\n")
            resp = s.recv(256)
            return b"250" in resp
    except Exception:
        return False


def _tor_available() -> bool:
    """Check if Tor SOCKS proxy is running and reachable."""
    tor_port = int(os.getenv("TOR_SOCKS_PORT", "9050"))
    try:
        session = _requests.Session()
        session.proxies = {
            "http": f"socks5h://127.0.0.1:{tor_port}",
            "https": f"socks5h://127.0.0.1:{tor_port}",
        }
        r = session.get("https://check.torproject.org/api/ip", timeout=10)
        if r.status_code == 200 and r.json().get("IsTor"):
            logger.info("Tor proxy active (IP: %s)", r.json().get("IP"))
            return True
    except Exception as e:
        logger.debug("Tor not available: %s", e)
    return False


def _make_tor_session() -> _requests.Session:
    """Create a fresh requests session routed through Tor."""
    tor_port = int(os.getenv("TOR_SOCKS_PORT", "9050"))
    session = _requests.Session()
    session.proxies = {
        "http": f"socks5h://127.0.0.1:{tor_port}",
        "https": f"socks5h://127.0.0.1:{tor_port}",
    }
    return session


def _get_transcript_text(video_id: str, use_tor: bool = False) -> str:
    """Fetch YouTube transcript. With Tor, retries with circuit rotation on failure."""
    from youtube_transcript_api import YouTubeTranscriptApi

    if use_tor:
        control_port = int(os.getenv("TOR_CONTROL_PORT", "9051"))
        for attempt in range(_TOR_MAX_RETRIES):
            session = _make_tor_session()
            try:
                ytt = YouTubeTranscriptApi(http_client=session)
                transcript = ytt.fetch(video_id, languages=["en"])
                full_text = " ".join(snippet.text for snippet in transcript)
                if len(full_text) >= 100:
                    logger.info("Transcript via Tor (attempt %d): %d chars for %s",
                                attempt + 1, len(full_text), video_id)
                    return full_text
            except Exception as e:
                logger.debug("Tor attempt %d failed for %s: %s", attempt + 1, video_id,
                             type(e).__name__)
            # Rotate to a new exit node and wait for new circuit
            _rotate_tor_circuit(control_port)
            time.sleep(3)

    # Direct fallback (works locally, may fail in CI)
    try:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id, languages=["en"])
        full_text = " ".join(snippet.text for snippet in transcript)
        if len(full_text) >= 100:
            logger.info("Transcript via direct: %d chars for %s", len(full_text), video_id)
            return full_text
    except Exception as e:
        logger.debug("Direct transcript failed for %s: %s", video_id, type(e).__name__)

    logger.warning("All transcript methods failed for %s", video_id)
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

    # Check if Tor is available (once, not per-video)
    use_tor = _tor_available()

    # Fetch transcripts
    for video in selected:
        video["raw_text"] = _get_transcript_text(video["video_id"], use_tor=use_tor)
        del video["published_dt"]

    with_transcripts = sum(1 for v in selected if len(v.get("raw_text", "")) > 500)
    logger.info("YouTube complete: %d videos, %d with transcripts", len(selected), with_transcripts)
    return selected

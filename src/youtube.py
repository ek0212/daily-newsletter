"""Fetch recent YouTube videos from channel feeds with transcript extraction.

Uses a tiered approach for getting episode text:
1. Podcast RSS descriptions / website transcripts (free, works everywhere)
2. YouTube transcript API direct (works locally, may be blocked in CI)
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests as _requests
import trafilatura

from src.constants import (
    HTTP_TIMEOUT_SHORT,
    MAX_PODCAST_ENTRIES,
    MAX_VIDEOS,
    MIN_TEXT_LENGTH_LONG,
    MIN_TEXT_LENGTH_MEDIUM,
    MIN_TEXT_LENGTH_SHORT,
    PODCAST_MATCH_THRESHOLD,
    PODCAST_MIN_DESC_CHARS,
)
from src.summarizer import summarize as extractive_summarize

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

# Podcast RSS feeds with substantial episode descriptions or transcripts.
# These are tried BEFORE YouTube transcripts — they work from any IP.
PODCAST_RSS_FEEDS = {
    "This Week in Startups": "https://anchor.fm/s/7c624c84/podcast/rss",
    "Dwarkesh Podcast": "https://api.substack.com/feed/podcast/69345.rss",
    "Lex Fridman Podcast": "https://lexfridman.com/feed/podcast/",
    "AI Daily Brief": "https://anchor.fm/s/f7cac464/podcast/rss",
    "Morning Brew Daily": "https://feeds.megaphone.fm/MOBI8777994188",
    "Matt Wolfe": "https://feeds.megaphone.fm/thenextwave",
}

# Channels where full transcripts are published on their website.
# Map: channel name -> URL pattern (use {slug} for episode slug).
TRANSCRIPT_WEBSITES = {
    "Dwarkesh Podcast": "https://dwarkesh.com",
    "Lex Fridman Podcast": "https://lexfridman.com",
}

def _is_short(video_id: str) -> bool:
    """Check if a YouTube video is a Short by probing the /shorts/ URL.

    YouTube returns 200 for actual Shorts and redirects to /watch?v= for regular videos.
    """
    try:
        r = _requests.head(
            f"https://www.youtube.com/shorts/{video_id}",
            allow_redirects=False, timeout=HTTP_TIMEOUT_SHORT,
        )
        return r.status_code == 200
    except Exception:
        return False



def _title_similarity(a: str, b: str) -> float:
    """Fuzzy title match using keyword overlap, tuned for YT vs podcast titles.

    YouTube title: "The AI Industry Will Hit Trillions by 2030 - Dario Amodei"
    Podcast title: 'Dario Amodei — "We are near the end of the exponential"'
    These share "Dario Amodei" which is the key match signal.
    """
    def _keywords(s: str) -> set[str]:
        s = s.lower()
        # Remove episode markers, podcast names, punctuation
        s = re.sub(r'[|\-–—].*(?:podcast|lex fridman|dwarkesh|morning brew).*$', '', s, flags=re.IGNORECASE)
        s = re.sub(r'[#|"\'\-–—:,.()\[\]]', ' ', s)
        s = re.sub(r'\b(the|a|an|in|of|and|or|is|to|for|with|on|at|by|from|that|this|it)\b', '', s)
        words = {w for w in s.split() if len(w) >= 3}
        return words

    kw_a = _keywords(a)
    kw_b = _keywords(b)
    if not kw_a or not kw_b:
        return 0.0
    overlap = kw_a & kw_b
    # Jaccard-ish but weighted toward shorter set (the query title)
    smaller = min(len(kw_a), len(kw_b))
    return len(overlap) / smaller if smaller else 0.0


def _get_podcast_text(channel: str, video_title: str) -> tuple[str, str]:
    """Try to get episode text from podcast RSS feed for a given channel/title.

    Returns (episode_text, episode_url) tuple.
    """
    feed_url = PODCAST_RSS_FEEDS.get(channel)
    if not feed_url:
        return "", ""

    try:
        feed = feedparser.parse(feed_url)
        best_match = ""
        best_score = 0.0
        best_url = ""

        for entry in feed.entries[:MAX_PODCAST_ENTRIES]:
            ep_title = entry.get("title", "")
            score = _title_similarity(video_title, ep_title)
            if score > best_score:
                best_score = score
                # Prefer content:encoded > description > summary
                text = ""
                if hasattr(entry, "content") and entry.content:
                    text = entry.content[0].get("value", "")
                if not text or len(text) < MIN_TEXT_LENGTH_MEDIUM:
                    text = entry.get("description", "") or entry.get("summary", "")
                # Strip HTML tags
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                best_match = text
                best_url = entry.get("link", "")

        if best_score >= PODCAST_MATCH_THRESHOLD and len(best_match) >= MIN_TEXT_LENGTH_MEDIUM:
            logger.info("Podcast RSS match for '%s' (score=%.2f): %d chars from %s",
                        video_title[:50], best_score, len(best_match), channel)
            return best_match, best_url

        logger.debug("No good podcast RSS match for '%s' in %s (best=%.2f)",
                     video_title[:50], channel, best_score)
    except Exception as e:
        logger.debug("Podcast RSS fetch failed for %s: %s", channel, e)

    return "", ""


def _get_website_transcript(channel: str, video_title: str) -> tuple[str, str]:
    """Try to fetch a full transcript from the channel's website.

    Works for Dwarkesh (Substack) and Lex Fridman (lexfridman.com).
    Returns (text, source_url) tuple.
    """
    base_url = TRANSCRIPT_WEBSITES.get(channel)
    if not base_url:
        return "", ""

    try:
        if channel == "Lex Fridman Podcast":
            # Lex publishes transcripts at lexfridman.com/GUEST-NAME-transcript
            # Try to find the transcript link from the podcast RSS entry
            feed = feedparser.parse(PODCAST_RSS_FEEDS[channel])
            for entry in feed.entries[:10]:
                score = _title_similarity(video_title, entry.get("title", ""))
                if score >= PODCAST_MATCH_THRESHOLD:
                    # Look for transcript URL in description
                    desc = entry.get("description", "") + entry.get("summary", "")
                    match = re.search(r'(https://lexfridman\.com/[a-z0-9-]+-transcript)', desc, re.IGNORECASE)
                    if match:
                        url = match.group(1)
                        downloaded = trafilatura.fetch_url(url)
                        if downloaded:
                            text = trafilatura.extract(downloaded)
                            if text and len(text) > MIN_TEXT_LENGTH_LONG:
                                logger.info("Lex transcript fetched: %d chars from %s", len(text), url)
                                # Link to the episode page (without -transcript suffix)
                                episode_url = url.replace("-transcript", "")
                                return text, episode_url
                    break

        elif channel == "Dwarkesh Podcast":
            # Dwarkesh publishes on Substack — full transcripts in post body
            feed = feedparser.parse(PODCAST_RSS_FEEDS[channel])
            for entry in feed.entries[:10]:
                score = _title_similarity(video_title, entry.get("title", ""))
                if score >= PODCAST_MATCH_THRESHOLD:
                    link = entry.get("link", "")
                    if link:
                        downloaded = trafilatura.fetch_url(link)
                        if downloaded:
                            text = trafilatura.extract(downloaded)
                            if text and len(text) > MIN_TEXT_LENGTH_LONG:
                                logger.info("Dwarkesh transcript fetched: %d chars from %s", len(text), link)
                                return text, link
                    break

    except Exception as e:
        logger.debug("Website transcript fetch failed for %s: %s", channel, e)

    return "", ""


def _get_morning_brew_text(video_title: str) -> tuple[str, str]:
    """Fetch today's Morning Brew stories from their RSS feed and archive.

    Returns (concatenated_text, issue_url) tuple.
    """
    try:
        today_prefix = datetime.now(timezone.utc).strftime("%a, %d %b %Y")
        feed = feedparser.parse("https://www.morningbrew.com/feed")
        stories = []
        for entry in feed.entries:
            pub = entry.get("published", "")
            if not pub.startswith(today_prefix):
                continue
            url = entry.get("link", "")
            title = entry.get("title", "")
            if not url:
                continue
            try:
                resp = _requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                    timeout=15,
                )
                text = trafilatura.extract(resp.text)
                if text:
                    stories.append(f"{title}\n\n{text}")
            except Exception as e:
                logger.debug("Morning Brew story fetch failed for %s: %s", url, e)

        # Try to find today's issue URL from the archive page
        issue_url = ""
        try:
            resp = _requests.get(
                "https://www.morningbrew.com/archive",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                timeout=15,
            )
            match = re.search(r'href="(/issues/[^"]+)"', resp.text)
            if match:
                issue_url = f"https://www.morningbrew.com{match.group(1)}"
        except Exception as e:
            logger.debug("Morning Brew archive fetch failed: %s", e)

        if stories:
            combined = "\n\n---\n\n".join(stories)
            logger.info("Morning Brew website: %d stories, %d chars", len(stories), len(combined))
            return combined, issue_url

    except Exception as e:
        logger.debug("Morning Brew text fetch failed: %s", e)

    return "", ""


def _get_jeffsu_text(video_title: str) -> tuple[str, str]:
    """Fetch matching blog post text from Jeff Su's RSS feed.

    Returns (text, blog_url) tuple.
    """
    try:
        feed = feedparser.parse("https://www.jeffsu.org/rss/")
        best_score = 0.0
        best_url = ""
        best_title = ""

        for entry in feed.entries[:MAX_PODCAST_ENTRIES]:
            ep_title = entry.get("title", "")
            score = _title_similarity(video_title, ep_title)
            if score > best_score:
                best_score = score
                best_url = entry.get("link", "")
                best_title = ep_title

        if best_score >= PODCAST_MATCH_THRESHOLD and best_url:
            resp = _requests.get(
                best_url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                timeout=15,
            )
            text = trafilatura.extract(resp.text)
            if text and len(text) >= MIN_TEXT_LENGTH_MEDIUM:
                logger.info("Jeff Su blog match for '%s' (score=%.2f): %d chars from %s",
                            video_title[:50], best_score, len(text), best_url)
                return text, best_url

        logger.debug("No Jeff Su blog match for '%s' (best=%.2f)", video_title[:50], best_score)
    except Exception as e:
        logger.debug("Jeff Su blog fetch failed: %s", e)

    return "", ""


def _get_izzy_text() -> tuple[str, str]:
    """Fetch the latest blog post from Dr. Izzy Sealey's Substack.

    Uses the most recent post regardless of title match, since her Substack
    covers personal development topics that complement her YouTube content.
    Returns (text, post_url) tuple.
    """
    try:
        feed = feedparser.parse("https://letters.izzysealey.com/feed")
        if not feed.entries:
            return "", ""

        entry = feed.entries[0]
        url = entry.get("link", "")
        if not url:
            return "", ""

        # Prefer content:encoded > description > summary
        text = ""
        if hasattr(entry, "content") and entry.content:
            text = entry.content[0].get("value", "")
        if not text or len(text) < MIN_TEXT_LENGTH_MEDIUM:
            text = entry.get("description", "") or entry.get("summary", "")

        # Strip HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if text and len(text) >= MIN_TEXT_LENGTH_MEDIUM:
            logger.info("Dr. Izzy Substack: %d chars from %s", len(text), url)
            return text, url

    except Exception as e:
        logger.debug("Dr. Izzy Substack fetch failed: %s", e)

    return "", ""


def _get_transcript_text(video_id: str) -> str:
    """Fetch YouTube transcript via the YouTube Transcript API (works locally, may fail in CI)."""
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id, languages=["en"])
        full_text = " ".join(snippet.text for snippet in transcript)
        if len(full_text) >= MIN_TEXT_LENGTH_SHORT:
            logger.info("Transcript fetched: %d chars for %s", len(full_text), video_id)
            return full_text
    except Exception as e:
        logger.debug("Transcript fetch failed for %s: %s", video_id, type(e).__name__)

    logger.warning("Transcript fetch failed for %s", video_id)
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

    # Sort by recency
    all_videos.sort(key=lambda v: v["published_dt"], reverse=True)

    # Filter out YouTube Shorts (too short for meaningful summaries)
    selected = []
    shorts_skipped = 0
    for video in all_videos:
        if len(selected) >= MAX_VIDEOS:
            break
        if _is_short(video["video_id"]):
            shorts_skipped += 1
            logger.debug("Skipping Short: %s (%s)", video["title"][:50], video["video_id"])
            continue
        selected.append(video)
    if shorts_skipped:
        logger.info("Skipped %d YouTube Shorts", shorts_skipped)

    # Phase 1: Try podcast RSS / website transcripts (free, reliable from any IP)
    for video in selected:
        # Channel-specific sources first
        if video["channel"] == "Morning Brew Daily":
            text, issue_url = _get_morning_brew_text(video["title"])
            if text and len(text) >= MIN_TEXT_LENGTH_MEDIUM:
                video["raw_text"] = text
                video["_text_source"] = "podcast"
                if issue_url:
                    video["source_url"] = issue_url
                continue

        if video["channel"] == "Jeff Su":
            text, blog_url = _get_jeffsu_text(video["title"])
            if text and len(text) >= MIN_TEXT_LENGTH_MEDIUM:
                video["raw_text"] = text
                video["_text_source"] = "podcast"
                if blog_url:
                    video["source_url"] = blog_url
                continue

        if video["channel"] == "Dr. Izzy Sealey":
            text, post_url = _get_izzy_text()
            if text and len(text) >= MIN_TEXT_LENGTH_MEDIUM:
                video["raw_text"] = text
                video["_text_source"] = "podcast"
                if post_url:
                    video["source_url"] = post_url
                continue

        # Try website transcripts first (fullest text)
        text, source_url = _get_website_transcript(video["channel"], video["title"])
        if not text or len(text) < MIN_TEXT_LENGTH_MEDIUM:
            # Try podcast RSS descriptions — only use if substantial
            text, source_url = _get_podcast_text(video["channel"], video["title"])
            if text and len(text) < PODCAST_MIN_DESC_CHARS:
                logger.debug("Podcast text too short (%d chars) for '%s', skipping",
                             len(text), video["title"][:50])
                text = ""
                source_url = ""
        if text and len(text) >= MIN_TEXT_LENGTH_MEDIUM:
            video["raw_text"] = text
            video["_text_source"] = "podcast"
            if source_url:
                video["source_url"] = source_url

    needs_yt = [v for v in selected if not v.get("raw_text")]
    podcast_hits = len(selected) - len(needs_yt)
    logger.info("Podcast/website text: %d/%d videos covered. %d need YouTube transcripts.",
                podcast_hits, len(selected), len(needs_yt))

    # Phase 2: YouTube transcripts for remaining videos
    for video in needs_yt:
        video["raw_text"] = _get_transcript_text(video["video_id"])
        if video["raw_text"]:
            video["_text_source"] = "youtube"

    # Summarize each video's text
    for video in selected:
        if video.get("raw_text"):
            try:
                result = extractive_summarize(video["raw_text"], num_sentences=2, title=video.get("title", ""))
                if result:
                    video["summary"] = result
            except Exception as e:
                logger.warning("Summarize failed for '%s': %s", video["title"][:60], e)

    # Clean up and log
    for video in selected:
        video.pop("published_dt", None)
        video.pop("_text_source", None)

    with_text = sum(1 for v in selected if len(v.get("raw_text", "")) > MIN_TEXT_LENGTH_MEDIUM)
    logger.info("YouTube complete: %d videos, %d with text content (podcast: %d, youtube: %d)",
                len(selected), with_text, podcast_hits,
                with_text - podcast_hits)
    return selected

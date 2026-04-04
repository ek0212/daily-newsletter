#!/usr/bin/env python3
"""Main newsletter generator: fetches all data, renders HTML, and updates the static site."""

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.constants import (
    DEFAULT_AI_NEWS_COUNT,
    DEFAULT_NEWS_COUNT,
    DEFAULT_PAPERS_DAYS_BACK,
    DEFAULT_PAPERS_TOP_N,
    DEFAULT_YOUTUBE_DAYS,
    DATE_DISPLAY_FORMAT,
)
from src.weather import get_nyc_weather
from src.news import get_top_news
from src.youtube import get_recent_videos
from src.papers import get_ai_security_papers
from src.ai_news import get_ai_security_news
from src.events import get_nyc_events
from src.health import get_nyc_health_status
from src.llm import batch_summarize, generate_trending_topics, generate_ai_security_tldr
from src.site_generator import update_site

try:
    from text_summarizer import summarize as sdk_summarize
    SDK_SUMMARIZER_AVAILABLE = True
except ImportError:
    SDK_SUMMARIZER_AVAILABLE = False
    logger.warning("text_summarizer SDK not available; sdk_summary will be skipped")

logger = logging.getLogger(__name__)

MIN_SDK_TEXT_LENGTH = 100


def _run_sdk_summarizer(items: list[dict], text_field: str = "raw_text") -> None:
    """Call sdk_summarize on each item in parallel; attach sdk_summary to the item dict."""
    if not SDK_SUMMARIZER_AVAILABLE:
        return

    def _summarize_item(item: dict) -> None:
        text = item.get(text_field) or item.get("abstract") or item.get("raw_text") or ""
        if len(text) < MIN_SDK_TEXT_LENGTH:
            return
        try:
            summary, _insights, _entities = sdk_summarize(text)
            item["sdk_summary"] = summary.strip()
        except Exception as e:
            logger.warning("sdk_summarize failed for '%s': %s", item.get("title", "?")[:60], e)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_summarize_item, item) for item in items]
        for f in as_completed(futures):
            f.result()  # surface any unexpected exceptions


def fetch_all_data() -> dict:
    """Fetch all newsletter sections, then batch-summarize via Gemini."""
    fetch_start = time.time()

    # Run all fetchers concurrently — they are fully independent
    fetchers = {
        "weather": lambda: get_nyc_weather(),
        "health": lambda: get_nyc_health_status(),
        "events": lambda: get_nyc_events(),
        "news": lambda: get_top_news(count=DEFAULT_NEWS_COUNT),
        "youtube": lambda: get_recent_videos(days=DEFAULT_YOUTUBE_DAYS),
        "papers": lambda: get_ai_security_papers(days_back=DEFAULT_PAPERS_DAYS_BACK, top_n=DEFAULT_PAPERS_TOP_N),
        "ai_security_news": lambda: get_ai_security_news(count=DEFAULT_AI_NEWS_COUNT),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
        future_to_name = {}
        timers = {}
        for name, fn in fetchers.items():
            timers[name] = time.time()
            future_to_name[executor.submit(fn)] = name

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.error("Fetcher %s failed: %s", name, e)
                results[name] = [] if name != "weather" else {}
            logger.info("%s fetched in %.1fs", name.capitalize(), time.time() - timers[name])

    weather = results["weather"]
    health = results["health"]
    events = results["events"]
    news = results["news"]
    youtube = results["youtube"]
    papers = results["papers"]
    ai_security_news = results["ai_security_news"]

    logger.info("All data fetched in %.1fs", time.time() - fetch_start)

    # Merge papers and ai_security_news into a single list sorted by date
    for p in papers:
        p["type"] = "paper"
    for n in ai_security_news:
        n["type"] = "news"
    ai_security = sorted(
        papers + ai_security_news,
        key=lambda x: x.get("published", ""),
        reverse=True,
    )

    # Batch summarize all sections in one Gemini call
    sections = {
        "news": [{"title": n["title"], "raw_text": n.get("raw_text", "")} for n in news],
        "youtube": [{"title": v["title"], "channel": v.get("channel", ""), "raw_text": v.get("raw_text", "")} for v in youtube],
        "ai_security": [{"title": item["title"], "raw_text": item.get("raw_text", "")} for item in ai_security if item.get("type") == "news"],
    }
    summaries = batch_summarize(sections)

    # Distribute summaries back
    for i, item in enumerate(news):
        if i < len(summaries.get("news", [])) and summaries["news"][i]:
            item["summary"] = summaries["news"][i]
        if not item.get("summary"):
            item["summary"] = f"📰 <strong>Breaking</strong> — Read the full story at {item['source']}." if item.get("source") else "📰 <strong>Developing story</strong> — Click the headline for full details."

    for i, item in enumerate(youtube):
        if i < len(summaries.get("youtube", [])) and summaries["youtube"][i]:
            item["summary"] = summaries["youtube"][i]
        if not item.get("summary"):
            item["summary"] = "🎬 New video — Click to watch."
        # Prefer source URL (newsletter/blog) over YouTube link
        if item.get("source_url"):
            item["link"] = item["source_url"]

    ai_security_news_items = [item for item in ai_security if item.get("type") == "news"]
    for i, item in enumerate(ai_security_news_items):
        if i < len(summaries.get("ai_security", [])) and summaries["ai_security"][i]:
            item["summary"] = summaries["ai_security"][i]
        if not item.get("summary"):
            item["summary"] = "🛡️ Security update — Click for details."
    for item in ai_security:
        if item["type"] == "paper":
            item["quick_summary"] = item.get("abstract", "")

    # Run text-summarizer SDK on all items in parallel
    t0 = time.time()
    all_content_items = news + youtube + ai_security
    _run_sdk_summarizer(all_content_items)
    logger.info("SDK summarization completed in %.1fs", time.time() - t0)

    # Generate trending AI security topics for purple teamers
    t0 = time.time()
    trending_topics = generate_trending_topics(ai_security)
    logger.info("Trending topics generated in %.1fs", time.time() - t0)

    # Generate one-sentence AI security TLDR
    t0 = time.time()
    ai_security_tldr = generate_ai_security_tldr(ai_security)
    logger.info("AI security TLDR generated in %.1fs", time.time() - t0)

    return {
        "date": datetime.now().strftime(DATE_DISPLAY_FORMAT),
        "weather": weather,
        "health": health,
        "events": events,
        "news": news,
        "youtube": youtube,
        "trending_topics": trending_topics,
        "ai_security_tldr": ai_security_tldr,
        "ai_security": ai_security,
    }


def render_html(data: dict) -> str:
    """Render the newsletter HTML template with data."""
    template_dir = PROJECT_ROOT / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("newsletter.html")
    return template.render(**data)


def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    load_dotenv(PROJECT_ROOT / ".env")

    logger.info("=== Daily Newsletter Build Started ===")

    data = fetch_all_data()
    html = render_html(data)
    logger.info("HTML rendered: %d chars", len(html))

    # Generate static site files (archive, index, RSS)
    update_site(data, html)

    # Save output.html for local testing
    output_path = PROJECT_ROOT / "output.html"
    output_path.write_text(html)

    logger.info("=== Build Complete ===")


if __name__ == "__main__":
    main()

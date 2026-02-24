#!/usr/bin/env python3
"""Main newsletter generator: fetches all data, renders HTML, and updates the static site."""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.weather import get_nyc_weather
from src.news import get_top_news
from src.podcasts import get_recent_episodes
from src.papers import get_ai_security_papers
from src.ai_news import get_ai_security_news
from src.llm import batch_summarize
from src.site_generator import update_site

logger = logging.getLogger(__name__)


def fetch_all_data() -> dict:
    """Fetch all newsletter sections, then batch-summarize via Gemini."""
    fetch_start = time.time()

    t0 = time.time()
    weather = get_nyc_weather()
    logger.info("Weather fetched in %.1fs", time.time() - t0)

    t0 = time.time()
    news = get_top_news(count=5)
    logger.info("News fetched in %.1fs", time.time() - t0)

    t0 = time.time()
    podcasts = get_recent_episodes(days=7)
    logger.info("Podcasts fetched in %.1fs", time.time() - t0)

    t0 = time.time()
    papers = get_ai_security_papers(days_back=7, top_n=5)
    logger.info("Papers fetched in %.1fs", time.time() - t0)

    t0 = time.time()
    ai_security_news = get_ai_security_news(count=4)
    logger.info("AI security news fetched in %.1fs", time.time() - t0)

    logger.info("All data fetched in %.1fs", time.time() - fetch_start)

    # Batch summarize all sections in one Gemini call
    sections = {
        "news": [{"title": n["title"], "raw_text": n.get("raw_text", "")} for n in news],
        "ai_security_news": [{"title": n["title"], "raw_text": n.get("raw_text", "")} for n in ai_security_news],
        "podcasts": [{"title": p["title"], "podcast": p.get("podcast", ""), "raw_text": p.get("raw_text", "")} for p in podcasts],
        "papers": [{"title": p["title"], "raw_text": p.get("raw_text", "")} for p in papers],
    }
    summaries = batch_summarize(sections)

    # Distribute summaries back
    for i, item in enumerate(news):
        if i < len(summaries.get("news", [])) and summaries["news"][i]:
            item["summary"] = summaries["news"][i]
        if not item.get("summary"):
            item["summary"] = f"📰 <strong>Breaking</strong> — Read the full story at {item['source']}." if item.get("source") else "📰 <strong>Developing story</strong> — Click the headline for full details."

    for i, item in enumerate(podcasts):
        if i < len(summaries.get("podcasts", [])) and summaries["podcasts"][i]:
            item["summary"] = summaries["podcasts"][i]
        if not item.get("summary"):
            raw = (item.get("raw_text", "") or "")[:400]
            item["summary"] = raw if raw else "🎙️ <strong>New episode</strong> — Click the headline to listen."

    for i, item in enumerate(papers):
        if i < len(summaries.get("papers", [])) and summaries["papers"][i]:
            item["quick_summary"] = summaries["papers"][i]
        if not item.get("quick_summary"):
            abstract = item.get("abstract", "")[:200]
            item["quick_summary"] = abstract if abstract else "🧠 <strong>New research</strong> — Click the headline to read the paper."

    for i, item in enumerate(ai_security_news):
        if i < len(summaries.get("ai_security_news", [])) and summaries["ai_security_news"][i]:
            item["summary"] = summaries["ai_security_news"][i]
        if not item.get("summary"):
            item["summary"] = f"🛡️ <strong>Security alert</strong> — Read the full story at {item['source']}." if item.get("source") else "🛡️ <strong>Security update</strong> — Click the headline for full details."

    return {
        "date": datetime.now().strftime("%A, %B %d, %Y"),
        "weather": weather,
        "news": news,
        "podcasts": podcasts,
        "papers": papers,
        "ai_security_news": ai_security_news,
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

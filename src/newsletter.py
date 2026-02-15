#!/usr/bin/env python3
"""Main newsletter generator: fetches all data, renders HTML, and updates the static site."""

import sys
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
from src.llm import batch_summarize
from src.site_generator import update_site


def fetch_all_data() -> dict:
    """Fetch all newsletter sections, then batch-summarize via Gemini."""
    print("Fetching NYC weather...")
    weather = get_nyc_weather()

    print("Fetching top news...")
    news = get_top_news(count=3)

    print("Fetching podcast episodes...")
    podcasts = get_recent_episodes(days=7)

    print("Fetching AI security papers...")
    papers = get_ai_security_papers(days_back=7, top_n=5)

    # Batch summarize all sections in one Gemini call
    print("Summarizing all content...")
    sections = {
        "news": [{"title": n["title"], "raw_text": n.get("raw_text", "")} for n in news],
        "podcasts": [{"title": p["title"], "podcast": p.get("podcast", ""), "raw_text": p.get("raw_text", "")} for p in podcasts],
        "papers": [{"title": p["title"], "raw_text": p.get("raw_text", "")} for p in papers],
    }
    summaries = batch_summarize(sections)

    # Distribute summaries back
    for i, item in enumerate(news):
        if i < len(summaries.get("news", [])):
            item["summary"] = summaries["news"][i]
        if not item["summary"]:
            item["summary"] = f"Read more at {item['source']}" if item.get("source") else ""

    for i, item in enumerate(podcasts):
        if i < len(summaries.get("podcasts", [])):
            item["summary"] = summaries["podcasts"][i]
        if not item["summary"]:
            item["summary"] = (item.get("raw_text", "") or "")[:400]

    for i, item in enumerate(papers):
        if i < len(summaries.get("papers", [])):
            item["quick_summary"] = summaries["papers"][i]
        if not item.get("quick_summary"):
            item["quick_summary"] = item.get("abstract", "")[:200]

    return {
        "date": datetime.now().strftime("%A, %B %d, %Y"),
        "weather": weather,
        "news": news,
        "podcasts": podcasts,
        "papers": papers,
    }


def render_html(data: dict) -> str:
    """Render the newsletter HTML template with data."""
    template_dir = PROJECT_ROOT / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("newsletter.html")
    return template.render(**data)


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    data = fetch_all_data()
    html = render_html(data)

    # Generate static site files (archive, index, RSS)
    update_site(data, html)

    # Save output.html for local testing
    output_path = PROJECT_ROOT / "output.html"
    output_path.write_text(html)
    print(f"Site updated successfully. Newsletter saved to {output_path}")


if __name__ == "__main__":
    main()

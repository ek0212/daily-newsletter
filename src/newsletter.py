#!/usr/bin/env python3
"""Main newsletter generator: fetches all data, renders HTML, and updates the static site."""

import logging
import re
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    DEDUP_OVERLAP_THRESHOLD,
)
from src.weather import get_nyc_weather
from src.news import get_top_news
from src.youtube import get_recent_videos
from src.papers import get_ai_security_papers
from src.ai_news import get_ai_security_news
from src.events import get_nyc_events
from src.health import get_nyc_health_status
from src.llm import generate_ai_security_tldr
from src.llm_summarizer import enhance_summaries
from src.site_generator import update_site

logger = logging.getLogger(__name__)

# AI security topic clusters — limit to 1 item per cluster to avoid repetition
_AI_SECURITY_TOPIC_CLUSTERS = [
    ("prompt_injection", re.compile(r'(?i)\b(prompt injection|indirect injection|instruction injection)\b')),
    ("jailbreak",        re.compile(r'(?i)\b(jailbreak|jail.break|bypass|adversarial prompt)\b')),
    ("agentic",          re.compile(r'(?i)\b(agentic|autonomous agent|multi.agent|tool.use|agent safety)\b')),
    ("model_extraction", re.compile(r'(?i)\b(model extraction|distillation attack|model theft)\b')),
    ("phishing_malware", re.compile(r'(?i)\b(phishing|malware|social engineering|clickfix)\b')),
    ("safety_alignment", re.compile(r'(?i)\b(safety|alignment|sycophancy|sabotage|behavioral eval)\b')),
    ("privacy",          re.compile(r'(?i)\b(privacy|data leakage|membership inference|pii)\b')),
    ("red_teaming",      re.compile(r'(?i)\b(red team|red.teaming|purple team|blue team)\b')),
]

_MAX_PER_TOPIC_CLUSTER = 2


def _title_words(title: str) -> set[str]:
    """Extract meaningful words from a title for overlap comparison."""
    stopwords = {"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are", "was", "were", "by", "with", "from", "as", "its", "has", "have", "had", "be", "been", "will", "would", "could", "should", "may", "might"}
    words = set(w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', title))
    return words - stopwords


def _deduplicate_items(items: list[dict]) -> list[dict]:
    """Remove items whose titles overlap significantly with earlier items."""
    kept = []
    kept_words = []
    for item in items:
        words = _title_words(item.get("title", ""))
        if not words:
            kept.append(item)
            continue
        is_dup = False
        for prev_words in kept_words:
            if not prev_words:
                continue
            overlap = len(words & prev_words) / min(len(words), len(prev_words))
            if overlap >= DEDUP_OVERLAP_THRESHOLD:
                logger.debug("Dedup: dropping '%s' (overlaps with existing)", item.get("title", "")[:60])
                is_dup = True
                break
        if not is_dup:
            kept.append(item)
            kept_words.append(words)
    if len(kept) < len(items):
        logger.info("Cross-dedup: %d -> %d items", len(items), len(kept))
    return kept


def _deduplicate_by_topic(items: list[dict]) -> list[dict]:
    """Limit AI security items to _MAX_PER_TOPIC_CLUSTER per topic cluster.

    Items are already sorted by date (newest first). We keep the most recent
    per cluster and collect unclustered items separately.
    """
    cluster_counts: dict[str, int] = {}
    kept = []
    for item in items:
        text = (item.get("title", "") + " " + (item.get("abstract") or item.get("raw_text") or "")[:300]).lower()
        matched_cluster = None
        for cluster_name, pattern in _AI_SECURITY_TOPIC_CLUSTERS:
            if pattern.search(text):
                matched_cluster = cluster_name
                break
        if matched_cluster:
            count = cluster_counts.get(matched_cluster, 0)
            if count >= _MAX_PER_TOPIC_CLUSTER:
                logger.debug("AI security dedup: dropping cluster '%s' item: %s", matched_cluster, item.get("title", "")[:60])
                continue
            cluster_counts[matched_cluster] = count + 1
        kept.append(item)
    logger.info("AI security dedup: %d -> %d items", len(items), len(kept))
    return kept


def fetch_all_data() -> dict:
    """Fetch all newsletter sections and summarize with extractive summarizer."""
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

    # Cross-section deduplication (catches same story from different sources)
    news = _deduplicate_items(news)

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
    ai_security = _deduplicate_items(ai_security)
    ai_security = _deduplicate_by_topic(ai_security)

    # ── LLM editorial enhancement pass ──────────────────────────────────
    # Groq rewrites extractive summaries into editorial 2-sentence blurbs.
    # Items the LLM flags as low-signal get dropped.
    t0 = time.time()
    enhance_summaries(news, "news")
    enhance_summaries(youtube, "youtube")

    # AI security items: papers vs news get different prompts
    ai_papers = [i for i in ai_security if i.get("type") == "paper"]
    ai_news_items = [i for i in ai_security if i.get("type") == "news"]
    enhance_summaries(ai_papers, "paper")
    enhance_summaries(ai_news_items, "ai_news")
    ai_security = [i for i in ai_papers + ai_news_items if not i.get("llm_skip")]
    ai_security.sort(key=lambda x: x.get("published", ""), reverse=True)
    logger.info("LLM enhancement pass completed in %.1fs", time.time() - t0)

    # Drop LLM-skipped items from news and youtube too
    news = [i for i in news if not i.get("llm_skip")]
    youtube = [i for i in youtube if not i.get("llm_skip")]

    # Apply fallbacks for any items that still lack a summary
    for item in news:
        if not item.get("summary"):
            item["summary"] = (
                f"Read the full story at {item['source']}."
                if item.get("source")
                else "Click the headline for full details."
            )

    for item in youtube:
        if not item.get("summary"):
            channel = item.get("channel", "")
            item["summary"] = f"New episode from {channel}. Click to watch." if channel else "New video. Click to watch."
        if item.get("source_url"):
            item["link"] = item["source_url"]

    for item in ai_security:
        if not item.get("summary"):
            if item.get("type") == "paper":
                item["summary"] = "Read the full paper for details."
            else:
                item["summary"] = "Security update, click for details."

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
    from src.constants import VERBOSE_LOGGING
    log_level = logging.DEBUG if VERBOSE_LOGGING else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
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

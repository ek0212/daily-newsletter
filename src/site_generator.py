#!/usr/bin/env python3
"""Generate static site files: archive JSON, post HTML, index, and RSS feed."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring, indent

ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SITE_DIR = PROJECT_ROOT / "site"
POSTS_DIR = SITE_DIR / "posts"

# Configurable base URL for GitHub Pages
SITE_URL = os.getenv("SITE_URL", "https://ek0212.github.io/daily-newsletter")


def ensure_dirs():
    SITE_DIR.mkdir(exist_ok=True)
    POSTS_DIR.mkdir(exist_ok=True)


def save_archive_json(data: dict, date_str: str):
    """Save newsletter data as JSON for the archive."""
    ensure_dirs()
    path = POSTS_DIR / f"{date_str}.json"
    path.write_text(json.dumps(data, default=str, indent=2))
    return path


def generate_post_html(data: dict, date_str: str, email_html: str):
    """Generate a standalone HTML page for a single newsletter."""
    ensure_dirs()
    html = _post_page(data, date_str, email_html)
    path = POSTS_DIR / f"{date_str}.html"
    path.write_text(html)
    return path


def generate_index():
    """Regenerate the landing page with latest newsletter and archive list."""
    ensure_dirs()
    posts = _get_sorted_posts()
    latest_data = None
    latest_date = None
    latest_html_content = ""

    if posts:
        latest_date = posts[0]
        json_path = POSTS_DIR / f"{latest_date}.json"
        if json_path.exists():
            latest_data = json.loads(json_path.read_text())
        html_path = POSTS_DIR / f"{latest_date}.html"
        if html_path.exists():
            latest_html_content = html_path.read_text()

    html = _index_page(posts, latest_data, latest_date)
    (SITE_DIR / "index.html").write_text(html)


def generate_feed():
    """Regenerate the RSS 2.0 feed from all archived posts."""
    ensure_dirs()
    posts = _get_sorted_posts()

    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Daily Briefing Newsletter"
    SubElement(channel, "link").text = SITE_URL
    SubElement(channel, "description").text = "A daily curated newsletter with weather, news, podcasts, and AI security papers."
    SubElement(channel, "language").text = "en-us"
    SubElement(channel, "lastBuildDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    atom_link = SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", f"{SITE_URL}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for date_str in posts[:30]:  # last 30 entries
        json_path = POSTS_DIR / f"{date_str}.json"
        html_path = POSTS_DIR / f"{date_str}.html"
        if not json_path.exists():
            continue

        data = json.loads(json_path.read_text())
        item = SubElement(channel, "item")
        SubElement(item, "title").text = f"Daily Briefing - {data.get('date', date_str)}"
        link = f"{SITE_URL}/posts/{date_str}.html"
        SubElement(item, "link").text = link
        SubElement(item, "guid").text = link

        # Build a summary from the data
        summary_parts = []
        if data.get("weather"):
            w = data["weather"]
            summary_parts.append(f"Weather: {w.get('current_temp', '?')}°{w.get('unit', 'F')} - {w.get('conditions', '')}")
        news = data.get("news", [])
        if news:
            summary_parts.append(f"{len(news)} top news stories")
        pods = data.get("podcasts", [])
        if pods:
            summary_parts.append(f"{len(pods)} podcast episodes")
        papers = data.get("papers", [])
        if papers:
            summary_parts.append(f"{len(papers)} AI security papers")

        SubElement(item, "description").text = " | ".join(summary_parts) if summary_parts else "Daily newsletter"

        # Include full HTML content if available
        if html_path.exists():
            content = html_path.read_text()
            encoded = SubElement(item, "{http://purl.org/rss/1.0/modules/content/}encoded")
            encoded.text = content

        # Parse date for pubDate
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y 07:00:00 +0000")
        except ValueError:
            pass

    indent(rss, space="  ")
    xml_bytes = tostring(rss, encoding="unicode", xml_declaration=False)
    feed_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes
    (SITE_DIR / "feed.xml").write_text(feed_content)


def update_site(data: dict, email_html: str):
    """Main entry point: save archive, generate post, rebuild index and feed."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    json_path = save_archive_json(data, date_str)
    logger.info("Saving archive: %s", json_path.relative_to(PROJECT_ROOT))
    html_path = generate_post_html(data, date_str, email_html)
    logger.info("Generating post page: %s", html_path.relative_to(PROJECT_ROOT))
    posts = _get_sorted_posts()
    generate_index()
    logger.info("Regenerating index.html (%d posts in archive)", len(posts))
    generate_feed()
    logger.info("Regenerating feed.xml (%d entries)", min(len(posts), 30))
    # Log file sizes
    for name, fpath in [("index.html", SITE_DIR / "index.html"), ("feed.xml", SITE_DIR / "feed.xml"),
                        (f"{date_str}.json", json_path), (f"{date_str}.html", html_path)]:
        if fpath.exists():
            logger.debug("File size %s: %d bytes", name, fpath.stat().st_size)


def _get_sorted_posts():
    """Return list of date strings from archived JSON files, newest first."""
    if not POSTS_DIR.exists():
        return []
    dates = []
    for f in POSTS_DIR.glob("*.json"):
        dates.append(f.stem)
    dates.sort(reverse=True)
    return dates


def _post_page(data: dict, date_str: str, email_html: str) -> str:
    """Self-contained HTML page for a single newsletter post."""
    display_date = data.get("date", date_str)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Briefing - {display_date}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f0f5; color: #1a1a1a; }}
  .site-nav {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 14px 24px; text-align: center; }}
  .site-nav a {{ color: rgba(255,255,255,0.8); text-decoration: none; font-size: 14px; font-weight: 500; }}
  .site-nav a:hover {{ color: #fff; }}
  .email-wrap {{ max-width: 680px; margin: 28px auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
</style>
</head>
<body>
<div class="site-nav">
  <a href="../index.html">&larr; Back to Daily Briefing</a>
</div>
<div class="email-wrap">
{email_html}
</div>
</body>
</html>"""


def _index_page(posts: list, latest_data: dict | None, latest_date: str | None) -> str:
    """Generate the landing page HTML."""
    # Build archive list HTML
    archive_items = ""
    for d in posts:
        json_path = POSTS_DIR / f"{d}.json"
        display = d
        if json_path.exists():
            try:
                jd = json.loads(json_path.read_text())
                display = jd.get("date", d)
            except Exception:
                pass
        archive_items += f'<li><a href="posts/{d}.html">{display}</a></li>\n'

    if not archive_items:
        archive_items = '<li class="no-items">No newsletters yet.</li>'

    # Latest newsletter summary
    latest_section = ""
    if latest_data and latest_date:
        display_date = latest_data.get("date", latest_date)
        latest_section = f"""
    <div class="latest">
      <h2>Latest Issue</h2>
      <div class="date-label">{display_date}</div>
      <a href="posts/{latest_date}.html" class="read-btn">Read Latest Newsletter &rarr;</a>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Briefing</title>
<link rel="alternate" type="application/rss+xml" title="Daily Briefing RSS" href="feed.xml">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f0f5; color: #1a1a1a; min-height: 100vh; }}
  .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: #fff; padding: 56px 24px 48px; text-align: center; }}
  .header h1 {{ font-size: 34px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 10px; }}
  .header p {{ font-size: 15px; opacity: 0.75; max-width: 400px; margin: 0 auto; line-height: 1.5; }}
  .rss-btn {{ display: inline-block; margin-top: 24px; padding: 11px 28px; background: rgba(255,255,255,0.12); color: #fff; text-decoration: none; border-radius: 8px; font-size: 14px; font-weight: 500; border: 1px solid rgba(255,255,255,0.2); transition: background 0.2s; }}
  .rss-btn:hover {{ background: rgba(255,255,255,0.22); }}
  .content {{ max-width: 640px; margin: 0 auto; padding: 36px 20px; }}
  .latest {{ background: #fff; border-radius: 12px; padding: 28px; margin-bottom: 28px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); border: 1px solid #e8e8ee; }}
  .latest h2 {{ font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #6c63ff; margin-bottom: 14px; }}
  .latest .date-label {{ font-size: 20px; font-weight: 600; color: #1a1a2e; margin-bottom: 16px; }}
  .read-btn {{ display: inline-block; padding: 10px 22px; background: #6c63ff; color: #fff; text-decoration: none; border-radius: 8px; font-size: 14px; font-weight: 600; }}
  .read-btn:hover {{ background: #5a52e0; }}
  .archive {{ background: #fff; border-radius: 12px; padding: 28px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); border: 1px solid #e8e8ee; }}
  .archive h2 {{ font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #1a1a2e; margin-bottom: 18px; }}
  .archive ul {{ list-style: none; }}
  .archive li {{ padding: 10px 0; border-bottom: 1px solid #f0f0f0; }}
  .archive li:last-child {{ border-bottom: none; }}
  .archive a {{ color: #1a1a2e; text-decoration: none; font-size: 15px; font-weight: 500; }}
  .archive a:hover {{ color: #6c63ff; }}
  .no-items {{ color: #888; font-style: italic; font-size: 14px; }}
  .footer {{ text-align: center; padding: 36px 20px; font-size: 12px; color: #aaa; }}
</style>
</head>
<body>
<div class="header">
  <h1>Daily Briefing</h1>
  <p>Weather, news, podcasts &amp; AI security papers &mdash; delivered daily.</p>
  <a href="feed.xml" class="rss-btn">Subscribe via RSS</a>
</div>
<div class="content">
  {latest_section}
  <div class="archive">
    <h2>Archive</h2>
    <ul>
      {archive_items}
    </ul>
  </div>
</div>
<div class="footer">Daily Briefing Newsletter</div>
</body>
</html>"""

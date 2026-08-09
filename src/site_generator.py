#!/usr/bin/env python3
"""Generate static site files: archive JSON, post HTML, index, and RSS feed."""

import json
import logging
import os
import shutil
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
STATIC_DIR = PROJECT_ROOT / "static"

from src.constants import (
    DEFAULT_SITE_URL,
    MAX_FEED_ITEMS,
    RSS_BUILD_DATE_FORMAT,
    RSS_PUB_DATE_FORMAT,
)

# Configurable base URL for GitHub Pages
SITE_URL = os.getenv("SITE_URL", "").strip() or DEFAULT_SITE_URL


def ensure_dirs():
    SITE_DIR.mkdir(exist_ok=True)
    POSTS_DIR.mkdir(exist_ok=True)
    # Copy static assets (favicon, etc.) into site dir
    if STATIC_DIR.exists():
        for f in STATIC_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, SITE_DIR / f.name)


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
    # Save raw email HTML for RSS feed (no site wrapper)
    email_path = POSTS_DIR / f"{date_str}.email.html"
    email_path.write_text(email_html)
    return path


def generate_index():
    """Regenerate the landing page with latest newsletter and archive list."""
    ensure_dirs()
    posts = _get_sorted_posts()
    latest_data = None
    latest_date = None
    latest_email_html = ""

    if posts:
        latest_date = posts[0]
        json_path = POSTS_DIR / f"{latest_date}.json"
        if json_path.exists():
            latest_data = json.loads(json_path.read_text())
        email_path = POSTS_DIR / f"{latest_date}.email.html"
        if email_path.exists():
            latest_email_html = email_path.read_text()

    html = _index_page(posts, latest_data, latest_date, latest_email_html)
    (SITE_DIR / "index.html").write_text(html)


def generate_feed():
    """Regenerate the RSS 2.0 feed from all archived posts.

    Uses CDATA sections for content:encoded so HTML is delivered raw
    to RSS readers and email services like Blogtrottr (not XML-escaped).
    """
    ensure_dirs()
    posts = _get_sorted_posts()

    # We build the feed XML manually to support CDATA in content:encoded,
    # since xml.etree.ElementTree doesn't support CDATA natively.
    items_xml = []

    for date_str in posts[:MAX_FEED_ITEMS]:
        json_path = POSTS_DIR / f"{date_str}.json"
        if not json_path.exists():
            continue

        data = json.loads(json_path.read_text())
        title = f"Daily Morning Briefing - {data.get('date', date_str)}"
        link = f"{SITE_URL}/posts/{date_str}.html"

        # Build a summary from the data
        summary_parts = []
        if data.get("weather"):
            w = data["weather"]
            summary_parts.append(f"Weather: {w.get('current_temp', '?')}\u00b0{w.get('unit', 'F')} - {w.get('conditions', '')}")
        if data.get("health") and data["health"].get("status") != "UNKNOWN":
            summary_parts.append(f"Illness level: {data['health']['status']}")
        events = data.get("events", [])
        if events:
            summary_parts.append(f"{len(events)} major events this week")
        news = data.get("news", [])
        if news:
            summary_parts.append(f"{len(news)} top news stories")
        vids = data.get("youtube", [])
        if vids:
            summary_parts.append(f"{len(vids)} YouTube videos")
        ai_sec = data.get("ai_security", [])
        if ai_sec:
            summary_parts.append(f"{len(ai_sec)} AI security updates")
        description = _xml_escape(" | ".join(summary_parts)) if summary_parts else "Daily newsletter"

        # Get email HTML content
        email_path = POSTS_DIR / f"{date_str}.email.html"
        html_path = POSTS_DIR / f"{date_str}.html"
        html_content = ""
        if email_path.exists():
            html_content = email_path.read_text()
        elif html_path.exists():
            html_content = html_path.read_text()

        # pubDate
        pub_date = ""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            pub_date = dt.strftime(RSS_PUB_DATE_FORMAT)
        except ValueError:
            pass

        item_parts = [
            "    <item>",
            f"      <title>{_xml_escape(title)}</title>",
            f"      <link>{_xml_escape(link)}</link>",
            f"      <guid>{_xml_escape(link)}</guid>",
            f"      <description>{description}</description>",
        ]
        if html_content:
            item_parts.append(f"      <content:encoded><![CDATA[{html_content}]]></content:encoded>")
        if pub_date:
            item_parts.append(f"      <pubDate>{pub_date}</pubDate>")
        item_parts.append("    </item>")
        items_xml.append("\n".join(item_parts))

    build_date = datetime.utcnow().strftime(RSS_BUILD_DATE_FORMAT)
    feed_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
  <channel>
    <title>Daily Morning Briefing</title>
    <link>{SITE_URL}</link>
    <description>Daily Morning Briefing: weather, news, YouTube, and AI security, delivered daily.</description>
    <language>en-us</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml" />
{chr(10).join(items_xml)}
  </channel>
</rss>"""

    (SITE_DIR / "feed.xml").write_text(feed_content)


def _xml_escape(text: str) -> str:
    """Escape special XML characters in text content."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


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
    logger.info("Regenerating feed.xml (%d entries)", min(len(posts), MAX_FEED_ITEMS))
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


def _strip_email_wrapper(html: str) -> str:
    """Strip outer document tags from email HTML for safe embedding in a post page."""
    import re
    html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</?html[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<head>.*?</head>', '', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'</?body[^>]*>', '', html, flags=re.IGNORECASE)
    return html.strip()


def _post_page(data: dict, date_str: str, email_html: str) -> str:
    """Return the exact email HTML for the public post page."""
    display_date = data.get("date", date_str)
    if "<title>" in email_html:
        return email_html
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Morning Briefing - {display_date}</title>
</head>
{email_html}
</html>"""


def _index_page(posts: list, latest_data: dict | None, latest_date: str | None, latest_email_html: str = "") -> str:
    """Generate the landing page HTML."""
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
        archive_items += f"""<div class="archive-row">
        <span>{_xml_escape(display)}</span>
        <a href="posts/{d}.html">Read</a>
      </div>"""

    if not archive_items:
        archive_items = '<div class="no-items">No newsletters yet.</div>'

    latest_href = f"posts/{latest_date}.html" if latest_date else "#"
    latest_issue = (
        _strip_email_wrapper(latest_email_html)
        if latest_email_html
        else '<div class="no-items">Latest email HTML unavailable.</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Morning Briefing</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="alternate" type="application/rss+xml" title="Daily Morning Briefing RSS" href="feed.xml">
<style>
  body {{ margin:0; background:#f1efeb; color:#15181b; }}
  .page-nav {{ max-width:640px; margin:0 auto; padding:14px 8px 0; display:flex; justify-content:space-between; gap:12px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; font-size:11px; line-height:16px; }}
  .page-nav a {{ color:#5f6a66; text-decoration:none; border-bottom:1px solid #d4e6da; }}
  .archive-shell {{ max-width:640px; margin:0 auto 36px; padding:0 8px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }}
  .archive-box {{ background:#ffffff; border-radius:14px; padding:18px 26px 22px; }}
  .archive-title {{ font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace; font-size:9px; letter-spacing:1.4px; color:#9aa19e; text-transform:uppercase; margin-bottom:5px; }}
  .archive-row {{ display:grid; grid-template-columns:1fr auto; gap:12px; align-items:center; padding:9px 0; border-top:1px solid #e6e2da; font-size:12px; line-height:18px; color:#5f6a66; }}
  .archive-row a {{ color:#15181b; text-decoration:none; border-bottom:1px solid #d4e6da; font-weight:600; }}
  .no-items {{ padding:9px 0; font-size:12px; line-height:18px; color:#9aa19e; }}
  @media (max-width:680px) {{ .archive-box {{ border-radius:0; padding-left:18px; padding-right:18px; }} }}
</style>
</head>
<body>
<nav class="page-nav">
  <a href="feed.xml">RSS</a>
  <a href="{latest_href}">Latest issue</a>
</nav>
{latest_issue}
<section class="archive-shell">
  <div class="archive-box">
    <div class="archive-title">Archive</div>
    <div aria-label="Back issues">
      {archive_items}
    </div>
  </div>
</section>
</body>
</html>"""

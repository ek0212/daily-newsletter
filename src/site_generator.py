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
        title = f"Daily Briefing - {data.get('date', date_str)}"
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
    <title>Daily Briefing Newsletter</title>
    <link>{SITE_URL}</link>
    <description>A daily curated newsletter with weather, news, YouTube, and AI security.</description>
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


def _post_page(data: dict, date_str: str, email_html: str) -> str:
    """Self-contained HTML page for a single newsletter post."""
    display_date = data.get("date", date_str)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Briefing &mdash; {display_date}</title>
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Times New Roman', Times, Georgia, serif; background: #f5f0e8; color: #1a1a1a; }}
  .site-nav {{ background: #1a1a1a; padding: 12px 24px; text-align: center; border-bottom: 1px solid #333; }}
  .site-nav a {{ color: rgba(255,255,255,0.7); text-decoration: none; font-size: 13px; letter-spacing: 1px; text-transform: uppercase; font-family: 'Times New Roman', Times, serif; }}
  .site-nav a:hover {{ color: #fff; }}
  .email-wrap {{ max-width: 680px; margin: 28px auto; background: #fffdf7; overflow: hidden; box-shadow: 0 1px 8px rgba(0,0,0,0.06); }}
</style>
</head>
<body>
<div class="site-nav">
  <a href="../index.html">&larr; Back to Daily Briefing</a>
</div>
<div class="email-wrap">
{email_html}
</div>
<script>
(function() {{
  var STORAGE_KEY = 'newsletter_likes';
  var sectionMap = {{'c0392b': 'news', '8e44ad': 'youtube', '27ae60': 'ai_security'}};

  function getStore() {{
    try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {{version:1,items:[]}}; }}
    catch(e) {{ return {{version:1,items:[]}}; }}
  }}
  function saveStore(store) {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(store)); }}

  function getDateFromURL() {{
    var m = window.location.pathname.match(/(\\d{{4}}-\\d{{2}}-\\d{{2}})/);
    return m ? m[1] : '';
  }}

  async function hashLink(link) {{
    var enc = new TextEncoder().encode(link);
    var buf = await crypto.subtle.digest('SHA-256', enc);
    return Array.from(new Uint8Array(buf)).map(function(b){{ return b.toString(16).padStart(2,'0'); }}).join('');
  }}

  function detectSection(el) {{
    var node = el;
    while (node && node !== document.body) {{
      var style = node.getAttribute('style') || '';
      for (var color in sectionMap) {{
        if (style.indexOf(color) !== -1) return sectionMap[color];
      }}
      node = node.parentElement;
    }}
    return 'other';
  }}

  function findCards() {{
    var cards = [];
    var wraps = document.querySelectorAll('.email-wrap div[style]');
    wraps.forEach(function(div) {{
      var a = div.querySelector('a[href]');
      if (!a) return;
      var style = div.getAttribute('style') || '';
      if (style.indexOf('margin-bottom') === -1 && style.indexOf('padding') === -1) return;
      var summaryDiv = div.querySelector('div[style*="font-size"]');
      var sourceEl = div.querySelector('span[style*="italic"], i, em');
      if (!summaryDiv) return;
      cards.push({{
        el: div,
        title: a.textContent.trim(),
        link: a.href,
        source: sourceEl ? sourceEl.textContent.trim() : '',
        summary: summaryDiv.innerHTML,
        section: detectSection(div)
      }});
    }});
    return cards;
  }}

  function updateExportBtn() {{
    var store = getStore();
    var btn = document.getElementById('export-likes-btn');
    if (store.items.length > 0) {{
      btn.style.display = 'block';
      btn.textContent = 'Export Likes (' + store.items.length + ')';
    }} else {{
      btn.style.display = 'none';
    }}
  }}

  function createExportBtn() {{
    var btn = document.createElement('button');
    btn.id = 'export-likes-btn';
    btn.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#1a1a1a;color:#fff;border:none;padding:8px 14px;font-family:Times New Roman,serif;font-size:13px;cursor:pointer;z-index:9999;display:none;';
    btn.addEventListener('click', function() {{
      var store = getStore();
      var blob = new Blob([JSON.stringify(store, null, 2)], {{type:'application/json'}});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'likes.json';
      a.click();
    }});
    document.body.appendChild(btn);
  }}

  async function init() {{
    var store = getStore();
    var savedIds = new Set(store.items.map(function(i){{ return i.id; }}));
    var ndate = getDateFromURL();
    var cards = findCards();

    createExportBtn();

    for (var idx = 0; idx < cards.length; idx++) {{
      var c = cards[idx];
      var id = await hashLink(c.link);
      c.el.style.position = 'relative';
      var btn = document.createElement('button');
      btn.className = 'like-btn';
      btn.style.cssText = 'position:absolute;top:4px;right:4px;font-size:16px;cursor:pointer;border:none;background:none;color:#1a1a1a;padding:2px;line-height:1;';
      btn.dataset.id = id;
      btn.dataset.idx = idx;
      btn.textContent = savedIds.has(id) ? '\\u2713 saved' : '\\uD83D\\uDD16';
      btn.addEventListener('click', (function(cardData, itemId, button) {{
        return async function() {{
          var st = getStore();
          var exists = st.items.findIndex(function(i){{ return i.id === itemId; }});
          if (exists >= 0) {{
            st.items.splice(exists, 1);
            button.textContent = '\\uD83D\\uDD16';
          }} else {{
            st.items.push({{
              id: itemId,
              title: cardData.title,
              link: cardData.link,
              source: cardData.source,
              section: cardData.section,
              summary: cardData.summary,
              newsletter_date: '{date_str}',
              saved_at: new Date().toISOString()
            }});
            button.textContent = '\\u2713 saved';
          }}
          saveStore(st);
          updateExportBtn();
        }};
      }})(c, id, btn));
      c.el.appendChild(btn);
    }}
    updateExportBtn();
  }}

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}})();
</script>
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

    # Build learnings section if available
    learnings_section = ""
    learnings_path = SITE_DIR / "learnings.json"
    if learnings_path.exists():
        try:
            learnings = json.loads(learnings_path.read_text())
            l_content = learnings.get("content_html", "")
            l_count = learnings.get("based_on_count", 0)
            l_date = learnings.get("generated_at", "")[:10]
            if l_content:
                learnings_section = f"""
    <div class="learnings" style="background: #fffdf7; padding: 28px; margin-bottom: 28px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); border: 1px solid #e0ddd5; border-left: 4px solid #e67e22;">
      <h2 style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 2.5px; color: #1a1a1a; margin-bottom: 14px; border-bottom: 2px solid #1a1a1a; display: inline-block; padding-bottom: 3px;">Learnings from Your Likes</h2>
      <div style="font-size: 15px; color: #444; line-height: 1.8; font-family: 'Times New Roman', Times, Georgia, serif;">{l_content}</div>
      <div style="font-size: 11px; color: #999; margin-top: 12px; font-style: italic;">Based on {l_count} liked items &middot; Generated {l_date}</div>
    </div>"""
        except Exception:
            pass

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Briefing</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="alternate" type="application/rss+xml" title="Daily Briefing RSS" href="feed.xml">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Times New Roman', Times, Georgia, serif; background: #f5f0e8; color: #1a1a1a; min-height: 100vh; }}
  .header {{ background: #fffdf7; color: #1a1a1a; padding: 56px 24px 40px; text-align: center; border-bottom: 3px double #1a1a1a; }}
  .header .kicker {{ font-size: 11px; text-transform: uppercase; letter-spacing: 3px; color: #888; margin-bottom: 10px; }}
  .header h1 {{ font-size: 44px; font-weight: 700; letter-spacing: -1px; margin-bottom: 8px; font-family: 'Times New Roman', Times, Georgia, serif; line-height: 1.1; }}
  .header p {{ font-size: 15px; font-style: italic; color: #666; max-width: 400px; margin: 0 auto; line-height: 1.5; }}
  .rss-btn {{ display: inline-block; margin-top: 24px; padding: 10px 28px; background: #1a1a1a; color: #fffdf7; text-decoration: none; font-size: 12px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; font-family: 'Times New Roman', Times, serif; transition: background 0.2s; }}
  .rss-btn:hover {{ background: #333; }}
  .content {{ max-width: 640px; margin: 0 auto; padding: 36px 20px; }}
  .latest {{ background: #fffdf7; padding: 28px; margin-bottom: 28px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); border: 1px solid #e0ddd5; }}
  .latest h2 {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 2.5px; color: #1a1a1a; margin-bottom: 14px; border-bottom: 2px solid #1a1a1a; display: inline-block; padding-bottom: 3px; }}
  .latest .date-label {{ font-size: 22px; font-weight: 600; color: #1a1a1a; margin-bottom: 16px; font-style: italic; }}
  .read-btn {{ display: inline-block; padding: 10px 22px; background: #1a1a1a; color: #fffdf7; text-decoration: none; font-size: 12px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; font-family: 'Times New Roman', Times, serif; }}
  .read-btn:hover {{ background: #333; }}
  .archive {{ background: #fffdf7; padding: 28px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); border: 1px solid #e0ddd5; }}
  .archive h2 {{ font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 2.5px; color: #1a1a1a; margin-bottom: 18px; border-bottom: 2px solid #1a1a1a; display: inline-block; padding-bottom: 3px; }}
  .archive ul {{ list-style: none; }}
  .archive li {{ padding: 10px 0; border-bottom: 1px solid #e0ddd5; }}
  .archive li:last-child {{ border-bottom: none; }}
  .archive a {{ color: #1a1a1a; text-decoration: none; font-size: 16px; }}
  .archive a:hover {{ color: #555; border-bottom: 1px solid #1a1a1a; }}
  .no-items {{ color: #888; font-style: italic; font-size: 14px; }}
  .footer {{ text-align: center; padding: 36px 20px; font-size: 11px; color: #aaa; letter-spacing: 1px; text-transform: uppercase; }}
</style>
</head>
<body>
<div class="header">
  <div class="kicker">Est. 2025 &middot; Automated Daily Intelligence</div>
  <h1>Daily Briefing</h1>
  <p>Weather, news, YouTube &amp; AI security &mdash; delivered daily.</p>
  <a href="feed.xml" class="rss-btn">Subscribe via RSS</a>
</div>
<div class="content">
  {latest_section}
  {learnings_section}
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

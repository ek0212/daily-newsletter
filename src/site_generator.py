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
        title = f"The Midtown Briefing - {data.get('date', date_str)}"
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
    <title>The Midtown Briefing</title>
    <link>{SITE_URL}</link>
    <description>The Midtown Briefing: weather, news, YouTube, and AI security, delivered daily.</description>
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
    """Self-contained HTML page for a single newsletter post."""
    display_date = data.get("date", date_str)
    email_html = _strip_email_wrapper(email_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Midtown Briefing &mdash; {display_date}</title>
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif; background: #f5f0e8; color: #1c1710; font-weight: 300; -webkit-font-smoothing: antialiased; }}
  a {{ color: #3d6b4f; text-decoration: none; }}
  a:hover {{ color: #8b4a3c; }}
  .shell-nav {{ position: sticky; top: 0; z-index: 20; background: #f5f0e8; border-bottom: 1px solid #ede5d5; display: flex; align-items: center; justify-content: space-between; padding: 14px 32px; font-weight: 500; font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; height: 64px; }}
  .shell-nav .brand {{ font-weight: 600; font-size: 20px; letter-spacing: 0; text-transform: none; color: #3d6b4f; }}
  .shell-nav .actions {{ display: flex; gap: 10px; align-items: center; }}
  .shell-nav .actions a, .shell-nav .actions button {{ background: transparent; border: 1px solid #ede5d5; padding: 7px 14px; font-family: inherit; font-weight: 500; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; cursor: pointer; color: #4a3f30; border-radius: 99px; text-decoration: none; }}
  .shell-nav .actions a:hover, .shell-nav .actions button:hover {{ background: #3d6b4f; color: #f5f0e8; border-color: #3d6b4f; }}
  .email-wrap {{ max-width: 700px; margin: 0 auto 60px; background: #faf7f0; overflow-x: hidden; }}
  @media (max-width: 760px) {{ .shell-nav {{ padding: 12px 16px; }} .shell-nav .brand {{ font-size: 16px; }} .shell-nav .actions {{ gap: 6px; }} .shell-nav .actions a, .shell-nav .actions button {{ padding: 5px 10px; font-size: 10px; }} }}
</style>
</head>
<body>
<nav class="shell-nav">
  <a class="brand" href="../index.html">The Midtown Briefing</a>
  <div class="actions">
    <a href="../index.html">Archive</a>
    <button onclick="window._openStash()">My Stash</button>
  </div>
</nav>
<div class="email-wrap">
{email_html}
</div>
<style>
  .save-btn {{ background:transparent; border:1px solid #ede5d5; width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; font-size:14px; color:#3d6b4f; padding:0; border-radius:99px; transition:transform 0.12s ease, background 0.12s, color 0.12s; vertical-align:middle; line-height:1; flex-shrink:0; }}
  .save-btn:hover {{ background:#d4e6da; transform:scale(1.08); }}
  .save-btn.saved {{ background:#3d6b4f; color:#f5f0e8; border-color:#3d6b4f; }}
  .login-bar {{ position:fixed; top:0; right:0; z-index:10000; padding:10px 16px; font-family:'DM Sans',-apple-system,sans-serif; font-size:13px; display:flex; gap:8px; align-items:center; background:rgba(250,247,240,0.97); border-bottom-left-radius:6px; box-shadow:0 2px 12px rgba(0,0,0,0.08); backdrop-filter:blur(8px); }}
  .login-bar input {{ font-family:inherit; font-size:12px; padding:6px 10px; border:1px solid #ede5d5; background:#faf7f0; border-radius:4px; }}
  .login-bar input:focus {{ outline:2px solid #3d6b4f; outline-offset:-2px; }}
  .login-bar button {{ font-family:inherit; font-size:11px; padding:6px 14px; background:#3d6b4f; color:#f5f0e8; border:none; cursor:pointer; letter-spacing:0.14em; text-transform:uppercase; border-radius:99px; font-weight:500; transition:background 0.2s; }}
  .login-bar button:hover {{ background:#1c1710; }}
  .stash-overlay {{ position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(26,22,40,0.55); backdrop-filter:blur(3px); z-index:9999; display:none; justify-content:center; align-items:flex-start; padding-top:5vh; }}
  .stash-overlay.open {{ display:flex; }}
  .stash-panel {{ background:#f5f0e8; width:92%; max-width:580px; max-height:88vh; overflow-y:auto; font-family:'DM Sans',-apple-system,sans-serif; box-shadow:0 24px 60px rgba(26,22,40,0.32); position:relative; border:1px solid #ede5d5; border-radius:6px; }}
  .stash-header {{ padding:24px 24px 18px; border-bottom:1px solid #ede5d5; position:sticky; top:0; background:#f5f0e8; z-index:1; display:flex; justify-content:space-between; align-items:center; }}
  .stash-header h2 {{ font-size:22px; font-weight:600; color:#1c1710; margin:0; }}
  .stash-header .stash-count {{ font-size:12px; color:#8a7a60; margin-top:4px; font-weight:400; }}
  .stash-close {{ font-size:16px; cursor:pointer; background:transparent; border:1px solid #ede5d5; color:#4a3f30; width:30px; height:30px; border-radius:99px; display:flex; align-items:center; justify-content:center; transition:background 0.15s; }}
  .stash-close:hover {{ background:#3d6b4f; color:#f5f0e8; }}
  .stash-body {{ padding:0 24px; }}
  .stash-date-group {{ margin-top:0; }}
  .stash-date-label {{ font-size:10.5px; text-transform:uppercase; letter-spacing:0.16em; font-weight:500; color:#3d6b4f; padding:18px 0 8px; border-bottom:1px solid #ede5d5; }}
  .stash-item {{ padding:14px 0; border-bottom:1px solid #ede5d5; display:flex; align-items:flex-start; gap:12px; }}
  .stash-item:last-child {{ border-bottom:none; }}
  .stash-item input[type=checkbox] {{ margin-top:4px; accent-color:#3d6b4f; flex-shrink:0; width:16px; height:16px; cursor:pointer; }}
  .stash-item-content {{ flex:1; min-width:0; }}
  .stash-item-text {{ font-size:14px; color:#1c1710; line-height:1.65; font-weight:400; }}
  .stash-item-meta {{ display:flex; align-items:center; gap:6px; margin-top:5px; font-size:10.5px; color:#8a7a60; letter-spacing:0.1em; text-transform:uppercase; }}
  .stash-item-section {{ text-transform:uppercase; letter-spacing:0.12em; font-weight:500; font-size:9.5px; padding:2px 8px; border:1px solid #ede5d5; border-radius:99px; color:#3d6b4f; }}
  .stash-item-section.news {{ color:#8b4a3c; border-color:#8b4a3c; }}
  .stash-item-section.youtube {{ color:#1a1628; border-color:#1a1628; }}
  .stash-item-section.ai_security {{ color:#3d6b4f; border-color:#3d6b4f; }}
  .stash-item-section.other {{ color:#8a7a60; border-color:#ede5d5; }}
  .stash-delete {{ background:none; border:none; color:#ede5d5; font-size:16px; cursor:pointer; padding:2px 4px; flex-shrink:0; transition:color 0.15s; line-height:1; margin-top:2px; }}
  .stash-delete:hover {{ color:#8b4a3c; }}
  .stash-footer {{ padding:20px 24px 24px; border-top:1px solid #ede5d5; position:sticky; bottom:0; background:#f5f0e8; z-index:1; }}
  .stash-prompt-label {{ font-size:10.5px; text-transform:uppercase; letter-spacing:0.16em; font-weight:500; color:#8a7a60; display:block; margin-bottom:8px; }}
  .stash-prompt {{ width:100%; font-family:'DM Sans',-apple-system,sans-serif; font-size:14px; padding:11px 13px; border:1px solid #ede5d5; background:#faf7f0; resize:vertical; line-height:1.5; color:#1c1710; border-radius:4px; }}
  .stash-prompt:focus {{ outline:2px solid #3d6b4f; outline-offset:-2px; }}
  .stash-actions {{ margin-top:14px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  .stash-actions button {{ font-family:'DM Sans',-apple-system,sans-serif; font-size:11px; padding:9px 16px; cursor:pointer; border:none; letter-spacing:0.14em; text-transform:uppercase; font-weight:500; border-radius:99px; transition:background 0.2s, color 0.2s; }}
  .stash-actions .primary {{ background:#3d6b4f; color:#f5f0e8; }}
  .stash-actions .primary:hover {{ background:#1c1710; }}
  .stash-actions .primary:disabled {{ background:#ede5d5; color:#8a7a60; cursor:wait; }}
  .stash-actions .secondary {{ background:transparent; color:#4a3f30; border:1px solid #ede5d5; }}
  .stash-actions .secondary:hover {{ background:#3d6b4f; color:#f5f0e8; border-color:#3d6b4f; }}
  .stash-actions .divider {{ flex:1; }}
  .script-output {{ margin-top:16px; padding:18px; background:#faf7f0; border:1px solid #ede5d5; font-size:15px; line-height:1.85; color:#4a3f30; white-space:pre-wrap; border-radius:4px; max-height:320px; overflow-y:auto; font-weight:300; }}
  .copy-script-btn {{ display:inline-block; margin-bottom:10px; padding:9px 16px; background:#3d6b4f; color:#f5f0e8; border:none; font-family:'DM Sans',-apple-system,sans-serif; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; font-weight:500; cursor:pointer; border-radius:99px; transition:background 0.2s; }}
  .copy-script-btn:hover {{ background:#1c1710; }}
  .stash-empty {{ font-size:15px; color:#8a7a60; padding:40px 24px; text-align:center; line-height:1.6; font-weight:300; }}
  .spinner {{ display:inline-block; width:14px; height:14px; border:2px solid rgba(245,240,232,0.3); border-top-color:#f5f0e8; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-left:8px; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
<script>
(function() {{
  var STORAGE_KEY = 'newsletter_user';
  var GEMINI_KEY_STORAGE = 'newsletter_gemini_key';
  var currentUser = null;
  var savedKeys = new Set();
  var allSaved = [];
  var nextId = 1;

  // --- Storage helpers ---
  function getStoredData() {{
    try {{
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    }} catch(e) {{ return null; }}
  }}

  function saveStoredData(data) {{
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  }}

  async function hashPassword(password) {{
    var enc = new TextEncoder().encode(password);
    var buf = await crypto.subtle.digest('SHA-256', enc);
    return Array.from(new Uint8Array(buf)).map(function(b) {{ return b.toString(16).padStart(2, '0'); }}).join('');
  }}

  function detectSection(el) {{
    var node = el;
    while (node && node !== document.body) {{
      var ds = node.dataset && node.dataset.section;
      if (ds) return ds;
      node = node.parentElement;
    }}
    return 'other';
  }}

  function getDateFromURL() {{
    var m = window.location.pathname.match(/(\\d{{4}}-\\d{{2}}-\\d{{2}})/);
    return m ? m[1] : '{date_str}';
  }}

  // --- Auth (localStorage) ---
  function loadSession() {{
    var data = getStoredData();
    if (data && data.session_active) {{
      currentUser = data.username;
      allSaved = data.saved || data.likes || [];
      nextId = allSaved.reduce(function(mx, l) {{ return Math.max(mx, l.id + 1); }}, 1);
      savedKeys = new Set(allSaved.map(function(l) {{ return l.source_key || l.bullet_text || ''; }}));
    }} else {{
      currentUser = null;
      allSaved = [];
      savedKeys = new Set();
    }}
  }}

  function renderLoginBar() {{
    var existing = document.querySelector('.login-bar');
    if (existing) existing.remove();
    var bar = document.createElement('div');
    bar.className = 'login-bar';
    if (currentUser) {{
      bar.innerHTML = '<span style="font-weight:500;color:#1c1710;">' + currentUser + '</span>'
        + '<button onclick="window._openStash()">My Stash</button>'
        + '<button onclick="window._logout()">Sign Out</button>';
    }} else {{
      bar.innerHTML = '<input id="lb-user" placeholder="username">'
        + '<input id="lb-pass" type="password" placeholder="password">'
        + '<button onclick="window._login()">Sign In</button>'
        + '<button onclick="window._register()">Register</button>';
    }}
    document.body.appendChild(bar);
  }}

  window._login = async function() {{
    var u = document.getElementById('lb-user').value.trim();
    var p = document.getElementById('lb-pass').value;
    if (!u || !p) {{ alert('Username and password required'); return; }}
    var data = getStoredData();
    if (!data || data.username !== u) {{ alert('User not found. Please register first.'); return; }}
    var hash = await hashPassword(p);
    if (data.password_hash !== hash) {{ alert('Incorrect password'); return; }}
    data.session_active = true;
    saveStoredData(data);
    loadSession();
    renderLoginBar();
    refreshAllButtons();
  }};

  window._register = async function() {{
    var u = document.getElementById('lb-user').value.trim();
    var p = document.getElementById('lb-pass').value;
    if (!u || !p) {{ alert('Username and password required'); return; }}
    var existing = getStoredData();
    if (existing && existing.username === u) {{ alert('User already exists. Please login.'); return; }}
    var hash = await hashPassword(p);
    var data = {{ version: 1, username: u, password_hash: hash, saved: [], session_active: true }};
    saveStoredData(data);
    loadSession();
    renderLoginBar();
    refreshAllButtons();
  }};

  window._logout = function() {{
    var data = getStoredData();
    if (data) {{
      data.session_active = false;
      saveStoredData(data);
    }}
    currentUser = null;
    allSaved = [];
    savedKeys = new Set();
    renderLoginBar();
    refreshAllButtons();
  }};

  // --- Saved sources (localStorage) ---
  function loadSaved() {{
    var data = getStoredData();
    if (!data || !data.session_active) {{ allSaved = []; savedKeys = new Set(); return; }}
    allSaved = data.saved || data.likes || [];
    nextId = allSaved.reduce(function(mx, l) {{ return Math.max(mx, l.id + 1); }}, 1);
    savedKeys = new Set(allSaved.map(function(l) {{ return l.source_key || l.bullet_text || ''; }}));
  }}

  function saveSaved() {{
    var data = getStoredData();
    if (!data) return;
    data.saved = allSaved;
    saveStoredData(data);
  }}

  function refreshAllButtons() {{
    document.querySelectorAll('.save-btn').forEach(function(btn) {{
      var key = btn.dataset.sourceKey;
      if (savedKeys.has(key)) {{
        btn.classList.add('saved');
        btn.innerHTML = '\u2605';
        btn.title = 'Saved';
      }} else {{
        btn.classList.remove('saved');
        btn.innerHTML = '\u2606';
        btn.title = 'Save to stash';
      }}
    }});
  }}

  function toggleSave(btn, sourceKey, title, link, summary, section) {{
    if (!currentUser) {{ alert('Please login first'); return; }}
    if (savedKeys.has(sourceKey)) {{
      allSaved = allSaved.filter(function(l) {{ return l.source_key !== sourceKey; }});
      savedKeys.delete(sourceKey);
      btn.classList.remove('saved');
      btn.innerHTML = '\u2606';
      btn.title = 'Save to stash';
    }} else {{
      allSaved.push({{
        id: nextId++,
        source_key: sourceKey,
        title: title,
        link: link,
        summary: summary,
        section: section,
        newsletter_date: getDateFromURL(),
        created_at: new Date().toISOString()
      }});
      savedKeys.add(sourceKey);
      btn.classList.add('saved');
      btn.innerHTML = '\u2605';
      btn.title = 'Saved';
    }}
    saveSaved();
  }}

  // --- Add bookmark icon next to each source title ---
  function addSaveButtons() {{
    // Find items inside data-section containers (news, youtube, ai_security)
    var sections = document.querySelectorAll('[data-section]');
    sections.forEach(function(sec) {{
      // Match padded items and card items
      var items = sec.querySelectorAll('div[style*="padding: 16px 0"], div[style*="padding: 14px 0"], div[style*="padding: 20px 22px"]');
      items.forEach(function(card) {{
        var titleEl = card.querySelector('a[href]');
        if (!titleEl) return;
        var title = titleEl.textContent.trim();
        var link = titleEl.getAttribute('href') || '';
        var section = detectSection(card);

        // Get summary text for storage
        var summaryEl = card.querySelector('div[style*="font-size: 14.5px"], div[style*="font-size: 15px"]');
        var summary = summaryEl ? summaryEl.textContent.trim() : '';
        if (summary.length > 400) summary = summary.substring(0, 400) + '...';

        var sourceKey = link || title;
        var isSaved = savedKeys.has(sourceKey);

        var wrapper = document.createElement('span');
        wrapper.style.cssText = 'display:flex;align-items:flex-start;gap:8px;';
        titleEl.parentNode.insertBefore(wrapper, titleEl);
        titleEl.style.flex = '1';
        wrapper.appendChild(titleEl);

        var btn = document.createElement('button');
        btn.className = 'save-btn' + (isSaved ? ' saved' : '');
        btn.dataset.sourceKey = sourceKey;
        btn.innerHTML = isSaved ? '\u2605' : '\u2606';
        btn.title = isSaved ? 'Saved' : 'Save to stash';
        btn.addEventListener('click', function(e) {{
          e.preventDefault();
          e.stopPropagation();
          toggleSave(btn, sourceKey, title, link, summary, section);
        }});
        wrapper.appendChild(btn);
      }});
    }});
  }}

  // --- Stash modal ---
  function formatDateLabel(dateStr) {{
    try {{
      var parts = dateStr.split('-');
      var months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
      return months[parseInt(parts[1],10)-1] + ' ' + parseInt(parts[2],10) + ', ' + parts[0];
    }} catch(e) {{ return dateStr; }}
  }}

  function sectionLabel(s) {{
    var map = {{'news':'News','youtube':'YouTube','ai_security':'AI Security','other':'Other'}};
    return map[s] || s;
  }}

  window._openStash = function() {{
    if (!currentUser) return;
    loadSaved();
    var overlay = document.getElementById('stash-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'stash-overlay';
    overlay.className = 'stash-overlay open';
    var panel = document.createElement('div');
    panel.className = 'stash-panel';

    var html = '<div class="stash-header">'
      + '<h2>My Stash</h2>'
      + '<button class="stash-close" onclick="document.getElementById(\\x27stash-overlay\\x27).remove()">&times;</button>'
      + '</div>';

    if (allSaved.length === 0) {{
      html += '<div class="stash-empty">Nothing saved yet. Tap the star next to any article, video, or paper.</div>';
    }} else {{
      html += '';

      // Group by newsletter_date, sorted newest first
      var groups = {{}};
      allSaved.forEach(function(item) {{
        var d = item.newsletter_date || 'Unknown';
        if (!groups[d]) groups[d] = [];
        groups[d].push(item);
      }});
      var sortedDates = Object.keys(groups).sort(function(a,b) {{ return b.localeCompare(a); }});

      html += '<div class="stash-body" id="stash-items">';
      sortedDates.forEach(function(date) {{
        html += '<div class="stash-date-group">';
        html += '<div class="stash-date-label">' + formatDateLabel(date) + '</div>';
        groups[date].forEach(function(item) {{
          var titleDisplay = (item.title || item.article_title || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          var summaryPreview = (item.summary || item.bullet_text || '').replace(/<[^>]*>/g, '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          if (summaryPreview.length > 150) summaryPreview = summaryPreview.substring(0, 150) + '...';
          var linkUrl = (item.link || '').replace(/"/g, '&quot;');
          var escapedTitle = titleDisplay.replace(/"/g, '&quot;');
          html += '<div class="stash-item" data-item-id="' + item.id + '">'
            + '<input type="checkbox" value="' + item.id + '" data-title="' + escapedTitle + '" data-summary="' + summaryPreview.replace(/"/g, '&quot;') + '">'
            + '<div class="stash-item-content">'
            + '<div class="stash-item-text">' + (linkUrl ? '<a href="' + linkUrl + '" target="_blank" style="color:#1c1710;text-decoration:none;border-bottom:1px solid #ede5d5;">' + titleDisplay + '</a>' : titleDisplay) + '</div>'
            + (summaryPreview ? '<div style="font-size:12.5px;color:#8a7a60;line-height:1.5;margin-top:4px;font-weight:300;">' + summaryPreview + '</div>' : '')
            + '<div class="stash-item-meta">'
            + '<span class="stash-item-section ' + (item.section || 'other') + '">' + sectionLabel(item.section) + '</span>'
            + '</div>'
            + '</div>'
            + '<button class="stash-delete" onclick="window._deleteItem(' + item.id + ',this)" title="Remove">&times;</button>'
            + '</div>';
        }});
        html += '</div>';
      }});
      html += '</div>';

      var hasKey = !!localStorage.getItem(GEMINI_KEY_STORAGE);
      html += '<div class="stash-footer">'
        + '<label class="stash-prompt-label">Custom prompt (optional)</label>'
        + '<textarea id="custom-prompt" class="stash-prompt" rows="2" placeholder="e.g. Make it conversational, focus on practical takeaways, explain it simply..."></textarea>';
      if (!hasKey) {{
        html += '<div style="margin-top:12px;padding:12px;background:#faf7f0;border:1px solid #ede5d5;border-radius:4px;">'
          + '<label class="stash-prompt-label" style="color:#8b4a3c;">Gemini API Key (saved locally, never uploaded)</label>'
          + '<div style="display:flex;gap:6px;">'
          + '<input id="gemini-key-input" type="password" class="stash-prompt" style="flex:1;padding:6px 10px;" placeholder="Paste your Gemini API key">'
          + '<button class="primary" style="font-size:11px;padding:6px 14px;" onclick="window._saveGeminiKey()">Save</button>'
          + '</div></div>';
      }} else {{
        html += '<div style="margin-top:8px;font-size:11px;color:#8a7a60;font-weight:400;">API key saved &middot; <a href="#" onclick="localStorage.removeItem(\\x27' + GEMINI_KEY_STORAGE + '\\x27);window._openStash();return false;" style="color:#3d6b4f;">Change key</a></div>';
      }}
      html += '<div class="stash-actions">'
        + '<button class="secondary" onclick="window._stashSelectAll()">Select All</button>'
        + '<button class="secondary" onclick="window._stashSelectNone()">Select None</button>'
        + '<button class="secondary" onclick="window._copySelection(this)">Copy Selection</button>'
        + '<span class="divider"></span>'
        + '<button class="primary" id="generate-script-btn" onclick="window._generateScript()">Generate Script</button>'
        + '</div>'
        + '<div id="script-result"></div>'
        + '</div>';
    }}

    panel.innerHTML = html;
    overlay.appendChild(panel);
    overlay.addEventListener('click', function(e) {{
      if (e.target === overlay) overlay.remove();
    }});
    document.body.appendChild(overlay);
  }};

  window._stashSelectAll = function() {{
    document.querySelectorAll('#stash-items input[type=checkbox]').forEach(function(cb) {{ cb.checked = true; }});
  }};

  window._stashSelectNone = function() {{
    document.querySelectorAll('#stash-items input[type=checkbox]').forEach(function(cb) {{ cb.checked = false; }});
  }};

  window._deleteItem = function(itemId, btnEl) {{
    allSaved = allSaved.filter(function(l) {{ return l.id !== itemId; }});
    saveSaved();
    savedKeys = new Set(allSaved.map(function(l) {{ return l.source_key || l.bullet_text || ''; }}));
    var row = btnEl.closest('.stash-item');
    if (row) row.remove();
    refreshAllButtons();
    if (allSaved.length === 0) {{
      window._openStash();
    }}
  }};

  window._copySelection = function(btn) {{
    var checked = document.querySelectorAll('#stash-items input[type=checkbox]:checked');
    if (checked.length === 0) {{ alert('Select at least one source'); return; }}
    var lines = [];
    var currentDate = '';
    checked.forEach(function(cb) {{
      var item = allSaved.find(function(l) {{ return l.id === parseInt(cb.value); }});
      if (!item) return;
      var d = item.newsletter_date || '';
      if (d !== currentDate) {{
        if (lines.length > 0) lines.push('');
        lines.push(d);
        lines.push('');
        currentDate = d;
      }}
      var title = item.title || item.article_title || 'Untitled';
      var sectionName = (item.section || '').replace('_', ' ');
      lines.push(title + (sectionName ? ' [' + sectionName + ']' : ''));
      if (item.link) lines.push(item.link);
      if (item.summary) {{
        var clean = (item.summary || '').replace(/<[^>]*>/g, '');
        if (clean.length > 0) lines.push(clean);
      }}
      lines.push('');
    }});
    var text = lines.join('\\n').trim();
    navigator.clipboard.writeText(text).then(function() {{
      btn.textContent = 'Copied!';
      setTimeout(function() {{ btn.textContent = 'Copy Selection'; }}, 2000);
    }});
  }};

  window._saveGeminiKey = function() {{
    var key = (document.getElementById('gemini-key-input') || {{}}).value || '';
    key = key.trim();
    if (!key) {{ alert('Please paste your API key'); return; }}
    localStorage.setItem(GEMINI_KEY_STORAGE, key);
    window._openStash();
  }};

  window._generateScript = async function() {{
    var checked = document.querySelectorAll('#stash-items input[type=checkbox]:checked');
    if (checked.length === 0) {{ alert('Select at least one source'); return; }}

    var apiKey = localStorage.getItem(GEMINI_KEY_STORAGE) || '';
    if (!apiKey) {{ alert('Please save your Gemini API key first'); return; }}

    var sources = [];
    checked.forEach(function(cb) {{
      sources.push({{ title: cb.dataset.title || '', summary: cb.dataset.summary || '' }});
    }});
    var customPrompt = (document.getElementById('custom-prompt') || {{}}).value || '';

    var prompt = 'You are an educational content writer. The user saved these sources from a daily newsletter:\\n\\n';
    sources.forEach(function(s) {{ prompt += '- ' + s.title + (s.summary ? ': ' + s.summary : '') + '\\n'; }});
    prompt += '\\nYour task:\\n1. Research each topic in more depth.\\n2. Write a 2-3 minute spoken script (350-500 words) that explains these topics in an educational, engaging way.\\n3. Be conversational but informative.\\n4. Add context, background, and why it matters.\\n5. Start with a hook, end with a takeaway.';
    if (customPrompt) {{ prompt += '\\n\\nAdditional instructions: ' + customPrompt; }}
    prompt += '\\n\\nReturn ONLY the script text, ready to be read aloud. No stage directions, no markdown.';

    var btn = document.getElementById('generate-script-btn');
    btn.disabled = true;
    btn.innerHTML = 'Generating<span class="spinner"></span>';
    var resultDiv = document.getElementById('script-result');
    resultDiv.innerHTML = '';

    try {{
      var res = await fetch('https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key=' + encodeURIComponent(apiKey), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ contents: [{{ parts: [{{ text: prompt }}] }}] }})
      }});
      var data = await res.json();
      if (data.error) throw new Error(data.error.message || 'API error');
      var script = data.candidates[0].content.parts[0].text;
      resultDiv.innerHTML = '<button class="copy-script-btn" onclick="window._copyScript(this)">Copy Script</button>'
        + '<div class="script-output" id="script-text">' + script.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
    }} catch(e) {{
      resultDiv.innerHTML = '<div class="script-output" style="color:#8b4a3c;">Error: ' + e.message + '</div>';
    }}

    btn.disabled = false;
    btn.textContent = 'Generate Script';
  }};

  window._copyScript = function(btn) {{
    var text = document.getElementById('script-text').innerText;
    navigator.clipboard.writeText(text).then(function() {{
      btn.textContent = 'Copied!';
      setTimeout(function() {{ btn.textContent = 'Copy Script'; }}, 2000);
    }});
  }};

  // --- Init ---
  function init() {{
    loadSession();
    renderLoginBar();
    addSaveButtons();
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
        archive_items += f"""<div class="archive-row">
        <span class="date">{display}</span>
        <a class="go" href="posts/{d}.html">Read</a>
      </div>\n"""

    if not archive_items:
        archive_items = '<div class="no-items">No newsletters yet.</div>'

    # Latest newsletter summary
    latest_section = ""
    if latest_data and latest_date:
        display_date = latest_data.get("date", latest_date)
        latest_section = f"""
    <section class="hero-latest">
      <div>
        <div class="label">Latest Issue</div>
        <div class="hero-date">{display_date}</div>
      </div>
      <div>
        <p class="hero-desc">Weather, news, YouTube, and AI security, curated daily.</p>
        <a href="posts/{latest_date}.html" class="btn btn-primary">Read the Issue</a>
      </div>
    </section>"""

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
    <section class="learnings">
      <div class="section-head">
        <span class="rule"></span>
        <h2>Learnings</h2>
        <span class="rule"></span>
      </div>
      <div class="learnings-body">{l_content}</div>
      <div class="learnings-meta">Based on {l_count} saved sources &middot; Generated {l_date}</div>
    </section>"""
        except Exception:
            pass

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Midtown Briefing</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="alternate" type="application/rss+xml" title="The Midtown Briefing RSS" href="feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif; background: #f5f0e8; color: #1c1710; font-weight: 300; font-size: 16px; line-height: 1.75; -webkit-font-smoothing: antialiased; min-height: 100vh; }}
  a {{ color: #3d6b4f; text-decoration: none; }}
  a:hover {{ color: #8b4a3c; }}
  .shell-nav {{ position: sticky; top: 0; z-index: 20; background: #f5f0e8; border-bottom: 1px solid #ede5d5; display: flex; align-items: center; justify-content: space-between; padding: 14px 32px; font-weight: 500; font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; height: 64px; }}
  .shell-nav .brand {{ font-weight: 600; font-size: 20px; letter-spacing: 0; text-transform: none; color: #3d6b4f; }}
  .shell-nav .actions {{ display: flex; gap: 12px; align-items: center; }}
  .shell-nav .actions a {{ background: transparent; border: 1px solid #ede5d5; padding: 7px 14px; font-weight: 500; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: #4a3f30; border-radius: 99px; }}
  .shell-nav .actions a:hover {{ background: #3d6b4f; color: #f5f0e8; border-color: #3d6b4f; }}
  .paper {{ max-width: 900px; margin: 0 auto; padding: 32px 48px 80px; }}
  @media (max-width: 760px) {{ .paper {{ padding: 16px 22px 60px; }} html, body {{ font-size: 15px; }} .shell-nav {{ padding: 12px 16px; }} .shell-nav .brand {{ font-size: 16px; }} }}
  .mast {{ border-top: 1px solid #ede5d5; border-bottom: 1px solid #ede5d5; padding: 36px 0 32px; margin-bottom: 32px; text-align: center; }}
  .mast-title {{ font-weight: 700; font-size: clamp(40px, 7vw, 72px); line-height: 1.0; letter-spacing: -0.015em; margin: 4px 0 12px; color: #1c1710; }}
  .mast-title em {{ font-style: normal; color: #3d6b4f; }}
  .mast-meta {{ font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: 0.16em; color: #8a7a60; margin-top: 14px; }}
  .hero-latest {{ border-top: 1px solid #ede5d5; border-bottom: 1px solid #ede5d5; padding: 32px 0; margin: 24px 0 36px; display: grid; grid-template-columns: 1fr 2fr; gap: 36px; align-items: center; }}
  @media (max-width: 760px) {{ .hero-latest {{ grid-template-columns: 1fr; gap: 16px; }} }}
  .hero-latest .label {{ font-weight: 500; font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase; color: #3d6b4f; }}
  .hero-date {{ font-weight: 600; font-size: 28px; line-height: 1.2; margin-top: 8px; color: #1c1710; }}
  .hero-desc {{ font-size: 16.5px; color: #4a3f30; line-height: 1.75; margin: 0 0 16px; font-weight: 300; }}
  .btn {{ font-weight: 500; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; background: transparent; border: 1px solid #ede5d5; padding: 9px 16px; cursor: pointer; color: #4a3f30; border-radius: 99px; display: inline-block; }}
  .btn:hover {{ background: #3d6b4f; color: #f5f0e8; border-color: #3d6b4f; }}
  .btn-primary {{ background: #3d6b4f; color: #f5f0e8; border-color: #3d6b4f; }}
  .btn-primary:hover {{ background: #1c1710; border-color: #1c1710; }}
  .section-head {{ display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 24px; margin-bottom: 24px; text-align: center; }}
  .section-head .rule {{ height: 1px; background: #ede5d5; }}
  .section-head h2 {{ font-weight: 700; font-size: 32px; margin: 0; letter-spacing: -0.015em; color: #1c1710; white-space: nowrap; }}
  .archive-row {{ display: grid; grid-template-columns: 1fr auto; gap: 22px; padding: 16px 0; border-bottom: 1px solid #ede5d5; align-items: center; }}
  .archive-row .date {{ font-weight: 400; font-size: 16px; color: #4a3f30; }}
  .archive-row a.go {{ font-weight: 500; font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; border: 1px solid #ede5d5; padding: 7px 14px; border-radius: 99px; color: #4a3f30; }}
  .archive-row a.go:hover {{ background: #3d6b4f; color: #f5f0e8; border-color: #3d6b4f; }}
  .no-items {{ color: #8a7a60; font-size: 14px; font-weight: 300; padding: 20px 0; }}
  .learnings {{ margin-top: 56px; }}
  .learnings-body {{ font-size: 15px; color: #4a3f30; line-height: 1.85; font-weight: 300; }}
  .learnings-meta {{ font-size: 11px; color: #8a7a60; margin-top: 12px; font-weight: 400; letter-spacing: 0.1em; text-transform: uppercase; }}
  .footer {{ margin-top: 64px; border-top: 1px solid #ede5d5; padding: 24px 0; text-align: center; font-size: 10.5px; color: #8a7a60; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 500; }}
</style>
</head>
<body>
<nav class="shell-nav">
  <span class="brand">The Midtown Briefing</span>
  <div class="actions">
    <a href="feed.xml">RSS</a>
  </div>
</nav>
<main class="paper">
  <header class="mast">
    <h1 class="mast-title">The Midtown <em>Briefing</em></h1>
    <div class="mast-meta">Est. 2025 &middot; Daily Intelligence</div>
  </header>
  {latest_section}
  {learnings_section}
  <section>
    <div class="section-head">
      <span class="rule"></span>
      <h2>Back Issues</h2>
      <span class="rule"></span>
    </div>
    <div class="archive">
      {archive_items}
    </div>
  </section>
  <footer class="footer">The Midtown Briefing</footer>
</main>
</body>
</html>"""

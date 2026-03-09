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
<style>
  .like-btn {{ background:none; border:none; cursor:pointer; font-size:16px; padding:0 4px; opacity:0.35; transition:opacity 0.2s, transform 0.15s; vertical-align:middle; }}
  .like-btn:hover {{ opacity:1; transform:scale(1.2); }}
  .like-btn.liked {{ opacity:1; }}
  .login-bar {{ position:fixed; top:0; right:0; z-index:10000; padding:10px 16px; font-family:'Times New Roman',serif; font-size:13px; display:flex; gap:8px; align-items:center; background:rgba(255,253,247,0.97); border-bottom-left-radius:6px; box-shadow:0 2px 12px rgba(0,0,0,0.08); backdrop-filter:blur(8px); }}
  .login-bar input {{ font-family:inherit; font-size:12px; padding:5px 10px; border:1px solid #d0cdc5; background:#faf8f2; }}
  .login-bar button {{ font-family:inherit; font-size:11px; padding:5px 14px; background:#1a1a1a; color:#fffdf7; border:none; cursor:pointer; letter-spacing:0.5px; text-transform:uppercase; transition:background 0.2s; }}
  .login-bar button:hover {{ background:#333; }}
  .stash-overlay {{ position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(26,26,26,0.45); backdrop-filter:blur(3px); z-index:9999; display:none; justify-content:center; align-items:flex-start; padding-top:5vh; }}
  .stash-overlay.open {{ display:flex; }}
  .stash-panel {{ background:#fffdf7; width:92%; max-width:580px; max-height:88vh; overflow-y:auto; font-family:'Times New Roman',Times,Georgia,serif; box-shadow:0 8px 40px rgba(0,0,0,0.18); position:relative; border:1px solid #e0ddd5; }}
  .stash-header {{ padding:28px 32px 20px; border-bottom:3px double #1a1a1a; position:sticky; top:0; background:#fffdf7; z-index:1; }}
  .stash-header h2 {{ font-size:10px; text-transform:uppercase; letter-spacing:3px; font-weight:700; color:#1a1a1a; margin:0; }}
  .stash-header .stash-count {{ font-size:12px; color:#999; font-style:italic; margin-top:4px; }}
  .stash-close {{ position:absolute; top:20px; right:24px; font-size:24px; cursor:pointer; background:none; border:none; color:#aaa; transition:color 0.15s; line-height:1; }}
  .stash-close:hover {{ color:#1a1a1a; }}
  .stash-body {{ padding:0 32px; }}
  .stash-date-group {{ margin-top:0; }}
  .stash-date-label {{ font-size:10px; text-transform:uppercase; letter-spacing:2px; font-weight:700; color:#999; padding:18px 0 8px; border-bottom:1px solid #e8e5de; display:flex; align-items:center; gap:8px; }}
  .stash-date-label::before {{ content:''; flex:1; height:1px; background:linear-gradient(to right, transparent, #e0ddd5); }}
  .stash-date-label::after {{ content:''; flex:1; height:1px; background:linear-gradient(to left, transparent, #e0ddd5); }}
  .stash-item {{ padding:14px 0; border-bottom:1px solid #f0ede6; display:flex; align-items:flex-start; gap:12px; transition:background 0.15s; }}
  .stash-item:last-child {{ border-bottom:none; }}
  .stash-item input[type=checkbox] {{ margin-top:4px; accent-color:#1a1a1a; flex-shrink:0; width:16px; height:16px; cursor:pointer; }}
  .stash-item-content {{ flex:1; min-width:0; }}
  .stash-item-text {{ font-size:14px; color:#333; line-height:1.65; cursor:pointer; }}
  .stash-item-meta {{ display:flex; align-items:center; gap:6px; margin-top:5px; font-size:10.5px; color:#aaa; letter-spacing:0.3px; }}
  .stash-item-source {{ font-style:italic; color:#888; max-width:250px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .stash-item-section {{ text-transform:uppercase; letter-spacing:1px; font-weight:600; font-size:9px; padding:1px 6px; border:1px solid; border-radius:1px; }}
  .stash-item-section.news {{ color:#c0392b; border-color:#c0392b; }}
  .stash-item-section.youtube {{ color:#8e44ad; border-color:#8e44ad; }}
  .stash-item-section.ai_security {{ color:#27ae60; border-color:#27ae60; }}
  .stash-item-section.other {{ color:#888; border-color:#ccc; }}
  .stash-delete {{ background:none; border:none; color:#ccc; font-size:16px; cursor:pointer; padding:2px 4px; flex-shrink:0; transition:color 0.15s; line-height:1; margin-top:2px; }}
  .stash-delete:hover {{ color:#c0392b; }}
  .stash-footer {{ padding:20px 32px 28px; border-top:1px solid #e8e5de; position:sticky; bottom:0; background:#fffdf7; z-index:1; }}
  .stash-prompt-label {{ font-size:10px; text-transform:uppercase; letter-spacing:2px; font-weight:700; color:#999; display:block; margin-bottom:8px; }}
  .stash-prompt {{ width:100%; font-family:'Times New Roman',Times,Georgia,serif; font-size:13.5px; padding:10px 12px; border:1px solid #e0ddd5; background:#faf8f2; resize:vertical; line-height:1.5; color:#333; }}
  .stash-prompt:focus {{ outline:none; border-color:#1a1a1a; }}
  .stash-actions {{ margin-top:14px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  .stash-actions button {{ font-family:'Times New Roman',Times,serif; font-size:11px; padding:8px 18px; cursor:pointer; border:none; letter-spacing:1.5px; text-transform:uppercase; transition:background 0.2s, color 0.2s; }}
  .stash-actions .primary {{ background:#1a1a1a; color:#fffdf7; }}
  .stash-actions .primary:hover {{ background:#333; }}
  .stash-actions .primary:disabled {{ background:#bbb; cursor:wait; }}
  .stash-actions .secondary {{ background:transparent; color:#888; border:1px solid #d0cdc5; }}
  .stash-actions .secondary:hover {{ color:#1a1a1a; border-color:#1a1a1a; }}
  .stash-actions .divider {{ flex:1; }}
  .script-output {{ margin-top:16px; padding:20px; background:#f5f0e8; font-size:14.5px; line-height:1.75; color:#333; white-space:pre-wrap; border-left:3px solid #1a1a1a; }}
  .copy-script-btn {{ display:inline-block; margin-bottom:10px; padding:7px 18px; background:#1a1a1a; color:#fffdf7; border:none; font-family:'Times New Roman',serif; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; cursor:pointer; transition:background 0.2s; }}
  .copy-script-btn:hover {{ background:#333; }}
  .stash-empty {{ font-size:15px; color:#999; font-style:italic; padding:40px 32px; text-align:center; line-height:1.6; }}
  .spinner {{ display:inline-block; width:14px; height:14px; border:2px solid rgba(255,253,247,0.3); border-top-color:#fffdf7; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-left:8px; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
<script>
(function() {{
  var STORAGE_KEY = 'newsletter_user';
  var GEMINI_KEY_STORAGE = 'newsletter_gemini_key';
  var sectionMap = {{'c0392b': 'news', '8e44ad': 'youtube', '27ae60': 'ai_security'}};
  var currentUser = null;
  var likedTexts = new Set();
  var allLikes = [];
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
      var style = node.getAttribute('style') || '';
      for (var color in sectionMap) {{
        if (style.indexOf(color) !== -1) return sectionMap[color];
      }}
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
      allLikes = data.likes || [];
      nextId = allLikes.reduce(function(mx, l) {{ return Math.max(mx, l.id + 1); }}, 1);
      likedTexts = new Set(allLikes.map(function(l) {{ return l.bullet_text; }}));
    }} else {{
      currentUser = null;
      allLikes = [];
      likedTexts = new Set();
    }}
  }}

  function renderLoginBar() {{
    var existing = document.querySelector('.login-bar');
    if (existing) existing.remove();
    var bar = document.createElement('div');
    bar.className = 'login-bar';
    if (currentUser) {{
      bar.innerHTML = '<span>' + currentUser + '</span>'
        + '<button onclick="window._openStash()">My Stash</button>'
        + '<button onclick="window._logout()">Logout</button>';
    }} else {{
      bar.innerHTML = '<input id="lb-user" placeholder="username">'
        + '<input id="lb-pass" type="password" placeholder="password">'
        + '<button onclick="window._login()">Login</button>'
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
    var data = {{ version: 1, username: u, password_hash: hash, likes: [], session_active: true }};
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
    allLikes = [];
    likedTexts = new Set();
    renderLoginBar();
    refreshAllButtons();
  }};

  // --- Likes (localStorage) ---
  function loadLikes() {{
    var data = getStoredData();
    if (!data || !data.session_active) {{ allLikes = []; likedTexts = new Set(); return; }}
    allLikes = data.likes || [];
    nextId = allLikes.reduce(function(mx, l) {{ return Math.max(mx, l.id + 1); }}, 1);
    likedTexts = new Set(allLikes.map(function(l) {{ return l.bullet_text; }}));
  }}

  function saveLikes() {{
    var data = getStoredData();
    if (!data) return;
    data.likes = allLikes;
    saveStoredData(data);
  }}

  function refreshAllButtons() {{
    document.querySelectorAll('.like-btn').forEach(function(btn) {{
      var text = btn.dataset.bulletText;
      if (likedTexts.has(text)) {{
        btn.classList.add('liked');
      }} else {{
        btn.classList.remove('liked');
      }}
    }});
  }}

  function toggleLike(btn, bulletText, articleTitle, section) {{
    if (!currentUser) {{ alert('Please login first'); return; }}
    if (likedTexts.has(bulletText)) {{
      allLikes = allLikes.filter(function(l) {{ return l.bullet_text !== bulletText; }});
      likedTexts.delete(bulletText);
      btn.classList.remove('liked');
    }} else {{
      allLikes.push({{
        id: nextId++,
        bullet_text: bulletText,
        article_title: articleTitle,
        section: section,
        newsletter_date: getDateFromURL(),
        created_at: new Date().toISOString()
      }});
      likedTexts.add(bulletText);
      btn.classList.add('liked');
    }}
    saveLikes();
  }}

  // --- Add thumbs up to each bullet ---
  function addThumbsToSummaries() {{
    var summaryDivs = document.querySelectorAll('.email-wrap div[style*="font-size: 14.5px"]');
    summaryDivs.forEach(function(div) {{
      var html = div.innerHTML;
      var cardEl = div.closest('div[style*="padding"]');
      var titleEl = cardEl ? cardEl.querySelector('a[href]') : null;
      var articleTitle = titleEl ? titleEl.textContent.trim() : '';
      var section = detectSection(div);

      var parts = html.split(/<br\s*\/?>/i);

      if (parts.length < 2) {{
        // Single block of text (e.g. paper abstract) — add one button for the whole thing
        var cleanText = html.replace(/<[^>]*>/g, '').trim();
        if (!cleanText) return;
        var truncated = cleanText.length > 200 ? cleanText.substring(0, 200) + '...' : cleanText;
        var isLiked = likedTexts.has(truncated);
        div.style.position = 'relative';
        var newHtml = '<span style="display:block;padding-right:28px;">' + html + '</span>'
          + '<button class="like-btn' + (isLiked ? ' liked' : '') + '" '
          + 'style="position:absolute;top:0;right:0;" '
          + 'data-bullet-text="' + truncated.replace(/"/g, '&quot;') + '" '
          + 'data-article-title="' + articleTitle.replace(/"/g, '&quot;') + '" '
          + 'data-section="' + section + '" '
          + 'title="Like this">\\uD83D\\uDC4D</button>';
        div.innerHTML = newHtml;
      }} else {{
        var newHtml = parts.map(function(part) {{
          var cleanText = part.replace(/<[^>]*>/g, '').trim();
          if (!cleanText) return part;
          var isLiked = likedTexts.has(cleanText);
          return '<span style="display:flex;align-items:flex-start;gap:2px;margin-bottom:2px;">'
            + '<span style="flex:1;">' + part + '</span>'
            + '<button class="like-btn' + (isLiked ? ' liked' : '') + '" '
            + 'data-bullet-text="' + cleanText.replace(/"/g, '&quot;') + '" '
            + 'data-article-title="' + articleTitle.replace(/"/g, '&quot;') + '" '
            + 'data-section="' + section + '" '
            + 'title="Like this bullet">\\uD83D\\uDC4D</button>'
            + '</span>';
        }}).join('');
        div.innerHTML = newHtml;
      }}

      div.querySelectorAll('.like-btn').forEach(function(btn) {{
        btn.addEventListener('click', function(e) {{
          e.preventDefault();
          e.stopPropagation();
          toggleLike(btn, btn.dataset.bulletText, btn.dataset.articleTitle, btn.dataset.section);
        }});
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
    loadLikes();
    var overlay = document.getElementById('stash-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'stash-overlay';
    overlay.className = 'stash-overlay open';
    var panel = document.createElement('div');
    panel.className = 'stash-panel';

    var html = '<div class="stash-header">'
      + '<button class="stash-close" onclick="document.getElementById(\\x27stash-overlay\\x27).remove()">&times;</button>'
      + '<h2>My Stash</h2>';

    if (allLikes.length === 0) {{
      html += '</div><div class="stash-empty">Nothing here yet.<br>Like bullet points as you read &mdash; they\\x27ll appear here.</div>';
    }} else {{
      html += '<div class="stash-count">' + allLikes.length + ' saved item' + (allLikes.length === 1 ? '' : 's') + '</div></div>';

      // Group by newsletter_date, sorted newest first
      var groups = {{}};
      allLikes.forEach(function(like) {{
        var d = like.newsletter_date || 'Unknown';
        if (!groups[d]) groups[d] = [];
        groups[d].push(like);
      }});
      var sortedDates = Object.keys(groups).sort(function(a,b) {{ return b.localeCompare(a); }});

      html += '<div class="stash-body" id="stash-items">';
      sortedDates.forEach(function(date) {{
        html += '<div class="stash-date-group">';
        html += '<div class="stash-date-label">' + formatDateLabel(date) + '</div>';
        groups[date].forEach(function(like) {{
          var escaped = like.bullet_text.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          var displayText = like.bullet_text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
          var titleDisplay = (like.article_title || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          html += '<div class="stash-item" data-like-id="' + like.id + '">'
            + '<input type="checkbox" value="' + like.id + '" data-text="' + escaped + '">'
            + '<div class="stash-item-content">'
            + '<div class="stash-item-text">' + displayText + '</div>'
            + '<div class="stash-item-meta">'
            + '<span class="stash-item-section ' + (like.section || 'other') + '">' + sectionLabel(like.section) + '</span>'
            + (titleDisplay ? '<span class="stash-item-source">' + titleDisplay + '</span>' : '')
            + '</div>'
            + '</div>'
            + '<button class="stash-delete" onclick="window._deleteLike(' + like.id + ',this)" title="Remove">&times;</button>'
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
        html += '<div style="margin-top:12px;padding:12px;background:#f5f0e8;border-left:3px solid #e67e22;">'
          + '<label class="stash-prompt-label" style="color:#e67e22;">Gemini API Key (saved locally, never uploaded)</label>'
          + '<div style="display:flex;gap:6px;">'
          + '<input id="gemini-key-input" type="password" class="stash-prompt" style="flex:1;padding:6px 10px;" placeholder="Paste your Gemini API key">'
          + '<button class="primary" style="font-size:11px;padding:6px 14px;" onclick="window._saveGeminiKey()">Save</button>'
          + '</div></div>';
      }} else {{
        html += '<div style="margin-top:8px;font-size:11px;color:#999;font-style:italic;">API key saved &middot; <a href="#" onclick="localStorage.removeItem(\\x27' + GEMINI_KEY_STORAGE + '\\x27);window._openStash();return false;" style="color:#888;">Change key</a></div>';
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

  window._deleteLike = function(likeId, btnEl) {{
    allLikes = allLikes.filter(function(l) {{ return l.id !== likeId; }});
    saveLikes();
    likedTexts = new Set(allLikes.map(function(l) {{ return l.bullet_text; }}));
    var row = btnEl.closest('.stash-item');
    if (row) row.remove();
    refreshAllButtons();
    if (allLikes.length === 0) {{
      window._openStash();
    }}
  }};

  window._copySelection = function(btn) {{
    var checked = document.querySelectorAll('#stash-items input[type=checkbox]:checked');
    if (checked.length === 0) {{ alert('Select at least one item'); return; }}
    var lines = [];
    var currentDate = '';
    checked.forEach(function(cb) {{
      var item = allLikes.find(function(l) {{ return l.id === parseInt(cb.value); }});
      if (!item) return;
      var d = item.newsletter_date || '';
      if (d !== currentDate) {{
        if (lines.length > 0) lines.push('');
        lines.push(d);
        lines.push('');
        currentDate = d;
      }}
      lines.push(item.bullet_text);
      var source = item.article_title ? '  — ' + item.article_title + ' [' + (item.section || '').replace('_',' ') + ']' : '';
      if (source) lines.push(source);
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
    if (checked.length === 0) {{ alert('Select at least one bullet'); return; }}

    var apiKey = localStorage.getItem(GEMINI_KEY_STORAGE) || '';
    if (!apiKey) {{ alert('Please save your Gemini API key first'); return; }}

    var bullets = [];
    checked.forEach(function(cb) {{ bullets.push(cb.dataset.text); }});
    var customPrompt = (document.getElementById('custom-prompt') || {{}}).value || '';

    var prompt = 'You are an educational content writer. The user liked these bullet points from a daily newsletter:\\n\\n';
    bullets.forEach(function(b) {{ prompt += '- ' + b + '\\n'; }});
    prompt += '\\nYour task:\\n1. Research each topic in more depth.\\n2. Write a 2-3 minute spoken script (350-500 words) that explains these topics in an educational, engaging way.\\n3. Be conversational but informative.\\n4. Add context, background, and why it matters.\\n5. Start with a hook, end with a takeaway.';
    if (customPrompt) {{ prompt += '\\n\\nAdditional instructions: ' + customPrompt; }}
    prompt += '\\n\\nReturn ONLY the script text, ready to be read aloud. No stage directions, no markdown.';

    var btn = document.getElementById('generate-script-btn');
    btn.disabled = true;
    btn.innerHTML = 'Generating<span class="spinner"></span>';
    var resultDiv = document.getElementById('script-result');
    resultDiv.innerHTML = '';

    try {{
      var res = await fetch('https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=' + encodeURIComponent(apiKey), {{
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
      resultDiv.innerHTML = '<div class="script-output" style="color:#c0392b;">Error: ' + e.message + '</div>';
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
    addThumbsToSummaries();
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

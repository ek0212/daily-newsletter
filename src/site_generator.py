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
  .like-btn {{ background:none; border:none; cursor:pointer; font-size:16px; padding:0 4px; opacity:0.4; transition:opacity 0.15s; vertical-align:middle; }}
  .like-btn:hover {{ opacity:1; }}
  .like-btn.liked {{ opacity:1; }}
  .login-bar {{ position:fixed; top:0; right:0; z-index:10000; padding:8px 14px; font-family:'Times New Roman',serif; font-size:13px; display:flex; gap:8px; align-items:center; background:rgba(255,253,247,0.95); border-bottom-left-radius:4px; box-shadow:0 1px 4px rgba(0,0,0,0.1); }}
  .login-bar input {{ font-family:inherit; font-size:12px; padding:4px 8px; border:1px solid #ccc; }}
  .login-bar button {{ font-family:inherit; font-size:12px; padding:4px 12px; background:#1a1a1a; color:#fff; border:none; cursor:pointer; }}
  .stash-overlay {{ position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:9999; display:none; justify-content:center; align-items:center; }}
  .stash-overlay.open {{ display:flex; }}
  .stash-panel {{ background:#fffdf7; width:90%; max-width:600px; max-height:80vh; overflow-y:auto; padding:28px; font-family:'Times New Roman',serif; box-shadow:0 4px 20px rgba(0,0,0,0.2); position:relative; }}
  .stash-panel h2 {{ font-size:11px; text-transform:uppercase; letter-spacing:2.5px; font-weight:700; margin-bottom:16px; border-bottom:2px solid #1a1a1a; display:inline-block; padding-bottom:3px; }}
  .stash-item {{ padding:10px 0; border-bottom:1px solid #e0ddd5; display:flex; align-items:flex-start; gap:10px; }}
  .stash-item label {{ font-size:14px; color:#333; line-height:1.6; cursor:pointer; flex:1; }}
  .stash-item input[type=checkbox] {{ margin-top:5px; }}
  .stash-actions {{ margin-top:16px; display:flex; gap:8px; flex-wrap:wrap; }}
  .stash-actions button {{ font-family:'Times New Roman',serif; font-size:12px; padding:8px 16px; cursor:pointer; border:none; letter-spacing:1px; text-transform:uppercase; }}
  .stash-actions .primary {{ background:#1a1a1a; color:#fff; }}
  .stash-actions .secondary {{ background:#e0ddd5; color:#1a1a1a; }}
  .script-output {{ margin-top:16px; padding:16px; background:#f5f0e8; font-size:14.5px; line-height:1.7; color:#333; white-space:pre-wrap; }}
  .close-btn {{ position:absolute; top:12px; right:16px; font-size:20px; cursor:pointer; background:none; border:none; color:#888; }}
  .stash-empty {{ font-size:14px; color:#888; font-style:italic; padding:20px 0; }}
  .spinner {{ display:inline-block; width:16px; height:16px; border:2px solid #ccc; border-top-color:#1a1a1a; border-radius:50%; animation:spin 0.6s linear infinite; vertical-align:middle; margin-left:6px; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style>
<script>
(function() {{
  var API = window.location.origin + '/api';
  var sectionMap = {{'c0392b': 'news', '8e44ad': 'youtube', '27ae60': 'ai_security'}};
  var currentUser = null;
  var likedTexts = new Set();

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
    return m ? m[1] : '';
  }}

  async function apiCall(path, opts) {{
    opts = opts || {{}};
    opts.credentials = 'include';
    opts.headers = opts.headers || {{}};
    if (opts.body) opts.headers['Content-Type'] = 'application/json';
    var res = await fetch(API + path, opts);
    return res.json();
  }}

  // --- Login bar ---
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
    var u = document.getElementById('lb-user').value;
    var p = document.getElementById('lb-pass').value;
    var r = await apiCall('/login', {{ method: 'POST', body: JSON.stringify({{ username: u, password: p }}) }});
    if (r.error) {{ alert(r.error); return; }}
    currentUser = r.username;
    renderLoginBar();
    await loadLikes();
    refreshAllButtons();
  }};

  window._register = async function() {{
    var u = document.getElementById('lb-user').value;
    var p = document.getElementById('lb-pass').value;
    var r = await apiCall('/register', {{ method: 'POST', body: JSON.stringify({{ username: u, password: p }}) }});
    if (r.error) {{ alert(r.error); return; }}
    currentUser = r.username;
    renderLoginBar();
    await loadLikes();
    refreshAllButtons();
  }};

  window._logout = async function() {{
    await apiCall('/logout', {{ method: 'POST' }});
    currentUser = null;
    likedTexts = new Set();
    renderLoginBar();
    refreshAllButtons();
  }};

  // --- Likes ---
  var allLikes = [];
  async function loadLikes() {{
    if (!currentUser) {{ allLikes = []; likedTexts = new Set(); return; }}
    var r = await apiCall('/likes');
    allLikes = r.likes || [];
    likedTexts = new Set(allLikes.map(function(l) {{ return l.bullet_text; }}));
  }}

  function refreshAllButtons() {{
    document.querySelectorAll('.like-btn').forEach(function(btn) {{
      var text = btn.dataset.bulletText;
      if (likedTexts.has(text)) {{
        btn.textContent = '\\uD83D\\uDC4D';
        btn.classList.add('liked');
      }} else {{
        btn.textContent = '\\uD83D\\uDC4D';
        btn.classList.remove('liked');
      }}
    }});
  }}

  async function toggleLike(btn, bulletText, articleTitle, section) {{
    if (!currentUser) {{ alert('Please login first'); return; }}
    if (likedTexts.has(bulletText)) {{
      var item = allLikes.find(function(l) {{ return l.bullet_text === bulletText; }});
      if (item) {{
        await apiCall('/likes/' + item.id, {{ method: 'DELETE' }});
      }}
      likedTexts.delete(bulletText);
      btn.classList.remove('liked');
    }} else {{
      await apiCall('/likes', {{
        method: 'POST',
        body: JSON.stringify({{
          bullet_text: bulletText,
          article_title: articleTitle,
          section: section,
          newsletter_date: getDateFromURL()
        }})
      }});
      likedTexts.add(bulletText);
      btn.classList.add('liked');
    }}
    await loadLikes();
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

      // Split on <br> to get individual bullets
      var parts = html.split(/<br\s*\/?>/i);
      if (parts.length < 2) return; // not a bullet-point summary

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

      // Attach click handlers
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
  window._openStash = async function() {{
    if (!currentUser) return;
    await loadLikes();
    var overlay = document.getElementById('stash-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'stash-overlay';
    overlay.className = 'stash-overlay open';
    var panel = document.createElement('div');
    panel.className = 'stash-panel';

    var html = '<button class="close-btn" onclick="document.getElementById(\\x27stash-overlay\\x27).remove()">&times;</button>';
    html += '<h2>My Stash</h2>';

    if (allLikes.length === 0) {{
      html += '<div class="stash-empty">No liked bullets yet. Like some bullet points to see them here.</div>';
    }} else {{
      html += '<div id="stash-items">';
      allLikes.forEach(function(like) {{
        html += '<div class="stash-item">'
          + '<input type="checkbox" value="' + like.id + '" data-text="' + like.bullet_text.replace(/"/g, '&quot;') + '">'
          + '<label>' + like.bullet_text + '</label>'
          + '</div>';
      }});
      html += '</div>';
      html += '<div class="stash-actions">'
        + '<button class="secondary" onclick="window._stashSelectAll()">Select All</button>'
        + '<button class="secondary" onclick="window._stashSelectNone()">Select None</button>'
        + '<button class="primary" id="generate-script-btn" onclick="window._generateScript()">Generate Script</button>'
        + '</div>';
      html += '<div id="script-result"></div>';
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

  window._generateScript = async function() {{
    var checked = document.querySelectorAll('#stash-items input[type=checkbox]:checked');
    if (checked.length === 0) {{ alert('Select at least one bullet'); return; }}
    var bullets = [];
    checked.forEach(function(cb) {{ bullets.push(cb.dataset.text); }});

    var btn = document.getElementById('generate-script-btn');
    btn.disabled = true;
    btn.innerHTML = 'Generating<span class="spinner"></span>';
    var resultDiv = document.getElementById('script-result');
    resultDiv.innerHTML = '';

    var r = await apiCall('/generate-script', {{
      method: 'POST',
      body: JSON.stringify({{ bullets: bullets }})
    }});

    btn.disabled = false;
    btn.textContent = 'Generate Script';

    if (r.error) {{
      resultDiv.innerHTML = '<div class="script-output" style="color:#c0392b;">Error: ' + r.error + '</div>';
    }} else {{
      resultDiv.innerHTML = '<div class="script-output">' + r.script + '</div>';
    }}
  }};

  // --- Init ---
  async function init() {{
    var r = await apiCall('/me');
    if (r.user) {{
      currentUser = r.user.username;
      await loadLikes();
    }}
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

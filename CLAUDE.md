# Daily Briefing Newsletter

## What This Is

An automated daily newsletter that fetches, summarizes, and delivers five sections:

1. **NYC Weather** — current conditions, high/low, forecast
2. **Top 3 News** — headlines with extractive article summaries
3. **Podcast Episodes** — recent episodes from configured feeds with YouTube transcript summaries
4. **AI Security Papers** — trending arxiv papers on prompt injection, red/blue teaming, jailbreaking, LLM security

The newsletter is sent as an HTML email, published to a GitHub Pages static site with RSS feed, and archived as JSON + HTML.

## Project Structure

```
src/
  newsletter.py      # Main entry point — orchestrates fetch, render, email, site
  weather.py         # NWS API (free, no key) for NYC weather
  news.py            # Google News RSS + trafilatura article extraction + summarization
  podcasts.py        # RSS feeds + YouTube transcript API for episode summaries
  papers.py          # arxiv API + HuggingFace Daily Papers + Semantic Scholar citations
  summarizer.py      # Extractive summarizer (sumy LexRank), no LLM/AI API
  site_generator.py  # Static site: archive JSON, post HTML, index.html, feed.xml
templates/
  newsletter.html    # Jinja2 HTML email template
site/                # Generated output (gitignored) — deployed to GitHub Pages
  index.html         # Landing page with archive + RSS subscribe button
  feed.xml           # RSS 2.0 feed
  posts/             # Per-day JSON data + HTML pages
.github/workflows/
  newsletter.yml     # Daily cron at 7AM UTC, deploys to GitHub Pages
```

## Tech Stack

- **Language:** Python 3.11+
- **Template engine:** Jinja2
- **Summarization:** sumy (LexRank extractive), NOT any LLM API
- **Article extraction:** trafilatura
- **Podcast transcripts:** youtube-transcript-api
- **RSS parsing:** feedparser
- **HTTP:** requests (news, weather), urllib (arxiv, Semantic Scholar, HuggingFace)
- **Email:** smtplib (SMTP/TLS, Gmail app passwords)
- **Scheduling:** macOS launchd (local) or GitHub Actions cron (production)
- **Site hosting:** GitHub Pages via actions/deploy-pages

## Critical Rules

### APIs — No Keys Required (except email)
- NWS API: free, only needs User-Agent header. NYC grid: OKX/33,35.
- Google News RSS: no limits, no key.
- arxiv API: no key. Use focused single-keyword queries (not giant OR queries — they timeout).
- Semantic Scholar: no key for basic citation lookups. Rate-limited, best-effort.
- HuggingFace Daily Papers: simple JSON endpoint, no key.
- YouTube channel RSS + youtube-transcript-api: no key.
- The ONLY credentials needed are SMTP email credentials in `.env`.

### Summarization
- NEVER use an LLM or AI API for summaries. Use sumy LexRank (extractive) only.
- `summarize(text, num_sentences)` in `src/summarizer.py` is the single summarization interface.
- News: 3-sentence summary from fetched article text.
- Papers: 2-sentence quick_summary from abstract.
- Podcasts: 4-sentence summary from YouTube transcript, fallback to RSS description.

### Imports
- All `src/` modules use `from src.module import thing` (package-style imports).
- Never use bare `from module import thing` — it breaks when run from project root.

### Error Handling
- Every data source must have try/except so one failure doesn't crash the whole newsletter.
- Weather, news, podcasts, papers each fail independently and show fallback content.
- arxiv queries run as separate small requests (one per keyword) to avoid timeouts.

### Generated Output
- `site/` is gitignored — it's rebuilt on every run.
- `output.html` is gitignored — local test output.
- `site/posts/*.json` archives are persisted on gh-pages branch (restored before each run in CI).

## Validation

Run these checks after ANY code change. All must pass before committing.

### 1. Newsletter generates without errors
```bash
source venv/bin/activate
python3 src/newsletter.py
```
**Expected:** Prints status lines for each section, ends with "Site updated successfully" and either "Newsletter sent" or "saved to output.html". Exit code 0.

### 2. Output HTML is valid and has all sections
```bash
python3 -c "
from pathlib import Path
html = Path('output.html').read_text()
checks = [
    ('Weather section', 'Weather in NYC' in html),
    ('Top News section', 'Top News' in html),
    ('Podcast section', 'Podcast Episodes' in html),
    ('Papers section', 'AI Security' in html),
    ('Has temperature', '°' in html),
    ('Has news links', '<a href=' in html),
    ('Header present', 'Your Daily Briefing' in html),
    ('Footer present', 'Generated automatically' in html),
]
for name, ok in checks:
    status = 'PASS' if ok else 'FAIL'
    print(f'  [{status}] {name}')
all_pass = all(ok for _, ok in checks)
print(f'\n{'All checks passed.' if all_pass else 'SOME CHECKS FAILED.'}')
exit(0 if all_pass else 1)
"
```

### 3. Site files are generated correctly
```bash
python3 -c "
from pathlib import Path
import json, xml.etree.ElementTree as ET
checks = []

# Index exists and has RSS link
idx = Path('site/index.html')
checks.append(('site/index.html exists', idx.exists()))
if idx.exists():
    t = idx.read_text()
    checks.append(('Index has RSS link', 'feed.xml' in t))
    checks.append(('Index has archive', 'Archive' in t))

# Feed is valid XML
feed = Path('site/feed.xml')
checks.append(('site/feed.xml exists', feed.exists()))
if feed.exists():
    try:
        ET.parse(str(feed))
        checks.append(('Feed is valid XML', True))
    except:
        checks.append(('Feed is valid XML', False))

# At least one post exists
posts = list(Path('site/posts').glob('*.json'))
checks.append(('Archive JSON exists', len(posts) > 0))
if posts:
    data = json.loads(posts[0].read_text())
    checks.append(('Archive has weather', 'weather' in data))
    checks.append(('Archive has news', 'news' in data))
    checks.append(('Archive has podcasts', 'podcasts' in data))
    checks.append(('Archive has papers', 'papers' in data))

html_posts = list(Path('site/posts').glob('*.html'))
checks.append(('Archive HTML exists', len(html_posts) > 0))

for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
all_pass = all(ok for _, ok in checks)
print(f'\n{\"All checks passed.\" if all_pass else \"SOME CHECKS FAILED.\"}')
exit(0 if all_pass else 1)
"
```

### 4. Visual validation (open in browser)
```bash
open output.html
open site/index.html
```
Check manually:
- Dark gradient header renders correctly
- Weather card shows temperature with blue background
- News items have headlines with gray source text and summary underneath
- Podcast items show podcast name in purple caps, title, and summary
- Papers show title, author list, date, and 2-sentence quick summary
- All links are clickable
- Layout is single-column, max 640px, centered
- No broken styling or overlapping elements

### 5. Individual module smoke tests
```bash
python3 -c "from src.weather import get_nyc_weather; w = get_nyc_weather(); print(f'Weather: {w[\"current_temp\"]}°{w[\"unit\"]}, {w[\"conditions\"]}')"
python3 -c "from src.news import get_top_news; n = get_top_news(1); print(f'News: {n[0][\"title\"]}')"
python3 -c "from src.podcasts import get_recent_episodes; eps = get_recent_episodes(30); print(f'Podcasts: {len(eps)} episodes')"
python3 -c "from src.papers import get_ai_security_papers; p = get_ai_security_papers(top_n=2); print(f'Papers: {len(p)} found')"
python3 -c "from src.summarizer import summarize; print(summarize('The quick brown fox jumps over the lazy dog. It was a sunny day. The birds were singing loudly in the trees. Everyone was happy.', 2))"
```
Each must exit 0 and print sensible output.

### 6. Template rendering check
```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
t = env.get_template('newsletter.html')
html = t.render(
    date='Test Date',
    weather={'current_temp': 42, 'unit': 'F', 'conditions': 'Cloudy', 'high': 50, 'low': 35, 'forecast': 'Test'},
    news=[{'title': 'Test', 'source': 'Src', 'link': '#', 'published': 'today', 'summary': 'A summary.'}],
    podcasts=[{'podcast': 'Test Pod', 'title': 'Ep 1', 'link': '#', 'summary': 'Pod summary.'}],
    papers=[{'title': 'Paper', 'authors': ['Auth'], 'link': '#', 'published': 'today', 'citation_count': 5, 'quick_summary': 'Quick.', 'abstract': 'Full abstract.'}],
)
assert 'Test Date' in html
assert 'A summary.' in html
assert 'Pod summary.' in html
assert 'Quick.' in html
print('Template renders correctly.')
"
```

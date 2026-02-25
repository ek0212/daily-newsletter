# Daily Briefing Newsletter

## Frontend Design
For any frontend/UI work, follow the frontend design skill guide: https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md

## What This Is

Automated daily newsletter with five sections, published to GitHub Pages + RSS feed, delivered to inbox via Blogtrottr:

1. **NYC Weather** — current conditions, high/low, forecast
2. **Top 3 News** — headlines with LLM or extractive summaries
3. **Podcast Episodes** — recent episodes with YouTube transcript summaries
4. **AI Security Papers** — trending arxiv papers on prompt injection, red/blue teaming, jailbreaking, LLM security

## Project Structure

```
src/
  newsletter.py      # Main entry — orchestrates fetch, summarize, render, site update
  weather.py         # NWS API (free, no key) for NYC weather
  news.py            # Google News RSS + googlenewsdecoder + trafilatura extraction
  podcasts.py        # RSS feeds + YouTube transcript API
  papers.py          # arxiv API + HuggingFace Daily Papers + Semantic Scholar
  llm.py             # Gemini batch summarization (single API call for all content)
  summarizer.py      # Extractive fallback (sumy LexRank), also bolds key terms
  site_generator.py  # Static site: archive JSON, post HTML, index.html, feed.xml
templates/
  newsletter.html    # Jinja2 HTML template (all inline CSS)
site/                # Generated output (gitignored) — deployed to GitHub Pages
.github/workflows/
  newsletter.yml     # Daily cron at 12PM UTC (7AM EST), deploys to GitHub Pages
```

## Tech Stack

- **Language:** Python 3.11+
- **Template:** Jinja2 (all CSS inline for email/RSS compatibility)
- **Summarization:** Gemini 2.5 Flash (single batched call), sumy LexRank fallback
- **Article extraction:** trafilatura + googlenewsdecoder (resolves Google News URLs)
- **Podcast transcripts:** youtube-transcript-api
- **RSS parsing:** feedparser
- **Delivery:** GitHub Pages → RSS feed → Blogtrottr → inbox
- **Logging:** Python logging module, every module has its own logger

## Critical Rules

### Card Format (template)
Every card in every section follows the same visual structure:
1. **Date line first** — always prominent, 12px, uppercase, section-colored, with metadata (source/podcast name/authors)
2. **Title** — 17px, bold 700, dark, clickable link
3. **Badges** (papers only) — topic pills after title
4. **Summary** — 14px, #555, 1.6 line-height. KEY: takeaway in colored box if present.

Cards are white with 1px #eee border, 10px border-radius, 20px padding, 4px colored left border. This is standardized — do not deviate.

### Summarization
- Gemini 2.5 Flash via `src/llm.py` — ONE API call for all summaries (news + podcasts + papers batched together)
- Fallback to sumy LexRank if no GEMINI_API_KEY or API error
- `src/summarizer.py` bolds numbers, stats, proper nouns, quoted text in fallback mode
- Each summary = exactly 3 emoji bullet points, no bold tags, no dash prefix
- `_validate_summary()` rejects bad summaries at runtime (see below)

### Summary Quality Rules (NEVER violate)
The #1 goal: a reader skims the bullets and learns all key facts WITHOUT clicking through.

**Vague bullets are the most common Gemini failure.** They pass structural checks but are useless. Examples of what MUST NEVER appear in output:
- `"⚠️ The podcast discussed the idea that X might pose inherent problems."` — Meta-description ("the podcast discussed") + vague claim ("might pose problems"). Says nothing.
- `"📊 Viewership experienced a significant increase."` — No number. Significant how?
- `"🛠️ AI benefits skilled trades by reducing operational friction."` — Corporate filler. What friction? What trades? What happened?
- `"🧠 The paper proposes a framework to bridge the gap."` — Describes the paper instead of reporting findings.

**Why this happens:** Gemini defaults to safe, generic language when the source text is editorial/thin on facts. The prompt explicitly bans this, but Gemini sometimes ignores it. The `_validate_summary()` function in `llm.py` catches these patterns at runtime and falls back to extractive summarization.

**Runtime validation catches:**
1. Structural: missing emoji bullets, fragments, cut-offs, raw text leaks
2. Semantic: meta-descriptions ("the podcast discussed"), vague filler ("might pose problems", "significant increase", "remains challenging")

**If you modify the prompt or validation:** Always rebuild and run check #6 from Validation to verify no vague bullets slip through.

### APIs
- NWS: free, no key. NYC grid: OKX/33,35
- Google News RSS: free. URLs decoded via googlenewsdecoder (protobuf → real URL)
- arxiv: no key. Focused single-keyword queries (avoid timeouts)
- Semantic Scholar: no key, rate-limited, best-effort citations
- HuggingFace Daily Papers: no key
- YouTube transcripts: no key
- Gemini: requires GEMINI_API_KEY (free tier available)

### Imports
- All modules: `from src.module import thing` (package-style). Never bare imports.

### Error Handling
- Every data source has try/except — one failure never crashes the whole build
- Each section fails independently with fallback content
- Logging captures all errors with context

### Generated Output
- `site/` and `output.html` are gitignored
- `site/posts/*.json` archives persisted on gh-pages branch

## Validation

Run ALL of these after ANY code change. All must pass before committing.

### 1. Full build succeeds
```bash
source venv/bin/activate
python3 src/newsletter.py 2>&1 | tee /tmp/newsletter-build.log
echo "Exit code: $?"
```
**Expected:** Exit code 0, output.html and site/ files generated.

### 2. HTML structure check
```bash
python3 -c "
from pathlib import Path
html = Path('output.html').read_text()
checks = [
    ('Header + date', 'Your Daily Briefing' in html),
    ('Weather section', 'Weather in NYC' in html),
    ('News section', 'Top News' in html),
    ('Podcast section', 'Podcast Episodes' in html),
    ('Papers section', 'AI Security' in html),
    ('Has links', '<a href=' in html),
    ('RSS footer', 'Subscribe via RSS' in html),
]
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

### 3. Site files check
```bash
python3 -c "
from pathlib import Path
import json, xml.etree.ElementTree as ET
checks = []
idx = Path('site/index.html')
checks.append(('index.html exists', idx.exists()))
if idx.exists():
    checks.append(('Index has RSS link', 'feed.xml' in idx.read_text()))
feed = Path('site/feed.xml')
checks.append(('feed.xml exists', feed.exists()))
if feed.exists():
    try: ET.parse(str(feed)); checks.append(('Feed valid XML', True))
    except: checks.append(('Feed valid XML', False))
posts = list(Path('site/posts').glob('*.json'))
checks.append(('Archive JSON exists', len(posts) > 0))
if posts:
    d = json.loads(posts[-1].read_text())
    for k in ['weather','news','podcasts','papers']:
        checks.append((f'Archive has {k}', k in d))
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

### 4. Visual check
```bash
open output.html
open site/index.html
```
Verify: date is prominent in header, every card has date first → title → summary, cards look uniform, badges render, links work, no broken layout.

### 5. Build log validation (ALWAYS run last)
```bash
python3 -c "
log = open('/tmp/newsletter-build.log').read()
checks = [
    ('Build started', '=== Daily Newsletter Build Started ===' in log),
    ('Build completed', '=== Build Complete ===' in log),
    ('No ERROR lines', 'ERROR' not in log),
    ('Weather fetched', 'NYC weather fetched' in log),
    ('News fetched', 'News fetch complete' in log),
    ('Podcasts fetched', 'Podcasts complete' in log),
    ('Papers fetched', 'Papers complete' in log),
    ('HTML rendered', 'HTML rendered' in log),
    ('Site updated', 'Regenerating feed.xml' in log),
    ('News articles extracted', 'with article text' in log),
]
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
failed = [n for n, ok in checks if not ok]
if failed:
    print(f'\nFAILED: {failed}')
    print('\nRelevant log lines:')
    for line in log.splitlines():
        if any(x in line for x in ['ERROR', 'WARNING', 'FAIL']):
            print(f'  {line}')
    exit(1)
print('\nAll build log checks passed.')
"
```
This is the final gate. It verifies every section produced data, no errors occurred, and the full pipeline ran end-to-end. If any check fails, it prints the relevant WARNING/ERROR log lines for debugging.

### 6. Summary quality validation
```bash
python3 -c "
import re
from pathlib import Path
html = Path('output.html').read_text()
summaries = re.findall(r'font-size: 14\.5px.*?>(.*?)</div>', html, re.DOTALL)
emoji_re = re.compile(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002702-\U000027B0]')
vague_res = [
    re.compile(r'(?i)the (?:podcast|episode|article|paper|discussion) (?:discussed|explores?|highlights?|focused on|suggests?|argues?)'),
    re.compile(r'(?i)(?:might|could|may) (?:pose|create|introduce|present) (?:inherent |potential |new )?(?:problems|challenges|issues|concerns)'),
    re.compile(r'(?i)(?:significant|substantial|considerable) (?:increase|decrease|impact|implications)'),
    re.compile(r'(?i)(?:is (?:critical|essential|important|key|crucial)|remains challenging)'),
    re.compile(r'(?i)experienced a (?:significant|notable|substantial) (?:increase|decrease|growth|decline)'),
]
checks = []
bad_items = []
for i, s in enumerate(summaries):
    clean = re.sub(r'<[^>]+>', '', s).strip()
    if not clean: continue
    emojis = len(emoji_re.findall(clean))
    bullets = len(s.split('<br>'))
    has_bullets = emojis >= 2 or bullets >= 2
    starts_lower = clean[0].islower()
    has_raw = any(x in s for x in ['made possible by:', \"Today's show:\", 'https://Gusto', 'calderalab.com'])
    last = clean.rstrip()[-1] if clean.rstrip() else ''
    cut_off = last not in '.!?)\"' + \"'\" + '…>0123456789%'
    vague_matches = [p.search(clean) for p in vague_res]
    is_vague = any(vague_matches)
    ok = has_bullets and not starts_lower and not has_raw and not cut_off and not is_vague
    if not ok:
        reasons = []
        if not has_bullets: reasons.append(f'only {emojis} emojis, {bullets} segments')
        if starts_lower: reasons.append('starts lowercase (fragment)')
        if has_raw: reasons.append('contains raw text/sponsors')
        if cut_off: reasons.append('cut off mid-sentence')
        if is_vague:
            for m in vague_matches:
                if m: reasons.append(f'vague: \"{m.group()}\"')
        bad_items.append((i+1, reasons, clean[:120]))
checks.append(('All summaries have bullet format', not any(r for _, r, _ in bad_items if any('emojis' in x for x in r))))
checks.append(('No fragments or cut-offs', not any(r for _, r, _ in bad_items if any('lowercase' in x or 'cut off' in x for x in r))))
checks.append(('No raw text leaks', not any(r for _, r, _ in bad_items if any('raw text' in x for x in r))))
checks.append(('No vague filler bullets', not any(r for _, r, _ in bad_items if any('vague' in x for x in r))))
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
if bad_items:
    print(f'\n  {len(bad_items)} bad summaries:')
    for idx, reasons, preview in bad_items:
        print(f'    Item {idx}: {\", \".join(reasons)}')
        print(f'      {preview}...')
exit(0 if all(ok for _, ok in checks) else 1)
"
```
Verifies every summary in the output has proper emoji bullet format (at least 2 emoji bullets), doesn't start with a lowercase fragment (sign of misaligned JSON extraction), contains no raw text/sponsor leaks, and isn't cut off mid-sentence. These are the most common failure modes when Gemini returns malformed JSON.

### 7. RSS feed email formatting check
```bash
python3 -c "
import xml.etree.ElementTree as ET
from pathlib import Path
ns = {'content': 'http://purl.org/rss/1.0/modules/content/'}
tree = ET.parse('site/feed.xml')
items = tree.getroot().findall('.//item')
checks = []
checks.append(('Feed has items', len(items) > 0))
# Verify CDATA wrapping (critical for Blogtrottr email rendering)
raw_feed = Path('site/feed.xml').read_text()
checks.append(('content:encoded uses CDATA', '<![CDATA[' in raw_feed))
checks.append(('No escaped HTML in content:encoded', '&lt;body style=' not in raw_feed))
# Verify no site wrapper leaked into content:encoded
all_clean = True
for item in items:
    encoded = item.find('content:encoded', ns)
    if encoded is not None and encoded.text:
        if 'site-nav' in encoded.text or 'email-wrap' in encoded.text:
            all_clean = False
            break
checks.append(('No site wrapper in content:encoded', all_clean))
# Verify today's entry has inline styles (email-compatible)
if items:
    latest = items[0].find('content:encoded', ns)
    checks.append(('Latest entry has inline styles', latest is not None and 'style=' in (latest.text or '')))
# Verify .email.html files exist for recent posts
from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')
email_path = Path(f'site/posts/{today}.email.html')
checks.append(('Today email.html exists', email_path.exists()))
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```
Verifies that the RSS feed's `content:encoded` uses CDATA wrapping (critical — without CDATA, Blogtrottr renders plain text instead of styled HTML), contains clean email HTML (no site navigation wrappers), has inline styles for email client compatibility, and that `.email.html` files are generated alongside post pages.

# Validation

Run ALL of these after ANY code change. All must pass before committing.

## 1. Full build succeeds
```bash
source venv/bin/activate
python3 src/newsletter.py 2>&1 | tee /tmp/newsletter-build.log
echo "Exit code: $?"
```
**Expected:** Exit code 0, output.html and site/ files generated.

## 2. HTML structure check
```bash
python3 -c "
from pathlib import Path
html = Path('output.html').read_text()
checks = [
    ('Header + date', 'Your Daily Briefing' in html),
    ('Weather section', 'Weather in New York City' in html),
    ('News section', 'Top News' in html),
    ('YouTube section', 'YouTube' in html),
    ('Papers section', 'AI Security' in html),
    ('Has links', '<a href=' in html),
    ('RSS footer', 'Subscribe via RSS' in html),
]
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 3. Site files check
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
    for k in ['weather','news','youtube','ai_security']:
        checks.append((f'Archive has {k}', k in d))
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 4. Visual check
```bash
open output.html
open site/index.html
```
Verify: date is prominent in header, every card has date first → title → summary, cards look uniform, badges render, links work, no broken layout.

## 5. Build log validation
```bash
python3 -c "
log = open('/tmp/newsletter-build.log').read()
checks = [
    ('Build started', '=== Daily Newsletter Build Started ===' in log),
    ('Build completed', '=== Build Complete ===' in log),
    ('Weather fetched', 'NYC weather fetched' in log),
    ('News fetched', 'News fetch complete' in log),
    ('YouTube fetched', 'YouTube complete' in log),
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

## 6. YouTube text coverage (CRITICAL — catches CI transcript failures)

This is the check that would have caught the #1 recurring problem: YouTube transcripts fail in GitHub Actions because YouTube blocks datacenter IPs. The fix uses podcast RSS feeds as primary text source for 6/9 channels. This check verifies that the podcast RSS fallback is actually working and enough videos have real text content.

```bash
python3 -c "
import json, re
from pathlib import Path
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')
archive = Path(f'site/posts/{today}.json')
if not archive.exists():
    # Fall back to most recent archive
    archives = sorted(Path('site/posts').glob('*.json'))
    archive = archives[-1] if archives else None
if not archive:
    print('  [FAIL] No archive JSON found'); exit(1)

data = json.loads(archive.read_text())
videos = data.get('youtube', [])
if not videos:
    print('  [FAIL] No youtube entries in archive'); exit(1)

total = len(videos)
with_text = sum(1 for v in videos if len(v.get('raw_text', '')) > 200)
no_text = total - with_text

# Check podcast RSS coverage specifically
log = open('/tmp/newsletter-build.log').read()
podcast_match = re.search(r'Podcast/website text: (\d+)/(\d+)', log)
podcast_hits = int(podcast_match.group(1)) if podcast_match else 0

checks = [
    ('At least 50% videos have text', with_text >= total / 2),
    ('Podcast RSS covered 3+ videos', podcast_hits >= 3),
    ('Not all videos lack text', with_text > 0),
]
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
print(f'\n  Text coverage: {with_text}/{total} videos have text (podcast: {podcast_hits})')
if no_text > 0:
    print(f'  Videos without text:')
    for v in videos:
        if len(v.get('raw_text', '')) <= 200:
            print(f'    - [{v.get(\"channel\",\"?\")}] {v.get(\"title\",\"?\")[:60]}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 7. YouTube summary quality (CRITICAL — catches Gemini rate limit fallback)

This catches the #2 recurring problem: even when transcripts are fetched, Gemini rate limits (429 daily quota) cause the youtube section to fall back to title-only summaries like `🎬 Some Video Title`. These are useless to readers. This check verifies summaries have actual 3-bullet content, not just the title.

```bash
python3 -c "
import json, re
from pathlib import Path
from datetime import datetime

today = datetime.now().strftime('%Y-%m-%d')
archive = Path(f'site/posts/{today}.json')
if not archive.exists():
    archives = sorted(Path('site/posts').glob('*.json'))
    archive = archives[-1] if archives else None
if not archive:
    print('  [FAIL] No archive JSON found'); exit(1)

data = json.loads(archive.read_text())
videos = data.get('youtube', [])
emoji_re = re.compile(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002702-\U000027B0]')

total = len(videos)
good = 0
title_only = []
for v in videos:
    s = v.get('summary', '')
    emojis = len(emoji_re.findall(s))
    bullets = len(s.split('<br>'))
    if emojis >= 2 and bullets >= 2:
        good += 1
    else:
        title_only.append(v.get('title', '?')[:60])

checks = [
    ('At least 50% have real summaries', good >= total / 2),
    ('Not all title-only', good > 0),
]
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
print(f'\n  Summary quality: {good}/{total} have 3-bullet summaries')
if title_only:
    print(f'  Title-only fallbacks ({len(title_only)}):')
    for t in title_only:
        print(f'    - {t}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 8. Summary content quality (catches vague Gemini output)
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

## 9. RSS feed email formatting check
```bash
python3 -c "
import xml.etree.ElementTree as ET
from pathlib import Path
ns = {'content': 'http://purl.org/rss/1.0/modules/content/'}
tree = ET.parse('site/feed.xml')
items = tree.getroot().findall('.//item')
checks = []
checks.append(('Feed has items', len(items) > 0))
raw_feed = Path('site/feed.xml').read_text()
checks.append(('content:encoded uses CDATA', '<![CDATA[' in raw_feed))
checks.append(('No escaped HTML in content:encoded', '&lt;body style=' not in raw_feed))
all_clean = True
for item in items:
    encoded = item.find('content:encoded', ns)
    if encoded is not None and encoded.text:
        if 'site-nav' in encoded.text or 'email-wrap' in encoded.text:
            all_clean = False
            break
checks.append(('No site wrapper in content:encoded', all_clean))
if items:
    latest = items[0].find('content:encoded', ns)
    checks.append(('Latest entry has inline styles', latest is not None and 'style=' in (latest.text or '')))
from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')
email_path = Path(f'site/posts/{today}.email.html')
checks.append(('Today email.html exists', email_path.exists()))
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 10. Gemini API key health (catches expired/quota-exhausted keys before wasting a build)
```bash
python3 -c "
import os, re
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.')/ '.env')

checks = []
keys = []
for var in ['GEMINI_API_KEY', 'GEMINI_API_KEY_2']:
    k = os.getenv(var)
    if k:
        keys.append((var, k))
checks.append(('At least 1 Gemini key set', len(keys) > 0))

for var, key in keys:
    try:
        from google import genai
        client = genai.Client(api_key=key)
        r = client.models.generate_content(model='gemini-2.5-flash', contents='Say OK')
        checks.append((f'{var} is valid', True))
    except Exception as e:
        err = str(e)
        if 'expired' in err.lower() or 'invalid' in err.lower():
            checks.append((f'{var} is valid', False))
            print(f'  WARNING: {var} is expired/invalid — renew it')
        elif '429' in err:
            checks.append((f'{var} is valid (quota exhausted)', True))
            print(f'  NOTE: {var} has hit daily quota — will reset tomorrow')
        else:
            checks.append((f'{var} is valid', False))
            print(f'  WARNING: {var} error: {err[:100]}')

for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 11. Podcast RSS feed reachability (catches feed URL changes before CI fails silently)
```bash
python3 -c "
import feedparser
feeds = {
    'This Week in Startups': 'https://anchor.fm/s/7c624c84/podcast/rss',
    'Dwarkesh Podcast': 'https://api.substack.com/feed/podcast/69345.rss',
    'Lex Fridman Podcast': 'https://lexfridman.com/feed/podcast/',
    'AI Daily Brief': 'https://anchor.fm/s/f7cac464/podcast/rss',
    'Morning Brew Daily': 'https://feeds.megaphone.fm/business-casual',
    'Matt Wolfe': 'https://feeds.megaphone.fm/thenextwave',
}
checks = []
for name, url in feeds.items():
    try:
        f = feedparser.parse(url)
        has_entries = len(f.entries) > 0
        has_desc = any(len(e.get('description','') or e.get('summary','')) > 100 for e in f.entries[:3])
        checks.append((f'{name} feed reachable', has_entries))
        if not has_desc:
            print(f'  NOTE: {name} has entries but descriptions are thin')
    except Exception as e:
        checks.append((f'{name} feed reachable', False))
        print(f'  WARNING: {name} feed failed: {e}')

for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
failed = [n for n, ok in checks if not ok]
if failed:
    print(f'\n  {len(failed)} feeds unreachable — these channels will fall back to YouTube transcripts only')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

## 12. CI simulation (catches problems that only appear in GitHub Actions)

Run this to simulate the CI environment: no Tor, no local YouTube transcript access. Verifies that podcast RSS alone provides enough text content.

```bash
python3 -c "
from src.youtube import PODCAST_RSS_FEEDS, TRANSCRIPT_WEBSITES, YOUTUBE_CHANNELS, _get_podcast_text, _get_website_transcript
import feedparser

# Simulate: for each channel's latest YT video, can we get text WITHOUT YouTube transcripts?
covered = 0
total = 0
for name, yt_url in YOUTUBE_CHANNELS.items():
    feed = feedparser.parse(yt_url)
    if not feed.entries:
        continue
    title = feed.entries[0].title
    total += 1
    text = _get_website_transcript(name, title)
    if not text or len(text) < 200:
        text = _get_podcast_text(name, title)
    if text and len(text) >= 200:
        covered += 1
        print(f'  [OK] {name}: {len(text)} chars from podcast/website')
    else:
        print(f'  [YT-ONLY] {name}: needs YouTube transcript ({title[:50]})')

checks = [
    ('At least 4 channels covered without YouTube', covered >= 4),
]
for name, ok in checks:
    print(f'  [{\"PASS\" if ok else \"FAIL\"}] {name}')
print(f'\n  CI-safe coverage: {covered}/{total} channels')
exit(0 if all(ok for _, ok in checks) else 1)
"
```

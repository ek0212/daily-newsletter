# Architecture & Product Decisions

## 2026-08-02: Consensus weather forecasts

**Context:** Single-source NWS hourly forecasts were drifting from the user's observed consumer-weather apps.

**Decision:** Keep NWS for current observations and fallback, but average hourly and daily forecast fields across up to 10 Open-Meteo public models. Show source count in the email weather section.

**Alternatives considered:**
- Use only NWS: rejected because forecast drift was the reported problem
- Scrape consumer weather pages: rejected because it is brittle and less transparent than model/API data

**Status:** ACTIVE

---

## 2026-04-04: Regex fallback summarizer for environments without NLTK data

**Context:** The LSA summarizer (sumy) requires NLTK punkt tokenizer data, which must be downloaded separately. In some CI/network-restricted environments, this download fails silently and all summaries fall back to raw text fragments.

**Decision:** Added a regex-based sentence splitter as fallback when NLTK punkt is unavailable. The fallback scores sentences by information density (numbers, proper nouns, quoted text) and picks the top N.

**Alternatives considered:**
- Bundling NLTK data in the repo: rejected because punkt_tab is ~35MB and would bloat the repo
- Using a different summarizer that doesn't need NLTK: rejected because sumy/LSA is the best extractive option and works well when NLTK is available

**Status:** ACTIVE

---

## 2026-07-17: Compact briefing reference format

**Context:** The colorful dashboard restored personality but moved away from the preferred briefing structure shown in the July 17 reference issue.

**Decision:** Use the compact Daily Morning Briefing format: direct masthead, one-line overall signal, five metric tiles, weather and health tables, emoji-led linked rows for events/news/videos/security, separate AI articles and papers, optional Second Brain todo table, notes, and one final overall-signal paragraph.

**Alternatives considered:**
- Big colorful dashboard cards: rejected because they made the issue feel less like the preferred briefing
- Plain prose report: rejected because the reference format is still visual and scan-first

**Status:** BACKTRACKED

---

## 2026-08-03: August 2 compact email reference is canonical

**Context:** The user identified `Daily Morning Briefing  August 2 2026 Weather consensus.pdf` as the correct visual and structural format, even if it came from a different session.

**Decision:** Use the August 2 compact Mail-exported format as the canonical email layout: rounded white container, direct masthead/date row, one green focus sentence, five muted metric chips, table-first NYC weather and public-health sections, a `Three reads carry today. The rest can wait.` callout, compact colored top-read rows, an `Everything else, if you have more than a minute` mixed list, NYC Events near the bottom, and a plain generated-from-live-fetchers footer when no notes are supplied. Optional Second Brain todos appear once near the bottom after NYC Events when a run explicitly supplies them.

**Alternatives considered:**
- Fully sectioned August 3 layout: rejected because it drifted from the user-confirmed reference rhythm
- Removing Second Brain support from the template: rejected because some automation prompts still request read-only todos

**Status:** ACTIVE

---

## 2026-07-17: Dashboard keeps newsletter personality

**Context:** The issue dashboard made the newsletter easier to scan but flattened the existing Midtown Briefing voice.

**Decision:** Keep the dashboard structure, but render it with colorful cards, emoji cues, playful action labels, and one primary CTA plus limited secondary CTAs.

**Alternatives considered:**
- Plain operational dashboard: rejected because this newsletter is personality-led and should feel fun to open
- Removing the dashboard entirely: rejected because the top summary remains useful for fast scanning

**Status:** BACKTRACKED

---

## 2026-04-04: Importance scoring for news story selection

**Context:** The "top 5 news" section was including local incidents (bus crashes, retirement home crimes) alongside global stories, making the newsletter feel unfocused.

**Decision:** Added an importance scoring system that boosts stories matching global keywords (G7, UN, Fed, climate, president, etc.) and penalizes local/minor stories. Stories are now selected by importance score within each topic category, not just recency.

**Alternatives considered:**
- Filtering by source only (Google News = important): rejected because individual feeds also carry major stories
- Using an LLM to rank importance: rejected because the project goal is zero LLM dependencies in the pipeline

**Status:** ACTIVE

---

## 2026-04-04: Summary length capping at 300 chars

**Context:** Extractive summaries were sometimes pulling long run-on sentences from articles, producing wall-of-text summaries that made the newsletter hard to scan.

**Decision:** Added MAX_SUMMARY_CHARS (300) constant and _cap_length() function that truncates at the last sentence boundary within the limit. Paper abstracts are separately capped at 250 chars.

**Alternatives considered:**
- Reducing num_sentences to 1: rejected because a single sentence often lacks enough context
- Capping at word count instead of char count: rejected because char count is more predictable for layout

**Status:** ACTIVE

# Architecture & Product Decisions

## 2026-04-04: Regex fallback summarizer for environments without NLTK data

**Context:** The LSA summarizer (sumy) requires NLTK punkt tokenizer data, which must be downloaded separately. In some CI/network-restricted environments, this download fails silently and all summaries fall back to raw text fragments.

**Decision:** Added a regex-based sentence splitter as fallback when NLTK punkt is unavailable. The fallback scores sentences by information density (numbers, proper nouns, quoted text) and picks the top N.

**Alternatives considered:**
- Bundling NLTK data in the repo: rejected because punkt_tab is ~35MB and would bloat the repo
- Using a different summarizer that doesn't need NLTK: rejected because sumy/LSA is the best extractive option and works well when NLTK is available

**Status:** ACTIVE

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

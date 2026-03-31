"""Parallel LLM summarization using Google Gemini API with sumy fallback.

Each section (news, youtube, ai_security) gets its own Gemini
API call on a separate API key, running in parallel to avoid timeouts.
"""

import json
import logging
import os
import time as _time

from src.constants import (
    GEMINI_MAX_RETRIES,
    GEMINI_MODEL,
    GEMINI_RETRY_BASE_DELAY,
    MIN_EMOJI_BULLETS,
    MIN_BULLET_SEGMENTS,
    MIN_SUMMARY_LENGTH,
    MIN_TEXT_LENGTH_MEDIUM,
    MIN_TEXT_LENGTH_SHORT,
    TEXT_SAMPLE_CHUNK,
    TEXT_SKIP_INTRO,
    TEXT_TRUNCATE_NEWS,
    TEXT_TRUNCATE_PAPER,
    TEXT_TRUNCATE_YOUTUBE,
)
from src.summarizer import summarize

logger = logging.getLogger(__name__)

# Section keys in processing order — each gets its own API key
SECTION_KEYS = ["news", "youtube", "ai_security"]

def _get_api_keys() -> list[str]:
    """Collect all available Gemini API keys from environment variables."""
    keys = []
    for var in ["GEMINI_API_KEY", "GEMINI_API_KEY_2"]:
        k = os.getenv(var)
        if k:
            keys.append(k)
    return keys


def batch_summarize(sections: dict) -> dict:
    """Summarize all newsletter sections via parallel Gemini API calls.

    Each section gets its own API key and runs concurrently. Sections that
    fail fall back to sumy extractive summarizer independently.
    """
    api_keys = _get_api_keys()
    if not api_keys:
        logger.warning("No Gemini API keys available, using extractive fallback")
        return _fallback_summarize(sections)

    # Determine which sections have content
    active = [(key, sections[key]) for key in SECTION_KEYS if sections.get(key)]
    if not active:
        return {key: [] for key in SECTION_KEYS}

    logger.info("Starting parallel summarization: %d sections across %d API keys",
                len(active), min(len(active), len(api_keys)))

    result = {key: [] for key in SECTION_KEYS}

    def _summarize_section(section_key: str, items: list[dict], api_key: str) -> tuple[str, list[str]]:
        """Summarize one section with one API key. Retries on 429 rate limits."""
        from google import genai
        from google.genai import types
        prompt = _build_section_prompt(section_key, items)
        logger.info("Gemini call for %s (%d items, %d chars) using key ...%s",
                     section_key, len(items), len(prompt), api_key[-6:])
        client = genai.Client(api_key=api_key)
        for attempt in range(GEMINI_MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    ),
                )
                logger.info("Gemini %s response: %d chars", section_key, len(response.text))
                summaries = _parse_section_response(response.text, section_key, items)
                return section_key, summaries
            except Exception as e:
                err_str = str(e)
                if "429" in err_str:
                    # Daily quota exhaustion — retrying same key won't help
                    if "PerDay" in err_str:
                        logger.warning("Daily quota exhausted for key ...%s on %s",
                                       api_key[-6:], section_key)
                        raise
                    # Per-minute rate limit — retry after delay
                    if attempt < GEMINI_MAX_RETRIES - 1:
                        import re as _re
                        delay_match = _re.search(r'retry(?:\s+after)?\s+(\d+(?:\.\d+)?)\s*s', err_str, _re.IGNORECASE)
                        if delay_match:
                            wait = float(delay_match.group(1)) + 1
                        else:
                            wait = GEMINI_RETRY_BASE_DELAY * (attempt + 1)
                        logger.info("Rate limited on %s (attempt %d), retrying in %.1fs...",
                                    section_key, attempt + 1, wait)
                        _time.sleep(wait)
                    else:
                        raise
                else:
                    raise

    # Run sections in parallel, each on its own thread with round-robin key assignment
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _try_section(idx, section_key, items):
        assigned_keys = [api_keys[(idx + offset) % len(api_keys)] for offset in range(len(api_keys))]
        for api_key in assigned_keys:
            try:
                key, summaries = _summarize_section(section_key, items, api_key)
                logger.info("Section %s: got %d summaries", key, len(summaries))
                return key, summaries
            except Exception as e:
                err_str = str(e)
                if any(x in err_str.lower() for x in ["expired", "api key", "invalid"]) or "PerDay" in err_str:
                    logger.warning("Key ...%s unusable for %s (%s), trying next key.",
                                   api_key[-6:], section_key,
                                   "daily quota" if "PerDay" in err_str else "expired/invalid")
                    continue
                break
        logger.warning("All keys failed for %s. Using extractive fallback.", section_key)
        return section_key, _fallback_section(sections.get(section_key, []), section_key)

    with ThreadPoolExecutor(max_workers=len(active)) as executor:
        futures = {
            executor.submit(_try_section, idx, section_key, items): section_key
            for idx, (section_key, items) in enumerate(active)
        }
        for future in as_completed(futures):
            key, summaries = future.result()
            result[key] = summaries

    return result


def _base_instructions() -> str:
    """Shared prompt instructions for all sections."""
    return (
        "You are writing a daily briefing newsletter. The reader should NEVER need to click through, read the article, watch the episode, or read the paper. Your bullets ARE the content.\n\n"
        "Write exactly 3 bullet points per item — the top 3 key takeaways. Each bullet is a SEPARATE fact.\n\n"
        "FORMAT: EMOJI followed by one concise sentence with specific details (names, numbers, dates, outcomes).<br>\n"
        "Separate bullets with <br> within each item's string. No bold tags, no dash prefix, no lead-in phrase.\n\n"
        "HARD RULES:\n"
        "- Each bullet = one distinct, concrete fact with a specific detail (number, name, date, dollar figure, percentage, outcome).\n"
        "- DO NOT restate the headline. Each bullet adds NEW information.\n"
        "- NEVER reference the source: 'the episode explores', 'the paper proposes', 'the article highlights', 'the discussion focused on'. Just state the fact.\n"
        "- NEVER include ads, sponsors, promos, or discount codes.\n"
        "- For PODCASTS: Report the actual news/claims/data as standalone facts.\n"
        "- For PAPERS: Report findings/results/scores. If no results in the abstract, state the most specific technical detail.\n\n"
        "VAGUE BULLET TEST — if a bullet could apply to dozens of different articles, it's too vague. Rewrite it.\n"
        "FAIL examples (NEVER write bullets like these):\n"
        "- '📊 The episode explored the concept of X, highlighting that rapid success can create its own set of challenges.' → VAGUE. What challenges? What success? No facts.\n"
        "- '⚡ Viewership for the Winter Olympics has significantly increased.' → VAGUE. By how much? What numbers?\n"
        "- '🛠️ AI benefits skilled trades by reducing operational friction.' → VAGUE. What friction? What trades? What specifically happened?\n"
        "- '📈 Most critics respond to specific, solvable concerns.' → VAGUE. What concerns? Name them.\n"
        "- '🧠 Optimizing GPU kernels remains challenging due to complex design factors.' → VAGUE. What factors? What kernels?\n\n"
        "PASS examples (every bullet should read like these):\n"
        "- '📈 OpenAI spent $3B training GPT-5, 3x more than GPT-4, using 50,000 H100 GPUs over 90 days.'\n"
        "- '⚖️ The Supreme Court ruled 6-3 that Trump exceeded his authority by issuing tariffs under IEEPA, invalidating $170B in collected duties.'\n"
        "- '📉 Claude Opus 4.6 repeated the same 16-character password 18 out of 50 times, yielding only 27 bits of entropy vs. 98 expected.'\n\n"
        "If the source text lacks specific numbers or names, state the most concrete claim available — but NEVER pad with vague filler.\n\n"
        "SELF-CHECK: Re-read every bullet. Ask: 'Could this sentence apply to 10 different articles?' If yes, it's too vague — rewrite with a specific detail from the source.\n\n"
        "Return ONLY a valid JSON array, no markdown code blocks.\n\n"
    )


def _build_section_prompt(section_key: str, items: list[dict]) -> str:
    """Build a prompt for a single section."""
    import re
    parts = [_base_instructions()]

    if section_key == "news":
        parts.append("NEWS ARTICLES:")
        for i, item in enumerate(items, 1):
            text = (item.get("raw_text") or "")[:TEXT_TRUNCATE_NEWS]
            if len(text) < MIN_TEXT_LENGTH_SHORT:
                text = "(No article text available — write a brief, factual summary based on the headline.)"
            parts.append(f"{i}. [{item['title']}]: {text}")

    elif section_key == "youtube":
        parts.append(
            "CRITICAL: Cover ALL major topics discussed in the episode, not just one. Many podcasts cover 3-5 different stories. Your 3 bullets should capture the BREADTH of the episode — pick the top 3 most important/interesting topics, one bullet per topic. Do NOT write 3 bullets about the same topic.\n\n"
            "YOUTUBE VIDEOS — These are transcripts from tech/AI/business YouTubers.\n"
            "CRITICAL: Each video's transcript is enclosed between '--- VIDEO N START ---' and '--- VIDEO N END ---' markers. "
            "You MUST only use text within a video's markers to generate that video's summary. NEVER let content from one video leak into another video's summary.\n"
            "Your job: extract ACTIONABLE ADVICE the reader can apply TODAY.\n"
            "Think: 'If my friend watched this, what would they actually DO differently tomorrow?'\n\n"
            "PRIORITY ORDER for each bullet:\n"
            "1. A specific TIP, TECHNIQUE, or RECOMMENDATION the viewer should try (best)\n"
            "2. A surprising fact or number that changes how you think about something (good)\n"
            "3. A concrete claim or finding (acceptable)\n\n"
            "Frame bullets as advice when possible. Use 'Try...', 'Consider...', 'Use...', or state the tip directly.\n"
            "DO NOT quote the transcript verbatim. DO NOT just describe what the speaker said.\n\n"
            "Examples of BAD → GOOD:\n"
            "BAD: '🛠️ Karpathy himself operates in the autocomplete-assisted category.'\n"
            "GOOD: '🛠️ Try Karpathy\\'s middle-ground approach: write architecture yourself but let LLM autocomplete handle boilerplate — he finds agents work best for repetitive patterns already in training data.'\n\n"
            "BAD: '📱 Claude Code introduced a remote control feature that allows users to approve commands via phone.'\n"
            "GOOD: '📱 Enable Claude Code\\'s new remote control mode to approve terminal commands from your phone — lets you kick off long tasks and walk away from your desk.'\n\n"
            "BAD: '🧠 Beato theorizes that jazz improvisers achieve their best output before turning 30.'\n"
            "GOOD: '🧠 Beato\\'s observation: jazz musicians peak in novelty before 30 — if you\\'re learning an instrument, prioritize wild experimentation now over perfecting technique later.'\n"
        )
        for i, item in enumerate(items, 1):
            text = (item.get("raw_text") or "").strip()
            # Strip markdown formatting that leaks from RSS/website sources
            text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
            text = re.sub(r'---+', '', text)
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
            text = re.sub(r'[•·]\s*less than \d+ min read\s*', ' ', text)
            if len(text) > 1500:  # long enough to warrant sponsor stripping + sampling
                # Strip sponsor/ad segments
                text = re.sub(
                    r'(?i)(?:brought to you by|sponsored by|use code|promo code|sign up at|download it at|learn more at|check out|our sponsor|this episode is|discount|coupon|free trial|special offer|percent off|dollars off|\bpromo\b|partner event|go to \w+\.\w+)[^\n]{0,300}',
                    '', text
                )
                # Sample from beginning, 1/3, 2/3, and end to capture breadth of content
                text = text[TEXT_SKIP_INTRO:]  # skip intro
                total = len(text)
                chunk = TEXT_SAMPLE_CHUNK
                if total <= chunk * 3:
                    text = text[:chunk * 3].strip()
                else:
                    beginning = text[:chunk]
                    third = total // 3
                    mid1 = text[third:third + chunk]
                    mid2 = text[2 * third:2 * third + chunk]
                    end = text[-chunk:]
                    text = f"{beginning}\n[...]\n{mid1}\n[...]\n{mid2}\n[...]\n{end}"
            elif len(text) < MIN_TEXT_LENGTH_MEDIUM:
                text = "(No transcript available. Use your knowledge and web search to find what this episode covered and summarize the key topics.)"
            else:
                text = text[:TEXT_TRUNCATE_YOUTUBE]
            parts.append(f"\n--- VIDEO {i} START ---\n{i}. [{item.get('channel', '')} - {item['title']}]:\n{text}\n--- VIDEO {i} END ---")

    elif section_key == "ai_security":
        parts.append("AI SECURITY (papers and news articles):")
        for i, item in enumerate(items, 1):
            if item.get("type") == "paper":
                text = (item.get("raw_text") or "")[:TEXT_TRUNCATE_PAPER]
                if len(text) < 50:
                    text = "(No abstract available — summarize based on the paper title.)"
                parts.append(f"{i}. [PAPER: {item['title']}]: {text}")
            else:
                text = (item.get("raw_text") or "")[:TEXT_TRUNCATE_NEWS]
                if len(text) < MIN_TEXT_LENGTH_SHORT:
                    text = "(No article text available — write a brief, factual summary based on the headline.)"
                parts.append(f"{i}. [NEWS: {item['title']}]: {text}")

    example_emojis = {
        "news": '📈 First key fact.<br>💰 Second key fact.<br>🔍 Third key fact.',
        "youtube": '🎬 First takeaway.<br>⚡ Second takeaway.<br>📊 Third takeaway.',
        "ai_security": '🛡️ First finding.<br>🔍 Second finding.<br>⚠️ Third finding.',
    }

    parts.append(
        f'\nReturn a JSON array with EXACTLY {len(items)} strings, one per item above. '
        f'Each string has exactly 3 emoji bullets separated by <br>.\n'
        f'Example: ["{example_emojis.get(section_key, example_emojis["news"])}", ...]\n\n'
        f'CRITICAL: Return EXACTLY {len(items)} items. Never return an empty string.'
    )

    return "\n".join(parts)


def _parse_section_response(text: str, section_key: str, items: list[dict]) -> list[str]:
    """Parse Gemini's JSON array response for a single section."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    import re

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try fixing trailing commas
        fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            # Try extracting array from wrapper object
            match = re.search(r'\[', cleaned)
            if match:
                try:
                    data = json.loads(cleaned[match.start():])
                except json.JSONDecodeError:
                    logger.warning("Cannot parse %s response, using fallback", section_key)
                    return _fallback_section(items, section_key)
            else:
                return _fallback_section(items, section_key)

    # Handle dict wrapper: {"news": [...]} or {"items": [...]}
    if isinstance(data, dict):
        if section_key in data:
            data = data[section_key]
        else:
            # Take the first array value
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break

    if not isinstance(data, list):
        logger.warning("Gemini %s response is not a list, using fallback", section_key)
        return _fallback_section(items, section_key)

    # Truncate or pad
    if len(data) > len(items):
        data = data[:len(items)]
    elif len(data) < len(items):
        logger.warning("Gemini returned %d %s summaries, expected %d. Padding.", len(data), section_key, len(items))
        data.extend(_fallback_section(items[len(data):], section_key))

    # Coerce items to strings — Gemini sometimes returns dicts instead of strings
    for i, item in enumerate(data):
        if isinstance(item, dict):
            # Extract the summary string from common dict shapes
            data[i] = item.get("summary") or item.get("text") or item.get("content") or "<br>".join(
                str(v) for v in item.values() if isinstance(v, str)
            ) or str(item)
        elif not isinstance(item, str):
            data[i] = str(item)

    # Validate each summary
    for i, summary in enumerate(data):
        issue = _validate_summary(summary)
        if issue:
            logger.warning("Bad summary for %s item %d (%s): %s. Using fallback.",
                           section_key, i, items[i].get("title", ""), issue)
            data[i] = _fallback_section([items[i]], section_key)[0]

    return data



def _validate_summary(summary: str) -> str | None:
    """Validate a summary meets quality standards.

    Returns None if valid, or a string describing the issue.
    """
    import re
    if not summary or len(summary.strip()) < MIN_SUMMARY_LENGTH:
        return "empty or too short"

    # Must contain emoji characters (at least 2 — expect 3 bullets)
    # Count <br> separated segments that start with emoji-like chars
    emoji_pattern = re.compile(
        r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002702-\U000027B0'
        r'\U0000FE00-\U0000FE0F\U0000200D\U00002194-\U00002199'
        r'\U000023E9-\U000023F3\U000025AA-\U000025FE\U00002934-\U00002935'
        r'\U0000203C\U00002049\U00002122\U00002139\U00002328\U000023CF]'
    )
    emoji_count = len(emoji_pattern.findall(summary))
    # Also count <br>-separated bullet segments as a secondary check
    bullet_count = len(summary.split('<br>'))
    if emoji_count < MIN_EMOJI_BULLETS and bullet_count < MIN_BULLET_SEGMENTS:
        return f"only {emoji_count} emoji bullets and {bullet_count} segments (need at least 2)"

    # Must not start with lowercase or a fragment (sign of misaligned extraction)
    stripped = summary.strip()
    if stripped[0].islower():
        return "starts with lowercase (likely a fragment)"

    # Must not contain raw URLs as main content (sign of raw text leak)
    if re.match(r'^https?://', stripped):
        return "starts with URL (raw text leak)"

    # Must not contain common raw-text indicators
    raw_indicators = [
        "This episode", "Today's show:", "made possible by:",
        "https://Gusto.com", "calderalab.com", "circle.so",
    ]
    for indicator in raw_indicators:
        if indicator in summary:
            return f"contains raw text indicator: '{indicator}'"

    # Check for cut-off mid-sentence (ends without punctuation)
    last_char = stripped.rstrip()[-1] if stripped.rstrip() else ""
    if last_char not in ".!?)\"'…>0123456789%":
        return f"appears cut off (ends with '{last_char}')"

    # Check for verbatim transcript quotes (conversational speech patterns)
    conversational_patterns = [
        r'(?i)^[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002702-\U000027B0]+ (?:I would say|I think|So (?:speaking|basically|like|I\'m)|You know|And so|About that|Not something|come from|orrow )',
        r'(?i)(?:uh |um |like (?:three|two|a lot|\d)|you know,)',
        r'(?i)(?:but it it |and then |So I\'m out |I\'m out there)',
        r'(?i)(?:into like \d|feet one day|really dumping|middle of the)',
    ]
    for pattern in conversational_patterns:
        match = re.search(pattern, stripped)
        if match:
            return f"verbatim transcript quote detected: '{match.group()[:50]}'"

    # Check individual bullets for truncation (first chars eaten after emoji)
    bullets_list = stripped.split('<br>')
    for b in bullets_list:
        b = b.strip()
        if not b:
            continue
        # Extract text portion after the leading emoji character(s) + space
        text_after = b
        for ci, ch in enumerate(b):
            if ch.isascii() and (ch.isalpha() or ch in "\"'(,;0123456789"):
                text_after = b[ci:]
                break
        if not text_after:
            continue
        first_ch = text_after[0]
        # Starts with comma/semicolon → mid-sentence fragment
        if first_ch in ',;':
            return f"bullet starts with truncated text: '{text_after[:30]}'"
        # Starts with apostrophe followed by lowercase → contraction fragment ('t, 's, etc.)
        if first_ch == "'" and len(text_after) > 1 and text_after[1].islower():
            return f"bullet starts with contraction fragment: '{text_after[:30]}'"
        # Starts with lowercase letter → mid-word fragment
        if first_ch.islower():
            return f"bullet starts mid-word: '{text_after[:30]}'"

    # Check for semantically vague bullets — meta-descriptions that say nothing
    vague_patterns = [
        r'(?i)the (?:podcast|episode|article|paper|discussion) (?:discussed|explores?|highlights?|focused on|suggests?|argues?)',
        r'(?i)(?:might|could|may) (?:pose|create|introduce|present) (?:inherent |potential |new )?(?:problems|challenges|issues|concerns)',
        r'(?i)(?:significant|substantial|considerable) (?:increase|decrease|impact|implications)',
        r'(?i)(?:is (?:critical|essential|important|key|crucial)|remains challenging)',
        r'(?i)experienced a (?:significant|notable|substantial) (?:increase|decrease|growth|decline)',
    ]
    for pattern in vague_patterns:
        match = re.search(pattern, stripped)
        if match:
            return f"vague filler detected: '{match.group()}'"

    return None


def generate_trending_topics(ai_security_items: list[dict]) -> list[dict]:
    """Analyze AI security items to identify trending topics for purple teamers.

    Returns a list of dicts: [{"topic": str, "why": str, "action": str}, ...]
    Each item suggests a topic the reader should look into for career growth.
    """
    import os
    from google import genai
    from google.genai import types

    api_keys = _get_api_keys()
    if not api_keys or not ai_security_items:
        return []

    # Build context from today's papers and news
    items_text = []
    for i, item in enumerate(ai_security_items[:12], 1):
        item_type = item.get("type", "unknown")
        title = item.get("title", "")
        abstract = (item.get("abstract") or item.get("raw_text") or "")[:500]
        items_text.append(f"{i}. [{item_type.upper()}] {title}: {abstract}")

    prompt = (
        "You are a career coach for an AI security purple teamer (someone who does both "
        "offensive red-teaming AND defensive blue-teaming of AI/LLM systems).\n\n"
        "Based on today's AI security papers and news below, identify the TOP 3 topics "
        "trending RIGHT NOW in AI security. For each topic, explain:\n"
        "- What the topic is (1 short phrase)\n"
        "- Why it's trending this week (1 sentence, reference specific papers/news)\n"
        "- A concrete action the reader should take for their career growth "
        "(e.g. 'try building X', 'read up on Y technique', 'practice Z in a lab')\n\n"
        "Frame everything as direct advice: 'You might want to look into X because...'\n\n"
        "TODAY'S AI SECURITY ITEMS:\n" + "\n".join(items_text) + "\n\n"
        "Return ONLY a valid JSON array of 3 objects with keys: topic, why, action\n"
        "Example: [{\"topic\": \"Agentic prompt injection\", \"why\": \"3 new papers this week show agents are vulnerable to multi-step injection chains.\", \"action\": \"Set up a test harness with LangChain agents and try chaining indirect prompt injections across tool calls.\"}]\n"
    )

    for api_key in api_keys:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            import json as _json
            data = _json.loads(text)
            if isinstance(data, list) and len(data) >= 1:
                logger.info("Trending topics generated: %d items", len(data))
                return data[:3]
        except Exception as e:
            logger.warning("Trending topics generation failed with key ...%s: %s",
                           api_key[-6:], str(e)[:100])
            continue

    logger.warning("All keys failed for trending topics, returning empty")
    return []


def generate_ai_security_tldr(ai_security_items: list[dict]) -> str:
    """Generate a single-sentence TLDR about the emerging AI security trends this week.

    Returns a sentence explaining what trends are forming and why they matter,
    e.g.: "Autonomous red-teaming tools are proliferating as vendors race to
    probe LLM-powered apps before attackers do, while supply chain compromises
    in AI tooling show the ecosystem's dependency risks are growing."
    """
    import os
    from google import genai
    from google.genai import types

    api_keys = _get_api_keys()
    if not api_keys or not ai_security_items:
        return ""

    # Give the model titles + short abstracts for richer context
    items_text = []
    for item in ai_security_items[:12]:
        title = item.get("title", "")
        abstract = (item.get("abstract") or item.get("raw_text") or "")[:300]
        items_text.append(f"- {title}: {abstract}" if abstract else f"- {title}")
    items_str = "\n".join(items_text)

    prompt = (
        "Below are this week's AI security papers and articles.\n\n"
        f"{items_str}\n\n"
        "Write EXACTLY ONE sentence (max 40 words) about the AI security trends "
        "emerging this week and WHY they matter. Connect the dots across the items. "
        "Do not list titles. Do not use em dashes. Write directly and specifically. "
        "No quotes, no markdown. Return ONLY the sentence."
    )

    for api_key in api_keys:
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = response.text.strip().rstrip('.')
            # Basic sanity check
            if 10 < len(text) < 200 and not text.startswith('{'):
                logger.info("AI security TLDR generated: %s", text[:80])
                return text + '.'
        except Exception as e:
            logger.warning("AI security TLDR failed with key ...%s: %s",
                           api_key[-6:], str(e)[:80])
            continue

    # Fallback: build a simple TLDR from the most common themes in titles
    if ai_security_items:
        titles = " ".join(item.get("title", "") for item in ai_security_items).lower()
        themes = []
        theme_keywords = [
            ("supply chain", "supply chain attacks on AI tooling"),
            ("llm", "LLM security vulnerabilities"),
            ("prompt injection", "prompt injection techniques"),
            ("agent", "autonomous AI agent risks"),
            ("jailbreak", "jailbreak methods"),
            ("red team", "AI red-teaming developments"),
            ("vulnerability", "newly disclosed AI vulnerabilities"),
        ]
        for keyword, label in theme_keywords:
            if keyword in titles:
                themes.append(label)
            if len(themes) >= 2:
                break
        if themes:
            return f"This week's focus: {' and '.join(themes)}."
    return ""


def _fallback_summarize(sections: dict) -> dict:
    """Summarize all sections using sumy extractive summarizer."""
    return {
        key: _fallback_section(sections.get(key, []), key)
        for key in ("news", "youtube", "ai_security")
    }


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, protecting abbreviations from false splits."""
    import re
    # Protect common abbreviations by replacing their periods with a placeholder
    protected = text
    abbreviations = [
        'U.S.', 'U.S', 'U.K.', 'E.U.', 'D.C.',
        'Dr.', 'Mr.', 'Mrs.', 'Ms.', 'Prof.', 'Rev.', 'Gen.', 'Gov.',
        'Rep.', 'Sen.', 'Sgt.', 'Jr.', 'Sr.', 'St.', 'Mt.',
        'Inc.', 'Ltd.', 'Corp.', 'Co.', 'Bros.', 'Dept.', 'Assn.',
        'vs.', 'etc.', 'e.g.', 'i.e.', 'approx.', 'est.',
        'Jan.', 'Feb.', 'Mar.', 'Apr.', 'Jun.', 'Jul.', 'Aug.',
        'Sep.', 'Oct.', 'Nov.', 'Dec.', 'Ave.', 'Blvd.', 'Vol.', 'No.',
    ]
    PLACEHOLDER = '\x00'
    for abbr in abbreviations:
        protected = protected.replace(abbr, abbr.replace('.', PLACEHOLDER))

    # Split on sentence-ending punctuation followed by space and uppercase
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z\"\'\u201c\u2018])', protected)

    # Restore placeholders and filter
    sentences = []
    for p in parts:
        p = p.replace(PLACEHOLDER, '.').strip()
        if len(p) > 15:  # skip tiny fragments
            if p[-1] not in '.!?':
                p = p + '.'
            sentences.append(p)
    return sentences


def _is_clean_sentence(s: str) -> bool:
    """Check if a string looks like a complete sentence (not a fragment)."""
    s = s.strip()
    if not s or len(s) < 20:
        return False
    # Must start with uppercase letter, number, or opening quote
    if not (s[0].isupper() or s[0].isdigit() or s[0] in '""\u201c'):
        return False
    # Must not start with common fragment indicators
    if s[0] in ',;' or (s[0] == "'" and len(s) > 1 and s[1].islower()):
        return False
    return True


def _fallback_section(items: list[dict], section_type: str) -> list[str]:
    """Summarize a single section's items using sumy, formatted as emoji bullets.

    YouTube transcripts are conversational text that LexRank cannot meaningfully
    summarize, so YouTube items fall back to a description from the raw_text if available.
    """
    emojis = {
        "news": ["📰", "📢", "🔍"],
        "youtube": ["🎬", "⚡", "📊"],
        "ai_security": ["🛡️", "🔍", "⚠️"],
    }
    section_emojis = emojis.get(section_type, ["📌", "📎", "🔹"])
    results = []
    for item in items:
        # YouTube: LexRank on spoken transcripts produces verbatim gibberish.
        # Try to extract a few coherent sentences from the raw text instead.
        if section_type == "youtube":
            raw_text = (item.get("raw_text") or "").strip()
            if len(raw_text) > 200:
                sentences = _split_sentences(raw_text[:3000])
                # Pick first 3 sentences that are long enough and not sponsor/ad text
                import re
                ad_re = re.compile(r'(?i)(?:brought to you|sponsored by|use code|promo code|sign up at|free trial|percent off|dollars off)')
                good = [s for s in sentences if not ad_re.search(s) and _is_clean_sentence(s)][:3]
                if len(good) >= 2:
                    bullets = []
                    for j, sent in enumerate(good):
                        emoji = section_emojis[j % len(section_emojis)]
                        bullets.append(f"{emoji} {sent}")
                    results.append("<br>".join(bullets))
                    continue
            results.append(f"{section_emojis[0]} {item.get('title', 'No summary available.')}")
            continue
        raw = summarize(item.get("raw_text", ""), num_sentences=3, title=item.get("title", ""))
        if not raw or len(raw.strip()) < 20:
            # Minimal fallback from title
            results.append(f"{section_emojis[0]} {item.get('title', 'No summary available.')}")
            continue
        # Split extractive summary into sentences using robust splitter
        sentences = _split_sentences(raw.replace('<br>', ' '))
        # Filter out fragment sentences that don't start cleanly
        clean_sentences = [s for s in sentences if _is_clean_sentence(s)]
        # If extractive produced only fragments, fall back to raw text sentences
        if len(clean_sentences) < 2:
            raw_text = (item.get("raw_text") or "").strip()
            if len(raw_text) > 100:
                raw_sentences = _split_sentences(raw_text[:3000])
                clean_sentences = [s for s in raw_sentences if _is_clean_sentence(s)][:3]
        if not clean_sentences:
            results.append(f"{section_emojis[0]} {item.get('title', 'No summary available.')}")
            continue
        bullets = []
        for j, sent in enumerate(clean_sentences[:3]):
            emoji = section_emojis[j % len(section_emojis)]
            bullets.append(f"{emoji} {sent}")
        results.append("<br>".join(bullets) if bullets else f"{section_emojis[0]} {raw}")
    return results

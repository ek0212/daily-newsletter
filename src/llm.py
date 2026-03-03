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
        prompt = _build_section_prompt(section_key, items)
        logger.info("Gemini call for %s (%d items, %d chars) using key ...%s",
                     section_key, len(items), len(prompt), api_key[-6:])
        client = genai.Client(api_key=api_key)
        for attempt in range(GEMINI_MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
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

    # Run sections sequentially, assigning keys via round-robin so each section
    # gets a different key when possible (avoids two sections sharing one key).
    for idx, (section_key, items) in enumerate(active):
        # Round-robin: section 0 → key 0, section 1 → key 1, etc.
        assigned_keys = [api_keys[(idx + offset) % len(api_keys)] for offset in range(len(api_keys))]
        last_exc = None
        section_done = False
        for api_key in assigned_keys:
            try:
                key, summaries = _summarize_section(section_key, items, api_key)
                result[key] = summaries
                logger.info("Section %s: got %d summaries", key, len(summaries))
                section_done = True
                break
            except Exception as e:
                err_str = str(e)
                last_exc = e
                # Expired, invalid, or daily-quota-exhausted key — try the next key
                if any(x in err_str.lower() for x in ["expired", "api key", "invalid"]) or "PerDay" in err_str:
                    logger.warning("Key ...%s unusable for %s (%s), trying next key.",
                                   api_key[-6:], section_key,
                                   "daily quota" if "PerDay" in err_str else "expired/invalid")
                    continue
                # Any other error (500, network, etc.) — stop trying keys
                break
        if not section_done:
            logger.warning("All keys failed for %s: %s. Using extractive fallback.", section_key, last_exc)
            result[section_key] = _fallback_section(sections.get(section_key, []), section_key)

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
            "YOUTUBE VIDEOS — These are transcripts from tech/AI/business YouTubers.\n"
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
            if len(text) > 1000:  # long enough to warrant sponsor stripping + sampling
                # Strip sponsor/ad segments
                text = re.sub(
                    r'(?i)(?:brought to you by|sponsored by|use code|promo code|sign up at|download it at|learn more at|check out|our sponsor|this episode is|discount|coupon|free trial|special offer|percent off|dollars off|\bpromo\b|partner event|go to \w+\.\w+)[^\n]{0,300}',
                    '', text
                )
                # Sample from beginning, middle, and end to capture key content
                text = text[TEXT_SKIP_INTRO:]  # skip intro
                total = len(text)
                chunk = TEXT_SAMPLE_CHUNK
                if total <= chunk * 2:
                    text = text[:chunk * 2].strip()
                else:
                    beginning = text[:chunk]
                    mid_start = total // 2 - chunk // 2
                    middle = text[mid_start:mid_start + chunk]
                    end = text[-chunk:]
                    text = f"{beginning}\n[...]\n{middle}\n[...]\n{end}"
            elif len(text) < MIN_TEXT_LENGTH_MEDIUM:
                text = "(No transcript available — summarize based on the episode title and podcast context.)"
            else:
                text = text[:TEXT_TRUNCATE_YOUTUBE]
            parts.append(f"{i}. [{item.get('channel', '')} - {item['title']}]: {text}")

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


def _fallback_summarize(sections: dict) -> dict:
    """Summarize all sections using sumy extractive summarizer."""
    return {
        key: _fallback_section(sections.get(key, []), key)
        for key in ("news", "youtube", "ai_security")
    }


def _fallback_section(items: list[dict], section_type: str) -> list[str]:
    """Summarize a single section's items using sumy, formatted as emoji bullets.

    YouTube transcripts are conversational text that LexRank cannot meaningfully
    summarize, so YouTube items fall back to title-only display.
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
        # Use title-only fallback instead.
        if section_type == "youtube":
            results.append(f"{section_emojis[0]} {item.get('title', 'No summary available.')}")
            continue
        raw = summarize(item.get("raw_text", ""), num_sentences=3, title=item.get("title", ""))
        if not raw or len(raw.strip()) < 20:
            # Minimal fallback from title
            results.append(f"{section_emojis[0]} {item.get('title', 'No summary available.')}")
            continue
        # Split extractive summary into sentences and format as emoji bullets
        sentences = [s.strip() for s in raw.replace('<br>', ' ').split('. ') if s.strip()]
        bullets = []
        for j, sent in enumerate(sentences[:3]):
            emoji = section_emojis[j % len(section_emojis)]
            sent = sent.rstrip('.')
            bullets.append(f"{emoji} {sent}.")
        results.append("<br>".join(bullets) if bullets else f"{section_emojis[0]} {raw}")
    return results

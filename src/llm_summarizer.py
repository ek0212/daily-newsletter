"""LLM-powered editorial summarizer using Groq (Llama 3).

Replaces extractive summaries with concise, editorial ones that explain
what happened and why it matters. Falls back to the existing extractive
summary if the Groq API is unavailable or the key is not set.
"""

import logging
import os
import re
import time

from src.constants import (
    GROQ_MAX_TOKENS,
    GROQ_MODEL,
    GROQ_RATE_LIMIT_DELAY,
    GROQ_TEMPERATURE,
    GROQ_MAX_INPUT_CHARS,
    MAX_SUMMARY_CHARS,
)

logger = logging.getLogger(__name__)

_groq_client = None


def _get_client():
    """Lazy-init Groq client. Returns None if key not set."""
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key.startswith("your-"):
        logger.info("GROQ_API_KEY not set, LLM summarizer disabled")
        return None
    try:
        from groq import Groq
        _groq_client = Groq(api_key=api_key)
        logger.info("Groq client initialized (model: %s)", GROQ_MODEL)
        return _groq_client
    except Exception as e:
        logger.warning("Failed to init Groq client: %s", e)
        return None


# ── Prompts per section type ─────────────────────────────────────────────

_NEWS_SYSTEM = (
    "You write 2-sentence news summaries for a daily briefing read by a busy NYC professional.\n"
    "Sentence 1: WHAT happened, with specifics (who, where, numbers, dates).\n"
    "Sentence 2: WHY it matters, what changes, or what happens next. This sentence is mandatory "
    "and must go beyond restating the headline. Connect it to a consequence, a trend, or a decision "
    "the reader might face.\n"
    "Rules:\n"
    "- If a claim cites a study or statistic, name the source and sample size.\n"
    "- If the source text is login-wall junk, garbled, or too thin for 2 real sentences, respond: SKIP\n"
    "- Never invent facts. No filler phrases. No 'developing story' or 'click for details.'\n"
    "- Keep it under 250 characters total."
)

_YOUTUBE_SYSTEM = (
    "You write 2-sentence summaries of video/podcast episodes for a daily briefing.\n"
    "Sentence 1: The core argument, finding, or claim of this episode, with specifics.\n"
    "Sentence 2: One concrete takeaway, a surprising detail, or why it's worth 30 minutes "
    "of the reader's time. Be specific, not generic.\n"
    "Rules:\n"
    "- If the transcript is too thin or garbled, respond: SKIP\n"
    "- No filler like 'new episode', 'interesting discussion', 'great conversation.'\n"
    "- Keep it under 250 characters total."
)

_PAPER_SYSTEM = (
    "You write 2-sentence paper summaries for security practitioners.\n"
    "Sentence 1: What the paper proposes or demonstrates, with the key technical idea in plain English.\n"
    "Sentence 2: Why a practitioner should care: what attack it stops, what defense it enables, "
    "or what blind spot it reveals. Be concrete.\n"
    "Rules:\n"
    "- If the abstract is too vague to summarize concretely, respond: SKIP\n"
    "- No jargon-only sentences. No marketing language.\n"
    "- Keep it under 250 characters total."
)

_AI_NEWS_SYSTEM = (
    "You write 2-sentence summaries of AI security news for practitioners and red-teamers.\n"
    "Sentence 1: The specific finding, incident, or development, with concrete details "
    "(names, numbers, affected systems, dates).\n"
    "Sentence 2: What this means for someone defending or testing AI systems.\n"
    "Rules:\n"
    "- If the article is generic advice ('why X matters', 'top 10 tips', 'explore Y'), respond: SKIP\n"
    "- Name sources for any statistics or claims.\n"
    "- No LinkedIn filler. No slogans.\n"
    "- Keep it under 250 characters total."
)


def _build_user_prompt(item: dict) -> str:
    """Build the user message for a single item."""
    title = item.get("title", "").strip()
    source = item.get("source", "").strip()
    raw_text = (item.get("raw_text") or item.get("abstract") or "").strip()

    # Truncate raw text to stay within token budget
    if len(raw_text) > GROQ_MAX_INPUT_CHARS:
        raw_text = raw_text[:GROQ_MAX_INPUT_CHARS] + "..."

    parts = []
    if title:
        parts.append(f"Title: {title}")
    if source:
        parts.append(f"Source: {source}")
    if raw_text:
        parts.append(f"Text: {raw_text}")
    else:
        parts.append("Text: [none available]")

    return "\n".join(parts)


def _get_system_prompt(section: str) -> str:
    """Return the appropriate system prompt for the section type."""
    return {
        "news": _NEWS_SYSTEM,
        "youtube": _YOUTUBE_SYSTEM,
        "paper": _PAPER_SYSTEM,
        "ai_news": _AI_NEWS_SYSTEM,
    }.get(section, _NEWS_SYSTEM)


def _call_groq(client, system_prompt: str, user_prompt: str) -> str | None:
    """Make a single Groq API call. Returns the response text or None on error.

    Handles 429 rate limits by reading retry-after and waiting.
    """
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=GROQ_MAX_TOKENS,
            temperature=GROQ_TEMPERATURE,
        )
        text = response.choices[0].message.content.strip()
        if text.upper() == "SKIP":
            return "SKIP"
        return text
    except Exception as e:
        err_str = str(e)
        # Handle rate limit: wait and retry once
        if "429" in err_str or "rate_limit" in err_str.lower():
            wait = 10
            logger.warning("Groq rate limit hit, waiting %ds", wait)
            time.sleep(wait)
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=GROQ_MAX_TOKENS,
                    temperature=GROQ_TEMPERATURE,
                )
                text = response.choices[0].message.content.strip()
                if text.upper() == "SKIP":
                    return "SKIP"
                return text
            except Exception as retry_e:
                logger.warning("Groq retry failed: %s", retry_e)
                return None
        logger.warning("Groq API call failed: %s", e)
        return None


def _clean_llm_summary(text: str) -> str:
    """Clean and cap LLM output."""
    # Remove any leading "Summary:" or "Here is..." preamble
    text = re.sub(r'^(?:summary|here (?:is|are)[^:]*):?\s*', '', text, flags=re.IGNORECASE)
    # Cap length at sentence boundary
    if len(text) > MAX_SUMMARY_CHARS:
        truncated = text[:MAX_SUMMARY_CHARS]
        for delim in ['. ', '? ', '! ']:
            pos = truncated.rfind(delim)
            if pos > MAX_SUMMARY_CHARS // 3:
                text = truncated[:pos + 1]
                break
        else:
            text = truncated.rsplit(' ', 1)[0] + "..."
    return text


def _bold_key_terms(summary: str, title: str = "") -> str:
    """Bold numbers/statistics and quoted text in summary."""
    summary = re.sub(
        r'(?<!\w)(\$?\d[\d,]*\.?\d*\s*%|\$\d[\d,]*\.?\d*[BMK]?|\d[\d,]*\.?\d*\s*(?:percent|million|billion|thousand))',
        r'<strong>\1</strong>',
        summary,
        flags=re.IGNORECASE,
    )
    summary = re.sub(r'"([^"]+)"', r'"<strong>\1</strong>"', summary)
    return summary


def enhance_summaries(items: list[dict], section: str) -> list[dict]:
    """Replace extractive summaries with LLM-generated editorial summaries.

    Processes items in place. Falls back to existing summary if LLM fails.
    Items where the LLM returns SKIP are flagged with 'llm_skip': True,
    so the caller can decide whether to drop them.

    Args:
        items: list of item dicts (must have 'title', optionally 'raw_text', 'summary')
        section: one of 'news', 'youtube', 'paper', 'ai_news'

    Returns:
        The same list (modified in place) for convenience.
    """
    client = _get_client()
    if client is None:
        return items

    system_prompt = _get_system_prompt(section)
    skipped = 0
    enhanced = 0

    for i, item in enumerate(items):
        user_prompt = _build_user_prompt(item)
        result = _call_groq(client, system_prompt, user_prompt)

        if result == "SKIP":
            item["llm_skip"] = True
            skipped += 1
            logger.debug("LLM skipped: %s", item.get("title", "")[:60])
        elif result:
            cleaned = _clean_llm_summary(result)
            item["summary"] = _bold_key_terms(cleaned, item.get("title", ""))
            enhanced += 1
        # else: keep existing extractive summary

        # Rate limit between calls (not after the last one)
        if i < len(items) - 1:
            time.sleep(GROQ_RATE_LIMIT_DELAY)

    logger.info(
        "LLM summarizer [%s]: %d enhanced, %d skipped, %d unchanged out of %d",
        section, enhanced, skipped, len(items) - enhanced - skipped, len(items),
    )
    return items

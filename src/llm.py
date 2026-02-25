"""Batched LLM summarization using Google Gemini API with sumy fallback."""

import json
import logging
import os

from src.summarizer import summarize

logger = logging.getLogger(__name__)


def batch_summarize(sections: dict) -> dict:
    """Summarize all newsletter content in a single Gemini API call.

    Args:
        sections: dict with keys 'news', 'podcasts', 'papers', each a list of
                  dicts containing 'title' and 'raw_text' fields.

    Returns:
        dict with same keys, each containing a list of summary strings.
        Falls back to sumy extractive summarizer if Gemini fails.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("No GEMINI_API_KEY set, using extractive fallback")
        return _fallback_summarize(sections)

    logger.info("Starting batch summarization via Gemini (gemini-2.5-flash)")
    prompt = _build_prompt(sections)
    n_news = len(sections.get("news", []))
    n_sec = len(sections.get("ai_security_news", []))
    n_pods = len(sections.get("podcasts", []))
    n_papers = len(sections.get("papers", []))
    logger.debug("Prompt size: %d chars, %d items total (news: %d, ai_security_news: %d, podcasts: %d, papers: %d)",
                 len(prompt), n_news + n_sec + n_pods + n_papers, n_news, n_sec, n_pods, n_papers)

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        logger.info("Gemini API call successful, response: %d chars", len(response.text))
        result = _parse_response(response.text, sections)
        logger.debug("Parsed summaries: news=%d, ai_security_news=%d, podcasts=%d, papers=%d",
                     len(result.get("news", [])), len(result.get("ai_security_news", [])),
                     len(result.get("podcasts", [])), len(result.get("papers", [])))
        return result
    except Exception as e:
        logger.warning("Gemini call failed: %s, falling back to extractive summarizer", e)
        return _fallback_summarize(sections)


def _build_prompt(sections: dict) -> str:
    """Build the single prompt for batch summarization."""
    parts = [
        "You are writing a daily briefing newsletter. The reader should NEVER need to click through, read the article, watch the episode, or read the paper. Your bullets ARE the content.\n\n"
        "Write exactly 3 bullet points per item — the top 3 key takeaways. Each bullet is a SEPARATE fact.\n\n"
        "FORMAT: EMOJI followed by one concise sentence with specific details (names, numbers, dates, outcomes).<br>\n"
        "Separate bullets with <br> within each item's string. No bold tags, no dash prefix, no lead-in phrase.\n\n"
        "HARD RULES:\n"
        "- Each bullet = one distinct, concrete fact with a specific detail (number, name, date, dollar figure, percentage, outcome).\n"
        "- DO NOT restate the headline. Each bullet adds NEW information.\n"
        "- NEVER write meta-descriptions: 'the episode discusses', 'the paper proposes', 'the article explores'. Report the fact directly.\n"
        "- NEVER write filler: 'raises questions', 'significant implications', 'could revolutionize', 'demands attention', 'is critical', 'remains challenging'.\n"
        "- NEVER include ads, sponsors, promos, or discount codes.\n"
        "- For PODCASTS: Report the actual news/claims/data from the episode as facts. 'Opus 4.6 achieves 14.5-hour time horizon' NOT 'the episode discussed AI capabilities'.\n"
        "- For PAPERS: Report findings, results, benchmark scores. NOT 'the paper proposes a framework'. If no results, report the most specific technical detail (dataset size, model, task).\n\n"
        "EXAMPLE:\n"
        "BAD: '📈 <strong>AI growth creates challenges</strong> — AI introduces complex hurdles that demand attention.'\n"
        "GOOD: '📈 OpenAI spent $3B training GPT-5, 3x more than GPT-4, using 50,000 H100 GPUs over 90 days.<br>💰 Total 2024 compute spending passed $7B, doubling from 2023.<br>⚡ The training run occupied an entire 50MW data center in Texas for the full 90 days.'\n\n"
        "SELF-CHECK: Every item must have exactly 3 bullets separated by <br>. Each bullet starts with an emoji and states a concrete fact.\n\n"
        "Return ONLY valid JSON, no markdown code blocks.\n\n"
    ]

    if sections.get("news"):
        parts.append("\nNEWS ARTICLES:")
        for i, item in enumerate(sections["news"], 1):
            text = (item.get("raw_text") or "")[:3000]
            if len(text) < 100:
                text = "(No article text available — write a brief, factual summary based on the headline.)"
            parts.append(f"{i}. [{item['title']}]: {text}")

    if sections.get("podcasts"):
        parts.append("\nPODCAST EPISODES:")
        for i, item in enumerate(sections["podcasts"], 1):
            text = (item.get("raw_text") or "").strip()
            if len(text) > 1000:
                # Strip sponsor/ad blocks before sending to LLM
                import re
                text = re.sub(
                    r'(?i)(?:brought to you by|sponsored by|use code|promo code|sign up at|download it at|learn more at|check out|our sponsor|this episode is|discount|coupon|free trial|special offer|percent off|dollars off|\bpromo\b|partner event|go to \w+\.\w+)[^\n]{0,300}',
                    '', text
                )
                # Skip intros, take substantive middle
                text = text[200:8000].strip()
            elif len(text) < 200:
                # No real transcript — tell Gemini to infer from title
                text = "(No transcript available — summarize based on the episode title and podcast context.)"
            else:
                text = text[:5000]
            parts.append(f"{i}. [{item.get('podcast', '')} - {item['title']}]: {text}")

    if sections.get("papers"):
        parts.append("\nARXIV PAPERS:")
        for i, item in enumerate(sections["papers"], 1):
            text = (item.get("raw_text") or "")[:1500]
            if len(text) < 50:
                text = "(No abstract available — summarize based on the paper title.)"
            parts.append(f"{i}. [{item['title']}]: {text}")

    if sections.get("ai_security_news"):
        parts.append("\nAI SECURITY NEWS ARTICLES:")
        for i, item in enumerate(sections["ai_security_news"], 1):
            text = (item.get("raw_text") or "")[:3000]
            if len(text) < 100:
                text = "(No article text available — write a brief, factual summary based on the headline.)"
            parts.append(f"{i}. [{item['title']}]: {text}")

    parts.append(
        '\nReturn JSON exactly like this (same number of items per section, exactly 3 emoji bullets per item):\n'
        '{\n'
        '  "news": ["📈 First key fact with specifics.<br>💰 Second key fact.<br>🔍 Third key fact.", ...],\n'
        '  "ai_security_news": ["🛡️ First fact.<br>🔍 Second fact.<br>⚠️ Third fact.", ...],\n'
        '  "podcasts": ["🎯 First takeaway.<br>⚡ Second takeaway.<br>📊 Third takeaway.", ...],\n'
        '  "papers": ["🧠 First finding.<br>📊 Second finding.<br>⚙️ Third finding.", ...]\n'
        '}\n\n'
        'CRITICAL: Every array must have EXACTLY the same number of items as the input. Every item MUST have exactly 3 bullets separated by <br>. Never return an empty string.'
    )

    return "\n".join(parts)


def _extract_arrays_fallback(text: str, sections: dict) -> dict | None:
    """Extract summary arrays from malformed JSON using regex."""
    import re
    data = {}
    for key in ("news", "ai_security_news", "podcasts", "papers"):
        # Find the array for this key: "key": [...]
        pattern = rf'"{key}"\s*:\s*\['
        match = re.search(pattern, text)
        if not match:
            continue
        # Find matching closing bracket
        start = match.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
            i += 1
        array_content = text[start:i - 1]
        # Split on '", "' pattern (between array items) — items are quoted strings
        # Use a pattern that finds string boundaries
        items = []
        in_str = False
        current = []
        for j, ch in enumerate(array_content):
            if ch == '"' and (j == 0 or array_content[j - 1] != '\\'):
                in_str = not in_str
                if in_str and not current:
                    continue  # opening quote
                elif not in_str:
                    items.append(''.join(current))
                    current = []
                    continue
            if in_str:
                current.append(ch)
        if current:
            items.append(''.join(current))
        data[key] = items
    if data:
        logger.info("Fallback JSON extraction recovered: %s",
                     {k: len(v) for k, v in data.items()})
        return data
    return None


def _parse_response(text: str, sections: dict) -> dict:
    """Parse Gemini's JSON response, validating item counts."""
    # Strip markdown code blocks if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("Initial JSON parse failed: %s. Attempting repair.", e)
        import re
        # Fix trailing commas
        fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
        # Fix unescaped double quotes inside strings by replacing inner quotes
        # Strategy: extract each array value between outer quotes, escape inner quotes
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            # Last resort: extract arrays manually using bracket matching
            data = _extract_arrays_fallback(fixed, sections)
            if data is None:
                raise

    result = {}
    for key in ("news", "ai_security_news", "podcasts", "papers"):
        expected = len(sections.get(key, []))
        got = data.get(key, [])
        if len(got) > expected:
            logger.warning("Gemini returned %d %s summaries, expected %d. Truncating.", len(got), key, expected)
            got = got[:expected]
        elif len(got) < expected:
            logger.warning("Gemini returned %d %s summaries, expected %d. Padding with fallback.", len(got), key, expected)
            missing = sections.get(key, [])[len(got):]
            got.extend(_fallback_section(missing, key))
        # Replace any empty/blank summaries with fallback for that item
        items = sections.get(key, [])
        for i, summary in enumerate(got):
            if not summary or len(summary.strip()) < 10:
                logger.warning("Gemini returned empty/short summary for %s item %d (%s): %r. Using fallback.",
                               key, i, items[i].get("title", ""), summary[:50] if summary else "")
                got[i] = _fallback_section([items[i]], key)[0]
        result[key] = got

    return result


def _fallback_summarize(sections: dict) -> dict:
    """Summarize all sections using sumy extractive summarizer."""
    return {
        key: _fallback_section(sections.get(key, []), key)
        for key in ("news", "ai_security_news", "podcasts", "papers")
    }


def _fallback_section(items: list[dict], section_type: str) -> list[str]:
    """Summarize a single section's items using sumy."""
    sentence_counts = {"news": 3, "ai_security_news": 3, "podcasts": 4, "papers": 2}
    n = sentence_counts.get(section_type, 2)
    return [summarize(item.get("raw_text", ""), num_sentences=n, title=item.get("title", "")) for item in items]

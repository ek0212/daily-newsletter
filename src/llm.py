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
        "You are a senior Axios editor. For each item, write 2-4 bullet points — only as many as there are distinct, concrete facts worth reporting.\n\n"
        "FORMAT: EMOJI <strong>Bold 3-8 word fact</strong> — One sentence with the KEY specifics (names, numbers, dates, amounts, outcomes).<br>\n\n"
        "RULES:\n"
        "- Every bullet MUST contain a concrete detail: a number, dollar figure, name, date, percentage, or specific outcome. NO exceptions.\n"
        "- GOAL: A reader skimming these bullets should learn everything important WITHOUT reading the article, watching the episode, or reading the paper. Your summary IS the content — not a teaser.\n"
        "- DO NOT restate the headline. Each bullet must add new information beyond what the title says.\n"
        "- NEVER use meta-descriptions like 'the episode discusses', 'the paper proposes', 'the article explores', 'the discussion highlights'. State the FACT directly as if you are reporting it, not describing someone else's content.\n"
        "- NEVER write vague filler like 'raises questions', 'significant implications', 'could revolutionize', 'demands attention', 'is key', 'offers promise', 'empowering operators', 'unlocking scale'.\n"
        "- NEVER summarize ads, sponsors, promos, discount codes, or partner events. Replace with a substantive point.\n"
        "- For PODCASTS: Extract the actual claims, data points, and news reported. If a host says 'GPT-5 can now do X', your bullet is about GPT-5 doing X — not about 'the host discusses GPT-5'.\n"
        "- For PAPERS: What did they FIND? What % improvement? What benchmark score? If the abstract only describes methodology, extract the most concrete technical detail.\n\n"
        "EXAMPLE — BAD vs GOOD:\n"
        "BAD: '📈 <strong>AI growth creates new challenges</strong> — The rapid exponential growth of AI introduces complex societal and technical hurdles that demand attention.'\n"
        "WHY BAD: Zero facts. What challenges? What growth? This tells the reader nothing.\n"
        "GOOD: '📈 <strong>GPT-5 costs $3B to train</strong> — OpenAI spent 3x more than GPT-4, using 50,000 H100 GPUs over 90 days, pushing total 2024 compute spend past $7B.'\n"
        "WHY GOOD: Specific dollar amounts, hardware, timeframes. Reader learned something.\n\n"
        "PODCAST BAD: '🛠️ <strong>AI benefits plumbers over programmers</strong> — The episode suggests that AI could be more beneficial for skilled trades by reducing operational friction.'\n"
        "WHY BAD: 'The episode suggests' is meta. 'Reducing operational friction' is corporate filler. WHAT specifically does AI do for plumbers?\n"
        "PODCAST GOOD: '🛠️ <strong>Solo plumber now handles 40 jobs/week</strong> — A one-person plumbing business used AI scheduling and invoicing agents to go from 15 to 40 jobs per week without hiring, tripling revenue to $300K.'\n"
        "WHY GOOD: Specific person, specific numbers, specific tools. Reader learned the actual claim.\n\n"
        "PAPER BAD: '🧠 <strong>Framework bridges reasoning gap</strong> — The paper proposes a hybrid framework to bridge the gap between two types of models.'\n"
        "PAPER GOOD: '🧠 <strong>Hybrid approach boosts accuracy 12%</strong> — Injecting domain knowledge from fine-tuned time-series models into GPT-4 improved diagnostic accuracy from 61% to 73% on SenTSR-Bench.'\n\n"
        "SELF-CHECK: Before returning, re-read each bullet. If it contains NO specific fact (name/number/date/outcome), rewrite it with one from the source text. If the source lacks specifics, state the most concrete claim available.\n\n"
        "Return ONLY valid JSON, no markdown code blocks. Every item MUST get a summary; infer from headline if text is missing.\n\n"
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
        '\nReturn JSON exactly like this (with the same number of items per section):\n'
        '{\n'
        '  "news": ["📈 <strong>Bold headline</strong> — detail.<br>💰 <strong>Another point</strong> — detail.<br>🔍 <strong>Third point</strong> — detail.", ...],\n'
        '  "ai_security_news": ["🛡️ <strong>Bold headline</strong> — detail.<br>🔍 <strong>Another point</strong> — detail.", ...],\n'
        '  "podcasts": ["🎯 <strong>Bold headline</strong> — detail.<br>⚡ <strong>Another point</strong> — detail.", ...],\n'
        '  "papers": ["🧠 <strong>Bold headline</strong> — detail.<br>📊 <strong>Another point</strong> — detail.", ...]\n'
        '}\n\n'
        'IMPORTANT: Every array must have EXACTLY the same number of items as the input. Never return an empty string for any item.'
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

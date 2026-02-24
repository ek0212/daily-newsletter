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
        "You are an expert editor at Axios or a top tech newsletter like Techpresso. "
        "Distill each item into exactly 3 ultra-concise, high-impact bullet points that capture the absolute core takeaways.\n\n"
        "STRICT STYLE RULES — follow every one:\n"
        "- Each bullet starts with a relevant, vibe-matching emoji (e.g. 📈 💰 🚨 ⚡ 📉 🛡️ 🔥 🔍 🎯 🤖 🧠).\n"
        "- After the emoji: a <strong>bolded, ultra-short headline phrase</strong> (3–8 words max) that states a SPECIFIC fact.\n"
        "- Then: 1 short sentence with the KEY DETAIL — a name, number, dollar amount, percentage, date, decision, or concrete outcome.\n"
        "- The reader should NOT need to click the article. Your bullets ARE the article. They must contain the actual information.\n"
        "- Use active voice, strong verbs, and ALWAYS include numbers/stats/names when they exist in the source.\n"
        "- DO NOT restate or paraphrase the headline.\n"
        "- NEVER write vague commentary like 'challenges common perceptions', 'highlights potential', 'significant implications', 'raising questions about', 'could revolutionize'. "
        "If you can't state a SPECIFIC fact, skip that bullet and find one you can.\n"
        "- NEVER include a heading like 'Key Takeaways' — just the bullets.\n"
        "- IGNORE all ads, sponsor reads, promo codes in podcasts.\n\n"
        "BAD (vague, useless): '🛠️ <strong>Enhancing hands-on professions</strong> — AI tools can optimize complex physical tasks, providing significant efficiency gains in fields like plumbing.'\n"
        "GOOD (specific, I learned something): '🛠️ <strong>Plumbers can scale without hiring</strong> — Agentic AI handles scheduling, invoicing, and customer follow-ups, letting a solo plumber run a $500K/yr operation that previously needed 3 office staff.'\n\n"
        "BAD (restates headline): '📉 <strong>Stock futures decline</strong> — Markets fell amid uncertainty about new tariff policies.'\n"
        "GOOD (tells me what happened): '📉 <strong>S&P futures down 0.8% pre-market</strong> — Trump\\'s proposed 25% tariff on EU auto imports rattled exporters; BMW and Mercedes dropped 3-4% in Frankfurt trading.'\n\n"
        "FORMATTING:\n"
        "- Each summary is a single HTML string with bullet points separated by <br> tags.\n"
        "- Format each bullet as: EMOJI <strong>Bold headline phrase</strong> — Detail sentence.<br>\n"
        "- For news: exactly 3 bullets.\n"
        "- For podcasts: exactly 3 bullets.\n"
        "- For papers: exactly 3 bullets.\n\n"
        "CRITICAL: Every item MUST get a summary. If the article text is short or missing, infer from the headline. Never return an empty string.\n\n"
        "Return ONLY valid JSON with no markdown formatting or code blocks.\n\n"
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
                # Skip sponsor reads / intros at the start of transcripts
                text = text[500:5500]
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


def _parse_response(text: str, sections: dict) -> dict:
    """Parse Gemini's JSON response, validating item counts."""
    # Strip markdown code blocks if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    data = json.loads(cleaned)

    result = {}
    for key in ("news", "ai_security_news", "podcasts", "papers"):
        expected = len(sections.get(key, []))
        got = data.get(key, [])
        if len(got) == expected:
            result[key] = got
        else:
            # Count mismatch — fall back to sumy for this section
            logger.warning("Gemini returned %d %s summaries, expected %d. Using fallback.", len(got), key, expected)
            result[key] = _fallback_section(sections.get(key, []), key)

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

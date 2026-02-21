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
        "You are writing summaries for a daily newsletter read by a busy professional. "
        "Your job is to give them the specific facts so they don't have to read/listen to the original.\n\n"
        "CRITICAL RULES:\n"
        "- Every sentence must contain a SPECIFIC fact: a name, number, dollar amount, date, decision, or outcome.\n"
        "- NEVER end with vague commentary like 'this could have significant implications' or 'raising questions about'. "
        "If you can't state a concrete implication with specifics, don't include it.\n"
        "- DO NOT restate or paraphrase the headline. Start with the most important detail NOT in the headline.\n"
        "- Write like you're telling a coworker in 15 seconds what actually happened. "
        "They should walk away knowing the key facts, not wondering what the article said.\n\n"
        "BAD example: 'This links two major fiscal policies and could lead to a significant financial impact on property owners.'\n"
        "GOOD example: 'NYC Council member <strong>Mamdani</strong> wants a <strong>wealth tax on assets over $5M</strong> to fund affordable housing. "
        "If it fails, he says he\\'ll push a <strong>9.5% property tax hike</strong> — roughly <strong>$800/year more</strong> for a median Brooklyn homeowner.'\n\n"
        "Return ONLY valid JSON with no markdown formatting or code blocks.\n\n"
        "FORMATTING RULES:\n"
        "- Use <strong> tags to bold the phrases that hammer home the key takeaway — the part someone would highlight if skimming. "
        "Bold multi-word phrases, not isolated keywords. E.g. '<strong>banned all new gas car sales starting 2035</strong>', "
        "not '<strong>banned</strong> all new <strong>gas car</strong> sales starting <strong>2035</strong>'.\n"
        "- For news: 2-3 sentences of specific facts.\n"
        "- For podcasts: 3-4 sentences. Pull out the most concrete claims, numbers, or predictions the speakers made. "
        "IGNORE all ads, sponsor reads, promo codes, and product pitches (e.g. 'brought to you by', 'use code', 'check out', 'sign up at'). "
        "Never mention sponsors, advertisers, or promotional URLs in your summary.\n"
        "- For papers: 1-2 sentences. State what the method achieves and the specific result (e.g. accuracy, improvement percentage).\n\n"
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
        '  "news": ["2-3 sentence summary with <strong>key takeaway phrases</strong> bolded.", ...],\n'
        '  "ai_security_news": ["2-3 sentence summary with <strong>key takeaway phrases</strong> bolded.", ...],\n'
        '  "podcasts": ["3-4 sentence summary with <strong>key takeaway phrases</strong> bolded.", ...],\n'
        '  "papers": ["1-2 sentence summary with <strong>key takeaway phrases</strong> bolded.", ...]\n'
        '}'
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

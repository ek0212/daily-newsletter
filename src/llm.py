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

    logger.info("Starting batch summarization via Gemini (gemini-2.0-flash)")
    prompt = _build_prompt(sections)
    n_news = len(sections.get("news", []))
    n_pods = len(sections.get("podcasts", []))
    n_papers = len(sections.get("papers", []))
    logger.debug("Prompt size: %d chars, %d items total (news: %d, podcasts: %d, papers: %d)",
                 len(prompt), n_news + n_pods + n_papers, n_news, n_pods, n_papers)

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        logger.info("Gemini API call successful, response: %d chars", len(response.text))
        result = _parse_response(response.text, sections)
        logger.debug("Parsed summaries: news=%d, podcasts=%d, papers=%d",
                     len(result.get("news", [])), len(result.get("podcasts", [])), len(result.get("papers", [])))
        return result
    except Exception as e:
        logger.warning("Gemini call failed: %s, falling back to extractive summarizer", e)
        return _fallback_summarize(sections)


def _build_prompt(sections: dict) -> str:
    """Build the single prompt for batch summarization."""
    parts = [
        "Summarize the following content for a daily newsletter. "
        "Return ONLY valid JSON with no markdown formatting or code blocks.\n\n"
        "IMPORTANT FORMATTING RULES:\n"
        "- Use <strong> tags to bold key terms, names, and numbers in every summary.\n"
        "- For news: bold the most important fact or figure in each summary.\n"
        "- For podcasts: bold guest names and key topics discussed.\n"
        "- For papers: bold the technique name and key finding.\n"
        '- Example: "Researchers at <strong>MIT</strong> found that <strong>prompt injection attacks</strong> succeed <strong>73% of the time</strong> against unguarded models."\n'
        "- Also include a one-sentence key takeaway for each item, prefixed with 'KEY: '.\n"
        "  This KEY sentence should be the single most important point, bolded entirely.\n\n"
    ]

    if sections.get("news"):
        parts.append("\nNEWS ARTICLES:")
        for i, item in enumerate(sections["news"], 1):
            text = (item.get("raw_text") or "")[:3000]
            parts.append(f"{i}. [{item['title']}]: {text}")

    if sections.get("podcasts"):
        parts.append("\nPODCAST EPISODES:")
        for i, item in enumerate(sections["podcasts"], 1):
            text = (item.get("raw_text") or "")[:5000]
            parts.append(f"{i}. [{item.get('podcast', '')} - {item['title']}]: {text}")

    if sections.get("papers"):
        parts.append("\nARXIV PAPERS:")
        for i, item in enumerate(sections["papers"], 1):
            text = (item.get("raw_text") or "")[:1500]
            parts.append(f"{i}. [{item['title']}]: {text}")

    parts.append(
        '\nReturn JSON exactly like this (with the same number of items per section):\n'
        '{\n'
        '  "news": ["KEY: <strong>Bold one-sentence takeaway.</strong>\\n2-3 sentence summary with <strong>key terms</strong> bolded.", ...],\n'
        '  "podcasts": ["KEY: <strong>Bold one-sentence takeaway.</strong>\\n3-4 sentence summary with <strong>guest names</strong> and <strong>topics</strong> bolded.", ...],\n'
        '  "papers": ["KEY: <strong>Bold one-sentence takeaway.</strong>\\n1-2 sentence summary with <strong>technique</strong> and <strong>findings</strong> bolded.", ...]\n'
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
    for key in ("news", "podcasts", "papers"):
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
        for key in ("news", "podcasts", "papers")
    }


def _fallback_section(items: list[dict], section_type: str) -> list[str]:
    """Summarize a single section's items using sumy."""
    sentence_counts = {"news": 3, "podcasts": 4, "papers": 2}
    n = sentence_counts.get(section_type, 2)
    return [summarize(item.get("raw_text", ""), num_sentences=n, title=item.get("title", "")) for item in items]

"""Batched LLM summarization using Google Gemini API with sumy fallback."""

import json
import os

from src.summarizer import summarize


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
        print("No GEMINI_API_KEY set, falling back to extractive summarizer.")
        return _fallback_summarize(sections)

    prompt = _build_prompt(sections)

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        result = _parse_response(response.text, sections)
        print("Gemini batch summarization complete.")
        return result
    except Exception as e:
        print(f"Gemini API failed ({e}), falling back to extractive summarizer.")
        return _fallback_summarize(sections)


def _build_prompt(sections: dict) -> str:
    """Build the single prompt for batch summarization."""
    parts = [
        "Summarize the following content for a daily newsletter. "
        "Return ONLY valid JSON with no markdown formatting or code blocks.\n"
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
        '  "news": ["2-3 sentence summary for article 1", ...],\n'
        '  "podcasts": ["3-4 sentence summary for episode 1", ...],\n'
        '  "papers": ["1-2 sentence summary for paper 1", ...]\n'
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
            print(f"Gemini returned {len(got)} {key} summaries, expected {expected}. Using fallback.")
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
    return [summarize(item.get("raw_text", ""), num_sentences=n) for item in items]

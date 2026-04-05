"""Trending topics and TLDR generation using Tavily search API.

No LLM calls. Uses Tavily web search to find current AI security trends,
with keyword extraction fallback from local items.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

TAVILY_SEARCH_DEPTH = "basic"
TAVILY_MAX_RESULTS = 5
TRENDING_TOPICS_COUNT = 3


def _get_tavily_client():
    """Create a Tavily client if API key is available."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("No TAVILY_API_KEY set, search features disabled")
        return None
    try:
        from tavily import TavilyClient
        return TavilyClient(api_key=api_key)
    except ImportError:
        logger.warning("tavily-python not installed, search features disabled")
        return None


def _extract_themes_from_items(ai_security_items: list[dict]) -> list[str]:
    """Extract common themes from AI security item titles and abstracts."""
    theme_keywords = [
        ("prompt injection", "Prompt Injection"),
        ("jailbreak", "LLM Jailbreaking"),
        ("supply chain", "AI Supply Chain Attacks"),
        ("adversarial", "Adversarial Attacks"),
        ("red team", "AI Red Teaming"),
        ("agent", "Agentic AI Security"),
        ("model extraction", "Model Extraction"),
        ("data poisoning", "Data Poisoning"),
        ("privacy", "AI Privacy"),
        ("alignment", "AI Alignment & Safety"),
        ("guardrail", "Guardrail Bypasses"),
        ("deepfake", "Deepfake Detection"),
        ("malware", "AI-Powered Malware"),
        ("phishing", "AI-Enhanced Phishing"),
        ("vulnerability", "AI Vulnerabilities"),
        ("watermark", "LLM Watermarking"),
        ("robustness", "Model Robustness"),
        ("backdoor", "Model Backdoors"),
    ]

    all_text = " ".join(
        (item.get("title", "") + " " + (item.get("abstract") or item.get("raw_text") or "")[:300]).lower()
        for item in ai_security_items
    )

    found = []
    for keyword, label in theme_keywords:
        count = all_text.count(keyword)
        if count > 0:
            found.append((count, label))

    found.sort(reverse=True)
    return [label for _, label in found]


def generate_trending_topics(ai_security_items: list[dict]) -> list[dict]:
    """Identify trending AI security topics using Tavily search.

    Falls back to keyword extraction from local items if Tavily is unavailable.
    Returns a list of dicts: [{"topic": str, "why": str, "action": str}, ...]
    """
    if not ai_security_items:
        return []

    # Extract themes from today's items to guide the search
    themes = _extract_themes_from_items(ai_security_items)
    if not themes:
        return []

    client = _get_tavily_client()
    if client:
        try:
            topics = _trending_via_tavily(client, themes, ai_security_items)
            if topics:
                return topics
        except Exception as e:
            logger.warning("Tavily trending topics search failed: %s", str(e)[:100])

    # Fallback: build topics from local keyword extraction
    return _trending_from_items(themes, ai_security_items)


def _trending_via_tavily(client, themes: list[str], items: list[dict]) -> list[dict]:
    """Search Tavily for context on the top themes, build structured topics."""
    topics = []

    for theme in themes[:TRENDING_TOPICS_COUNT]:
        query = f"{theme} AI security latest developments 2026"
        try:
            result = client.search(
                query,
                max_results=2,
                search_depth=TAVILY_SEARCH_DEPTH,
            )
            search_results = result.get("results", [])
            if search_results:
                # Use the first result's content as context
                content = search_results[0].get("content", "")[:200]
                why = _extract_first_sentence(content) if content else f"Multiple items in today's feed relate to {theme.lower()}."
                action = _suggest_action(theme)
                topics.append({
                    "topic": theme,
                    "why": why,
                    "action": action,
                })
        except Exception as e:
            logger.debug("Tavily search failed for theme '%s': %s", theme, str(e)[:80])
            continue

    if not topics:
        return []

    logger.info("Trending topics generated via Tavily: %d items", len(topics))
    return topics


def _trending_from_items(themes: list[str], items: list[dict]) -> list[dict]:
    """Build trending topics from local item analysis (no API calls)."""
    topics = []

    for theme in themes[:TRENDING_TOPICS_COUNT]:
        # Find items matching this theme
        keyword = theme.lower()
        matching = [
            item for item in items
            if keyword.split()[0] in (item.get("title", "") + " " + (item.get("abstract") or "")).lower()
        ]

        count = len(matching)
        if count > 0:
            titles = [m.get("title", "") for m in matching[:2]]
            why = f"{count} item{'s' if count > 1 else ''} in today's feed: {titles[0][:60]}."
            action = _suggest_action(theme)
            topics.append({
                "topic": theme,
                "why": why,
                "action": action,
            })

    if topics:
        logger.info("Trending topics generated from local items: %d", len(topics))
    return topics


def _suggest_action(theme: str) -> str:
    """Return a practical action suggestion for a given AI security theme."""
    actions = {
        "Prompt Injection": "Practice building prompt injection detectors using the techniques described in today's papers.",
        "LLM Jailbreaking": "Test jailbreak resistance on your own models using open-source red-teaming frameworks like garak.",
        "AI Supply Chain Attacks": "Audit your AI dependencies for known vulnerabilities. Check package signatures and pinned versions.",
        "Adversarial Attacks": "Set up a test bench to generate adversarial examples against your deployed models.",
        "AI Red Teaming": "Run a structured red-team exercise against one of your production AI endpoints this week.",
        "Agentic AI Security": "Review your agent tool-use permissions and add guardrails around high-risk actions.",
        "Model Extraction": "Evaluate your API rate limiting and output sanitization to reduce model theft risk.",
        "Data Poisoning": "Audit your training data pipeline for injection points where an attacker could insert poisoned samples.",
        "AI Privacy": "Run a membership inference attack against your model to quantify privacy leakage.",
        "AI Alignment & Safety": "Review your model's behavioral eval results for sycophancy and instruction-following edge cases.",
        "Guardrail Bypasses": "Test your guardrails with the latest bypass techniques from today's papers.",
        "Deepfake Detection": "Benchmark your detection pipeline against the latest generation models.",
        "AI-Powered Malware": "Update your threat models to account for LLM-assisted code obfuscation techniques.",
        "AI-Enhanced Phishing": "Run a simulated AI-phishing exercise with your security team.",
        "AI Vulnerabilities": "Check the latest CVEs related to ML frameworks in your stack.",
        "LLM Watermarking": "Evaluate watermarking schemes for your model outputs to track misuse.",
        "Model Robustness": "Run perturbation tests against your production model to find brittleness.",
        "Model Backdoors": "Scan your fine-tuned models for activation patterns that could indicate planted backdoors.",
    }
    return actions.get(theme, f"Research the latest developments in {theme.lower()} and assess your exposure.")


def _extract_first_sentence(text: str) -> str:
    """Extract the first complete sentence from text."""
    text = text.strip()
    match = re.search(r'[.!?](?:\s|$)', text)
    if match and match.start() > 10:
        return text[:match.start() + 1]
    # No clean sentence boundary, truncate
    if len(text) > 120:
        # Cut at last space before 120 chars
        cut = text[:120].rfind(" ")
        return text[:cut] + "." if cut > 0 else text[:120] + "."
    return text + "." if text and not text.endswith(".") else text


def generate_ai_security_tldr(ai_security_items: list[dict]) -> str:
    """Generate a one-sentence TLDR about AI security trends from local items.

    Uses keyword extraction only. No API calls needed for this.
    """
    if not ai_security_items:
        return ""

    themes = _extract_themes_from_items(ai_security_items)
    if not themes:
        return ""

    top = themes[:2]
    if len(top) == 2:
        tldr = f"This week's focus: {top[0].lower()} and {top[1].lower()}."
    elif top:
        tldr = f"This week's focus: {top[0].lower()}."
    else:
        return ""

    logger.info("AI security TLDR: %s", tldr)
    return tldr

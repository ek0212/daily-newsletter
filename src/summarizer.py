"""Extractive text summarization using sumy (LexRank)."""

import logging
import re

from sumy.parsers.plaintext import PlaintextParser

logger = logging.getLogger(__name__)
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer


def _bold_key_terms(summary: str, title: str = "") -> str:
    """Post-process a summary to bold numbers/statistics, quoted text, and title proper nouns."""
    # Bold numbers with percentages, dollar amounts, or standalone large numbers
    summary = re.sub(
        r'(?<!\w)(\$?\d[\d,]*\.?\d*\s*%|\$\d[\d,]*\.?\d*[BMK]?|\d[\d,]*\.?\d*\s*(?:percent|million|billion|thousand))',
        r'<strong>\1</strong>',
        summary,
        flags=re.IGNORECASE,
    )
    # Bold standalone numbers that look like stats (e.g., "73%" or "1.5 million")
    summary = re.sub(r'(?<!\w)(\d[\d,]*(?:\.\d+)?%)', r'<strong>\1</strong>', summary)

    # Bold quoted text
    summary = re.sub(r'"([^"]+)"', r'"<strong>\1</strong>"', summary)

    # Bold proper nouns from the title (2+ char capitalized words)
    if title:
        title_words = set(re.findall(r'\b([A-Z][a-zA-Z]{2,})\b', title))
        # Filter out common words
        stopwords = {'The', 'This', 'That', 'With', 'From', 'They', 'Their', 'What',
                     'When', 'Where', 'Which', 'About', 'Into', 'Over', 'After',
                     'Before', 'Between', 'Under', 'How', 'Are', 'Was', 'Were',
                     'Has', 'Had', 'Have', 'Does', 'Did', 'Can', 'Could', 'Will',
                     'Would', 'Should', 'May', 'Might', 'Its', 'For', 'And', 'But',
                     'Not', 'You', 'All', 'Any', 'Few', 'More', 'Most', 'Some',
                     'Such', 'Than', 'Too', 'Very', 'Just', 'Also', 'New', 'Our'}
        title_words -= stopwords
        for word in title_words:
            # Only bold if the word appears in summary and isn't already inside a tag
            summary = re.sub(
                r'(?<!<strong>)(?<!/)\b(' + re.escape(word) + r')\b(?!</strong>)',
                r'<strong>\1</strong>',
                summary,
            )

    # Clean up nested/duplicate strong tags
    summary = re.sub(r'<strong>\s*<strong>', '<strong>', summary)
    summary = re.sub(r'</strong>\s*</strong>', '</strong>', summary)

    return summary


def summarize(text: str, num_sentences: int = 2, title: str = "") -> str:
    """Return an extractive summary of the given text.

    Falls back to returning the original text (truncated) if summarization fails.
    """
    if not text or not text.strip():
        return ""

    logger.debug("Extractive summarize: input %d chars -> %d sentences", len(text), num_sentences)

    # If text is already short, return as-is
    sentences_rough = [s.strip() for s in text.replace("! ", ".\n").replace("? ", ".\n").split(".") if s.strip()]
    if len(sentences_rough) <= num_sentences:
        return text.strip()

    try:
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LexRankSummarizer()
        summary_sentences = summarizer(parser.document, num_sentences)
        result = " ".join(str(s) for s in summary_sentences)
        result = result if result.strip() else text[:300].strip()
        result = _bold_key_terms(result, title)
        logger.debug("Summarize result: %s...", result[:100])
        return result
    except Exception:
        # Fallback: return first N sentence-like chunks
        result = ". ".join(sentences_rough[:num_sentences]) + "."
        return _bold_key_terms(result, title)

"""Extractive text summarization using sumy (LexRank) with regex fallback.

Text extraction is handled upstream by trafilatura.
This module takes the extracted text and produces a concise extractive summary.
If NLTK punkt data is unavailable (e.g. restricted network), falls back to
a regex-based sentence extractor that picks the most information-dense sentences.
"""

import logging
import re

from src.constants import (
    MAX_SUMMARY_CHARS,
    SUMMARIZER_MIN_TEXT,
    SUMMARIZER_SKIP_INTRO,
    SUMMARIZER_URL_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Try to import sumy + NLTK. If NLTK data is missing, we fall back to regex.
_LEXRANK_AVAILABLE = False
try:
    import nltk
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        nltk.download('punkt_tab', quiet=True)
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)

    from sumy.parsers.plaintext import PlaintextParser
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.summarizers.lex_rank import LexRankSummarizer

    # Test that tokenizer actually works
    _test_parser = PlaintextParser.from_string("Test sentence.", Tokenizer("english"))
    _LEXRANK_AVAILABLE = True
    logger.info("LexRank summarizer available (NLTK punkt loaded)")
except Exception as e:
    logger.warning("LexRank summarizer unavailable, using regex fallback: %s", str(e)[:100])

# Patterns that indicate boilerplate, not article content
_BOILERPLATE_RE = re.compile(
    r'(?i)(?:'
    r'brought to you by|sponsored by|use code|promo code|sign up at|'
    r'learn more at|download it at|free trial|percent off|dollars off|'
    r'less than \d+ min read|subscribe to|subscribe now|cookie policy|'
    r'privacy policy|terms of service|all rights reserved|'
    r'follow us on|share this article|related articles|'
    r'click here to|join our newsletter|advertisement|'
    r'username|password|log ?in|log ?out|register|sign ?in|sign ?up|'
    r'list \d+ of \d+|image \d+ of \d+|slide \d+ of \d+'
    r')'
)

# Sentence boundary regex: split on period/question/exclamation followed by space+uppercase
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')

# Summaries that end on a hanging word (preposition, conjunction, article, verb, adverb)
# are truncated mid-idea. Also catches hyphenated compound words like "multi-turn."
_HANGING_ENDING_RE = re.compile(
    r'(?:'
    # Hanging prepositions, conjunctions, articles, auxiliaries
    r'\b(?:of|and|at|in|to|for|with|a|an|the|by|from|on|or|but|as|'
    r'that|which|who|when|where|if|its|their|this|these|those|has|have|'
    r'had|was|were|is|are|be|been|being|can|could|will|would|should|may|'
    r'might|shall|must|do|does|did|not|also|just|then|than|so|yet|nor|'
    r'after|before|during|between|about|against|under|over|into|within|'
    r'without|through|across|along|around|behind|beyond|despite|except|'
    r'following|including|like|near|per|plus|since|toward|upon|versus|via|'
    # Common adverbs that appear mid-clause
    r'nearly|almost|already|still|even|only|recently|currently|largely|'
    r'widely|rapidly|increasingly|significantly|effectively|specifically|'
    r'particularly|generally|primarily|ultimately|essentially|approximately)'
    r'\s*[.]\s*$'
    r'|'
    # Hyphenated compound word at end (e.g., "multi-turn.") — always mid-clause
    r'\b\w+-\w+\s*[.]\s*$'
    r')',
    re.IGNORECASE,
)


def _clean_text(text: str) -> str:
    """Clean extracted text before summarization.

    Strips leading fragments, boilerplate lines, scrape artifacts, and
    excessive whitespace.
    """
    # Remove Unicode replacement / garbage characters
    text = re.sub(r'[\ufffd\ufffc\ufffe\uffff\u0000-\u0008\u000b\u000c\u000e-\u001f]', '', text)

    # Strip YouTube auto-caption censorship markers: [ __ ], [Music], [Applause], etc.
    text = re.sub(r'\[\s*(?:__+|music|applause|laughter|inaudible|crosstalk)\s*\]', '', text, flags=re.IGNORECASE)

    # Remove stray symbols that look like nav artifacts: ☆ ♦ ★ • ◦ ◆ › » « ‹ ▸ ▾ ▲ ▼
    text = re.sub(r'[☆♦★•◦◆›»«‹▸▾▲▼▸▹◂◃⬆⬇⬅➡]', '', text)

    stripped = text.lstrip()
    if stripped and not stripped[0].isupper():
        match = re.search(r'[.!?]\s+([A-Z])', stripped)
        if match:
            stripped = stripped[match.start() + 2:]

    lines = stripped.split('\n')
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _BOILERPLATE_RE.search(line):
            continue
        # Skip very short lines (nav items, bylines, stray symbols)
        if len(line) < 20 and not line.endswith('.'):
            continue
        clean_lines.append(line)

    result = ' '.join(clean_lines)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def _is_clean_summary(text: str) -> bool:
    """Return False if the summary looks truncated or contains scrape junk."""
    if not text:
        return False
    # Ends on a hanging word (cut mid-clause)
    if _HANGING_ENDING_RE.search(text):
        return False
    # Contains residual scrape artifacts
    if re.search(r'[\ufffd\u0000-\u001f]', text):
        return False
    # Repeated phrase (same substring > 60 chars appearing twice)
    if len(text) > 80:
        half = text[: len(text) // 2]
        if half and half in text[len(half):]:
            return False
    return True


def _cap_length(text: str, max_chars: int = 300) -> str:
    """Truncate text to max_chars at the last complete sentence boundary.

    Returns empty string if no clean sentence boundary exists within max_chars,
    so the caller can fall back rather than showing a mid-sentence stub.
    """
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = truncated.rfind('. ')
    last_question = truncated.rfind('? ')
    last_exclaim = truncated.rfind('! ')
    cut_point = max(last_period, last_question, last_exclaim)
    if cut_point > max_chars // 3:
        return truncated[:cut_point + 1]
    # No clean boundary — return empty so caller falls back gracefully
    return ""


def _regex_summarize(text: str, num_sentences: int = 2) -> str:
    """Fallback extractive summarizer using regex sentence splitting.

    Picks the most information-dense sentences (longest, with numbers/proper nouns).
    """
    sentences = _SENTENCE_SPLIT_RE.split(text)
    # Filter out very short or boilerplate sentences
    good_sentences = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30:
            continue
        if _BOILERPLATE_RE.search(s):
            continue
        good_sentences.append(s)

    if not good_sentences:
        return ""

    def _score_sentence(s: str) -> float:
        """Score a sentence by information density."""
        score = 0.0
        # Reward numbers/statistics
        score += len(re.findall(r'\d+', s)) * 1.5
        # Reward proper nouns
        score += len(re.findall(r'\b[A-Z][a-z]+\b', s)) * 1.0
        # Reward quoted text
        score += len(re.findall(r'"[^"]+?"', s)) * 2.0
        # Slight reward for moderate length (50-200 chars)
        if 50 <= len(s) <= 200:
            score += 1.0
        # Penalize very long sentences (likely run-on or transcript fragments)
        if len(s) > 300:
            score -= 2.0
        return score

    scored = [(s, _score_sentence(s)) for s in good_sentences]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Pick top sentences, but maintain original order
    top = scored[:num_sentences]
    # Re-sort by position in original text
    top_texts = {s for s, _ in top}
    ordered = [s for s in good_sentences if s in top_texts]

    return " ".join(ordered[:num_sentences])


def _bold_key_terms(summary: str, title: str = "") -> str:
    """Bold numbers/statistics, quoted text, and title proper nouns."""
    summary = re.sub(
        r'(?<!\w)(\$?\d[\d,]*\.?\d*\s*%|\$\d[\d,]*\.?\d*[BMK]?|\d[\d,]*\.?\d*\s*(?:percent|million|billion|thousand))',
        r'<strong>\1</strong>',
        summary,
        flags=re.IGNORECASE,
    )
    summary = re.sub(r'(?<!\w)(\d[\d,]*(?:\.\d+)?%)', r'<strong>\1</strong>', summary)

    summary = re.sub(r'"([^"]+)"', r'"<strong>\1</strong>"', summary)

    if title:
        title_words = set(re.findall(r'\b([A-Z][a-zA-Z]{2,})\b', title))
        stopwords = {
            'The', 'This', 'That', 'With', 'From', 'They', 'Their', 'What',
            'When', 'Where', 'Which', 'About', 'Into', 'Over', 'After',
            'Before', 'Between', 'Under', 'How', 'Are', 'Was', 'Were',
            'Has', 'Had', 'Have', 'Does', 'Did', 'Can', 'Could', 'Will',
            'Would', 'Should', 'May', 'Might', 'Its', 'For', 'And', 'But',
            'Not', 'You', 'All', 'Any', 'Few', 'More', 'Most', 'Some',
            'Such', 'Than', 'Too', 'Very', 'Just', 'Also', 'New', 'Our',
        }
        title_words -= stopwords
        for word in title_words:
            summary = re.sub(
                r'(?<!<strong>)(?<!/)\b(' + re.escape(word) + r')\b(?!</strong>)',
                r'<strong>\1</strong>',
                summary,
            )

    summary = re.sub(r'<strong>\s*<strong>', '<strong>', summary)
    summary = re.sub(r'</strong>\s*</strong>', '</strong>', summary)

    return summary


def summarize(text: str, num_sentences: int = 2, title: str = "") -> str:
    """Return an extractive summary using LexRank or regex fallback.

    Expects text already extracted by trafilatura upstream.
    Returns empty string if text is too short or non-content.
    """
    if not text or not text.strip():
        return ""

    if len(text) < SUMMARIZER_MIN_TEXT or text.count("http") > SUMMARIZER_URL_THRESHOLD:
        return ""

    text = _clean_text(text)

    # For long content (transcripts, long articles), skip the intro
    if len(text) > SUMMARIZER_MIN_TEXT * 10:
        text = text[SUMMARIZER_SKIP_INTRO:]

    if len(text) < SUMMARIZER_MIN_TEXT:
        return ""

    logger.debug("Summarize: %d chars -> %d sentences (LexRank=%s)", len(text), num_sentences, _LEXRANK_AVAILABLE)

    result = ""

    if _LEXRANK_AVAILABLE:
        try:
            parser = PlaintextParser.from_string(text, Tokenizer("english"))
            summarizer_instance = LexRankSummarizer()
            sentences = summarizer_instance(parser.document, num_sentences)
            result = " ".join(str(s) for s in sentences)
        except Exception as e:
            logger.warning("LexRank summarize failed, using regex fallback: %s", e)

    if not result.strip():
        result = _regex_summarize(text, num_sentences)

    if not result.strip():
        return ""

    result = _cap_length(result, max_chars=MAX_SUMMARY_CHARS)

    if not _is_clean_summary(result):
        logger.debug("Rejected dirty/truncated summary: %s", result[:80])
        return ""

    result = _bold_key_terms(result, title)
    return result

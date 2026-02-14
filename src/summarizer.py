"""Extractive text summarization using sumy (LexRank)."""

from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer


def summarize(text: str, num_sentences: int = 2) -> str:
    """Return an extractive summary of the given text.

    Falls back to returning the original text (truncated) if summarization fails.
    """
    if not text or not text.strip():
        return ""

    # If text is already short, return as-is
    sentences_rough = [s.strip() for s in text.replace("! ", ".\n").replace("? ", ".\n").split(".") if s.strip()]
    if len(sentences_rough) <= num_sentences:
        return text.strip()

    try:
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LexRankSummarizer()
        summary_sentences = summarizer(parser.document, num_sentences)
        result = " ".join(str(s) for s in summary_sentences)
        return result if result.strip() else text[:300].strip()
    except Exception:
        # Fallback: return first N sentence-like chunks
        return ". ".join(sentences_rough[:num_sentences]) + "."

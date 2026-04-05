"""Tests for the extractive summarizer."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.summarizer import summarize, _clean_text, _cap_length, _regex_summarize


def test_summarize_returns_short_output():
    """Summary should be capped at MAX_SUMMARY_CHARS."""
    text = (
        "The Federal Reserve raised interest rates by a quarter percentage point. "
        "This brings the benchmark rate to a range of 5.25% to 5.5%, the highest in 22 years. "
        "Fed Chair Jerome Powell said the decision was driven by continued inflation concerns. "
        "The move affects mortgage rates, car loans, and credit card interest across the country. "
        "Economists had widely anticipated the increase following strong employment data. "
        "The labor market added 209,000 jobs in June, slightly below expectations. "
        "Consumer spending remained elevated despite higher borrowing costs. "
        "Wall Street reacted with modest gains, with the S&P 500 rising 0.4% on the day."
    )
    result = summarize(text, num_sentences=2)
    # Strip HTML tags for length check
    import re
    plain = re.sub(r'<[^>]+>', '', result)
    assert len(plain) <= 350, f"Summary too long: {len(plain)} chars"
    assert len(plain) > 30, f"Summary too short: {len(plain)} chars"


def test_summarize_empty_input():
    assert summarize("") == ""
    assert summarize("   ") == ""
    assert summarize("short") == ""


def test_summarize_url_heavy_text():
    """Text with too many URLs should return empty."""
    text = "See http://a.com and http://b.com and http://c.com and http://d.com for details on this topic."
    assert summarize(text) == ""


def test_clean_text_strips_boilerplate():
    text = "This is important news.\nFollow us on Twitter.\nThe economy grew 3%.\nSubscribe to our newsletter."
    result = _clean_text(text)
    assert "Follow us" not in result
    assert "Subscribe to" not in result
    assert "economy grew" in result


def test_clean_text_strips_leading_fragment():
    text = "ifecycle. The new policy will take effect on Monday."
    result = _clean_text(text)
    assert result.startswith("The new policy")


def test_cap_length_at_sentence_boundary():
    text = "First sentence here. Second sentence here. Third sentence that is much longer and pushes us past the limit."
    result = _cap_length(text, max_chars=50)
    # Should cut at a sentence boundary within 50 chars
    assert result.endswith("."), f"Should end at sentence boundary: {result}"
    assert len(result) <= 50, f"Should be under 50 chars: {len(result)}"


def test_cap_length_preserves_short_text():
    text = "Short text."
    assert _cap_length(text, max_chars=100) == text


def test_regex_summarize_picks_info_dense():
    text = (
        "The meeting was held on Tuesday. "
        "Revenue increased by 45% to $2.3 billion in Q3 2025. "
        "Several attendees were present. "
        "CEO John Smith said the company plans to expand into 12 new markets by 2026."
    )
    result = _regex_summarize(text, num_sentences=2)
    # Should pick the sentences with numbers and proper nouns
    assert "45%" in result or "$2.3 billion" in result or "12 new markets" in result


def test_regex_summarize_empty():
    assert _regex_summarize("", 2) == ""
    assert _regex_summarize("too short", 2) == ""


if __name__ == "__main__":
    test_summarize_returns_short_output()
    test_summarize_empty_input()
    test_summarize_url_heavy_text()
    test_clean_text_strips_boilerplate()
    test_clean_text_strips_leading_fragment()
    test_cap_length_at_sentence_boundary()
    test_cap_length_preserves_short_text()
    test_regex_summarize_picks_info_dense()
    test_regex_summarize_empty()
    print("All tests passed!")

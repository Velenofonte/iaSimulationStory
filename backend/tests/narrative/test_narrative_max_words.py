"""narrative_max_words clamp helper."""

from app.services.narrative_renderer import clamp_words, count_words


def test_clamp_words_noop_when_zero_or_under() -> None:
    text = "Una due tre quattro."
    assert clamp_words(text, 0) == text
    assert clamp_words(text, 10) == text
    assert count_words(text) == 4


def test_clamp_words_prefers_sentence_end() -> None:
    text = "Prima frase completa. Seconda frase molto più lunga del necessario qui."
    out = clamp_words(text, 5)
    assert out.endswith(".")
    assert "Prima frase completa." in out
    assert count_words(out) <= 5

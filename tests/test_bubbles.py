"""Tests for sonya.dialogue.bubbles.split_into_bubbles."""

from __future__ import annotations

from sonya.dialogue.bubbles import split_into_bubbles


def test_empty_returns_empty() -> None:
    assert split_into_bubbles("") == []
    assert split_into_bubbles("   ") == []


def test_short_text_is_one_bubble() -> None:
    assert split_into_bubbles("hey love 💛") == ["hey love 💛"]


def test_max_bubbles_one_never_splits() -> None:
    text = "Paragraph one is here.\n\nParagraph two is also here.\n\nAnd third."
    assert split_into_bubbles(text, max_bubbles=1) == [text]


def test_paragraph_split() -> None:
    text = (
        "First paragraph that's long enough to count as a real bubble on its own. "
        "It needs at least sixty characters to survive the merge step.\n\n"
        "Second paragraph also long enough to be its own bubble for sure here."
    )
    out = split_into_bubbles(text, max_bubbles=3)
    assert len(out) == 2


def test_sentence_fallback_when_no_paragraph() -> None:
    text = (
        "First long sentence that is clearly substantial in length and meaning. "
        "Second long sentence which is also substantial and meaningful here. "
        "Third sentence keeps going to push past the threshold easily."
    )
    out = split_into_bubbles(text, max_bubbles=3, single_threshold=60, min_chars=40)
    assert len(out) >= 2


def test_max_bubbles_caps_output() -> None:
    text = "\n\n".join(
        [f"Paragraph {i} is long enough to be its own bubble forever and ever." for i in range(6)]
    )
    out = split_into_bubbles(text, max_bubbles=2)
    assert len(out) == 2
    # Tail must have absorbed the rest.
    assert "Paragraph 5" in out[-1]


def test_micro_pieces_are_merged() -> None:
    # Two tiny "sentences" should not produce two micro-bubbles.
    text = "Ok. Yes. " + ("This is a long-enough trailing sentence to count as content. " * 5)
    out = split_into_bubbles(text, max_bubbles=3, min_chars=60)
    # The first "Ok. Yes." piece must have been absorbed into a real bubble.
    assert all(len(b) >= 5 for b in out)
    # And we should not have one bubble per sentence.
    assert len(out) <= 3


def test_no_split_returns_one_bubble_when_only_one_part() -> None:
    text = "x" * 250  # one giant blob, no boundaries
    out = split_into_bubbles(text, max_bubbles=3, single_threshold=100)
    assert out == [text]

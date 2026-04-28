"""Tests for sonya.dialogue.intent.classify_intent."""

from __future__ import annotations

import pytest

from sonya.dialogue.intent import Intent, classify_intent


@pytest.mark.parametrize(
    "text",
    ["hi", "Hello!", "hey there", "yo", "good morning", "Привет", "хай"],
)
def test_greeting(text: str) -> None:
    assert classify_intent(text).intent is Intent.GREETING


@pytest.mark.parametrize("text", ["bye", "ttyl", "good night ❤", "пока", "до завтра"])
def test_farewell(text: str) -> None:
    assert classify_intent(text).intent is Intent.FAREWELL


@pytest.mark.parametrize(
    "text",
    [
        "how much?",
        "what's the price?",
        "how much does it cost?",
        "сколько стоит?",
        "почём?",
    ],
)
def test_price(text: str) -> None:
    assert classify_intent(text).intent is Intent.PRICE_QUESTION


@pytest.mark.parametrize(
    "text",
    ["how do I pay?", "payment method?", "can I pay with telegram stars?", "как оплатить"],
)
def test_payment(text: str) -> None:
    assert classify_intent(text).intent is Intent.PAYMENT_QUESTION


@pytest.mark.parametrize(
    "text",
    [
        "send me a pic",
        "can I see another photo?",
        "send me some pics please",
        "пришли фото",
        "покажи тело",
    ],
)
def test_content_request(text: str) -> None:
    assert classify_intent(text).intent is Intent.CONTENT_REQUEST


@pytest.mark.parametrize("text", ["send nudes", "i wanna fuck you", "let's sext"])
def test_sexual_request(text: str) -> None:
    assert classify_intent(text).intent is Intent.SEXUAL_REQUEST


@pytest.mark.parametrize(
    "text", ["this is bullshit", "i want a refund", "you scammed me", "верни деньги"]
)
def test_complaint(text: str) -> None:
    assert classify_intent(text).intent is Intent.COMPLAINT


@pytest.mark.parametrize(
    "text",
    ["you're so beautiful", "you're hot", "you look amazing", "ты такая красивая"],
)
def test_compliment(text: str) -> None:
    assert classify_intent(text).intent is Intent.COMPLIMENT


@pytest.mark.parametrize(
    "text",
    ["where are you from?", "how old are you?", "what's your name?", "what are you doing?"],
)
def test_personal_question(text: str) -> None:
    assert classify_intent(text).intent is Intent.PERSONAL_QUESTION


@pytest.mark.parametrize("text", ["how are you?", "how's it going?", "what's up?"])
def test_smalltalk(text: str) -> None:
    assert classify_intent(text).intent is Intent.SMALLTALK


@pytest.mark.parametrize(
    "text",
    ["", "   ", "lorem ipsum dolor sit", "the cat sat on the mat in a quiet room"],
)
def test_unknown_for_unrecognised_or_empty(text: str) -> None:
    assert classify_intent(text).intent is Intent.UNKNOWN


def test_priority_complaint_beats_greeting() -> None:
    # "hi, this is bullshit" should fire COMPLAINT, not GREETING
    res = classify_intent("hi, this is bullshit, refund please")
    assert res.intent is Intent.COMPLAINT


def test_short_greeting_is_high_confidence() -> None:
    res = classify_intent("hi")
    assert res.intent is Intent.GREETING
    assert res.confidence == "high"


def test_long_text_is_mid_confidence() -> None:
    res = classify_intent("Hi there, I just wanted to say hello and check in for a sec")
    assert res.intent is Intent.GREETING
    assert res.confidence == "mid"

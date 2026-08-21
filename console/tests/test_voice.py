"""Tests for speech synthesis.

Only the mock is exercised. `ElevenLabsVoice` needs a paid account, so nothing
in CI touches it — the same honesty as `GmailMailbox` and `GoogleCalendar`.
"""

from __future__ import annotations

import pytest

from console.models import Channel, Utterance
from console.voice import (
    DEFAULT_VOICE_ID,
    BudgetExhausted,
    ElevenLabsVoice,
    MockVoice,
    build_voice,
)


def utterance(**overrides) -> Utterance:
    base = {
        "id": "u1",
        "display_text": "2 of 7 verified",
        "spoken_text": "Two out of seven were verified.",
    }
    return Utterance(**{**base, **overrides})


# --- What gets spoken ---------------------------------------------------


def test_the_spoken_wording_is_used_not_the_displayed_one():
    # "2 of 7 (29%)" is fine in a table and unintelligible read aloud.
    voice = MockVoice()
    clip = voice.speak(utterance())

    assert clip.text == "Two out of seven were verified."
    assert voice.spoken == "Two out of seven were verified."


def test_display_only_lines_are_never_spoken():
    voice = MockVoice()
    clip = voice.speak(utterance(channel=Channel.DISPLAY))

    assert clip.text == ""
    assert voice.transcript == []


def test_a_line_without_spoken_wording_falls_back_to_the_displayed_text():
    clip = MockVoice().speak(utterance(spoken_text=""))
    assert clip.text == "2 of 7 verified"


def test_the_clip_reports_what_it_cost_in_characters():
    clip = MockVoice().speak(utterance())
    assert clip.characters == len("Two out of seven were verified.")
    assert clip.succeeded


# --- The budget ---------------------------------------------------------


def test_characters_accumulate_across_a_session():
    voice = MockVoice(budget=1_000)
    voice.speak(utterance(id="a"))
    voice.speak(utterance(id="b"))

    assert voice.characters_used == 2 * len("Two out of seven were verified.")
    assert voice.remaining == 1_000 - voice.characters_used


def test_exceeding_the_budget_raises_rather_than_billing():
    # ElevenLabs bills per character, so a runaway loop is a billing incident.
    # The provider enforces this itself rather than trusting the caller.
    voice = MockVoice(budget=10)

    with pytest.raises(BudgetExhausted, match="character session budget"):
        voice.speak(utterance())


def test_a_refused_utterance_is_not_charged():
    voice = MockVoice(budget=10)
    with pytest.raises(BudgetExhausted):
        voice.speak(utterance())

    assert voice.characters_used == 0
    assert voice.transcript == []


def test_silent_lines_cost_nothing():
    voice = MockVoice(budget=5)
    voice.speak(utterance(channel=Channel.DISPLAY))

    assert voice.characters_used == 0


# --- Provider selection -------------------------------------------------


def test_mock_is_the_default():
    assert isinstance(build_voice(), MockVoice)
    assert isinstance(build_voice("mock"), MockVoice)


def test_an_unrecognised_mode_falls_back_to_mock_rather_than_the_network():
    # Anything other than an explicit "live" must not reach ElevenLabs.
    assert isinstance(build_voice("liveish"), MockVoice)
    assert isinstance(build_voice(""), MockVoice)


def test_live_mode_without_a_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    with pytest.raises(ValueError, match="needs an API key"):
        build_voice("live")


def test_live_mode_with_a_key_builds_the_real_provider(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-real")
    voice = build_voice("live")

    assert isinstance(voice, ElevenLabsVoice)
    assert voice.voice_id == DEFAULT_VOICE_ID


def test_the_voice_id_is_configurable(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "some-other-voice")

    assert build_voice("live").voice_id == "some-other-voice"


def test_the_real_provider_refuses_to_construct_without_a_key():
    with pytest.raises(ValueError, match="needs an API key"):
        ElevenLabsVoice(api_key="")

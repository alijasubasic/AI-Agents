"""Speech synthesis behind an interface.

One `Protocol`, a mock that makes no network calls, and an ElevenLabs
implementation. Mock is the default, so the console demo speaks its briefing on
a machine with no API key and no audio hardware.

ElevenLabs bills per character. That makes a runaway loop a billing incident
rather than a slow afternoon, so the budget below is enforced by the provider
itself rather than trusted to the caller — the same reasoning as codex article
A7, applied one layer down.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from console.models import SpokenClip, Utterance

#: Characters one briefing may synthesise. A morning brief is a few hundred;
#: anything near this ceiling means something is repeating itself.
MAX_CHARACTERS_PER_SESSION = 4_000

#: ElevenLabs' lowest-latency model. Quality is fine for a spoken briefing and
#: it is materially cheaper than the multilingual tiers.
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
API_BASE = "https://api.elevenlabs.io/v1"


class BudgetExhausted(RuntimeError):
    """The session hit its character ceiling."""


class VoiceProvider(Protocol):
    """The speech operations the console needs."""

    voice_id: str

    def speak(self, utterance: Utterance) -> SpokenClip: ...


class _BudgetedVoice:
    """Shared character accounting for both implementations."""

    def __init__(self, *, voice_id: str, budget: int = MAX_CHARACTERS_PER_SESSION) -> None:
        self.voice_id = voice_id
        self.budget = budget
        self.characters_used = 0

    def _charge(self, text: str) -> None:
        if self.characters_used + len(text) > self.budget:
            raise BudgetExhausted(
                f"speaking {len(text)} more characters would exceed the "
                f"{self.budget}-character session budget "
                f"({self.characters_used} already used)"
            )
        self.characters_used += len(text)

    @property
    def remaining(self) -> int:
        return self.budget - self.characters_used


class MockVoice(_BudgetedVoice):
    """Records what would have been spoken. No network, no audio.

    The transcript it keeps is what the tests assert against, so "the briefing
    never speaks something that was blocked" is a checkable property rather
    than a claim.
    """

    def __init__(self, *, voice_id: str = "mock-voice", budget: int = MAX_CHARACTERS_PER_SESSION):
        super().__init__(voice_id=voice_id, budget=budget)
        self.transcript: list[str] = []

    def speak(self, utterance: Utterance) -> SpokenClip:
        text = utterance.to_speak
        if not text:
            return SpokenClip(utterance_id=utterance.id, text="", voice_id=self.voice_id)

        self._charge(text)
        self.transcript.append(text)
        return SpokenClip(
            utterance_id=utterance.id,
            text=text,
            # One byte per character is nonsense as audio, and deliberately so:
            # a mock that reported plausible sizes would invite someone to
            # believe them.
            audio_bytes=len(text),
            characters=len(text),
            voice_id=self.voice_id,
        )

    @property
    def spoken(self) -> str:
        return " ".join(self.transcript)


class ElevenLabsVoice(_BudgetedVoice):
    """Real speech synthesis through the ElevenLabs API.

    NOT COVERED BY TESTS. Exercising it needs a paid account, so nothing in CI
    touches it and it should be treated as unverified until someone runs it
    against a real key. The mock is what the test suite and the demo use.

    Written against `urllib` rather than an HTTP client library on purpose: one
    POST returning bytes does not justify a dependency, and the `httpx` that
    arrives with the Anthropic SDK is a transitive dependency this package has
    no business reaching into.
    """

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str = DEFAULT_VOICE_ID,
        model_id: str = DEFAULT_MODEL_ID,
        output_dir: Path | str = "briefs/audio",
        budget: int = MAX_CHARACTERS_PER_SESSION,
        timeout_s: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError(
                "ElevenLabsVoice needs an API key. Leave VOICE_MODE unset to use "
                "the mock provider instead."
            )
        super().__init__(voice_id=voice_id, budget=budget)
        self._api_key = api_key
        self._model_id = model_id
        self._timeout_s = timeout_s
        self.output_dir = Path(output_dir)

    def speak(self, utterance: Utterance) -> SpokenClip:
        text = utterance.to_speak
        if not text:
            return SpokenClip(utterance_id=utterance.id, text="", voice_id=self.voice_id)

        self._charge(text)
        request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
            f"{API_BASE}/text-to-speech/{self.voice_id}",
            data=json.dumps(
                {
                    "text": text,
                    "model_id": self._model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                }
            ).encode("utf-8"),
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310
                audio = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            # A briefing that cannot be spoken is still a briefing that can be
            # read. Failing the whole run over the audio would be the wrong
            # trade, so the failure is reported and the console carries on.
            return SpokenClip(
                utterance_id=utterance.id,
                text=text,
                characters=len(text),
                voice_id=self.voice_id,
                error=f"{type(exc).__name__}: {exc}",
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{utterance.id}.mp3"
        path.write_bytes(audio)

        return SpokenClip(
            utterance_id=utterance.id,
            text=text,
            audio_bytes=len(audio),
            characters=len(text),
            voice_id=self.voice_id,
            path=str(path),
        )


def build_voice(mode: str | None = None) -> VoiceProvider:
    """Return the provider matching `VOICE_MODE`. Mock unless told otherwise."""
    mode = (mode or os.environ.get("VOICE_MODE", "mock")).strip().lower()
    if mode != "live":
        return MockVoice()

    return ElevenLabsVoice(
        api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
        voice_id=os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
        model_id=os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_MODEL_ID),
    )

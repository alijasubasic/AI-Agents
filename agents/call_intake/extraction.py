"""Deterministic verification of what the model extracted.

A model reading a noisy transcript will occasionally produce a contact detail
that sounds right and was never said. `name@company.com` is a very plausible
address to invent for a caller from `company.com`, and nothing about the
extraction itself reveals that it was invented.

So every detail is checked back against what the **caller** actually said. This
module contains no prompts and no model calls: it is string handling, and it
either finds the value in the transcript or it does not.
"""

from __future__ import annotations

import re

from agents.call_intake.models import (
    CallTranscript,
    ExtractedCall,
    GroundingIssue,
)

#: Spoken renderings of email punctuation. Callers spell addresses aloud and
#: transcription writes them out in words.
_SPOKEN = (
    (r"\s+at\s+", "@"),
    (r"\s+dot\s+", "."),
    (r"\s+underscore\s+", "_"),
    (r"\s+dash\s+", "-"),
    (r"\s+hyphen\s+", "-"),
)

#: Attempts to talk the agent out of its instructions. A transcript is text a
#: stranger dictated; treating it as data is not optional.
_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"ignore\s+(all\s+|any\s+)?(previous|prior|earlier|above)\s+instructions",
        "instruction override",
    ),
    (r"disregard\s+(all\s+|your\s+)?(previous|prior|earlier)\s+", "instruction override"),
    (r"\byou\s+are\s+now\b", "role reassignment"),
    (r"\bnew\s+(system\s+)?(prompt|instructions?)\b", "prompt replacement"),
    (r"\bsystem\s*[:>]", "fake system turn"),
    (r"\bpretend\s+(that\s+)?you\b", "role reassignment"),
    (r"</?(system|instructions?|assistant)>", "markup injection"),
    (r"\bdeveloper\s+mode\b", "jailbreak phrasing"),
)


def spoken_to_written(text: str) -> str:
    """Turn spoken email punctuation into written form.

    "j dot wolf at kestrel dot example" becomes "j.wolf@kestrel.example", so a
    correctly-extracted address can still be found in the transcript.
    """
    result = text
    for pattern, replacement in _SPOKEN:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def digits_only(text: str) -> str:
    """Every digit in `text`, in order. Used to compare phone numbers."""
    return re.sub(r"\D", "", text)


#: Callers read numbers out as words, and transcription writes them as words.
#: Without this, a correctly-heard phone number looks invented to the check
#: below, which would flag every honest extraction and teach people to ignore
#: the warning.
_DIGIT_WORDS = {
    "oh": "0",
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


def written_digits(text: str) -> str:
    """Replace spoken digit words with digits, leaving everything else alone."""
    return re.sub(
        r"\b(" + "|".join(_DIGIT_WORDS) + r")\b",
        lambda match: _DIGIT_WORDS[match.group(0).lower()],
        text,
        flags=re.IGNORECASE,
    )


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, resolve spoken punctuation."""
    return re.sub(r"\s+", " ", spoken_to_written(text)).strip().lower()


def detect_injection(text: str) -> list[str]:
    """Return the injection techniques present in `text`. Empty means none found.

    Detection is a tripwire, not a filter: a hit routes the call to a human. It
    is deliberately not used to sanitise the transcript, because a transcript
    edited to look safe is worse than one flagged as suspicious.
    """
    found: list[str] = []
    for pattern, label in _INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and label not in found:
            found.append(label)
    return found


def check_grounding(extraction: ExtractedCall, transcript: CallTranscript) -> list[GroundingIssue]:
    """Report extracted contact details the caller never actually said.

    Checked against `caller_text` only. A detail our own operator read back
    down the line is not the caller providing it, and an extraction that leans
    on the operator's guess is exactly the failure worth catching.
    """
    issues: list[GroundingIssue] = []
    said = _normalise(transcript.caller_text)
    said_digits = digits_only(written_digits(transcript.caller_text))
    contact = extraction.contact

    if contact.email and _normalise(contact.email) not in said:
        issues.append(
            GroundingIssue(
                field="email",
                value=contact.email,
                reason="address does not appear in what the caller said",
            )
        )

    if contact.phone:
        wanted = digits_only(contact.phone)
        # Short fragments match by accident; a real number is long enough to be
        # a meaningful check.
        if len(wanted) < 6 or wanted not in said_digits:
            issues.append(
                GroundingIssue(
                    field="phone",
                    value=contact.phone,
                    reason="number does not appear in what the caller said",
                )
            )

    if contact.name and not _name_mentioned(contact.name, said):
        issues.append(
            GroundingIssue(
                field="name",
                value=contact.name,
                reason="name does not appear in what the caller said",
            )
        )

    if contact.company and _normalise(contact.company) not in said:
        issues.append(
            GroundingIssue(
                field="company",
                value=contact.company,
                reason="company does not appear in what the caller said",
            )
        )

    return issues


def _name_mentioned(name: str, said: str) -> bool:
    """True if any part of `name` longer than two characters was said.

    Deliberately lenient: callers give a first name and the model may add a
    surname it heard once. Requiring the full string to match would flag more
    honest extractions than invented ones.
    """
    parts = [part for part in re.split(r"[\s\-]+", _normalise(name)) if len(part) > 2]
    return any(part in said for part in parts) if parts else False

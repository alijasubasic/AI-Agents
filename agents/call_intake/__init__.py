"""Call intake: transcript in, verified record out, meeting options if asked.

The transcript is untrusted input. Extraction is verified against what the
caller actually said, and delegation to the booking agent is typed.
"""

from agents.call_intake.agent import CallIntakeAgent, render_summary
from agents.call_intake.extraction import (
    check_grounding,
    detect_injection,
    digits_only,
    spoken_to_written,
    written_digits,
)
from agents.call_intake.models import (
    CallIntent,
    CallTranscript,
    ContactDetails,
    ExtractedCall,
    GroundingIssue,
    IntakeResult,
    Turn,
    Urgency,
)
from agents.call_intake.policy import DEFAULT_POLICY, IntakePolicy

__all__ = [
    "DEFAULT_POLICY",
    "CallIntakeAgent",
    "CallIntent",
    "CallTranscript",
    "ContactDetails",
    "ExtractedCall",
    "GroundingIssue",
    "IntakePolicy",
    "IntakeResult",
    "Turn",
    "Urgency",
    "check_grounding",
    "detect_injection",
    "digits_only",
    "render_summary",
    "spoken_to_written",
    "written_digits",
]

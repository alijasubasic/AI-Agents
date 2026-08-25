"""Eval cases for the email triage agent.

Every case here scores the deterministic half — the escalation policy and the
routing decision. Whether the *model* classifies a subtle complaint correctly
is a JUDGEMENT-layer question and needs a live key.
"""

from __future__ import annotations

from agents.email_triage.agent import EmailTriageAgent
from agents.email_triage.fixtures import by_id
from agents.email_triage.models import Classification, Intent, Priority, Sentiment
from agents.email_triage.policy import DEFAULT_POLICY
from agents.email_triage.providers import MockCrm, MockMailbox
from agents.email_triage.scripted import provider_for
from core.config import Settings
from evals.models import Expectation, Layer, Score
from evals.registry import case
from evals.scoring import combine, contains_all, equals, excludes_all, is_false, is_true

AGENT = "email-triage"


def _triage(email_id: str):
    mailbox = MockMailbox()
    agent = EmailTriageAgent(
        provider=provider_for(email_id),
        crm=MockCrm(),
        mailbox=mailbox,
        settings=Settings(trace_enabled=False),
    )
    result = agent.triage(by_id(email_id))
    return result, agent.send_if_allowed(result), mailbox


def _classification(**overrides) -> Classification:
    base = {
        "priority": Priority.NORMAL,
        "intent": Intent.QUESTION,
        "sentiment": Sentiment.NEUTRAL,
        "confidence": 0.95,
        "summary": "A routine question.",
        "tasks": [],
        "draft_reply": "Thanks, I will look into it.",
    }
    return Classification(**{**base, **overrides})


# --- Routing ------------------------------------------------------------


@case(
    id="triage-routine-auto-replies",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A confident, benign enquiry is answered without a human.",
)
def _() -> Score:
    result, sent, mailbox = _triage("msg-001")
    return combine(
        is_false(result.requires_human, label="escalated"),
        is_true(sent, label="sent"),
        equals(mailbox.labels.get("msg-001"), ["auto-answered"], label="labels"),
    )


@case(
    id="triage-hostile-complaint-escalates",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A hostile, urgent complaint mentioning a lawyer reaches a human.",
)
def _() -> Score:
    result, sent, _ = _triage("msg-002")
    return combine(
        is_true(result.requires_human, label="escalated"),
        is_false(sent, label="not sent"),
        contains_all(
            " | ".join(result.escalation_reasons),
            ["complaint", "hostile", "urgent", "legal language"],
            label="reasons",
        ),
    )


@case(
    id="triage-body-scan-catches-refund",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A confident, benign-looking invoice query is held because the body says 'refund'.",
)
def _() -> Score:
    result, sent, _ = _triage("msg-003")
    return combine(
        is_true(result.classification.confidence >= 0.75, label="model was confident"),
        is_true(result.requires_human, label="escalated anyway"),
        equals(
            result.escalation_reasons,
            ["body mentions money leaving the business"],
            label="reason",
        ),
        is_false(sent, label="not sent"),
    )


@case(
    id="triage-low-confidence-escalates",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A vague email the model is unsure about goes to a person.",
)
def _() -> Score:
    result, sent, _ = _triage("msg-006")
    return combine(
        is_true(result.classification.confidence < 0.75, label="low confidence"),
        is_true(result.requires_human, label="escalated"),
        is_false(sent, label="not sent"),
    )


@case(
    id="triage-spam-neither-answered-nor-escalated",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Spam is filed: no reply, and no human time spent on it either.",
)
def _() -> Score:
    result, sent, mailbox = _triage("msg-005")
    return combine(
        is_false(result.requires_human, label="escalated"),
        is_false(sent, label="sent"),
        equals(mailbox.sent, [], label="outbox"),
    )


@case(
    id="triage-scheduling-auto-replies",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A friendly scheduling request is answered automatically.",
)
def _() -> Score:
    result, sent, _ = _triage("msg-004")
    return combine(
        equals(result.classification.intent, Intent.SCHEDULING, label="intent"),
        is_true(sent, label="sent"),
    )


# --- Policy -------------------------------------------------------------


@case(
    id="triage-policy-complaint-overrides-confidence",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A complaint escalates even when the model is completely certain.",
)
def _() -> Score:
    reasons = DEFAULT_POLICY.evaluate(_classification(intent=Intent.COMPLAINT, confidence=1.0))
    return equals(reasons, ["intent is complaint"], label="reasons")


@case(
    id="triage-policy-reports-every-reason",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="All applicable escalation reasons accumulate; none short-circuits.",
)
def _() -> Score:
    reasons = DEFAULT_POLICY.evaluate(
        _classification(
            priority=Priority.URGENT,
            intent=Intent.COMPLAINT,
            sentiment=Sentiment.HOSTILE,
            confidence=0.2,
        )
    )
    return equals(len(reasons), 4, label="reason count")


@case(
    id="triage-policy-threshold-is-a-floor",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Confidence exactly at the threshold is acceptable, not a trip wire.",
)
def _() -> Score:
    return equals(DEFAULT_POLICY.evaluate(_classification(confidence=0.75)), [], label="reasons")


@case(
    id="triage-policy-cannot-be-loosened-at-runtime",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The shared default policy is immutable.",
)
def _() -> Score:
    import pydantic

    try:
        DEFAULT_POLICY.min_confidence = 0.0
    except pydantic.ValidationError:
        return Score.hit("policy rejected mutation")
    return Score.miss("the shared policy was mutated")


@case(
    id="triage-no-escalated-draft-is-ever-sent",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Across the whole fixture inbox, nothing escalated reaches the sender.",
)
def _() -> Score:
    leaked = []
    for email_id in ("msg-001", "msg-002", "msg-003", "msg-004", "msg-005", "msg-006"):
        result, sent, _ = _triage(email_id)
        if result.requires_human and sent:
            leaked.append(email_id)
    return is_false(bool(leaked), label=f"no escalated email sent (leaked: {leaked})")


# --- Known gaps ---------------------------------------------------------


@case(
    id="triage-body-scan-misses-paraphrase",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="The body scan does not catch a legal threat phrased indirectly.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "SENSITIVE_PATTERNS is regex over fixed phrasings. 'our counsel will be "
        "in touch' means the same as 'my lawyer' and matches nothing. Fixing it "
        "properly needs a classifier, not more regexes."
    ),
)
def _() -> Score:
    reasons = DEFAULT_POLICY.evaluate(
        _classification(), body="Our counsel will be in touch about this matter."
    )
    return is_true(bool(reasons), label="paraphrased legal threat caught")


@case(
    id="triage-body-scan-is-english-only",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A German legal threat passes the body scan untouched.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Real inbound mail for this business is largely German. Every pattern "
        "in the policy is English, so the safety net does not exist for most of "
        "the actual inbox."
    ),
)
def _() -> Score:
    reasons = DEFAULT_POLICY.evaluate(_classification(), body="Wir schalten unseren Anwalt ein.")
    return is_true(bool(reasons), label="German legal threat caught")


@case(
    id="triage-no-thread-history",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="A third chaser is judged as though it were a first contact.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "Each email is classified alone. msg-002 says 'the third time I am "
        "writing' and only escalates because it is also angry; a polite third "
        "chaser would be treated as routine."
    ),
)
def _() -> Score:
    result, _sent, _ = _triage("msg-002")
    return contains_all(" | ".join(result.escalation_reasons), ["repeat contact"], label="reasons")


@case(
    id="triage-draft-not-checked-against-facts",
    agent=AGENT,
    layer=Layer.LOGIC,
    description="Nothing verifies that a drafted reply is factually supported.",
    expectation=Expectation.KNOWN_GAP,
    note=(
        "lead-research verifies claims against sources and call-intake verifies "
        "them against the transcript. The triage draft goes out unchecked; only "
        "the supervisor's codex looks at it, and only for claims it was told about."
    ),
)
def _() -> Score:
    result, sent, _ = _triage("msg-001")
    # Nothing in the agent inspects the draft for unsupported specifics.
    return excludes_all(
        result.classification.draft_reply if sent else "",
        ["Thursday"],
        label="draft avoids unbacked specifics",
    )

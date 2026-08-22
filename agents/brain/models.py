"""Data models for the supervising agent.

Every specialist agent in this repository produces its own result type. The
brain cannot review five different shapes, so each one is adapted into a common
`Decision` envelope: what an agent concluded, what it would do about it, and
what it already knows is wrong with it.

The verdict type is deliberately ordered, and `supervisor.review` combines
every reviewer's opinion with `max()`. Those two facts together are what make
"the brain can only ever be more conservative" checkable rather than merely
promised in a prompt.

Worth stating precisely, because an earlier version of this docstring did not:
the *type* supplies the ordering, it does not enforce the rule. Nothing here
stops a caller reaching for `min()`. The enforcement lives in `supervisor.py`
and is pinned by an exhaustive test over every combination of codex outcome and
reviewer opinion — which is where a guarantee of this kind has to live.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


class Verdict(IntEnum):
    """What may happen to a decision. Higher is stricter.

    Ordering is what the supervisor's guarantee rests on: `supervisor.review`
    combines every reviewer's verdict with `max()`, so no reviewer in the chain
    can loosen what another has tightened. `IntEnum` supplies that ordering —
    it inherits all four comparison operators from `int`, and `max()` and
    `sorted()` work on it with nothing added.

    This class previously carried `@total_ordering` and a hand-written
    `__lt__`. Both were dead: `total_ordering` only fills in operators
    inherited from `object`, and these come from `int`, so it generated
    nothing. The custom `__lt__` merely restated `int`'s behaviour while
    refusing comparisons against plain integers. The live reviewer crew found
    it, and two reviewers found it independently.
    """

    APPROVED = 0
    HOLD_FOR_HUMAN = 1
    BLOCKED = 2

    @property
    def label(self) -> str:
        """A human-readable name.

        Falls back to the member name rather than raising: a new verdict is a
        deliberate act, and a `KeyError` from a *display* helper is a poor way
        to find out that somebody added one.
        """
        return {
            Verdict.APPROVED: "approved",
            Verdict.HOLD_FOR_HUMAN: "hold for human",
            Verdict.BLOCKED: "blocked",
        }.get(self, self.name.lower().replace("_", " "))


class DecisionKind(StrEnum):
    """What a specialist agent proposes to do."""

    SEND_EMAIL = "send_email"
    ESCALATE_EMAIL = "escalate_email"
    ARCHIVE_EMAIL = "archive_email"
    PROPOSE_TIMES = "propose_times"
    BOOK_MEETING = "book_meeting"
    RECORD_CALL = "record_call"
    PUBLISH_RESEARCH = "publish_research"

    @property
    def is_outbound(self) -> bool:
        """Whether this decision puts text in front of someone outside the company."""
        return self in {
            DecisionKind.SEND_EMAIL,
            DecisionKind.PROPOSE_TIMES,
            DecisionKind.BOOK_MEETING,
        }


class Severity(IntEnum):
    """How badly a codex article was breached."""

    NOTE = 0
    CONCERN = 1
    BREACH = 2


class Decision(BaseModel):
    """One specialist agent's conclusion, in a form the brain can review."""

    id: str
    agent: str
    kind: DecisionKind
    subject: str = Field(description="What this decision is about, in a few words.")
    summary: str = ""

    #: Text that would reach someone outside the company, if this goes ahead.
    outbound_text: str = ""
    recipient: str | None = None

    #: Whether the recipient's contact details were actually confirmed. None
    #: means the question does not arise for this kind of decision.
    recipient_verified: bool | None = None

    #: What the specialist agent already concluded. The brain may not undo this.
    requires_human: bool = False
    escalation_reasons: list[str] = Field(default_factory=list)

    #: Claims attached to this decision that did not survive verification.
    unverified_claims: list[str] = Field(default_factory=list)

    cost_usd: float = 0.0
    trace_ref: str | None = None
    occurred_at: datetime | None = None


class CodexFinding(BaseModel):
    """One breach of the codex, found deterministically."""

    article: str
    title: str
    severity: Severity
    detail: str
    verdict: Verdict

    def render(self) -> str:
        return f"{self.article} {self.title}: {self.detail}"


class Judgement(BaseModel):
    """The model's opinion on a decision the codex did not settle.

    Field descriptions are prompt text. Note what the model is *not* asked: it
    never decides whether something is approved. It reports concerns, and the
    supervisor combines them with the codex by taking the stricter of the two.
    """

    concerns: list[str] = Field(
        default_factory=list,
        description=(
            "Things a careful manager would object to that a rule cannot catch: "
            "tone that would damage the relationship, a reply that misses what "
            "the customer actually asked, a commitment made too casually. Empty "
            "if nothing stands out."
        ),
    )
    recommend_hold: bool = Field(
        default=False,
        description=(
            "True if a person should look at this before it goes out. Setting "
            "this can only make the outcome stricter, never less strict, so err "
            "towards true when unsure."
        ),
    )
    rationale: str = Field(default="", description="One sentence explaining the recommendation.")


class Review(BaseModel):
    """The brain's complete assessment of one decision."""

    decision: Decision
    verdict: Verdict
    findings: list[CodexFinding] = Field(default_factory=list)
    judgement: Judgement | None = None
    reasons: list[str] = Field(default_factory=list)

    @property
    def is_approved(self) -> bool:
        return self.verdict is Verdict.APPROVED

    @property
    def breaches(self) -> list[CodexFinding]:
        return [f for f in self.findings if f.severity is Severity.BREACH]


class TaskPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TaskItem(BaseModel):
    """Something a person has to do today."""

    id: str
    title: str
    priority: TaskPriority = TaskPriority.NORMAL
    owner: str = "unassigned"
    source_decision: str | None = None
    origin_agent: str = ""
    why: str = ""

    @property
    def sort_key(self) -> tuple[int, str]:
        order = {
            TaskPriority.URGENT: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
        }
        return (order[self.priority], self.title)


class DailyReport(BaseModel):
    """Yesterday's activity and today's work."""

    generated_for: date
    covering: date

    reviews: list[Review] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)

    total_cost_usd: float = 0.0

    @property
    def approved(self) -> list[Review]:
        return [r for r in self.reviews if r.verdict is Verdict.APPROVED]

    @property
    def held(self) -> list[Review]:
        return [r for r in self.reviews if r.verdict is Verdict.HOLD_FOR_HUMAN]

    @property
    def blocked(self) -> list[Review]:
        return [r for r in self.reviews if r.verdict is Verdict.BLOCKED]

    @property
    def autonomy_rate(self) -> float:
        """Share of decisions that went ahead without a person. 0.0 if none."""
        return len(self.approved) / len(self.reviews) if self.reviews else 0.0

    @property
    def all_findings(self) -> list[CodexFinding]:
        return [finding for review in self.reviews for finding in review.findings]

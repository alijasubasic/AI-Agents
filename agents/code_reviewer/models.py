"""Data models for the improvement agent.

This agent writes code. That changes what the models have to carry.

Everywhere else in this repository the danger is an agent saying something
wrong. Here the danger is an agent *doing* something wrong to the codebase, and
the specific failure worth designing against is subtle: an agent that writes a
bad patch and then adjusts the thing that would have caught it. A weakened
assertion, a loosened lint rule, a deleted eval case — each makes the next run
look cleaner and the repository worse.

So a `Patch` carries the exact set of files it is allowed to touch, a
`Verification` records every gate separately rather than collapsing to a
boolean, and `ReviewRun` keeps what was attempted and failed alongside
what succeeded.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


class Severity(IntEnum):
    """How much a finding matters. Ordered so the worst sorts first."""

    NIT = 0
    MINOR = 1
    MAJOR = 2
    BLOCKER = 3

    @property
    def label(self) -> str:
        return self.name.lower()


class Reviewer(StrEnum):
    """The specialised reviewers. Each reads the same file for a different thing."""

    CORRECTNESS = "correctness"
    SECURITY = "security"
    ROBUSTNESS = "robustness"
    READABILITY = "readability"
    AGENT_QUALITY = "agent_quality"


class FileEntry(BaseModel):
    """One file in the scanner's index."""

    path: str
    lines: int
    functions: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    has_tests: bool = False
    test_path: str | None = None
    is_self: bool = Field(default=False, description="Part of the code reviewer itself.")
    protected: bool = Field(default=False, description="A file the code reviewer may never modify.")

    #: Higher means more worth reviewing. Deterministic; see scanner.py.
    priority: float = 0.0
    priority_reasons: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """One reviewer's observation about one file.

    Field descriptions are prompt text — this is the schema each reviewer fills.
    """

    reviewer: Reviewer
    path: str
    severity: Severity = Field(
        description=(
            "blocker for something that is wrong now, major for a real defect "
            "under conditions that will occur, minor for a genuine improvement, "
            "nit for taste. Most findings are minor or nit; be honest about it."
        )
    )
    title: str = Field(description="One line naming the problem.")
    detail: str = Field(description="Why it is a problem, concretely.")
    suggestion: str = Field(description="What to change. Specific enough that someone could do it.")
    anchor: str = Field(
        default="",
        description=(
            "A short verbatim snippet from the file showing where this is. "
            "Checked against the file, so copy it."
        ),
    )

    @property
    def key(self) -> tuple[str, str]:
        """Identity for deduplication: the file and a normalised title."""
        return (self.path, " ".join(self.title.lower().split()))


class PatchStatus(StrEnum):
    """What became of a patch."""

    APPLIED = "applied"
    #: Written, verified, and thrown away because a gate failed.
    REVERTED = "reverted"
    #: Refused before anything was written, by a safety rule.
    REFUSED = "refused"


class Patch(BaseModel):
    """One change addressing exactly one finding."""

    finding: Finding
    branch: str
    #: Files this patch is permitted to touch. Anything else fails the scope
    #: gate, however good the change is.
    allowed_paths: list[str] = Field(default_factory=list)

    #: New full contents, keyed by path. Whole files rather than diffs: a diff
    #: that applies cleanly to the wrong place is a class of bug that does not
    #: exist if the agent has to write out what it means.
    changes: dict[str, str] = Field(default_factory=dict)
    regression_test: str = Field(
        default="",
        description="A test that fails without this change. Required for a bug fix.",
    )
    rationale: str = ""

    @property
    def touched(self) -> list[str]:
        return sorted(self.changes)

    @property
    def size(self) -> int:
        """Total characters written. Stands in for diff size."""
        return sum(len(text) for text in self.changes.values())


class Gate(StrEnum):
    """The checks a patch must pass. All of them, or it is reverted."""

    SAFETY = "safety"
    SCOPE = "scope"
    TESTS = "tests"
    LINT = "lint"
    EVALS = "evals"
    REGRESSION_TEST = "regression_test"


class GateResult(BaseModel):
    """One gate, run."""

    gate: Gate
    passed: bool
    detail: str = ""


class Verification(BaseModel):
    """Every gate for one patch.

    Kept as a list rather than collapsed to a boolean so the improvement log
    can say *which* gate refused a patch. "Rejected" is not useful feedback;
    "the eval score fell from 100% to 92%" is.
    """

    results: list[GateResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(result.passed for result in self.results)

    @property
    def failures(self) -> list[GateResult]:
        return [result for result in self.results if not result.passed]

    @property
    def first_failure(self) -> GateResult | None:
        return self.failures[0] if self.failures else None


class PatchAttempt(BaseModel):
    """One patch and what happened to it."""

    patch: Patch
    status: PatchStatus
    verification: Verification = Field(default_factory=Verification)
    reason: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status is PatchStatus.APPLIED


class ReviewRun(BaseModel):
    """One `make improve` run, start to finish."""

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_date: date = Field(default_factory=lambda: datetime.now(UTC).date())

    scanned: list[FileEntry] = Field(default_factory=list)
    reviewed: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    worklist: list[Finding] = Field(default_factory=list)
    nits: list[Finding] = Field(default_factory=list)
    attempts: list[PatchAttempt] = Field(default_factory=list)

    halted_reason: str | None = None
    cost_usd: float = 0.0

    @property
    def applied(self) -> list[PatchAttempt]:
        return [attempt for attempt in self.attempts if attempt.succeeded]

    @property
    def reverted(self) -> list[PatchAttempt]:
        return [a for a in self.attempts if a.status is PatchStatus.REVERTED]

    @property
    def refused(self) -> list[PatchAttempt]:
        return [a for a in self.attempts if a.status is PatchStatus.REFUSED]

    @property
    def branches(self) -> list[str]:
        return [attempt.patch.branch for attempt in self.applied]

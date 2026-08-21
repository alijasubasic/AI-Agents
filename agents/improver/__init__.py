"""The improvement agent: reviews this repository and proposes patches.

Every guardrail here protects against the improver itself. It may analyse its
own package and may not patch it; it may report a problem in a test and may not
edit one. A code-writing agent's worst failure is not writing bad code — it is
writing bad code and adjusting whatever would have caught it.
"""

from agents.improver.models import (
    FileEntry,
    Finding,
    Gate,
    ImprovementRun,
    Patch,
    PatchAttempt,
    PatchStatus,
    Reviewer,
    Severity,
    Verification,
)
from agents.improver.pipeline import ImprovementPipeline
from agents.improver.prioritizer import deduplicate, prioritise
from agents.improver.reporter import render_entry, render_log, summarise, worst_unfixed
from agents.improver.reviewers import ReviewerCrew, anchor_is_real
from agents.improver.safety import (
    MAX_PATCHES_PER_RUN,
    branch_name,
    check_patch,
    is_protected,
    is_self,
    may_modify,
)
from agents.improver.scanner import candidates, scan
from agents.improver.verifier import verify
from agents.improver.workspace import GitWorkspace, MockWorkspace, Workspace

__all__ = [
    "MAX_PATCHES_PER_RUN",
    "FileEntry",
    "Finding",
    "Gate",
    "GitWorkspace",
    "ImprovementPipeline",
    "ImprovementRun",
    "MockWorkspace",
    "Patch",
    "PatchAttempt",
    "PatchStatus",
    "Reviewer",
    "ReviewerCrew",
    "Severity",
    "Verification",
    "Workspace",
    "anchor_is_real",
    "branch_name",
    "candidates",
    "check_patch",
    "deduplicate",
    "is_protected",
    "is_self",
    "may_modify",
    "prioritise",
    "render_entry",
    "render_log",
    "scan",
    "summarise",
    "verify",
    "worst_unfixed",
]

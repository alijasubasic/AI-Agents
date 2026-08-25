"""The improvement agent: reviews this repository and proposes patches.

Every guardrail here protects against the code reviewer itself. It may analyse its
own package and may not patch it; it may report a problem in a test and may not
edit one. A code-writing agent's worst failure is not writing bad code — it is
writing bad code and adjusting whatever would have caught it.
"""

from agents.code_reviewer.models import (
    FileEntry,
    Finding,
    Gate,
    Patch,
    PatchAttempt,
    PatchStatus,
    Reviewer,
    ReviewRun,
    Severity,
    Verification,
)
from agents.code_reviewer.pipeline import ReviewPipeline
from agents.code_reviewer.prioritizer import deduplicate, prioritise
from agents.code_reviewer.reporter import render_entry, render_log, summarise, worst_unfixed
from agents.code_reviewer.reviewers import ReviewerCrew, anchor_is_real
from agents.code_reviewer.safety import (
    MAX_PATCHES_PER_RUN,
    branch_name,
    check_patch,
    is_protected,
    is_self,
    may_modify,
)
from agents.code_reviewer.scanner import candidates, scan
from agents.code_reviewer.verifier import verify
from agents.code_reviewer.workspace import GitWorkspace, MockWorkspace, Workspace

__all__ = [
    "MAX_PATCHES_PER_RUN",
    "FileEntry",
    "Finding",
    "Gate",
    "GitWorkspace",
    "ReviewPipeline",
    "ReviewRun",
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

"""The improvement pipeline.

    scan → review → prioritise → patch → verify → report

Each patch gets its own branch, is verified alone, and is discarded outright if
any gate refuses it. Nothing is merged: a run produces branches and a report,
and a person decides what happens next.

The loop is written so that the failure path is the cheap one. A patch that
breaks a safety rule never reaches the workspace; a patch that fails scope
never reaches the test runner. Only a patch that has already earned it costs a
full suite.
"""

from __future__ import annotations

from datetime import date

from agents.code_reviewer.models import (
    FileEntry,
    Finding,
    Patch,
    PatchAttempt,
    PatchStatus,
    Reviewer,
    ReviewRun,
    Verification,
)
from agents.code_reviewer.patcher import Patcher
from agents.code_reviewer.prioritizer import prioritise
from agents.code_reviewer.reviewers import ReviewerCrew
from agents.code_reviewer.safety import MAX_PATCHES_PER_RUN, MAX_RUN_COST_USD
from agents.code_reviewer.verifier import EVAL_COMMAND, verify
from agents.code_reviewer.workspace import Workspace
from core.config import Settings
from core.llm import LLMProvider


class ReviewPipeline:
    """Runs one improvement pass over a workspace."""

    def __init__(
        self,
        *,
        workspace: Workspace,
        reviewer_providers: dict[Reviewer, LLMProvider],
        patcher_provider: LLMProvider,
        settings: Settings | None = None,
        run_date: date | None = None,
        max_patches: int = MAX_PATCHES_PER_RUN,
        max_cost_usd: float = MAX_RUN_COST_USD,
        review_limit: int = 3,
    ) -> None:
        self.workspace = workspace
        self.settings = settings or Settings.from_env()
        self.run_date = run_date or date.today()
        self.max_patches = min(max_patches, MAX_PATCHES_PER_RUN)
        self.max_cost_usd = min(max_cost_usd, MAX_RUN_COST_USD)
        self.review_limit = review_limit

        self.crew = ReviewerCrew(providers=reviewer_providers, settings=self.settings)
        self.patcher = Patcher(
            provider=patcher_provider, settings=self.settings, run_date=self.run_date
        )

    def run(self, index: list[FileEntry]) -> ReviewRun:
        """Review, patch and verify. Returns everything that happened."""
        result = ReviewRun(run_date=self.run_date, scanned=index)

        from agents.code_reviewer.scanner import candidates

        targets = candidates(index, limit=self.review_limit)
        if not targets:
            result.halted_reason = "nothing in the index was eligible for review"
            return result

        sources = self._read_sources(targets)
        self._review(targets, sources, result)
        if result.halted_reason:
            return result

        result.worklist, result.nits = prioritise(
            result.findings, {entry.path: entry for entry in index}, sources
        )

        baseline = self.workspace.run(EVAL_COMMAND)
        self._patch(result, sources, baseline_output=baseline.output)
        return result

    # -- stages ----------------------------------------------------------

    def _read_sources(self, targets: list[FileEntry]) -> dict[str, str]:
        sources: dict[str, str] = {}
        for entry in targets:
            try:
                sources[entry.path] = self.workspace.read(entry.path)
            except FileNotFoundError:
                # An index entry for a file that has since gone is not an error
                # worth stopping for; the next scan will not list it.
                continue
        return sources

    def _review(self, targets: list[FileEntry], sources: dict[str, str], result: ReviewRun) -> None:
        for entry in targets:
            if entry.path not in sources:
                continue
            if result.cost_usd > self.max_cost_usd:
                result.halted_reason = (
                    f"cost ceiling reached during review: ${result.cost_usd:.4f} of "
                    f"${self.max_cost_usd:.2f}"
                )
                return

            findings, cost = self.crew.review(
                entry.path, sources[entry.path], has_tests=entry.has_tests
            )
            result.findings.extend(findings)
            result.reviewed.append(entry.path)
            result.cost_usd += cost

    def _patch(self, result: ReviewRun, sources: dict[str, str], *, baseline_output: str) -> None:
        for finding in result.worklist:
            if len(result.applied) >= self.max_patches:
                result.halted_reason = f"patch ceiling reached: {self.max_patches} applied this run"
                return
            if result.cost_usd > self.max_cost_usd:
                result.halted_reason = (
                    f"cost ceiling reached: ${result.cost_usd:.4f} of ${self.max_cost_usd:.2f}"
                )
                return

            source = sources.get(finding.path)
            if source is None:
                continue

            patch, cost = self.patcher.write(finding, source)
            result.cost_usd += cost
            if patch is None:
                # The patcher looked and decided not to change anything. That is
                # an outcome worth recording, not a gap in the log.
                result.attempts.append(
                    PatchAttempt(
                        patch=self._empty_patch(finding),
                        status=PatchStatus.REFUSED,
                        reason="the patcher declined to change the file",
                    )
                )
                continue

            result.attempts.append(
                self._attempt(patch, applied=len(result.applied), baseline=baseline_output)
            )

    def _attempt(self, patch: Patch, *, applied: int, baseline: str) -> PatchAttempt:
        """Write a patch on its own branch, verify it, and keep it or discard it."""
        from agents.code_reviewer.verifier import check_safety

        # Safety is checked before anything is written. A refused patch must
        # never have existed in the workspace, not even briefly.
        safety = check_safety(patch, applied_so_far=applied)
        if not safety.passed:
            return PatchAttempt(
                patch=patch,
                status=PatchStatus.REFUSED,
                verification=Verification(results=[safety]),
                reason=safety.detail,
            )

        self.workspace.create_branch(patch.branch)
        for path, contents in patch.changes.items():
            self.workspace.write(path, contents)

        verification = verify(
            patch,
            self.workspace,
            applied_so_far=applied,
            baseline_eval_output=baseline,
        )

        if verification.passed:
            return PatchAttempt(
                patch=patch,
                status=PatchStatus.APPLIED,
                verification=verification,
                reason=f"all gates passed on {patch.branch}",
            )

        self.workspace.discard_changes()
        failure = verification.first_failure
        return PatchAttempt(
            patch=patch,
            status=PatchStatus.REVERTED,
            verification=verification,
            reason=f"{failure.gate.value} gate: {failure.detail}" if failure else "rejected",
        )

    def _empty_patch(self, finding: Finding) -> Patch:
        from agents.code_reviewer.safety import branch_name

        return Patch(
            finding=finding,
            branch=branch_name(self.run_date, finding.title),
            allowed_paths=[finding.path],
        )

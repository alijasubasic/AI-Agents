"""Turning a pile of findings into an ordered worklist.

Five reviewers over three files produces a list nobody will read. This module
reduces it, and every step is deterministic — which findings get worked on is
too consequential to leave to a model's ordering.

Three things happen here:

* **Deduplication.** Two reviewers noticing the same thing is a signal, not a
  duplicate to discard. The merged finding keeps the highest severity and
  records that more than one reviewer saw it.
* **Nits are collected, not queued.** A patch per nit produces ten branches
  nobody wants to review. They are reported together and worked on by hand, if
  at all.
* **Impact against risk.** A blocker in an untested file is worth more than a
  blocker in a well-tested one, because there is nothing else standing between
  it and production. A change to a file many things import is riskier than one
  to a leaf.
"""

from __future__ import annotations

from agents.improver.models import FileEntry, Finding, Severity
from agents.improver.reviewers import anchor_is_real

#: Findings whose anchor is not in the file are dropped entirely. A reviewer
#: quoting something that is not there did not read the file carefully, and
#: patching from that is how a good agent breaks a working function.
DROP_UNANCHORED = True


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """Merge findings that describe the same problem.

    Corroboration raises severity to the highest any reviewer assigned, and the
    detail records who else saw it — two reviewers independently flagging a
    line is the strongest signal this pipeline produces.
    """
    merged: dict[tuple[str, str], Finding] = {}

    for finding in findings:
        existing = merged.get(finding.key)
        if existing is None:
            merged[finding.key] = finding
            continue

        others = f"{existing.detail}\n\nAlso raised by {finding.reviewer.value}."
        merged[finding.key] = existing.model_copy(
            update={
                "severity": max(existing.severity, finding.severity),
                "detail": others,
            }
        )

    return list(merged.values())


def drop_unanchored(findings: list[Finding], sources: dict[str, str]) -> list[Finding]:
    """Remove findings whose quoted snippet is not in the file they name."""
    if not DROP_UNANCHORED:
        return findings
    return [
        finding
        for finding in findings
        if finding.path in sources and anchor_is_real(finding, sources[finding.path])
    ]


def score(finding: Finding, index: dict[str, FileEntry]) -> float:
    """Impact against risk. Higher is more worth doing.

    Severity dominates, as it should. The adjustments are small and stated:
    untested code is worth fixing sooner, and a widely-imported file is riskier
    to touch.
    """
    value = float(finding.severity) * 10.0
    entry = index.get(finding.path)
    if entry is None:
        return value

    if not entry.has_tests:
        value += 3.0

    # A long file is more likely to have a change land somewhere unexpected.
    if entry.lines > 400:
        value -= 1.0

    return value


def prioritise(
    findings: list[Finding],
    index: dict[str, FileEntry],
    sources: dict[str, str],
    *,
    limit: int = 10,
) -> tuple[list[Finding], list[Finding]]:
    """Return the worklist and the collected nits.

    Ties break on path then title, so two runs over an unchanged tree produce
    the same order and the improvement log can be diffed.
    """
    usable = drop_unanchored(deduplicate(findings), sources)

    nits = [finding for finding in usable if finding.severity is Severity.NIT]
    worklist = [finding for finding in usable if finding.severity is not Severity.NIT]

    worklist.sort(key=lambda finding: (-score(finding, index), finding.path, finding.title))
    return worklist[:limit], nits

"""The codex: what the business will and will not do, as executable rules.

A supervising agent whose principles live in its system prompt has no
principles — it has a suggestion that a long context, an unusual phrasing, or a
model upgrade can quietly erode. Nothing in this module asks a model anything.
Each article is a function over a `Decision`, and each returns a finding with
the article it breached and the verdict that follows.

The articles fall into two groups. A1 and A2 are about honesty and authority
and produce hard outcomes. A3 to A8 are about competence and market conduct;
they hold work for a person rather than destroying it, because most of what
they catch is a draft needing an edit rather than a decision that must not
happen.
"""

from __future__ import annotations

import re

from agents.brain.models import CodexFinding, Decision, Severity, Verdict

#: Ceiling per individual decision. A single email costing more than this means
#: something looped, and a person should see the trace before it recurs.
MAX_DECISION_COST_USD = 0.50

#: Commitments a machine must not make on the company's behalf without review.
_COMMITMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bguarantee[sd]?\b", "a guarantee"),
    (r"\bwe promise\b", "a promise"),
    (r"\bno later than\b", "a hard deadline"),
    (r"\bwill (?:ship|deliver|arrive|be delivered)\b", "a delivery commitment"),
    (r"[€$£]\s?\d", "a price"),
    (r"\b\d+\s?%\s*(?:discount|off)\b", "a discount"),
    (r"\bfree of charge\b", "a waiver of fees"),
)

#: Pressure selling. Legal in most places, and not how this business talks.
_PRESSURE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bact now\b", "urgency pressure"),
    (r"\blimited time\b", "artificial scarcity"),
    (r"\blast chance\b", "urgency pressure"),
    (r"\bonly today\b", "artificial scarcity"),
    (r"\bexpires? (?:today|soon)\b", "artificial scarcity"),
    (r"\bdo\W?n\W?t miss\b", "urgency pressure"),
    (r"\bhurry\b", "urgency pressure"),
    (r"\bfinal (?:offer|notice)\b", "urgency pressure"),
)

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{8,}\d)(?!\w)")

ARTICLES: dict[str, str] = {
    "A1": "Human authority",
    "A2": "Honesty",
    "A3": "No unbacked commitments",
    "A4": "Confirmed recipient",
    "A5": "Data minimisation",
    "A6": "Fair dealing",
    "A7": "Cost discipline",
    "A8": "Auditability",
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _finding(article: str, severity: Severity, detail: str, verdict: Verdict) -> CodexFinding:
    return CodexFinding(
        article=article,
        title=ARTICLES[article],
        severity=severity,
        detail=detail,
        verdict=verdict,
    )


# --- Articles -----------------------------------------------------------


def article_1_human_authority(decision: Decision) -> list[CodexFinding]:
    """A specialist agent's escalation is final. The brain may not overturn it.

    This is the article that makes the supervisor safe to add. Without it, a
    confident reviewer could talk itself past a guard that fired for good
    reason, and the system would be less safe with oversight than without it.
    """
    if not decision.requires_human:
        return []
    reasons = "; ".join(decision.escalation_reasons) or "no reason recorded"
    return [
        _finding(
            "A1",
            Severity.BREACH,
            f"{decision.agent} already routed this to a person ({reasons})",
            Verdict.HOLD_FOR_HUMAN,
        )
    ]


def article_2_honesty(decision: Decision) -> list[CodexFinding]:
    """Nothing unverified may be stated to a third party as fact.

    Checked against the outbound text specifically. Holding an unverified claim
    in an internal record is fine and often necessary; putting it in front of a
    customer is not.
    """
    if not decision.outbound_text or not decision.unverified_claims:
        return []

    body = _normalise(decision.outbound_text)
    leaked = [claim for claim in decision.unverified_claims if _normalise(claim) in body]
    if not leaked:
        return []

    return [
        _finding(
            "A2",
            Severity.BREACH,
            f"outbound text repeats {len(leaked)} unverified claim(s): {'; '.join(leaked[:3])}",
            Verdict.BLOCKED,
        )
    ]


def article_3_no_unbacked_commitments(decision: Decision) -> list[CodexFinding]:
    """Prices, deadlines and guarantees are made by people, not by agents."""
    if not decision.kind.is_outbound or not decision.outbound_text:
        return []

    found = [
        label
        for pattern, label in _COMMITMENT_PATTERNS
        if re.search(pattern, decision.outbound_text, re.IGNORECASE)
    ]
    if not found:
        return []

    return [
        _finding(
            "A3",
            Severity.CONCERN,
            f"outbound text contains {', '.join(sorted(set(found)))}",
            Verdict.HOLD_FOR_HUMAN,
        )
    ]


def article_4_confirmed_recipient(decision: Decision) -> list[CodexFinding]:
    """Never write to an address nobody confirmed.

    `recipient_verified is None` means the question does not arise for this kind
    of decision. `False` means it arose and the answer was no.
    """
    if not decision.kind.is_outbound or decision.recipient_verified is not False:
        return []

    return [
        _finding(
            "A4",
            Severity.BREACH,
            f"recipient {decision.recipient or 'unknown'} was never confirmed",
            Verdict.BLOCKED,
        )
    ]


def article_5_data_minimisation(decision: Decision) -> list[CodexFinding]:
    """Do not put a third party's contact details in someone else's message."""
    if not decision.outbound_text:
        return []

    recipient = _normalise(decision.recipient or "")
    others = {
        address
        for address in _EMAIL_RE.findall(decision.outbound_text)
        if _normalise(address) != recipient
    }
    phones = set(_PHONE_RE.findall(decision.outbound_text))
    if not others and not phones:
        return []

    parts = []
    if others:
        parts.append(f"{len(others)} third-party email address(es)")
    if phones:
        parts.append(f"{len(phones)} phone number(s)")

    return [
        _finding(
            "A5",
            Severity.CONCERN,
            f"outbound text contains {' and '.join(parts)}",
            Verdict.HOLD_FOR_HUMAN,
        )
    ]


def article_6_fair_dealing(decision: Decision) -> list[CodexFinding]:
    """No pressure selling, manufactured urgency, or invented scarcity."""
    if not decision.outbound_text:
        return []

    found = sorted(
        {
            label
            for pattern, label in _PRESSURE_PATTERNS
            if re.search(pattern, decision.outbound_text, re.IGNORECASE)
        }
    )
    if not found:
        return []

    return [
        _finding(
            "A6",
            Severity.BREACH,
            f"outbound text uses {', '.join(found)}",
            Verdict.HOLD_FOR_HUMAN,
        )
    ]


def article_7_cost_discipline(decision: Decision) -> list[CodexFinding]:
    """One decision costing this much means something looped."""
    if decision.cost_usd <= MAX_DECISION_COST_USD:
        return []
    return [
        _finding(
            "A7",
            Severity.CONCERN,
            f"decision cost ${decision.cost_usd:.4f}, over the "
            f"${MAX_DECISION_COST_USD:.2f} ceiling",
            Verdict.HOLD_FOR_HUMAN,
        )
    ]


def article_8_auditability(decision: Decision) -> list[CodexFinding]:
    """A decision nobody can reconstruct afterwards is not reviewable."""
    if decision.trace_ref:
        return []
    return [
        _finding(
            "A8",
            Severity.NOTE,
            "no trace reference recorded; this decision cannot be reconstructed",
            Verdict.HOLD_FOR_HUMAN,
        )
    ]


CHECKS = (
    article_1_human_authority,
    article_2_honesty,
    article_3_no_unbacked_commitments,
    article_4_confirmed_recipient,
    article_5_data_minimisation,
    article_6_fair_dealing,
    article_7_cost_discipline,
    article_8_auditability,
)


def apply_codex(decision: Decision) -> list[CodexFinding]:
    """Run every article. Findings accumulate; none short-circuits the rest.

    A reviewer should see everything wrong with a decision at once, not the
    first thing that happened to be checked.
    """
    return [finding for check in CHECKS for finding in check(decision)]


def codex_verdict(findings: list[CodexFinding]) -> Verdict:
    """The strictest verdict any article demanded."""
    return max((f.verdict for f in findings), default=Verdict.APPROVED)

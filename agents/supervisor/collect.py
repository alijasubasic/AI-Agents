"""Adapters turning each specialist agent's result into a `Decision`.

Every agent produces its own result type, shaped by its own problem. The supervisor
cannot review five different shapes, and giving the agents a shared base class
would have meant bending each of them towards the supervisor rather than
towards its own job.

So the translation lives here instead, one small function per agent. Adding a
sixth agent means writing a sixth adapter and changing nothing else.
"""

from __future__ import annotations

from agents.calendar_booking.models import BookingResult, MeetingProposal
from agents.call_intake.models import IntakeResult
from agents.email_triage.models import Email, TriageResult
from agents.lead_research.models import ResearchResult
from agents.outreach.models import OutreachResult
from agents.prospecting.models import ContactStatus, ProspectingResult
from agents.supervisor.models import Decision, DecisionKind


def from_triage(result: TriageResult, email: Email, *, sent: bool) -> Decision:
    """One triaged email.

    The sender address is treated as confirmed: they wrote to us from it, which
    is the strongest confirmation available for a reply address.
    """
    if sent:
        kind = DecisionKind.SEND_EMAIL
    elif result.requires_human:
        kind = DecisionKind.ESCALATE_EMAIL
    else:
        kind = DecisionKind.ARCHIVE_EMAIL

    return Decision(
        id=f"dec-email-{email.id}",
        agent="email-triage",
        kind=kind,
        subject=email.subject,
        summary=result.classification.summary,
        outbound_text=result.classification.draft_reply if sent else "",
        recipient=email.sender if sent else None,
        recipient_verified=True if sent else None,
        requires_human=result.requires_human,
        escalation_reasons=result.escalation_reasons,
        cost_usd=result.cost_usd,
        trace_ref=result.email_id,
        occurred_at=email.received_at,
    )


def from_booking(
    proposal: MeetingProposal,
    booking: BookingResult | None,
    *,
    decision_id: str,
    recipient: str | None = None,
    recipient_verified: bool | None = None,
) -> Decision:
    """A meeting proposal, and the booking if one was made."""
    booked = booking is not None and booking.booked
    outbound = booking.confirmation if booked and booking else proposal.message

    return Decision(
        id=decision_id,
        agent="calendar-booking",
        kind=DecisionKind.BOOK_MEETING if booked else DecisionKind.PROPOSE_TIMES,
        subject=proposal.request.title,
        summary=(f"{len(proposal.slots)} option(s) offered" + (", one booked" if booked else "")),
        outbound_text=outbound,
        recipient=recipient,
        recipient_verified=recipient_verified,
        # The booking agent has no escalation concept: it either finds times or
        # it does not, and a failure to find any is not a decision to review.
        requires_human=False,
        cost_usd=0.0,
        trace_ref=decision_id,
    )


def from_intake(result: IntakeResult) -> Decision:
    """One processed call.

    Unverifiable contact details become `unverified_claims`, so that if any of
    them later reach an outbound message the honesty article catches it.
    """
    return Decision(
        id=f"dec-call-{result.transcript_id}",
        agent="call-intake",
        kind=DecisionKind.RECORD_CALL,
        subject=f"Call {result.transcript_id}",
        summary=result.extraction.summary,
        requires_human=result.requires_human,
        escalation_reasons=result.escalation_reasons,
        unverified_claims=[issue.value for issue in result.grounding_issues],
        recipient_verified=(
            None
            if result.extraction.contact.email is None
            else not any(i.field == "email" for i in result.grounding_issues)
        ),
        cost_usd=result.cost_usd,
        trace_ref=result.transcript_id,
    )


def from_research(result: ResearchResult) -> Decision:
    """One researched company profile.

    Internal, so nothing goes out. The flagged claims travel with the decision
    anyway: they are what the honesty article compares against if this material
    is later used in something that does.
    """
    return Decision(
        id=f"dec-research-{result.company.lower().replace(' ', '-')}",
        agent="lead-research",
        kind=DecisionKind.PUBLISH_RESEARCH,
        subject=f"Research: {result.company}",
        summary=(
            f"{len(result.verified)}/{len(result.facts)} claims verified against "
            f"{len(result.sources)} source(s)"
        ),
        unverified_claims=[f.fact.value for f in result.flagged],
        requires_human=False,
        cost_usd=result.cost_usd,
        trace_ref=result.company,
    )


def outreach_from_research(
    result: ResearchResult, draft: str, *, recipient: str, recipient_verified: bool = True
) -> Decision:
    """An outbound email drafted from a research profile.

    This is where the chain closes. `lead-research` labelled some claims as
    unsupported; if a draft written from that profile repeats one of them to a
    prospect, the honesty article has everything it needs to stop it.
    """
    return Decision(
        id=f"dec-outreach-{result.company.lower().replace(' ', '-')}",
        agent="lead-research",
        kind=DecisionKind.SEND_EMAIL,
        subject=f"Outreach: {result.company}",
        summary="Prospect email drafted from the research profile",
        outbound_text=draft,
        recipient=recipient,
        recipient_verified=recipient_verified,
        unverified_claims=[f.fact.value for f in result.flagged],
        requires_human=False,
        cost_usd=0.0,
        trace_ref=result.company,
    )


def from_prospecting(result: ProspectingResult) -> Decision:
    """One area search.

    Internal: finding a business is not an act anyone outside the company sees,
    so nothing here can go wrong in a way a recipient experiences. It is still
    reviewed, for two reasons. The guessed addresses travel with it as
    `unverified_claims`, ready for A2 if any of them later turn up in a message.
    And a search that cost more than it should have is exactly the kind of thing
    that is invisible until somebody totals up the month.
    """
    guesses = [
        contact.value
        for lead in result.leads
        for contact in lead.contacts
        if contact.status is ContactStatus.CONSTRUCTED
    ]

    return Decision(
        id=f"dec-prospecting-{result.area.what.lower().replace(' ', '-')}-"
        f"{result.area.where.lower().replace(' ', '-')}",
        agent="prospecting",
        kind=DecisionKind.COLLECT_LEADS,
        subject=f"Recherche: {result.area.describe()}",
        summary=(
            f"{len(result.leads)} Betriebe aus {result.listings_seen} Einträgen "
            f"({result.duplicates_merged} Dubletten zusammengeführt), "
            f"{len(result.contactable)} mit bestätigter E-Mail"
        ),
        unverified_claims=guesses,
        requires_human=False,
        cost_usd=result.cost_usd,
        trace_ref=result.area.describe(),
    )


def from_outreach(result: OutreachResult) -> Decision:
    """One drafted first-contact email.

    Where the prospecting chain closes. The address's status was decided by
    whoever published it — or did not — long before this draft existed, and it
    travels here as `recipient_verified`. A draft to a guessed address is
    blocked by A9 no matter how good the draft is, and every claim the policy
    could not back is carried along for A2 to find in the text.
    """
    return Decision(
        id=f"dec-outreach-{result.lead_id}",
        agent="outreach",
        kind=DecisionKind.COLD_OUTREACH,
        subject=f"Erstkontakt: {result.company}",
        summary=result.email.personalisation or result.email.subject,
        outbound_text=result.message,
        recipient=result.recipient,
        recipient_verified=(
            None
            if result.recipient_status is None
            else result.recipient_status is ContactStatus.CONFIRMED
        ),
        contact_source=result.source_url,
        recipient_opted_out=result.suppressed,
        requires_human=result.requires_human,
        escalation_reasons=result.blockers,
        unverified_claims=result.unbacked_claims,
        cost_usd=result.cost_usd,
        trace_ref=result.lead_id,
    )


def follow_up_from_intake(result: IntakeResult, draft: str) -> Decision:
    """A follow-up email drafted after a call.

    The other half of the chain that `outreach_from_research` starts. Intake
    already established whether the caller's address was actually spoken; if it
    was not, this decision carries `recipient_verified=False` and the codex
    refuses to let anything be sent to it.
    """
    contact = result.extraction.contact
    email_was_verified = not any(issue.field == "email" for issue in result.grounding_issues)

    return Decision(
        id=f"dec-followup-{result.transcript_id}",
        agent="call-intake",
        kind=DecisionKind.SEND_EMAIL,
        subject=f"Follow-up to call {result.transcript_id}",
        summary="Email drafted after the call",
        outbound_text=draft,
        recipient=contact.email,
        recipient_verified=email_was_verified,
        unverified_claims=[issue.value for issue in result.grounding_issues],
        # Deliberately not inherited: this is a *new* decision about whether to
        # send, and the codex judges it on its own evidence. The underlying
        # call keeps its own escalation in its own decision.
        requires_human=False,
        cost_usd=0.0,
        trace_ref=result.transcript_id,
    )

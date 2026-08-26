"""The supervisor running a lead campaign: find businesses, write to them, decide.

This is the orchestration the rest of the repository's pipeline does for the
inbound agents, applied to the outbound ones. The supervisor does not do the work —
it decides what work happens, in what order, and which of the results are
allowed to leave the building:

    1. `prospecting` searches every platform for the area and merges the
       results into one row per business, with a source on every field.
    2. `outreach` drafts one short email per business, from the lead record
       only, with the identification and opt-out footer assembled in code.
    3. Each of those becomes a `Decision`, and the supervisor reviews every one
       against the codex and — where the codex left the question open — a
       reviewing model.
    4. Only decisions the supervisor approved are eligible to send, and even then
       only if the campaign was explicitly taken out of dry-run mode.

Step 4 is the part that matters. Three independent things have to agree before
an email reaches a stranger: the outreach policy, the codex, and a human who
turned dry-run off. Any one of them says no and nothing happens — and the
default value of every one of them is no.

The two agents never talk to each other. `prospecting` does not know that
outreach exists, `outreach` cannot search for anything, and neither can send
anything on its own. That is what makes the supervisor's approval the only route
between finding a business and writing to it.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from agents.outreach.agent import OutreachAgent
from agents.outreach.models import Campaign, OutreachResult
from agents.outreach.policy import DEFAULT_POLICY, OutreachPolicy
from agents.outreach.providers import MailSender
from agents.outreach.suppression import MemorySuppressionList, SuppressionProvider
from agents.prospecting.agent import LEAD_COLUMNS, ProspectingAgent, lead_row
from agents.prospecting.models import Lead, ProspectingResult, SearchArea
from agents.prospecting.providers import PageFetcher, PlaceProvider
from agents.supervisor.agent import SupervisorAgent
from agents.supervisor.collect import from_outreach, from_prospecting
from agents.supervisor.models import Decision, DecisionKind, Review, Verdict
from agents.supervisor.spreadsheet import Sheet
from core.config import Settings
from core.llm import LLMProvider

#: Builds the model provider for one lead's draft. A function rather than a
#: single provider because mock mode scripts one response per company, while
#: live mode hands back the same client every time.
DraftProviderFactory = Callable[[Lead], LLMProvider]

#: Builds the reviewing model for a set of decisions, or None to run the supervisor
#: on the codex alone — which is a legitimate configuration, and the cheap one.
JudgeFactory = Callable[[list[Decision]], LLMProvider | None]


class CampaignResult(BaseModel):
    """Everything one campaign produced, decisions included."""

    area: SearchArea
    campaign: Campaign
    prospecting: ProspectingResult
    drafts: list[OutreachResult] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    sent_to: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def leads(self) -> list[Lead]:
        return self.prospecting.leads

    @property
    def outreach_reviews(self) -> list[Review]:
        return [r for r in self.reviews if r.decision.kind is DecisionKind.COLD_OUTREACH]

    @property
    def approved(self) -> list[Review]:
        return [r for r in self.outreach_reviews if r.verdict is Verdict.APPROVED]

    @property
    def held(self) -> list[Review]:
        return [r for r in self.outreach_reviews if r.verdict is Verdict.HOLD_FOR_HUMAN]

    @property
    def blocked(self) -> list[Review]:
        return [r for r in self.outreach_reviews if r.verdict is Verdict.BLOCKED]

    @property
    def total_cost_usd(self) -> float:
        return round(self.prospecting.cost_usd + sum(d.cost_usd for d in self.drafts), 6)


class LeadCampaign:
    """The supervisor, steering the prospecting and outreach agents over one area."""

    def __init__(
        self,
        *,
        area: SearchArea,
        campaign: Campaign,
        places: Sequence[PlaceProvider],
        draft_provider: DraftProviderFactory | None = None,
        pages: PageFetcher | None = None,
        planner: LLMProvider | None = None,
        judge: JudgeFactory | None = None,
        policy: OutreachPolicy = DEFAULT_POLICY,
        sender: MailSender | None = None,
        suppression: SuppressionProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.area = area
        self.campaign = campaign
        self.policy = policy
        self.sender = sender
        self.suppression = suppression or MemorySuppressionList()
        self.settings = settings or Settings.from_env()
        self.judge = judge or (lambda _decisions: None)
        self._draft_provider = draft_provider

        self._prospecting = ProspectingAgent(
            places=list(places),
            pages=pages,
            provider=planner,
            settings=self.settings,
        )

    def run(self) -> CampaignResult:
        """Find, draft, review, and send whatever survived all three."""
        started = time.monotonic()

        prospecting = self._prospecting.find(self.area)
        drafts, agents = self._draft_all(prospecting.leads)

        decisions = [from_prospecting(prospecting), *(from_outreach(draft) for draft in drafts)]
        supervisor = SupervisorAgent(provider=self.judge(decisions), settings=self.settings)
        reviews = supervisor.review_all(decisions)

        sent_to = self._send_approved(reviews, drafts, agents)

        return CampaignResult(
            area=self.area,
            campaign=self.campaign,
            prospecting=prospecting,
            drafts=drafts,
            reviews=reviews,
            sent_to=sent_to,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    # -- internals -------------------------------------------------------

    def _draft_all(
        self, leads: list[Lead]
    ) -> tuple[list[OutreachResult], dict[str, OutreachAgent]]:
        """One draft per lead, up to the campaign ceiling.

        With no draft provider there is no outreach step at all, and the
        campaign is a search that gets reviewed. That is a real mode rather than
        a degenerate one: finding out who is in an area is useful on its own,
        and it is the mode that needs no model, no key and no mail server.

        The per-domain counter is shared across the loop rather than kept inside
        one agent, because each lead gets its own agent — that is what lets mock
        mode script a specific draft per company and live mode reuse one client.
        """
        if self._draft_provider is None:
            return [], {}

        already_written: Counter[str] = Counter()
        drafts: list[OutreachResult] = []
        agents: dict[str, OutreachAgent] = {}

        for lead in leads[: self.campaign.max_emails]:
            agent = OutreachAgent(
                provider=self._draft_provider(lead),
                campaign=self.campaign,
                policy=self.policy,
                sender=self.sender,
                suppression=self.suppression,
                settings=self.settings,
            )
            result = agent.draft(lead, already_written=already_written)

            drafts.append(result)
            agents[lead.id] = agent
            if result.recipient:
                already_written[result.recipient.split("@")[-1]] += 1

        return drafts, agents

    def _send_approved(
        self,
        reviews: list[Review],
        drafts: list[OutreachResult],
        agents: dict[str, OutreachAgent],
    ) -> list[str]:
        """Send exactly the drafts the supervisor approved, and nothing else.

        `OutreachAgent.send` checks the policy and the dry-run flag again. The
        duplication is deliberate: this function decides *which* drafts are
        eligible, and the agent decides whether an eligible one may actually go.
        Neither is in a position to be sure of the other's half.
        """
        by_id = {draft.lead_id: draft for draft in drafts}
        sent: list[str] = []

        for review in reviews:
            if review.decision.kind is not DecisionKind.COLD_OUTREACH:
                continue
            if review.verdict is not Verdict.APPROVED:
                continue

            draft = by_id.get(review.decision.trace_ref or "")
            agent = agents.get(review.decision.trace_ref or "")
            if draft is None or agent is None:
                continue

            if agent.send(draft, approved=True) and draft.recipient:
                sent.append(draft.recipient)

        return sent


# --- Reporting ----------------------------------------------------------


def lead_sheet(result: CampaignResult) -> Sheet:
    """The lead list, as a spreadsheet tab.

    This is the artefact the campaign exists to produce: company, person,
    email, phone — with the status of each contact detail on the same row, so
    nobody has to guess which of them are safe to use.
    """
    return Sheet(
        name="Leads",
        columns=list(LEAD_COLUMNS),
        rows=[lead_row(lead) for lead in result.leads],
    )


def outreach_sheet(result: CampaignResult) -> Sheet:
    """What was drafted for whom, and what the supervisor did about it."""
    verdicts = {
        review.decision.trace_ref: review
        for review in result.outreach_reviews
        if review.decision.trace_ref
    }

    rows = []
    for draft in result.drafts:
        review = verdicts.get(draft.lead_id)
        reasons = review.reasons if review else draft.blockers
        rows.append(
            [
                draft.company,
                draft.recipient or "",
                draft.recipient_status.value if draft.recipient_status else "",
                draft.email.subject,
                review.verdict.label if review else "nicht geprüft",
                "ja" if draft.sent else "nein",
                "; ".join(reasons),
            ]
        )

    return Sheet(
        name="Erstkontakte",
        columns=[
            "Firma",
            "E-Mail",
            "Status",
            "Betreff",
            "Urteil",
            "Versendet",
            "Gründe",
        ],
        rows=rows,
    )


def render_summary(result: CampaignResult) -> str:
    """A few lines a person can read without opening anything."""
    prospecting = result.prospecting
    return "\n".join(
        [
            f"Gebiet:        {result.area.describe()}",
            f"Einträge:      {prospecting.listings_seen} gefunden, "
            f"{prospecting.duplicates_merged} Dubletten zusammengeführt",
            f"Betriebe:      {len(result.leads)} "
            f"({len(prospecting.contactable)} mit bestätigter E-Mail, "
            f"{len(prospecting.with_phone)} mit Telefon, "
            f"{len(prospecting.with_person)} mit Ansprechpartner)",
            f"Entwürfe:      {len(result.drafts)}",
            f"Urteil:        {len(result.approved)} freigegeben, "
            f"{len(result.held)} zur Prüfung, {len(result.blocked)} blockiert",
            f"Versendet:     {len(result.sent_to)}"
            + ("  (Testlauf — dry_run=True)" if result.campaign.dry_run else ""),
            f"Kosten:        ${result.total_cost_usd:.4f}",
        ]
    )

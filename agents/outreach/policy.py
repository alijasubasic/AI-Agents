"""Whether a drafted email may be sent, decided in code.

The model is never asked this. It cannot be: the question "may we write to this
person" has one correct answer per case, the answer has to be identical on every
run, and the reasons have to be inspectable afterwards by somebody who was not
there. That is a policy, and a policy is `if` statements.

The checks fall into three groups:

**Consent and provenance.** Only an address the business published itself may be
written to unattended, and only if nobody has asked us to stop. A guessed
address, an address that only a directory knows, and an address on the
suppression list are all refused here rather than debated later.

**What the message says.** No pressure, no price, no invented facts. Every fact
the model claims to have used has to appear in the record it was given.

**Volume.** One email per business per campaign, and a ceiling on the run. A
system that can write two hundred emails is a system that will one day write two
hundred emails to the same domain.

Nothing here is subjective, so nothing here needs a model. What a rule cannot
catch — a tone that lands badly, a pitch that misses — is exactly what the
supervisor's reviewing model is for, and it runs after this.
"""

from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field

from agents.outreach.models import Campaign, OutreachEmail
from agents.outreach.suppression import MemorySuppressionList, SuppressionProvider
from agents.prospecting.models import ContactPoint, ContactStatus, Lead, domain_of

#: Phrasings that make a cold email a nuisance rather than an offer. Same
#: intent as codex article A6, checked here too so the draft never reaches the
#: supervisor in this state — a blocker with a reason is more useful to whoever
#: rewrites it than a verdict at the end of the pipeline.
_PRESSURE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bnur heute\b", "künstliche Verknappung"),
    (r"\bletzte chance\b", "Drucksprache"),
    (r"\bjetzt handeln\b", "Drucksprache"),
    (r"\bbegrenzte[sn]? (?:zeit|angebot)\b", "künstliche Verknappung"),
    (r"\bnur noch \d+\b", "künstliche Verknappung"),
    (r"\bverpassen sie nicht\b", "Drucksprache"),
    (r"\bexklusiv(?:es)? angebot\b", "Drucksprache"),
)

#: Commitments nobody authorised a machine to make. Mirrors codex article A3.
_COMMITMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    # German writes the currency after the number — "890 €" — and the codex's
    # English-shaped pattern misses that, which is why this list is not simply
    # imported from there.
    (r"[€$£]\s?\d|\d\s?(?:[€$£]|EUR\b|Euro\b)", "ein Preis"),
    (r"\b\d+\s?%\s*(?:rabatt|nachlass|günstiger|off)\b", "ein Rabatt"),
    (r"\bgarantier(?:en|t|e)\b", "eine Garantie"),
    (r"\bkostenlos\b", "eine Zusage über Kosten"),
    (r"\bspätestens\b", "eine Frist"),
)

#: Wording that satisfies the opt-out requirement. The footer in `models.py`
#: writes the first of these; the check is broader so a hand-edited message that
#: says the same thing differently still passes.
_OPT_OUT_RE = re.compile(
    r"\babmeld\w*\b|\bkeine weitere\w*\b|\bwiderspr\w*\b|\baustragen\b"
    r"|\bunsubscribe\b|\bopt[- ]?out\b",
    re.IGNORECASE,
)


class OutreachPolicy(BaseModel):
    """The rules a draft has to clear before anything is sent."""

    require_confirmed_email: bool = True
    require_opt_out: bool = True
    require_identification: bool = True

    max_per_domain: int = Field(default=1, ge=1)
    max_body_words: int = Field(default=170, ge=40)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    def evaluate(
        self,
        lead: Lead,
        contact: ContactPoint | None,
        email: OutreachEmail,
        message: str,
        *,
        campaign: Campaign,
        suppression: SuppressionProvider | None = None,
        already_written: Counter[str] | None = None,
    ) -> list[str]:
        """Every reason this may not be sent unattended. Empty means it may.

        Reasons accumulate: a draft with three problems reports three, because
        whoever fixes it should see all of them at once rather than discovering
        the next one after each edit.
        """
        suppression = suppression or MemorySuppressionList()
        already_written = already_written or Counter()

        reasons: list[str] = []
        reasons += self._check_recipient(lead, contact, suppression, already_written)
        reasons += self._check_message(email, message, campaign)
        reasons += [
            f"unbelegte Angabe: {claim}" for claim in unbacked_claims(email, lead, campaign)
        ]

        if lead.confidence < self.min_confidence:
            reasons.append(
                f"Konfidenz {lead.confidence:.2f} unter dem Minimum "
                f"{self.min_confidence:.2f} — der Betrieb ist nur schwach belegt"
            )

        return reasons

    # -- internals -------------------------------------------------------

    def _check_recipient(
        self,
        lead: Lead,
        contact: ContactPoint | None,
        suppression: SuppressionProvider,
        already_written: Counter[str],
    ) -> list[str]:
        if contact is None:
            return ["keine E-Mail-Adresse vorhanden"]

        reasons: list[str] = []

        if contact.status is ContactStatus.INVALID:
            reasons.append(f"{contact.value} nimmt keine Post an ({contact.note or 'ungültig'})")
        elif self.require_confirmed_email and not contact.contactable:
            reasons.append(
                f"{contact.value} ist {contact.status.value}, nicht vom Betrieb selbst "
                f"veröffentlicht"
            )

        blocked = suppression.blocks(contact.value)
        if blocked is not None:
            reasons.append(
                f"{contact.value} steht auf der Sperrliste"
                + (f" ({blocked.reason})" if blocked.reason else "")
            )

        domain = domain_of(contact.value)
        if already_written[domain] >= self.max_per_domain:
            reasons.append(
                f"an {domain} wurde in dieser Kampagne bereits "
                f"{already_written[domain]}× geschrieben"
            )

        return reasons

    def _check_message(self, email: OutreachEmail, message: str, campaign: Campaign) -> list[str]:
        reasons: list[str] = []

        if not email.subject.strip():
            reasons.append("kein Betreff")
        if not email.body.strip():
            reasons.append("kein Text")

        words = len(email.body.split())
        if words > self.max_body_words:
            reasons.append(f"Text ist {words} Wörter lang, erlaubt sind {self.max_body_words}")

        if self.require_opt_out and not _OPT_OUT_RE.search(message):
            reasons.append("kein Abmeldehinweis im Text")

        if self.require_identification and campaign.sender.company.lower() not in message.lower():
            reasons.append("Absender ist im Text nicht identifizierbar")

        for pattern, label in _PRESSURE_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                reasons.append(f"{label} im Text")
        for pattern, label in _COMMITMENT_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                reasons.append(f"{label} im Text, den niemand freigegeben hat")

        return reasons


def unbacked_claims(email: OutreachEmail, lead: Lead, campaign: Campaign) -> list[str]:
    """Facts the model says it used that are not in the record it was given.

    Checked by token coverage: every meaningful word of the claim — anything
    four characters or longer, plus every number — has to appear somewhere in
    the record. Short words are ignored, so "Dachdecker in München" passes
    against a record that says "Dachdecker" and "München" separately.

    The obvious cheaper check, "does any known fact appear inside the claim",
    was the first version of this function and it was worthless: "über 200
    sanierte Dächer im Raum München" contains "München", so a fabricated
    project count passed as backed because the town name was real. Numbers are
    exactly what this needs to catch, which is why they count as meaningful
    however short they are.
    """
    known_blob = " ".join(campaign.known_facts(lead)).lower()

    unbacked: list[str] = []
    for claim in email.facts_used:
        needle = claim.strip()
        if not needle:
            continue

        tokens = [
            token
            for token in re.split(r"[^\wäöüßÄÖÜ]+", needle.lower())
            if len(token) >= 4 or token.isdigit()
        ]
        if any(token not in known_blob for token in tokens):
            unbacked.append(needle)

    return unbacked


#: What a cold campaign runs under unless someone deliberately loosens it.
DEFAULT_POLICY = OutreachPolicy()

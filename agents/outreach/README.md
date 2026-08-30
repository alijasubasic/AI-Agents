# outreach

Writes one short first-contact email per business, and refuses to send most of
them.

```bash
python -m agents.outreach.demo    # fixtures, no key, no network, nothing sent
```

---

## Kurzanleitung (deutsch)

```bash
# 1. Absenderidentität in .env eintragen (OUTREACH_SENDER_*)
# 2. Entwürfe erzeugen und vom Brain prüfen lassen — nichts wird versendet:
make leads WHAT="Dachdecker" WHERE="München" OUTREACH=1

# 3. Erst wenn die Entwürfe passen und SMTP_* gesetzt ist:
make leads WHAT="Dachdecker" WHERE="München" OUTREACH=1 SEND=1
```

Jede Mail enthält automatisch — nicht vom Modell geschrieben, sondern im Code
zusammengesetzt: wer schreibt, mit Impressum-Link; warum dieser Betrieb
angeschrieben wird und über welche Plattform er gefunden wurde; und einen Satz,
mit dem der Empfänger die Kontaktaufnahme dauerhaft beendet.

Wer „Abmelden“ antwortet, gehört in `suppression.jsonl`. Diese Liste blockiert
danach die ganze Domain, nicht nur das eine Postfach.

---

## The one idea worth taking from this agent

**Sending needs three independent yesses, and every default is no.**

```python
if not approved or not result.auto_send_allowed or self.campaign.dry_run:
    return False
```

- the **policy** found nothing wrong (`agents/outreach/policy.py`)
- the **supervisor** approved the decision (`agents/supervisor/campaign.py`)
- a **person** turned dry run off (`--send`, and nothing else does it)

None of the three can be inferred from the other two, so all three are checked
at the point of sending rather than trusted to whoever assembled the call. The
failure mode of forgetting one of them is silence, not a hundred emails.

## What the model writes, and what it must not

The model writes a subject, a greeting and three to five sentences. Everything
that has to be there for the email to be lawful and honest is assembled in code,
in `render_message`:

```
Viele Grüße
Lena Hartwig, Vertrieb Handwerk          <- who is writing
Sturmfest Systeme GmbH
Gewerbepark 4, 85560 Ebersberg
Impressum: https://…/impressum           <- how to check who that is

--
Wir schreiben Ihnen einmalig, weil … Ihr Eintrag öffentlich zugänglich ist
(gefunden über Google Maps, OpenStreetMap, Firmenwebsite).   <- why you
Wenn Sie keine weitere Nachricht von uns möchten, antworten Sie bitte kurz
mit „Abmelden“ — wir vermerken das dauerhaft.                <- how to stop it
```

A model that can rewrite the opt-out line is a model that will eventually
improve it away. The prompt tells it not to write a footer at all, and
`policy.evaluate` checks the assembled message for the opt-out and the sender
identification anyway — because the value of a guarantee is what happens after
somebody refactors the code that was holding it up.

**The model never sees a scraped page.** It gets the normalised fields of a
`Lead` — name, city, trade, the person's name and role. The imprint text those
came from is third-party content that anyone can edit, and feeding it to a model
about to write in your name is how a stranger gets to dictate what you say.

## What stops a send

Every rule is deterministic, and every one of them has a case that fires it and
a case that does not in [`tests/test_policy.py`](tests/test_policy.py).

| Rule | Why |
|---|---|
| Address must be `CONFIRMED` | a guess reaches whoever really owns that mailbox |
| Not on the suppression list | one mailbox opting out covers the whole domain |
| One email per domain per campaign | an imperfect merge should not mean three emails |
| Confidence ≥ 0.5 | a business only one platform has heard of may not exist |
| Opt-out and sender identification present | checked on the assembled text |
| No prices, discounts, guarantees, deadlines | nobody authorised a machine to commit |
| No urgency or manufactured scarcity | this is a first contact, not a closing sequence |
| Every claim backed by the record | see below |

The claims check is token coverage, not substring matching. The first version
asked "does any known fact appear inside the claim", and

> über 200 sanierten Dächern im Raum München

passed, because *München* was real. Now every word of four letters or more, and
every number, has to appear somewhere in the lead record. Numbers count however
short they are — a fabricated project count is exactly what this exists to
catch.

## The demo

Five businesses. One email clears every rule. The other four are stopped by four
different rules, none of which is visible in the draft:

```
[  ok  ] Reiter Bedachungen GmbH  ->  m.reiter@reiter-bedachungen.example
[ STOP ] Nordwind Dachtechnik GmbH   - steht auf der Sperrliste
[  ok  ] Bauzentrum Isartal e.K.  ->  info@bauzentrum-isartal.example
[ STOP ] Dachdeckerei Sailer & Sohn  - Adresse ist constructed
[ STOP ] Alpenblick Dach & Fassade   - Adresse ist reported
                                     - unbelegte Angabe: über 200 sanierten …
```

Nordwind is the best lead in the run — three platforms, a named managing
director, a confirmed personal address — and it is the one nobody may write to.
A suppression list that only ever blocks weak leads has never been tested.

## Files

| File | What is in it |
|---|---|
| `models.py` | `Campaign`, `OutreachEmail`, `OutreachResult`, `render_message` |
| `policy.py` | every reason not to send, as `if` statements |
| `suppression.py` | the do-not-contact list, JSONL on disk |
| `providers.py` | `MockSender` and SMTP with `List-Unsubscribe` |
| `agent.py` | draft, apply policy, and the three-yes send |

## What this does not do

- **Read replies.** The message promises that "Abmelden" stops further contact,
  and a person currently has to add that entry by hand. Wiring `email-triage`
  to `FileSuppressionList.add` is the obvious next step, and until it exists the
  promise is kept by the operator rather than by the code.
- **Check that an address accepts mail.** Syntax only, no MX lookup. A typo in a
  published imprint is sent to and bounces.
- **Follow up.** One email per business, ever. Sequences are where cold outreach
  turns into a nuisance, and adding them is a decision for a person, not a
  default.
- **Check claims in the prose.** Only `facts_used` is verified, and the model
  fills that in itself.

All three gaps are scored, failing, in
[`evals/cases/outreach.py`](../../evals/cases/outreach.py).

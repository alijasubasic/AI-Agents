# ADR 0006 — A contact detail carries where it was published

**Status:** Accepted

## Context

The prospecting agent produces email addresses and phone numbers. They arrive
from four different kinds of place, and as strings they are indistinguishable:

```
info@reiter-bedachungen.example      the company's own imprint
info@alpenblick-dach.example         a directory entry, maintained by nobody
s.sailer@sailer-dach.example         built from "Stefan Sailer" plus the domain
kontakt@studio-nordlicht.example     the web agency in the footer of their site
```

The obvious design stores one field, `email`, and lets whoever uses it decide.
That decision then has to be made again at every call site, by somebody who no
longer has the evidence, and the guessed address is the one that looks most
convincing — a personal-looking address at the right domain for a person who
really does work there.

Every "verified emails from Google Maps" product ships this mixture. The
verification refers to the syntax.

## Decision

Provenance is a field on the contact detail, not context the caller is expected
to remember.

- `ContactPoint` carries `status`, `platform`, `source_url` and `found_on`.
- `ContactStatus` has four members: `CONFIRMED` (the business published it, on
  its own domain), `REPORTED` (a third party says so), `CONSTRUCTED` (a pattern
  produced it), `INVALID` (no-reply, or not an address).
- `Lead.best_email()` returns `CONFIRMED` addresses only. Anything else has to
  be dug out of `lead.emails` deliberately.
- The outreach policy refuses to send to anything but `CONFIRMED`, and codex
  article A9 refuses again at the supervisor.
- A constructed address is still generated and still shown, labelled, in the
  export. It is never used by an automated step.

An address on a different domain than the business's own is `REPORTED` even
when it appears on their site, with the reason recorded — the web agency case
above.

## Rationale

- **The dangerous case is the convincing one.** A guessed address is formatted
  exactly like a real one and often belongs to a real person who never published
  it. The only thing separating them is where it came from, so that is what gets
  stored.
- **One decision, made once, in the place with the evidence.** The extractor
  knows which page it read. A policy three modules later does not, and a
  salesperson opening a CSV certainly does not.
- **It makes the refusal checkable.** "Never mail a guessed address" is a
  property of an enum comparison, testable exhaustively, rather than a rule
  somebody has to remember. Two independent layers enforce it, and the eval
  suite scores both.
- **A guess is still useful to a person.** Deleting it would lose real
  information; promoting it to a fact would be a lie. Showing it with
  `geraten` in the status column is neither.
- **It survives the export.** The status is a column in the CSV, so the
  distinction reaches the person who actually decides whether to write, rather
  than dying at the module boundary.

## Consequences

- Every producer of a contact detail must state a status, including future ones.
  There is no default, which is the point.
- Businesses that publish only a contact form end up with no usable address, and
  the lead says so rather than inventing one. Those firms are reachable by phone,
  and the export names the gap. This is scored as a known gap rather than
  quietly worked around.
- Reading company websites becomes load-bearing rather than an enrichment step:
  without it, a run produces phone numbers and almost no addresses. That is a
  fact about map platforms, not a limitation of this design, and making it
  visible was part of the intent.

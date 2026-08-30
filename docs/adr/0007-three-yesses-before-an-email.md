# ADR 0007 — Three independent yesses before a cold email

**Status:** Accepted

## Context

The outbound chain can, in principle, run unattended: find businesses in an
area, draft an email to each, send them. That is what the tooling exists to do,
and it is also the shape of every system that has ever accidentally mailed a
thousand strangers.

The failure is rarely a decision to spam anybody. It is a check that lived in
one place, and a code path that did not go through it — a retry, a new caller, a
refactor that moved the send one layer up.

The other half of the problem is that "is this all right to send?" has three
different kinds of answer, and they are not interchangeable:

- **Is it lawful and honest?** Deterministic. Same answer every run.
- **Would it embarrass us?** A judgement call a rule cannot encode.
- **Do we actually want to send today?** Nobody but the operator knows.

## Decision

`OutreachAgent.send` requires all three, checked at the point of sending:

```python
if not approved or not result.auto_send_allowed or self.campaign.dry_run:
    return False
```

- `auto_send_allowed` — the outreach policy found no reason not to.
- `approved` — the supervisor reviewed the decision and the codex did not block it.
- `not dry_run` — a person passed `--send`, which is the only thing in the
  repository that clears this flag.

Each default is the refusing one. `Campaign.dry_run` defaults to `True`, the
policy defaults to requiring a confirmed address, and a campaign with no
reviewer approves nothing.

The campaign runner also decides *which* drafts are eligible before calling
`send`, so the check happens twice from two directions. That duplication is
deliberate.

## Rationale

- **No single edit can open the gate.** Removing one condition still leaves two
  refusing. The cost of the redundancy is three lines; the cost of not having it
  is the failure mode this ADR exists for.
- **Each yes comes from something qualified to give it.** The policy is code, so
  it is exhaustively testable. The supervisor is a model plus a codex, so it catches
  what rules cannot. The operator is a person, so they know whether today is the
  day. Collapsing them into one check would mean one of the three answers being
  guessed by something unqualified to guess it.
- **Forgetting produces silence.** A caller who forgets to pass `approved`, or
  who never turns off dry run, sends nothing. The failure mode of every mistake
  is an email that did not go out, which is recoverable, rather than one that
  did, which is not.
- **It survives being wired into something else.** The campaign runner, the CLI
  and any future caller all go through the same three conditions, because they
  live inside `send` rather than in the code that calls it.

## Consequences

- Getting an actual email sent takes deliberate effort: a sender identity in the
  environment, SMTP credentials, and an explicit flag. That is friction, and it
  is the intended amount.
- The demo and the whole test suite can exercise the complete path — draft,
  review, send — with a mock sender and dry run on, so the sending code is
  covered without anything leaving the machine.
- A draft the policy blocked is still produced and still shown. A person can
  read it, fix the underlying problem, and send by hand; what they cannot do is
  get the system to send it for them without fixing anything.

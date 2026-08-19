# ADR 0004 — Agents delegate through types, not prose

**Status:** Accepted

## Context

`call-intake` needs `calendar-booking` to find meeting times. The obvious
implementation writes a sentence and hands it over:

```python
booking_agent.propose(f"Book 30 minutes with {caller.email} about {topic}")
```

This is how most multi-agent examples are wired, and it looks natural: agents
talk to each other the way people do.

## Decision

Agent-to-agent handoffs pass a **pydantic model**. `calendar-booking` gained
`propose_for(request: BookingRequest)`, which runs the scheduling engine and
makes no model call. `propose(text)` remains for the human boundary, where free
text is the only thing on offer.

## Rationale

- **The fields were already correct.** `call-intake` has parsed the caller's
  email, the topic, and the duration into typed fields. Rendering them into a
  sentence so another model can parse them back out is a lossy round trip whose
  only possible outcomes are "unchanged" and "wrong".
- **It removes a failure mode rather than handling one.** A prose handoff can
  drop an attendee, round a duration, or misread a date. A typed handoff cannot:
  the fields either validate or raise.
- **It is much cheaper and faster.** The delegation costs nothing and takes
  microseconds. In a system where one caller can trigger several handoffs, the
  saving compounds.
- **It makes the seam testable.** The test for this wires the booking agent up
  with a scripted provider holding exactly one response and asserts the response
  is still unconsumed after a delegation. "No model was involved" is a property
  the suite checks, not a claim in a README.
- **Prompt injection has one less path.** Text assembled from a caller's words
  and handed to a second model is a second opportunity for that caller's words
  to be read as instructions. A `BookingRequest` has no instruction-shaped
  field.

## Consequences

- Every delegating pair needs an agreed type. That is a real coupling: changing
  `BookingRequest` now affects `call-intake` as well as `calendar-booking`, and
  the compiler will not tell you, because Python.
- Specialist agents need two entry points — one for humans, one for agents —
  and both must stay in step. `propose` and `propose_for` share `_find`, which
  keeps the scheduling behaviour identical by construction, but the offer
  wording is rendered twice and could drift.
- Some genuinely fuzzy handoffs do not fit a schema. A delegation meaning
  "look into this and tell me what you find" has no useful type. When one
  appears, it gets prose and an explicit note saying why — not a silent
  exception to this rule.

## Revisit if

A handoff appears whose payload is genuinely open-ended. That is an argument for
a prose channel *alongside* the typed one, not for replacing it.

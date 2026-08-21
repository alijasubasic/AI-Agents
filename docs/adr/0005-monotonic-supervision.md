# ADR 0005 — Supervision may only tighten

**Status:** Accepted

## Context

The brain reviews decisions the specialist agents have already made. The
obvious design gives it full authority: it reads the decision, forms a view,
and issues a verdict. A supervisor that can approve as well as refuse.

That design has a failure mode which is easy to state and hard to notice. The
specialist agents contain guards that took real work to get right — an
escalation policy, a grounding check, an injection tripwire. Each of those
fires on evidence. A reviewing model asked "is this all right?" sees a summary,
not the evidence, and a confident model looking at a summary will sometimes
conclude that a guard overreacted.

At that point the system is **less safe with oversight than without it**.

## Decision

The supervisor may raise strictness and may never lower it.

- `Verdict` is an ordered enum: `APPROVED < HOLD_FOR_HUMAN < BLOCKED`.
- Every reviewer contributes a verdict, and they combine with `max()`.
- Codex article A1 states the same rule at the source: a specialist agent's
  escalation is final, and the brain records it rather than reweighing it.
- The reviewing model is never asked whether something is approved. It is asked
  for concerns and for a hold recommendation, both of which can only tighten.

## Rationale

- **It makes adding oversight risk-free.** Whatever the brain does, the outcome
  is at least as strict as the system without it. That turns "should we add a
  supervisor?" from a judgement call into an easy yes.
- **The guarantee is structural.** It follows from `max()` over an ordered type,
  so it holds for any reviewer, any prompt, and any future model. A prompt
  saying "never overrule an escalation" holds only until something in the
  context outweighs it.
- **It is exhaustively testable.** The property is checked over every
  combination of codex outcome and reviewer opinion, which is a small finite
  set. A behavioural promise about a model is not testable in that way.
- **It shortens the reviewing prompt.** The model is told its recommendation
  can only tighten, so it can be told to err towards caution without that
  advice costing anything. There is no over-approval failure mode to balance
  against.
- **It saves money.** Once the codex has blocked a decision, no opinion could
  change the outcome, so the model is not consulted at all.

## Consequences

- **A false escalation is permanent.** If a specialist holds something it
  should not have, the brain cannot release it. Only a person can, and until
  they do it sits in the brief. Over-cautious agents therefore generate work
  rather than saving it, and their thresholds have to be tuned on their own
  merits — the supervisor will not paper over them.
- **The autonomy rate is bounded by the strictest component.** In the demo it
  sits at 41%, and most of what is held is held by A1 rather than by anything
  the brain concluded itself. Raising it means improving the specialists, not
  the supervisor.
- **The brain cannot fix a bad decision, only stop it.** There is no path where
  it rewrites a draft and lets it through. That keeps the design honest but
  means a one-word problem still costs a human interruption.

## Revisit if

Never for the direction of the rule. If releasing an escalation ever becomes
necessary, it belongs behind an explicit human action with its own audit trail
— not inside the supervisor's ordinary verdict.

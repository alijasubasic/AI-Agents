# ADR 0003 — Model selection and thinking configuration

**Status:** Accepted

## Context

The Claude API exposes several models and several controls over how much the
model reasons before answering. Choosing badly costs money on every request, so
the default belongs in one place rather than scattered across agents.

## Decision

- **Default model: `claude-opus-5`** (`core.config.DEFAULT_MODEL`), overridable
  per-process via `ANTHROPIC_MODEL`.
- **Adaptive thinking**, not a fixed token budget: `thinking={"type": "adaptive"}`.
- **Effort as the cost dial**: `output_config={"effort": "high"}`.
- **No sampling parameters.** `temperature`, `top_p`, and `top_k` are not sent.
- **Prices live in one table**, `core/cost.py`, keyed by model ID.

## Rationale

- **Adaptive thinking over `budget_tokens`.** A fixed thinking budget is the
  wrong shape: it spends the same on a trivial classification as on a
  multi-step plan. Adaptive thinking lets the model scale reasoning to the task,
  and `effort` gives a coarse dial over the whole cost/quality tradeoff. The
  fixed-budget parameter is also rejected outright by current models.
- **No sampling parameters.** Current Claude models reject non-default
  `temperature`/`top_p`/`top_k`. Behaviour is steered by prompting instead,
  which is more legible anyway — a prompt states intent; a temperature value
  does not.
- **Opus as the default.** These agents make consequential decisions
  (escalating a customer email, booking a meeting). Being wrong costs more than
  the token difference. Individual agents can drop to a cheaper model where the
  task is genuinely simple; that is a per-agent decision recorded in that
  agent's README.
- **One price table.** Cost accounting is only as honest as its prices. A single
  table with a documented source is auditable; prices inlined at call sites are
  not. Unknown models fall back to the most expensive known tier, so a missing
  entry over-estimates rather than letting a run slip past its budget.

## Consequences

- The price table is a maintenance obligation. It must be checked against the
  published pricing page when models change, and `core/cost.py` names that
  source explicitly.
- Cost figures are list prices. Any negotiated discount is not reflected, so
  reported cost is an upper bound.
- Agents that would be well served by a cheaper model pay Opus rates until
  someone measures and overrides it. The eval suite is what makes that
  measurement possible.

## Revisit if

Eval scores show a cheaper model matching Opus on a given agent's task — then
that agent's default changes, with the eval delta recorded as the evidence.

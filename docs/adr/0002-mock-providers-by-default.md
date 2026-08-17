# ADR 0002 — Mock providers are the default, everywhere

**Status:** Accepted

## Context

Every agent here touches something external: the Claude API, and in later
agents Gmail, Google Calendar, telephony, and a CRM. The obvious design points
each agent at the real service and requires credentials to run anything.

That makes the repository unusable as a portfolio piece. A reviewer with five
minutes will not create four accounts to watch a demo.

## Decision

Every external dependency sits behind an interface with two implementations: a
`MockProvider` backed by synthetic fixtures, and a real one. **Mock is the
default.** Live mode is opt-in via `AGENT_MODE=live` and requires credentials.

`make demo` and `make test` must pass on a fresh clone with no `.env` file, no
API key, and no network access. CI enforces this by running the demo on every
push with no secrets configured.

## Rationale

- **A demo nobody can run is not a demo.** The five-minute review is the actual
  use case for this repository.
- **Deterministic evals.** Scripted mock responses mean the scores in `evals/`
  measure the agent. If a score moves, the agent changed — not the sampling.
- **Fast, free tests.** The suite runs in under a second and costs nothing, so
  it can run on every commit.
- **The seam is real.** Writing a mock forces a clean interface. Several
  abstractions in `core/` are sharper because they had to satisfy two
  implementations from day one.

## Consequences

- Mock fixtures must be maintained alongside the real providers, and they can
  drift from real API behaviour. Contract tests against the live providers are
  needed before anything here is trusted in production.
- Mock mode cannot catch prompt-quality regressions — the model's actual
  judgement is exactly what is stubbed out. That is what `evals/` is for, run
  deliberately in live mode.
- No customer data enters this repository under any circumstances. All fixtures
  are invented.

## Revisit if

Never for the default. The live/mock split may grow a third mode (record and
replay against real APIs) if fixture drift becomes a real maintenance problem.

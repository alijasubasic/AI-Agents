# ADR 0001 — No agent framework

**Status:** Accepted

## Context

Agent frameworks (LangChain, LlamaIndex, CrewAI, and friends) provide an agent
loop, tool abstractions, memory, and tracing out of the box. Using one would
have made the first agent in this repository land in an afternoon.

## Decision

Build the loop, tool registry, tracing, and cost accounting directly against
the Anthropic SDK. The only runtime dependencies are `anthropic` and `pydantic`.

## Rationale

- **The loop is the subject, not the plumbing.** This repository exists to show
  that I understand agent orchestration. Importing someone else's loop would
  hide exactly the thing a reviewer wants to see.
- **Guardrails are easier to place than to retrofit.** The step ceiling, the
  wall-clock deadline, the cost budget, and the retry policy live inside a loop
  I control. In a framework, each of those is a configuration hook I would have
  to discover, and some are not exposed at all.
- **Debuggability.** When an agent misbehaves, the stack trace ends in this
  repository. There is no layer of callbacks and dynamic dispatch between the
  symptom and the cause.
- **Dependency surface.** Frameworks move fast and break interfaces. Two
  well-maintained libraries is a smaller maintenance liability than a framework
  plus its transitive tree.

## Consequences

- More code to write and test up front: roughly 700 lines in `core/` before the
  first agent existed.
- Features that come free in a framework (vector stores, document loaders, a
  large integration catalogue) must be written here if a future agent needs them.
- In exchange, every behaviour of every agent is traceable to code in this repo,
  and the runtime is small enough to read in one sitting.

## Revisit if

An agent needs a substantial subsystem that is a solved problem elsewhere — a
production vector database client, for instance. Adopting one library for that
one job is not the same as adopting a framework for the loop.

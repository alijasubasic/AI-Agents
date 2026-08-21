# AI Agent Portfolio

Production-minded AI agent systems built directly on the Anthropic API — no
agent framework. The orchestration loop, tool registry, tracing, and cost
accounting are written by hand, because that machinery is the point.

**Every agent runs with no API key and no network.** Clone it and run
`make demo`.

```bash
git clone https://github.com/alijasubasic/AI-Agents.git
cd AI-Agents
make install
make demo
```

---

## Status

This repository is being built in public, one agent at a time. What is here is
finished and tested; what is not here says so.

| Component | Status |
|---|---|
| `core/` — agent loop, tools, providers, tracing, cost | ✅ Done |
| [`agents/email_triage`](agents/email_triage) — classify, extract, draft, escalate | ✅ Done |
| [`agents/calendar_booking`](agents/calendar_booking) — cross-timezone slot finding and booking | ✅ Done |
| [`agents/call_intake`](agents/call_intake) — transcript to verified record, typed delegation | ✅ Done |
| [`agents/lead_research`](agents/lead_research) — sourced facts, every claim labelled | ✅ Done |
| [`agents/brain`](agents/brain) — supervises every agent, writes the morning brief | ✅ Done |
| [`console/`](console) — overlay, ElevenLabs voice, Obsidian vault | ✅ Done |
| `agents/knowledge-base` — RAG with citations | ⬜ Next |
| `agents/self-improving` — evaluator/optimizer loop | ⬜ Planned |
| `agents/improver` — reviewer crew that patches this repo | ⬜ Planned |
| `evals/` — scored test cases per agent | ⬜ Planned |

---

## Architecture

```mermaid
flowchart TB
    subgraph core["core/ — shared runtime"]
        direction TB
        Loop["Agent loop<br/><i>step ceiling · deadline<br/>budget · retries</i>"]
        Registry["Tool registry<br/><i>schema from type hints</i>"]
        Provider["LLMProvider<br/><i>interface</i>"]
        Trace["Tracing + cost<br/><i>JSON per run</i>"]
    end

    Loop -->|"asks"| Provider
    Loop -->|"executes"| Registry
    Loop -->|"records"| Trace

    Provider --> Mock["MockProvider<br/><i>scripted · default</i>"]
    Provider --> Live["AnthropicProvider<br/><i>live · opt-in</i>"]

    Agents["agents/*<br/><i>system prompt + tools</i>"] -->|"built on"| Loop
    Trace --> Report["Trace log<br/><i>steps · tokens · $ · latency</i>"]
```

The loop itself is deliberately small:

```
while under every limit:
    ask the model
    if it requested tools  -> run them, feed all results back, continue
    otherwise              -> that is the answer, stop
```

Everything else is guardrails.

### What `core/` provides

| Module | Responsibility |
|---|---|
| `agent.py` | The loop, retries with jittered backoff, structured output |
| `tools.py` | `@tool` decorator; JSON schema derived from type hints and docstring |
| `llm.py` | `LLMProvider` interface, `MockProvider`, `AnthropicProvider` |
| `models.py` | Pydantic models for every boundary — no string parsing anywhere |
| `cost.py` | Per-model price table, per-run token and dollar accounting |
| `tracing.py` | One JSON file per run: steps, tools, tokens, cost, latency |
| `config.py` | Environment-driven settings with working defaults |
| `errors.py` | A distinct exception type per failure mode |

---

## The agents

### [email-triage](agents/email_triage) ✅

Classifies inbound mail (priority, intent, sentiment, confidence), extracts
action items, drafts a reply in a configured voice, and routes anything risky to
a human.

The idea worth stealing: **the model classifies, deterministic code decides.**
Adding a `requires_human` field to the output schema and letting the model fill
it in would be easier — and untestable. Instead an
[`EscalationPolicy`](agents/email_triage/policy.py) applies plain Python rules
with stated reasons, each covered by a test.

One rule reads the raw email body rather than the classification, so it catches
what the classifier missed. In the fixture inbox, a confidently-classified,
benign-looking invoice query is held back for review purely because the body
contains the word "refund".

```bash
python -m agents.email_triage.demo
```

### [calendar-booking](agents/calendar_booking) ✅

Finds times that work across several calendars and time zones, respecting
working hours, buffers and minimum notice. Offers three options spread across
days, books one, confirms it.

Same idea, different axis: **the model decides who and how long, the engine
decides when.** [`scheduling.py`](agents/calendar_booking/scheduling.py) has no
prompts and no model calls — intersecting busy blocks across time zones is
arithmetic, and a model asked to do it will be plausibly wrong in a way nobody
notices until two people join an empty call.

The model never sees a calendar, and the times it writes in its message are
discarded: the authoritative slots are recomputed from the calendars afterwards.
Booking involves no model at all, so it cannot fail because a provider is
rate-limited.

The fixture week straddles the US daylight saving change while Europe has not
switched yet, so the Berlin/New York overlap widens by an hour mid-horizon —
[pinned by a test](agents/calendar_booking/tests/test_scheduling.py).

```bash
python -m agents.calendar_booking.demo
```

### [call-intake](agents/call_intake) ✅

Turns a phone transcript into a verified record — what the caller wanted, who
they are, what they asked for — and, when they asked for a meeting, real
openings fetched from the booking agent.

**Nothing the model reports about the caller is believed without checking it.**
A model reading a noisy transcript will occasionally produce a contact detail
that sounds right and was never said, and the extraction gives no sign of which
is which. So every detail is checked back against the caller's own words. One
fixture is scripted to hallucinate on purpose, so the demo shows the guard
firing rather than merely claiming it exists.

**The transcript is data, never instructions.** One fixture is someone reading
an instruction-override attempt down the phone. Three independent things stop
it, and none relies on the model behaving: detection runs *before* the model is
consulted, the prompt draws an explicit data boundary, and policy — not the
model — refuses to act.

**Delegation is typed.** When a meeting is wanted, this agent hands
`calendar-booking` a `BookingRequest`, not a sentence, through an entry point
that calls no model at all. A test proves it by asserting the booking agent's
scripted response is still unconsumed afterwards.
→ [ADR 0004](docs/adr/0004-typed-agent-delegation.md)

```bash
python -m agents.call_intake.demo
```

### [lead-research](agents/lead_research) ✅

Researches a company, extracts structured facts with citations, and labels every
claim by how well the retrieved documents actually support it.

**Research is the easiest task here to fake convincingly.** Ask a model about a
company and it produces a tidy profile whether or not it read anything — a
plausible headcount is exactly as cheap to generate as a real one, and the
output looks identical either way. So the unit of output is a *fact with a
citation*, and [`verification.py`](agents/lead_research/verification.py) checks
each quote against the document it was attributed to.

Five labels: `VERIFIED`, `UNSOURCED`, `MISATTRIBUTED`, `DISPUTED`, `STALE`. Only
the first means "we found this written down". The demo corpus trips **all five**
— in the Kestrel profile, 2 of 7 claims survive. Two of the failures are
scripted on purpose: an invented CEO citation and an unsourced revenue figure,
because a labelling system whose failure paths have never run is one nobody
should rely on.

```bash
python -m agents.lead_research.demo
```

### [brain](agents/brain) ✅ — the supervisor

Runs every other agent, reviews what each of them decided, and writes the
morning brief.

**The brain can only ever be more conservative than the agent it supervises.**
An oversight layer that can also *approve* is not oversight — the moment it
talks itself past a guard that fired for good reason, the system is less safe
with supervision than without. So `Verdict` is an ordered enum and every
reviewer's opinion combines with `max()`. Nothing in the chain can lower what
another link raised, and the property is checked exhaustively rather than
promised in a prompt.
→ [ADR 0005](docs/adr/0005-monotonic-supervision.md)

**The codex is executable, not a prompt.** Eight articles in
[`codex.py`](agents/brain/codex.py) — human authority, honesty, no unbacked
commitments, confirmed recipient, data minimisation, fair dealing, cost
discipline, auditability. Dishonesty and unconfirmed recipients block a
decision outright; the rest hold it for a person, because most of what they
catch is a draft needing an edit.

**The chains close.** `lead-research` labels a revenue figure `UNSOURCED`; an
outreach draft repeats it to the prospect as fact; **A2 blocks the send**.
`call-intake` establishes a caller never spoke the address the model extracted;
a follow-up is drafted to it anyway; **A4 blocks the send**. Neither specialist
did anything wrong, and neither could have caught it alone.

**The model earns its place once.** A scheduling reply breaches no article, and
the reviewer holds it anyway: the draft names a specific time before anyone
checked the calendar. No rule could see that.

The morning brief answers two questions — what happened yesterday, what needs
a person today — as Markdown and as a spreadsheet (`Summary`, `Decisions`,
`Tasks today`, `Codex findings`).

```bash
make brief    # or: python -m agents.brain.demo
```

---

## The console

### [console/](console) ✅ — overlay, voice and vault

The layer a person actually looks at: a heads-up display, a spoken briefing,
and an Obsidian vault recording every decision.

**The console observes; it cannot act.** No button approves a held decision, no
endpoint sends a blocked email — the server refuses every HTTP method except
`GET` and `HEAD` before it looks at the path. A display with controls would be a
second way to approve something, one that never passes through the codex and
never lands in the audit trail. Two tests hold the line: one asserts the page
contains no `<form>`, `<button>` or `<input>`, the other walks every mutating
method and expects `405`.

**The overlay** is one self-contained HTML file — inline CSS, inline JSON, no
build step, no CDN. It opens from disk with the network unplugged. Decisions are
ordered by how much attention they need, not by time. Chrome's `--app` flag
turns it into the frameless always-on-top window.

**The voice** enforces its own per-character ceiling, because ElevenLabs bills
that way and a runaway loop would be a billing incident. Spoken and displayed
wording are generated separately: "2 of 7 (29%)" is fine in a table and
unintelligible aloud. Only blocks and urgent tasks are read out in detail —
reading seven approvals aloud trains the listener to stop paying attention by
the third, which is when the blocked one arrives.

**The Obsidian vault** is the one integration here built completely rather than
as a skeleton, because a vault is just a folder of Markdown files. Every
decision note links to its agent, its codex articles and the day's brief, so
opening `A2 Honesty` in Obsidian lists every decision that article has ever
blocked. Nobody built that view; it falls out of writing the links.

```bash
make brief      # render, speak and record one day
make overlay    # the same overlay, live on localhost
```


---

## Design decisions worth arguing about

**No framework.** The loop is what a reviewer wants to see; importing someone
else's would hide it. Two runtime dependencies: `anthropic` and `pydantic`.
→ [ADR 0001](docs/adr/0001-no-agent-framework.md)

**Mock by default, everywhere.** Every external service sits behind an interface
with a synthetic-fixture implementation. CI runs the full demo with no secrets
configured, which is what keeps the "clone it and run it" promise true.
→ [ADR 0002](docs/adr/0002-mock-providers-by-default.md)

**Adaptive thinking, no sampling parameters, one price table.** Cost accounting
is only as honest as its price source, so there is exactly one.
→ [ADR 0003](docs/adr/0003-model-selection.md)

**Agents delegate through types, not prose.** A handoff between two programs
that both speak pydantic has no reason to be re-parsed by a model.
→ [ADR 0004](docs/adr/0004-typed-agent-delegation.md)

**Supervision may only tighten.** An oversight layer that can also approve is
not oversight.
→ [ADR 0005](docs/adr/0005-monotonic-supervision.md)

**Tool schemas come from the code.** The `@tool` decorator derives the JSON
schema the model sees from the function's type hints and docstring, so the
schema cannot drift from the implementation.

**Failures reach the model.** A tool that raises, receives bad arguments, or
does not exist returns an error *result* rather than crashing the run — the
model gets a chance to correct itself. Only the loop's own guardrails stop a run.

**A halted run is still a result.** Hitting the step ceiling, the deadline, or
the budget populates `halted_reason` and returns the partial work. Callers
always get a `RunResult`, never a surprise exception.

---

## Guardrails

Every run is bounded on four axes, all configurable and all enforced in mock
mode too — so the limits themselves are covered by tests rather than only
discovered in production.

| Limit | Default | Env var | Behaviour on breach |
|---|---|---|---|
| Steps | 8 | `AGENT_MAX_STEPS` | Halt, keep partial work |
| Wall clock | 60 s | `AGENT_TIMEOUT_SECONDS` | Halt before the next model call |
| Cost | $1.00 | `AGENT_MAX_COST_USD` | Halt after the step that crossed it |
| Provider retries | 3 | — | Jittered exponential backoff, then halt |

---

## Running it

```bash
make install   # uv sync --all-extras
make demo      # every demo, all without an API key
make test      # pytest with coverage
make lint      # ruff check + format --check
make check     # everything CI runs, in the same order
```

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and `make`.

### Running against the real API

```bash
cp .env.example .env     # then set ANTHROPIC_API_KEY and AGENT_MODE=live
```

Live mode is strictly opt-in. No code path reaches the network unless
`AGENT_MODE=live` is set *and* a key is present.

---

## Limitations & what I would do next

Written down deliberately — an honest limitations section is worth more than a
feature list.

- **Mock mode cannot catch prompt regressions.** The model's judgement is
  exactly what the mock stubs out. The scripted fixtures prove the *loop* is
  correct, not that the *prompts* are good. That is what `evals/` is for, and
  the evals are not built yet.
- **No live contract tests.** Nothing currently verifies that `MockProvider` and
  `AnthropicProvider` agree on behaviour. Fixture drift is a real risk, and a
  small live-mode contract suite run on a schedule is the fix.
- **Cost figures are list prices.** Negotiated discounts are not modelled, so
  the reported cost is an upper bound. Prices are hand-maintained in
  `core/cost.py` and can go stale when models change.
- **The timeout is checked between steps, not during one.** A single pathological
  model call can overrun the deadline. Enforcing it mid-request needs the async
  client and a cancellation path.
- **No concurrency yet.** Tool calls within a step run sequentially even when the
  model requested several in parallel. The results are already batched into one
  message correctly, so this is a performance gap rather than a correctness one.
- **`core/` has no memory or context-compaction layer.** Long conversations will
  hit the context window. Compaction is a `core/` concern and belongs there
  before the orchestrator agent, not after.

---

## Repository layout

```
core/          shared runtime — loop, tools, providers, tracing, cost
agents/        one package per agent (README + demo + tests each)
evals/         scored test cases per agent
docs/adr/      architecture decision records
tests/         tests for core/
```

---

## License

MIT

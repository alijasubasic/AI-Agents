# jarvis

A J.A.R.V.I.S.-style operations dashboard for the agent fleet: arc reactor,
agent cards, a thirty-day activity heatmap, live session monitoring, system
diagnostics and quick capture into an Obsidian vault.

```bash
python -m jarvis          # http://127.0.0.1:8756
python -m jarvis.demo     # every panel, rendered to the terminal
```

One self-contained HTML page. No framework, no build step, no CDN — the
server's Content-Security-Policy forbids every external origin and a test
asserts the page contains no `https://` at all.

---

## Where this comes from

The look and the widget vocabulary are taken from
[AndrewKochulab/jarvis-dashboard](https://github.com/AndrewKochulab/jarvis-dashboard)
(MIT): the arc reactor, the agent cards, the activity heatmap, the
mission-control nav, quick capture, and the idea of reading Claude Code's own
session transcripts for telemetry. That is a good project and this is its
design.

The implementation is not shared. That one is ~12k lines of JavaScript running
inside an Obsidian note, with a Node companion server, a Tauri desktop shell
and a SwiftUI iOS app. This is Python rendering one page, on top of the console
that already exists in this repository.

### What was taken, and what changed

| Idea | Kept | Changed |
|---|---|---|
| Arc reactor | the whole visual | CSS keyframes rather than per-frame JS |
| Palette | the cyan-on-near-black | CSS custom properties, not a JS object merged at render |
| Agent cards | cards, avatars, skill pills | the registry is [checked against the filesystem](#the-registry-cannot-drift) |
| Live sessions | reading `~/.claude/projects/**/*.jsonl` | no `pgrep`; mtime answers the actual question |
| 30-day analytics | heatmap, peak hours, model split | [two counting bugs fixed](#the-cost-figures-were-wrong) |
| Quick capture | note into the vault | one fixed folder, [path containment asserted](#the-one-route-that-writes) |
| System diagnostics | the panel | reports guardrails, not CPU and memory |
| Voice command | — | not ported; `console/voice.py` already has ElevenLabs |
| Focus timer, quick launch | — | not ported; nothing to do with agents |

## The cost figures were wrong

Porting the analytics meant reading the transcript format closely, and two
errors fell out. Both are in the original.

**Claude Code writes one record per content block, not per message**, and every
record repeats the message's full `usage`. Summing across records counts the
same tokens up to seven times. On one real session here: 456M tokens and $367
naively, 252M and $177 deduplicated.

**Cache reads are billed**, at 0.1× the input rate. On a long agent session
they are most of the input. `input × rate + output × rate` misses nearly the
whole bill.

Both are covered in [`telemetry/README.md`](../telemetry/README.md) and pinned
by tests. Tool calls, notably, must *not* be deduplicated — each record carries
a different block — which is why one rule could not cover both.

## The registry cannot drift

The source keeps its fleet in a Markdown file with a YAML header that a person
edits by hand. That is the right shape: a fleet is data, and hard-coded cards
describe agents that were deleted a year ago.

The problem is that a hand-maintained list drifts silently. So
[`registry.py`](registry.py) is data *and* `test_registry.py` asserts it against
reality: every entry's package exists, its README exists, its demo module
imports — and, the one that actually catches drift, **no package under
`agents/` is missing from the list**. Add an agent and forget the card and the
suite fails.

## Two fleets, deliberately not joined

The source shows agent cards and live sessions as one thing, because there the
agents *are* Claude Code subagents and a card lighting up means that subagent
is running.

Here they are different things. The eight agents in `agents/` run in this
process when you type a request. The live sessions are Claude Code transcripts
on this machine that have nothing to do with them. Wiring one to the other
would make an agent card flicker because you opened a terminal somewhere else.

So there are two panels and each says what it is. `test_the_fleet_is_not_joined_to_live_sessions`
keeps them apart.

## Diagnostics report the guardrails, not the machine

The source's system-diagnostics panel shows CPU, memory and uptime. Those are
the wrong numbers for an agent fleet — the interesting question is not whether
the laptop is warm.

This panel runs the deterministic eval suite and reports the score, the
surprises and the documented known gaps, alongside the step ceiling, the run
deadline, the cost budget and the codex article count. All of it is free and
offline.

It is measured **once, at startup**. The eval run takes a couple of seconds; on
a four-second poll that would mean the machine never stops working to redraw
six numbers that only change when the code does. Telemetry, by contrast, is
re-read on every request, because it is cached against file modification times
and costs a `stat`.

## The one route that writes

Everything else in this console obeys one rule:

> The console may create work; it has no route that approves any.

`POST /api/capture` writes a Markdown note into the local vault, and it is
worth being explicit about why that stays on the right side of the line. A
captured note approves nothing, sends nothing, books nothing and overrides
nothing. It is the same category as typing a task: creating a record, not
authorising an action.

What it cannot do:

- **write outside one folder** — `Captures/`, fixed in code. There is no
  `folder` field in the payload, and a test asserts that adding one would not
  help.
- **escape the vault** — this route made a latent hole matter.
  `ObsidianVault` already sanitised the *filename*, but `note.folder` went into
  the path unchecked. It now resolves the target and refuses anything that
  leaves the root, so every writer is covered, including ones nobody has
  written yet.
- **grow without limit** — bodies over 4 KB are refused, matching the cap the
  server puts on request bodies.

## No handler is written into an attribute

The earlier console generated `onclick="answer('${id}', …)"`. That nests data
inside a JavaScript string inside an HTML attribute: two layers of quoting, and
an apostrophe in the wrong field escapes both.

Here every control carries `data-` values and one delegated listener reads them
off the element. There is no layer for a quote to escape from, and
`test_the_page_has_no_inline_event_handlers` keeps it that way. Everything
rendered goes through `textContent`; the page builds nodes and never
concatenates into `innerHTML`.

The bootstrap payload is escaped for `<script>` embedding — `json.dumps`
escapes quotes but not angle brackets, so a task containing the literal
`</script>` closed the block early. That was a real hole, found by a test
written against it.

## Panels

| Panel | Source of truth |
|---|---|
| Communication link | the `ChatSession` — the same one `python -m console.chat_demo` drives |
| Decisions | the brain's morning brief |
| Agent fleet | `registry.py`, joined to this session's tasks |
| Live sessions | `telemetry` — real transcripts on this machine |
| Activity | `telemetry` — 30-day heatmap, hour-of-day, model split |
| System diagnostics | the eval suite and `Settings` |
| Quick capture | the Obsidian vault at `OBSIDIAN_VAULT_PATH` |

## Limitations

- **Conversations live in memory.** Restarting loses the transcript. The vault
  writer is right there and nothing yet writes conversations into it.
- **Polling, not streaming.** Four seconds. A long agent run looks like nothing
  happening, apart from the reactor spinning faster.
- **A task runs synchronously inside the POST.** A slow agent holds the request
  open, and the browser's timeout decides when to give up rather than the
  agent's.
- **One session, one operator.** No accounts, no locking. Two browsers share
  one conversation and will confuse each other.
- **Only three agents take free text.** `email-triage`, `call-intake` and the
  two repository agents work on structured fixtures; the cards say so rather
  than pretending otherwise.
- **The page is tested as a string, not in a browser.** These tests prove the
  markup contains what it should and nothing it shouldn't — not that it looks
  right.
- **No voice.** `console/voice.py` has an ElevenLabs provider and the reactor is
  a button that focuses the input, not a microphone. Wiring the two together is
  the obvious next step and is not done.

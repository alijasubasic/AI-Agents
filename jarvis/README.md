# jarvis

The operations dashboard: a force-directed graph of the whole system at the
centre, and three readouts behind it.

```bash
python -m jarvis          # http://127.0.0.1:8756
python -m jarvis.demo     # the same data, rendered to a terminal
```

One self-contained HTML page. No framework, no build step, no CDN — the
server's Content-Security-Policy forbids external origins and a test asserts
the page contains no `https://` at all.

---

## Layout

```
jarvis/
  registry.py     the fleet, as data
  graph.py        who may hand work to whom, and what it touches
  panels.py       the Dashboard model — everything one render needs
  diagnostics.py  the guardrails, measured
  capture.py      the one route that writes
  app.py          wiring: session + brief + telemetry + vault
  ui/
    theme.py      design tokens — the only file that writes a colour
    styles.py     the stylesheet
    sphere.py     the force-directed graph
    scripts.py    the client
    layout.py     the page skeleton
```

**Dependencies run one way.** The UI reads the models; the models know nothing
about a colour, a class name or an element id. That is what makes the data
layer testable without a browser and the styling replaceable without touching
a pydantic model — and it is asserted, because one `from jarvis.ui.theme
import` in `panels.py` would quietly end it.

[`test_structure.py`](tests/test_structure.py) checks four things: no data
module imports the UI, the UI does import the models, no hex value is written
outside `theme.py`, and the page template interpolates nothing but its four
asset slots. The colour check caught two hard-coded values the first time it
ran, which is roughly the half-life of that rule without one.

## Four views, not one long page

| | |
|---|---|
| **Operations** | the sphere, an inspector, the command box, recent decisions |
| **Fleet** | eight agents as rows — select one to focus it in the sphere |
| **Activity** | this machine's own Claude Code history |
| **Systems** | what is connected, what is not, and what the guardrails say |

The previous version stacked every readout on one page, which meant the sphere
shared the screen with a heatmap, a diagnostics grid and a capture form, and
none of them had room. Switching is client-side and hash-addressed, so a link
to `#activity` opens on Activity and the back button works. Nothing is fetched
on a switch — the server already sent everything.

## The sphere

![the sphere](../docs/img/sphere.svg)

**Position is derived, not drawn.** Fixed coordinates are easier and they lie:
they make the picture a drawing rather than a consequence. Nodes repel, edges
pull at a rest length set by the link kind, and each kind is held to its ring —
so an agent that touches three outside systems is pulled toward the rim by
three springs on its own, and adding a delegation to the model rearranges the
layout without anyone repositioning a circle.

**The layout is seeded**, so the same fleet settles into the same shape on
every reload and a screenshot stays true. `Math.random` would make the graph
impossible to learn.

**The layout does not depend on animation.** `requestAnimationFrame` does not
fire in a background tab or a pane the browser is not compositing. An earlier
version relaxed the graph inside the frame callback, so in those cases every
node sat stacked at the origin — found by a headless check, not by looking.
The simulation now runs to rest synchronously before the first paint.

### Every edge is a call that exists in the code

This is the claim that makes the picture worth anything, and it is checked
rather than asserted in prose. [`test_graph.py`](tests/test_graph.py) compares
each drawn agent-to-integration edge against the agent's real constructor
signature — **in both directions**:

- an edge drawn for a provider the agent does not take fails
- a provider the agent *does* take that is missing from the picture also fails

A systems diagram is the easiest thing in a repository to lie with. It costs
nothing to draw an arrow, nobody runs it, and a reader takes it as evidence.

## Two fleets, deliberately not joined

Agent cards and live sessions are separate panels here, and the source design
this borrows from joins them. There its agents *are* Claude Code subagents, so
a card lighting up means that subagent is running. Here the eight agents run in
this process when you type a request, and the live sessions are Claude Code
transcripts that have nothing to do with them — wiring one to the other would
make an agent card flicker because you opened a terminal somewhere else.

## Diagnostics report the guardrails, not the machine

Not CPU, memory and uptime. The interesting question about an agent fleet is
whether the limits still hold, so the panel runs the deterministic eval suite
and reports the score, the surprises and the documented known gaps, alongside
the step ceiling, the run deadline, the cost budget and the codex article
count. All of it free and offline.

Measured **once, at startup** — the eval run takes a couple of seconds, and on
a four-second poll that would mean the machine never stops working to redraw
six numbers that change only when the code does. Telemetry is the opposite: it
is re-read on every request, because it is cached against file modification
times and costs a `stat`.

## The one route that writes

Everything else obeys one rule:

> The console may create work; it has no route that approves any.

`POST /api/capture` writes a Markdown note into the local vault. A captured
note approves nothing, sends nothing, books nothing and overrides nothing — it
is the same category as typing a task. What it cannot do:

- **write outside one folder** — `Captures/`, fixed in code. There is no
  `folder` field in the payload, and a test asserts adding one would not help.
- **escape the vault** — this route made a latent hole matter. `ObsidianVault`
  sanitised the filename but let `note.folder` into the path unchecked. It now
  resolves the target and refuses anything that leaves the root.
- **grow without limit** — bodies over 4 KB are refused.

## Nothing becomes markup

Every value that came from a model, a transcript or a person is written with
`textContent`. The page builds nodes; it never concatenates into `innerHTML`,
and a test asserts the word does not appear in the file.

**No handler is written into an attribute.** An earlier console generated
`onclick="answer('${id}', …)"` — data inside a JavaScript string inside an HTML
attribute, two layers of quoting, and an apostrophe in the wrong field escapes
both. Every control carries `data-` values read by one delegated listener.

The bootstrap payload is escaped for `<script>` embedding: `json.dumps` escapes
quotes but not angle brackets, so a task containing the literal `</script>`
closed the block early. That was a real hole, found by a test written against
it.

The redesign removed an escaping call that had become *wrong*. The capture path
used to be HTML-escaped on its way into the markup; once it moved into the
payload and started going through `textContent`, escaping it meant a path
containing `&` displayed as `&amp;`. Escaping something that is never parsed as
HTML corrupts it.

## Where the look comes from

The visual language — the orb, the agent cards, the activity heatmap, and the
idea of reading Claude Code's own transcripts for telemetry — is taken from
[AndrewKochulab/jarvis-dashboard](https://github.com/AndrewKochulab/jarvis-dashboard)
(MIT). That project is ~12k lines of JavaScript inside an Obsidian note with a
Node companion server, a Tauri shell and a SwiftUI app; this is Python
rendering one page on top of the console that already existed here.

Porting its analytics found two errors in the original's arithmetic — see
[`telemetry/README.md`](../telemetry/README.md). Claude Code writes one record
per *content block*, each repeating the message's full usage, so summing across
records counts the same tokens up to seven times; and cache reads are billed at
0.1× input, which on an agent session is most of the bill.

## Limitations

- **Conversations live in memory.** Restarting loses the transcript. The vault
  writer is right there and nothing yet writes conversations into it.
- **Polling, not streaming.** Four seconds. A long agent run looks like nothing
  happening.
- **A task runs synchronously inside the POST.** A slow agent holds the request
  open, and the browser's timeout decides when to give up rather than the
  agent's.
- **One session, one operator.** No accounts, no locking. Two browsers share
  one conversation and will confuse each other.
- **Only three agents take free text.** The rest work on structured input; the
  fleet rows say so rather than pretending otherwise.
- **The page is tested as a string and driven headlessly**, which proves it
  contains what it should and behaves when clicked — not that it looks right.

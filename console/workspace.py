"""The operator workspace: an Obsidian-styled console you can type into.

Three panes, laid out the way Obsidian lays out a vault — a sidebar of what
exists, a main pane you work in, and a right pane of context.

    agents & tasks  |  conversation  |  what the brain decided

Self-contained: one HTML string, no framework, no CDN, no build step. It polls
a JSON endpoint and posts to two others. Everything it can do is in this file,
which is the property that makes it reviewable.

**The page has no control that approves anything.** It can create work and
answer a question. There is no approve button, no send button, no override —
those would be a second path around the codex, and the codex is the only reason
any of this is safe to run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from console.models import OverlayState
from console.tasks import Conversation, TaskStatus

#: Obsidian's dark palette, near enough to feel like the same application.
_CSS = """
:root {
  --bg: #1e1e1e; --bg-alt: #262626; --bg-panel: #202020;
  --border: #333; --text: #dcddde; --muted: #888;
  --accent: #a882ff; --accent-dim: #7c5cbf;
  --ok: #4caf7d; --hold: #d9a441; --block: #e05561;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.55 -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  height: 100vh; overflow: hidden;
}
.frame { display: grid; grid-template-columns: 240px 1fr 320px; height: 100vh; }
.pane { overflow-y: auto; padding: 14px 16px; }
.pane + .pane { border-left: 1px solid var(--border); }
.sidebar { background: var(--bg-panel); }
.context { background: var(--bg-panel); }

h1 { font-size: 13px; letter-spacing: .08em; text-transform: uppercase;
     color: var(--muted); margin: 0 0 12px; font-weight: 600; }
h2 { font-size: 11px; letter-spacing: .1em; text-transform: uppercase;
     color: var(--muted); margin: 18px 0 8px; font-weight: 600; }

.agent { padding: 5px 8px; border-radius: 4px; color: var(--text);
         display: flex; justify-content: space-between; gap: 8px; }
.agent:hover { background: var(--bg-alt); }
.agent .n { color: var(--muted); font-variant-numeric: tabular-nums; }

.tile { background: var(--bg-alt); border: 1px solid var(--border);
        border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }
.tile .big { font-size: 22px; font-weight: 600; }
.tile .lbl { font-size: 11px; color: var(--muted); text-transform: uppercase;
             letter-spacing: .08em; }

.card { border-left: 3px solid var(--border); background: var(--bg-alt);
        border-radius: 0 6px 6px 0; padding: 8px 11px; margin-bottom: 7px; }
.card.ok { border-left-color: var(--ok); }
.card.hold { border-left-color: var(--hold); }
.card.block { border-left-color: var(--block); }
.card .who { font-size: 11px; color: var(--muted); }
.card .what { font-size: 13px; }
.card .why { font-size: 11px; color: var(--muted); margin-top: 3px; }

.stream { display: flex; flex-direction: column; gap: 10px;
          padding-bottom: 14px; }
.turn { max-width: 78%; padding: 8px 12px; border-radius: 8px;
        background: var(--bg-alt); border: 1px solid var(--border);
        white-space: pre-wrap; word-wrap: break-word; }
.turn .who { font-size: 10px; letter-spacing: .09em; text-transform: uppercase;
             color: var(--muted); margin-bottom: 3px; }
.turn.operator { align-self: flex-end; background: var(--accent-dim);
                 border-color: var(--accent); }
.turn.operator .who { color: #e5dbff; }
.turn.brain { border-left: 3px solid var(--accent); }
.turn.system { color: var(--muted); font-size: 12px; }

.ask { border: 1px solid var(--accent); background: rgba(168,130,255,.09);
       border-radius: 8px; padding: 11px 13px; margin-bottom: 10px; }
.ask .q { font-weight: 600; }
.ask .why { font-size: 12px; color: var(--muted); margin: 3px 0 9px; }
.row { display: flex; gap: 6px; flex-wrap: wrap; }
button, input {
  font: inherit; border-radius: 5px; border: 1px solid var(--border);
  background: var(--bg-alt); color: var(--text); padding: 7px 11px;
}
button { cursor: pointer; }
button:hover { border-color: var(--accent); color: #fff; }
button.opt { background: transparent; border-color: var(--accent-dim); }
input { flex: 1; min-width: 0; }
input:focus, button:focus { outline: 1px solid var(--accent); }

.composer { position: sticky; bottom: 0; background: var(--bg);
            padding-top: 10px; border-top: 1px solid var(--border);
            display: flex; gap: 8px; }
.hint { font-size: 11px; color: var(--muted); margin-top: 7px; }
.empty { color: var(--muted); font-size: 13px; }
.busy { color: var(--accent); font-size: 12px; }
@media (max-width: 1000px) {
  .frame { grid-template-columns: 1fr; grid-template-rows: auto 1fr auto; }
  .pane + .pane { border-left: none; border-top: 1px solid var(--border); }
}
"""

_JS = """
const $ = (id) => document.getElementById(id);
let busy = false;

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

// Everything from the server is inserted as text, never as markup. A decision
// summary can contain an email a stranger wrote.
function render(state) {
  $('approved').textContent = state.approved;
  $('held').textContent = state.held;
  $('blocked').textContent = state.blocked;
  $('open').textContent = state.open_tasks;

  $('agents').innerHTML = state.agents.map(a =>
    `<div class="agent"><span>${esc(a.name)}</span><span class="n">${a.count}</span></div>`
  ).join('') || '<div class="empty">none</div>';

  $('stream').innerHTML = state.turns.map(t =>
    `<div class="turn ${esc(t.tone)}"><div class="who">${esc(t.speaker)}</div>${esc(t.text)}</div>`
  ).join('') || '<div class="empty">Nothing yet. Give an agent something to do.</div>';

  $('asks').innerHTML = state.questions.map(q => `
    <div class="ask">
      <div class="q">${esc(q.text)}</div>
      <div class="why">${esc(q.why)}</div>
      <div class="row">
        ${q.options.map(o => {
          const call = `answer('${esc(q.task_id)}','${esc(q.id)}','${esc(o)}')`;
          return `<button class="opt" onclick="${call}">${esc(o)}</button>`;
        }).join('')}
        <input id="in-${esc(q.id)}" placeholder="or type an answer"
               onkeydown="if(event.key==='Enter')answer('${esc(q.task_id)}','${esc(q.id)}',this.value)">
      </div>
    </div>`).join('');

  $('cards').innerHTML = state.cards.map(c => `
    <div class="card ${esc(c.tone)}">
      <div class="who">${esc(c.agent)}</div>
      <div class="what">${esc(c.subject)}</div>
      ${c.reasons.map(r => `<div class="why">${esc(r)}</div>`).join('')}
    </div>`).join('') || '<div class="empty">No decisions yet.</div>';

  const s = $('stream');
  s.scrollTop = s.scrollHeight;
}

async function post(url, body) {
  if (busy) return;
  busy = true;
  $('busy').textContent = 'working...';
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    render(await r.json());
  } catch (e) {
    $('busy').textContent = 'the console could not reach the server';
    return;
  } finally {
    busy = false;
  }
  $('busy').textContent = '';
}

function submit() {
  const box = $('request');
  const text = box.value.trim();
  if (!text) return;
  box.value = '';
  post('/api/task', {request: text});
}

function answer(taskId, questionId, text) {
  if (!String(text).trim()) return;
  post('/api/answer', {task_id: taskId, question_id: questionId, text: text});
}

async function refresh() {
  if (busy) return;
  try { render(await (await fetch('/api/state')).json()); } catch (e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  $('request').addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  render(BOOTSTRAP);
  setInterval(refresh, 4000);
});
"""

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading}</title>
<style>{css}</style></head>
<body>
<div class="frame">

  <aside class="pane sidebar">
    <h1>Agents</h1>
    <div id="agents"></div>
    <h2>Yesterday</h2>
    <div class="tile"><div class="big" id="approved">0</div>
      <div class="lbl">approved</div></div>
    <div class="tile"><div class="big" id="held">0</div>
      <div class="lbl">held</div></div>
    <div class="tile"><div class="big" id="blocked">0</div>
      <div class="lbl">blocked</div></div>
    <h2>Open tasks</h2>
    <div class="tile"><div class="big" id="open">0</div>
      <div class="lbl">waiting</div></div>
  </aside>

  <main class="pane">
    <h1>{heading}</h1>
    <div id="asks"></div>
    <div class="stream" id="stream"></div>
    <div class="composer">
      <input id="request" placeholder="Give an agent something to do...">
      <button onclick="submit()">Send</button>
    </div>
    <div class="hint" id="busy"></div>
    <div class="hint">
      This console can create work. It has no control that approves any —
      every result goes through the codex.
    </div>
  </main>

  <aside class="pane context">
    <h1>Decisions</h1>
    <div id="cards"></div>
  </aside>

</div>
<script>const BOOTSTRAP = {bootstrap};</script>
<script>{js}</script>
</body></html>
"""


def workspace_state(state: OverlayState, conversation: Conversation) -> dict:
    """Everything the page renders, as plain JSON-able data.

    Assembled here rather than in the template so the same payload serves the
    initial render and the polling endpoint — one shape, one place to change.
    """
    counts: dict[str, int] = {}
    for task in conversation.tasks:
        if task.agent:
            counts[task.agent] = counts.get(task.agent, 0) + 1

    questions = [
        {
            "id": question.id,
            "task_id": task.id,
            "text": question.text,
            "why": question.why,
            "options": question.options,
        }
        for task in conversation.waiting
        for question in task.open_questions
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "approved": state.approved,
        "held": state.held,
        "blocked": state.blocked,
        "open_tasks": conversation.open_count,
        "agents": [{"name": name, "count": count} for name, count in sorted(counts.items())]
        or [{"name": "no tasks yet", "count": 0}],
        "turns": [
            {"speaker": turn.speaker.value, "tone": turn.tone, "text": turn.text}
            for turn in conversation.turns
        ],
        "questions": questions,
        "cards": [
            {
                "agent": card.agent,
                "subject": card.subject,
                "tone": card.tone,
                "reasons": card.reasons[:2],
            }
            for card in state.cards
        ],
    }


def embed_json(payload: dict) -> str:
    """Serialise a payload for embedding inside a `<script>` block.

    `json.dumps` alone is not safe here, and the difference is a real hole
    rather than a theoretical one. It escapes quotes but leaves `<` and `>`
    alone, so a task containing the literal text `</script>` ends the block
    early and everything after it is parsed as markup — on a page the operator
    trusts, from a string an agent or a caller supplied.

    Escaping the three characters as `\\uXXXX` is still valid JSON, produces
    the same value once parsed, and cannot close a tag.
    """
    return (
        json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


def render_workspace(state: OverlayState, conversation: Conversation) -> str:
    """The whole console as one self-contained HTML page."""
    return _TEMPLATE.format(
        heading=state.heading or "Operator console",
        css=_CSS,
        js=_JS,
        bootstrap=embed_json(workspace_state(state, conversation)),
    )


def status_tone(status: TaskStatus) -> str:
    """CSS class for a task status, for callers rendering task lists."""
    return {
        TaskStatus.DONE: "ok",
        TaskStatus.ESCALATED: "hold",
        TaskStatus.BLOCKED: "block",
    }.get(status, "")

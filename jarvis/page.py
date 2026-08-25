"""The dashboard as one self-contained HTML page.

No framework, no build step, no CDN — the server's Content-Security-Policy
forbids every external origin and a test asserts the page contains no `https://`
at all. Everything it can do is in this file and `sphere.py`, which is what
makes it reviewable in an afternoon.

The layout has one centre and everything else reports to it. The
[operations sphere](sphere.py) is the top of the page: the supervisor in the
middle, the agents around it, the outside systems on the rim, and every edge a
call that exists in the code. Clicking a node explains it. The readouts below —
fleet, sessions, activity, diagnostics — are detail for whatever the sphere
just told you.

Two properties this page is built to keep, both security properties rather
than style ones:

**Nothing is ever inserted as markup.** Every value that came from a model, a
transcript or a person is set with `textContent`. The page builds nodes; it
never concatenates a string into `innerHTML`.

**No handler is written into an attribute.** The earlier console generated
`onclick="answer('${id}', ...)"`, which puts data inside a JavaScript string
literal inside an HTML attribute — two layers of quoting, and an apostrophe in
the wrong field breaks out of both. Here every control carries `data-` values
and one delegated listener reads them off the element. There is no layer for a
quote to escape from.
"""

from __future__ import annotations

import html
import json

from jarvis.panels import Dashboard
from jarvis.sphere import SPHERE_JS
from jarvis.styles import stylesheet

_JS_APP = r"""
'use strict';
const $ = (id) => document.getElementById(id);
let STATE = null;
let busy = false;

// --- building nodes, never markup ---------------------------------------

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function fill(id, nodes) {
  const host = $(id);
  if (!host) return;
  host.replaceChildren(...(Array.isArray(nodes) ? nodes : [nodes]));
}
function none(message) { return el('div', 'empty', message); }
function num(value) { return Number(value || 0).toLocaleString(); }
function money(value) { return '$' + Number(value || 0).toFixed(2); }

function tick() {
  const now = new Date();
  $('clock').textContent = now.toLocaleTimeString([], {hour12: false});
  $('date').textContent = now.toLocaleDateString([], {
    weekday: 'short', day: '2-digit', month: 'short'});
}

// --- panels --------------------------------------------------------------

function renderHeader(state) {
  $('subheading').textContent = state.subheading || '';
  const pills = [];
  pills.push(el('span', 'pill ' + (state.mode === 'live' ? 'live' : 'on'),
    state.mode === 'live' ? 'live · ' + state.model : 'mock · no network'));
  pills.push(el('span', 'pill', state.open_tasks + ' open'));
  pills.push(el('span', 'pill ok', state.approved + ' approved'));
  if (state.held) pills.push(el('span', 'pill hold', state.held + ' held'));
  if (state.blocked) pills.push(el('span', 'pill block', state.blocked + ' blocked'));
  fill('pills', pills);
}

function renderStream(state) {
  if (!state.turns.length) {
    fill('stream', none('Nothing yet. Pick a node, or type a task below.'));
    return;
  }
  fill('stream', state.turns.map((turn) => {
    const box = el('div', 'turn ' + (turn.tone || ''));
    box.appendChild(el('div', 'who', turn.speaker));
    box.appendChild(document.createTextNode(turn.text));
    return box;
  }));
  const host = $('stream');
  host.scrollTop = host.scrollHeight;
}

function renderQuestions(state) {
  fill('asks', state.questions.map((question) => {
    const box = el('div', 'ask');
    box.appendChild(el('div', 'q', question.text));
    box.appendChild(el('div', 'why', question.why));

    const row = el('div', 'row');
    (question.options || []).forEach((option) => {
      const button = el('button', null, option);
      button.dataset.task = question.task_id;
      button.dataset.question = question.id;
      button.dataset.answer = option;
      row.appendChild(button);
    });
    const free = el('input');
    free.placeholder = 'or type an answer';
    free.dataset.task = question.task_id;
    free.dataset.question = question.id;
    row.appendChild(free);
    box.appendChild(row);
    return box;
  }));
}

function renderFleet(state) {
  fill('fleet', state.fleet.map((member) => {
    const card = el('div', 'agent');
    card.style.setProperty('--c', member.colour);
    card.dataset.node = member.name;
    card.appendChild(el('span', 'status ' + member.tone));

    const head = el('div', 'head');
    head.appendChild(el('div', 'avatar', member.initials));
    const naming = el('div');
    naming.appendChild(el('div', 'name', member.title));
    naming.appendChild(el('div', 'meta',
      member.tasks ? member.tasks + ' task(s) · ' + member.last : member.name));
    head.appendChild(naming);
    card.appendChild(head);

    card.appendChild(el('div', 'blurb', member.blurb));
    const tags = el('div', 'tags');
    member.skills.forEach((skill) => tags.appendChild(el('span', 'tag', skill)));
    tags.appendChild(el('span', 'tag' + (member.reachable ? ' on' : ''),
      member.reachable ? 'takes free text' : 'fixtures only'));
    card.appendChild(tags);
    return card;
  }));
}

function renderSessions(state) {
  if (!state.sessions.length) {
    fill('sessions', none('No Claude Code session is active on this machine.'));
    return;
  }
  fill('sessions', state.sessions.map((session) => {
    const line = el('div', 'line');
    line.appendChild(el('span', 'beat ' + session.tone));
    const middle = el('div');
    middle.appendChild(el('div', null, session.project + ' — ' + session.doing));
    middle.appendChild(el('div', 'sub', session.session_id + ' · ' +
      (session.model || 'model unknown')));
    line.appendChild(middle);
    line.appendChild(el('span', 'age', session.age));
    return line;
  }));
}

function renderAnalytics(state) {
  const a = state.analytics;
  if (!a) return;

  $('analytics-note').textContent = a.real
    ? a.window_days + ' days of real history'
    : 'fixtures — no history found';

  fill('totals', [
    ['sessions', num(a.sessions), 'last ' + a.window_days + ' days'],
    ['messages', num(a.messages), 'turns, deduplicated'],
    ['tool calls', num(a.tool_calls), 'blocks, not turns'],
    ['tokens', num(a.tokens), 'cache reads included'],
    ['spend', money(a.cost_usd), 'list price, cache-aware'],
    ['per session', money(a.cost_per_session), 'mean across the window'],
  ].map(([key, value, detail]) => {
    const stat = el('div', 'stat');
    stat.appendChild(el('div', 'v', value));
    stat.appendChild(el('div', 'k', key));
    stat.appendChild(el('div', 'd', detail));
    return stat;
  }));

  // Heatmap. Blank cells pad the first column so a day lands on its weekday.
  const cells = [];
  const offset = a.days.length ? a.days[0].weekday : 0;
  for (let i = 0; i < offset; i++) {
    const blank = el('div', 'cell');
    blank.style.opacity = '0';
    cells.push(blank);
  }
  a.days.forEach((day) => {
    const cell = el('div', 'cell');
    cell.style.opacity = day.level ? String(0.18 + day.level * 0.82) : '0.06';
    cell.title = day.day + ' — ' + day.messages + ' messages, ' +
      day.sessions + ' session(s)';
    cells.push(cell);
  });
  fill('heat', cells);

  const peak = a.peak_hourly || 1;
  fill('hours', a.hourly.map((count, hour) => {
    const bar = el('div', 'bar' + (hour === a.busiest_hour ? ' peak' : ''));
    bar.style.height = Math.max(2, Math.round(count / peak * 84)) + 'px';
    bar.title = String(hour).padStart(2, '0') + ':00 — ' + count + ' records';
    return bar;
  }));
  $('peak').textContent = a.busiest_hour === null
    ? 'no activity recorded'
    : 'busiest at ' + String(a.busiest_hour).padStart(2, '0') + ':00';

  fill('models', a.models.length ? a.models.map((share) => {
    const box = el('div', 'share');
    const top = el('div', 'top');
    top.appendChild(el('span', null, share.family));
    top.appendChild(el('span', null, share.percent + '% · ' + money(share.cost_usd)));
    box.appendChild(top);
    const track = el('div', 'track');
    const bar = el('div', 'fill ' + share.family);
    bar.style.width = Math.max(2, share.percent) + '%';
    track.appendChild(bar);
    box.appendChild(track);
    return box;
  }) : none('nothing to split'));
}

function renderChecks(state) {
  fill('checks', state.checks.map((check) => {
    const stat = el('div', 'stat ' + (check.tone || ''));
    stat.appendChild(el('div', 'v', check.value));
    stat.appendChild(el('div', 'k', check.label));
    stat.appendChild(el('div', 'd', check.detail));
    return stat;
  }));
}

function renderDecisions(state) {
  fill('cards', state.cards.length ? state.cards.map((card) => {
    const box = el('div', 'card ' + card.tone);
    box.appendChild(el('div', 'who', card.agent));
    box.appendChild(el('div', null, card.subject));
    (card.reasons || []).forEach((reason) => box.appendChild(el('div', 'why', reason)));
    return box;
  }) : none('No decisions yet.'));
}

function render(state) {
  const firstRender = STATE === null;
  STATE = state;
  renderHeader(state);
  renderQuestions(state);
  renderStream(state);
  renderFleet(state);
  renderSessions(state);
  renderAnalytics(state);
  renderChecks(state);
  renderDecisions(state);

  if (state.graph) {
    renderSphere(state.graph);
    describeNode(Sphere.selected || 'supervisor');
    if (firstRender) { /* the sphere seeds itself deterministically */ }
  }
}

// --- talking to the server ----------------------------------------------

function working(on, message) {
  busy = on;
  const orb = $('sphere');
  if (orb) orb.classList.toggle('busy', on);
  $('status').textContent = message || '';
  $('send').disabled = on;
  if (on) nudge(0.7);
}

async function post(url, body) {
  if (busy) return false;
  working(true, 'working…');
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) {
      working(false, payload.error || 'refused');
      return false;
    }
  } catch (error) {
    working(false, 'the console could not reach the server');
    return false;
  }
  working(false, '');
  await refresh();
  return true;
}

async function refresh() {
  if (busy) return;
  try {
    const response = await fetch('/api/dashboard');
    if (response.ok) render(await response.json());
  } catch (error) { /* a dropped poll is not worth reporting */ }
}

function submit() {
  const box = $('request');
  const text = box.value.trim();
  if (!text) return;
  box.value = '';
  post('/api/task', {request: text});
}

async function capture() {
  const body = $('capture-body').value.trim();
  if (!body) return;
  const done = await post('/api/capture', {
    title: $('capture-title').value.trim(), body: body});
  if (done) {
    $('capture-body').value = '';
    $('capture-title').value = '';
    $('status').textContent = 'captured to the vault';
  }
}

// --- one delegated listener, no handlers in attributes -------------------

function nodeUnder(target) {
  const carrier = target.closest ? target.closest('[data-node]') : null;
  return carrier ? carrier.dataset.node : null;
}

document.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.id === 'send') return submit();
  if (target.id === 'capture') return capture();

  const node = nodeUnder(target);
  if (node) return selectNode(node);

  if (target.dataset && target.dataset.answer !== undefined) {
    post('/api/answer', {
      task_id: target.dataset.task,
      question_id: target.dataset.question,
      text: target.dataset.answer,
    });
  }
});

document.addEventListener('mouseover', (event) => {
  if (!(event.target instanceof Element)) return;
  const node = nodeUnder(event.target);
  if (node !== Sphere.hovered) { Sphere.hovered = node; draw(); }
});

document.addEventListener('keydown', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  if (event.key === 'Escape') {
    Sphere.selected = null; describeNode('supervisor'); draw(); return;
  }
  if (event.key !== 'Enter' && event.key !== ' ') return;

  if (target.dataset && target.dataset.node) {
    event.preventDefault();
    return selectNode(target.dataset.node);
  }
  if (event.key !== 'Enter') return;
  if (target.id === 'request') { event.preventDefault(); return submit(); }
  if (target.dataset && target.dataset.question && target.tagName === 'INPUT') {
    event.preventDefault();
    post('/api/answer', {
      task_id: target.dataset.task,
      question_id: target.dataset.question,
      text: target.value,
    });
  }
});

let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (STATE && STATE.graph) { renderSphere(STATE.graph); }
  }, 180);
});

document.addEventListener('DOMContentLoaded', () => {
  tick();
  setInterval(tick, 1000);
  render(BOOTSTRAP);
  setInterval(refresh, 4000);
});
"""

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — agent operations</title>
<style>{css}</style></head>
<body>
<div class="shell">

  <header class="top">
    <div class="brand">
      <h1>J.A.R.V.I.S.</h1>
      <p id="subheading"></p>
    </div>
    <div class="spacer"></div>
    <div class="readout">
      <div class="clock" id="clock">--:--:--</div>
      <div class="date" id="date"></div>
      <div class="pills" id="pills"></div>
    </div>
  </header>

  <nav class="nav">
    <a href="#operations">Operations</a>
    <a href="#fleet-panel">Fleet</a>
    <a href="#sessions-panel">Sessions</a>
    <a href="#telemetry">Telemetry</a>
    <a href="#diagnostics">Diagnostics</a>
    <a href="#capture-panel">Capture</a>
    <a href="/workspace">Plain console</a>
  </nav>

  <section class="panel wide" id="operations" style="--edge: var(--accent)">
    <h2>Operations sphere
      <span class="note">every edge is a call that exists in the code</span></h2>
    <div class="hero">

      <div class="orb-wrap">
        <div id="sphere"></div>
        <div class="legend">
          <span class="l-reviews"><i></i> supervisor reviews</span>
          <span class="l-delegates"><i></i> typed handoff</span>
          <span class="l-uses"><i></i> uses a system</span>
          <span>dashed ring = not connected yet</span>
        </div>
      </div>

      <div class="hero-side">
        <div id="node-detail" class="node-detail"></div>
        <div id="asks"></div>
        <div class="stream" id="stream"></div>
        <div class="composer">
          <input id="request" placeholder="Research Kestrel Systems…" autocomplete="off">
          <button id="send" type="button">Send</button>
        </div>
        <div class="hint" id="status"></div>
        <div class="hint">
          This console can create work. It has no control that approves any —
          every result goes through the codex.
        </div>
      </div>

    </div>
  </section>

  <div class="grid">

    <section class="panel wide" id="fleet-panel" style="--edge: var(--accent)">
      <h2>Agent fleet <span class="note">runs in this process — not the sessions below</span></h2>
      <div class="fleet" id="fleet"></div>
    </section>

    <section class="panel" id="diagnostics" style="--edge: var(--ok)">
      <h2>System diagnostics <span class="note">the guardrails, not the CPU</span></h2>
      <div class="stats" id="checks"></div>
    </section>

    <section class="panel" style="--edge: var(--purple)">
      <h2>Decisions <span class="note">what the supervisor made of it</span></h2>
      <div id="cards"></div>
    </section>

    <section class="panel wide" id="sessions-panel" style="--edge: var(--warn)">
      <h2>Live sessions
        <span class="note">Claude Code on this machine, from its own transcripts</span></h2>
      <div class="rows" id="sessions"></div>
    </section>

    <section class="panel wide" id="telemetry" style="--edge: var(--ok)">
      <h2>Activity <span class="note" id="analytics-note"></span></h2>
      <div class="stats" id="totals"></div>
      <div class="two" style="margin-top:16px">
        <div>
          <div class="minihead">Daily messages</div>
          <div class="heat" id="heat"></div>
        </div>
        <div>
          <div class="minihead">Hour of day</div>
          <div class="bars" id="hours"></div>
          <div class="axis"><span>00</span><span>06</span><span>12</span>
            <span>18</span><span>23</span></div>
          <div class="hint" id="peak"></div>
        </div>
      </div>
      <div class="split" style="margin-top:18px" id="models"></div>
    </section>

    <section class="panel wide" id="capture-panel" style="--edge: var(--purple)">
      <h2>Quick capture <span class="note">{capture_note}</span></h2>
      <input id="capture-title" placeholder="Title (optional)" autocomplete="off"
             style="margin-bottom:9px">
      <textarea id="capture-body" placeholder="A note for the vault…"></textarea>
      <div class="composer">
        <div class="spacer"></div>
        <button id="capture" type="button">Capture</button>
      </div>
    </section>

  </div>
</div>
<script>const BOOTSTRAP = {bootstrap};</script>
<script>{sphere_js}</script>
<script>{js}</script>
</body></html>
"""


def embed_json(payload: dict) -> str:
    """Serialise a payload for embedding inside a `<script>` block.

    `json.dumps` alone is not safe here, and the difference is a real hole
    rather than a theoretical one: it escapes quotes but leaves `<` and `>`
    alone, so a task containing the literal `</script>` ends the block early and
    everything after it is parsed as markup.

    Escaping the three characters as `\\uXXXX` is still valid JSON, parses to
    the same value, and cannot close a tag.
    """
    return (
        json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )


def render_dashboard(dashboard: Dashboard) -> str:
    """The whole dashboard as one self-contained HTML page."""
    # Escaped rather than trusted: the capture target is a filesystem path from
    # the environment, and it is the one value on this page that reaches the
    # markup instead of going through `textContent`.
    note = (
        "writes into " + html.escape(dashboard.capture_target)
        if dashboard.capture_target
        else "no vault configured — set OBSIDIAN_VAULT_PATH"
    )
    return _TEMPLATE.format(
        css=stylesheet(),
        sphere_js=SPHERE_JS,
        js=_JS_APP,
        capture_note=note,
        bootstrap=embed_json(dashboard.model_dump(mode="json")),
    )

"""The client.

Two properties this file exists to keep, and both are security properties
rather than style ones.

**Nothing is ever inserted as markup.** Every value that came from a model, a
transcript or a person is set with `textContent`. The page builds nodes; it
never concatenates a string into `innerHTML`, and a test asserts the word does
not appear.

**No handler is written into an attribute.** An earlier console generated
`onclick="answer('${id}', …)"`, which nests data inside a JavaScript string
inside an HTML attribute — two layers of quoting, and an apostrophe in the
wrong field escapes both. Here every control carries `data-` values and a
single delegated listener reads them off the element. There is no layer for a
quote to escape from.
"""

from __future__ import annotations

APP_JS = r"""
'use strict';

const $ = (id) => document.getElementById(id);
let STATE = null;
let busy = false;

const VIEWS = ['operations', 'fleet', 'activity', 'systems'];
const TITLES = {
  operations: ['Operations', 'The fleet, what it touches, and what it is doing now.'],
  fleet: ['Fleet', 'Eight agents, one supervisor over all of them.'],
  activity: ['Activity', ''],
  systems: ['Systems', 'Connections, guardrails and capture.'],
};
const CONNECTION = {
  'local': 'working locally — needs no account',
  'needs-credentials': 'implemented, waiting on one credential',
  'not-built': 'interface only, no implementation',
};

// ── building nodes, never markup ────────────────────────────────────

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

function figure(value, key, detail, tone) {
  const box = el('div', 'fig' + (tone ? ' ' + tone : ''));
  box.appendChild(el('div', 'v', value));
  box.appendChild(el('div', 'k', key));
  if (detail) box.appendChild(el('div', 'd', detail));
  return box;
}

// ── views ───────────────────────────────────────────────────────────

function currentView() {
  const wanted = (location.hash || '').replace('#', '');
  return VIEWS.includes(wanted) ? wanted : 'operations';
}

function showView(name) {
  VIEWS.forEach((view) => {
    $('view-' + view).classList.toggle('on', view === name);
  });
  document.querySelectorAll('#nav a').forEach((link) => {
    link.classList.toggle('on', link.dataset.view === name);
  });
  const [title, subtitle] = TITLES[name] || ['', ''];
  $('title').textContent = title;
  $('subtitle').textContent =
    name === 'activity' && STATE && STATE.analytics
      ? (STATE.analytics.real
          ? 'Read from this machine\'s own Claude Code transcripts.'
          : 'No history found — these figures are fixtures.')
      : subtitle;

  // The sphere sizes itself from its container, which is display:none until
  // its view is shown. Re-render on arrival or it lays out into zero width.
  if (name === 'operations' && STATE && STATE.graph) renderSphere(STATE.graph);
}

function clock() {
  $('clock').textContent = new Date().toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', hour12: false});
}

// ── panels ──────────────────────────────────────────────────────────

function renderChrome(state) {
  $('t-approved').textContent = state.approved;
  $('t-held').textContent = state.held;
  $('t-blocked').textContent = state.blocked;

  $('n-open').textContent = state.open_tasks ? state.open_tasks + ' open' : '';
  $('n-fleet').textContent = state.fleet.length;
  $('n-days').textContent = state.analytics ? state.analytics.window_days + 'd' : '';
  const pending = (state.graph ? state.graph.nodes : [])
    .filter((n) => n.connection && n.connection !== 'local').length;
  $('n-systems').textContent = pending ? pending + ' to wire' : 'all set';

  $('mode').textContent = state.mode === 'live'
    ? 'live · ' + state.model
    : 'mock · no network';
}

function renderInspector(id) {
  const node = Orb.byId.get(id);
  const box = $('inspect');
  if (!node || !box) return;

  const rows = [];
  const top = el('div', 'top');
  const swatch = el('span', 'swatch');
  swatch.style.background = node.colour;
  top.appendChild(swatch);
  top.appendChild(el('span', 'who', node.label));
  top.appendChild(el('span', 'kind', node.kind));
  rows.push(top);

  if (node.detail) rows.push(el('p', 'what', node.detail));

  if (node.connection) {
    const state = el('div', 'state tone-' + node.tone);
    state.appendChild(el('span', 'beat ' + node.tone));
    state.appendChild(el('span', null, CONNECTION[node.connection] || node.connection));
    rows.push(state);
    if (node.requires && node.requires.length) {
      rows.push(el('div', 'needs', 'Needs: ' + node.requires.join(', ')));
    }
  } else {
    const state = el('div', 'state tone-' + (node.tasks ? node.tone : 'dim'));
    state.appendChild(el('span', 'beat ' + (node.tasks ? node.tone : '')));
    state.appendChild(el('span', null,
      node.tasks ? node.tasks + ' task(s) this session' : 'idle this session'));
    rows.push(state);
  }

  const edges = Orb.links.filter((l) => l.source.id === id || l.target.id === id);
  if (edges.length) {
    const list = el('div', 'links');
    edges.forEach((link) => {
      const other = link.source.id === id ? link.target : link.source;
      const arrow = link.source.id === id ? '→' : '←';
      list.appendChild(el('div', null,
        arrow + '  ' + other.label + '  ·  ' + (link.label || link.kind)));
    });
    rows.push(list);
  }

  box.replaceChildren(...rows);
}

function selectNode(id) {
  Orb.selected = Orb.selected === id ? null : id;
  renderInspector(Orb.selected || 'supervisor');
  draw();
}

function renderStream(state) {
  if (!state.turns.length) {
    fill('stream', none('Nothing yet. Pick a node, or type a task.'));
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

function renderCalls(state) {
  fill('calls', state.cards.length ? state.cards.map((card) => {
    const box = el('div', 'call ' + card.tone);
    box.appendChild(el('div', 'who', card.agent));
    box.appendChild(el('div', 'what', card.subject));
    (card.reasons || []).forEach((r) => box.appendChild(el('div', 'why', r)));
    return box;
  }) : none('No decisions yet.'));
}

function renderFleet(state) {
  fill('fleet', state.fleet.map((member) => {
    const row = el('div', 'crew');
    row.style.setProperty('--c', member.colour);
    row.dataset.node = member.name;
    row.tabIndex = 0;

    row.appendChild(el('div', 'badge', member.initials));

    const naming = el('div');
    naming.appendChild(el('div', 'who', member.title));
    naming.appendChild(el('div', 'slug',
      member.name + (member.reachable ? ' · takes free text' : '')));
    row.appendChild(naming);

    row.appendChild(el('div', 'what', member.blurb));

    const state2 = el('div', 'state');
    state2.appendChild(el('span', 'beat ' + (member.tasks ? member.tone : '')));
    state2.appendChild(el('span', null,
      member.tasks ? member.tasks + ' · ' + member.last : 'idle'));
    row.appendChild(state2);
    return row;
  }));
}

function renderSystems(state) {
  const nodes = (state.graph ? state.graph.nodes : [])
    .filter((node) => node.kind === 'integration');

  fill('systems', nodes.map((node) => {
    const row = el('div', 'system');
    const beat = el('span', 'beat ' + node.tone);
    row.appendChild(beat);

    const naming = el('div');
    naming.appendChild(el('div', 'who', node.label));
    row.appendChild(naming);

    row.appendChild(el('div', 'what', node.detail));

    const right = el('div');
    right.appendChild(el('div', 'state tone-' + node.tone,
      CONNECTION[node.connection] || node.connection));
    if (node.requires && node.requires.length) {
      right.appendChild(el('div', 'needs', node.requires.join(', ')));
    }
    row.appendChild(right);
    return row;
  }));
}

function renderActivity(state) {
  const a = state.analytics;
  if (!a) return;

  $('activity-note').textContent = a.real
    ? 'The one real data source here. Everything else in this repository runs '
      + 'on fixtures; this reads transcripts already on the disk — no key, no '
      + 'network, no account.'
    : 'No Claude Code history was found on this machine, so these figures are '
      + 'fixtures. They are labelled rather than quietly shown as real.';

  fill('figures', [
    figure(num(a.sessions), 'sessions', 'last ' + a.window_days + ' days'),
    figure(num(a.messages), 'messages', 'turns, deduplicated'),
    figure(num(a.tool_calls), 'tool calls', 'blocks, not turns'),
    figure(num(a.tokens), 'tokens', 'cache reads included'),
    figure(money(a.cost_usd), 'spend', 'list price, cache-aware'),
    figure(money(a.cost_per_session), 'per session', 'mean over the window'),
  ]);

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
    cell.style.opacity = day.level ? String(0.16 + day.level * 0.84) : '0.05';
    cell.title = day.day + ' — ' + day.messages + ' messages, '
      + day.sessions + ' session(s)';
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
    top.appendChild(el('b', null, share.family));
    top.appendChild(el('span', null, share.percent + '%  ·  ' + money(share.cost_usd)));
    box.appendChild(top);
    const track = el('div', 'track');
    const bar = el('div', 'fill');
    bar.style.width = Math.max(2, share.percent) + '%';
    track.appendChild(bar);
    box.appendChild(track);
    return box;
  }) : none('nothing to split'));

  fill('sessions', state.sessions.length ? state.sessions.map((session) => {
    const row = el('div', 'row-line');
    row.appendChild(el('span', 'beat ' + session.tone));
    const middle = el('div');
    middle.appendChild(el('div', null, session.project + ' — ' + session.doing));
    middle.appendChild(el('div', 'sub',
      session.session_id + ' · ' + (session.model || 'model unknown')));
    row.appendChild(middle);
    row.appendChild(el('span', 'age', session.age));
    return row;
  }) : none('No Claude Code session is active on this machine.'));
}

function renderChecks(state) {
  fill('checks', state.checks.map((check) =>
    figure(check.value, check.label, check.detail, check.tone)));
  // The vault path is joined by the server, not concatenated here — a
  // client that appends its own separator produces C:\a\b/Captures.
  $('capture-note').textContent = state.capture_target
    ? 'Writes into the Captures folder of ' + state.capture_target
    : 'No vault configured. Set OBSIDIAN_VAULT_PATH to enable this.';
}

function render(state) {
  STATE = state;
  renderChrome(state);
  renderQuestions(state);
  renderStream(state);
  renderCalls(state);
  renderFleet(state);
  renderSystems(state);
  renderActivity(state);
  renderChecks(state);

  if (state.graph) {
    const view = currentView();
    if (view === 'operations') renderSphere(state.graph);
    else buildScene(state.graph);
    renderInspector(Orb.selected || 'supervisor');
  }
}

// ── talking to the server ───────────────────────────────────────────

function working(on, message) {
  busy = on;
  $('status').textContent = message || '';
  $('send').disabled = on;
  $('capture').disabled = on;
  if (on) nudge(0.5);
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

// ── one delegated listener, no handlers in attributes ───────────────

function nodeUnder(target) {
  const carrier = target.closest ? target.closest('[data-node]') : null;
  return carrier ? carrier.dataset.node : null;
}

function focusNode(id) {
  selectNode(id);
  if (currentView() !== 'operations') location.hash = '#operations';
}

document.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.id === 'send') return submit();
  if (target.id === 'capture') return capture();

  const node = nodeUnder(target);
  if (node) return focusNode(node);

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
  if (node !== Orb.hovered) { Orb.hovered = node; draw(); }
});

document.addEventListener('keydown', (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;

  if (event.key === 'Escape') {
    Orb.selected = null;
    renderInspector('supervisor');
    draw();
    return;
  }
  if (event.key !== 'Enter' && event.key !== ' ') return;

  if (target.dataset && target.dataset.node) {
    event.preventDefault();
    return focusNode(target.dataset.node);
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

window.addEventListener('hashchange', () => showView(currentView()));

let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (STATE && STATE.graph && currentView() === 'operations') renderSphere(STATE.graph);
  }, 180);
});

document.addEventListener('DOMContentLoaded', () => {
  clock();
  setInterval(clock, 10000);
  render(BOOTSTRAP);
  showView(currentView());
  setInterval(refresh, 4000);
});
"""

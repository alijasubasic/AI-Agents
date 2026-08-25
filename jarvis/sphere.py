"""The operations sphere: the graph, drawn.

An Obsidian-style force-directed graph inside a glowing orb, and the centre of
the whole dashboard. Everything else on the page is a readout; this is the
thing you look at to understand the system.

**Why a force simulation rather than fixed coordinates.** Fixed positions are
easier and they lie: they make the picture a drawing rather than a consequence.
Here position falls out of the edges — an agent that touches three outside
systems is pulled outward by three springs and ends up nearer the rim, and an
isolated agent drifts to a quiet corner on its own. Add a delegation to the
model and the layout rearranges itself without anyone repositioning a circle.

**Why the layout is seeded and deterministic.** `Math.random` would give a
different picture on every reload, which makes the graph impossible to learn.
Nodes start on their ring at an angle derived from their id, so the same fleet
always settles into the same shape and a screenshot stays true. The simulation
then relaxes from there.

Three forces, and one constraint:

    repulsion   every pair pushes apart, so labels do not stack
    springs     linked nodes pull together, at a length set by the link kind
    radial      each node is drawn toward the ring its kind belongs to
    the rim     nothing may leave the sphere

The rim constraint is what makes it an orb rather than a cloud. Without it the
graph spreads until it fills whatever box it is given, and the shape stops
meaning anything.
"""

from __future__ import annotations

#: How many simulation steps run synchronously before the first paint.
#: See the note in `renderSphere` — the layout must not depend on rAF firing.
SETTLE_STEPS = 240

#: Radius in pixels by node kind, in the sphere's own coordinate space.
NODE_RADIUS = {"supervisor": 27, "agent": 17, "integration": 12, "surface": 15}

#: Ring radius as a fraction of the sphere's radius.
RING_FRACTION = {0: 0.0, 1: 0.46, 2: 0.84}

SPHERE_JS = r"""
// --- The operations sphere ----------------------------------------------
// A force-directed graph in an orb. See jarvis/sphere.py for why each force
// is here; this is the arithmetic, the reasoning is in the docstring.

const SVG_NS = 'http://www.w3.org/2000/svg';

const RADIUS = {supervisor: 27, agent: 17, integration: 12, surface: 15};
const RING   = {0: 0.0, 1: 0.46, 2: 0.84};
const SURFACE_RING = 0.24;
const SETTLE_STEPS = 240;

// Spring rest length per link kind, as a fraction of the sphere radius. A
// review edge is short because the supervisor sits at the centre; a "uses"
// edge is long because integrations belong on the rim.
const REST = {reviews: 0.42, delegates: 0.36, uses: 0.40, operates: 0.30};

const Sphere = {
  nodes: [], links: [], byId: new Map(),
  size: 0, centre: 0, radius: 0,
  hovered: null, selected: null, frame: null, alpha: 0,
  svg: null, layers: {},
};

// A stable hash, so a node always starts at the same angle. Math.random would
// redraw the fleet differently on every reload and make it unlearnable.
function seedAngle(id) {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) % 100000;
  return (hash / 100000) * Math.PI * 2;
}

function buildScene(graph) {
  const previous = new Map(Sphere.nodes.map((n) => [n.id, n]));
  Sphere.nodes = graph.nodes.map((node) => {
    const kept = previous.get(node.id);
    const ring = node.kind === 'surface' ? SURFACE_RING
               : (RING[node.ring] !== undefined ? RING[node.ring] : 0.6);
    const angle = seedAngle(node.id);
    return Object.assign({}, node, {
      r: RADIUS[node.kind] || 14,
      ring: ring,
      // Keep positions across a refresh so a poll does not make it jump.
      x: kept ? kept.x : Math.cos(angle) * ring,
      y: kept ? kept.y : Math.sin(angle) * ring,
      vx: 0, vy: 0,
    });
  });
  Sphere.byId = new Map(Sphere.nodes.map((n) => [n.id, n]));
  Sphere.links = graph.links
    .map((link) => ({
      kind: link.kind,
      label: link.label,
      source: Sphere.byId.get(link.source),
      target: Sphere.byId.get(link.target),
    }))
    .filter((link) => link.source && link.target);
}

// One step of the simulation. Positions are kept in unit space (-1..1) so the
// forces do not have to be retuned when the sphere is resized.
function step() {
  const nodes = Sphere.nodes;

  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    // Radial: toward the ring this kind belongs on.
    const dist = Math.hypot(a.x, a.y) || 0.0001;
    const pull = (a.ring - dist) * 0.045;
    a.vx += (a.x / dist) * pull;
    a.vy += (a.y / dist) * pull;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 0.0001) { dx = 0.001; dy = 0.001; d2 = 0.000002; }
      const force = 0.0016 / d2;
      const d = Math.sqrt(d2);
      a.vx -= (dx / d) * force; a.vy -= (dy / d) * force;
      b.vx += (dx / d) * force; b.vy += (dy / d) * force;
    }
  }

  for (const link of Sphere.links) {
    const rest = REST[link.kind] || 0.4;
    const dx = link.target.x - link.source.x;
    const dy = link.target.y - link.source.y;
    const d = Math.hypot(dx, dy) || 0.0001;
    const force = (d - rest) * 0.035;
    link.source.vx += (dx / d) * force; link.source.vy += (dy / d) * force;
    link.target.vx -= (dx / d) * force; link.target.vy -= (dy / d) * force;
  }

  for (const node of nodes) {
    node.vx *= 0.82; node.vy *= 0.82;
    node.x += node.vx; node.y += node.vy;
    // The rim. Without this the graph spreads to fill whatever box it is
    // given and the shape stops meaning anything.
    const limit = 0.94 - node.r / (Sphere.radius || 300);
    const dist = Math.hypot(node.x, node.y);
    if (dist > limit) { node.x = (node.x / dist) * limit; node.y = (node.y / dist) * limit; }
  }
}

function toScreen(node) {
  return [Sphere.centre + node.x * Sphere.radius, Sphere.centre + node.y * Sphere.radius];
}

// Which nodes are lit: the hovered or selected one and everything it touches.
function focusSet() {
  const focus = Sphere.hovered || Sphere.selected;
  if (!focus) return null;
  const set = new Set([focus]);
  for (const link of Sphere.links) {
    if (link.source.id === focus) set.add(link.target.id);
    if (link.target.id === focus) set.add(link.source.id);
  }
  return set;
}

function draw() {
  const lit = focusSet();
  const focus = Sphere.hovered || Sphere.selected;

  for (const item of Sphere.layers.links) {
    const [x1, y1] = toScreen(item.link.source);
    const [x2, y2] = toScreen(item.link.target);
    // A gentle arc rather than a straight line: two edges between the same
    // pair stay distinguishable, and the whole thing reads as an orb.
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const bow = 0.12;
    const cx = mx + (my - Sphere.centre) * bow;
    const cy = my - (mx - Sphere.centre) * bow;
    item.el.setAttribute('d', `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`);
    const touched = !focus ||
      item.link.source.id === focus || item.link.target.id === focus;
    item.el.style.opacity = touched ? (focus ? '0.95' : '0.34') : '0.05';
  }

  for (const item of Sphere.layers.nodes) {
    const [x, y] = toScreen(item.node);
    item.group.setAttribute('transform', `translate(${x},${y})`);
    const on = !lit || lit.has(item.node.id);
    item.group.style.opacity = on ? '1' : '0.16';
    item.group.classList.toggle('is-focus', item.node.id === focus);
  }
}

function tickSim() {
  if (Sphere.alpha > 0.001) {
    for (let i = 0; i < 3; i++) step();
    Sphere.alpha *= 0.985;
    draw();
    Sphere.frame = requestAnimationFrame(tickSim);
  } else {
    Sphere.frame = null;
    draw();
  }
}

function nudge(alpha) {
  Sphere.alpha = Math.max(Sphere.alpha, alpha === undefined ? 1 : alpha);
  if (!Sphere.frame) Sphere.frame = requestAnimationFrame(tickSim);
}

function renderSphere(graph) {
  const host = $('sphere');
  if (!host) return;
  buildScene(graph);

  const size = Math.max(320, Math.min(host.clientWidth || 560, 720));
  Sphere.size = size; Sphere.centre = size / 2; Sphere.radius = size / 2;

  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  svg.setAttribute('class', 'orb');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label',
    graph.nodes.length + ' nodes and ' + graph.links.length + ' connections');

  const rim = document.createElementNS(SVG_NS, 'circle');
  rim.setAttribute('cx', Sphere.centre); rim.setAttribute('cy', Sphere.centre);
  rim.setAttribute('r', Sphere.radius - 2);
  rim.setAttribute('class', 'orb-rim');
  svg.appendChild(rim);

  for (const fraction of [0.46, 0.84]) {
    const ring = document.createElementNS(SVG_NS, 'circle');
    ring.setAttribute('cx', Sphere.centre); ring.setAttribute('cy', Sphere.centre);
    ring.setAttribute('r', Sphere.radius * fraction);
    ring.setAttribute('class', 'orb-ring');
    svg.appendChild(ring);
  }

  const linkLayer = document.createElementNS(SVG_NS, 'g');
  const nodeLayer = document.createElementNS(SVG_NS, 'g');
  svg.appendChild(linkLayer); svg.appendChild(nodeLayer);

  Sphere.layers.links = Sphere.links.map((link) => {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('class', 'edge edge-' + link.kind);
    path.setAttribute('fill', 'none');
    linkLayer.appendChild(path);
    return {link: link, el: path};
  });

  Sphere.layers.nodes = Sphere.nodes.map((node) => {
    const group = document.createElementNS(SVG_NS, 'g');
    group.setAttribute('class', 'orb-node kind-' + node.kind + ' tone-' + node.tone);
    group.setAttribute('tabindex', '0');
    group.dataset.node = node.id;

    if (node.tasks > 0 || node.kind === 'supervisor') {
      const halo = document.createElementNS(SVG_NS, 'circle');
      halo.setAttribute('r', node.r + 8);
      halo.setAttribute('class', 'halo');
      halo.setAttribute('fill', node.colour);
      group.appendChild(halo);
    }

    const disc = document.createElementNS(SVG_NS, 'circle');
    disc.setAttribute('r', node.r);
    disc.setAttribute('class', 'disc');
    disc.setAttribute('fill', node.colour);
    group.appendChild(disc);

    if (node.connection && node.connection !== 'local') {
      const dashed = document.createElementNS(SVG_NS, 'circle');
      dashed.setAttribute('r', node.r + 4);
      dashed.setAttribute('class', 'pending');
      dashed.setAttribute('stroke', node.colour);
      group.appendChild(dashed);
    }

    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('y', node.r + 14);
    text.setAttribute('class', 'orb-label');
    text.textContent = node.label;
    group.appendChild(text);

    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = node.label + (node.detail ? ' — ' + node.detail : '');
    group.appendChild(title);

    nodeLayer.appendChild(group);
    return {node: node, group: group};
  });

  host.replaceChildren(svg);
  Sphere.svg = svg;

  // Settle synchronously, then draw. requestAnimationFrame does not fire in a
  // background tab or a pane the browser is not compositing, and a layout that
  // waits for it shows every node stacked at the origin — which is exactly
  // what this did until a headless check caught it. The animation is a
  // nicety; the picture is not allowed to depend on it.
  settle(SETTLE_STEPS);
  draw();
  nudge(0.35);
}

function settle(iterations) {
  for (let i = 0; i < iterations; i++) step();
}

function describeNode(id) {
  const node = Sphere.byId.get(id);
  const box = $('node-detail');
  if (!node || !box) return;

  const rows = [];
  const head = el('div', 'nd-head');
  const dot = el('span', 'nd-dot');
  dot.style.background = node.colour;
  head.appendChild(dot);
  head.appendChild(el('span', 'nd-name', node.label));
  head.appendChild(el('span', 'nd-kind', node.kind));
  rows.push(head);

  if (node.detail) rows.push(el('p', 'nd-detail', node.detail));

  if (node.connection) {
    const status = el('div', 'nd-status tone-' + node.tone);
    status.appendChild(el('span', 'beat ' + node.tone));
    status.appendChild(el('span', null, CONNECTION_LABEL[node.connection] || node.connection));
    rows.push(status);
    if (node.requires && node.requires.length) {
      rows.push(el('div', 'nd-sub', 'Needs: ' + node.requires.join(', ')));
    }
  }

  if (node.kind === 'agent' || node.kind === 'supervisor') {
    rows.push(el('div', 'nd-sub',
      node.tasks ? node.tasks + ' task(s) this session' : 'no tasks this session'));
  }

  const edges = Sphere.links.filter((l) => l.source.id === id || l.target.id === id);
  if (edges.length) {
    const list = el('div', 'nd-edges');
    edges.forEach((link) => {
      const other = link.source.id === id ? link.target : link.source;
      const arrow = link.source.id === id ? '→' : '←';
      list.appendChild(el('div', 'nd-edge',
        arrow + ' ' + other.label + '  (' + (link.label || link.kind) + ')'));
    });
    rows.push(list);
  }

  box.replaceChildren(...rows);
}

const CONNECTION_LABEL = {
  'local': 'working locally — no account needed',
  'needs-credentials': 'implemented, waiting on credentials',
  'not-built': 'interface only, no implementation',
};

function selectNode(id) {
  Sphere.selected = Sphere.selected === id ? null : id;
  describeNode(Sphere.selected || 'supervisor');
  draw();
}
"""

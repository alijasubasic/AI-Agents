"""The operations sphere: the graph, drawn.

A force-directed graph of the whole system inside an orb, and the centre of the
dashboard. Everything else on the page is a readout; this is the thing you look
at to understand what is running and what it touches.

**Position is derived, not drawn.** Fixed coordinates are easier and they lie —
they make the picture a drawing rather than a consequence. Here an agent that
touches three outside systems is pulled outward by three springs and ends up
nearer the rim on its own, and adding a delegation to the model rearranges the
layout without anyone repositioning a circle.

**The layout is seeded.** `Math.random` would give a different picture on every
reload, which makes the graph impossible to learn. Nodes start on their ring at
an angle derived from their id, so the same fleet always settles into the same
shape and a screenshot stays true.

**The layout does not depend on animation.** `requestAnimationFrame` does not
fire in a background tab or a pane the browser is not compositing. An earlier
version relaxed the graph inside the frame callback, so in those cases every
node sat stacked at the origin — a headless check caught it. The simulation now
runs to rest synchronously before the first paint; the animation on top is a
nicety.

Three forces and one constraint:

    repulsion   every pair pushes apart, so labels never stack
    springs     linked nodes pull together, at a length set by the link kind
    radial      each node is drawn toward the ring its kind belongs to
    the rim     nothing may leave the sphere

The rim is what makes it an orb rather than a cloud. Without it the graph
spreads to fill whatever box it is given and the shape stops meaning anything.
"""

from __future__ import annotations

#: Steps run synchronously before the first paint. See the module docstring.
SETTLE_STEPS = 260

#: Node radius in the sphere's own coordinate space, by kind.
NODE_RADIUS = {"supervisor": 25, "agent": 15, "integration": 10, "surface": 13}

#: Ring radius as a fraction of the sphere's radius.
RING_FRACTION = {0: 0.0, 1: 0.45, 2: 0.83}

SPHERE_JS = r"""
// The operations sphere. Physics here, reasoning in jarvis/ui/sphere.py.
'use strict';

const SVG_NS = 'http://www.w3.org/2000/svg';
const R_BY_KIND = {supervisor: 25, agent: 15, integration: 10, surface: 13};
const RING = {0: 0.0, 1: 0.45, 2: 0.83};
const SURFACE_RING = 0.23;
const SETTLE_STEPS = 260;

// Spring rest length per link kind, as a fraction of the sphere radius. A
// review edge is short because the supervisor sits at the centre; a "uses"
// edge is long because outside systems belong on the rim.
const REST = {reviews: 0.42, delegates: 0.34, uses: 0.40, operates: 0.28};

const Orb = {
  nodes: [], links: [], byId: new Map(),
  centre: 0, radius: 0, alpha: 0, frame: null,
  hovered: null, selected: null, layers: {nodes: [], links: []},
};

// A stable hash, so a node always starts at the same angle.
function seedAngle(id) {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) % 100000;
  return (hash / 100000) * Math.PI * 2;
}

function buildScene(graph) {
  const previous = new Map(Orb.nodes.map((n) => [n.id, n]));
  Orb.nodes = graph.nodes.map((node) => {
    const kept = previous.get(node.id);
    const ring = node.kind === 'surface'
      ? SURFACE_RING
      : (RING[node.ring] !== undefined ? RING[node.ring] : 0.6);
    const angle = seedAngle(node.id);
    return Object.assign({}, node, {
      r: R_BY_KIND[node.kind] || 13,
      ring: ring,
      // Positions survive a poll, so a refresh does not make the graph jump.
      x: kept ? kept.x : Math.cos(angle) * ring,
      y: kept ? kept.y : Math.sin(angle) * ring,
      vx: 0, vy: 0,
    });
  });
  Orb.byId = new Map(Orb.nodes.map((n) => [n.id, n]));
  Orb.links = graph.links
    .map((link) => ({
      kind: link.kind, label: link.label,
      source: Orb.byId.get(link.source), target: Orb.byId.get(link.target),
    }))
    .filter((link) => link.source && link.target);
}

// One step. Positions live in unit space (-1..1) so the forces never need
// retuning when the sphere is resized.
function step() {
  const nodes = Orb.nodes;

  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    const dist = Math.hypot(a.x, a.y) || 0.0001;
    const pull = (a.ring - dist) * 0.045;
    a.vx += (a.x / dist) * pull;
    a.vy += (a.y / dist) * pull;

    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 0.0001) { dx = 0.001; dy = 0.001; d2 = 0.000002; }
      const d = Math.sqrt(d2);
      const force = 0.0016 / d2;
      a.vx -= (dx / d) * force; a.vy -= (dy / d) * force;
      b.vx += (dx / d) * force; b.vy += (dy / d) * force;
    }
  }

  for (const link of Orb.links) {
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
    const limit = 0.93 - node.r / (Orb.radius || 300);
    const dist = Math.hypot(node.x, node.y);
    if (dist > limit) { node.x = (node.x / dist) * limit; node.y = (node.y / dist) * limit; }
  }
}

function settle(iterations) { for (let i = 0; i < iterations; i++) step(); }

function toScreen(node) {
  return [Orb.centre + node.x * Orb.radius, Orb.centre + node.y * Orb.radius];
}

// The lit set: the focused node and everything it touches.
function focusSet() {
  const focus = Orb.hovered || Orb.selected;
  if (!focus) return null;
  const set = new Set([focus]);
  for (const link of Orb.links) {
    if (link.source.id === focus) set.add(link.target.id);
    if (link.target.id === focus) set.add(link.source.id);
  }
  return set;
}

function draw() {
  const lit = focusSet();
  const focus = Orb.hovered || Orb.selected;

  for (const item of Orb.layers.links) {
    const [x1, y1] = toScreen(item.link.source);
    const [x2, y2] = toScreen(item.link.target);
    // A gentle arc: two edges between the same pair stay distinguishable and
    // the whole thing reads as a sphere rather than a wire frame.
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const cx = mx + (my - Orb.centre) * 0.1;
    const cy = my - (mx - Orb.centre) * 0.1;
    item.el.setAttribute('d', 'M' + x1 + ',' + y1 + ' Q' + cx + ',' + cy + ' ' + x2 + ',' + y2);
    const touched = !focus || item.link.source.id === focus || item.link.target.id === focus;
    item.el.style.opacity = touched ? (focus ? '0.9' : '0.42') : '0.05';
  }

  for (const item of Orb.layers.nodes) {
    const [x, y] = toScreen(item.node);
    item.group.setAttribute('transform', 'translate(' + x + ',' + y + ')');
    const on = !lit || lit.has(item.node.id);
    item.group.style.opacity = on ? '1' : '0.14';
    item.group.classList.toggle('is-focus', item.node.id === focus);
  }
}

function tickSim() {
  if (Orb.alpha > 0.002) {
    for (let i = 0; i < 3; i++) step();
    Orb.alpha *= 0.98;
    draw();
    Orb.frame = requestAnimationFrame(tickSim);
  } else {
    Orb.frame = null;
    draw();
  }
}

function nudge(alpha) {
  Orb.alpha = Math.max(Orb.alpha, alpha === undefined ? 1 : alpha);
  if (!Orb.frame) Orb.frame = requestAnimationFrame(tickSim);
}

function renderSphere(graph) {
  const host = document.getElementById('sphere');
  if (!host) return;
  buildScene(graph);

  const size = Math.max(300, Math.min(host.clientWidth || 560, 660));
  Orb.centre = size / 2;
  Orb.radius = size / 2;

  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
  svg.setAttribute('class', 'orb');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label',
    graph.nodes.length + ' components and ' + graph.links.length + ' connections');

  const rim = document.createElementNS(SVG_NS, 'circle');
  rim.setAttribute('cx', Orb.centre); rim.setAttribute('cy', Orb.centre);
  rim.setAttribute('r', Orb.radius - 2);
  rim.setAttribute('class', 'orb-rim');
  svg.appendChild(rim);

  for (const fraction of [0.45, 0.83]) {
    const ring = document.createElementNS(SVG_NS, 'circle');
    ring.setAttribute('cx', Orb.centre); ring.setAttribute('cy', Orb.centre);
    ring.setAttribute('r', Orb.radius * fraction);
    ring.setAttribute('class', 'orb-ring');
    svg.appendChild(ring);
  }

  const linkLayer = document.createElementNS(SVG_NS, 'g');
  const nodeLayer = document.createElementNS(SVG_NS, 'g');
  svg.appendChild(linkLayer);
  svg.appendChild(nodeLayer);

  Orb.layers.links = Orb.links.map((link) => {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('class', 'edge edge-' + link.kind);
    linkLayer.appendChild(path);
    return {link: link, el: path};
  });

  Orb.layers.nodes = Orb.nodes.map((node) => {
    const group = document.createElementNS(SVG_NS, 'g');
    group.setAttribute('class', 'orb-node kind-' + node.kind);
    group.setAttribute('tabindex', '0');
    group.dataset.node = node.id;

    if (node.tasks > 0 || node.kind === 'supervisor') {
      const halo = document.createElementNS(SVG_NS, 'circle');
      halo.setAttribute('r', node.r + 7);
      halo.setAttribute('class', 'halo');
      halo.setAttribute('fill', node.colour);
      group.appendChild(halo);
    }

    const disc = document.createElementNS(SVG_NS, 'circle');
    disc.setAttribute('r', node.r);
    disc.setAttribute('class', 'disc');
    disc.setAttribute('fill', node.colour);
    group.appendChild(disc);

    // A dashed outline marks an outside system that is not connected yet.
    if (node.connection && node.connection !== 'local') {
      const pending = document.createElementNS(SVG_NS, 'circle');
      pending.setAttribute('r', node.r + 4);
      pending.setAttribute('class', 'pending');
      pending.setAttribute('stroke', node.colour);
      group.appendChild(pending);
    }

    const label = document.createElementNS(SVG_NS, 'text');
    label.setAttribute('y', node.r + 14);
    label.setAttribute('class', 'orb-label');
    label.textContent = node.label;
    group.appendChild(label);

    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = node.label + (node.detail ? ' — ' + node.detail : '');
    group.appendChild(title);

    nodeLayer.appendChild(group);
    return {node: node, group: group};
  });

  host.replaceChildren(svg);

  // Settle first, paint second. See the note in jarvis/ui/sphere.py.
  settle(SETTLE_STEPS);
  draw();
  nudge(0.3);
}
"""

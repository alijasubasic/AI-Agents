"""The stylesheet.

Written against three rules, and the previous version broke all three.

**One border weight, used rarely.** Every panel had a border, a rounded corner
and a gradient hairline across the top. Fourteen boxes each shouting for
attention is a page with no focus. Separation here comes from space first,
a hairline second, and a surface only where something is genuinely raised.

**Colour means state.** Nothing is accent-coloured for decoration.

**Numbers are the content.** Figures are large, light and tabular; their labels
are small and quiet. The earlier version had labels and values at nearly the
same weight, so a panel of six statistics read as twelve things.

No build step, no CDN — the server's Content-Security-Policy forbids external
origins and a test asserts the page contains no `https://`.
"""

from __future__ import annotations

from jarvis.ui.theme import css_variables

_CSS = """
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Inter, sans-serif;
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, p, figure { margin: 0; }
a { color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }

/* ── shell ─────────────────────────────────────────────────────────── */
.app { display: grid; grid-template-columns: var(--rail) minmax(0, 1fr);
       min-height: 100vh; }

.rail { position: sticky; top: 0; align-self: start; height: 100vh;
        display: flex; flex-direction: column; gap: 6px;
        padding: 26px 16px 20px; border-right: 1px solid var(--line); }
.mark { display: flex; align-items: center; gap: 10px; padding: 0 10px 22px; }
.mark .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
             box-shadow: 0 0 12px var(--accent); flex: none; }
.mark .name { font-size: 13px; font-weight: 600; letter-spacing: .26em; }

.rail nav { display: flex; flex-direction: column; gap: 2px; }
.rail nav a { display: flex; align-items: center; justify-content: space-between;
              gap: 8px; padding: 9px 11px; border-radius: var(--radius-sm);
              font-size: 13.5px; color: var(--muted); text-decoration: none;
              transition: background .12s, color .12s; }
.rail nav a:hover { background: var(--surface); color: var(--text); }
.rail nav a.on { background: var(--accent-soft); color: var(--accent); }
.rail nav a .count { font-size: 11px; color: var(--dim);
                     font-variant-numeric: tabular-nums; }
.rail nav a.on .count { color: var(--accent); }

.rail .foot { margin-top: auto; padding: 0 11px; display: grid; gap: 7px; }
.rail .foot .clock { font-size: 19px; font-weight: 300; letter-spacing: .04em;
                     font-variant-numeric: tabular-nums; color: var(--muted); }
.rail .foot .meta { font-size: 11px; color: var(--dim); line-height: 1.5; }

/* ── main ──────────────────────────────────────────────────────────── */
.main { min-width: 0; padding: 26px 34px 72px; max-width: 1320px; }
.head { display: flex; align-items: flex-end; gap: 20px; flex-wrap: wrap;
        padding-bottom: 20px; margin-bottom: 26px;
        border-bottom: 1px solid var(--line); }
.head h1 { font-size: 21px; font-weight: 600; letter-spacing: -.01em; }
.head p { margin-top: 5px; font-size: 12.5px; color: var(--muted); }
.grow { flex: 1 1 auto; }

.tally { display: flex; gap: 26px; }
.tally div { text-align: right; }
.tally .v { font-size: 20px; font-weight: 300; font-variant-numeric: tabular-nums; }
.tally .k { font-size: 10px; letter-spacing: .13em; text-transform: uppercase;
            color: var(--dim); margin-top: 2px; }
.tally .ok .v { color: var(--ok); }
.tally .hold .v { color: var(--hold); }
.tally .block .v { color: var(--block); }

.view { display: none; }
.view.on { display: block; animation: rise .28s ease-out both; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } }

h2.section { font-size: 10.5px; font-weight: 600; letter-spacing: .18em;
             text-transform: uppercase; color: var(--dim);
             margin: 34px 0 14px; }
h2.section:first-child { margin-top: 0; }
.note { font-size: 12.5px; color: var(--muted); margin-bottom: 16px;
        max-width: 62ch; line-height: 1.6; }
.empty { color: var(--dim); font-size: 13px; padding: 14px 0; }

/* ── operations: the sphere ────────────────────────────────────────── */
.ops { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 34px;
       align-items: start; }
.orb-stage { display: grid; place-items: center; }
#sphere { width: 100%; display: grid; place-items: center; }
.orb { width: 100%; height: auto; max-width: 660px; overflow: visible; }

.orb-rim { fill: rgba(77, 212, 255, 0.014); stroke: var(--accent-line);
           stroke-width: 1; stroke-dasharray: 2 10;
           transform-origin: center; animation: turn 140s linear infinite; }
.orb-ring { fill: none; stroke: var(--line); stroke-width: 1; }
@keyframes turn { to { transform: rotate(360deg); } }

.edge { stroke-width: 1; fill: none; transition: opacity .2s; }
.edge-reviews { stroke: var(--dim); stroke-dasharray: 2 6; }
.edge-delegates { stroke: var(--accent); stroke-width: 1.4; }
.edge-uses { stroke: var(--faint); }
.edge-operates { stroke: var(--muted); stroke-width: 1.3; }

.orb-node { cursor: pointer; transition: opacity .2s; }
.orb-node .disc { stroke: var(--bg); stroke-width: 2.5; }
.orb-node .halo { opacity: .13; }
.orb-node .pending { fill: none; stroke-width: 1; stroke-dasharray: 1.5 3.5;
                     opacity: .55; }
.orb-node .orb-label { fill: var(--muted); font-size: 10px; text-anchor: middle;
                       pointer-events: none; paint-order: stroke;
                       stroke: var(--bg); stroke-width: 3.5px; }
.orb-node.kind-supervisor .orb-label { fill: var(--text); font-size: 11.5px;
                                       font-weight: 600; letter-spacing: .1em; }
.orb-node:hover .disc, .orb-node.is-focus .disc { stroke: var(--accent); }
.orb-node.is-focus .orb-label { fill: var(--text); }
.orb-node:focus-visible .disc { stroke: var(--accent); stroke-width: 3.5; }

.key { display: flex; gap: 20px; flex-wrap: wrap; justify-content: center;
       margin-top: 10px; font-size: 11px; color: var(--dim); }
.key span { display: inline-flex; align-items: center; gap: 6px; }
.key i { width: 15px; border-top: 1.4px solid currentColor; }
.key .k-del { color: var(--accent); }
.key .k-rev { color: var(--dim); }

/* ── inspector ─────────────────────────────────────────────────────── */
.side { display: grid; gap: 22px; }
.inspect { border: 1px solid var(--line); border-radius: var(--radius);
           background: var(--surface); padding: 17px 18px; }
.inspect .top { display: flex; align-items: center; gap: 9px; margin-bottom: 4px; }
.inspect .swatch { width: 9px; height: 9px; border-radius: 50%; flex: none; }
.inspect .who { font-size: 15.5px; font-weight: 600; }
.inspect .kind { font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
                 color: var(--dim); margin-left: auto; }
.inspect .what { font-size: 12.5px; color: var(--muted); line-height: 1.6;
                 margin: 9px 0 0; }
.inspect .state { display: flex; align-items: center; gap: 7px; font-size: 12px;
                  margin-top: 13px; }
.inspect .needs { font-size: 11.5px; color: var(--dim); margin-top: 6px;
                  line-height: 1.5; }
.inspect .links { margin-top: 14px; padding-top: 12px;
                  border-top: 1px solid var(--line); display: grid; gap: 4px; }
.inspect .links div { font-size: 11.5px; color: var(--muted); }
.tone-ok { color: var(--ok); } .tone-hold { color: var(--hold); }
.tone-block { color: var(--block); } .tone-dim { color: var(--dim); }

.beat { width: 7px; height: 7px; border-radius: 50%; background: var(--dim);
        flex: none; }
.beat.ok { background: var(--ok); }
.beat.hold { background: var(--hold); }
.beat.block { background: var(--block); }

/* ── conversation ──────────────────────────────────────────────────── */
.stream { display: flex; flex-direction: column; gap: 9px; max-height: 40vh;
          overflow-y: auto; padding-right: 4px; }
.turn { font-size: 13px; line-height: 1.55; white-space: pre-wrap;
        word-wrap: break-word; padding-left: 11px;
        border-left: 2px solid var(--line-strong); }
.turn .who { font-size: 9.5px; letter-spacing: .16em; text-transform: uppercase;
             color: var(--dim); margin-bottom: 3px; }
.turn.operator { border-left-color: var(--accent); }
.turn.supervisor, .turn.brain { border-left-color: var(--muted); }
.turn.system { color: var(--muted); font-size: 12px; }

.ask { border: 1px solid var(--accent-line); background: var(--accent-soft);
       border-radius: var(--radius); padding: 13px 15px; margin-bottom: 14px; }
.ask .q { font-weight: 600; font-size: 13.5px; }
.ask .why { font-size: 12px; color: var(--muted); margin: 4px 0 11px; }
.row { display: flex; gap: 7px; flex-wrap: wrap; }

button, input, textarea {
  font: inherit; color: var(--text); background: var(--raised);
  border: 1px solid var(--line-strong); border-radius: var(--radius-sm);
  padding: 9px 13px; }
button { cursor: pointer; transition: border-color .12s, background .12s; }
button:hover:not(:disabled) { border-color: var(--accent); background: var(--accent-soft); }
button:disabled { opacity: .4; cursor: default; }
button.go { background: var(--accent); border-color: var(--accent);
            color: var(--accent-ink); font-weight: 600; }
button.go:hover:not(:disabled) { background: var(--accent-lift); }
input, textarea { flex: 1; min-width: 0; }
input::placeholder, textarea::placeholder { color: var(--dim); }
textarea { resize: vertical; min-height: 84px; width: 100%; }

.composer { display: flex; gap: 8px; margin-top: 16px; }
.hint { font-size: 11.5px; color: var(--dim); margin-top: 9px; line-height: 1.55; }
.hint.live { color: var(--hold); }

/* ── fleet ─────────────────────────────────────────────────────────── */
.fleet { display: grid; gap: 1px; background: var(--line);
         border: 1px solid var(--line); border-radius: var(--radius);
         overflow: hidden; }
.crew { display: grid; grid-template-columns: 30px minmax(150px, 1fr) minmax(0, 2.1fr) 130px;
        gap: 16px; align-items: center; padding: 15px 18px;
        background: var(--surface); cursor: pointer; transition: background .12s; }
.crew:hover { background: var(--raised); }
.crew .badge { width: 30px; height: 30px; border-radius: 8px; display: grid;
               place-items: center; font-size: 11px; font-weight: 700;
               color: var(--c); border: 1px solid var(--c);
               background: color-mix(in srgb, var(--c) 11%, transparent); }
.crew .who { font-size: 14px; font-weight: 600; }
.crew .slug { font-size: 11px; color: var(--dim); margin-top: 2px; }
.crew .what { font-size: 12.5px; color: var(--muted); line-height: 1.5; }
.crew .state { display: flex; align-items: center; gap: 7px; font-size: 11.5px;
               color: var(--muted); justify-content: flex-end; }

/* ── figures ───────────────────────────────────────────────────────── */
.figures { display: grid; gap: 26px 40px;
           grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.fig .v { font-size: 30px; font-weight: 200; letter-spacing: -.02em;
          font-variant-numeric: tabular-nums; line-height: 1.1; }
.fig .k { font-size: 10.5px; letter-spacing: .13em; text-transform: uppercase;
          color: var(--muted); margin-top: 7px; }
.fig .d { font-size: 11.5px; color: var(--dim); margin-top: 4px; line-height: 1.45; }
.fig.ok .v { color: var(--ok); } .fig.hold .v { color: var(--hold); }
.fig.block .v { color: var(--block); } .fig.dim .v { color: var(--dim); }

/* ── charts ────────────────────────────────────────────────────────── */
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }
.heat { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 12px);
        gap: 3px; overflow-x: auto; padding-bottom: 4px; }
.cell { width: 12px; height: 12px; border-radius: 2px; background: var(--accent); }
.bars { display: flex; align-items: flex-end; gap: 3px; height: 84px; }
.bar { flex: 1; min-width: 3px; border-radius: 2px 2px 0 0; min-height: 2px;
       background: var(--faint); }
.bar.peak { background: var(--accent); }
.axis { display: flex; justify-content: space-between; font-size: 10px;
        color: var(--dim); margin-top: 7px; }
.split { display: grid; gap: 13px; margin-top: 8px; }
.share .top { display: flex; justify-content: space-between; font-size: 12px;
              margin-bottom: 5px; }
.share .top b { font-weight: 500; }
.share .top span { color: var(--muted); font-variant-numeric: tabular-nums; }
.share .track { height: 4px; border-radius: 2px; background: var(--line);
                overflow: hidden; }
.share .fill { height: 100%; background: var(--accent); }

/* ── systems ───────────────────────────────────────────────────────── */
.systems { display: grid; gap: 1px; background: var(--line);
           border: 1px solid var(--line); border-radius: var(--radius);
           overflow: hidden; }
.system { display: grid;
          grid-template-columns: 8px minmax(140px, 1fr) minmax(0, 2fr) minmax(150px, 1fr);
          gap: 16px; align-items: center; padding: 15px 18px;
          background: var(--surface); }
.system .who { font-size: 13.5px; font-weight: 600; }
.system .what { font-size: 12.5px; color: var(--muted); line-height: 1.5; }
.system .needs { font-size: 11px; color: var(--dim); line-height: 1.5; }
.system .state { font-size: 11.5px; }

/* ── rows ──────────────────────────────────────────────────────────── */
.rows { display: grid; gap: 1px; background: var(--line);
        border: 1px solid var(--line); border-radius: var(--radius);
        overflow: hidden; }
.row-line { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; gap: 14px;
            align-items: center; padding: 13px 18px; background: var(--surface);
            font-size: 13px; }
.row-line .sub { font-size: 11px; color: var(--dim); margin-top: 2px; }
.row-line .age { font-size: 11px; color: var(--muted); white-space: nowrap;
                 font-variant-numeric: tabular-nums; }

/* ── decisions ─────────────────────────────────────────────────────── */
.calls { display: grid; gap: 12px; }
.call { border-left: 2px solid var(--line-strong); padding-left: 13px; }
.call.ok { border-left-color: var(--ok); }
.call.hold { border-left-color: var(--hold); }
.call.block { border-left-color: var(--block); }
.call .who { font-size: 10px; letter-spacing: .13em; text-transform: uppercase;
             color: var(--dim); }
.call .what { font-size: 13px; margin-top: 2px; }
.call .why { font-size: 11.5px; color: var(--muted); margin-top: 4px; }

/* ── responsive ────────────────────────────────────────────────────── */
@media (max-width: 1180px) {
  .ops, .pair { grid-template-columns: 1fr; }
  .crew { grid-template-columns: 30px 1fr; }
  .crew .what, .crew .state { grid-column: 2; justify-content: flex-start; }
  .system { grid-template-columns: 8px 1fr; }
  .system .what, .system .needs, .system .state { grid-column: 2; }
}
@media (max-width: 820px) {
  .app { grid-template-columns: 1fr; }
  .rail { position: static; height: auto; border-right: none;
          border-bottom: 1px solid var(--line); padding: 18px 20px; }
  .rail nav { flex-direction: row; flex-wrap: wrap; }
  .rail .foot { margin-top: 14px; padding: 0; }
  .main { padding: 22px 20px 60px; }
  .head { align-items: flex-start; }
  .tally { gap: 18px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""


def stylesheet() -> str:
    """Tokens plus layout, as one `<style>` body."""
    return css_variables() + _CSS

"""The dashboard's stylesheet.

Kept apart from the markup for one reason: it is long, and a page module that
holds both is a module nobody reads. There is no build step, no preprocessor
and no CDN — the Content-Security-Policy the server sends forbids all three,
and a test asserts the page contains no external URL.
"""

from __future__ import annotations

from jarvis.theme import css_variables

_LAYOUT = """
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}
/* A faint grid, the way a heads-up display has one. Pointer-events off so it
   never eats a click. */
body::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    linear-gradient(var(--line-soft) 1px, transparent 1px),
    linear-gradient(90deg, var(--line-soft) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse at 50% 0%, #000 10%, transparent 78%);
}
.shell { position: relative; z-index: 1; max-width: 1500px; margin: 0 auto;
         padding: 18px 20px 60px; }

/* --- header ---------------------------------------------------------- */
.top { display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
       padding-bottom: 16px; border-bottom: 1px solid var(--line); }
.brand h1 { margin: 0; font-size: 26px; font-weight: 700; letter-spacing: .34em;
            color: var(--accent); text-shadow: 0 0 22px rgba(0,212,255,.45); }
.brand p { margin: 4px 0 0; font-size: 11.5px; color: var(--muted); }
.spacer { flex: 1 1 auto; }
.readout { text-align: right; }
.readout .clock { font-size: 26px; font-weight: 300; letter-spacing: .05em;
                  font-variant-numeric: tabular-nums; }
.readout .date { font-size: 11px; color: var(--muted); letter-spacing: .16em;
                 text-transform: uppercase; }
.pills { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 8px;
         justify-content: flex-end; }
.pill { font-size: 10.5px; letter-spacing: .11em; text-transform: uppercase;
        padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line);
        color: var(--muted); white-space: nowrap; }
.pill.on { color: var(--accent); border-color: var(--accent-dim);
           background: var(--accent-faint); }
.pill.live { color: var(--warn); border-color: rgba(255,107,53,.4);
             background: rgba(255,107,53,.09); }
.pill.ok { color: var(--ok); border-color: rgba(68,201,143,.35); }
.pill.hold { color: var(--hold); border-color: rgba(246,211,101,.35); }
.pill.block { color: var(--block); border-color: rgba(224,85,97,.4); }

/* --- navigation ------------------------------------------------------ */
.nav { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0 20px; }
.nav a { font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
         color: var(--muted); text-decoration: none; padding: 7px 14px;
         border: 1px solid var(--line); border-radius: 8px;
         background: var(--panel); transition: .15s; }
.nav a:hover, .nav a:focus-visible {
  color: var(--accent); border-color: var(--accent-dim);
  background: var(--accent-faint); outline: none; }

/* --- panels ---------------------------------------------------------- */
.grid { display: grid; grid-template-columns: 1.55fr 1fr; gap: 16px;
        align-items: start; }
.grid .wide { grid-column: 1 / -1; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

.panel { position: relative; overflow: hidden; background: var(--panel);
         border: 1px solid var(--line); border-radius: 12px;
         padding: 18px 20px; scroll-margin-top: 14px;
         animation: rise .45s ease-out both; }
.panel::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
                 background: linear-gradient(90deg, transparent,
                             var(--edge, var(--accent)), transparent); }
.panel > h2 { margin: 2px 0 14px; font-size: 11px; font-weight: 700;
              letter-spacing: .2em; text-transform: uppercase;
              color: var(--muted); display: flex; gap: 10px;
              align-items: baseline; }
.panel > h2 .note { font-weight: 400; letter-spacing: .04em;
                    text-transform: none; color: var(--dim); font-size: 11px; }
@keyframes rise { from { opacity: 0; transform: translateY(9px); } }

/* --- arc reactor ----------------------------------------------------- */
.reactor { position: relative; width: 132px; height: 132px; flex: none;
           display: grid; place-items: center; cursor: pointer;
           background: none; border: 0; padding: 0; }
.reactor .ring, .reactor .glow, .reactor .core { position: absolute;
                                                 border-radius: 50%; }
.reactor .ring { width: 132px; height: 132px;
                 border: 2px dashed var(--accent-dim);
                 animation: spin 14s linear infinite; }
.reactor .glow { width: 94px; height: 94px; border: 1px solid var(--accent-dim);
                 background: radial-gradient(circle, var(--accent-faint) 0%,
                             transparent 70%);
                 box-shadow: 0 0 26px rgba(0,212,255,.45),
                             0 0 58px rgba(0,212,255,.18);
                 animation: breathe 4s ease-in-out infinite; }
.reactor .core { width: 58px; height: 58px;
                 background: radial-gradient(circle at 50% 35%, #cdf6ff 0%,
                             var(--accent) 45%, #0a4a63 100%);
                 box-shadow: 0 0 20px rgba(0,212,255,.75); }
.reactor .dot { position: absolute; width: 4px; height: 4px; border-radius: 50%;
                background: var(--accent); box-shadow: 0 0 7px var(--accent);
                animation: orbit 3.4s linear infinite; }
.reactor .dot:nth-child(5) { animation-duration: 4.6s; animation-delay: -1.2s; }
.reactor .dot:nth-child(6) { animation-duration: 5.8s; animation-delay: -2.4s; }
.reactor.busy .ring { animation-duration: 2.6s; border-color: var(--accent); }
.reactor.busy .glow { animation-duration: 1.1s; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes breathe { 0%,100% { opacity: .55; } 50% { opacity: 1; } }
@keyframes orbit {
  from { transform: rotate(0) translateX(60px) rotate(0); }
  to   { transform: rotate(360deg) translateX(60px) rotate(-360deg); }
}
.reactor-wrap { display: flex; gap: 20px; align-items: center; }
.reactor-wrap .say { font-size: 12.5px; color: var(--muted); }
.reactor-wrap .say b { display: block; color: var(--text); font-size: 15px;
                       font-weight: 600; margin-bottom: 4px; }

/* --- conversation ---------------------------------------------------- */
.stream { display: flex; flex-direction: column; gap: 10px;
          max-height: 46vh; overflow-y: auto; padding: 2px 4px 8px 0; }
.turn { max-width: 84%; padding: 9px 13px; border-radius: 10px;
        background: var(--panel-2); border: 1px solid var(--line-soft);
        white-space: pre-wrap; word-wrap: break-word; font-size: 13.5px; }
.turn .who { font-size: 9.5px; letter-spacing: .18em; text-transform: uppercase;
             color: var(--muted); margin-bottom: 4px; }
.turn.operator { align-self: flex-end; background: rgba(0,212,255,.1);
                 border-color: var(--accent-dim); }
.turn.supervisor { border-left: 3px solid var(--purple); }
.turn.system { color: var(--muted); font-size: 12px; background: none;
               border-style: dashed; }

.ask { border: 1px solid var(--accent-dim); background: var(--accent-faint);
       border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
.ask .q { font-weight: 600; }
.ask .why { font-size: 12px; color: var(--muted); margin: 4px 0 10px; }
.row { display: flex; gap: 7px; flex-wrap: wrap; }

button, input, textarea {
  font: inherit; color: var(--text); background: var(--panel-2);
  border: 1px solid var(--line); border-radius: 8px; padding: 9px 12px; }
button { cursor: pointer; transition: .15s; }
button:hover { border-color: var(--accent); color: #fff;
               background: var(--accent-faint); }
button:disabled { opacity: .45; cursor: default; }
input, textarea { flex: 1; min-width: 0; }
textarea { resize: vertical; min-height: 62px; width: 100%; }
:focus-visible { outline: 1px solid var(--accent); outline-offset: 1px; }
.composer { display: flex; gap: 9px; margin-top: 12px; }
.composer button { min-width: 92px; }
.hint { font-size: 11.5px; color: var(--muted); margin-top: 9px; }
.hint.warn { color: var(--warn); }
.empty { color: var(--dim); font-size: 13px; padding: 6px 0; }

/* --- fleet ----------------------------------------------------------- */
.fleet { display: grid; gap: 12px;
         grid-template-columns: repeat(auto-fill, minmax(258px, 1fr)); }
.agent { position: relative; background: var(--panel-2); border-radius: 10px;
         border: 1px solid var(--line-soft); padding: 13px 14px 14px 16px; }
.agent::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px;
                 border-radius: 10px 0 0 10px; background: var(--c); }
.agent .head { display: flex; gap: 11px; align-items: center; }
.avatar { width: 34px; height: 34px; flex: none; border-radius: 9px;
          display: grid; place-items: center; font-size: 12px; font-weight: 700;
          letter-spacing: .04em; color: var(--c);
          border: 1px solid var(--c); background: color-mix(in srgb,
                  var(--c) 12%, transparent); }
.agent .name { font-weight: 600; font-size: 14px; }
.agent .meta { font-size: 10.5px; color: var(--muted); letter-spacing: .06em; }
.agent .blurb { font-size: 12px; color: var(--muted); margin: 10px 0 9px;
                line-height: 1.45; }
.tags { display: flex; gap: 5px; flex-wrap: wrap; }
.tag { font-size: 10px; letter-spacing: .05em; padding: 2px 7px;
       border-radius: 999px; border: 1px solid var(--line);
       color: var(--muted); }
.tag.on { color: var(--accent); border-color: var(--accent-dim); }
.status { position: absolute; top: 13px; right: 13px; width: 8px; height: 8px;
          border-radius: 50%; background: var(--dim); }
.status.ok { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
.status.hold { background: var(--hold); box-shadow: 0 0 8px var(--hold); }
.status.block { background: var(--block); box-shadow: 0 0 8px var(--block); }

/* --- tables and rows ------------------------------------------------- */
.rows { display: flex; flex-direction: column; gap: 7px; }
.line { display: grid; grid-template-columns: 12px 1fr auto; gap: 11px;
        align-items: center; background: var(--panel-2); border-radius: 8px;
        padding: 9px 12px; border: 1px solid var(--line-soft); font-size: 13px; }
.beat { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); }
.beat.ok { background: var(--ok); animation: pulse 1.6s ease-in-out infinite; }
.beat.hold { background: var(--hold); }
@keyframes pulse { 0%,100% { opacity: .35; } 50% { opacity: 1; } }
.line .sub { font-size: 11px; color: var(--muted); }
.line .age { font-size: 11px; color: var(--muted); white-space: nowrap;
             font-variant-numeric: tabular-nums; }

/* --- statistics ------------------------------------------------------ */
.stats { display: grid; gap: 10px;
         grid-template-columns: repeat(auto-fit, minmax(126px, 1fr)); }
.stat { background: var(--panel-2); border: 1px solid var(--line-soft);
        border-radius: 9px; padding: 11px 13px; }
.stat .v { font-size: 21px; font-weight: 600; font-variant-numeric: tabular-nums; }
.stat .k { font-size: 10px; letter-spacing: .13em; text-transform: uppercase;
           color: var(--muted); margin-top: 2px; }
.stat .d { font-size: 10.5px; color: var(--dim); margin-top: 5px;
           line-height: 1.35; }
.stat.ok .v { color: var(--ok); }
.stat.hold .v { color: var(--hold); }
.stat.block .v { color: var(--block); }
.stat.dim .v { color: var(--dim); }

/* --- heatmap and bars ------------------------------------------------ */
.heat { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 13px);
        gap: 3px; overflow-x: auto; padding-bottom: 4px; }
.cell { width: 13px; height: 13px; border-radius: 3px;
        background: var(--accent); }
.bars { display: flex; align-items: flex-end; gap: 3px; height: 84px; }
.bar { flex: 1; min-width: 3px; border-radius: 2px 2px 0 0;
       background: linear-gradient(180deg, var(--accent), rgba(0,212,255,.18));
       min-height: 2px; }
.bar.peak { background: linear-gradient(180deg, #fff, var(--accent)); }
.axis { display: flex; justify-content: space-between; font-size: 9.5px;
        color: var(--dim); margin-top: 6px; letter-spacing: .05em; }
.split { display: flex; flex-direction: column; gap: 9px; }
.share .top { display: flex; justify-content: space-between; font-size: 12px;
              margin-bottom: 4px; }
.share .track { height: 6px; border-radius: 3px; background: var(--panel-2);
                overflow: hidden; }
.share .fill { height: 100%; border-radius: 3px; background: var(--accent); }
.share .fill.sonnet { background: var(--purple); }
.share .fill.haiku { background: var(--ok); }
.share .fill.unknown { background: var(--dim); }

/* --- decisions ------------------------------------------------------- */
.card { border-left: 3px solid var(--dim); background: var(--panel-2);
        border-radius: 0 8px 8px 0; padding: 9px 12px; margin-bottom: 8px; }
.card.ok { border-left-color: var(--ok); }
.card.hold { border-left-color: var(--hold); }
.card.block { border-left-color: var(--block); }
.card .who { font-size: 10px; letter-spacing: .13em; text-transform: uppercase;
             color: var(--muted); }
.card .why { font-size: 11.5px; color: var(--muted); margin-top: 4px; }

/* --- the operations sphere ------------------------------------------- */
.hero { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr);
        gap: 18px; align-items: stretch; }
.orb-wrap { position: relative; display: grid; place-items: center;
            min-height: 380px; padding: 6px 0 2px; }
#sphere { width: 100%; display: grid; place-items: center; }
.orb { width: 100%; height: auto; max-width: 720px; overflow: visible;
       filter: drop-shadow(0 0 40px rgba(0, 212, 255, 0.10)); }

.orb-rim { fill: radial-gradient(circle, transparent, transparent);
           fill: rgba(0, 212, 255, 0.022);
           stroke: var(--accent-dim); stroke-width: 1;
           stroke-dasharray: 3 9; transform-origin: center;
           animation: orbspin 90s linear infinite; }
.orb-ring { fill: none; stroke: var(--line-soft); stroke-width: 1; }
@keyframes orbspin { to { transform: rotate(360deg); } }

.edge { stroke-width: 1.1; transition: opacity .22s; }
.edge-reviews   { stroke: var(--purple); stroke-dasharray: 2 5; }
.edge-delegates { stroke: var(--accent); stroke-width: 1.5; }
.edge-uses      { stroke: var(--muted); }
.edge-operates  { stroke: var(--text); stroke-width: 1.6; }

.orb-node { cursor: pointer; transition: opacity .22s; }
.orb-node:focus-visible { outline: none; }
.orb-node .disc { stroke: var(--bg); stroke-width: 2; transition: r .18s; }
.orb-node .halo { opacity: .16; animation: haloPulse 3.2s ease-in-out infinite; }
.orb-node .pending { fill: none; stroke-width: 1; stroke-dasharray: 2 4; opacity: .6; }
.orb-node .orb-label { fill: var(--muted); font-size: 10.5px; text-anchor: middle;
                       letter-spacing: .04em; pointer-events: none;
                       paint-order: stroke; stroke: var(--bg); stroke-width: 3px; }
.orb-node.kind-supervisor .orb-label { fill: var(--text); font-size: 12px;
                                       font-weight: 600; letter-spacing: .1em; }
.orb-node:hover .disc, .orb-node.is-focus .disc { stroke: var(--accent); }
.orb-node.is-focus .orb-label { fill: var(--text); }
.orb-node:focus-visible .disc { stroke: var(--accent); stroke-width: 3; }
@keyframes haloPulse { 0%,100% { opacity: .10; } 50% { opacity: .30; } }

.legend { display: flex; gap: 14px; flex-wrap: wrap; justify-content: center;
          margin-top: 6px; font-size: 10.5px; color: var(--dim); }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend i { width: 16px; height: 0; border-top: 1.5px solid currentColor;
            display: inline-block; }
.legend .l-reviews { color: var(--purple); }
.legend .l-delegates { color: var(--accent); }
.legend .l-uses { color: var(--muted); }

/* --- node detail ------------------------------------------------------ */
.nd-head { display: flex; align-items: baseline; gap: 9px; margin-bottom: 8px; }
.nd-dot { width: 10px; height: 10px; border-radius: 50%; flex: none;
          align-self: center; }
.nd-name { font-size: 16px; font-weight: 600; }
.nd-kind { font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
           color: var(--dim); }
.nd-detail { margin: 0 0 10px; font-size: 12.5px; color: var(--muted);
             line-height: 1.5; }
.nd-status { display: flex; align-items: center; gap: 7px; font-size: 12px;
             margin-bottom: 6px; }
.nd-status.tone-ok { color: var(--ok); }
.nd-status.tone-hold { color: var(--hold); }
.nd-status.tone-dim { color: var(--dim); }
.nd-sub { font-size: 11.5px; color: var(--dim); margin-bottom: 5px; }
.nd-edges { margin-top: 11px; border-top: 1px solid var(--line-soft);
            padding-top: 9px; }
.nd-edge { font-size: 11.5px; color: var(--muted); padding: 2px 0;
           font-variant-numeric: tabular-nums; }

@media (max-width: 1080px) {
  .grid, .two, .hero { grid-template-columns: 1fr; }
  .reactor-wrap { flex-direction: column; text-align: center; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


def stylesheet() -> str:
    """Palette plus layout, as one `<style>` body."""
    return css_variables() + _LAYOUT

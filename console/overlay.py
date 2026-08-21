"""Rendering the heads-up display.

One self-contained HTML file: inline CSS, inline JSON, no build step, no CDN,
no framework. It opens from the filesystem or from the local server, and it
works with the network unplugged.

**The overlay cannot act.** There is no button that approves, sends or books
anything, and the server behind it exposes no route that would. A display with
controls would be a second path around the codex, and an unaudited one — see
the README in this package.

The template is assembled with `replace()` rather than an f-string or
`.format()`, because CSS is mostly braces and both of those would fight it.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime

from console.models import OverlayState

_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #05080d;
  --panel: rgba(14, 22, 34, 0.82);
  --edge: rgba(94, 234, 255, 0.22);
  --text: #dbe7f2;
  --dim: #7c8ea3;
  --accent: #5eeaff;
  --ok: #4ade80;
  --hold: #fbbf24;
  --block: #fb7185;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 18px;
  background: var(--bg);
  color: var(--text);
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.5;
  background-image:
    radial-gradient(circle at 12% -10%, rgba(94,234,255,0.10), transparent 55%),
    radial-gradient(circle at 88% 110%, rgba(94,234,255,0.06), transparent 55%);
  min-height: 100vh;
}
header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
h1 { font-size: 15px; margin: 0; letter-spacing: 0.14em;
     text-transform: uppercase; color: var(--accent); }
.sub { color: var(--dim); font-size: 12px; }
.pulse { width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
         box-shadow: 0 0 10px var(--accent); animation: pulse 2.4s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
        gap: 8px; margin: 14px 0; }
.stat { background: var(--panel); border: 1px solid var(--edge);
        border-radius: 8px; padding: 10px 12px; }
.stat .n { font-size: 22px; font-weight: 600; }
.stat .l { color: var(--dim); font-size: 10px; letter-spacing: 0.13em; text-transform: uppercase; }
.n.ok { color: var(--ok); } .n.hold { color: var(--hold); } .n.block { color: var(--block); }
section { margin-top: 16px; }
h2 { font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase;
     color: var(--dim); margin: 0 0 8px; font-weight: 600; }
.card { background: var(--panel); border: 1px solid var(--edge); border-left-width: 3px;
        border-radius: 6px; padding: 9px 12px; margin-bottom: 6px; }
.card.ok { border-left-color: var(--ok); }
.card.hold { border-left-color: var(--hold); }
.card.block { border-left-color: var(--block); }
.card .top { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.card .subj { font-weight: 600; }
.tag { font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase; padding: 2px 6px;
       border-radius: 3px; white-space: nowrap; }
.tag.ok { background: rgba(74,222,128,0.14); color: var(--ok); }
.tag.hold { background: rgba(251,191,36,0.14); color: var(--hold); }
.tag.block { background: rgba(251,113,133,0.14); color: var(--block); }
.meta { color: var(--dim); font-size: 11px; }
.reason { color: var(--dim); font-size: 11px; padding-left: 12px;
          border-left: 1px solid var(--edge); margin-top: 5px; }
ul { list-style: none; margin: 0; padding: 0; }
li.task { background: var(--panel); border: 1px solid var(--edge); border-radius: 6px;
          padding: 7px 11px; margin-bottom: 5px; }
.say { color: var(--dim); font-size: 11px; border-top: 1px solid var(--edge);
       margin-top: 18px; padding-top: 10px; }
.say b { color: var(--accent); font-weight: 600; }
footer { color: var(--dim); font-size: 10px; margin-top: 16px; letter-spacing: 0.08em; }
</style>
</head>
<body>
<header>
  <span class="pulse"></span>
  <h1>__HEADING__</h1>
  <span class="sub">__SUBHEADING__</span>
</header>
<div id="root"></div>
<footer>Read-only. This display cannot approve, send or book anything.</footer>
<script id="state" type="application/json">__STATE__</script>
<script>
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));

function render(s) {
  const stat = (n, l, cls) =>
    `<div class="stat"><div class="n ${cls}">${n}</div><div class="l">${l}</div></div>`;

  const card = c => `
    <div class="card ${c.tone}">
      <div class="top">
        <span class="subj">${esc(c.subject)}</span>
        <span class="tag ${c.tone}">${
          c.tone === "ok" ? "approved" : c.tone === "hold" ? "hold" : "blocked"
        }</span>
      </div>
      <div class="meta">${esc(c.agent)}${c.recipient ? " → " + esc(c.recipient) : ""}</div>
      ${(c.reasons || []).map(r => `<div class="reason">${esc(r)}</div>`).join("")}
    </div>`;

  document.getElementById("root").innerHTML = `
    <div class="grid">
      ${stat(s.approved, "approved", "ok")}
      ${stat(s.held, "held", "hold")}
      ${stat(s.blocked, "blocked", "block")}
      ${stat(Math.round(s.autonomy_rate * 100) + "%", "autonomy", "")}
      ${stat("$" + Number(s.cost_usd).toFixed(4), "spent", "")}
    </div>
    <section>
      <h2>Decisions</h2>
      ${(s.cards || []).map(card).join("")}
    </section>
    ${(s.tasks || []).length ? `<section><h2>Today</h2><ul>${
      s.tasks.map(t => `<li class="task">${esc(t)}</li>`).join("")}</ul></section>` : ""}
    ${(s.utterances || []).length ? `<div class="say"><b>Spoken briefing</b><br>${
      s.utterances.filter(u => u.channel !== "display")
        .map(u => esc(u.spoken_text || u.display_text)).join(" ")}</div>` : ""}`;
}

render(JSON.parse(document.getElementById("state").textContent));

// Live mode polls the read-only snapshot endpoint. Absent on a static file,
// where the state above is all there is.
const endpoint = "__ENDPOINT__";
if (endpoint) {
  setInterval(async () => {
    try { render(await (await fetch(endpoint, { cache: "no-store" })).json()); }
    catch (e) { /* keep showing the last good snapshot */ }
  }, 5000);
}
</script>
</body>
</html>
"""


def render_overlay(state: OverlayState, *, endpoint: str = "") -> str:
    """Render the HUD as one self-contained HTML document.

    With no `endpoint`, the state is inlined and the file is a frozen snapshot
    that works offline from disk. With one, the page re-fetches that read-only
    snapshot every few seconds.
    """
    payload = json.loads(state.model_dump_json())
    payload["cards"] = [
        {**card, "tone": original.tone}
        for card, original in zip(payload["cards"], state.cards, strict=True)
    ]

    return (
        _TEMPLATE.replace("__TITLE__", html.escape(state.heading or "Overlay"))
        .replace("__HEADING__", html.escape(state.heading or "Overlay"))
        .replace("__SUBHEADING__", html.escape(state.subheading))
        # </script> inside the JSON payload would close the tag early; the
        # escape is invisible to JSON.parse and harmless everywhere else.
        .replace("__STATE__", json.dumps(payload).replace("</", "<\\/"))
        .replace("__ENDPOINT__", html.escape(endpoint))
    )


def snapshot_heading(now: datetime | None = None) -> str:
    """Heading for an overlay rendered outside a briefing context."""
    moment = now or datetime.now(UTC)
    return f"Agent overlay — {moment:%d %b %H:%M} UTC"

"""The page skeleton.

Four views behind one left rail, rather than one long scroll of panels. The
earlier dashboard put every readout on a single page, which meant the sphere —
the thing worth looking at — shared the screen with a heatmap, a diagnostics
grid and a capture form, and none of them had room.

    Operations   the sphere, the inspector, the command box
    Fleet        the eight agents, as rows
    Activity     this machine's Claude Code history
    Systems      what is connected, what is not, and what the guardrails say

Switching views is client-side and hash-addressed, so a link to `#activity`
opens on Activity and the browser's back button works. No round trip: the
server already sent everything.

The template holds no data. Every value is written by `scripts.py` through
`textContent`, which is what keeps a task somebody typed from becoming markup.
"""

from __future__ import annotations

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — agent operations</title>
<style>{css}</style></head>
<body>
<div class="app">

  <aside class="rail">
    <div class="mark"><span class="dot"></span><span class="name">JARVIS</span></div>
    <nav id="nav">
      <a href="#operations" data-view="operations">Operations
        <span class="count" id="n-open"></span></a>
      <a href="#fleet" data-view="fleet">Fleet
        <span class="count" id="n-fleet"></span></a>
      <a href="#activity" data-view="activity">Activity
        <span class="count" id="n-days"></span></a>
      <a href="#systems" data-view="systems">Systems
        <span class="count" id="n-systems"></span></a>
    </nav>
    <div class="foot">
      <div class="clock" id="clock">--:--</div>
      <div class="meta" id="mode"></div>
      <div class="meta"><a href="/workspace">Plain console</a></div>
    </div>
  </aside>

  <main class="main">

    <header class="head">
      <div>
        <h1 id="title">Operations</h1>
        <p id="subtitle"></p>
      </div>
      <div class="grow"></div>
      <div class="tally">
        <div class="ok"><div class="v" id="t-approved">0</div><div class="k">approved</div></div>
        <div class="hold"><div class="v" id="t-held">0</div><div class="k">held</div></div>
        <div class="block"><div class="v" id="t-blocked">0</div><div class="k">blocked</div></div>
      </div>
    </header>

    <!-- ── Operations ─────────────────────────────────────────────── -->
    <section class="view" id="view-operations">
      <div class="ops">
        <div>
          <div class="orb-stage"><div id="sphere"></div></div>
          <div class="key">
            <span class="k-rev"><i></i> reviews</span>
            <span class="k-del"><i></i> typed handoff</span>
            <span><i></i> uses a system</span>
            <span>dashed outline · not connected</span>
          </div>
        </div>

        <div class="side">
          <div class="inspect" id="inspect"></div>

          <div>
            <h2 class="section">Conversation</h2>
            <div id="asks"></div>
            <div class="stream" id="stream"></div>
            <div class="composer">
              <input id="request" placeholder="Give an agent something to do…"
                     autocomplete="off">
              <button id="send" class="go" type="button">Send</button>
            </div>
            <div class="hint" id="status"></div>
            <div class="hint">
              This console creates work. It has no control that approves any —
              every result goes through the codex.
            </div>
          </div>
        </div>
      </div>

      <h2 class="section">Recent decisions</h2>
      <div class="calls" id="calls"></div>
    </section>

    <!-- ── Fleet ──────────────────────────────────────────────────── -->
    <section class="view" id="view-fleet">
      <p class="note">Eight agents, running in this process. Three take free
        text from the command box; the rest work on structured input and say so
        rather than pretending otherwise. Select one to see it in the sphere.</p>
      <div class="fleet" id="fleet"></div>
    </section>

    <!-- ── Activity ───────────────────────────────────────────────── -->
    <section class="view" id="view-activity">
      <p class="note" id="activity-note"></p>
      <div class="figures" id="figures"></div>

      <div class="pair" style="margin-top:36px">
        <div>
          <h2 class="section">Daily messages</h2>
          <div class="heat" id="heat"></div>
        </div>
        <div>
          <h2 class="section">Hour of day</h2>
          <div class="bars" id="hours"></div>
          <div class="axis"><span>00</span><span>06</span><span>12</span>
            <span>18</span><span>23</span></div>
          <div class="hint" id="peak"></div>
        </div>
      </div>

      <h2 class="section">Models</h2>
      <div class="split" id="models"></div>

      <h2 class="section">Live sessions</h2>
      <div class="rows" id="sessions"></div>
    </section>

    <!-- ── Systems ────────────────────────────────────────────────── -->
    <section class="view" id="view-systems">
      <p class="note">Every outside system this repository can reach, and the
        truthful state of each. Two need nothing. Three are implemented and
        waiting on one credential. Two are interfaces with no implementation
        behind them, which the sphere draws with a dashed outline.</p>
      <div class="systems" id="systems"></div>

      <h2 class="section">Guardrails</h2>
      <p class="note">Not CPU and memory. The interesting question about an
        agent fleet is whether the limits still hold.</p>
      <div class="figures" id="checks"></div>

      <h2 class="section">Quick capture</h2>
      <p class="note" id="capture-note"></p>
      <input id="capture-title" placeholder="Title (optional)" autocomplete="off"
             style="margin-bottom:9px">
      <textarea id="capture-body" placeholder="A note for the vault…"></textarea>
      <div class="composer">
        <div class="grow"></div>
        <button id="capture" type="button">Capture</button>
      </div>
    </section>

  </main>
</div>
<script>const BOOTSTRAP = {bootstrap};</script>
<script>{sphere_js}</script>
<script>{app_js}</script>
</body></html>
"""

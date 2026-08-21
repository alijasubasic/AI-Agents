# console

The layer a person actually looks at: a heads-up overlay, a spoken briefing,
and an Obsidian vault recording everything the agents did.

```bash
python -m console.demo      # render, speak and record one day
python -m console.server    # the same overlay, live on localhost
```

Mock voice and a local vault by default, so this runs on a clone with no API
key, no ElevenLabs account, and no vault of your own.

---

## The one idea worth taking from this package

**The console observes. It cannot act.**

There is no button that approves a held decision, no endpoint that sends a
blocked email, no method anywhere in this package that changes anything the
agents decided. The server refuses every HTTP method except `GET` and `HEAD`
before it even looks at the path.

That is not tidiness. A display with controls is a **second way to approve
something** — one that never passes through the codex and never lands in the
audit trail. The whole point of
[ADR 0005](../docs/adr/0005-monotonic-supervision.md) is that oversight can only
tighten; a HUD with an "approve anyway" button would hand that back for the
sake of a convenient click.

Two tests hold the line: one asserts the rendered page contains no `<form>`,
`<button>` or `<input>`, and one walks every mutating HTTP method and expects
`405`.

## The overlay

One self-contained HTML file. Inline CSS, inline JSON, no build step, no CDN,
no framework — it opens from disk with the network unplugged.

Decisions are ordered **by how much attention they need**, not by time: blocked
first, then held, then the ones that went through. A display sorted
chronologically buries the two things worth looking at.

### Making it a Jarvis-style window

The overlay is a web page because a GUI framework would break
[ADR 0001](../docs/adr/0001-no-agent-framework.md) and the promise that this
repository runs on a fresh machine with nothing installed. Chrome gets you the
frameless always-on-top window without any of that:

```bash
chrome --app=http://127.0.0.1:8787 --window-size=460,900
```

`--app` drops the tab strip and address bar. Pinning it above other windows is
your window manager's job — on Windows, PowerToys' Always On Top (`Win`+`Ctrl`+`T`).

## Voice

`ElevenLabs` bills per character, which makes a runaway loop a billing incident
rather than a slow afternoon. The provider enforces its own character ceiling
rather than trusting the caller — the same reasoning as codex article A7, one
layer down. Exceeding it raises; the briefing then reports the failure and
stops speaking rather than failing the whole run.

Spoken and displayed wording are generated separately. `2 of 7 (29%)` is fine
in a table and unintelligible read aloud, so the briefing says "two out of
seven were verified" instead. Dates are assembled by hand because `%-d` does
not exist on Windows.

**Only what needs a person is read out in detail.** Reading seven approvals
aloud trains the listener to stop paying attention by the third, which is
exactly when the blocked one arrives. Approvals are counted; blocks and urgent
tasks are named.

Nothing the codex refused is ever spoken as though it happened — every mention
of a blocked decision carries the word "blocked", and a test checks it against
real pipeline output.

| | |
|---|---|
| `MockVoice` | Records a transcript. No network, no audio. **Default.** |
| `ElevenLabsVoice` | Real synthesis. **Not covered by tests** — see below. |

## Obsidian

This is the one integration in the repository that is built completely rather
than as a skeleton, because a vault is just a folder of Markdown files. No
account, no API, nothing to apologise for.

**Wikilinks turn an audit log into something you can navigate.** Every decision
note links to the agent that made it, to each codex article that fired on it,
and to the day's brief:

```markdown
## Linked
- [[Agent lead-research]]
- [[2026-03-06 Brief]]
- [[A2 Honesty]]
- [[A3 No unbacked commitments]]
```

Open `A2 Honesty` in Obsidian and the backlinks pane lists **every decision
that article has ever blocked**. Nobody built that view; it falls out of
writing the links. Frontmatter carries `verdict`, `agent`, `action` and
`cost_usd` as typed values, so Dataview queries work over the same notes.

```
vault/
  Briefs/      one per day
  Decisions/   one per decision, with the draft and why it was refused
  Codex/       one per article, with its backlinks
```

Slugs are stable, so re-running a day rewrites its notes rather than
accumulating `note 1.md`, `note 2.md`. Filenames are stripped of the characters
Windows forbids and the ones Obsidian reads as link syntax — a note containing
either one will fail to write or silently break every link pointing at it.

Point it at a real vault with `OBSIDIAN_VAULT_PATH`. The default is a
git-ignored `vault/` folder inside the repository, so a clone can never write
into somebody's notes by accident.

## Configuration

```bash
VOICE_MODE=live                 # anything else uses the mock
ELEVENLABS_API_KEY=...          # required when VOICE_MODE=live
ELEVENLABS_VOICE_ID=...         # optional
OBSIDIAN_VAULT_PATH=/path/to/vault
```

## Limitations

- **`ElevenLabsVoice` is unverified.** Nothing in CI touches it, because doing
  so would need a paid account. It is written to the documented API and should
  be treated as unproven until someone runs it against a real key.
- **There is no voice input.** The console speaks; it does not listen. Adding
  speech-to-text is straightforward — but a spoken *command* interface would
  need a path from the microphone to an action, and this package deliberately
  has no path to an action at all. That is a design question before it is an
  engineering one.
- **Audio is written to disk, not played.** Live mode saves MP3 files; playing
  them needs an audio library, which is a dependency this package has not
  earned yet.
- **The overlay polls; it is not pushed to.** Five-second polling is fine for
  a morning brief and wrong for anything live. Server-sent events would fix it
  and would be the first thing to add if the agents ever ran continuously.
- **`http.server` is not a production web server.** It binds to localhost,
  serves one person, and holds no state. Putting this on a network would need a
  real server and an answer to authentication, which right now is "there is
  nothing to authenticate because there is nothing to do".
- **The vault is written, never read.** Editing a note in Obsidian has no
  effect on anything; the next run overwrites it. Round-tripping human edits
  back into the system is a genuinely useful feature and a genuinely hard one.

# Connecting real accounts

Everything in this repository runs with **no accounts and no API key**. That is
the default and it stays the default — `make demo` works on a machine that has
never heard of Google.

This page is about turning that off, one system at a time. It is written as a
checklist because that is what it is: exactly what you have to supply, where it
goes, and how to prove it worked.

> **Nothing here is committed.** Every credential lives outside the repository
> and every path below is git-ignored. If a step ever asks you to put a secret
> in a file inside this folder, the step is wrong.

---

## The short answer

| System | What I need from you | What it costs |
|---|---|---|
| **Anthropic** | one API key | pennies per request |
| **Google** (Calendar + Gmail + Drive) | one OAuth client JSON, then one browser approval | free |
| **Obsidian** | a folder path | free, already works |
| **ElevenLabs** | one API key | free tier is enough |
| **Web search** | not built — see [below](#what-is-not-built) | — |
| **CRM** | not built — see [below](#what-is-not-built) | — |

Google is one credential for all three services. You do not need three.

---

## 1. Anthropic — makes the agents think

Without this the agents run on scripted replies. With it, they reason.

1. Go to <https://console.anthropic.com> → **API keys** → **Create key**
2. Copy it once — the console will not show it again
3. Put it in `.env` in the repository root:

```
ANTHROPIC_MODE=live
AGENT_MODE=live
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Prove it:

```bash
python -m agents.lead_research.demo
```

The header prints `mode=live`. If it prints `mode=mock`, the key was not read.

> **I will never type a key for you and never ask you to paste one into this
> chat.** Anything pasted into a conversation is in a transcript forever. Put
> it in `.env` yourself; that file is git-ignored and stays on your machine.

---

## 2. Google — Calendar, Gmail and Drive

One OAuth client covers all three. This takes about ten minutes, once.

### 2a. What I need from you

Exactly **one file** and **two environment variables**:

| | |
|---|---|
| **The file** | `client_secret_*.json`, downloaded from Google Cloud Console |
| `GOOGLE_CLIENT_SECRETS` | the full path to that file — **outside this repository** |
| `GOOGLE_TOKEN_PATH` | where the token should be written — **outside this repository** |

That is the whole list. You never send me the file, and you never paste its
contents anywhere. You put it on your disk and point a variable at it.

### 2b. Create the OAuth client

1. Open <https://console.cloud.google.com> and **create a project**
   (name it anything — `jarvis-agents` is fine)

2. **APIs & Services → Library** → enable these three:
   - Google Calendar API
   - Gmail API
   - Google Drive API

3. **APIs & Services → OAuth consent screen**
   - User type: **External**
   - App name, your email, your email again — nothing else is required
   - **Audience → Test users → Add your own Google address**

   > This is the step people miss. An app in *Testing* only works for accounts
   > listed as test users. You do not need to publish or get verified; you are
   > the only user.

4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Download the JSON

5. Move it somewhere sensible and private, e.g.
   `C:\Users\you\.google\client_secret.json`

### 2c. Point the repository at it

Add to `.env`:

```
GOOGLE_CLIENT_SECRETS=C:\Users\you\.google\client_secret.json
GOOGLE_TOKEN_PATH=C:\Users\you\.google\jarvis-token.json
```

Both paths are **outside** the repository. That is deliberate: a credential
inside a working tree is a credential one careless `git add -A` away from a
public repository.

### 2d. Approve it once

```bash
uv sync --extra google
python -m integrations.google.connect
```

A browser opens. Approve. The token is written to `GOOGLE_TOKEN_PATH`.

Then prove it — this makes one real read-only call against each API:

```bash
python -m integrations.google.check
```

```
  [ ok ] calendar   3 calendar(s) visible
  [ ok ] gmail      14,208 messages in the mailbox
  [ ok ] drive      0 app-owned file(s)
```

### 2e. What it can and cannot do

The scopes are deliberately narrow. This is the part worth reading.

| Scope asked for | What it allows | What it does **not** allow |
|---|---|---|
| `calendar.readonly` | free/busy — *when* someone is busy | reading what the meeting is |
| `calendar.events` | create and update events | deleting calendars, changing sharing |
| `gmail.modify` | read messages, add labels | changing settings or filters |
| `drive.file` | files **this app created** | anything else in your Drive |

**Sending mail is not in that list.** `gmail.send` is a separate, opt-in scope:

```bash
python -m integrations.google.connect --allow-send
```

Do the first connection *without* it. Reading and labelling is useful on its
own; sending is the one path that reaches another person. And even with the
scope granted, the code refuses unless it is also constructed with
`allow_send=True` — two independent switches, because a config file being wrong
should not be able to email your customer.

The same applies to creating calendar events: `GoogleCalendar(allow_writes=True)`
is required, and the default is `False`.

### 2f. What Google will not give you

`calendar-booking` needs each attendee's **working hours and time zone**.
Google does not expose that for anyone but you — `calendar.readonly` gives free
and busy, not office hours.

Guessing 09:00–17:00 in your own zone would produce proposals that look
authoritative and are wrong for anybody abroad, which is the exact failure this
agent exists to prevent. So attendees come from a roster you maintain:

```python
from agents.calendar_booking.models import Attendee, WorkingHours
from integrations.google.calendar import GoogleCalendar

roster = {
    "dana@example.com": Attendee(
        email="dana@example.com",
        name="Dana Reyes",
        working_hours=WorkingHours(start_hour=9, end_hour=17, timezone="Europe/Berlin"),
    ),
}
calendar = GoogleCalendar(roster=roster)
```

An address that is not in the roster is an unknown address, and the agent says
so rather than inventing a schedule for it.

---

## 3. Obsidian — the audit trail

Already works. It needs a folder, not an account.

```
OBSIDIAN_VAULT_PATH=D:\path	o\Your Vault
```

Every decision becomes a Markdown note that links to its agent, the codex
articles that fired on it, and the day's brief. Open `A2 Honesty` in Obsidian
and the backlinks pane lists every decision that article has ever blocked.

---

## 4. ElevenLabs — the spoken brief

```
VOICE_MODE=live
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...        # optional; there is a sensible default
```

Get the key at <https://elevenlabs.io> → **Profile → API key**. The free tier
covers a daily brief comfortably.

The voice enforces its own per-character ceiling, because ElevenLabs bills that
way and a runaway loop would be a billing incident rather than a bug.

---

## What is *not* built

Two integrations are interfaces with nothing behind them, and the dashboard
draws them with a dashed ring for exactly that reason.

**Web search** (`lead-research`). The agent's `SearchProvider` interface is
real and the mock returns a fixed corpus. A live implementation needs a search
API — Brave, Serper, Tavily, or Google Custom Search — and each returns a
different shape. Picking one is a decision, not an afternoon.

**CRM** (`email-triage`). `HttpCrm` exists as a skeleton. Which CRM decides
everything about the mapping, so there is nothing honest to write until there
is a CRM.

Neither is stubbed with fake data pretending to be live. An interface that
raises `NotImplementedError` is a better answer than one that quietly returns
something plausible.

---

## Making the agents run for real, not for show

Connecting an account is half of it. This is the other half — the difference
between a demo and something you would actually leave running.

### The three modes, and what each one proves

| | reasoning | data | proves |
|---|---|---|---|
| `AGENT_MODE=mock` | scripted | fixtures | the orchestration works |
| `AGENT_MODE=live` | real model | fixtures | the *reasoning* works |
| live + connected accounts | real model | your data | it works |

Most people stop at the middle row and call it done. The row below it is where
the interesting failures live: a mailbox where every third message is a
newsletter, a calendar where somebody shared free/busy but not details, a
company whose website has been down since 2019.

### Swapping a mock for the real thing

Every agent takes its provider as a constructor argument, so this is one line:

```python
from agents.email_triage.agent import EmailTriageAgent
from integrations.google.gmail import GmailMailbox  # was MockMailbox
from core.llm import AnthropicProvider
from core.config import Settings

settings = Settings.from_env()
agent = EmailTriageAgent(
    provider=AnthropicProvider(settings),
    mailbox=GmailMailbox(query="is:unread in:inbox newer_than:2d"),
    settings=settings,
)
```

No agent code changes. That is the entire point of the provider interfaces, and
it is why they were written before any live implementation existed.

### Do this in order

1. **Run it read-only first.** `allow_send=False`, `allow_writes=False` — the
   defaults. Watch what it *would* have done for a few days.
2. **Read the morning brief before trusting the queue.** `make brief` writes
   what every agent decided and what the supervisor made of it. If the held
   items look wrong, the agents are wrong.
3. **Narrow the query.** `newer_than:2d` on a mailbox with ten years of history
   is the difference between a test and a bill.
4. **Watch the cost.** Every run reports tokens and dollars. `max_cost_usd`
   stops a run that overspends, per run — not per day.
5. **Only then turn on sending**, and only for one label at a time.

### What will go wrong first

Honest list, from the shapes of these APIs rather than from experience with
your data:

- **Most mail is not what the fixtures look like.** Newsletters, automated
  receipts, and calendar invites all arrive as ordinary messages. Expect the
  first run to escalate far more than the demo does — that is the agent being
  cautious, which is the correct direction to fail.
- **Free/busy is often empty** because colleagues share their calendar with
  their organisation, not with your OAuth client. The code raises rather than
  reading an empty result as "free"; you will see it immediately.
- **Threading matters more than it looks.** A reply without `In-Reply-To`
  arrives as a new conversation and looks like a bot. The Gmail provider sets
  it; anything you write on top of it should too.
- **Rate limits arrive at scale, not in testing.** Gmail's per-user limit is
  generous for one mailbox and not for a loop over a thousand messages.

---

## Everything in one place

The complete list of environment variables. `.env.example` in the repository
root carries the same list with placeholder values.

```bash
# Reasoning
AGENT_MODE=live                 # or mock (default)
ANTHROPIC_API_KEY=sk-ant-api03-...

# Google — one credential, three services
GOOGLE_CLIENT_SECRETS=/path/outside/this/repo/client_secret.json
GOOGLE_TOKEN_PATH=/path/outside/this/repo/token.json

# Obsidian
OBSIDIAN_VAULT_PATH=/path/to/your/vault

# Voice
VOICE_MODE=live                 # or mock (default)
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...

# Guardrails — sensible defaults, override if you mean it
AGENT_MAX_STEPS=8
AGENT_TIMEOUT_SECONDS=60
AGENT_MAX_COST_USD=1.00
```

## If something does not work

| Symptom | Cause |
|---|---|
| `mode=mock` when you set live | `.env` not read — check for a BOM, or a quoted value |
| `GOOGLE_CLIENT_SECRETS is not set` | the variable, not the file, is missing |
| `access_denied` in the browser | your address is not a **test user** on the consent screen |
| `insufficient authentication scopes` | scopes changed since you connected — delete the token, connect again |
| `Google returned no free/busy` | that calendar is not shared with the account you connected |
| `will not send` | working as designed — see [2e](#2e-what-it-can-and-cannot-do) |

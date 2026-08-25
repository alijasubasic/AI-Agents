# The operator console

An Obsidian-styled workspace you can type into: give an agent a task, answer
the questions it asks back, and see what the supervisor made of the result.

```bash
make console                       # http://127.0.0.1:8756
python -m console.chat_demo        # the same flow in the terminal, no server
```

---

## It can create work. It cannot approve any.

An earlier version of this console was strictly read-only, and the reasoning
was written down: *a heads-up display with action buttons is a second path
around the codex.* Adding a chat contradicts that, so the rule had to be
re-examined rather than quietly dropped.

The principle was never "the console must be inert". It was **nothing reaches
the outside world unreviewed**. A task typed here becomes an ordinary
`Decision` and goes through the same supervisor and the same codex as work an agent
raised on its own — so the sharper rule is:

> The console may create work; it has no route that approves any.

That is testable, and it is tested. The route table is asserted directly:

| | |
|---|---|
| `GET /` | the console |
| `GET /api/state` | what it renders, as JSON |
| `POST /api/task` | give an agent something to do |
| `POST /api/answer` | answer a question an agent asked |

There is no endpoint that sets a verdict, sends a message, books anything, or
overrides an escalation. `test_no_route_approves_sends_books_or_overrides`
fails if one appears.

## Clarification is not escalation

This is the idea worth taking from the whole component.

Before this, agents had two outcomes: finish, or escalate. That forces a bad
choice on any task with a gap in it — abandon it to a human, or guess. Both are
worse than asking.

| | Who owns the work afterwards | What the human does |
|---|---|---|
| **Escalation** | the human | *decides* |
| **Clarification** | still the agent | *tells it something*, and it continues |

`TaskStatus.NEEDS_CLARIFICATION` is a pause, not a handover. In the demo,
"*Have a look at that company we spoke to*" names no company, so the research
agent asks rather than profiling whichever one it saw first:

```
you     Have a look at that company we spoke to and pull together a profile.
supervisor   Routed to lead-research — asks for a profile, though not which company
agent   Which company should I research? (I could not identify one in the ...)
you     Kestrel Systems
agent   Kestrel Systems: 2 of 7 claims verified against 4 source(s).
```

**An answer is data, not instruction.** It is appended to the briefing under a
labelled heading rather than merged into the request, so nothing in a reply can
be mistaken for the original task. Answering a question twice changes nothing —
a second reply must not be able to steer the agent somewhere else.

## The supervisor answers first

When an agent asks something, the supervisor looks at the question before the
operator does, and answers the ones the codex already settles.

```
-> supervisor: May I send this to the address, even though it is unconfirmed?
          A4 Confirmed recipient: No. Nothing may be sent to an address
          nobody confirmed.

-> you:   Which of the two Berlin warehouses does this order ship from?
          (no rule covers this; it needs a person)
```

An assistant that interrupts you with a question its own rulebook answers is
one you learn to ignore, and once you ignore it you miss the question that
mattered. The matching is deterministic — a supervisor that *decided* whether to
interrupt would interrupt inconsistently.

Settled questions are still recorded with their answer, so the exchange stays
in the transcript and the ruling reaches the agent's next briefing.

## Routing: the model proposes, code disposes

A model picks which agent should take a request; `ChatSession._route` validates
the name against the handlers that actually exist. A hallucinated agent name
sends work nowhere.

**"None" is a good answer.** A request nobody can place produces a question
listing the available agents, rather than a guess that wastes a real run:

```
you     Sort out the parking situation in the office.
agent   I could not place this. No agent here deals with facilities.
        -> Which agent should take this?  [lead-research] [knowledge-base]
```

## Adapters, and where they do not fit

Each agent's interface is shaped by its own problem — `propose(text)`,
`ask(text)`, `research(company)`. The chat hands all of them a sentence
somebody typed, and [`handlers.py`](handlers.py) bridges that.

The bridging is where the honest work is. `lead-research` needs a company
name, and `find_company` matches against the known corpus rather than pulling a
capitalised phrase out of the sentence — a regex would happily "find" a company
in *"research our biggest account"*. Two companies named is ambiguous, not a
coin flip. No company named is a question.

## Security notes

- **Localhost only, and not configurable.** This process holds an API key and
  spends money when told to. Binding it to a network interface should not be
  something an argument can do.
- **Request bodies are capped** and rejected unread past a few kilobytes.
- **Everything is rendered through `textContent`**, never as markup.
- **The bootstrap payload is escaped for `<script>` embedding.** `json.dumps`
  escapes quotes but not angle brackets, so a task containing the literal
  `</script>` closed the block early and the rest was parsed as markup. That
  was a real hole in this file, found by a test written against it, and
  `test_a_script_tag_in_a_task_cannot_close_the_bootstrap_block` keeps it shut.

## Limitations

- **Conversations live in memory.** Restarting the server loses the transcript.
  The vault writer is right there and nothing yet writes conversations into it.
- **One session, one operator.** No accounts, no locking. Two browsers pointed
  at the same server share one conversation and will confuse each other.
- **Polling, not streaming.** The page refreshes every four seconds; a long
  agent run looks like nothing happening. Server-sent events would fix it.
- **A task runs synchronously inside the POST.** A slow agent holds the request
  open, and the browser's timeout, not the agent's, decides when to give up.
- **`supervisor_answer` is four regexes.** It covers the articles most likely to be
  asked about and will miss a policy question phrased unusually — in which case
  the operator is asked, which is the safe direction to fail.
- **Only three agents are reachable.** `email-triage` and `call-intake` work on
  fixtures rather than free text, so there is nothing sensible to hand them
  from a chat box yet.

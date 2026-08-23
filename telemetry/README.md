# telemetry

Reads this machine's own Claude Code transcripts and turns them into counts,
costs and a thirty-day picture. No API key, no network, no account — the data
is already on the disk.

```bash
python -m telemetry.demo
```

This is the one component in the repository whose data is **real**. Every agent
here runs on fixtures and says so; this one does not have to.

---

## Counts, timestamps and tool names. Never message text.

A session transcript is somebody's actual work: client names, half-written
emails, things they pasted and regretted. So the rule is enforced in the type
system rather than promised in a comment —

> there is no field in [`models.py`](models.py) that can hold a sentence a
> person or a model wrote.

`LiveSession.tool` is `"Bash"`, never the command. The source this borrows from
renders the tool *input* on screen, which is how a dashboard ends up displaying
the contents of a file somebody just opened.
`test_no_transcript_text_reaches_the_models` puts a marker string in every
content field of a transcript and asserts it appears in neither parser's output.

## The counting bug

Claude Code does not write one record per assistant message. It writes **one
record per content block**, and every one of them repeats the message's full
`usage`. A turn made of thinking, text and two tool calls appears four times.

Summing usage across records therefore counts the same tokens up to seven times
over. Measured against one real session on this machine:

| | tokens | cost |
|---|---:|---:|
| summing every record | 456,000,000 | $367 |
| deduplicated by message id | 252,000,000 | $177 |

Tool calls are the **opposite** case and must not be deduplicated — each record
carries a *different* block, so all of them count. One rule cannot cover both,
which is why `parse_whole` handles them separately and two tests pin the
distinction.

The second correction is cheaper to state: **cache reads are billed.** They are
0.1× the input rate, not free, and on a long agent session they are most of the
input. `pricing.cost_of_usage` charges cache reads and cache writes; a naive
`input × rate + output × rate` misses almost the whole bill.

## Two reads, because they want opposite things

| | needs | so it |
|---|---|---|
| **liveness** | the end of the file, now, every four seconds | seeks to the last 48 KB |
| **statistics** | the whole file, once ever | streams it and caches the result |

`parse_tail` walks backwards from the end until it has the model, the tool in
flight and whether the last turn closed. `parse_whole` streams the file once —
these reach hundreds of megabytes, and the aggregation only needs one record at
a time.

## The cache is keyed on mtime, not a clock

A finished transcript never changes again. So the answer is kept against the
file's modification time and a refresh costs one `stat` per file.

A time-to-live cache would re-read everything every five minutes whether or not
anything happened: gigabytes of I/O on a quiet afternoon to produce a
byte-identical answer, and a five-minute-stale dashboard on a busy one.

The cache carries a **version integer**, which exists because of a specific
failure. When `SessionSummary.daily` was added, every cached entry validated
cleanly — new fields have defaults — and was served forever, because the
transcript's mtime had not changed and so it was never re-read. The heatmap
collapsed a week of work onto a single day and stayed that way. Bumping
`CACHE_VERSION` discards the old shape.

## What it does not do

* **It does not shell out to `pgrep`.** The source dashboard runs
  `pgrep -fa claude` on every refresh to decide whether Claude Code is running.
  That is a process listing per poll, it is Unix-only, and it answers the wrong
  question: a running binary says nothing about whether *this* transcript is
  active. A `stat` answers the actual question.
* **It does not follow paths out of the scan root.** Directory entries are
  resolved and checked against the root before being read, so a symlink planted
  in `~/.claude/projects` cannot make the walk visit somebody's documents.
* **It does not invent data.** `collect()` returns an honest empty result when
  there is nothing to find. `load()` substitutes fixtures — and sets
  `Telemetry.real = False`, which the dashboard prints. A heatmap that quietly
  shows invented data is worse than an empty one, because you would believe it.

## Sessions span days

A long run began on Monday and is still going on Thursday. Attributing all of
it to `started_at` — which is what the source does — leaves Thursday's cell
empty while you are visibly typing into it, and a panel that says nothing
happened today is one you stop believing.

`SessionSummary.daily` records messages against the day they happened on. The
session itself is still counted once, on the day it began, because that is what
a session count means. Cost follows the messages: the transcript prices a
request, not a day, so splitting by volume is the honest approximation.

## Limitations

- **The window is thirty days and the scan is whole-file.** The first run on a
  machine with a long history takes a few seconds. Every run after that is a
  `stat` per file.
- **Project labels are the last path segment.** `D--Claude-Sessions` becomes
  `Sessions`. Two projects whose directories end the same way are
  indistinguishable on screen.
- **Subagent transcripts are named from their `.meta.json` sidecar.** Without
  one they read as "subagent" rather than by type — the parent session holds
  the `Agent` call that named them, and correlating the two on every refresh
  would cost the saving the tail read exists for.
- **`hourly` counts records, not messages.** It is a shape, not a total, and
  the block-splitting described above inflates it uniformly.

"""Reading Claude Code transcripts without reading what they say.

Two jobs, and they want opposite things:

* **liveness** needs the *end* of the file and needs it now, on every refresh
* **statistics** need the *whole* file, but only once per file ever

So there are two functions. `parse_tail` seeks to the last few kilobytes and
walks backwards until it has what it needs; `parse_whole` streams the file once
and is cached against the modification time by the caller. Reading a whole
history on every four-second refresh is the mistake this split exists to avoid
-- a year of transcripts is gigabytes.

Every record is parsed defensively. A transcript is appended to by a running
process, so the last line is routinely half-written, and a parser that raises
on that would fail exactly when the session is most interesting.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from core.models import Usage
from telemetry.models import Activity, LiveSession, SessionSummary
from telemetry.pricing import NON_MODELS, cost_of_usage

#: How much of the end of the file `parse_tail` looks at. Large enough to hold
#: the last several turns of a busy session, small enough that scanning twenty
#: transcripts costs nothing.
TAIL_BYTES = 48 * 1024

#: A transcript this quiet is not "in flight" whatever else is true.
WORKING_SECONDS = 45
WAITING_SECONDS = 300


def _records(text: str) -> Iterator[dict]:
    """Every parsable JSON object in a chunk of transcript.

    Silently drops the rest. The first line of a tail read is almost always a
    fragment, and the last line of a live file often is too.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def _read_tail(path: Path, size: int = TAIL_BYTES) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        total = handle.tell()
        handle.seek(max(0, total - size))
        return handle.read().decode("utf-8", errors="replace")


def _usage_of(message: dict) -> Usage:
    raw = message.get("usage") or {}
    if not isinstance(raw, dict):
        return Usage()
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cache_read_input_tokens=int(raw.get("cache_read_input_tokens") or 0),
        cache_creation_input_tokens=int(raw.get("cache_creation_input_tokens") or 0),
    )


def _timestamp(record: dict) -> datetime | None:
    raw = record.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def message_key(record: dict) -> str | None:
    """The API message id a record belongs to, if it has one.

    **This is the correction that matters most in this package.** Claude Code
    does not write one record per assistant message — it writes *one record per
    content block*, and every one of them repeats the message's full `usage`.
    A four-block turn (thinking, text, two tool calls) appears four times.

    Summing usage across records therefore counts the same tokens up to seven
    times. Measured against one real session on this machine, the naive sum
    reported 456M tokens and $367; deduplicated, 252M tokens and $177. The
    dashboard this idea came from sums every record, so its cost figures are
    high by roughly that factor.

    Tool calls are the opposite case and must *not* be deduplicated: each
    record carries a different block, so all of them count.
    """
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    identifier = message.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier
    # Older transcripts predate the message id; the request id is per-response
    # too, so it deduplicates just as well.
    fallback = record.get("requestId")
    return fallback if isinstance(fallback, str) and fallback else None


def _tool_blocks(record: dict) -> Iterator[dict]:
    """Every `tool_use` block in an assistant record."""
    message = record.get("message")
    if record.get("type") != "assistant" or not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block


def _activity(age_seconds: float, finished: bool) -> Activity:
    """Working, waiting on a person, or idle.

    `finished` means the last assistant turn ended cleanly — the model stopped
    because it had nothing more to say, not because it is mid-tool-call. That
    is the difference between "thinking" and "waiting for you", and showing the
    first when it is the second makes the panel useless.
    """
    if age_seconds > WAITING_SECONDS:
        return Activity.IDLE
    if finished:
        return Activity.WAITING
    return Activity.WORKING if age_seconds <= WORKING_SECONDS else Activity.WAITING


def parse_tail(path: Path, project: str, *, now: datetime | None = None) -> LiveSession | None:
    """What a transcript looks like it is doing, from its last few kilobytes.

    Returns None only if the file cannot be read at all. An idle session is
    still a session; deciding whether it is old enough to hide is the caller's
    business, not the parser's.
    """
    try:
        stat = path.stat()
        text = _read_tail(path)
    except OSError:
        return None

    now = now or datetime.now(UTC)
    age = max(0.0, now.timestamp() - stat.st_mtime)

    records = list(_records(text))
    model = ""
    tool: str | None = None
    subagent: str | None = None
    finished = False

    # Deduplicated for the same reason as `parse_whole` — see `message_key`.
    # An assistant turn split across four blocks is one message, not four.
    seen: set[str] = set()
    messages = 0
    for record in records:
        kind = record.get("type")
        if kind == "user":
            messages += 1
        elif kind == "assistant":
            key = message_key(record)
            if key is None or key not in seen:
                messages += 1
            if key is not None:
                seen.add(key)

    # Walk backwards: the most recent mention of each thing is the true one.
    for record in reversed(records):
        message = record.get("message")
        if isinstance(message, dict):
            candidate = message.get("model")
            if not model and isinstance(candidate, str) and candidate not in NON_MODELS:
                model = candidate
            if record.get("type") == "assistant" and message.get("stop_reason") == "end_turn":
                finished = True

        for block in _tool_blocks(record):
            name = block.get("name")
            if not tool and isinstance(name, str):
                tool = name
            payload = block.get("input")
            if not subagent and name == "Agent" and isinstance(payload, dict):
                chosen = payload.get("subagent_type")
                if isinstance(chosen, str):
                    subagent = chosen
        if model and tool and subagent:
            break

    return LiveSession(
        session_id=path.stem,
        project=project,
        model=model,
        tool=tool,
        subagent=subagent,
        activity=_activity(age, finished),
        age_seconds=int(age),
        recent_messages=messages,
    )


def parse_whole(path: Path, project: str) -> SessionSummary | None:
    """One transcript reduced to counts and money.

    Streamed line by line rather than read into memory: these files reach
    hundreds of megabytes on a long project, and the aggregation only ever
    needs one record at a time.
    """
    try:
        stat = path.stat()
    except OSError:
        return None

    summary = SessionSummary(session_id=path.stem, project=project, mtime=stat.st_mtime)
    total = Usage()
    priced: dict[str, Usage] = {}
    #: Message ids whose usage has already been counted. See `message_key`.
    counted: set[str] = set()

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue

                stamp = _timestamp(record)
                local = stamp.astimezone() if stamp else None
                if local:
                    if summary.started_at is None:
                        summary.started_at = local
                    summary.ended_at = local
                    summary.hours[local.hour] = summary.hours.get(local.hour, 0) + 1

                # Attributed to the day the message happened on, not the day
                # the session started. See `SessionSummary.daily`.
                today = local.date() if local else None

                kind = record.get("type")
                if kind == "user":
                    summary.messages += 1
                    if today:
                        summary.daily[today] = summary.daily.get(today, 0) + 1

                message = record.get("message")
                if kind != "assistant" or not isinstance(message, dict):
                    continue

                model = message.get("model")
                if isinstance(model, str) and model not in NON_MODELS and not summary.model:
                    summary.model = model

                # Every block of a turn carries the whole turn's usage, so it
                # is counted once. Tool calls are counted from every record,
                # because each one holds a different block.
                summary.tool_calls += sum(1 for _ in _tool_blocks(record))

                identifier = message_key(record)
                if identifier is not None and identifier in counted:
                    continue
                if identifier is not None:
                    counted.add(identifier)
                summary.messages += 1
                if today:
                    summary.daily[today] = summary.daily.get(today, 0) + 1

                usage = _usage_of(message)
                total = total + usage
                # Priced per model, not per session: a session that switched
                # models mid-way would otherwise bill all of it at whichever id
                # happened to appear first.
                key = model if isinstance(model, str) else ""
                priced[key] = priced.get(key, Usage()) + usage
    except OSError:
        return None

    summary.input_tokens = total.input_tokens
    summary.output_tokens = total.output_tokens
    summary.cache_read_tokens = total.cache_read_input_tokens
    summary.cache_write_tokens = total.cache_creation_input_tokens
    summary.cost_usd = sum(cost_of_usage(usage, model) for model, usage in priced.items())
    return summary

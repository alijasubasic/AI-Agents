"""Tests for transcript parsing.

The transcripts here are written by hand rather than copied from a real
session, for the obvious reason: a fixture lifted from `~/.claude` is somebody's
work, and it would be in the repository forever.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from telemetry.models import Activity
from telemetry.parser import message_key, parse_tail, parse_whole
from telemetry.pricing import cost_of_usage, model_family, price_of


def write(path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def assistant(
    message_id: str,
    *,
    blocks: list[dict] | None = None,
    usage: dict | None = None,
    model: str = "claude-opus-5",
    stop: str = "tool_use",
    stamp: str = "2026-08-20T21:15:00Z",
) -> dict:
    return {
        "type": "assistant",
        "timestamp": stamp,
        "requestId": f"req_{message_id}",
        "message": {
            "id": message_id,
            "model": model,
            "stop_reason": stop,
            "content": blocks if blocks is not None else [{"type": "text"}],
            "usage": usage or {},
        },
    }


USAGE = {
    "input_tokens": 10,
    "output_tokens": 100,
    "cache_read_input_tokens": 50_000,
    "cache_creation_input_tokens": 2_000,
}


# --- The counting bug this package exists to get right -------------------


def test_one_turn_split_across_blocks_is_counted_once(tmp_path):
    """The correction at the heart of `message_key`.

    Claude Code writes one record per content block, each repeating the whole
    turn's usage. Summing them counts the same tokens four times over.
    """
    path = tmp_path / "s.jsonl"
    write(
        path,
        [
            assistant("msg_1", blocks=[{"type": "thinking"}], usage=USAGE),
            assistant("msg_1", blocks=[{"type": "text"}], usage=USAGE),
            assistant("msg_1", blocks=[{"type": "tool_use", "name": "Bash"}], usage=USAGE),
            assistant("msg_1", blocks=[{"type": "tool_use", "name": "Edit"}], usage=USAGE),
        ],
    )

    summary = parse_whole(path, "proj")

    assert summary is not None
    assert summary.messages == 1, "four records, one assistant turn"
    assert summary.output_tokens == 100, "usage counted once, not four times"
    assert summary.cache_read_tokens == 50_000


def test_tool_calls_are_not_deduplicated(tmp_path):
    """The opposite case, and the reason the two cannot share one rule.

    Each record carries a *different* block, so deduplicating tool calls by
    message id would report one tool call for a turn that made two.
    """
    path = tmp_path / "s.jsonl"
    write(
        path,
        [
            assistant("msg_1", blocks=[{"type": "text"}], usage=USAGE),
            assistant("msg_1", blocks=[{"type": "tool_use", "name": "Bash"}], usage=USAGE),
            assistant("msg_1", blocks=[{"type": "tool_use", "name": "Edit"}], usage=USAGE),
        ],
    )

    summary = parse_whole(path, "proj")

    assert summary is not None
    assert summary.tool_calls == 2


def test_a_record_without_a_message_id_still_counts(tmp_path):
    # Falling back to requestId, and then to counting it, so an unfamiliar
    # transcript shape under-reports nothing.
    path = tmp_path / "s.jsonl"
    write(
        path,
        [
            {"type": "assistant", "message": {"model": "claude-opus-5", "usage": USAGE}},
            {"type": "assistant", "message": {"model": "claude-opus-5", "usage": USAGE}},
        ],
    )

    summary = parse_whole(path, "proj")

    assert summary is not None
    assert summary.messages == 2


def test_message_key_prefers_the_message_id():
    record = assistant("msg_9")
    assert message_key(record) == "msg_9"
    assert message_key({"type": "assistant", "requestId": "req_9"}) is None
    assert message_key({"type": "assistant", "message": {}, "requestId": "req_9"}) == "req_9"


# --- Robustness ----------------------------------------------------------


def test_a_half_written_last_line_does_not_raise(tmp_path):
    # A live transcript is being appended to while it is read.
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps(assistant("msg_1", usage=USAGE)) + '\n{"type": "assist',
        encoding="utf-8",
    )

    summary = parse_whole(path, "proj")

    assert summary is not None
    assert summary.messages == 1


def test_a_missing_file_returns_none(tmp_path):
    assert parse_whole(tmp_path / "nope.jsonl", "proj") is None
    assert parse_tail(tmp_path / "nope.jsonl", "proj") is None


def test_an_empty_file_parses_to_zeroes(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("", encoding="utf-8")

    summary = parse_whole(path, "proj")

    assert summary is not None
    assert (summary.messages, summary.cost_usd) == (0, 0.0)


def test_a_synthetic_model_is_not_priced(tmp_path):
    """`<synthetic>` marks a record Claude Code generated for itself.

    Treating it as an unknown model would bill local bookkeeping at the most
    expensive tier, which is how a dashboard invents money.
    """
    path = tmp_path / "s.jsonl"
    write(path, [assistant("msg_1", model="<synthetic>", usage=USAGE)])

    summary = parse_whole(path, "proj")

    assert summary is not None
    assert summary.model == ""


# --- Liveness ------------------------------------------------------------


def touch(path, seconds_ago: float) -> None:
    when = time.time() - seconds_ago
    import os

    os.utime(path, (when, when))


def test_a_recent_tool_call_reads_as_working(tmp_path):
    path = tmp_path / "s.jsonl"
    write(path, [assistant("m", blocks=[{"type": "tool_use", "name": "Bash"}], usage=USAGE)])
    touch(path, 3)

    session = parse_tail(path, "proj")

    assert session is not None
    assert session.activity is Activity.WORKING
    assert session.tool == "Bash"
    assert session.doing == "running Bash"


def test_a_finished_turn_reads_as_waiting_not_working(tmp_path):
    """The distinction the panel is for.

    A session that ended its turn is waiting on a person. Showing it as
    "working" is the difference between a useful panel and a decorative one.
    """
    path = tmp_path / "s.jsonl"
    write(path, [assistant("m", stop="end_turn", usage=USAGE)])
    touch(path, 3)

    session = parse_tail(path, "proj")

    assert session is not None
    assert session.activity is Activity.WAITING


def test_an_old_transcript_reads_as_idle(tmp_path):
    path = tmp_path / "s.jsonl"
    write(path, [assistant("m", usage=USAGE)])
    touch(path, 4000)

    session = parse_tail(path, "proj")

    assert session is not None
    assert session.activity is Activity.IDLE
    assert session.age_label.endswith("h ago")


def test_a_delegating_session_names_the_subagent(tmp_path):
    path = tmp_path / "s.jsonl"
    write(
        path,
        [
            assistant(
                "m",
                blocks=[
                    {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "Explore"}}
                ],
                usage=USAGE,
            )
        ],
    )
    touch(path, 2)

    session = parse_tail(path, "proj")

    assert session is not None
    assert session.subagent == "Explore"
    assert session.doing == "delegating to Explore"


def test_the_tail_reads_only_the_end_of_a_large_file(tmp_path):
    """A year of history must not cost a full read on every refresh."""
    path = tmp_path / "s.jsonl"
    filler = [assistant(f"old_{n}", usage=USAGE) for n in range(4000)]
    write(path, [*filler, assistant("last", blocks=[{"type": "tool_use", "name": "Grep"}])])
    touch(path, 1)
    assert path.stat().st_size > 200_000

    session = parse_tail(path, "proj")

    assert session is not None
    assert session.tool == "Grep"
    # Proof that it did not read the whole file: the tail window holds far
    # fewer than the four thousand turns written above.
    assert session.recent_messages < 1000


# --- No message text escapes ---------------------------------------------


def test_no_transcript_text_reaches_the_models(tmp_path):
    """The rule the whole package rests on, asserted rather than promised."""
    secret = "acme-corp confidential merger memo"
    path = tmp_path / "s.jsonl"
    write(
        path,
        [
            {
                "type": "assistant",
                "timestamp": "2026-08-20T10:00:00Z",
                "message": {
                    "id": "msg_1",
                    "model": "claude-opus-5",
                    "usage": USAGE,
                    "content": [
                        {"type": "text", "text": secret},
                        {"type": "tool_use", "name": "Bash", "input": {"command": secret}},
                    ],
                },
            },
            {"type": "user", "message": {"content": secret}},
        ],
    )
    touch(path, 2)

    rendered = parse_whole(path, "proj").model_dump_json()
    rendered += parse_tail(path, "proj").model_dump_json()

    assert "acme" not in rendered.lower()
    assert "merger" not in rendered.lower()


# --- Pricing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "family"),
    [
        ("claude-opus-4-1-20250805", "opus"),
        ("claude-sonnet-5", "sonnet"),
        ("claude-haiku-4-5-20251001", "haiku"),
        ("<synthetic>", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        ("gpt-something", "unknown"),
    ],
)
def test_model_families_are_read_from_the_id(model, family):
    assert model_family(model) == family


def test_an_unknown_model_is_priced_at_the_most_expensive_tier():
    """Erring low is how a cost estimate lets a bill surprise you."""
    unknown = price_of("some-new-model")
    known = price_of("claude-opus-5")
    assert unknown.input >= known.input
    assert unknown.output >= known.output


def test_cache_reads_are_billed_and_are_not_free():
    """The other half of the correction.

    The source dashboard prices `input * rate + output * rate` and drops the
    cache fields, which on an agent session is most of the input.
    """
    from core.models import Usage

    cached = Usage(cache_read_input_tokens=1_000_000)
    cost = cost_of_usage(cached, "claude-opus-5")

    assert cost > 0
    assert cost == pytest.approx(0.5)  # $5/M input, billed at 0.1x


def test_parse_whole_prices_each_model_separately(tmp_path):
    path = tmp_path / "s.jsonl"
    write(
        path,
        [
            assistant("a", model="claude-opus-5", usage={"output_tokens": 1_000_000}),
            assistant("b", model="claude-haiku-4-5", usage={"output_tokens": 1_000_000}),
        ],
    )

    summary = parse_whole(path, "proj")

    # $25/M for opus output plus $5/M for haiku, not both at whichever id came
    # first in the file.
    assert summary is not None
    assert summary.cost_usd == pytest.approx(30.0)


def test_timestamps_land_in_local_hour_buckets(tmp_path):
    path = tmp_path / "s.jsonl"
    stamp = datetime(2026, 8, 20, 21, 15, tzinfo=UTC)
    write(path, [assistant("m", stamp=stamp.isoformat().replace("+00:00", "Z"))])

    summary = parse_whole(path, "proj")

    assert summary is not None
    expected = stamp.astimezone().hour
    assert summary.hours == {expected: 1}
    assert summary.started_at is not None
    assert abs(summary.started_at - stamp) < timedelta(seconds=1)

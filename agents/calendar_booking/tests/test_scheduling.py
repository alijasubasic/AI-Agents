"""Tests for the scheduling engine.

This is the part of the agent that no model touches, so it can be pinned down
exactly. The fixtures here are written out in full rather than imported, so each
test can be checked against the calendar by eye.

March 2026 reference points:
    Thu 5th, Fri 6th, Sat 7th, Sun 8th, Mon 9th, Tue 10th, Wed 11th.
    US daylight saving starts Sun 8 March; European summer time not until the
    29th. Berlin is UTC+1 throughout this window.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from agents.calendar_booking.models import (
    Attendee,
    BusyBlock,
    SchedulingPolicy,
    TimeSlot,
    WorkingHours,
)
from agents.calendar_booking.scheduling import (
    describe_conflicts,
    find_slots,
    merge_blocks,
)

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")

#: Thursday 5 March 2026, 09:00 Berlin time.
NOW = datetime(2026, 3, 5, 8, 0, tzinfo=UTC)


def bt(day: int, hour: int, minute: int = 0) -> datetime:
    """Berlin wall-clock time in March 2026."""
    return datetime(2026, 3, day, hour, minute, tzinfo=BERLIN)


def nyt(day: int, hour: int, minute: int = 0) -> datetime:
    """New York wall-clock time in March 2026."""
    return datetime(2026, 3, day, hour, minute, tzinfo=NEW_YORK)


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


BERLIN_HOURS = WorkingHours(timezone="Europe/Berlin", start=time(9), end=time(17))
NEW_YORK_HOURS = WorkingHours(timezone="America/New_York", start=time(9), end=time(17))

ALICE = Attendee(email="a@example.com", name="Alice", working_hours=BERLIN_HOURS)
BOB = Attendee(email="b@example.com", name="Bob", working_hours=NEW_YORK_HOURS)


def policy(**overrides) -> SchedulingPolicy:
    """A policy with the friction turned off, so each test adds back only its own."""
    base = {
        "buffer_minutes": 0,
        "granularity_minutes": 30,
        "min_notice_hours": 0,
        "max_suggestions": 3,
        "max_suggestions_per_day": 1,
    }
    return SchedulingPolicy(**{**base, **overrides})


# --- merge_blocks -------------------------------------------------------


def test_merging_nothing_gives_nothing():
    assert merge_blocks([]) == []


def test_overlapping_blocks_merge():
    merged = merge_blocks(
        [
            BusyBlock(start=bt(5, 9), end=bt(5, 11)),
            BusyBlock(start=bt(5, 10), end=bt(5, 12)),
        ]
    )
    assert len(merged) == 1
    assert merged[0].start == bt(5, 9)
    assert merged[0].end == bt(5, 12)


def test_touching_blocks_merge():
    # 09:00–10:00 followed by 10:00–11:00 is one unavailable stretch.
    merged = merge_blocks(
        [
            BusyBlock(start=bt(5, 9), end=bt(5, 10)),
            BusyBlock(start=bt(5, 10), end=bt(5, 11)),
        ]
    )
    assert len(merged) == 1
    assert merged[0].end == bt(5, 11)


def test_disjoint_blocks_stay_separate():
    merged = merge_blocks(
        [
            BusyBlock(start=bt(5, 9), end=bt(5, 10)),
            BusyBlock(start=bt(5, 14), end=bt(5, 15)),
        ]
    )
    assert len(merged) == 2


def test_a_contained_block_is_absorbed():
    merged = merge_blocks(
        [
            BusyBlock(start=bt(5, 9), end=bt(5, 17)),
            BusyBlock(start=bt(5, 11), end=bt(5, 12)),
        ]
    )
    assert len(merged) == 1
    assert merged[0].end == bt(5, 17)


def test_unsorted_input_is_handled():
    merged = merge_blocks(
        [
            BusyBlock(start=bt(5, 14), end=bt(5, 15)),
            BusyBlock(start=bt(5, 9), end=bt(5, 10)),
        ]
    )
    assert merged[0].start == bt(5, 9)


# --- working hours ------------------------------------------------------


def test_working_hours_reject_before_and_after():
    assert BERLIN_HOURS.contains(bt(5, 8, 59)) is False
    assert BERLIN_HOURS.contains(bt(5, 9, 0)) is True
    assert BERLIN_HOURS.contains(bt(5, 16, 59)) is True
    assert BERLIN_HOURS.contains(bt(5, 17, 0)) is False


def test_working_hours_reject_weekends():
    # 7 and 8 March 2026 are a Saturday and a Sunday.
    assert BERLIN_HOURS.contains(bt(7, 11)) is False
    assert BERLIN_HOURS.contains(bt(8, 11)) is False
    assert BERLIN_HOURS.contains(bt(9, 11)) is True


def test_a_meeting_may_finish_exactly_at_the_end_of_the_day():
    assert BERLIN_HOURS.covers(bt(5, 16), bt(5, 17)) is True
    assert BERLIN_HOURS.covers(bt(5, 16, 30), bt(5, 17, 30)) is False


def test_working_hours_are_evaluated_in_the_owners_time_zone():
    # 15:00 Berlin is 09:00 in New York — inside Bob's day, and inside Alice's.
    moment = bt(5, 15)
    assert BERLIN_HOURS.contains(moment) is True
    assert NEW_YORK_HOURS.contains(moment) is True

    # 10:00 Berlin is 04:00 in New York — outside Bob's day.
    assert NEW_YORK_HOURS.contains(bt(5, 10)) is False


def test_naive_datetimes_are_rejected():
    # A naive datetime in a scheduler silently means "server local time".
    with pytest.raises(ValueError, match="timezone-aware"):
        BERLIN_HOURS.contains(datetime(2026, 3, 5, 10, 0))


# --- find_slots ---------------------------------------------------------


def test_slots_are_spread_across_days_and_skip_the_weekend():
    slots = find_slots(
        attendees=[ALICE],
        busy=[],
        duration_minutes=30,
        policy=policy(),
        now=NOW,
    )
    # One per day, so: Thursday, Friday, then Monday — the weekend is skipped.
    assert [s.start for s in slots] == [bt(5, 9), bt(6, 9), bt(9, 9)]


def test_existing_meetings_are_avoided():
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(5, 9), end=bt(5, 10), title="Standup")],
        duration_minutes=30,
        policy=policy(),
        now=NOW,
    )
    assert slots[0].start == bt(5, 10)


def test_the_buffer_is_applied_on_both_sides():
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(5, 9), end=bt(5, 10), title="Standup")],
        duration_minutes=30,
        policy=policy(buffer_minutes=15, granularity_minutes=15),
        now=NOW,
    )
    # The 09:00–10:00 meeting blocks 08:45–10:15 once padded.
    assert slots[0].start == bt(5, 10, 15)


def test_minimum_notice_pushes_the_first_slot_out():
    slots = find_slots(
        attendees=[ALICE],
        busy=[],
        duration_minutes=30,
        policy=policy(min_notice_hours=24),
        now=NOW,
    )
    # 24 hours from Thursday 09:00 Berlin lands on Friday morning.
    assert slots[0].start == bt(6, 9)


def test_a_meeting_that_does_not_fit_before_the_end_of_day_is_not_offered():
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(5, 9), end=bt(5, 16, 30), title="All day")],
        duration_minutes=60,
        policy=policy(max_suggestions=1),
        now=NOW,
    )
    # Only 16:30–17:00 is free on Thursday, which is half an hour short.
    assert slots[0].start == bt(6, 9)


def test_no_openings_returns_an_empty_list_not_an_error():
    slots = find_slots(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(6, 0), end=bt(7, 0), title="Blocked")],
        duration_minutes=30,
        policy=policy(),
        now=NOW,
        earliest=bt(6, 0),
        latest=bt(7, 0),
    )
    assert slots == []


def test_several_suggestions_may_share_a_day_when_the_policy_allows():
    slots = find_slots(
        attendees=[ALICE],
        busy=[],
        duration_minutes=30,
        policy=policy(max_suggestions_per_day=3),
        now=NOW,
    )
    assert [s.start for s in slots] == [bt(5, 9), bt(5, 9, 30), bt(5, 10)]


def test_an_empty_attendee_list_is_a_programming_error():
    with pytest.raises(ValueError, match="at least one attendee"):
        find_slots(attendees=[], busy=[], duration_minutes=30, now=NOW)


# --- time zones and daylight saving -------------------------------------


def test_only_the_overlap_between_two_time_zones_is_offered():
    slots = find_slots(
        attendees=[ALICE, BOB],
        busy=[],
        duration_minutes=60,
        policy=policy(max_suggestions=1),
        now=NOW,
    )
    # Berlin 09–17 is 08:00–16:00 UTC. New York 09–17 EST is 14:00–22:00 UTC.
    # The only shared window on Thursday is 14:00–16:00 UTC.
    assert slots[0].start == utc(5, 14)
    assert slots[0].start.astimezone(BERLIN).hour == 15
    assert slots[0].start.astimezone(NEW_YORK).hour == 9


def test_the_overlap_shifts_when_us_daylight_saving_begins():
    slots = find_slots(
        attendees=[ALICE, BOB],
        busy=[],
        duration_minutes=60,
        policy=policy(max_suggestions=3),
        now=NOW,
    )
    thursday, friday, monday = slots

    # Before 8 March, New York is on EST (UTC-5): the overlap opens at 14:00 UTC.
    assert thursday.start == utc(5, 14)
    assert friday.start == utc(6, 14)

    # From 8 March, New York is on EDT (UTC-4): the same 09:00 local start is
    # now an hour earlier in UTC, and the shared window is an hour wider.
    assert monday.start == utc(9, 13)

    # Both remain 09:00 for Bob — that is the point of storing UTC and
    # converting, rather than doing arithmetic on offsets.
    for slot in slots:
        assert slot.start.astimezone(NEW_YORK).hour == 9


def test_a_busy_block_in_one_zone_blocks_the_other():
    slots = find_slots(
        attendees=[ALICE, BOB],
        busy=[BusyBlock(start=nyt(5, 9), end=nyt(5, 10), title="Bob's team sync")],
        duration_minutes=60,
        policy=policy(max_suggestions=1),
        now=NOW,
    )
    # Bob's 09:00 New York meeting removes the first hour of the overlap.
    assert slots[0].start == utc(5, 15)


# --- describe_conflicts -------------------------------------------------


def test_a_workable_slot_has_no_conflicts():
    slot = TimeSlot(start=bt(5, 10), end=bt(5, 10, 30))
    assert describe_conflicts(attendees=[ALICE], busy=[], slot=slot, policy=policy()) == []


def test_a_clash_is_named():
    slot = TimeSlot(start=bt(5, 9, 30), end=bt(5, 10))
    reasons = describe_conflicts(
        attendees=[ALICE],
        busy=[BusyBlock(start=bt(5, 9), end=bt(5, 10), title="Standup")],
        slot=slot,
        policy=policy(),
    )
    assert reasons == ["conflicts with Standup"]


def test_a_slot_outside_working_hours_says_whose():
    slot = TimeSlot(start=bt(5, 10), end=bt(5, 11))
    reasons = describe_conflicts(attendees=[BOB], busy=[], slot=slot, policy=policy())
    assert len(reasons) == 1
    assert "Bob" in reasons[0]


def test_conflicts_accumulate():
    slot = TimeSlot(start=bt(7, 10), end=bt(7, 11))  # a Saturday
    reasons = describe_conflicts(
        attendees=[ALICE, BOB],
        busy=[BusyBlock(start=bt(7, 10), end=bt(7, 11), title="Weekend thing")],
        slot=slot,
        policy=policy(),
    )
    assert len(reasons) == 3  # both attendees plus the clash


# --- model guards -------------------------------------------------------


def test_a_busy_block_must_end_after_it_starts():
    with pytest.raises(ValueError, match="end after"):
        BusyBlock(start=bt(5, 10), end=bt(5, 9))


def test_touching_intervals_do_not_overlap():
    block = BusyBlock(start=bt(5, 9), end=bt(5, 10))
    assert block.overlaps(bt(5, 10), bt(5, 11)) is False
    assert block.overlaps(bt(5, 8), bt(5, 9)) is False
    assert block.overlaps(bt(5, 9, 30), bt(5, 10, 30)) is True


def test_padding_widens_a_block_on_both_sides():
    padded = BusyBlock(start=bt(5, 9), end=bt(5, 10)).padded(15)
    assert padded.start == bt(5, 8, 45)
    assert padded.end == bt(5, 10, 15)


def test_slot_duration_is_reported_in_minutes():
    assert TimeSlot(start=bt(5, 9), end=bt(5, 10, 30)).duration_minutes == 90


def test_an_unknown_time_zone_is_rejected_at_construction():
    with pytest.raises(Exception):  # noqa: B017 - zoneinfo raises its own type
        WorkingHours(timezone="Mars/Olympus_Mons")


def test_search_horizon_bounds_the_result():
    slots = find_slots(
        attendees=[ALICE],
        busy=[],
        duration_minutes=30,
        policy=policy(search_horizon_days=1, max_suggestions=5),
        now=NOW,
    )
    assert all(s.start < NOW + timedelta(days=1) for s in slots)

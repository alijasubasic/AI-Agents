"""The slot-finding engine.

This module contains no prompts, no model calls, and no randomness. Given the
same calendars it returns the same slots, every time, which is exactly what you
want from the part of a booking system that decides when a meeting happens.

The algorithm is unglamorous on purpose:

    1. Pad every busy block by the buffer, then merge the overlaps.
    2. Walk a grid of candidate start times from "earliest allowed" forward.
    3. Keep a candidate if the whole meeting fits inside every attendee's
       working day and collides with nobody.
    4. Stop once enough spread-out options have been collected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agents.calendar_booking.models import (
    Attendee,
    BusyBlock,
    SchedulingPolicy,
    TimeSlot,
)

#: Hard ceiling on grid steps, so a pathological configuration (a one-minute
#: granularity over a long horizon) cannot spin for a noticeable time.
MAX_CANDIDATES = 20_000


def merge_blocks(blocks: list[BusyBlock]) -> list[BusyBlock]:
    """Merge overlapping and touching busy blocks into a minimal set.

    Touching blocks are merged: 09:00–10:00 followed by 10:00–11:00 is one
    unavailable stretch, and treating it as two invites off-by-one mistakes
    later in the search.
    """
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda b: (b.start, b.end))
    merged = [ordered[0]]

    for block in ordered[1:]:
        last = merged[-1]
        if block.start <= last.end:
            if block.end > last.end:
                merged[-1] = BusyBlock(
                    start=last.start,
                    end=block.end,
                    title=last.title,
                )
        else:
            merged.append(block)

    return merged


def blocked_periods(busy: list[BusyBlock], policy: SchedulingPolicy) -> list[BusyBlock]:
    """Every period a meeting may not touch: busy blocks widened by the buffer."""
    return merge_blocks([block.padded(policy.buffer_minutes) for block in busy])


def _align_up(moment: datetime, minutes: int) -> datetime:
    """Round `moment` up to the next multiple of `minutes` past the hour.

    Alignment happens in UTC, which keeps candidates on clean local minutes for
    every whole-hour and half-hour offset: a 15- or 30-minute grid divides both.
    Zones at a :45 offset (Asia/Kathmandu, Pacific/Chatham) are the exception
    and land on odd local times. See this agent's README.
    """
    moment = moment.replace(second=0, microsecond=0)
    step = timedelta(minutes=minutes)
    hour_start = moment.replace(minute=0)
    elapsed = moment - hour_start

    steps = -(-elapsed // step)  # ceiling division
    return hour_start + steps * step


def find_slots(
    *,
    attendees: list[Attendee],
    busy: list[BusyBlock],
    duration_minutes: int,
    policy: SchedulingPolicy | None = None,
    now: datetime | None = None,
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> list[TimeSlot]:
    """Find meeting slots that work for everyone.

    Returns at most `policy.max_suggestions` slots, spread across days. An empty
    list means no time in the window satisfies every constraint — a normal
    answer, not an error.
    """
    if not attendees:
        raise ValueError("find_slots needs at least one attendee")

    policy = policy or SchedulingPolicy()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    duration = timedelta(minutes=duration_minutes)

    window_start = max(
        now + timedelta(hours=policy.min_notice_hours),
        (earliest or now).astimezone(UTC),
    )
    window_end = min(
        now + timedelta(days=policy.search_horizon_days),
        (latest or now + timedelta(days=policy.search_horizon_days)).astimezone(UTC),
    )
    if window_start >= window_end:
        return []

    unavailable = blocked_periods(busy, policy)
    working_hours = [attendee.working_hours for attendee in attendees]

    slots: list[TimeSlot] = []
    per_day: dict[object, int] = {}
    candidate = _align_up(window_start, policy.granularity_minutes)
    step = timedelta(minutes=policy.granularity_minutes)

    for _ in range(MAX_CANDIDATES):
        if candidate >= window_end or len(slots) >= policy.max_suggestions:
            break

        end = candidate + duration
        if end > window_end:
            break

        if not all(hours.covers(candidate, end) for hours in working_hours):
            candidate += step
            continue

        if any(block.overlaps(candidate, end) for block in unavailable):
            candidate += step
            continue

        # Group by the organiser's local date so "one per day" means one per day
        # as the organiser experiences it, not per UTC day.
        day_key = candidate.astimezone(working_hours[0].zone).date()
        if per_day.get(day_key, 0) >= policy.max_suggestions_per_day:
            candidate += step
            continue

        slots.append(TimeSlot(start=candidate, end=end))
        per_day[day_key] = per_day.get(day_key, 0) + 1
        candidate += step

    return slots


def describe_conflicts(
    *,
    attendees: list[Attendee],
    busy: list[BusyBlock],
    slot: TimeSlot,
    policy: SchedulingPolicy | None = None,
) -> list[str]:
    """Explain why a specific slot does not work. Empty means it does.

    Used when a caller asks for a slot directly rather than picking from the
    offered list — "that time is taken" is a far more useful answer than a bare
    refusal.
    """
    policy = policy or SchedulingPolicy()
    reasons: list[str] = []

    for attendee in attendees:
        if not attendee.working_hours.covers(slot.start, slot.end):
            reasons.append(
                f"outside {attendee.label}'s working hours "
                f"({slot.local(attendee.working_hours.timezone)})"
            )

    reasons.extend(
        f"conflicts with {block.title or 'an existing booking'}"
        for block in blocked_periods(busy, policy)
        if block.overlaps(slot.start, slot.end)
    )

    return reasons

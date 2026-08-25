"""The task the demo improves: routing short customer messages to a department.

Small, deterministically scorable, and chosen because the failure modes are
obvious to a reader — a billing question misrouted to sales is visible at a
glance, so the improvement is visible too.

The baseline prompt is deliberately underspecified. It names the four
departments and stops, which is roughly what a first draft looks like.
"""

from __future__ import annotations

from agents.prompt_optimizer.models import Split, TaskCase
from agents.prompt_optimizer.task import PromptTask

BASELINE_PROMPT = """\
Route the customer message to a department.

Answer with exactly one of: billing, technical, sales, other.
"""

CASES: list[TaskCase] = [
    # --- Tuning: the optimizer may see these -----------------------------
    TaskCase(
        id="t1",
        split=Split.TUNING,
        inputs="My invoice shows two charges for the same delivery.",
        expected="billing",
    ),
    TaskCase(
        id="t2",
        split=Split.TUNING,
        inputs="The scanner stopped pairing after the firmware update.",
        expected="technical",
    ),
    TaskCase(
        id="t3",
        split=Split.TUNING,
        inputs="What would 200 units of the KB-88 cost us?",
        expected="sales",
        note="Pricing on a prospective order is sales, not billing.",
    ),
    TaskCase(
        id="t4",
        split=Split.TUNING,
        inputs="Can you send me a copy of last quarter's statement?",
        expected="billing",
        note="A document about money already spent is billing.",
    ),
    TaskCase(
        id="t5",
        split=Split.TUNING,
        inputs="Do you have a distributor in Portugal?",
        expected="sales",
    ),
    TaskCase(
        id="t6",
        split=Split.TUNING,
        inputs="Our whole order arrived with the wrong cable type.",
        expected="technical",
        note="A fault with delivered goods is technical even though it began as an order.",
    ),
    TaskCase(
        id="t7",
        split=Split.TUNING,
        inputs="Please remove me from your mailing list.",
        expected="other",
    ),
    TaskCase(
        id="t8",
        split=Split.TUNING,
        inputs="We would like to extend our payment terms to 60 days.",
        expected="billing",
        note="Terms are billing; the sale itself is not in question.",
    ),
    # --- Holdout: neither the critic nor the optimizer ever sees these ---
    TaskCase(
        id="h1",
        split=Split.HOLDOUT,
        inputs="Could you quote us for a 50-seat rollout next quarter?",
        expected="sales",
    ),
    TaskCase(
        id="h2",
        split=Split.HOLDOUT,
        inputs="The credit note from March has still not appeared on our account.",
        expected="billing",
    ),
    TaskCase(
        id="h3",
        split=Split.HOLDOUT,
        inputs="Two units from the same batch are overheating.",
        expected="technical",
    ),
    TaskCase(
        id="h4",
        split=Split.HOLDOUT,
        inputs="Who should I speak to about a press enquiry?",
        expected="other",
    ),
]


def build_task() -> PromptTask:
    return PromptTask(name="department-routing", cases=CASES, baseline_prompt=BASELINE_PROMPT)

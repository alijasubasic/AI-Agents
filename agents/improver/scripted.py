"""Scripted reviewers, patches and command results for the demo.

The synthetic file below has one real bug and one real robustness gap, so the
demo has something honest to find. It is never written to disk: the whole patch
stage runs in a `MockWorkspace`.

Three outcomes are scripted, because a pipeline that only ever succeeds tells
you nothing about whether its gates work:

* **applied** — the discount bug is fixed and every gate passes.
* **reverted** — the robustness patch is written, `make test` fails, and the
  change is discarded.
* **collected** — a nit is reported and never patched.
"""

from __future__ import annotations

from agents.improver.models import FileEntry, Finding, Reviewer, Severity
from agents.improver.patcher import PatchDraft
from agents.improver.reviewers import ReviewResult
from agents.improver.workspace import CommandResult, MockWorkspace
from core.llm import MockProvider, text_response

SYNTHETIC_PATH = "core/pricing.py"

#: A small module with a genuine defect: `percent` is documented as 0-100 and
#: used as though it were 0-1, so every discount is a hundred times too large.
SYNTHETIC_SOURCE = '''"""Order pricing helpers."""

from __future__ import annotations


def apply_discount(total: float, percent: float) -> float:
    """Return `total` reduced by `percent`.

    Args:
        total: The order total.
        percent: The discount as a percentage, e.g. 15 for fifteen percent.
    """
    return total - (total * percent)


def line_total(unit_price: float, quantity: int) -> float:
    """Return the total for one order line."""
    return unit_price * quantity


def order_total(lines: list[tuple[float, int]], discount_percent: float = 0.0) -> float:
    """Return the discounted total for a whole order."""
    subtotal = sum(line_total(price, quantity) for price, quantity in lines)
    return apply_discount(subtotal, discount_percent)
'''

FIXED_SOURCE = SYNTHETIC_SOURCE.replace(
    "    return total - (total * percent)",
    "    return total - (total * percent / 100)",
)

HARDENED_SOURCE = FIXED_SOURCE.replace(
    '    """Return the total for one order line."""\n    return unit_price * quantity',
    '    """Return the total for one order line."""\n'
    "    if quantity < 0:\n"
    '        raise ValueError("quantity cannot be negative")\n'
    "    return unit_price * quantity",
)


SYNTHETIC_INDEX: list[FileEntry] = [
    FileEntry(
        path=SYNTHETIC_PATH,
        lines=len(SYNTHETIC_SOURCE.splitlines()),
        functions=["apply_discount", "line_total", "order_total"],
        imports=["__future__"],
        has_tests=False,
        priority=3.0,
        priority_reasons=["no test file"],
    )
]


# --- Findings -----------------------------------------------------------

DISCOUNT_BUG = Finding(
    reviewer=Reviewer.CORRECTNESS,
    path=SYNTHETIC_PATH,
    severity=Severity.MAJOR,
    title="Discount treats a percentage as a fraction",
    detail=(
        "The docstring says percent is 15 for fifteen percent, and the "
        "arithmetic multiplies by it directly. A 15% discount removes fifteen "
        "times the order total, so every discounted order comes out negative."
    ),
    suggestion="Divide by 100, or change the parameter to a fraction and say so.",
    anchor="return total - (total * percent)",
)

NEGATIVE_QUANTITY = Finding(
    reviewer=Reviewer.ROBUSTNESS,
    path=SYNTHETIC_PATH,
    severity=Severity.MAJOR,
    title="A negative quantity silently produces a negative line total",
    detail=(
        "line_total multiplies without checking. A negative quantity from a "
        "malformed order reduces the invoice instead of failing."
    ),
    suggestion="Raise on a negative quantity rather than returning a credit.",
    anchor="return unit_price * quantity",
)

MISSING_DOCSTRING = Finding(
    reviewer=Reviewer.READABILITY,
    path=SYNTHETIC_PATH,
    severity=Severity.NIT,
    title="order_total does not say what the discount applies to",
    detail="It is applied to the subtotal, which the docstring does not mention.",
    suggestion="Say so in the docstring.",
    anchor="subtotal = sum(line_total(price, quantity) for price, quantity in lines)",
)

#: A finding whose anchor is not in the file. Dropped by the prioritizer, which
#: is the behaviour worth showing: a reviewer quoting something that is not
#: there did not read the file carefully, and patching from it is how a working
#: function gets broken.
INVENTED = Finding(
    reviewer=Reviewer.SECURITY,
    path=SYNTHETIC_PATH,
    severity=Severity.MAJOR,
    title="Order identifiers are interpolated into a query",
    detail="Looks like string-built SQL.",
    suggestion="Use a parameterised query.",
    anchor='cursor.execute(f"SELECT * FROM orders WHERE id = {order_id}")',
)


REVIEW_RESULTS: dict[Reviewer, ReviewResult] = {
    Reviewer.CORRECTNESS: ReviewResult(findings=[DISCOUNT_BUG]),
    Reviewer.SECURITY: ReviewResult(findings=[INVENTED]),
    Reviewer.ROBUSTNESS: ReviewResult(findings=[NEGATIVE_QUANTITY]),
    Reviewer.READABILITY: ReviewResult(findings=[MISSING_DOCSTRING]),
    # An empty result is a valid answer, and a crew where one reviewer always
    # finds something is a crew nobody believes.
    Reviewer.AGENT_QUALITY: ReviewResult(findings=[]),
}


def reviewer_providers(*, model: str = "claude-opus-5") -> dict[Reviewer, MockProvider]:
    """One scripted provider per reviewer."""
    return {
        reviewer: MockProvider([text_response(result.model_dump_json())], model=model)
        for reviewer, result in REVIEW_RESULTS.items()
    }


# --- Patches ------------------------------------------------------------

PATCH_DRAFTS: list[PatchDraft] = [
    PatchDraft(
        new_contents=FIXED_SOURCE,
        changed=True,
        rationale=(
            "Divided by 100 so the parameter matches its documented meaning. "
            "Changing the parameter to a fraction instead would have been a "
            "breaking change for every caller."
        ),
        regression_test=(
            "def test_a_fifteen_percent_discount_removes_fifteen_percent():\n"
            "    assert apply_discount(200.0, 15) == 170.0\n"
        ),
    ),
    PatchDraft(
        new_contents=HARDENED_SOURCE,
        changed=True,
        rationale="Raise on a negative quantity rather than issuing a silent credit.",
        regression_test=(
            "def test_a_negative_quantity_is_refused():\n"
            "    with pytest.raises(ValueError):\n"
            "        line_total(10.0, -1)\n"
        ),
    ),
]


def patcher_provider(*, model: str = "claude-opus-5") -> MockProvider:
    return MockProvider(
        [text_response(draft.model_dump_json()) for draft in PATCH_DRAFTS], model=model
    )


# --- Workspace ----------------------------------------------------------


def workspace(run_date) -> MockWorkspace:
    """An in-memory checkout where the second patch fails its test run.

    Command results are keyed by branch, so the same `make test` passes for one
    patch and fails for another — which is what verifying each patch in
    isolation is supposed to catch.
    """
    from agents.improver.safety import branch_name

    failing_branch = branch_name(run_date, NEGATIVE_QUANTITY.title)
    return MockWorkspace(
        files={SYNTHETIC_PATH: SYNTHETIC_SOURCE},
        results={
            failing_branch: {
                "make test": CommandResult(
                    command="make test",
                    exit_code=1,
                    output=(
                        "FAILED tests/test_orders.py::test_credit_note_line\n"
                        "  line_total(10.0, -1) now raises; the credit-note path\n"
                        "  relies on negative quantities.\n"
                        "1 failed, 551 passed"
                    ),
                )
            }
        },
    )

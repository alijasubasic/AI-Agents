"""The one rule the package layout depends on.

`jarvis/*.py` is what the dashboard **knows** — the fleet, the graph, the
telemetry, the guardrails. `jarvis/ui/` is how it is **drawn**.

Dependencies run one way: the UI reads the models, and the models know nothing
about a colour, a class name or an element id. That is what makes the data
layer testable without a browser and the styling replaceable without touching
a pydantic model.

The rule is easy to break by accident — one `from jarvis.ui.theme import` in
`panels.py` to reuse a hex value and the split is gone. So it is asserted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]

#: Modules that are allowed to know about both halves. `app` wires the pieces
#: together and `demo` renders one; that is their whole job.
WIRING = {"app.py", "demo.py", "__init__.py", "__main__.py"}

#: The data layer: everything at the top of the package that is not wiring.
DATA_MODULES = sorted(path for path in PACKAGE.glob("*.py") if path.name not in WIRING)


def imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, at any depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("path", DATA_MODULES, ids=lambda p: p.name)
def test_the_data_layer_does_not_import_the_ui(path: Path):
    offenders = {name for name in imported_modules(path) if name.startswith("jarvis.ui")}
    assert offenders == set(), (
        f"{path.name} imports {sorted(offenders)}. The data layer must not know "
        "how it is drawn — move the shared value, or put the code in jarvis/ui/."
    )


def test_the_data_layer_is_not_empty():
    """Guards the guard. A glob that matches nothing passes vacuously."""
    assert {path.name for path in DATA_MODULES} >= {
        "panels.py",
        "graph.py",
        "registry.py",
        "diagnostics.py",
        "capture.py",
    }


def test_the_ui_reads_the_models_rather_than_redefining_them():
    """The dependency that *should* exist, in the direction it should run."""
    imports = imported_modules(PACKAGE / "ui" / "__init__.py")
    assert "jarvis.panels" in imports


def test_only_the_theme_writes_a_colour():
    """Every hex value lives in one file, so a restyle is one file.

    Checked across the UI package rather than promised in a docstring — the
    stylesheet is long enough that one hard-coded `#1b2029` would never be
    noticed in review.
    """
    import re

    hexes = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    offenders: dict[str, list[str]] = {}

    for path in (PACKAGE / "ui").glob("*.py"):
        if path.name == "theme.py":
            continue
        found = hexes.findall(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.name] = sorted(set(found))

    assert offenders == {}, f"hard-coded colours outside theme.py: {offenders}"


def test_the_page_template_carries_no_data():
    """The template is a skeleton. Every value arrives through the payload.

    A template that interpolated one field would need escaping rules for that
    field, and the next one would be added without them.
    """
    from jarvis.ui.layout import TEMPLATE

    slots = {"{css}", "{sphere_js}", "{app_js}", "{bootstrap}"}
    import re

    found = set(re.findall(r"\{[a-z_]+\}", TEMPLATE))
    assert found == slots, f"unexpected template slots: {sorted(found - slots)}"

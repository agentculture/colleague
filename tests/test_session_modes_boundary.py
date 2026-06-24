"""Boundary + audience guards for session modes (t5).

These tests prove the session-mode feature does not alter the classifier,
auto delegates verbatim, the TAUI mirror carries the mode for agent readers,
and the module stays stdlib-only.  Complements
tests/test_session_modes_integration.py (which covers the full session loop).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from colleague.session_intent import PLAN, WORK, classify_intent
from colleague.session_modes import route_for
from colleague.tui.render.markdown import render_markdown
from colleague.tui.state import CockpitState
from colleague.tui.taui import serialize

# ---------------------------------------------------------------------------
# 1. Classifier unchanged — modes wrap, never modify, classify_intent
# ---------------------------------------------------------------------------


def test_classifier_unchanged() -> None:
    """classify_intent still returns PLAN for a planning phrase and WORK for
    a plain task — the classifier itself was not altered by the mode feature."""
    assert classify_intent("plan this feature out") == PLAN
    assert classify_intent("add a CONTRIBUTING.md file") == WORK


# ---------------------------------------------------------------------------
# 2. Auto mode delegates verbatim to the classifier
# ---------------------------------------------------------------------------


def test_auto_mode_is_classifier_verbatim() -> None:
    """For a sample of inputs, route_for('auto', text, classify_intent) ==
    classify_intent(text) — auto delegates verbatim."""
    samples = [
        "plan this feature out",
        "add a CONTRIBUTING.md file",
        "break this down into tasks",
        "fix the login bug",
        "design a new API",
        "implement the plan",
    ]
    for text in samples:
        assert route_for("auto", text, classify_intent) == classify_intent(text)


# ---------------------------------------------------------------------------
# 3. TAUI JSON carries mode (audience: agent reads the mode as JSON)
# ---------------------------------------------------------------------------


def test_taui_json_carries_mode() -> None:
    """Build a CockpitState(mode='plan') and assert the TAUI JSON mirror and
    Markdown render both carry 'plan' — proving an agent/pipeline reads the
    same mode from the TAUI mirror."""
    state = CockpitState(mode="plan")

    # JSON mirror
    mirror = serialize(state)
    assert mirror["mode"] == "plan"

    # Markdown render
    md = render_markdown(state)
    assert "plan" in md


# ---------------------------------------------------------------------------
# 4. session_modes module is stdlib-only (zero-deps non-goal guard)
# ---------------------------------------------------------------------------


def test_session_modes_module_is_stdlib_only() -> None:
    """Assert colleague/session_modes.py imports only standard-library modules
    (no third-party import). Parse its imports with ast and check each
    top-level module name is in sys.stdlib_module_names or is 'colleague...'.
    This guards the zero-deps non-goal."""
    source_file = Path(__file__).resolve().parent.parent / "colleague" / "session_modes.py"
    tree = ast.parse(source_file.read_text())

    stdlib = sys.stdlib_module_names

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib or top.startswith(
                    "colleague"
                ), f"session_modes.py imports non-stdlib module '{alias.name}'"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                assert top in stdlib or top.startswith(
                    "colleague"
                ), f"session_modes.py imports non-stdlib module '{node.module}'"

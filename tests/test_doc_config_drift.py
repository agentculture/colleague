"""Guard against feature-doc constants drifting from ``colleague/config.py``.

Issue #225 (gap 2): a self-reflection ``ask-colleague explore`` surfaced that
``docs/features/`` had drifted from the code — ``graceful-degradation.md`` quoted
a 24,000-token default context budget (code: 192,000, an 8x error) and the
subagent docs quoted ``MAX_SUBAGENT_DEPTH=2`` (code: 4). Those are exactly the
kind of stale value that makes a *worker* mis-budget or mis-plan.

``colleague/config.py`` is the source of truth. These tests read the live
constants and assert the relevant feature docs quote the current value (and do
NOT quote the specific known-stale value), so the drift cannot silently recur.
The assertions are deliberately narrow — one constant per doc — so ordinary
prose edits don't make them flaky.
"""

from __future__ import annotations

from pathlib import Path

import colleague.config as cfg

DOCS = Path(__file__).resolve().parents[1] / "docs" / "features"


def _read(name: str) -> str:
    path = DOCS / name
    assert path.is_file(), f"expected feature doc missing: {path}"
    return path.read_text(encoding="utf-8")


def test_context_budget_default_matches_docs() -> None:
    """graceful-degradation.md must quote the live default context budget."""
    budget = cfg._DEFAULT_CONTEXT_BUDGET
    assert budget == 48000, "update this guard if the default budget changes"
    text = _read("graceful-degradation.md")
    # the current default must appear (bare or comma-grouped)
    assert str(budget) in text or f"{budget:,}" in text, (
        "graceful-degradation.md does not quote the live default context budget "
        f"({budget}); it has drifted from colleague/config.py"
    )
    # the historic 8x-wrong default must not be presented as current
    for stale in ("24,000 tokens", "24000 tokens"):
        assert stale not in text, (
            f"graceful-degradation.md still quotes the stale default {stale!r}; "
            f"the live default is {budget}"
        )


def test_subagent_depth_matches_docs() -> None:
    """The subagent feature docs must quote the live MAX_SUBAGENT_DEPTH."""
    depth = cfg.MAX_SUBAGENT_DEPTH
    assert depth == 4, "update this guard if the recursion cap changes"
    for name in ("subagents.md", "parallel-subagents.md"):
        text = _read(name)
        assert "MAX_SUBAGENT_DEPTH=4" in text or "DEPTH` | 4 " in text, (
            f"{name} does not quote the live MAX_SUBAGENT_DEPTH ({depth}); "
            "it has drifted from colleague/config.py"
        )
        # the old depth-2 claim must not survive as the stated cap
        assert (
            "MAX_SUBAGENT_DEPTH=2" not in text and "DEPTH` | 2 " not in text
        ), f"{name} still quotes the stale recursion cap of 2; the live cap is {depth}"

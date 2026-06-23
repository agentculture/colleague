"""Feed-grouping tests (#233): consecutive identical cockpit feed lines collapse to
``<line> ×N`` instead of stacking duplicate ``[culture]`` lines.

Driven through the pure reducer so the grouping holds identically live, in
``tui replay``, and in a snapshot — the same single-source guarantee the rest of
the cockpit relies on.
"""

from __future__ import annotations

from colleague.tui.events import WorkStep
from colleague.tui.reducer import reduce
from colleague.tui.state import CockpitState, Panel

_CONV = "panel.conversation"


def _conversation(state: CockpitState) -> str:
    panel = next((p for p in state.panels if p.id == _CONV), None)
    return panel.content_summary if panel else ""


def _blank() -> CockpitState:
    return CockpitState(panels=[Panel(id=_CONV, title="Conversation", visible=True)])


def _step(tool: str, target: str) -> WorkStep:
    return WorkStep(tool=tool, summary=target, ok=True)


def test_consecutive_identical_lines_collapse_to_count() -> None:
    """Four identical culture steps render as one ``×4`` line, not four lines."""
    state = _blank()
    for _ in range(4):
        state = reduce(state, _step("culture", "agtag issues"))
    conv = _conversation(state)
    assert conv == "[culture] agtag issues ×4", conv
    assert conv.count("\n") == 0, "the four repeats must be a single grouped line"


def test_distinct_lines_are_not_grouped() -> None:
    """Different targets stay on their own lines."""
    state = _blank()
    state = reduce(state, _step("list_dir", "."))
    state = reduce(state, _step("list_dir", "spark"))
    conv = _conversation(state)
    assert conv == "[list_dir] .\n[list_dir] spark", conv


def test_grouping_only_collapses_consecutive_runs() -> None:
    """An intervening different line starts a fresh run — a later repeat of the
    first line is NOT folded back into the earlier group."""
    state = _blank()
    state = reduce(state, _step("culture", "agtag issues"))
    state = reduce(state, _step("culture", "agtag issues"))
    state = reduce(state, _step("read_file", "README.md"))
    state = reduce(state, _step("culture", "agtag issues"))
    conv = _conversation(state)
    assert conv == "[culture] agtag issues ×2\n[read_file] README.md\n[culture] agtag issues", conv


def test_run_of_three_increments_existing_count() -> None:
    """A third identical line bumps an existing ×2 to ×3 (not ×2 ×2)."""
    state = _blank()
    for _ in range(3):
        state = reduce(state, _step("run_command", "pytest -q"))
    assert _conversation(state) == "[run_command] pytest -q ×3"


def test_step_count_still_counts_every_step() -> None:
    """Grouping is display-only: each grouped step still advances the work-item
    step counter (the four repeats are four real actions)."""
    from colleague.tui.state import WorkItem

    state = CockpitState(
        panels=[Panel(id=_CONV, title="Conversation", visible=True)],
        work_item=WorkItem(task_id="t", engine="mock", running=True),
    )
    for _ in range(4):
        state = reduce(state, _step("culture", "agtag issues"))
    assert state.work_item is not None
    assert state.work_item.step_count == 4
    assert _conversation(state) == "[culture] agtag issues ×4"

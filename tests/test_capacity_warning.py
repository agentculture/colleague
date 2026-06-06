"""Warn-only "too big for one repo" caller warning (#156, t7).

Covers plan targets c13/h6/h9: when the up-front capacity assessment judges an
assignment to exceed even the in-repo split capacity, the runtime sets a
caller-visible ``capacity_warning`` (recorded in the artifact) that names the
cross-repo/instance split — and a normal-sized assignment leaves it unset
(byte-identical, omitted from the artifact). Colleague performs NO cross-repo write.
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_SYS = "You are a test coding agent."


def _finish(messages):
    return ModelResponse(
        content="done",
        tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
        prompt_tokens=5,
        completion_tokens=1,
    )


def _run(task, **kwargs):
    cc = ContextControls(budget=kwargs.pop("budget", 100))
    return run(_finish, task, context=cc, system_prompt=_SYS, max_steps=5, **kwargs)


def test_over_split_capacity_warns_caller(tmp_path: Path) -> None:
    """An assignment past the split capacity sets a cross-repo warning on the result
    and records it in the artifact (#156, c13/h6)."""
    # budget=100 → over_split when instruction tokens > 400; 2000 chars ~= 500 tokens.
    task = Task.new(str(tmp_path), "x" * 2000, engine="mock")
    result = _run(task, budget=100)

    assert result.status == OK
    assert result.capacity_warning is not None
    lowered = result.capacity_warning.lower()
    assert "repositor" in lowered or "instances" in lowered  # names the cross-repo split
    assert "warn-only" in lowered
    # Recorded in the artifact (the caller reads it there too).
    assert "capacity_warning" in result.to_dict()


def test_normal_assignment_no_warning(tmp_path: Path) -> None:
    """A normal-sized assignment leaves capacity_warning unset and omitted (#156)."""
    task = Task.new(str(tmp_path), "add a small helper", engine="mock")
    result = _run(task, budget=100)

    assert result.status == OK
    assert result.capacity_warning is None
    assert "capacity_warning" not in result.to_dict()


def test_warning_dormant_without_budget(tmp_path: Path) -> None:
    """With degradation off (no budget), the assessment does not run — no warning."""
    task = Task.new(str(tmp_path), "x" * 5000, engine="mock")
    result = run(
        _finish, task, context=ContextControls(budget=None), system_prompt=_SYS, max_steps=5
    )

    assert result.status == OK
    assert result.capacity_warning is None

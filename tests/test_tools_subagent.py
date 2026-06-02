"""Tests for the ``subagent`` tool surface in :mod:`colleague.tools`.

Acceptance criteria (task t4):
1. SCHEMAS and TOOL_NAMES include a ``subagent`` function with required
   ``instruction`` and optional ``engine``/``model``.
2. ``colleague/tools.py`` imports NOTHING from ``colleague/engines/``,
   ``colleague.registry``, ``colleague.loop``, or ``colleague.subagents``.
3. A ``ToolExecutor`` with no spawn callback raises ``ToolError`` when asked to
   run ``subagent`` — never raises something else.
4. With an injected fake spawn callback: ``execute("subagent", ...)`` returns a
   ToolOutcome whose result contains the child summary; ``executor.sub_results``
   records the entry; ``changed_files`` from the child are merged into
   ``executor.changed``; fan-out beyond ``MAX_SUBAGENT_FANOUT`` raises
   ``ToolError``.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Optional

import pytest

from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.contract import SubResult
from colleague.tools import SCHEMAS, TOOL_NAMES, ToolError, ToolExecutor, ToolOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOOLS_PY = pathlib.Path(__file__).parent.parent / "colleague" / "tools.py"


def _fake_sub(
    task_id="s1", engine="mock", model="m", status="ok", summary="did it", changed_files=None
) -> SubResult:
    return SubResult(
        task_id=task_id,
        engine=engine,
        model=model,
        status=status,
        summary=summary,
        changed_files=list(changed_files or ["a.py"]),
    )


def _make_spawn(sub: Optional[SubResult] = None, exc: Optional[Exception] = None):
    """Return a fake spawn callable that either returns ``sub`` or raises ``exc``."""
    if exc is not None:

        def spawn(instruction: str, engine=None, model=None):
            raise exc

    else:
        s = sub or _fake_sub()

        def spawn(instruction: str, engine=None, model=None):
            return s

    return spawn


# ---------------------------------------------------------------------------
# AC1 — schema presence
# ---------------------------------------------------------------------------


def test_subagent_in_schemas():
    names = [s["function"]["name"] for s in SCHEMAS]
    assert "subagent" in names, "SCHEMAS must include a 'subagent' function"


def test_subagent_in_tool_names():
    assert "subagent" in TOOL_NAMES, "TOOL_NAMES must include 'subagent'"


def test_subagent_schema_required_instruction():
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")
    fn = schema["function"]
    assert (
        "instruction" in fn["parameters"]["required"]
    ), "'instruction' must be a required parameter of the subagent schema"


def test_subagent_schema_optional_engine_and_model():
    schema = next(s for s in SCHEMAS if s["function"]["name"] == "subagent")
    props = schema["function"]["parameters"]["properties"]
    assert "engine" in props, "'engine' must be a parameter of the subagent schema"
    assert "model" in props, "'model' must be a parameter of the subagent schema"
    # They must NOT appear in 'required'
    required = schema["function"]["parameters"].get("required", [])
    assert "engine" not in required, "'engine' must be optional (not in 'required')"
    assert "model" not in required, "'model' must be optional (not in 'required')"


# ---------------------------------------------------------------------------
# AC2 — forbidden imports
# ---------------------------------------------------------------------------


def test_tools_py_no_forbidden_imports():
    """Parse colleague/tools.py and assert no import touches the banned modules."""
    source = _TOOLS_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_TOOLS_PY))

    forbidden_prefixes = (
        "colleague.engines",
        "colleague.registry",
        "colleague.loop",
        "colleague.subagents",
    )
    forbidden_partial = (
        "colleague/engines",
        "colleague/registry",
        "colleague/loop",
        "colleague/subagents",
    )

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Build a dotted module string for ImportFrom
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not (
                        mod == prefix or mod.startswith(prefix + ".")
                    ), f"tools.py must not import from '{prefix}' (found: '{mod}')"
            # Handle plain 'import x.y'
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not (alias.name == prefix or alias.name.startswith(prefix + ".")), (
                            f"tools.py must not import '{prefix}' " f"(found: '{alias.name}')"
                        )

    # Belt-and-suspenders: also scan raw source for the forbidden identifiers
    for partial in forbidden_partial:
        # Skip lines that are comments
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if partial in line and ("import" in line):
                pytest.fail(
                    f"tools.py contains a suspicious import referencing '{partial}': {line!r}"
                )


# ---------------------------------------------------------------------------
# AC3 — no spawn → ToolError, not a crash
# ---------------------------------------------------------------------------


def test_subagent_no_spawn_raises_tool_error(tmp_path):
    executor = ToolExecutor(tmp_path)
    with pytest.raises(ToolError, match="not available"):
        executor.execute("subagent", {"instruction": "x"})


def test_subagent_no_spawn_no_other_exception(tmp_path):
    """Ensure it raises ToolError specifically, not KeyError or AttributeError."""
    executor = ToolExecutor(tmp_path)
    try:
        executor.execute("subagent", {"instruction": "x"})
    except ToolError:
        pass  # expected
    except Exception as exc:
        pytest.fail(f"Expected ToolError, got {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# AC4 — injected fake spawn
# ---------------------------------------------------------------------------


def test_subagent_returns_tool_outcome(tmp_path):
    sub = _fake_sub(summary="did it", engine="mock", model="m", changed_files=["a.py"])
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    outcome = executor.execute("subagent", {"instruction": "x"})
    assert isinstance(outcome, ToolOutcome)


def test_subagent_outcome_contains_child_summary(tmp_path):
    sub = _fake_sub(summary="did it", engine="mock", model="m", changed_files=["a.py"])
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    outcome = executor.execute("subagent", {"instruction": "x"})
    assert "did it" in outcome.result


def test_subagent_records_sub_result(tmp_path):
    sub = _fake_sub()
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    executor.execute("subagent", {"instruction": "x"})
    assert len(executor.sub_results) == 1
    assert executor.sub_results[0] is sub


def test_subagent_merges_changed_files(tmp_path):
    sub = _fake_sub(changed_files=["a.py"])
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    executor.execute("subagent", {"instruction": "x"})
    assert "a.py" in executor.changed


def test_subagent_merges_multiple_changed_files(tmp_path):
    sub = _fake_sub(changed_files=["x.py", "y.py", "z.py"])
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    executor.execute("subagent", {"instruction": "x"})
    assert {"x.py", "y.py", "z.py"} <= executor.changed


def test_subagent_outcome_no_changed_file_field(tmp_path):
    """The per-tool changed_file= on ToolOutcome should NOT be set for subagent."""
    sub = _fake_sub(changed_files=["a.py"])
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    outcome = executor.execute("subagent", {"instruction": "x"})
    assert outcome.changed_file is None


# ---------------------------------------------------------------------------
# Fan-out cap
# ---------------------------------------------------------------------------


def test_subagent_fanout_cap(tmp_path):
    """Calling subagent more than MAX_SUBAGENT_FANOUT times raises ToolError."""
    sub = _fake_sub()
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))

    # Fill up to the cap
    for _ in range(MAX_SUBAGENT_FANOUT):
        executor.execute("subagent", {"instruction": "x"})

    # The next call (index == MAX_SUBAGENT_FANOUT) must be refused
    with pytest.raises(ToolError, match="fan-out limit"):
        executor.execute("subagent", {"instruction": "one too many"})


def test_subagent_fanout_at_cap_ok(tmp_path):
    """Exactly MAX_SUBAGENT_FANOUT calls should all succeed."""
    sub = _fake_sub()
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    for i in range(MAX_SUBAGENT_FANOUT):
        outcome = executor.execute("subagent", {"instruction": f"step {i}"})
        assert isinstance(outcome, ToolOutcome)


# ---------------------------------------------------------------------------
# Callback exception conversion
# ---------------------------------------------------------------------------


def test_subagent_launcher_exception_converted_to_tool_error(tmp_path):
    """Any exception from the spawn callback is converted to ToolError."""
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(exc=RuntimeError("boom")))
    with pytest.raises(ToolError, match="subagent failed"):
        executor.execute("subagent", {"instruction": "x"})


def test_subagent_tool_error_from_callback_propagated(tmp_path):
    """A ToolError raised by the callback propagates as-is (re-raised)."""
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(exc=ToolError("inner tool error")))
    with pytest.raises(ToolError, match="inner tool error"):
        executor.execute("subagent", {"instruction": "x"})


# ---------------------------------------------------------------------------
# Missing / bad instruction
# ---------------------------------------------------------------------------


def test_subagent_missing_instruction_raises_tool_error(tmp_path):
    sub = _fake_sub()
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    with pytest.raises(ToolError, match="instruction"):
        executor.execute("subagent", {})


def test_subagent_empty_instruction_raises_tool_error(tmp_path):
    sub = _fake_sub()
    executor = ToolExecutor(tmp_path, spawn=_make_spawn(sub))
    with pytest.raises(ToolError, match="instruction"):
        executor.execute("subagent", {"instruction": ""})


# ---------------------------------------------------------------------------
# ToolExecutor backward-compat: keyword-only spawn
# ---------------------------------------------------------------------------


def test_tool_executor_spawn_keyword_only(tmp_path):
    """spawn is keyword-only so existing ToolExecutor(root) callers keep working."""
    # This must not raise TypeError
    executor = ToolExecutor(tmp_path)
    assert executor._spawn is None


def test_tool_executor_spawn_positional_raises(tmp_path):
    """Passing spawn positionally must raise TypeError (keyword-only enforcement)."""
    with pytest.raises(TypeError):
        ToolExecutor(tmp_path, _make_spawn())  # type: ignore[call-arg]


def test_tool_executor_sub_results_initialised_empty(tmp_path):
    executor = ToolExecutor(tmp_path)
    assert executor.sub_results == []


def test_tool_executor_sub_results_initialised_empty_with_spawn(tmp_path):
    executor = ToolExecutor(tmp_path, spawn=_make_spawn())
    assert executor.sub_results == []

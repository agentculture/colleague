"""Purpose-tool executor wiring (purpose-tools-associate-seat, plan task t6).

Covers the t6 acceptance criteria (spec c3/c28/c34/c40, honesty h3/h26/h30/h33):

1. :func:`colleague.purpose_schemas.dispatch` binds a handler per purpose name,
   and each handler spawns with the FIXED ``role`` (:data:`PURPOSE_ROLE`), the
   FIXED rung (:data:`colleague.efforttables.PURPOSE_TABLE`) and the FIXED step
   budget (:data:`colleague.efforttables.PURPOSE_STEPS`) — the model never picks
   any of the three.
2. A parent seat override (``reasoning_effort_seats={'cortex': 'medium'}``) does
   NOT leak into the purpose child: ``review`` still runs at ``low``,
   ``code_survey`` at ``off`` (the purpose row is an explicit spawn override, the
   highest-precedence input in :func:`colleague.effort.resolve_effort`).
3. The arithmetic exemption (c34): a READ-ONLY purpose does not charge the
   global agent budget (25 sequential ``code_survey`` calls all run), while
   ``handover_to_colleague`` — the writer purpose — does, and a depth/total
   refusal comes back as the tool RESULT text, never as an exception.
4. A child that comes back non-``ok`` is reported with a NON-empty
   ``[purpose budget exhausted: N steps]`` marker plus its partial.
5. The child runs through :func:`colleague.subagents.run_subagent` unchanged;
   ``handover_to_colleague``'s ``changed_files`` reach the parent's changed set
   and its ``SubResult`` lands on ``executor.sub_results`` exactly as the
   ``subagent`` tool does; the child's served model + id land on the parent's
   ``Step.arguments`` so ``scripts/compare_arms.py`` can count purpose steps.
6. ``colleague/purpose_schemas.py`` imports no worktree/subprocess machinery
   (grep guard) and manual ``subagent`` delegation stays byte-identical
   (``ChildSpec.charges_budget`` defaults to ``True``).
"""

from __future__ import annotations

import pathlib
from typing import Any, Optional

import pytest

from colleague import purpose_schemas, subagents
from colleague.config import MAX_SUBAGENT_DEPTH, EngineConfig
from colleague.contract import INCOMPLETE, OK, SubResult, Task, TaskResult
from colleague.efforttables import PURPOSE_STEPS, PURPOSE_TABLE
from colleague.purpose_schemas import PURPOSE_ROLE, PURPOSE_TOOL_NAMES
from colleague.subagents import ChildSpec, make_spawn, new_agent_budget
from colleague.tools import ToolExecutor

_PURPOSE_PY = pathlib.Path(__file__).parent.parent / "colleague" / "purpose_schemas.py"

#: A minimal valid argument set per purpose (the schema's required keys).
_ARGS: dict[str, dict[str, Any]] = {
    "web_survey": {"question": "what changed upstream?"},
    "code_survey": {"question": "where is the loop?"},
    "review": {"diff_ref": "HEAD~1"},
    "validate": {"scope": "tests/test_x.py"},
    "plan": {"goal": "ship the thing"},
    "handover_to_colleague": {"task": "add a flag"},
}


class _Recorder:
    """A fake spawn callable that records every keyword it was handed."""

    def __init__(self, sub: Optional[SubResult] = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.sub = sub or SubResult(
            task_id="child-1",
            engine="mock",
            model="m",
            status=OK,
            summary="child summary",
            changed_files=["a.py"],
        )

    def __call__(self, instruction: str, **kwargs: Any) -> SubResult:
        self.calls.append({"instruction": instruction, **kwargs})
        return self.sub


def _executor(tmp_path, spawn) -> ToolExecutor:
    return ToolExecutor(tmp_path, spawn=spawn)


# ---------------------------------------------------------------------------
# AC1 — dispatch binds the six handlers with fixed role / rung / step budget
# ---------------------------------------------------------------------------


def test_dispatch_binds_every_purpose_name(tmp_path) -> None:
    handlers = purpose_schemas.dispatch(_executor(tmp_path, _Recorder()))
    assert set(handlers) == set(PURPOSE_TOOL_NAMES)


@pytest.mark.parametrize("name", PURPOSE_TOOL_NAMES)
def test_purpose_spawn_uses_fixed_role_rung_and_steps(tmp_path, name: str) -> None:
    rec = _Recorder()
    ex = _executor(tmp_path, rec)
    ex.execute(name, dict(_ARGS[name]))

    assert len(rec.calls) == 1
    call = rec.calls[0]
    assert call["role"] == PURPOSE_ROLE[name]
    assert call["effort"] == PURPOSE_TABLE[name]
    assert call["max_steps"] == PURPOSE_STEPS[name]
    # The model never picks a backend or a model id.
    assert call["engine"] is None
    assert call["model"] is None
    # The brief is the fixed template, rendered with the model's arguments.
    assert call["instruction"] == purpose_schemas.brief_for(name, _ARGS[name])


@pytest.mark.parametrize("name", PURPOSE_TOOL_NAMES)
def test_only_the_writer_purpose_charges_the_budget(tmp_path, name: str) -> None:
    rec = _Recorder()
    _executor(tmp_path, rec).execute(name, dict(_ARGS[name]))
    expected = name == "handover_to_colleague"
    assert rec.calls[0]["charges_budget"] is expected
    assert purpose_schemas.charges_budget(name) is expected


@pytest.mark.parametrize("name", PURPOSE_TOOL_NAMES)
def test_missing_required_argument_is_a_clean_tool_error(tmp_path, name: str) -> None:
    from colleague.tools import ToolError

    rec = _Recorder()
    with pytest.raises(ToolError):
        _executor(tmp_path, rec).execute(name, {})
    assert rec.calls == []  # refused BEFORE any spawn


# ---------------------------------------------------------------------------
# AC2 — a parent seat override never leaks into the purpose child's rung
# ---------------------------------------------------------------------------


class _CapturingEngine:
    """A fake engine that records the child config and returns a canned result."""

    def __init__(self, status: str = OK, changed: Optional[list] = None) -> None:
        self.configs: list[Any] = []
        self.status = status
        self.changed = list(changed or [])

    def work(self, task: Task, config: Any) -> TaskResult:
        self.configs.append(config)
        return TaskResult(
            task_id=task.id,
            status=self.status,
            summary="child partial" if self.status != OK else "child done",
            changed_files=list(self.changed),
        )


@pytest.fixture()
def capturing_engine(monkeypatch):
    """Replace the child engine registry lookup with a recording fake."""

    def _install(engine: _CapturingEngine) -> _CapturingEngine:
        monkeypatch.setattr(subagents.registry, "load", lambda _name: engine)
        return engine

    return _install


@pytest.mark.parametrize(
    ("name", "expected"),
    [("review", "low"), ("code_survey", "off"), ("plan", "medium")],
)
def test_parent_seat_medium_does_not_leak_into_the_purpose_child(
    tmp_path, capturing_engine, name: str, expected: str
) -> None:
    eng = capturing_engine(_CapturingEngine())
    parent = EngineConfig.resolve()
    parent.reasoning_effort_seats = {"cortex": "medium"}
    spawn = make_spawn(str(tmp_path), parent, "mock")

    _executor(tmp_path, spawn).execute(name, dict(_ARGS[name]))

    assert len(eng.configs) == 1
    assert getattr(eng.configs[0], "reasoning_effort_seat", None) == expected
    assert eng.configs[0].max_steps == PURPOSE_STEPS[name]


def test_handover_rides_the_callers_step_budget(tmp_path, capturing_engine) -> None:
    """``PURPOSE_STEPS['handover_to_colleague']`` is ``None`` — no distinct cap."""
    eng = capturing_engine(_CapturingEngine())
    parent = EngineConfig.resolve()
    parent.max_steps = 37
    spawn = make_spawn(str(tmp_path), parent, "mock")

    _executor(tmp_path, spawn).execute("handover_to_colleague", {"task": "do it"})

    assert eng.configs[0].max_steps == 37


# ---------------------------------------------------------------------------
# AC3 — the arithmetic exemption (c34)
# ---------------------------------------------------------------------------


def test_read_only_purposes_do_not_charge_the_global_budget(tmp_path, capturing_engine) -> None:
    """25 sequential ``code_survey`` calls all run — MAX_SUBAGENT_TOTAL is 24."""
    eng = capturing_engine(_CapturingEngine())
    parent = EngineConfig.resolve()
    budget = new_agent_budget(parent)
    spawn = make_spawn(str(tmp_path), parent, "mock", counter=budget)
    ex = _executor(tmp_path, spawn)

    for i in range(25):
        outcome = ex.execute("code_survey", {"question": f"q{i}"})
        assert "budget" not in outcome.result.lower(), outcome.result

    assert len(eng.configs) == 25
    assert budget.count == 0  # nothing charged


def test_handover_charges_the_global_budget_and_refusal_is_the_tool_result(
    tmp_path, capturing_engine
) -> None:
    capturing_engine(_CapturingEngine())
    parent = EngineConfig.resolve()
    parent.subagent_total = 2
    budget = new_agent_budget(parent)
    spawn = make_spawn(str(tmp_path), parent, "mock", counter=budget)
    ex = _executor(tmp_path, spawn)

    for _ in range(2):
        ex.execute("handover_to_colleague", {"task": "work"})
    assert budget.count == 2

    outcome = ex.execute("handover_to_colleague", {"task": "one too many"})
    assert "global agent budget" in outcome.result
    assert budget.count == 2  # a refused charge never bumps the counter


def test_depth_refusal_is_the_tool_result_not_an_exception(tmp_path, capturing_engine) -> None:
    capturing_engine(_CapturingEngine())
    parent = EngineConfig.resolve()
    spawn = make_spawn(str(tmp_path), parent, "mock", depth=MAX_SUBAGENT_DEPTH + 1)

    outcome = _executor(tmp_path, spawn).execute("handover_to_colleague", {"task": "deep"})
    assert "depth limit" in outcome.result


def test_manual_subagent_still_charges_the_budget(tmp_path, capturing_engine) -> None:
    """Byte-identical manual delegation: ``ChildSpec.charges_budget`` defaults True."""
    assert ChildSpec().charges_budget is True

    capturing_engine(_CapturingEngine())
    parent = EngineConfig.resolve()
    budget = new_agent_budget(parent)
    spawn = make_spawn(str(tmp_path), parent, "mock", counter=budget)
    _executor(tmp_path, spawn).execute("subagent", {"instruction": "do a thing"})
    assert budget.count == 1


# ---------------------------------------------------------------------------
# AC4 — the budget-exhausted marker
# ---------------------------------------------------------------------------


def test_budget_exhausted_marker_carries_the_partial(tmp_path) -> None:
    rec = _Recorder(
        SubResult(
            task_id="c9",
            engine="mock",
            model="m",
            status=INCOMPLETE,
            summary="found three call sites so far",
        )
    )
    outcome = _executor(tmp_path, rec).execute("code_survey", {"question": "where?"})

    assert outcome.result.startswith(f"[purpose budget exhausted: {PURPOSE_STEPS['code_survey']}")
    assert "found three call sites so far" in outcome.result


def test_budget_exhausted_marker_is_never_empty(tmp_path) -> None:
    rec = _Recorder(SubResult(task_id="c9", engine="mock", model="m", status="error", summary=""))
    outcome = _executor(tmp_path, rec).execute("review", {"diff_ref": "HEAD"})
    assert outcome.result.strip()
    assert outcome.result.startswith("[purpose budget exhausted:")


def test_ok_child_has_no_marker(tmp_path) -> None:
    outcome = _executor(tmp_path, _Recorder()).execute("review", {"diff_ref": "HEAD"})
    assert "budget exhausted" not in outcome.result
    assert "child summary" in outcome.result


# ---------------------------------------------------------------------------
# AC5 — parent bookkeeping: sub_results, changed files, served model on the Step
# ---------------------------------------------------------------------------


def test_handover_changed_files_reach_the_parent(tmp_path) -> None:
    rec = _Recorder(
        SubResult(
            task_id="c1",
            engine="mock",
            model="m",
            status=OK,
            summary="landed",
            changed_files=["src/a.py", "src/b.py"],
        )
    )
    ex = _executor(tmp_path, rec)
    ex.execute("handover_to_colleague", {"task": "add a flag"})

    assert ex.changed == {"src/a.py", "src/b.py"}
    assert len(ex.sub_results) == 1
    assert ex.sub_results[0].task_id == "c1"


def test_served_model_and_child_id_land_on_the_step_arguments(tmp_path) -> None:
    """``scripts/compare_arms.py`` reads ``Step.arguments['served_model']``."""
    rec = _Recorder()
    arguments = {"question": "where?"}
    _executor(tmp_path, rec).execute("code_survey", arguments)

    assert arguments["served_model"] == "m"
    assert arguments["purpose_child_id"] == "child-1"


def test_resolved_model_wins_as_the_served_model(tmp_path) -> None:
    rec = _Recorder(
        SubResult(
            task_id="c2",
            engine="mock",
            model="parent-main",
            status=OK,
            summary="ok",
            resolved_model="qwen-scout-3b",
        )
    )
    arguments = {"question": "where?"}
    _executor(tmp_path, rec).execute("code_survey", arguments)
    assert arguments["served_model"] == "qwen-scout-3b"


def test_no_spawn_available_is_a_clean_tool_error(tmp_path) -> None:
    from colleague.tools import ToolError

    with pytest.raises(ToolError):
        ToolExecutor(tmp_path).execute("code_survey", {"question": "q"})


# ---------------------------------------------------------------------------
# AC6 — the grep guard
# ---------------------------------------------------------------------------


def test_purpose_schemas_imports_no_worktree_or_subprocess_machinery() -> None:
    source = _PURPOSE_PY.read_text(encoding="utf-8")
    for banned in ("import subprocess", "colleague.worktrees", "from colleague import worktrees"):
        assert banned not in source, f"purpose_schemas.py must not reference {banned!r}"


# ---------------------------------------------------------------------------
# AC5 (e2e) — the child runs through run_subagent on the REAL mock engine and
# leaves no sub/<id> worktree or branch behind.
# ---------------------------------------------------------------------------


def _git_repo(tmp_path) -> pathlib.Path:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True, capture_output=True)
    return repo


def _scripted(turns):
    state = {"i": 0}

    def complete(_messages):
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def test_e2e_mock_purpose_child_runs_and_leaves_no_worktree(tmp_path) -> None:
    """A scripted mock parent calling ``code_survey`` + ``handover_to_colleague``.

    Both children run through :func:`colleague.subagents.run_subagent` on the
    REAL mock engine; the writer child's changed files reach the parent, both
    ``SubResult``s land on the parent, and no ``sub/<id>`` worktree or branch
    survives the run (the single-child path never creates one; the batch path
    is what owns ``sub/<id>`` — pinned here so a future change that starts
    creating one must also remove it).
    """
    import subprocess

    from colleague.engines import mock as mock_mod
    from colleague.loop import ModelResponse, Spawns, ToolCall, run

    repo = _git_repo(tmp_path)
    config = EngineConfig.resolve()
    task = Task.new(str(repo), "parent task", engine="mock")
    spawn = make_spawn(str(repo), config, "mock")

    parent = _scripted(
        [
            ModelResponse(
                tool_calls=[ToolCall("p-1", "code_survey", {"question": "where is the loop?"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall("p-2", "handover_to_colleague", {"task": "write the marker file"})
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("p-3", "finish", {"summary": "delegated and done"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )

    result = run(parent, task, max_steps=10, spawns=Spawns(single=spawn))

    assert result.status == OK
    assert [s.tool for s in result.steps][:2] == ["code_survey", "handover_to_colleague"]
    assert len(result.sub_results) == 2
    assert {s.engine for s in result.sub_results} == {"mock"}
    # The writer child's changed files reach the parent's changed-file set.
    assert mock_mod.OUTPUT_FILE in result.changed_files
    # The served model + child id are on the parent's Step arguments (t9).
    for step in result.steps[:2]:
        assert step.arguments["served_model"]
        assert step.arguments["purpose_child_id"]

    # No sub/<id> branch and no leftover worktree.
    branches = subprocess.run(
        ["git", "branch", "--list", "sub/*"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert branches.strip() == ""
    worktrees = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert len(worktrees.strip().splitlines()) == 1


def test_all_engines_same_sub_results_shape(tmp_path, capturing_engine) -> None:
    """All-engines rule: a purpose child's serialized shape is engine-independent."""
    shapes = []
    for engine in ("mock", "vllm-openai"):
        capturing_engine(_CapturingEngine())
        parent = EngineConfig.resolve()
        spawn = make_spawn(str(tmp_path), parent, engine)
        ex = _executor(tmp_path, spawn)
        ex.execute("review", {"diff_ref": "HEAD~1"})
        shapes.append(ex.sub_results[0].to_dict())

    assert set(shapes[0]) == set(shapes[1])
    assert shapes[0]["engine"] == "mock" and shapes[1]["engine"] == "vllm-openai"

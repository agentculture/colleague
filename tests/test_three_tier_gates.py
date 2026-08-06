"""Structural gates for the three-tier-execution arc, pinned in ONE place
(plan task t12: docs/plans/2026-08-05-three-tier-execution.md, covers c11,
h11, c17, h14, c21, h18; instruction: "Tests + CI wiring only — no production
code. This is the audience pin (c17/h14): legacy operators, agent callers,
--json/piped fronts, resident all observe zero change.").

Every guarantee below is ALSO exercised, less centrally, by
``tests/test_config_worker.py`` (t3), ``tests/test_finish_states.py`` /
``tests/test_finishstate.py`` (t1), and ``tests/test_e2e_mock.py``'s
byte-identical shape pins. This module deliberately does NOT import from
those files: the point of a dedicated, NAMED gate suite is that it keeps
asserting the arc's structural guarantees even if those scattered tests are
later refactored, renamed, or trimmed. Some duplication with them is the
entire point, not an oversight.

Four gates, one per acceptance criterion / honesty condition group:

1. BYTE-IDENTICAL (c11/h11, c17/h14) — with NO three-tier configuration, a
   full mock-engine AND (mocked-HTTP) vllm-openai work item stays behavior +
   existing-field identical, gaining ONLY the one sanctioned addition
   (``finish_states``, decision c30); the resolved ``EngineConfig`` reports
   ``three_tier is False`` and carries no ``worker``/``deepthink`` keys.
2. LOUD REFUSAL (c21, first half) — three-tier armed with no worker
   resolvable refuses via ``CliError`` naming the gap, on BOTH the
   ``work`` and ``session`` CLI fronts.
3. FINISH-STATE DISTINGUISHABILITY (c21, second half) — the five
   ``FINISH_*`` states are distinct, and a clean mock run's artifact carries
   a ``deliberate`` finish state.
4. CI PRESENCE (c17/h14, c21/h18) — this module itself carries no skip
   marker / env gate, so gates 1-3 always run in the default ``pytest`` job.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Iterator

import pytest

from colleague import registry
from colleague.cli._errors import CliError
from colleague.config import EngineConfig
from colleague.contract import (
    FINISH_DELIBERATE,
    FINISH_EMPTY,
    FINISH_STATES,
    FINISH_STOPPED,
    FINISH_TIMEOUT,
    FINISH_TRUNCATED,
    NO_RESULT_PRODUCED,
    OK,
    Task,
)
from colleague.engines import vllm_openai
from colleague.finishstate import classify_finish_state

# ---------------------------------------------------------------------------
# Shared fixtures: a hermetic, no-three-tier-config environment.
#
# Mirrors tests/test_config_worker.py's env/home isolation stance (kept
# local/independent rather than imported — see the module docstring).
# ---------------------------------------------------------------------------

_ALL_ENV = (
    "COLLEAGUE_LOBES_URL",
    "CONVERTIBLE_LOBES_URL",
    "COLLEAGUE_BASE_URL",
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "COLLEAGUE_API_KEY",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_MODEL",
    "COLLEAGUE_THREE_TIER",
    "COLLEAGUE_WORKER_API_KEY",
    "COLLEAGUE_DEEPTHINK_MODEL",
    "CONVERTIBLE_DEEPTHINK_MODEL",
    "COLLEAGUE_ENGINE",
    "COLLEAGUE_SESSION_ENGINE",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    # Prevent a real ~/.colleague/config.json (e.g. an operator's own lobes
    # default) from leaking three-tier config into the "no config" baseline.
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


# ---------------------------------------------------------------------------
# Gate 1: BYTE-IDENTICAL (c11/h11, c17/h14).
# ---------------------------------------------------------------------------

# The TaskResult key set BEFORE this arc (plan task t1 is the one that first
# touched this shape by adding finish_states) — pinned independently of
# tests/test_e2e_mock.py's own copy of this set, on purpose (see module
# docstring: this gate must survive that file being refactored).
_PRE_ARC_TASKRESULT_KEYS = {
    "task_id",
    "status",
    "summary",
    "changed_files",
    "steps",
    "usage",
    "stats",
    "artifacts_path",
    "error",
    "branch",
    "pr_url",
    "hook_firings",
    "command",
    "not_finished",
    "stopped_without_finish",
}

# Decision c30: finish_reason propagation is unconditional observability for
# ALL runs — the ONE sanctioned artifact addition to the no-config shape.
_SANCTIONED_FINISH_ADDITIONS = {"finish_states"}

_EXPECTED_NOCONFIG_TASKRESULT_KEYS = _PRE_ARC_TASKRESULT_KEYS | _SANCTIONED_FINISH_ADDITIONS

# Fields the arc introduced elsewhere on TaskResult (t7's config event stream)
# that must stay ABSENT from a no-config serialized result — additive,
# omit-when-empty, never gated behind three-tier config but also never
# present with nothing to record.
_MUST_STAY_ABSENT_FROM_NOCONFIG_TASKRESULT = {
    "config_events",
    "config_digest",
    "worker",
    "deepthink",
}


def _mock_vllm_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """A minimal two-turn scripted vLLM HTTP fixture (write_file, then
    finish) — independent of tests/test_e2e_mock.py's own copy, by design.
    """
    turns = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": "gate.txt", "content": "from the worker"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "2",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "wrote gate.txt"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    ]
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)


@pytest.mark.parametrize("engine_name", ["mock", "vllm-openai"])
def test_no_config_taskresult_shape_is_pre_arc_plus_sanctioned_finish_fields(
    engine_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All-engines pin (c11/h11): with NO three-tier configuration, a full
    work item on EITHER engine serializes to exactly the pre-arc key set plus
    the one sanctioned addition — never config_events/config_digest/worker/
    deepthink, which stay omitted with nothing to record."""
    _mock_vllm_http(monkeypatch)  # a no-op setup for "mock"; required for "vllm-openai"
    cfg = EngineConfig.resolve()
    assert cfg.three_tier is False  # sanity: this really is the no-config baseline

    repo = tmp_path / engine_name.replace("-", "_")
    repo.mkdir()
    result = registry.load(engine_name).work(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    serialized = result.to_dict()

    # (a) existing-field identity + presence of the new finish fields.
    assert set(serialized.keys()) == _EXPECTED_NOCONFIG_TASKRESULT_KEYS, (
        f"engine={engine_name}: no-config TaskResult key set drifted.\n"
        f"  got:      {sorted(serialized.keys())}\n"
        f"  expected: {sorted(_EXPECTED_NOCONFIG_TASKRESULT_KEYS)}"
    )
    assert "finish_states" in serialized
    assert serialized["finish_states"], "a completed run must record at least one finish state"

    # config_events/config_digest (t7) stay ABSENT when empty — never gated
    # behind three-tier config, but never present with nothing to record.
    for absent_key in _MUST_STAY_ABSENT_FROM_NOCONFIG_TASKRESULT:
        assert absent_key not in serialized, (
            f"engine={engine_name}: {absent_key!r} must be absent from an unconfigured "
            "TaskResult (omit-when-empty), not present-as-empty"
        )


def test_no_config_resolved_engineconfig_reports_three_tier_false() -> None:
    """(b) three_tier is False in the resolved config to_dict, on the plain
    no-config resolution path (no lobes gateway declared at all)."""
    cfg = EngineConfig.resolve()
    assert cfg.three_tier is False
    assert cfg.to_dict()["three_tier"] is False


def test_no_config_resolved_engineconfig_omits_worker_and_deepthink_keys() -> None:
    """(c) no worker/deepthink keys appear in the resolved config snapshot
    when nothing is configured — both stay omit-when-None, the same
    convention senses/voice already use."""
    cfg = EngineConfig.resolve()
    assert cfg.worker is None
    assert cfg.deepthink is None
    snapshot = cfg.to_dict()
    assert "worker" not in snapshot
    assert "deepthink" not in snapshot


# ---------------------------------------------------------------------------
# Gate 2: LOUD REFUSAL (c21, first half) — both CLI fronts.
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _work_namespace(repo: Path, **overrides: object) -> argparse.Namespace:
    base = dict(
        instruction=["do", "x"],
        repo=str(repo),
        engine="mock",
        no_pr=True,
        watch=False,
        base="main",
        model=None,
        base_url=None,
        api_key=None,
        max_steps=None,
        json=True,
        command_name=None,
        allow_dirty=True,
        mode=None,
        role=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _session_namespace(repo: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )


def test_work_front_refuses_loudly_when_three_tier_armed_without_worker(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """The ``work`` front: cmd_work calls EngineConfig.resolve() before
    building any task — armed with no lobes gateway at all, the refusal
    fires before any episode starts, naming the gap (never a silent
    cortex-as-actor fallback)."""
    from colleague.cli._commands.work import cmd_work

    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    namespace = _work_namespace(git_repo)
    with pytest.raises(CliError) as exc_info:
        cmd_work(namespace)
    message = exc_info.value.message.lower()
    assert "three-tier" in message
    assert "lobes" in message


def test_session_front_refuses_loudly_when_three_tier_armed_without_worker(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """The ``session`` front: run_session calls EngineConfig.resolve() before
    entering its interactive loop — the refusal fires before any input is
    even read (the session loop must never start)."""
    from colleague.cli._commands.session import run_session

    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")

    def _boom_input() -> Iterator[str]:
        raise AssertionError("the session loop must never start reading input")
        yield  # pragma: no cover - unreachable, satisfies the generator shape

    namespace = _session_namespace(git_repo)
    input_iter = _boom_input()
    with pytest.raises(CliError) as exc_info:
        run_session(
            namespace,
            input_fn=input_iter,
            out=lambda *a, **k: None,
            err=lambda *a, **k: None,
            _color=False,
        )
    message = exc_info.value.message.lower()
    assert "three-tier" in message
    assert "lobes" in message


# ---------------------------------------------------------------------------
# Gate 3: FINISH-STATE DISTINGUISHABILITY (c21, second half).
# ---------------------------------------------------------------------------


def test_five_finish_states_are_distinct_values() -> None:
    """The five FINISH_* states are pairwise distinct string constants — the
    "100% distinguishable" claim starts with the vocabulary itself."""
    states = (FINISH_DELIBERATE, FINISH_TRUNCATED, FINISH_STOPPED, FINISH_TIMEOUT, FINISH_EMPTY)
    assert len(set(states)) == 5
    assert set(FINISH_STATES) == set(states)
    assert len(FINISH_STATES) == 5


def test_classifier_reaches_every_one_of_the_five_states() -> None:
    """colleague.finishstate.classify_finish_state actually produces all five
    values from the terminal facts that are supposed to trigger them —
    proving the states are not just declared but reachable."""
    # timeout takes precedence over everything else.
    assert (
        classify_finish_state(summary="x", finish_reason="stop", timed_out=True) == FINISH_TIMEOUT
    )
    # an abort that is NOT a timeout maps to empty.
    assert classify_finish_state(summary="diagnostic fallback", aborted=True) == FINISH_EMPTY
    # the NO_RESULT_PRODUCED sentinel must never be reported as deliberate.
    assert classify_finish_state(summary=NO_RESULT_PRODUCED) == FINISH_EMPTY
    # an external stop (pilot stop / tool-protocol-broken) maps to stopped.
    assert classify_finish_state(summary="partial", outcome="pilot_stop") == FINISH_STOPPED
    assert classify_finish_state(summary="partial", outcome="tool_protocol") == FINISH_STOPPED
    # a wire length cap OR the loop's own budget ceiling maps to truncated.
    assert classify_finish_state(summary="cut short", finish_reason="length") == FINISH_TRUNCATED
    assert classify_finish_state(summary="cut short", outcome="budget") == FINISH_TRUNCATED
    # a clean stop with a real answer maps to deliberate.
    assert classify_finish_state(summary="done", finish_reason="stop") == FINISH_DELIBERATE


def test_mock_run_artifact_carries_a_deliberate_finish_state(tmp_path: Path) -> None:
    """A clean, unconfigured mock work item's artifact carries finish_states
    with a "main"-seat deliberate state — the 100% claim is this assertion
    running in CI, not prose."""
    cfg = EngineConfig.resolve()
    repo = tmp_path / "repo"
    repo.mkdir()

    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    assert len(result.finish_states) == 1
    main = result.finish_states[0]
    assert main.seat == "main"
    assert main.state == FINISH_DELIBERATE
    assert main.state in FINISH_STATES


# ---------------------------------------------------------------------------
# Gate 4: CI PRESENCE (c17/h14, c21/h18) — this module runs unconditionally.
# ---------------------------------------------------------------------------


def test_this_module_defines_no_skip_markers_or_env_gates() -> None:
    """Meta-gate: the byte-identical suite, the loud-refusal test, and the
    finish-state tests all run in the DEFAULT pytest job by construction —
    no marker, no module-level pytestmark, no env-var-gated skip anywhere in
    this file (mirrors the pattern tests/test_vllm_live.py uses to OPT OUT,
    which this file must never adopt).

    Parses the module's own AST rather than substring-scanning the raw text
    (this file's OWN docstrings legitimately discuss "pytestmark"/"skip" as
    the thing being ruled out — a naive ``"pytestmark" not in source`` check
    would self-trip on its own prose). Real code, not comments or
    docstrings, is what must stay clean.
    """
    import ast

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=__file__)

    # No module-level "pytestmark = ..." assignment (the collection-wide
    # opt-out idiom tests/test_vllm_live.py uses).
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            assert "pytestmark" not in names, "module-level pytestmark assignment found"

    def _dotted(node: ast.AST) -> str:
        """Render a dotted attribute/call chain (e.g. pytest.mark.skip) as text."""
        if isinstance(node, ast.Attribute):
            return f"{_dotted(node.value)}.{node.attr}"
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Call):
            return _dotted(node.func)
        return ""

    for node in ast.walk(tree):
        # No @pytest.mark.skip / skipif / xfail decorator on any def, and no
        # imperative pytest.skip(...) / pytest.importorskip(...) call.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                dotted = _dotted(dec)
                assert not dotted.endswith(
                    (".skip", ".skipif", ".xfail")
                ), f"{node.name} carries a skip-shaped decorator: {dotted}"
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            assert dotted not in (
                "pytest.skip",
                "pytest.importorskip",
            ), f"an imperative skip call was found: {dotted}(...)"

    # No "import os" at all — this arc's env-gated tests (e.g.
    # test_vllm_live.py) always key their skip condition off os.environ, so
    # the absence of the import is itself proof no such gate exists here.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert "os" not in {alias.name for alias in node.names}
        if isinstance(node, ast.ImportFrom):
            assert node.module != "os"


def test_default_pytest_config_carries_no_marker_filter_that_could_exclude_this_module() -> None:
    """pyproject.toml's [tool.pytest.ini_options] must keep ``testpaths`` on
    the whole ``tests`` directory and ``addopts`` free of a ``-m``/``-k``
    marker-or-keyword filter — this file lives in ``tests/`` with a
    pytest-discoverable name (``test_*.py``), so it is collected by the bare
    ``pytest`` invocation CI runs, with no extra flags required."""
    repo_root = Path(__file__).resolve().parent.parent
    pyproject_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    # Locate the [tool.pytest.ini_options] table body (up to the next
    # top-level "[" heading, or end of file).
    marker = "[tool.pytest.ini_options]"
    assert marker in pyproject_text, "pyproject.toml must declare [tool.pytest.ini_options]"
    start = pyproject_text.index(marker) + len(marker)
    rest = pyproject_text[start:]
    next_section = rest.find("\n[")
    body = rest if next_section == -1 else rest[:next_section]

    assert '"tests"' in body  # testpaths still targets the whole tests/ tree
    assert " -m " not in body  # no marker filter
    assert not body.strip().startswith("-m ")  # no marker filter
    assert " -k " not in body  # no keyword filter that could exclude this module by name


def test_finish_state_gate_functions_carry_no_skip_decorator() -> None:
    """Belt-and-suspenders on top of the source-text scan above: introspect
    the actual test functions defined in this module and assert none carries
    a pytest skip/xfail mark object (catches a decorator spelled in a way
    the plain-text scan might miss, e.g. via an imported alias)."""
    import sys

    this_module = sys.modules[__name__]
    checked = 0
    for name, obj in vars(this_module).items():
        if not name.startswith("test_") or not callable(obj):
            continue
        checked += 1
        marks = getattr(obj, "pytestmark", [])
        for mark in marks:
            assert mark.name not in (
                "skip",
                "skipif",
                "xfail",
            ), f"{name} carries a {mark.name} marker — gate tests must never opt out"
    assert checked > 0  # sanity: the introspection actually found test functions

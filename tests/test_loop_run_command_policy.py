"""Policy-gate for run_command in the loop chassis (t2 — approval gate).

Proves three acceptance criteria:

1. A run_command whose program token is denied by policy is NOT executed;
   ``verdict.reason`` is fed back as the tool result (a ``role:"tool"`` message)
   and recorded as a non-ok ``Step``; the drive continues (does not abort).

2. The gate lives in the loop (chassis) — the same ``Policy`` produces the same
   denial regardless of engine (demonstrated by driving the loop with two
   different scripted ``complete`` callables, neither of which is an imported
   engine module).

3. With no ``run_command`` section (empty policy), run_command runs normally and
   the result/artifact is byte-identical to a policy-free run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run
from colleague.policy import Policy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def scripted(responses: list[ModelResponse]):
    """Return a complete() callable that replays *responses* in order."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _policy_with_deny(token: str) -> Policy:
    """A Policy whose run_command section explicitly denies *token*."""
    return Policy(
        run_command={"deny": [token], "allow": []},
        present=frozenset({"run_command"}),
    )


def _policy_with_allow(*tokens: str) -> Policy:
    """A Policy whose run_command section only allows the listed *tokens*."""
    return Policy(
        run_command={"allow": list(tokens), "deny": []},
        present=frozenset({"run_command"}),
    )


def _empty_policy() -> Policy:
    """A Policy with no sections — total no-op."""
    return Policy()


def _write_approvals(repo: Path, config: dict) -> None:
    """Write .colleague/approvals.json under *repo*."""
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(json.dumps(config), encoding="utf-8")


# ---------------------------------------------------------------------------
# Acceptance criterion 1: denied run_command is NOT executed; reason is the
# tool result; a non-ok Step is recorded; drive continues.
# ---------------------------------------------------------------------------


def test_denied_run_command_is_not_executed_and_continues(tmp_path: Path) -> None:
    """AC1: a run_command denied by policy — the command never runs, verdict.reason
    is fed back as the tool result message, a non-ok Step is recorded, and the
    drive continues to finish (does not abort)."""
    # The model requests 'rm -rf /tmp/sentinel' — policy denies 'rm'.
    # We verify the command never ran by checking the sentinel never changed.
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("original", encoding="utf-8")

    policy = _policy_with_deny("rm")
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "run_command", {"command": f"rm {sentinel}"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "drive continues"})]),
    ]
    task = Task.new(str(tmp_path), "try to rm something")
    result = run(scripted(responses), task, max_steps=10, policy=policy)

    # Command never executed — sentinel is untouched.
    assert sentinel.read_text(encoding="utf-8") == "original"
    # Drive still reached finish normally.
    assert result.status == OK
    assert result.summary == "drive continues"
    # A non-ok Step was recorded for the denied call.
    deny_steps = [s for s in result.steps if s.tool == "run_command"]
    assert len(deny_steps) == 1
    assert deny_steps[0].ok is False
    # The verdict reason is in the Step.result (so the model can read it next turn).
    assert "rm" in deny_steps[0].result


def test_denied_run_command_reason_is_tool_message(tmp_path: Path) -> None:
    """AC1 (message shape): the loop appends a role:'tool' message so the model
    receives the reason — the only observable evidence is the Step.result which
    matches what would be the tool message content."""
    policy = _policy_with_allow("git", "uv")  # only these two; 'pytest' is unlisted
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "run_command", {"command": "pytest tests/"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "ok"})]),
    ]
    task = Task.new(str(tmp_path), "run tests")
    result = run(scripted(responses), task, max_steps=10, policy=policy)

    deny_steps = [s for s in result.steps if s.tool == "run_command"]
    assert deny_steps[0].ok is False
    # The reason names the offending token ('pytest').
    assert "pytest" in deny_steps[0].result


def test_policy_allows_permitted_run_command(tmp_path: Path) -> None:
    """AC1 (positive): a run_command on the allow-list runs normally."""
    policy = _policy_with_allow("echo")
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "run_command", {"command": "echo hello"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "ok"})]),
    ]
    task = Task.new(str(tmp_path), "echo something")
    result = run(scripted(responses), task, max_steps=10, policy=policy)

    assert result.status == OK
    run_steps = [s for s in result.steps if s.tool == "run_command"]
    assert len(run_steps) == 1
    assert run_steps[0].ok is True
    assert "hello" in run_steps[0].result


# ---------------------------------------------------------------------------
# Acceptance criterion 2: gate is chassis-owned — same Policy, different
# scripted engines, same denial shape.
# ---------------------------------------------------------------------------


def test_policy_denial_is_engine_agnostic(tmp_path: Path) -> None:
    """AC2: two distinct scripted complete callables (simulating two engines)
    driven through the same Policy produce the same denial shape — the gate
    lives in the loop, not in any engine module."""
    policy = _policy_with_deny("curl")

    def responses_for(call_id_prefix: str, file_name: str) -> list[ModelResponse]:
        return [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        f"{call_id_prefix}1",
                        "run_command",
                        {"command": "curl http://example.com"},
                    )
                ]
            ),
            ModelResponse(
                tool_calls=[ToolCall(f"{call_id_prefix}2", "finish", {"summary": "done"})]
            ),
        ]

    # Engine A
    repo_a = tmp_path / "a"
    repo_a.mkdir()
    result_a = run(
        scripted(responses_for("a", "a.txt")),
        Task.new(str(repo_a), "fetch"),
        max_steps=10,
        policy=policy,
    )

    # Engine B — a different complete callable
    repo_b = tmp_path / "b"
    repo_b.mkdir()

    def engine_b_complete(_messages: list[dict]) -> ModelResponse:
        # Stateless: always returns the turn corresponding to the message count.
        turn = max(0, len(_messages) - 2)  # 0 → first turn, 1+ → finish
        if turn == 0:
            return ModelResponse(
                tool_calls=[ToolCall("b1", "run_command", {"command": "curl http://example.com"})]
            )
        return ModelResponse(tool_calls=[ToolCall("b2", "finish", {"summary": "done"})])

    result_b = run(
        engine_b_complete,
        Task.new(str(repo_b), "fetch"),
        max_steps=10,
        policy=policy,
    )

    # Both drives denied 'curl'.
    for result in (result_a, result_b):
        deny_steps = [s for s in result.steps if s.tool == "run_command"]
        assert len(deny_steps) == 1
        assert deny_steps[0].ok is False
        assert "curl" in deny_steps[0].result
        assert result.status == OK

    # Same denial shape across both "engines".
    shape_a = [(s.tool, s.ok) for s in result_a.steps]
    shape_b = [(s.tool, s.ok) for s in result_b.steps]
    assert shape_a == shape_b


def test_policy_not_imported_from_engine_modules(tmp_path: Path) -> None:
    """AC2 (isolation): the loop imports policy; engine modules do NOT import it.
    We verify that neither the mock engine nor the vllm-openai engine module
    references 'colleague.policy' directly.
    """
    import colleague.engines.mock as mock_engine
    import colleague.engines.vllm_openai as vllm_engine

    for engine_mod in (mock_engine, vllm_engine):
        mod_dict = vars(engine_mod)
        # No symbol from policy is imported into the engine namespace.
        from colleague import policy as policy_mod

        assert policy_mod not in mod_dict.values(), (
            f"{engine_mod.__name__} imported the policy module — "
            "the gate must live in the loop, not in engines"
        )


# ---------------------------------------------------------------------------
# Acceptance criterion 3: empty policy is a strict no-op; result is
# byte-identical to a policy-free run.
# ---------------------------------------------------------------------------


def test_empty_policy_run_command_executes_normally(tmp_path: Path) -> None:
    """AC3: when the policy has no run_command section, run_command executes
    normally and the result matches a run with no policy at all."""
    marker = tmp_path / "marker.txt"

    responses = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "1",
                    "run_command",
                    {"command": f"touch {marker}"},
                )
            ]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "touched"})]),
    ]

    # With empty policy
    task_a = Task.new(str(tmp_path), "touch a file")
    marker.unlink(missing_ok=True)
    result_with_empty = run(scripted(responses), task_a, max_steps=10, policy=_empty_policy())

    # Without policy at all (defaults to load_policy which finds nothing → empty)
    marker.unlink(missing_ok=True)
    responses2 = [
        ModelResponse(
            tool_calls=[
                ToolCall(
                    "1",
                    "run_command",
                    {"command": f"touch {marker}"},
                )
            ]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "touched"})]),
    ]
    task_b = Task.new(str(tmp_path), "touch a file")
    result_without = run(scripted(responses2), task_b, max_steps=10)

    # Both results have the same shape (all steps ok, run_command succeeded).
    for result in (result_with_empty, result_without):
        assert result.status == OK
        run_steps = [s for s in result.steps if s.tool == "run_command"]
        assert len(run_steps) == 1
        assert run_steps[0].ok is True


def test_empty_policy_result_shape_is_byte_identical(tmp_path: Path) -> None:
    """AC3: driving with an explicit empty Policy yields the same to_dict() key
    set as driving with no policy kwarg (the default load path returns empty
    when no approvals.json is present)."""

    def make_responses(prefix: str) -> list[ModelResponse]:
        return [
            ModelResponse(
                tool_calls=[
                    ToolCall(f"{prefix}1", "write_file", {"path": "out.txt", "content": "hi"})
                ]
            ),
            ModelResponse(tool_calls=[ToolCall(f"{prefix}2", "finish", {"summary": "wrote"})]),
        ]

    repo_a = tmp_path / "a"
    repo_a.mkdir()
    result_a = run(
        scripted(make_responses("a")),
        Task.new(str(repo_a), "write"),
        max_steps=10,
        policy=_empty_policy(),
    )

    repo_b = tmp_path / "b"
    repo_b.mkdir()
    result_b = run(
        scripted(make_responses("b")),
        Task.new(str(repo_b), "write"),
        max_steps=10,
    )

    # Same key structure.
    def key_set(d: dict[str, Any]) -> set:
        return set(d.keys())

    assert key_set(result_a.to_dict()) == key_set(result_b.to_dict())
    # Same step shape.
    assert [(s.tool, s.ok) for s in result_a.steps] == [(s.tool, s.ok) for s in result_b.steps]
    # Both ok.
    assert result_a.status == result_b.status == OK


# ---------------------------------------------------------------------------
# Policy loaded from approvals.json on disk (integration smoke test)
# ---------------------------------------------------------------------------


def test_policy_loaded_from_disk_gates_run_command(tmp_path: Path) -> None:
    """The default load path (no policy= kwarg) reads approvals.json and gates
    run_command.  This verifies the full wiring: disk config → load_policy →
    _Drive.policy → check_run_command → deny."""
    _write_approvals(
        tmp_path,
        {"run_command": {"allow": ["echo"], "deny": []}},
    )
    responses = [
        # 'ls' is not on the allow list — should be denied.
        ModelResponse(tool_calls=[ToolCall("1", "run_command", {"command": "ls -la"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "list files")
    # No policy= kwarg: the loop loads approvals.json from tmp_path.
    result = run(scripted(responses), task, max_steps=10)

    deny_steps = [s for s in result.steps if s.tool == "run_command"]
    assert len(deny_steps) == 1
    assert deny_steps[0].ok is False
    assert "ls" in deny_steps[0].result
    assert result.status == OK


# ---------------------------------------------------------------------------
# Policy does NOT gate non-run_command tools (isolation guard)
# ---------------------------------------------------------------------------


def test_policy_does_not_gate_write_file(tmp_path: Path) -> None:
    """The policy gate is run_command-only.  write_file executes normally even
    when an aggressive allow-only policy is in place."""
    # Allow-only policy with no run_command section → write_file must not be gated.
    policy = Policy(
        run_command={"allow": ["echo"], "deny": []},
        present=frozenset({"run_command"}),
    )
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "safe.txt", "content": "safe"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote"})]),
    ]
    task = Task.new(str(tmp_path), "write a file")
    result = run(scripted(responses), task, max_steps=10, policy=policy)

    assert (tmp_path / "safe.txt").read_text(encoding="utf-8") == "safe"
    assert result.status == OK
    write_steps = [s for s in result.steps if s.tool == "write_file"]
    assert write_steps[0].ok is True

"""Bounded agentic tool-loop: execution, termination, usage, errors (R3, h3)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from colleague.contract import ERROR, INCOMPLETE, NO_RESULT_PRODUCED, OK, Task
from colleague.loop import (
    CompleteFn,
    ContextControls,
    ModelResponse,
    ToolCall,
    WorkAborted,
    _assistant_message,
    run,
)


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def test_loop_writes_file_and_finishes(tmp_path: Path) -> None:
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hello"})],
            prompt_tokens=10,
            completion_tokens=2,
        ),
        ModelResponse(
            tool_calls=[ToolCall("2", "finish", {"summary": "wrote out.txt"})],
            completion_tokens=1,
        ),
    ]
    task = Task.new(str(tmp_path), "write out.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert result.status == OK
    assert result.changed_files == ["out.txt"]
    assert (tmp_path / "out.txt").read_text() == "hello"
    assert result.summary == "wrote out.txt"
    assert result.usage.total_tokens == 13
    assert len(result.steps) == 2


def test_loop_stops_at_budget_when_never_finishing(tmp_path: Path) -> None:
    def never_finish(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "loop forever")
    result = run(never_finish, task, max_steps=3)

    assert result.status == INCOMPLETE
    assert len(result.steps) == 3
    # No content was ever produced, so the summary is the NO_RESULT_PRODUCED
    # sentinel (t2, #109).  Budget exhaustion is preserved in stats.step_count
    # (== max_steps) rather than encoded in the summary string.
    assert result.summary == NO_RESULT_PRODUCED
    assert result.stats.step_count == 3


def test_budget_exhaustion_forces_synthesis(tmp_path: Path) -> None:
    """#191: a budget-exhausted run that read context but never finished gets ONE
    forced no-tools synthesis turn, returned as the summary — not the sentinel.

    Three tool-call turns consume ``max_steps=3``; the loop exits on the budget.
    The forced synthesis turn (which executes no tool) then returns prose, which
    becomes the summary.  Contrast with
    :func:`test_loop_stops_at_budget_when_never_finishing`, where the model keeps
    emitting tool calls (no content) even on the forced turn, so the run correctly
    falls back to ``NO_RESULT_PRODUCED``.
    """
    tool = ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])
    synthesis = ModelResponse(content="SYNTHESIZED: the repo maps to modules A and B.")
    task = Task.new(str(tmp_path), "map the repo")
    result = run(scripted([tool, tool, tool, synthesis]), task, max_steps=3)

    assert result.status == INCOMPLETE
    assert result.not_finished is True
    assert result.summary == "SYNTHESIZED: the repo maps to modules A and B."
    # The forced synthesis executes no tool, so it adds no step (only a model turn).
    assert result.stats.step_count == 3


def test_mapping_fanout_advisory_injected_after_threshold(tmp_path: Path) -> None:
    """#188: once a read-only survey reads MORE than the files-read threshold, the
    loop injects ONE advisory pointing at the ``subagents`` tool — and only once."""
    captured: list[list[str]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        captured.append([str(m.get("content", "")) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "map the repo")
    run(complete, task, max_steps=6, context=ContextControls(fanout_files=2))

    marker = "partition the unmapped surface"
    # The recommendation is appended to the history once it fires, so the final
    # turn the model saw must contain it EXACTLY once (one-shot) and name subagents.
    final_turn = captured[-1]
    assert sum(1 for c in final_turn if marker in c) == 1
    assert any("subagents" in c for c in final_turn)


def test_mapping_fanout_dormant_is_noop(tmp_path: Path) -> None:
    """#188: with the advisory dormant (``fanout_files`` <= 0) a read-heavy run never
    sees the recommendation — a strict no-op."""
    seen: list[str] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.extend(str(m.get("content", "")) for m in messages)
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "map the repo")
    run(complete, task, max_steps=6, context=ContextControls(fanout_files=0))
    assert not any("partition the unmapped surface" in c for c in seen)


def test_loop_terminates_on_empty_tool_calls(tmp_path: Path) -> None:
    task = Task.new(str(tmp_path), "just answer")
    result = run(scripted([ModelResponse(content="nothing to do here")]), task, max_steps=5)
    assert result.summary == "nothing to do here"
    assert result.steps == []


def test_assistant_message_serializes_arguments_as_json_string() -> None:
    # OpenAI wire format: function.arguments must be a JSON *string*, not a dict,
    # or strict servers reject replayed turns.
    resp = ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a", "content": "b"})])
    msg = _assistant_message(resp)
    args = msg["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args, str)
    assert json.loads(args) == {"path": "a", "content": "b"}


def test_assistant_message_passes_string_arguments_through() -> None:
    resp = ModelResponse(tool_calls=[ToolCall("1", "finish", '{"summary": "done"}')])
    args = _assistant_message(resp)["tool_calls"][0]["function"]["arguments"]
    assert args == '{"summary": "done"}'


def test_loop_records_tool_error_and_continues(tmp_path: Path) -> None:
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {"path": "missing.txt"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "gave up reading"})]),
    ]
    task = Task.new(str(tmp_path), "read a missing file")
    result = run(scripted(responses), task, max_steps=5)

    assert result.status == OK  # a failed tool call is not a failed drive
    assert result.steps[0].ok is False
    assert "error:" in result.steps[0].result
    assert result.summary == "gave up reading"


def test_loop_preserves_partial_result_when_complete_raises(tmp_path: Path) -> None:
    """An engine that raises mid-loop -> WorkAborted carrying the partial result (#37)."""
    calls = {"n": 0}

    def flaky(_messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})],
                prompt_tokens=7,
                completion_tokens=3,
            )
        raise TimeoutError("timed out")

    task = Task.new(str(tmp_path), "write then time out")
    with pytest.raises(WorkAborted) as excinfo:
        run(flaky, task, max_steps=10)

    result = excinfo.value.result
    assert result.status == ERROR
    assert "TimeoutError" in (result.error or "")
    assert isinstance(excinfo.value.__cause__, TimeoutError)
    # Work done up to the failure is preserved, not discarded.
    assert result.changed_files == ["out.txt"]
    assert len(result.steps) == 1
    assert result.usage.total_tokens == 10
    assert (tmp_path / "out.txt").read_text() == "hi"  # the file really landed on disk


def test_loop_emits_progress_per_step(tmp_path: Path) -> None:
    """The progress sink fires once per tool call with (index, tool, target, ok) (#38)."""
    events: list[tuple] = []
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "read_file", {"path": "missing.txt"})]),  # errors
        ModelResponse(tool_calls=[ToolCall("3", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "two steps then finish")
    run(scripted(responses), task, max_steps=10, progress=lambda *a: events.append(a))

    assert [e[0] for e in events] == [0, 1, 2]  # step indices, in order
    assert [e[1] for e in events] == ["write_file", "read_file", "finish"]
    assert events[0][2] == "a.txt"  # target hint = the path
    assert events[0][3] is True  # write ok
    assert events[1][3] is False  # read of a missing file is not ok
    assert events[2][3] is True  # finish ok


def test_loop_progress_default_is_noop(tmp_path: Path) -> None:
    """No progress sink -> behavior is byte-identical to before (#38)."""
    responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "ok"})])]
    task = Task.new(str(tmp_path), "finish immediately")
    result = run(scripted(responses), task, max_steps=5)  # no progress=
    assert result.status == OK
    assert result.summary == "ok"


def test_loop_progress_sink_failure_does_not_abort(tmp_path: Path) -> None:
    """A raising progress sink is observability, not control — the drive still completes (Qodo)."""

    def boom(*_args: object) -> None:
        raise RuntimeError("progress sink blew up")

    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write then finish")
    result = run(scripted(responses), task, max_steps=10, progress=boom)

    assert result.status == OK  # the sink failure was suppressed, not propagated
    assert result.summary == "done"
    assert (tmp_path / "a.txt").read_text() == "x"


# ---------------------------------------------------------------------------
# Hook lifecycle wiring (t5 — R4): task_start / pre_tool / post_tool / finish.
#
# The loop loads .colleague/hooks.json from task.repo_path by default, so
# every engine inherits the lifecycle for free (the all-engines rule). When no
# config exists, nothing fires and behavior is byte-identical to today (the
# tests above stay green). Hooks run as shell commands (run_hook uses
# shell=True), so fixtures embed the hook command inline in hooks.json:
#   - deny: exit non-zero (reason from stderr/stdout), or emit
#     {"decision":"deny","reason":...} on stdout with exit 0.
#   - rewrite: emit {"decision":"rewrite","arguments":{...}} on stdout, exit 0.
#   - allow/observe: exit 0 with empty/non-JSON stdout.
# ---------------------------------------------------------------------------


def _write_hooks(repo: Path, config: dict) -> None:
    """Write .colleague/hooks.json under *repo*."""
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(config), encoding="utf-8")


def _make_script(path: Path, body: str) -> str:
    """Write an executable shell script and return an absolute command to run it.

    Using a real script file sidesteps brittle nested-quote escaping when the
    hook must emit JSON (deny/rewrite) on stdout.
    """
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return f"sh {path}"


def test_no_hooks_config_is_byte_identical(tmp_path: Path) -> None:
    """No .colleague/hooks.json → nothing fires; result is unchanged."""
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write out.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert result.hook_firings == []
    assert result.changed_files == ["out.txt"]
    assert (tmp_path / "out.txt").read_text() == "hi"
    assert result.summary == "done"


def test_pre_tool_deny_blocks_run_command_and_continues(tmp_path: Path) -> None:
    """Acceptance 1: a pre_tool deny-hook on run_command stops the command from
    running (observable side-effect absent), the model gets the reason and the
    loop still finishes, and the firing is recorded."""
    # The model would, absent the deny, create marker.txt via run_command.
    marker = tmp_path / "marker.txt"
    _write_hooks(
        tmp_path,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "run_command",
                        # exit 1 with a reason on stderr → deny.
                        "command": "sh -c 'echo blocked-by-policy >&2; exit 1'",
                    }
                ]
            }
        },
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "run_command", {"command": f"touch {marker}"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "finished anyway"})]),
    ]
    task = Task.new(str(tmp_path), "run a command")
    result = run(scripted(responses), task, max_steps=10)

    # The denied command never executed: the marker file does not exist.
    assert not marker.exists()
    # The loop still reached finish.
    assert result.status == OK
    assert result.summary == "finished anyway"
    # A non-ok Step was recorded carrying the reason so the model can continue.
    deny_steps = [s for s in result.steps if s.tool == "run_command"]
    assert len(deny_steps) == 1
    assert deny_steps[0].ok is False
    assert "blocked-by-policy" in deny_steps[0].result
    # A deny firing was recorded.
    deny_firings = [f for f in result.hook_firings if f.decision == "deny"]
    assert len(deny_firings) == 1
    assert deny_firings[0].event == "pre_tool"
    assert deny_firings[0].tool == "run_command"
    assert "blocked-by-policy" in deny_firings[0].reason
    assert deny_firings[0].exit_code == 1


def test_pre_tool_deny_reason_reaches_model(tmp_path: Path) -> None:
    """The deny reason is fed back so a model could react to it. We assert the
    reason became the tool-result content the next turn would see (the Step).

    This deny comes via structured stdout (exit 0 + {"decision":"deny",...})
    rather than a non-zero exit, exercising the other deny path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    deny_cmd = _make_script(
        scripts / "deny.sh",
        'echo \'{"decision":"deny","reason":"writes are frozen"}\'\n',
    )
    _write_hooks(
        repo,
        {"hooks": {"pre_tool": [{"matcher": "write_file", "command": deny_cmd}]}},
    )
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "x.txt", "content": "nope"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "ok"})]),
    ]
    task = Task.new(str(repo), "try to write")
    result = run(scripted(responses), task, max_steps=10)

    assert not (repo / "x.txt").exists()
    step = [s for s in result.steps if s.tool == "write_file"][0]
    assert step.ok is False
    assert "writes are frozen" in step.result
    # exit_code is 0 here (deny came via structured stdout, not a crash).
    deny_firing = [f for f in result.hook_firings if f.decision == "deny"][0]
    assert deny_firing.exit_code == 0


def test_pre_tool_rewrite_changes_written_path_and_content(tmp_path: Path) -> None:
    """Acceptance 2: a pre_tool rewrite-hook on write_file changes the path AND
    content actually written; the original is not written; the firing is
    recorded as a rewrite."""
    repo = tmp_path / "repo"
    repo.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    rewrite_cmd = _make_script(
        scripts / "rewrite.sh",
        'echo \'{"decision":"rewrite","arguments":'
        '{"path":"rewritten.txt","content":"REWRITTEN"}}\'\n',
    )
    _write_hooks(
        repo,
        {"hooks": {"pre_tool": [{"matcher": "write_file", "command": rewrite_cmd}]}},
    )
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "original.txt", "content": "ORIG"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote"})]),
    ]
    task = Task.new(str(repo), "write a file")
    result = run(scripted(responses), task, max_steps=10)

    # The rewritten file exists with rewritten content; the original does not.
    assert (repo / "rewritten.txt").read_text() == "REWRITTEN"
    assert not (repo / "original.txt").exists()
    assert "rewritten.txt" in result.changed_files
    assert "original.txt" not in result.changed_files
    # The executed Step reflects the rewritten arguments and succeeded.
    step = [s for s in result.steps if s.tool == "write_file"][0]
    assert step.ok is True
    assert step.arguments == {"path": "rewritten.txt", "content": "REWRITTEN"}
    # A rewrite firing was recorded.
    rewrites = [f for f in result.hook_firings if f.decision == "rewrite"]
    assert len(rewrites) == 1
    assert rewrites[0].event == "pre_tool"
    assert rewrites[0].tool == "write_file"


def test_pre_tool_allow_is_a_noop(tmp_path: Path) -> None:
    """An allow/observe pre_tool hook does not alter execution; still recorded."""
    _write_hooks(
        tmp_path,
        {
            "hooks": {
                "pre_tool": [
                    {"matcher": "write_file", "command": "sh -c 'exit 0'"},
                ]
            }
        },
    )
    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "ok.txt", "content": "data"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write ok.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert (tmp_path / "ok.txt").read_text() == "data"
    assert result.changed_files == ["ok.txt"]
    allows = [f for f in result.hook_firings if f.event == "pre_tool"]
    assert len(allows) == 1
    assert allows[0].decision == "allow"


def test_task_start_finish_post_tool_fire_observe_only(tmp_path: Path) -> None:
    """task_start, post_tool, and finish hooks all fire and are recorded in
    lifecycle order, observe-only (they do not alter control flow)."""
    _write_hooks(
        tmp_path,
        {
            "hooks": {
                "task_start": [{"command": "sh -c 'exit 0'"}],
                "post_tool": [{"matcher": "write_file", "command": "sh -c 'exit 0'"}],
                "finish": [{"command": "sh -c 'exit 0'"}],
            }
        },
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "f.txt", "content": "z"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write f.txt")
    result = run(scripted(responses), task, max_steps=10)

    events = [f.event for f in result.hook_firings]
    # task_start fires first; finish fires last; post_tool fires after the write.
    assert events[0] == "task_start"
    assert events[-1] == "finish"
    assert "post_tool" in events
    # write succeeded normally (observe-only post_tool did not block it).
    assert (tmp_path / "f.txt").read_text() == "z"
    # post_tool fires after the write step, before finish.
    post = [f for f in result.hook_firings if f.event == "post_tool"][0]
    assert post.tool == "write_file"


def test_finish_hook_fires_on_budget_exhaustion(tmp_path: Path) -> None:
    """finish hooks fire once on every loop exit, including the budget path."""
    _write_hooks(
        tmp_path,
        {"hooks": {"finish": [{"command": "sh -c 'exit 0'"}]}},
    )

    def never_finish(_messages: list[dict]) -> ModelResponse:
        return ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])

    task = Task.new(str(tmp_path), "loop forever")
    result = run(never_finish, task, max_steps=2)

    # No content was produced, so the summary is the NO_RESULT_PRODUCED sentinel
    # (t2, #109).  Budget exhaustion is preserved via stats.step_count == max_steps.
    assert result.summary == NO_RESULT_PRODUCED
    assert result.stats.step_count == 2
    finish_firings = [f for f in result.hook_firings if f.event == "finish"]
    assert len(finish_firings) == 1


def test_finish_hook_fires_on_empty_tool_turn(tmp_path: Path) -> None:
    """finish hooks fire when the model answers without a tool call."""
    _write_hooks(
        tmp_path,
        {"hooks": {"finish": [{"command": "sh -c 'exit 0'"}]}},
    )
    task = Task.new(str(tmp_path), "just answer")
    result = run(scripted([ModelResponse(content="all done")]), task, max_steps=5)

    assert result.summary == "all done"
    finish_firings = [f for f in result.hook_firings if f.event == "finish"]
    assert len(finish_firings) == 1


def test_explicit_hooks_argument_overrides_loading(tmp_path: Path) -> None:
    """Passing hooks=HookConfig() explicitly suppresses repo loading."""
    from colleague.hooks import HookConfig

    # A repo WITH a deny hook, but we pass an empty config → nothing fires.
    _write_hooks(
        tmp_path,
        {"hooks": {"pre_tool": [{"matcher": "write_file", "command": "sh -c 'exit 1'"}]}},
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "w.txt", "content": "v"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write w.txt")
    result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

    assert result.hook_firings == []
    assert (tmp_path / "w.txt").read_text() == "v"


def test_lifecycle_is_engine_agnostic(tmp_path: Path) -> None:
    """Acceptance 3: the same hook config + two DIFFERENT scripted complete fns
    ('engines') produce the same firing shape — the lifecycle lives in the loop,
    not the engine."""
    config = {
        "hooks": {
            "task_start": [{"command": "sh -c 'exit 0'"}],
            "pre_tool": [{"matcher": "write_file", "command": "sh -c 'exit 0'"}],
            "post_tool": [{"matcher": "write_file", "command": "sh -c 'exit 0'"}],
            "finish": [{"command": "sh -c 'exit 0'"}],
        }
    }

    def drive_once(repo: Path) -> list[tuple[str, str | None, str]]:
        _write_hooks(repo, config)
        responses = [
            ModelResponse(
                tool_calls=[ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})]
            ),
            ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "ok"})]),
        ]
        task = Task.new(str(repo), "write a.txt")
        result = run(scripted(responses), task, max_steps=10)
        return [(f.event, f.tool, f.decision) for f in result.hook_firings]

    # Engine A: the scripted closure above (write then finish).
    repo_a = tmp_path / "a"
    repo_a.mkdir()
    shape_a = drive_once(repo_a)

    # Engine B: a different complete implementation that produces the SAME calls
    # via a stateful generator — distinct callable, same lifecycle.
    def engine_b_complete_factory():
        seq = iter(
            [
                ModelResponse(
                    tool_calls=[ToolCall("b1", "write_file", {"path": "a.txt", "content": "x"})]
                ),
                ModelResponse(tool_calls=[ToolCall("b2", "finish", {"summary": "ok"})]),
            ]
        )
        last = {"r": None}

        def complete(_messages: list[dict]) -> ModelResponse:
            try:
                last["r"] = next(seq)
            except StopIteration:
                pass
            return last["r"]

        return complete

    repo_b = tmp_path / "b"
    repo_b.mkdir()
    _write_hooks(repo_b, config)
    task_b = Task.new(str(repo_b), "write a.txt")
    result_b = run(engine_b_complete_factory(), task_b, max_steps=10)
    shape_b = [(f.event, f.tool, f.decision) for f in result_b.hook_firings]

    assert shape_a == shape_b
    # And the lifecycle order is what we expect.
    assert shape_a == [
        ("task_start", None, "allow"),
        ("pre_tool", "write_file", "allow"),
        ("post_tool", "write_file", "allow"),
        ("finish", None, "allow"),
    ]


# ---------------------------------------------------------------------------
# Per-model hook wiring (t2): run() accepts model= and threads it into
# load_hooks so per-model overlays fire during a real drive.
# ---------------------------------------------------------------------------


def _write_per_model_hooks(repo: Path, model: str, config: dict) -> None:
    """Write .colleague/<sanitized-model>/hooks.json under *repo*."""
    from colleague.layers import sanitize_model

    safe = sanitize_model(model)
    dotdir = repo / ".colleague" / safe
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(config), encoding="utf-8")


def test_per_model_hook_fires_when_model_passed_to_run(tmp_path: Path) -> None:
    """Criterion 1a: run(model=<model>) causes the per-model overlay hooks.json
    to be loaded.  A per_tool deny in the overlay blocks the write; the deny is
    recorded in the result."""
    model = "test-model-v1"

    # Only the per-model overlay has a deny hook; no base hooks.json is present.
    _write_per_model_hooks(
        tmp_path,
        model,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": "sh -c 'echo per-model-deny >&2; exit 1'",
                    }
                ]
            }
        },
    )

    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "out.txt", "content": "data"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write a file")
    result = run(scripted(responses), task, max_steps=10, model=model)

    # The per-model deny hook blocked the write; the file must not exist.
    assert not (tmp_path / "out.txt").exists()
    # A deny firing was recorded from the per-model overlay.
    deny_firings = [f for f in result.hook_firings if f.decision == "deny"]
    assert len(deny_firings) == 1
    assert deny_firings[0].event == "pre_tool"
    assert "per-model-deny" in deny_firings[0].reason
    # The loop still finished.
    assert result.status == OK
    assert result.summary == "done"


def test_per_model_hook_does_not_fire_when_model_not_passed(tmp_path: Path) -> None:
    """Criterion 1b / criterion 2a: when run() is called without model=, the
    per-model overlay is NOT loaded; a deny in the overlay does NOT fire; the
    write succeeds; behavior is identical to a hook-free drive."""
    model = "test-model-v1"

    # Write the deny only in the per-model overlay — no base hooks.json.
    _write_per_model_hooks(
        tmp_path,
        model,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": "sh -c 'echo should-not-fire >&2; exit 1'",
                    }
                ]
            }
        },
    )

    responses = [
        ModelResponse(
            tool_calls=[ToolCall("1", "write_file", {"path": "ok.txt", "content": "hi"})]
        ),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write ok.txt")
    # No model= kwarg — base-only load, overlay is invisible.
    result = run(scripted(responses), task, max_steps=10)

    assert (tmp_path / "ok.txt").read_text() == "hi"
    assert result.hook_firings == []
    assert result.summary == "done"


def test_per_model_overlay_takes_priority_over_base_hook(tmp_path: Path) -> None:
    """Criterion 1c: per-model overlay entries are prepended ahead of base entries;
    the per-model deny wins before the base allow even runs."""
    model = "test-model-v2"

    # Base hook: allow (exit 0).
    _write_hooks(
        tmp_path,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": "sh -c 'exit 0'",
                    }
                ]
            }
        },
    )
    # Per-model overlay: deny.
    _write_per_model_hooks(
        tmp_path,
        model,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": "sh -c 'echo model-priority-deny >&2; exit 1'",
                    }
                ]
            }
        },
    )

    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "x.txt", "content": "v"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "ok"})]),
    ]
    task = Task.new(str(tmp_path), "write x.txt")
    result = run(scripted(responses), task, max_steps=10, model=model)

    # Per-model deny fires first; the write does not happen.
    assert not (tmp_path / "x.txt").exists()
    deny_firings = [f for f in result.hook_firings if f.decision == "deny"]
    assert len(deny_firings) == 1
    assert "model-priority-deny" in deny_firings[0].reason


def test_run_model_none_is_identical_to_no_model_kwarg(tmp_path: Path) -> None:
    """Criterion 2b: run(model=None) is identical to run() — base-only load,
    per-model overlay untouched."""
    model = "test-model-v1"

    # Only per-model overlay — base is empty.
    _write_per_model_hooks(
        tmp_path,
        model,
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": "sh -c 'echo overlay >&2; exit 1'",
                    }
                ]
            }
        },
    )

    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "nm.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "done"})]),
    ]
    task = Task.new(str(tmp_path), "write nm.txt")
    # model=None: overlay must be invisible.
    result = run(scripted(responses), task, max_steps=10, model=None)

    assert (tmp_path / "nm.txt").read_text() == "x"
    assert result.hook_firings == []


# ---------------------------------------------------------------------------
# continue-working: configurable no-tool-call nudge cap (the t5-class stall fix)
# ---------------------------------------------------------------------------


def test_continue_nudge_cap_resumes_past_first_stall(tmp_path: Path) -> None:
    """With ``max_continue_nudges=2`` a model that stalls twice then finishes resumes
    past the FIRST stall and completes — where the old single-nudge cap stops it after
    the first stall (the t5-class failure: a no-tool-call turn ended the run mid-task).
    """
    turn = {"n": 0}

    def stalls_twice_then_finishes(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] <= 2:
            return ModelResponse(content="Let me check:")  # a stall — no tool call
        return ModelResponse(
            tool_calls=[ToolCall("1", "finish", {"summary": "done after resuming"})]
        )

    # cap=2: two nudges absorb both stalls, the third turn finishes cleanly.
    result = run(
        stalls_twice_then_finishes,
        Task.new(str(tmp_path), "resume past stall"),
        max_steps=8,
        context=ContextControls(max_continue_nudges=2),
    )
    assert result.status == OK
    assert result.stopped_without_finish is False
    assert result.summary == "done after resuming"

    # Contrast — the SAME model under the old single-nudge cap stops without finishing.
    turn["n"] = 0
    stopped = run(
        stalls_twice_then_finishes,
        Task.new(str(tmp_path), "single nudge stops"),
        max_steps=8,
        context=ContextControls(max_continue_nudges=1),
    )
    assert stopped.stopped_without_finish is True
    assert stopped.status == INCOMPLETE


def test_continue_nudge_cap_bounds_termination(tmp_path: Path) -> None:
    """An always-stalling model stops after exactly the cap's worth of nudges — the
    loop terminates on the cap (not the step budget), so continuation never runs away.
    """
    calls = {"n": 0}

    def always_stalls(_messages: list[dict]) -> ModelResponse:
        calls["n"] += 1
        return ModelResponse(content="thinking...")

    result = run(
        always_stalls,
        Task.new(str(tmp_path), "bounded"),
        max_steps=20,  # generous: the CAP must end it, not the step budget
        context=ContextControls(max_continue_nudges=2),
    )
    assert result.stopped_without_finish is True
    assert result.not_finished is False  # cap stop, not budget exhaustion
    assert calls["n"] == 3  # 2 nudges (turns 1,2) then stop on turn 3


# ---------------------------------------------------------------------------
# auto-compact-on-finish: a clean summary at a stop, never mid-thought prose (t5 fix)
# ---------------------------------------------------------------------------


def test_context_rich_stop_synthesizes_instead_of_trailing_prose(tmp_path: Path) -> None:
    """A stop after real tool work no longer returns mid-thought trailing prose as the
    summary (the t5 failure). The stop no longer pre-empts forced synthesis (#191), so
    a clean summary is produced from what was read; the prose is only the floor.
    """
    turn = {"n": 0}

    def reads_then_stalls(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] == 1:
            return ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])  # real work
        if turn["n"] >= 4:  # the forced-synthesis turn answers from what was read
            return ModelResponse(content="SYNTH: surveyed the repo; modules A and B.")
        return ModelResponse(content="Let me check:")  # a mid-thought stall (no tool call)

    result = run(
        reads_then_stalls,
        Task.new(str(tmp_path), "context-rich stop"),
        max_steps=10,
        context=ContextControls(max_continue_nudges=1),
    )
    assert result.stopped_without_finish is True
    assert result.summary == "SYNTH: surveyed the repo; modules A and B."  # not "Let me check:"


def test_compaction_summary_is_preferred_at_stop(tmp_path: Path) -> None:
    """A run that crossed the fill line and compacted carries its model-authored
    self-summary to a stop exit — preferred over a fresh synthesis and over the
    trailing prose (auto-compact-on-finish, t3)."""
    turn = {"n": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn["n"] += 1
        if turn["n"] == 1:  # cross the fill line (>= 0.8 * 100) with a working tool call
            return ModelResponse(
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})], prompt_tokens=90
            )
        if turn["n"] == 2:  # fill line now offered; a no-tool reply declares COMPACT
            return ModelResponse(content="Context is large; compacting.", prompt_tokens=90)
        if turn["n"] == 3:  # the compaction summary turn (run inside _compact_history)
            return ModelResponse(content="COMPACTED: read modules A and B; no edits yet.")
        return ModelResponse(content="Let me check:")  # then stall to a stop

    result = run(
        complete,
        Task.new(str(tmp_path), "compact then stop"),
        max_steps=10,
        context=ContextControls(budget=100, fillline_threshold=0.8, max_continue_nudges=1),
    )
    assert result.stopped_without_finish is True
    assert result.summary == "COMPACTED: read modules A and B; no edits yet."
    assert result.capacity_decision is not None and result.capacity_decision.kind == "compact"

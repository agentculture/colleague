"""Bounded agentic tool-loop: execution, termination, usage, errors (R3, h3)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from colleague.contract import NO_RESULT_PRODUCED, OK, Task
from colleague.loop import CompleteFn, ModelResponse, ToolCall, run


def scripted(responses: list[ModelResponse]) -> CompleteFn:
    """A complete() that returns each canned response in turn (then repeats last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


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


def _write_per_model_hooks(repo: Path, model: str, config: dict) -> None:
    """Write .colleague/<sanitized-model>/hooks.json under *repo*."""
    from colleague.layers import sanitize_model

    safe = sanitize_model(model)
    dotdir = repo / ".colleague" / safe
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(config), encoding="utf-8")


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

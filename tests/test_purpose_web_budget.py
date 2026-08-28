"""Tests for t7 — parent-side reporting + one work-item-wide web budget across
purpose children (purpose-tools-associate-seat, spec c33/h32, c36/h34, c37).

Acceptance criteria covered here (see docs/plans/2026-08-28-purpose-tools-
associate-seat.md, task t7):

(a) ONE work-item-wide web budget: a purpose child inherits
    ``COLLEAGUE_WEB_MAX_CALLS - parent.web_calls`` as its OWN effective cap
    (:class:`~colleague.subagents.ChildSpec.web_calls_remaining`), and on
    return its ``web_calls``/``web_failed`` fold onto the parent's executor
    counters (:func:`colleague.webbudget.fold_child_counts`).

(b) Parent-side URL reporting: the parent's ``Step.result`` for a
    ``web_survey`` purpose call ends with a ``urls fetched:`` block listing
    every url from the child's OWN web steps, verbatim; the parent artifact's
    ``web:`` report line (:func:`colleague.web_schemas.summary_line`)
    includes them; and a ``.colleague/hooks.json`` ``pre_tool`` deny on
    ``web`` makes the child's fetches fail — the digest says so.

(c) ``config.reasoning_effort_purposes``/``reasoning_effort`` (the
    kill-switch) reach the purpose executor at its build site
    (:func:`colleague.purpose_schemas._thread_effort_config`), so e.g.
    ``reasoning_effort_purposes={'review': 'off'}`` reaches a ``review``
    child's rung.

Every test drives the REAL ``colleague.loop.run`` for both parent and child
(the same path production engines use — mirrors ``tests/test_subagent_e2e.py``'s
scripting pattern), with ``colleague.web.run_web`` faked so no real webglass
process ever launches.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from colleague import subagents, web, web_schemas
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import ModelResponse, Spawns, ToolCall, run
from colleague.subagents import ChildSpec, make_batch_spawn, make_spawn
from colleague.tools import ToolExecutor

# ---------------------------------------------------------------------------
# Shared scripting helpers (mirrors tests/test_subagent_e2e.py's `_scripted`).
# ---------------------------------------------------------------------------


def _scripted(turns: list[ModelResponse]):
    """Replay ``turns`` in order, repeating the last one indefinitely."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return complete


def _make_scout_engine(pages: int):
    """A fake child engine that fetches *pages* urls via the REAL ``web`` tool
    (through the REAL ``colleague.loop.run``), then finishes — so hooks,
    ``webbudget``, and ``Step`` recording all behave exactly as production."""

    class _ScoutEngine:
        def work(self, task: Task, config: Any) -> Any:
            calls = [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            f"w{i}",
                            "web",
                            {"verb": "page read", "url": f"https://example.com/{task.id}/{i}"},
                        )
                    ]
                )
                for i in range(pages)
            ]
            calls.append(
                ModelResponse(tool_calls=[ToolCall("fin", "finish", {"summary": "fetched"})])
            )
            return run(
                _scripted(calls),
                task,
                max_steps=config.max_steps,
                model=config.model,
                spawns=Spawns(single=config.subagent_spawn, batch=config.subagent_batch_spawn),
            )

    return _ScoutEngine()


_SUCCESS_ENVELOPE = 'exit=0\n{"operation_id": "op", "lifecycle_state": "succeeded", "content": {}}'


@pytest.fixture
def fake_webglass(monkeypatch: pytest.MonkeyPatch) -> None:
    """webglass is 'installed' and every call succeeds with a minimal envelope."""
    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/webglass" if name == "webglass" else None
    )
    monkeypatch.setattr(web, "run_web", lambda verb, args, root: _SUCCESS_ENVELOPE)
    monkeypatch.delenv(web_schemas.WEB_ENV, raising=False)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _parent_config_and_task(repo: Path, instruction: str) -> tuple[Any, Task]:
    config = EngineConfig.resolve()
    task = Task.new(str(repo), instruction, engine="mock")
    config.subagent_spawn = make_spawn(str(repo), config, "mock", parent_task_id=task.id)
    config.subagent_batch_spawn = make_batch_spawn(
        str(repo), config, "mock", parent_task_id=task.id
    )
    return config, task


# ---------------------------------------------------------------------------
# (a) ONE work-item-wide web budget across purpose children
# ---------------------------------------------------------------------------


def test_web_calls_remaining_none_is_byte_identical_for_manual_subagents() -> None:
    """The new ``ChildSpec`` field defaults to ``None`` — today's per-executor
    behaviour, unchanged for every manual ``subagent``/``subagents`` call."""
    assert ChildSpec().web_calls_remaining is None


def test_three_web_survey_scouts_share_one_work_item_wide_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_webglass: None
) -> None:
    """COLLEAGUE_WEB_MAX_CALLS=5, three ``web_survey`` scouts each fetching 2
    pages: the 6th call is refused and the parent's ``result.stats.web_calls``
    is exactly 5 (2 + 2 + 1) — the third scout's 2nd call is the refused one."""
    monkeypatch.setenv("COLLEAGUE_WEB_MAX_CALLS", "5")
    monkeypatch.setattr(subagents.registry, "load", lambda _name: _make_scout_engine(2))

    repo = _repo(tmp_path)
    config, task = _parent_config_and_task(repo, "survey the web three times")
    parent_complete = _scripted(
        [
            ModelResponse(tool_calls=[ToolCall("s1", "web_survey", {"question": "q1"})]),
            ModelResponse(tool_calls=[ToolCall("s2", "web_survey", {"question": "q2"})]),
            ModelResponse(tool_calls=[ToolCall("s3", "web_survey", {"question": "q3"})]),
            ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "surveyed"})]),
        ]
    )

    result = run(
        parent_complete,
        task,
        max_steps=20,
        spawns=Spawns(single=config.subagent_spawn, batch=config.subagent_batch_spawn),
    )

    assert result.status == OK
    assert result.stats.web_calls == 5

    survey_steps = [s for s in result.steps if s.tool == "web_survey"]
    assert len(survey_steps) == 3
    # The third scout's 2nd page (the overall 6th web call) was refused —
    # the parent's rendered result names it, annotated as failed.
    third = survey_steps[2].result
    assert "urls fetched:" in third
    assert "(failed)" in third


# ---------------------------------------------------------------------------
# (b) parent-side URL reporting + the hook-deny digest
# ---------------------------------------------------------------------------


def test_web_survey_result_ends_with_urls_fetched_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_webglass: None
) -> None:
    monkeypatch.setattr(subagents.registry, "load", lambda _name: _make_scout_engine(2))

    repo = _repo(tmp_path)
    config, task = _parent_config_and_task(repo, "survey the web")
    parent_complete = _scripted(
        [
            ModelResponse(tool_calls=[ToolCall("s1", "web_survey", {"question": "q1"})]),
            ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "surveyed"})]),
        ]
    )

    result = run(
        parent_complete,
        task,
        max_steps=10,
        spawns=Spawns(single=config.subagent_spawn, batch=config.subagent_batch_spawn),
    )

    survey_step = next(s for s in result.steps if s.tool == "web_survey")
    lines = survey_step.result.splitlines()
    idx = lines.index("urls fetched:")
    url_lines = lines[idx + 1 :]
    assert len(url_lines) == 2
    assert all("https://example.com/" in line for line in url_lines)
    assert survey_step.result.rstrip().endswith(url_lines[-1])

    # The artifact's web: report line folds the purpose-embedded urls in too.
    line = web_schemas.summary_line(result.steps)
    assert line is not None
    assert line.startswith("web: 2 fetch(es), 0 failed")


def test_pre_tool_hook_deny_on_web_fails_the_childs_fetch_and_the_digest_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_webglass: None
) -> None:
    """A ``.colleague/hooks.json`` ``pre_tool`` deny on ``web`` (matcher
    ``"web"``, never ``"web_survey"`` — the parent's own purpose call is
    untouched) makes the child's own ``web`` fetch fail; the parent's
    rendered ``urls fetched:`` block marks it failed, and the artifact's
    ``web:`` report line counts it."""
    monkeypatch.setattr(subagents.registry, "load", lambda _name: _make_scout_engine(1))

    repo = _repo(tmp_path)
    dotdir = repo / ".colleague"
    dotdir.mkdir()
    (dotdir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "pre_tool": [
                        {"matcher": "web", "command": "sh -c 'echo denied web calls >&2; exit 1'"}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    config, task = _parent_config_and_task(repo, "survey the web, denied")
    parent_complete = _scripted(
        [
            ModelResponse(tool_calls=[ToolCall("s1", "web_survey", {"question": "q1"})]),
            ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "surveyed"})]),
        ]
    )

    result = run(
        parent_complete,
        task,
        max_steps=10,
        spawns=Spawns(single=config.subagent_spawn, batch=config.subagent_batch_spawn),
    )

    survey_step = next(s for s in result.steps if s.tool == "web_survey")
    assert "urls fetched:" in survey_step.result
    assert "(failed)" in survey_step.result

    line = web_schemas.summary_line(result.steps)
    assert line is not None
    assert "1 failed" in line


# ---------------------------------------------------------------------------
# (c) purpose_effort_overrides / effort_kill_switch reach the executor
# ---------------------------------------------------------------------------


class _CapturingEngine:
    """A fake engine that records the child config and returns a canned result."""

    def __init__(self) -> None:
        self.configs: list[Any] = []

    def work(self, task: Task, config: Any) -> Any:
        self.configs.append(config)
        from colleague.contract import TaskResult

        return TaskResult(task_id=task.id, status=OK, summary="child done")


def test_reasoning_effort_purposes_override_reaches_the_review_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eng = _CapturingEngine()
    monkeypatch.setattr(subagents.registry, "load", lambda _name: eng)

    parent = EngineConfig.resolve()
    parent.reasoning_effort_purposes = {"review": "off"}
    spawn = make_spawn(str(tmp_path), parent, "mock")
    executor = ToolExecutor(str(tmp_path), spawn=spawn)

    outcome = executor.execute("review", {"diff_ref": "HEAD~1"})

    assert len(eng.configs) == 1
    assert getattr(eng.configs[0], "reasoning_effort_seat", None) == "off"
    assert "refused" not in outcome.result.lower()


def test_reasoning_effort_kill_switch_overrides_the_purpose_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reasoning_effort='default'`` (the global kill-switch) beats the
    ``PURPOSE_TABLE`` row too — ``plan`` (normally ``medium``) runs at the
    kill-switch floor."""
    eng = _CapturingEngine()
    monkeypatch.setattr(subagents.registry, "load", lambda _name: eng)

    parent = EngineConfig.resolve()
    parent.reasoning_effort = "default"
    spawn = make_spawn(str(tmp_path), parent, "mock")
    executor = ToolExecutor(str(tmp_path), spawn=spawn)

    executor.execute("plan", {"goal": "ship it"})

    assert len(eng.configs) == 1
    from colleague import efforttables

    expected = efforttables.resolve_purpose_effort(
        kill_switch=True, purpose_override=None, purpose="plan"
    )
    assert getattr(eng.configs[0], "reasoning_effort_seat", None) == expected

"""Plan t13 (delegation-follow-ups-a7-p3-hire, covers c38/h22): the
``assign_to_colleague`` handler + the ``TaskResult.hires`` block.

Acceptance criteria under test:

1. ``assign_to_colleague(agent_id, task, acceptance)`` spawns ONE child
   through ``executor._spawn`` with the hire's base role NAME (the seam the
   spawn path actually accepts — see :mod:`colleague.hire_assign`'s module
   docstring), ``purpose="assign_to_colleague"``,
   ``effort=effort.ROLE_TABLE[base]``, ``charges_budget=not
   roles.is_read_only(base)`` and ``web_calls_remaining`` exactly as
   ``purpose_schemas._record`` folds it; the result renders like a purpose
   result including the ``urls fetched:`` block, and the authored
   ``prompt_fragment`` rides the child's brief.
2. An unknown or expired ``agent_id`` returns ``no live hire: <id>`` as the
   tool RESULT (one readable step, never an exception); ``TaskResult.hires``
   (omit-when-empty) records every Hire plus its assignments and round-trips
   through the artifact dict.
3. A 2001-char prompt at hire time is refused readably (h22 re-tested
   end-to-end): the roster stays empty and a subsequent assign to the never-
   minted id is the same readable refusal.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from colleague import hire_assign, webbudget
from colleague.contract import OK, SubResult, TaskResult
from colleague.effort import ROLE_TABLE
from colleague.hire import MAX_PROMPT_CHARS, HireError, Roster, mint_hire
from colleague.roles import is_read_only
from colleague.tools import ToolError, ToolExecutor


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


def _mint(**overrides):
    kwargs = dict(
        agent_id="hire-1",
        hirer_id="cortex-0",
        base_role="scout",
        purpose="survey the tests",
        when="whenever a multi-file survey is needed",
        prompt_fragment="You are a hired scout with a standing brief.",
        task_id="task-42",
        created_step=3,
    )
    kwargs.update(overrides)
    return mint_hire(**kwargs)


def _armed(tmp_path, spawn, hire=None) -> ToolExecutor:
    """An executor whose roster (the t12 ``hire_roster`` seam) holds *hire*."""
    ex = _executor(tmp_path, spawn)
    roster = Roster()
    if hire is not None:
        roster.add(hire)
    ex.hire_roster = roster
    return ex


# ---------------------------------------------------------------------------
# AC1 — the spawn contract: fixed base role, rung, budget charge, web budget
# ---------------------------------------------------------------------------


def test_dispatch_binds_exactly_the_assign_name(tmp_path) -> None:
    handlers = hire_assign.dispatch(_executor(tmp_path, _Recorder()))
    assert set(handlers) == {"assign_to_colleague"}


@pytest.mark.parametrize("base", sorted(ROLE_TABLE))
def test_assign_spawns_one_child_with_the_hires_base_role(tmp_path, base: str) -> None:
    rec = _Recorder()
    hire = _mint(base_role=base)
    ex = _armed(tmp_path, rec, hire)
    expected_web = webbudget.remaining_for_child(ex)

    ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "count the tests"})

    assert len(rec.calls) == 1
    call = rec.calls[0]
    # The base role NAME — the seam run_subagent/load_role actually accepts.
    assert call["role"] == base
    assert call["effort"] == ROLE_TABLE[base]
    assert call["charges_budget"] is (not is_read_only(base))
    assert call["web_calls_remaining"] == expected_web
    assert call["purpose"] == "assign_to_colleague"
    # The model never picks a backend or a model id.
    assert call["engine"] is None
    assert call["model"] is None


def test_assignment_brief_carries_the_authored_prompt_and_acceptance(tmp_path) -> None:
    rec = _Recorder()
    hire = _mint()
    ex = _armed(tmp_path, rec, hire)
    ex.execute(
        "assign_to_colleague",
        {
            "agent_id": "hire-1",
            "task": "count the tests",
            "acceptance": ["a number is reported", "the command is named"],
        },
    )
    brief = rec.calls[0]["instruction"]
    # The authored standing prompt reaches the child through its brief (the
    # documented seam), followed by the scoped task and acceptance criteria.
    assert brief.startswith(hire.prompt_fragment)
    assert "count the tests" in brief
    assert "  - a number is reported" in brief
    assert "  - the command is named" in brief


def test_result_renders_like_a_purpose_result_with_urls_block(tmp_path) -> None:
    sub = SubResult(
        task_id="c7",
        engine="mock",
        model="m",
        status=OK,
        summary="did the thing",
        changed_files=["x.py"],
    )
    sub.web_urls = ["https://a.example/", "https://b.example/"]
    sub.web_urls_failed = ["https://b.example/"]
    ex = _armed(tmp_path, _Recorder(sub), _mint())

    outcome = ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})

    assert outcome.result.startswith("assign_to_colleague[mock/m] ok: did the thing")
    assert "changed files: x.py" in outcome.result
    assert "urls fetched:" in outcome.result
    assert "  - https://a.example/" in outcome.result
    assert "  - https://b.example/ (failed)" in outcome.result


def test_child_folds_onto_the_parent_exactly_as_a_purpose_child_does(tmp_path) -> None:
    ex = _armed(tmp_path, _Recorder(), _mint())
    args = {"agent_id": "hire-1", "task": "t"}
    ex.execute("assign_to_colleague", args)
    # purpose_schemas._record's fold: sub_results + changed set + step arguments.
    assert [s.task_id for s in ex.sub_results] == ["child-1"]
    assert "a.py" in ex.changed
    assert args["served_model"] == "m"
    assert args["purpose_child_id"] == "child-1"


def test_a_refused_launch_is_a_readable_result_not_a_crash(tmp_path) -> None:
    def boom(instruction: str, **kwargs: Any) -> SubResult:
        raise RuntimeError("depth limit exceeded")

    ex = _armed(tmp_path, boom, _mint())
    outcome = ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    assert outcome.result == "assign_to_colleague refused: depth limit exceeded"


def test_missing_required_arguments_are_a_clean_tool_error(tmp_path) -> None:
    rec = _Recorder()
    ex = _armed(tmp_path, rec, _mint())
    with pytest.raises(ToolError):
        ex.execute("assign_to_colleague", {"task": "t"})
    with pytest.raises(ToolError):
        ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "  "})
    assert rec.calls == []


# ---------------------------------------------------------------------------
# AC2 — unknown/expired hires refuse readably; the hires block round-trips
# ---------------------------------------------------------------------------


def test_unknown_agent_id_returns_no_live_hire(tmp_path) -> None:
    rec = _Recorder()
    ex = _armed(tmp_path, rec, _mint())
    outcome = ex.execute("assign_to_colleague", {"agent_id": "ghost", "task": "t"})
    assert outcome.result == "no live hire: ghost"
    assert rec.calls == []


def test_expired_hire_returns_no_live_hire(tmp_path) -> None:
    from dataclasses import replace

    rec = _Recorder()
    expired = replace(_mint(), status="expired")
    ex = _armed(tmp_path, rec, expired)
    outcome = ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    assert outcome.result == "no live hire: hire-1"
    assert rec.calls == []


def test_handler_works_standalone_without_a_t12_roster(tmp_path) -> None:
    """No ``hire_roster`` on the executor (t12 not merged): the handler builds
    one lazily under the SAME attribute name and refuses readably."""
    ex = _executor(tmp_path, _Recorder())
    assert not hasattr(ex, "hire_roster")
    outcome = ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    assert outcome.result == "no live hire: hire-1"
    assert isinstance(ex.hire_roster, Roster)


def test_hires_block_records_every_hire_plus_assignments(tmp_path) -> None:
    hire = _mint()
    ex = _armed(tmp_path, _Recorder(), hire)
    # A second, never-assigned hire must ALSO appear (with empty assignments).
    idle = _mint(agent_id="hire-2", base_role="writer")
    ex.hire_roster.add(idle)

    ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "u"})

    block = hire_assign.hires_block(ex)
    assert [e["agent_id"] for e in block] == ["hire-1", "hire-2"]
    first = block[0]
    # The Hire's full to_dict — the authored prompt TEXT rides the artifact.
    for key, value in hire.to_dict().items():
        assert first[key] == value
    assert first["assignments"] == [
        {"task_id": "child-1", "status": OK, "changed_files": ["a.py"]},
        {"task_id": "child-1", "status": OK, "changed_files": ["a.py"]},
    ]
    assert block[1]["assignments"] == []


def test_hires_block_is_empty_without_a_roster(tmp_path) -> None:
    assert hire_assign.hires_block(_executor(tmp_path, _Recorder())) == []


def test_task_result_hires_round_trips_and_omits_when_empty(tmp_path) -> None:
    ex = _armed(tmp_path, _Recorder(), _mint())
    ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    hires = hire_assign.hires_block(ex)

    result = TaskResult(task_id="tr-1", status=OK, summary="s", hires=hires)
    d = result.to_dict()
    assert d["hires"] == hires
    # The serialized block never aliases the in-memory entries.
    assert d["hires"] is not hires
    assert d["hires"][0] is not hires[0]
    assert d["hires"][0]["assignments"] is not hires[0]["assignments"]

    rebuilt = TaskResult.from_dict(d)
    assert rebuilt.hires == hires
    assert rebuilt.to_dict() == d

    # Omit-when-empty: a hire-less result carries NO key (bare-run pins hold).
    bare = TaskResult(task_id="tr-2", status=OK, summary="s")
    assert "hires" not in bare.to_dict()
    assert TaskResult.from_dict(bare.to_dict()).hires == []


# ---------------------------------------------------------------------------
# AC3 — h22 end-to-end: a 2001-char prompt is refused readably at hire time
# ---------------------------------------------------------------------------


def test_over_cap_prompt_is_refused_readably_at_hire_time(tmp_path) -> None:
    with pytest.raises(HireError) as excinfo:
        _mint(prompt_fragment="x" * (MAX_PROMPT_CHARS + 1))
    message = str(excinfo.value)
    assert str(MAX_PROMPT_CHARS + 1) in message
    assert str(MAX_PROMPT_CHARS) in message
    assert "Traceback" not in message

    # End-to-end: nothing was minted, so assigning to the id refuses readably.
    ex = _armed(tmp_path, _Recorder())
    outcome = ex.execute("assign_to_colleague", {"agent_id": "hire-1", "task": "t"})
    assert outcome.result == "no live hire: hire-1"

"""Plan t12 (delegation-follow-ups-a7-p3-hire, covers c18/h9/c40/h24): the
``hire_colleague`` handler — the bounded two-round negotiation on the
tools-off completion seam, with the mock engine's deterministic candidate rule.

Acceptance criteria under test:

1. At most 2 candidate rounds, each ONE tools-off completion
   (``engine.make_complete(seat_config, tools=[])`` — the deepthink /
   senses-loop seam) on the cortex seat, parsing
   ``accept | amend(purpose, when) | decline``; accept or amend-then-accept
   mints a :class:`colleague.hire.Hire` on ``executor.hire_roster``; two
   declines or a malformed second reply return ``not hired: <reason>`` with
   the roster unchanged and EXACTLY 2 completions made.
2. The mock engine's candidate rule is deterministic: accept unless the
   proposed purpose contains ``'decline'``; amend when it contains
   ``'amend'`` (decline wins when both appear).
3. A refused hire (roster cap, over-cap when/prompt, unknown base) is a
   readable tool result, never an exception (h30); the caller's
   ``step_count`` advances by 1 per hire call (a hire call is ONE ordinary
   tool step in the loop).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from colleague import effort, hire, hire_dispatch
from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.contract import Task
from colleague.engines.mock import MockEngine
from colleague.hire import Roster
from colleague.loop import ModelResponse, ToolCall, run
from colleague.tools import ToolError, ToolExecutor

_ARGS: dict[str, Any] = {
    "purpose": "survey wide code surfaces",
    "when": "whenever a brief spans more than five files",
    "base_role": "scout",
    "prompt": "You survey code and report digests with citations.",
}


class _FakeEngine:
    """A vllm-shaped engine double: ``make_complete`` returns a scripted
    completion and records every call's config/tools plus each sent request."""

    name = "fake"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[Any, Optional[list]]] = []
        self.sent: list[list[dict[str, Any]]] = []

    def make_complete(self, config: Any, tools: Optional[list] = None):
        self.calls.append((config, tools))

        def complete(messages: list[dict[str, Any]]) -> Any:
            self.sent.append(messages)
            return SimpleNamespace(content=self.replies.pop(0))

        return complete


def _cfg(hire_armed: bool = True, reasoning_effort: Optional[str] = None) -> SimpleNamespace:
    return SimpleNamespace(hire=hire_armed, reasoning_effort=reasoning_effort)


def _executor(tmp_path, engine, cfg=None) -> ToolExecutor:
    def _spawn(*_a: Any, **_k: Any):  # pragma: no cover - negotiation must not spawn
        raise AssertionError("hire_colleague must never spawn a child")

    _spawn.parent_config = cfg if cfg is not None else _cfg()
    _spawn.parent_engine = "fake"
    ex = ToolExecutor(tmp_path, spawn=_spawn)
    ex.hire_engine_loader = lambda _name: engine
    return ex


# ---------------------------------------------------------------------------
# AC1 — the bounded two-round negotiation on the tools-off seam
# ---------------------------------------------------------------------------


def test_accept_round_one_mints_a_hire_with_one_completion(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("hired: hire-1")
    assert len(engine.sent) == 1
    roster = ex.hire_roster
    assert isinstance(roster, Roster)
    minted = roster.get("hire-1")
    assert minted is not None
    assert minted.purpose == _ARGS["purpose"]
    assert minted.when == _ARGS["when"]
    assert minted.base_role == "scout"
    assert minted.status == "live"


def test_each_round_is_one_tools_off_completion(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    _executor(tmp_path, engine).execute("hire_colleague", dict(_ARGS))
    # ONE make_complete bind, explicit tools=[] (the deepthink h2 invariant).
    assert len(engine.calls) == 1
    assert engine.calls[0][1] == []


def test_candidate_effort_is_the_role_table_row_for_the_base_role(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    _executor(tmp_path, engine).execute("hire_colleague", dict(_ARGS))
    seat_config = engine.calls[0][0]
    assert seat_config.reasoning_effort_seat == effort.ROLE_TABLE["scout"]


def test_kill_switch_sends_no_effort_for_the_candidate_turn(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    cfg = _cfg(reasoning_effort=effort.DEFAULT_SENTINEL)
    _executor(tmp_path, engine, cfg).execute("hire_colleague", dict(_ARGS))
    assert engine.calls[0][0].reasoning_effort_seat is None


def test_amend_then_accept_mints_the_amended_terms(tmp_path) -> None:
    engine = _FakeEngine(
        ["amend: purpose=broader repo surveys; when=only on multi-file briefs", "accept"]
    )
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("hired: hire-1")
    assert len(engine.sent) == 2
    minted = ex.hire_roster.get("hire-1")
    assert minted.purpose == "broader repo surveys"
    assert minted.when == "only on multi-file briefs"


def test_two_declines_is_not_hired_with_exactly_two_completions(tmp_path) -> None:
    engine = _FakeEngine(["decline: too busy", "decline: still too busy"])
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("not hired:")
    assert "still too busy" in outcome.result
    assert len(engine.sent) == 2
    assert getattr(ex, "hire_roster", None) is None or len(ex.hire_roster) == 0


def test_decline_then_accept_mints_the_original_terms(tmp_path) -> None:
    engine = _FakeEngine(["decline: convince me", "accept"])
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("hired: hire-1")
    assert len(engine.sent) == 2
    assert ex.hire_roster.get("hire-1").purpose == _ARGS["purpose"]


def test_malformed_second_reply_is_not_hired_with_exactly_two_completions(tmp_path) -> None:
    engine = _FakeEngine(["amend: purpose=x; when=y", "banana banana banana"])
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("not hired:")
    assert "malformed" in outcome.result
    assert len(engine.sent) == 2
    assert getattr(ex, "hire_roster", None) is None or len(ex.hire_roster) == 0


def test_a_second_amend_is_malformed_never_a_third_round(tmp_path) -> None:
    engine = _FakeEngine(["amend: purpose=a; when=b", "amend: purpose=c; when=d", "accept"])
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("not hired:")
    assert len(engine.sent) == 2  # the bound: never a 3rd completion


def test_amend_parse_requires_both_terms_non_empty() -> None:
    """Sonar S6019: the old one-regex amend parse used a LAZY ``(.*?)`` against
    a ``(?:; when=|$)`` alternation, so the purpose group could satisfy itself
    with ZERO repetitions — ``purpose=`` with no value parsed as a successful
    (empty) amendment. Both terms are now sliced to the next ``;`` (or the end
    of the line) and BOTH must be non-empty."""
    assert hire_dispatch._parse_reply(
        "amend: purpose=audit one package; when=each package", allow_amend=True
    ) == ("amend", "audit one package", "each package")
    # An empty purpose is malformed, never an empty-purpose amendment.
    verdict, _, _ = hire_dispatch._parse_reply("amend: purpose=; when=x", allow_amend=True)
    assert verdict == "malformed"
    # A dropped when clause is malformed (Qodo #469/5) — a live hire is never
    # minted without its agreed clause.
    verdict, _, _ = hire_dispatch._parse_reply("amend: purpose=x", allow_amend=True)
    assert verdict == "malformed"


def test_dispatch_binds_exactly_the_hire_colleague_name(tmp_path) -> None:
    handlers = hire_dispatch.dispatch(_executor(tmp_path, _FakeEngine([])))
    assert set(handlers) == {"hire_colleague"}


# ---------------------------------------------------------------------------
# AC2 — the mock engine's deterministic candidate rule
# ---------------------------------------------------------------------------


def _mock_executor(tmp_path, cfg=None) -> ToolExecutor:
    ex = _executor(tmp_path, MockEngine(), cfg)
    ex._spawn.parent_engine = "mock"
    return ex


def test_mock_candidate_accepts_a_plain_purpose(tmp_path) -> None:
    ex = _mock_executor(tmp_path)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("hired: hire-1")
    assert ex.hire_roster.get("hire-1").purpose == _ARGS["purpose"]


def test_mock_candidate_amends_when_purpose_contains_amend(tmp_path) -> None:
    ex = _mock_executor(tmp_path)
    args = dict(_ARGS, purpose="please amend the survey terms")
    outcome = ex.execute("hire_colleague", args)
    assert outcome.result.startswith("hired: hire-1")
    minted = ex.hire_roster.get("hire-1")
    assert minted.purpose == "please amend the survey terms (amended)"
    assert minted.when == _ARGS["when"]


def test_mock_candidate_declines_when_purpose_contains_decline(tmp_path) -> None:
    ex = _mock_executor(tmp_path)
    args = dict(_ARGS, purpose="a role you will decline")
    outcome = ex.execute("hire_colleague", args)
    assert outcome.result.startswith("not hired:")
    assert getattr(ex, "hire_roster", None) is None or len(ex.hire_roster) == 0


def test_mock_candidate_decline_wins_over_amend(tmp_path) -> None:
    ex = _mock_executor(tmp_path)
    args = dict(_ARGS, purpose="amend or decline this")
    outcome = ex.execute("hire_colleague", args)
    assert outcome.result.startswith("not hired:")


# ---------------------------------------------------------------------------
# AC3 — readable refusals (h30) + one step per hire call
# ---------------------------------------------------------------------------


def test_unknown_base_role_is_a_readable_result_and_costs_no_completion(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    outcome = _executor(tmp_path, engine).execute("hire_colleague", dict(_ARGS, base_role="wizard"))
    assert outcome.result.startswith("not hired:")
    assert "wizard" in outcome.result
    assert engine.sent == []


def test_over_cap_when_is_a_readable_result(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    outcome = _executor(tmp_path, engine).execute(
        "hire_colleague", dict(_ARGS, when="w" * (hire.MAX_WHEN_CHARS + 1))
    )
    assert outcome.result.startswith("not hired:")
    assert engine.sent == []


def test_over_cap_prompt_is_a_readable_result(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    outcome = _executor(tmp_path, engine).execute(
        "hire_colleague", dict(_ARGS, prompt="p" * (hire.MAX_PROMPT_CHARS + 1))
    )
    assert outcome.result.startswith("not hired:")
    assert engine.sent == []


def test_roster_cap_is_a_readable_result(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    ex = _executor(tmp_path, engine)
    roster = Roster()
    for i in range(MAX_SUBAGENT_FANOUT):
        roster.add(
            hire.mint_hire(
                agent_id=f"hire-{i + 1}",
                hirer_id="cortex",
                base_role="scout",
                purpose="p",
                when="w",
                prompt_fragment="pf",
                task_id="t",
                created_step=0,
            )
        )
    ex.hire_roster = roster
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("not hired:")
    assert engine.sent == []
    assert len(ex.hire_roster) == MAX_SUBAGENT_FANOUT


def test_over_cap_amended_when_is_a_readable_result(tmp_path) -> None:
    long_when = "w" * (hire.MAX_WHEN_CHARS + 1)
    engine = _FakeEngine([f"amend: purpose=x; when={long_when}", "accept"])
    ex = _executor(tmp_path, engine)
    outcome = ex.execute("hire_colleague", dict(_ARGS))
    assert outcome.result.startswith("not hired:")
    assert getattr(ex, "hire_roster", None) is None or len(ex.hire_roster) == 0


def test_unarmed_hire_is_one_readable_tool_error_step(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    ex = _executor(tmp_path, engine, _cfg(hire_armed=False))
    with pytest.raises(ToolError):
        ex.execute("hire_colleague", dict(_ARGS))
    assert engine.sent == []


def test_missing_required_argument_is_a_clean_tool_error(tmp_path) -> None:
    engine = _FakeEngine(["accept"])
    ex = _executor(tmp_path, engine)
    with pytest.raises(ToolError):
        ex.execute("hire_colleague", {"purpose": "p"})
    assert engine.sent == []


def test_hire_call_advances_step_count_by_one(tmp_path) -> None:
    """Through the real loop: one hire call = ONE step, then finish = one more."""
    engine = _FakeEngine(["accept"])
    ex = _executor(tmp_path, engine)
    turns = [
        ModelResponse(
            content="hiring",
            tool_calls=[ToolCall("h1", "hire_colleague", dict(_ARGS))],
            finish_reason="stop",
        ),
        ModelResponse(
            content="done",
            tool_calls=[ToolCall("h2", "finish", {"summary": "hired a scout"})],
            finish_reason="stop",
        ),
    ]
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    task = Task(id="t-hire", repo_path=str(tmp_path), instruction="hire a scout")
    result = run(complete, task, max_steps=5, executor=ex)
    assert [s.tool for s in result.steps] == ["hire_colleague", "finish"]
    assert result.stats.step_count == 2
    assert ex.hire_roster.get("hire-1") is not None

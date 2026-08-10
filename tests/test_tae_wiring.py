"""Thought->action->evaluation control-loop WIRING (plan task t13).

Plan: docs/plans/2026-08-09-post-387-program-evaluator-rename-self-learn-speci.md,
task t13 (covers c25, h18, c29, h22, c33, h26, h28). Issue #397.

These are INTEGRATION tests: the unit semantics of the control decisions are
already pinned by ``tests/test_tae_control.py`` (the pure module) and by the
four contract suites. What is proven here is that the running loop actually
consults them, at the right seams, in the right order:

* criterion 2 — the evaluator is invoked ONLY at the enumerated boundaries; a
  run whose worker only reads/lists never reaches the evaluator at all;
* criterion 3 — ``rethink`` routes to the front (new, superseding thought),
  ``replan`` routes to the worker under the UNCHANGED thought, and the host's
  approval policy remains the execution gate on every route;
* criterion 5 — with the mode armed, flight guidance goes to the FRONT as an
  observation (never a raw worker turn), and a mid-run objective change
  produces a new/superseding thought whose id the worker's next consequential
  action names;
* criterion 6 — mid-action supersession is complete-then-re-evaluate, and
  evaluator seat loss is bounded-retry-then-block with a legible reason;
* criterion 7 — a presence-mode utterance implying an objective produces NO
  ActionProposal, and the front's two cadences are wired.

Plus the two standing invariants: the front/evaluator seats are offered
``tools=[]`` on every completion, and an UNARMED run is byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from colleague import tae_loop
from colleague.config import EngineConfig, EvaluationSeats, SeatConfig
from colleague.contract import OK, Task
from colleague.evaluation import Evaluation
from colleague.ledger import KIND_ACTION, KIND_EVALUATION, KIND_THOUGHT
from colleague.loop import ContextControls, ModelResponse, ToolCall, run
from colleague.policy import Policy
from colleague.tae_control import EVALUATOR_BOUNDARIES, EvaluatorLossPolicy
from colleague.tae_loop import EvaluatorSeat, FrontSeat, TaeSession
from colleague.thought import PresenceUtterance, Thought

# ---------------------------------------------------------------------------
# Scripted seat doubles — a make_complete seam recording exactly what it was
# offered, so the tools-off invariant is provable rather than asserted.
# ---------------------------------------------------------------------------


class ScriptedSeat:
    """A ``make_complete(config, tools=...)`` double returning canned text.

    Each scripted reply is either a string (the completion's ``content``) or an
    exception instance (raised, simulating seat loss). Exhausting the script
    raises — a test that drives more completions than it scripted fails loudly
    instead of silently degrading.
    """

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.offered: list[Any] = []
        self.prompts: list[tuple[str, str]] = []

    def make_complete(
        self, config: Any, tools: Optional[list] = None
    ) -> Callable[[list[dict]], ModelResponse]:
        self.offered.append(tools)

        def complete(messages: list[dict]) -> ModelResponse:
            system = str(messages[0].get("content", "")) if messages else ""
            user = str(messages[-1].get("content", "")) if messages else ""
            self.prompts.append((system, user))
            if not self.replies:
                raise AssertionError("ScriptedSeat exhausted — more completions than scripted")
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return ModelResponse(content=str(reply))

        return complete


def thought_json(intent: str = "add the greeting file", why: str = "the task asks for it") -> str:
    return json.dumps({"intent": intent, "why": why})


def presence_json(text: str = "noted.") -> str:
    return json.dumps({"text": text})


def evaluation_json(route: str, verdict: str = "aligned", reason: str = "fits the intent") -> str:
    return json.dumps(
        {
            "thought_id": "ignored-by-the-host",
            "action_id": "ignored-by-the-host",
            "verdict": verdict,
            "route": route,
            "reason": reason,
        }
    )


def build_session(
    front_replies: list[Any],
    evaluator_replies: list[Any],
    *,
    max_retries: int = 2,
) -> tuple[TaeSession, ScriptedSeat, ScriptedSeat]:
    front_seat = ScriptedSeat(front_replies)
    evaluator_seat = ScriptedSeat(evaluator_replies)
    session = TaeSession(
        front=FrontSeat(seat_config=None, make_complete=front_seat.make_complete),
        evaluator=EvaluatorSeat(
            seat_config=None,
            make_complete=evaluator_seat.make_complete,
            loss_policy=EvaluatorLossPolicy(max_retries=max_retries),
        ),
        worker_model="worker-sentinel",
    )
    return session, front_seat, evaluator_seat


def scripted(responses: list[ModelResponse]):
    """A worker ``complete()`` returning each canned response in turn."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def kinds(session: TaeSession) -> list[str]:
    return [entry.kind for entry in session.ledger.entries()]


# ---------------------------------------------------------------------------
# Criterion 1 (standing): the front seat is offered NO repo tools, ever.
# ---------------------------------------------------------------------------


def test_front_and_evaluator_seats_are_always_offered_an_empty_tool_list() -> None:
    """Every front and evaluator completion is handed ``tools=[]`` — an explicit
    empty list, never ``None`` and never a schema. ``_build_chat_payload`` omits
    BOTH ``tools`` and ``tool_choice`` for an empty list, so the front
    structurally cannot carry a repo tool on the wire."""
    session, front, evaluator = build_session([thought_json()], [evaluation_json("execute")])
    session.commit_initial_plan("write greet.txt")
    session.before_tool_call("write_file", {"path": "greet.txt", "content": "hi"})

    assert front.offered == [[]]
    assert evaluator.offered == [[]]
    assert all(offered == [] for offered in front.offered + evaluator.offered)


# ---------------------------------------------------------------------------
# Criterion 2: the evaluator is invoked ONLY at the enumerated boundaries.
# ---------------------------------------------------------------------------


def test_ordinary_tool_calls_never_invoke_the_evaluator(tmp_path: Path) -> None:
    """THE criterion-2 proof, driven through the real loop: a worker episode
    that only reads and lists reaches the evaluator ZERO times. The gate is the
    host's enumerated CONSEQUENTIAL_TOOLS list, not anything the model said."""
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    session, _front, evaluator = build_session(
        [thought_json()],
        # Exactly ONE scripted reply: enough for the single ``episode_completion``
        # boundary at the end, and not one spare. Any invocation from a tool call
        # would exhaust the script and fail loudly.
        [evaluation_json("execute")],
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "read_file", {"path": "a.txt"})]),
        ModelResponse(tool_calls=[ToolCall("2", "list_dir", {"path": "."})]),
        ModelResponse(tool_calls=[ToolCall("3", "read_file", {"path": "a.txt"})]),
        ModelResponse(tool_calls=[ToolCall("4", "finish", {"summary": "read it"})]),
    ]
    task = Task.new(str(tmp_path), "read a.txt")
    result = run(
        scripted(responses),
        task,
        max_steps=10,
        context=ContextControls(tae_session=session),
    )

    assert result.status == OK
    assert len(result.steps) == 4
    # Not one tool-call-driven evaluator invocation across four ordinary calls —
    # the ONLY boundary reached is the episode end.
    assert session.evaluator.boundaries == ["episode_completion"]
    assert "consequential_action" not in session.evaluator.boundaries
    assert "drift_threshold" not in session.evaluator.boundaries
    assert len(evaluator.offered) == 1
    # ...and the ledger carries the thought but no per-action evaluation.
    assert KIND_THOUGHT in kinds(session)
    assert KIND_ACTION not in kinds(session)
    assert KIND_EVALUATION not in kinds(session)


def test_a_consequential_tool_call_invokes_the_evaluator_at_its_named_boundary(
    tmp_path: Path,
) -> None:
    """The other half: a host-classified consequential call DOES reach the
    evaluator, at the ``consequential_action`` boundary and no other."""
    session, _front, _evaluator = build_session(
        [thought_json()], [evaluation_json("execute"), evaluation_json("execute")]
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "o.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote it"})]),
    ]
    task = Task.new(str(tmp_path), "write o.txt")
    result = run(
        scripted(responses),
        task,
        max_steps=10,
        context=ContextControls(tae_session=session),
    )

    assert result.changed_files == ["o.txt"]
    assert session.evaluator.boundaries[0] == "consequential_action"
    assert set(session.evaluator.boundaries) <= set(EVALUATOR_BOUNDARIES)


def test_the_evaluator_seat_refuses_a_boundary_outside_the_enumerated_list() -> None:
    """The guard lives at the seat: no caller can route ``"tool_call"`` (or any
    other non-boundary) to the slow seat, even by asking directly."""
    _session, _front, evaluator_double = build_session([], ["never used"])
    seat = EvaluatorSeat(seat_config=None, make_complete=evaluator_double.make_complete)
    outcome = seat.evaluate("tool_call", Thought("t-1", "i", "w"), None)

    assert outcome.evaluation is None
    assert "not an evaluator boundary" in outcome.block_reason
    assert evaluator_double.offered == []  # not one completion was issued


def test_the_episode_end_boundary_is_named_honestly(tmp_path: Path) -> None:
    """A finished episode is judged at ``episode_completion``; an episode that
    ended with no deliverable is the honest ``declared_infeasible``."""
    session, _f, _e = build_session(
        [thought_json()], [evaluation_json("execute", verdict="aligned")]
    )
    responses = [ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])]
    run(
        scripted(responses),
        Task.new(str(tmp_path), "do it"),
        max_steps=5,
        context=ContextControls(tae_session=session),
    )
    assert session.evaluator.boundaries == ["episode_completion"]

    session2, _f2, _e2 = build_session([thought_json()], [evaluation_json("block")])
    run(
        scripted([ModelResponse(tool_calls=[ToolCall("1", "list_dir", {"path": "."})])]),
        Task.new(str(tmp_path), "do it"),
        max_steps=2,
        context=ContextControls(tae_session=session2),
    )
    assert session2.evaluator.boundaries == ["declared_infeasible"]


# ---------------------------------------------------------------------------
# Criterion 3: routing + the host approval gate on every route.
# ---------------------------------------------------------------------------


def test_replan_routes_to_the_worker_under_the_unchanged_thought() -> None:
    session, _front, _evaluator = build_session(
        [thought_json()], [evaluation_json("replan", verdict="action_drift", reason="wrong file")]
    )
    committed = session.commit_initial_plan("write greet.txt")
    assert committed is not None

    decision = session.before_tool_call("write_file", {"path": "wrong.txt", "content": "x"})

    assert decision.allowed is False
    assert decision.route == "replan"
    assert decision.actor == "worker"
    # The THOUGHT stands — same object, same id, nothing superseded.
    assert session.live_thought is committed
    assert session.superseded_ids == set()
    assert "thought preserved" in decision.reason


def test_rethink_routes_to_the_front_which_recommits_a_superseding_thought() -> None:
    session, front, _evaluator = build_session(
        [thought_json(), thought_json(intent="write greet.md instead")],
        [evaluation_json("rethink", verdict="thought_ambiguous", reason="which file?")],
    )
    first = session.commit_initial_plan("write the greeting")
    assert first is not None

    decision = session.before_tool_call("write_file", {"path": "greet.txt", "content": "x"})

    assert decision.allowed is False
    assert decision.route == "rethink"
    assert decision.actor == "front"
    assert "thought re-opened" in decision.reason
    # The FRONT — not the worker — produced the replacement, superseding the old.
    assert session.live_thought is not None
    assert session.live_thought.thought_id != first.thought_id
    assert session.live_thought.supersedes == first.thought_id
    assert first.thought_id in session.superseded_ids
    assert front.offered == [[], []]  # both front turns tools-off


def test_host_policy_denies_an_aligned_execute_route() -> None:
    """Alignment is not permission. The evaluator says execute; the operator's
    approval gate says no; the host's answer wins and names WHO denied it."""
    session, _front, _evaluator = build_session([thought_json()], [evaluation_json("execute")])
    session.commit_initial_plan("clean the tree")
    policy = Policy(run_command={"deny": ["rm"]}, present=frozenset({"run_command"}))

    decision = session.before_tool_call("run_command", {"command": "rm -rf build"}, policy=policy)

    assert decision.allowed is False
    assert decision.route == "execute"  # the evaluation DID align...
    assert "denied by policy" in decision.reason  # ...and permission still lost


def test_a_missing_policy_object_is_itself_a_denial() -> None:
    """``authorize_execution``'s safe direction, reached through the wiring: no
    policy to consult means withhold approval, never assume it."""
    session, _front, _evaluator = build_session([thought_json()], [evaluation_json("execute")])
    session.commit_initial_plan("clean the tree")

    decision = session.before_tool_call("run_command", {"command": "ls"}, policy=None)

    assert decision.allowed is False
    assert "denied by policy" in decision.reason


def test_the_loop_policy_gate_still_runs_on_an_allowed_route(tmp_path: Path) -> None:
    """The loop's own untouched ``_deny_by_policy`` sits directly after the TAE
    gate, so the operator's allow-list gates every route — including one the
    evaluator green-lit — for tools the TAE seam does not itself authorize."""
    session, _front, _evaluator = build_session(
        [thought_json()], [evaluation_json("execute"), evaluation_json("execute")]
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "run_command", {"command": "git status"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "checked"})]),
    ]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "check status"),
        max_steps=5,
        policy=Policy(run_command={"allow": ["ls"]}, present=frozenset({"run_command"})),
        context=ContextControls(tae_session=session),
    )

    denials = [step for step in result.steps if not step.ok]
    assert denials, "the operator's allow-list must still refuse git status"
    assert "not on the allow list" in denials[0].result


# ---------------------------------------------------------------------------
# Criterion 5: guidance -> the FRONT; a mid-run objective change supersedes.
# ---------------------------------------------------------------------------


def test_flight_guidance_routes_to_the_front_as_an_observation(tmp_path: Path) -> None:
    """With the mode armed, a pilot's words are NOT appended as a raw worker
    turn — the ``[pilot guidance]`` line the unarmed loop injects is absent, and
    the front is what saw the message."""
    import colleague.flight as flightmod

    session, front, _evaluator = build_session([thought_json(), presence_json("ok")], [])
    session.commit_initial_plan("write greet.txt")

    task = Task.new(str(tmp_path), "write greet.txt")
    task.watch = True
    flightmod.arm(str(tmp_path), task.id)
    flightmod.append_guidance(str(tmp_path), task.id, "keep the file small")

    seen: list[dict] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append(messages[-1])
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    run(complete, task, max_steps=3, context=ContextControls(tae_session=session))

    joined = json.dumps(seen)
    assert "[pilot guidance]" not in joined
    # The FRONT ran a presence turn on the operator's words.
    assert front.prompts[-1][1].endswith("keep the file small")
    assert "presence" in session.front.cadences


def test_a_mid_run_objective_change_supersedes_and_the_next_action_names_it() -> None:
    """Criterion 5's substance: an observation that really changes the objective
    produces a NEW thought superseding the old one, and the worker's next
    consequential action is bound to the NEW thought_id."""
    session, _front, _evaluator = build_session(
        [
            thought_json(intent="write greet.txt"),
            presence_json("understood"),
            thought_json(intent="write greet.md"),
        ],
        [evaluation_json("execute")],
    )
    first = session.commit_initial_plan("write greet.txt")
    assert first is not None

    session.observe("actually write greet.md instead", source="flight-guidance")

    assert session.live_thought is not None
    new_id = session.live_thought.thought_id
    assert new_id != first.thought_id
    assert session.live_thought.supersedes == first.thought_id

    decision = session.before_tool_call("write_file", {"path": "greet.md", "content": "hi"})
    assert decision.allowed is True
    assert decision.thought_id == new_id

    action_entries = [e for e in session.ledger.entries() if e.kind == KIND_ACTION]
    assert action_entries[-1].thought_id == new_id


# ---------------------------------------------------------------------------
# Criterion 6: supersession + evaluator loss.
# ---------------------------------------------------------------------------


def test_mid_action_supersession_is_complete_then_re_evaluate() -> None:
    """A thought committed while an action is IN FLIGHT is not adopted mid-tool
    (that would leave half-applied tool state). The old thought stays live until
    the action completes; only then does the new one take over."""
    session, _front, _evaluator = build_session(
        [
            thought_json(intent="write greet.txt"),
            presence_json("understood"),
            thought_json(intent="write greet.md"),
        ],
        [evaluation_json("execute")],
    )
    first = session.commit_initial_plan("write greet.txt")
    assert first is not None

    allowed = session.before_tool_call("write_file", {"path": "greet.txt", "content": "x"})
    assert allowed.allowed is True  # the action is now in flight

    session.observe("actually write greet.md instead", source="talk")

    assert session.supersessions == ["complete_then_re_evaluate"]
    assert session.live_thought is first  # NOT adopted mid-action

    session.after_tool_call("write_file", True)

    assert session.live_thought is not None
    assert session.live_thought is not first
    assert session.live_thought.supersedes == first.thought_id


def test_evaluator_seat_loss_is_bounded_retry_then_block_with_a_legible_reason() -> None:
    """Seat loss never degrades to "proceed unevaluated": it retries to the
    policy's bound, then BLOCKS, naming the boundary, the attempt count, and the
    underlying failure."""
    boom = RuntimeError("connection refused")
    session, _front, evaluator = build_session([thought_json()], [boom, boom, boom], max_retries=2)
    session.commit_initial_plan("write greet.txt")

    decision = session.before_tool_call("write_file", {"path": "greet.txt", "content": "x"})

    assert decision.allowed is False
    assert decision.route == "block"
    assert decision.actor == "host"
    assert "consequential_action" in decision.reason
    assert "3 attempt(s)" in decision.reason
    assert "connection refused" in decision.reason
    assert "does not proceed unevaluated" in decision.reason
    assert len(evaluator.offered) == 3  # exactly 1 + 2 retries, then stop

    # Once blocked, the episode stays blocked — no later call slips through.
    again = session.before_tool_call("write_file", {"path": "other.txt", "content": "y"})
    assert again.allowed is False
    assert len(evaluator.offered) == 3


def test_a_blocked_episode_denies_the_write_through_the_real_loop(tmp_path: Path) -> None:
    """The same loss, driven through the loop: nothing lands on disk and the
    denial reason reaches the model as the tool result."""
    boom = RuntimeError("connection refused")
    session, _front, _evaluator = build_session([thought_json()], [boom, boom, boom])
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "o.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "gave up"})]),
    ]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write o.txt"),
        max_steps=5,
        context=ContextControls(tae_session=session),
    )

    assert not (tmp_path / "o.txt").exists()
    assert result.changed_files == []
    assert any("does not proceed unevaluated" in step.result for step in result.steps)


# ---------------------------------------------------------------------------
# Criterion 7: presence grants nothing; the two cadences are wired.
# ---------------------------------------------------------------------------


def test_a_presence_utterance_implying_an_objective_produces_no_action_proposal() -> None:
    """The c36/h28 invariant at the wiring level: presence-mode prose that
    clearly implies an objective commits NO thought, so no ActionProposal is
    ever built and a consequential call is blocked for want of authority."""
    session, _front, evaluator = build_session(
        # The front answers in presence mode with text that plainly implies work.
        [presence_json("sure — we should delete the stale cache directory")],
        [],  # any evaluator invocation would raise
    )
    session.observe("we should probably clear out the old cache", source="talk")

    assert session.live_thought is None
    assert KIND_THOUGHT not in kinds(session)
    assert KIND_ACTION not in kinds(session)

    decision = session.before_tool_call("run_command", {"command": "rm -rf .cache"})

    assert decision.allowed is False
    assert decision.route == "block"
    assert "no committed thought grants action-planning authority" in decision.reason
    assert KIND_ACTION not in kinds(session)  # still no ActionProposal
    assert evaluator.offered == []  # the evaluator was never consulted


def test_the_two_front_cadences_are_wired_with_distinct_prompts_and_bounds() -> None:
    """Presence: exactly ONE completion, thinking off. Commitment: bounded
    thinking — at most COMMITMENT_MAX_ATTEMPTS completions, then an honest
    no-commitment rather than an unbounded retry."""
    front_double = ScriptedSeat([presence_json("hi")])
    front = FrontSeat(seat_config=None, make_complete=front_double.make_complete)

    assert isinstance(front.presence("hello"), PresenceUtterance)
    assert front.cadences == [tae_loop.CADENCE_PRESENCE]
    assert len(front_double.offered) == 1
    assert "PRESENCE mode" in front_double.prompts[0][0]
    assert "thinking OFF" in front_double.prompts[0][0]

    # Commitment cadence: two junk replies exhaust the bound and commit nothing.
    front2_double = ScriptedSeat(["not json at all", '{"intent": 5, "why": "x"}'])
    front2 = FrontSeat(seat_config=None, make_complete=front2_double.make_complete)
    assert front2.commit(objective="do the thing", thought_id="t-1") is None
    assert front2.cadences == [tae_loop.CADENCE_COMMITMENT] * tae_loop.COMMITMENT_MAX_ATTEMPTS
    assert len(front2_double.offered) == tae_loop.COMMITMENT_MAX_ATTEMPTS
    assert "THOUGHT-COMMITMENT mode" in front2_double.prompts[0][0]
    assert "bounded thinking" in front2_double.prompts[0][0]


def test_a_model_supplied_thought_id_is_never_trusted() -> None:
    """Identity is the host's: the ledger keys off ``thought_id``, so a model
    cannot invent or collide one."""
    front_double = ScriptedSeat([json.dumps({"thought_id": "hijack", "intent": "i", "why": "w"})])
    front = FrontSeat(seat_config=None, make_complete=front_double.make_complete)
    thought = front.commit(objective="do it", thought_id="thought-1")

    assert thought is not None
    assert thought.thought_id == "thought-1"


# ---------------------------------------------------------------------------
# Host-owned classification (c25/h18): the worker's flag is evidence only.
# ---------------------------------------------------------------------------


def test_the_worker_flag_cannot_downgrade_a_host_classified_consequential_action() -> None:
    session, _front, evaluator = build_session([thought_json()], [evaluation_json("execute")])
    session.commit_initial_plan("write greet.txt")

    # The worker claims the write is NOT consequential. The host disagrees, and
    # the host's verdict is the one that counts.
    decision = session.before_tool_call(
        "write_file", {"path": "greet.txt", "content": "x", "consequential": False}
    )

    assert decision.allowed is True
    assert session.evaluator.boundaries == ["consequential_action"]
    assert len(evaluator.offered) == 1


def test_the_worker_flag_cannot_upgrade_a_read_into_a_consequential_action() -> None:
    session, _front, evaluator = build_session([thought_json()], [])
    session.commit_initial_plan("read a file")

    decision = session.before_tool_call("read_file", {"path": "a.txt", "consequential": True})

    assert decision.allowed is True
    assert decision.route is None
    assert evaluator.offered == []


def test_the_consequential_tool_list_is_an_enumerated_constant() -> None:
    assert isinstance(tae_loop.CONSEQUENTIAL_TOOLS, tuple)
    assert set(tae_loop.CONSEQUENTIAL_TOOLS) == {
        "write_file",
        "edit_file",
        "run_command",
        "subagent",
        "subagents",
    }
    for read_only in ("read_file", "list_dir", "view_media", "run_tests", "finish"):
        assert not tae_loop.host_classifies_consequential(read_only)


# ---------------------------------------------------------------------------
# Standing invariants: unarmed byte-identity + the artifact fold.
# ---------------------------------------------------------------------------


def test_unarmed_is_a_strict_no_op(tmp_path: Path) -> None:
    """No session -> every one of the four loop call sites is inert, and the
    artifact carries no evaluation_ledger key."""
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "o.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote o.txt"})]),
    ]
    task = Task.new(str(tmp_path), "write o.txt")
    result = run(scripted(responses), task, max_steps=10)

    assert result.status == OK
    assert result.changed_files == ["o.txt"]
    assert result.evaluation_ledger is None
    assert "evaluation_ledger" not in result.to_dict()


def test_an_armed_run_folds_the_ledger_onto_the_artifact(tmp_path: Path) -> None:
    session, _front, _evaluator = build_session(
        [thought_json()], [evaluation_json("execute"), evaluation_json("execute")]
    )
    responses = [
        ModelResponse(tool_calls=[ToolCall("1", "write_file", {"path": "o.txt", "content": "x"})]),
        ModelResponse(tool_calls=[ToolCall("2", "finish", {"summary": "wrote o.txt"})]),
    ]
    result = run(
        scripted(responses),
        Task.new(str(tmp_path), "write o.txt"),
        max_steps=10,
        context=ContextControls(tae_session=session),
    )

    assert result.evaluation_ledger is not None
    payload = result.to_dict()["evaluation_ledger"]
    entry_kinds = [entry["kind"] for entry in payload["entries"]]
    assert entry_kinds[0] == KIND_THOUGHT
    assert KIND_EVALUATION in entry_kinds
    # One traceable chain: every entry names the one live thought.
    assert {entry["thought_id"] for entry in payload["entries"]} == {"thought-1"}


def test_make_tae_session_is_none_when_unarmed() -> None:
    class _Bare:
        thought_action_evaluation = False
        evaluation_seats = None

    assert tae_loop.make_tae_session(_Bare(), "mock") is None
    assert tae_loop.make_tae_session(object(), "mock") is None


@pytest.mark.parametrize("engine_name", ["mock", "vllm-openai"])
def test_make_tae_session_resolves_the_same_seats_for_every_engine(engine_name: str) -> None:
    """The all-engines rule at this seam: ``make_tae_session`` is the ONE source
    both backends forward through ``ContextControls.from_config``, so an armed
    config produces the identical seat wiring on ``mock`` and ``vllm-openai`` —
    front on the senses-resolved dial, evaluator on the cortex-resolved dial,
    and the worker's model recorded for ledger attribution."""
    config = EngineConfig(
        model="acting-worker-model",
        base_url="http://rig/v1",
        thought_action_evaluation=True,
        evaluation_seats=EvaluationSeats(
            front=SeatConfig("front-model", "http://front/v1", "k1", 32768),
            worker=SeatConfig("acting-worker-model", "http://worker/v1", "k2", 262144),
            evaluator=SeatConfig("evaluator-model", "http://evaluator/v1", "k3", 131072),
        ),
    )
    session = tae_loop.make_tae_session(config, engine_name)

    assert session is not None
    assert session.front.model == "front-model"
    assert session.evaluator.model == "evaluator-model"
    assert session.worker_model == "acting-worker-model"


def test_a_seat_config_never_inherits_the_acting_seat_streaming_sink() -> None:
    """A seat call is its own conversation: model/base_url/api_key/budget point
    at the seat, and ``on_delta``/``refresh_seat`` are cleared so a seat turn
    never leaks into the acting seat's delta sink (the senses precedent)."""
    config = EngineConfig(model="m", base_url="http://rig/v1", on_delta=lambda _chunk: None)
    seat = tae_loop.seat_engine_config(
        config, SeatConfig("seat-model", "http://seat/v1", "seat-key", 4096)
    )

    assert seat.model == "seat-model"
    assert seat.base_url == "http://seat/v1"
    assert seat.api_key == "seat-key"
    assert seat.context_budget_tokens == 4096
    assert seat.on_delta is None
    assert seat.refresh_seat is None


def test_the_committed_thought_reaches_the_worker_as_a_named_brief(tmp_path: Path) -> None:
    """The worker acts under a NAMED thought: the front's commitment is injected
    into the worker's history so its next consequential action can bind to it."""
    session, _front, _evaluator = build_session([thought_json()], [evaluation_json("execute")])
    seen: list[str] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.extend(str(m.get("content", "")) for m in messages)
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    run(
        complete,
        Task.new(str(tmp_path), "write greet.txt"),
        max_steps=3,
        context=ContextControls(tae_session=session),
    )

    briefs = [line for line in seen if line.startswith("[committed thought]")]
    assert briefs, "the worker never saw the committed thought"
    assert json.loads(briefs[0][len("[committed thought] ") :])["thought_id"] == "thought-1"


@pytest.mark.parametrize("boundary", list(EVALUATOR_BOUNDARIES))
def test_every_enumerated_boundary_is_accepted_by_the_seat(boundary: str) -> None:
    """The seat's guard admits exactly the enumerated five and nothing else."""
    double = ScriptedSeat([evaluation_json("execute")])
    seat = EvaluatorSeat(seat_config=None, make_complete=double.make_complete)
    outcome = seat.evaluate(boundary, Thought("t-1", "i", "w"), None)

    assert outcome.evaluation is not None
    assert isinstance(outcome.evaluation, Evaluation)
    assert seat.boundaries == [boundary]


# ── qodo-code-review regressions on PR #403 ─────────────────────────────────


def _armed_config() -> EngineConfig:
    return EngineConfig(
        model="acting-worker-model",
        base_url="http://rig/v1",
        thought_action_evaluation=True,
        evaluation_seats=EvaluationSeats(
            front=SeatConfig("front-model", "http://front/v1", "k1", 32768),
            worker=SeatConfig("acting-worker-model", "http://worker/v1", "k2", 262144),
            evaluator=SeatConfig("evaluator-model", "http://evaluator/v1", "k3", 131072),
        ),
    )


def test_armed_mode_fails_closed_when_the_engine_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comment 3746426182: swallowing a registry failure made an ARMED run
    indistinguishable from an unarmed one — every TAE call site is guarded by
    ``if ctx.tae is None``, so the episode would proceed with no thought, no
    evaluator boundary and no ledger while the operator believed otherwise."""
    from colleague import registry
    from colleague.cli._errors import CliError

    def boom(_name: str):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(registry, "load", boom)
    with pytest.raises(CliError) as excinfo:
        tae_loop.make_tae_session(_armed_config(), "mock")
    message = str(excinfo.value)
    assert "thought_action_evaluation" in message
    assert "unevaluated" in message


def test_unarmed_mode_still_returns_none_when_the_engine_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-closed path must not disturb the unarmed strict no-op."""
    from colleague import registry

    def boom(_name: str):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(registry, "load", boom)
    assert tae_loop.make_tae_session(EngineConfig(), "mock") is None


def test_each_tools_off_completion_records_its_own_list() -> None:
    """Comment 3746426184: the audit trail must not alias one shared list."""
    session = tae_loop.make_tae_session(_armed_config(), "mock")
    assert session is not None
    seat = session.front
    seat.offered_tools.append(list(tae_loop.FRONT_OFFERED_TOOLS))
    seat.offered_tools.append([])
    seat.offered_tools[0].append({"leaked": "schema"})
    # The module-level constant is never the object handed out or recorded.
    assert tae_loop.FRONT_OFFERED_TOOLS == []
    assert seat.offered_tools[1] == []

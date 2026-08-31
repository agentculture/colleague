"""Control-loop WIRING for the thought->action->evaluation (TAE) mode (t13).

This module is the *wiring* half of plan task t13. The pure control logic it
drives already exists and is NOT re-derived here:

* :mod:`colleague.tae_control` — the enumerated evaluator boundaries, the
  routing table, host-owned consequential classification, the supersession
  policy, the evaluator-loss policy, and ``may_plan_action``.
* :mod:`colleague.thought` / :mod:`colleague.actionproposal` /
  :mod:`colleague.evaluation` / :mod:`colleague.ledger` — the four contracts.

What this module adds is the *seams*: a front seat that runs the two cadences
over a tools-off completion, an evaluator seat invoked at exactly the five
enumerated boundaries with a bounded-retry-then-block loss policy, and one
:class:`TaeSession` object the bounded tool loop (:mod:`colleague.loop`) holds
in a single field. ``colleague/loop.py`` itself gains only four thin call sites
-- an initial-plan commit, a per-tool-call gate, an observation route, and an
episode finalizer -- so its diff stays wiring, not a rewrite.

Authority boundary, restated where it is enforced
-------------------------------------------------

* The **front** perceives and commits typed :class:`~colleague.thought.Thought`
  objects. It is offered ``tools=[]`` on EVERY completion -- never a repo tool
  (:data:`FRONT_OFFERED_TOOLS`). A presence-mode utterance carries no action
  authority no matter what it says (``may_plan_action``).
* The **worker** acts. Every consequential action it takes names exactly one
  live ``thought_id``.
* The **evaluator** judges, tools-off, and ONLY at
  :data:`~colleague.tae_control.EVALUATOR_BOUNDARIES`. An ordinary tool call is
  not a boundary and never reaches it.
* The **host** owns consequential classification (:data:`CONSEQUENTIAL_TOOLS`)
  and remains the execution gate on every route: the operator's approval policy
  is consulted through :func:`colleague.evaluation.authorize_execution`, and
  ``colleague/loop.py``'s own ``_deny_by_policy`` still runs afterwards,
  untouched.

Pure stdlib. No subprocess, no threads, no socket -- nothing here joins
``tests/test_boundary.py``'s sanctioned lists.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Any, Callable, Optional, cast

from colleague.actionproposal import ActionProposal, validate_action_proposal
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.config import EngineConfig
from colleague.evaluation import (
    ROUTE_BLOCK,
    ROUTE_EXECUTE,
    ROUTE_REPLAN,
    ROUTE_RETHINK,
    Evaluation,
    authorize_execution,
    build_evaluation_envelope,
    build_evaluation_prompt,
    may_execute,
    parse_evaluation,
)
from colleague.ledger import (
    KIND_ACTION,
    KIND_EVALUATION,
    KIND_EXECUTION,
    KIND_OUTCOME,
    KIND_REROUTE,
    KIND_THOUGHT,
    SEAT_EVALUATOR,
    SEAT_FRONT,
    SEAT_HOST,
    SEAT_WORKER,
    EvaluationLedger,
)
from colleague.tae_control import (
    EvaluatorLossPolicy,
    classify_consequential,
    may_plan_action,
    next_actor,
    route_preserves_thought,
    should_invoke_evaluator,
    supersession_policy,
)
from colleague.tae_front import (
    CADENCE_COMMITMENT,
    CADENCE_PRESENCE,
    COMMITMENT_MAX_ATTEMPTS,
    FRONT_OFFERED_TOOLS,
    FrontSeat,
    _ToolsOffSeat,
)
from colleague.thought import PresenceUtterance, Thought

# ---------------------------------------------------------------------------
# Host-owned enumerated constants
# ---------------------------------------------------------------------------

#: The HOST's enumerated classification of which repo tools are consequential.
#: A worker's own ``ActionProposal.consequential`` flag is EVIDENCE ONLY -- it
#: is passed to :func:`colleague.tae_control.classify_consequential` as the
#: first argument and discarded there. This tuple is the whole classifier: a
#: tool named here mutates the tree or executes arbitrary operator-supplied
#: text.
#:
#: Deliberately NOT here: ``read_file``/``list_dir``/``view_media`` are read-only;
#: ``run_tests`` is a fixed non-mutating gate tool; ``finish``/``check_test_integrity``/
#: ``memory``/``culture``/``devague``/the five read-only purposes/``deepthink`` do not
#: change the tree. Widening is a deliberate, visible edit, never an inference.
#: ``handover_to_colleague`` (plan t5, q9) joins as the write purpose that replaces
#: ``subagent`` on cortex/worker (``subagent``/``subagents`` stay here too: a manual
#: subagent call remains consequential).
CONSEQUENTIAL_TOOLS: tuple[str, ...] = (
    "write_file",
    "edit_file",
    "run_command",
    "subagent",
    "subagents",
    "handover_to_colleague",
)

#: Consecutive ``replan`` routes that constitute drift. The evaluator has now
#: told the worker its action was wrong this many times in a row under an
#: unchanged thought -- the THOUGHT is the suspect, so the next boundary is
#: ``drift_threshold`` rather than ``consequential_action``.
DRIFT_REPLAN_THRESHOLD = 3

#: The four boundary names this module raises itself, spelled once. All are
#: members of :data:`~colleague.tae_control.EVALUATOR_BOUNDARIES`; the seat
#: re-checks membership anyway (see :meth:`EvaluatorSeat.evaluate`).
BOUNDARY_CONSEQUENTIAL = "consequential_action"
BOUNDARY_DRIFT = "drift_threshold"
BOUNDARY_EPISODE = "episode_completion"
BOUNDARY_INFEASIBLE = "declared_infeasible"


def host_classifies_consequential(tool_name: str, worker_flag: bool = False) -> bool:
    """Whether the HOST classifies *tool_name* as a consequential action.

    *worker_flag* is the worker's own claim and is passed through
    :func:`colleague.tae_control.classify_consequential` purely to keep the
    "evidence only" contract visible at the one call site that has both values:
    the return value is the host verdict, and a worker claiming
    ``consequential=False`` cannot stop a host-classified consequential action
    from being treated as consequential.
    """
    return classify_consequential(worker_flag, tool_name in CONSEQUENTIAL_TOOLS)


# ---------------------------------------------------------------------------
# The gate decision the tool loop consumes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDecision:
    """The verdict :meth:`TaeSession.before_tool_call` hands the tool loop.

    ``allowed`` is the only field ``colleague/loop.py`` branches on; the rest
    are for the recorded step/tool message and for tests. ``route`` is the
    evaluator's own closed-vocabulary route (``None`` when no evaluator was
    invoked -- an ordinary, non-consequential tool call), and ``actor`` is
    :func:`colleague.tae_control.next_actor` applied to it.
    """

    allowed: bool
    reason: str = ""
    route: Optional[str] = None
    actor: Optional[str] = None
    thought_id: str = ""
    action_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Seat plumbing -- a seat is a dial target + a tools-off completion
# ---------------------------------------------------------------------------


def seat_engine_config(config: EngineConfig, seat: Any, seat_name: str = "") -> EngineConfig:
    """Point *config* at one resolved seat's dial (the senses_engine_config twin).

    A ``dataclasses.replace`` switching model/base_url/api_key to the seat and
    the context budget to the seat's OWN advertised window, with ``on_delta``
    and ``refresh_seat`` cleared so a seat call never inherits the acting
    seat's streaming sink or stale-pin refresh. Every other knob inherits.

    Per-seat thinking effort (#416 t4): when *seat_name* names a seat-table
    row ("senses" for the front, "evaluator" for the evaluator), the returned
    config carries the plain ``reasoning_effort_seat`` attribute that
    ``vllm_openai._effort_for`` honors ahead of the acting seat's resolved
    rung. The TAE worker needs no attribute: with the mode armed the ACTING
    dial IS the TAE worker (``config.resolve`` repoints it), so its effort
    resolves through ``reasoning_effort_effective`` as the "worker" seat.
    """
    seat_context = int(getattr(seat, "context", 0) or 0)
    built = cast(
        EngineConfig,
        dataclasses.replace(
            config,
            model=seat.model,
            base_url=seat.base_url,
            api_key=seat.api_key,
            context_budget_tokens=seat_context or config.context_budget_tokens,
            refresh_seat=None,
            on_delta=None,
        ),
    )
    if seat_name:
        from colleague import effort

        setattr(
            built,
            "reasoning_effort_seat",
            effort.resolve_effort(
                kill_switch=(config.reasoning_effort == "default"),
                seat_override=config.reasoning_effort_seats.get(seat_name),
                seat=seat_name,
            ),
        )
    return built


# ---------------------------------------------------------------------------
# The evaluator seat -- invoked ONLY at the enumerated boundaries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluatorOutcome:
    """One evaluator invocation's result.

    Exactly one of ``evaluation`` / ``block_reason`` is meaningful: an
    evaluation was recovered, or the seat was lost past its retry bound and the
    episode must BLOCK with a legible reason. There is deliberately no third,
    "proceed unevaluated" outcome.
    """

    evaluation: Optional[Evaluation] = None
    block_reason: str = ""
    attempts: int = 0


class EvaluatorSeat(_ToolsOffSeat):
    """The tools-off judgment seat, gated by the enumerated boundary list."""

    def __init__(
        self,
        *,
        seat_config: Optional[EngineConfig],
        make_complete: Callable[..., Callable[[list[dict[str, Any]]], Any]],
        loss_policy: Optional[EvaluatorLossPolicy] = None,
    ) -> None:
        super().__init__(seat_config=seat_config, make_complete=make_complete)
        self._loss = loss_policy or EvaluatorLossPolicy()
        #: The boundary NAME of each invocation, in order -- the audit trail
        #: criterion 2's test reads to prove no ordinary tool call got here.
        self.boundaries: list[str] = []

    def evaluate(self, boundary: str, thought: Any, action: Any) -> EvaluatorOutcome:
        """Judge one thought/action pair at *boundary*.

        Refuses to run at all for a boundary outside
        :data:`~colleague.tae_control.EVALUATOR_BOUNDARIES` -- the guard lives
        here, at the seat, so no caller can route an ordinary tool call to the
        slow seat by mistake.

        Bounded-retry-then-block: each failed attempt consults
        :meth:`~colleague.tae_control.EvaluatorLossPolicy.decide_on_evaluator_loss`,
        which returns ``retry`` while attempts remain and ``block`` after --
        never anything that lets the episode proceed unevaluated.
        """
        if not should_invoke_evaluator(boundary):
            return EvaluatorOutcome(
                block_reason=(
                    f"refused: {boundary!r} is not an evaluator boundary "
                    "(the evaluator is invoked only at the enumerated boundaries)"
                )
            )
        prompt = build_evaluation_prompt(build_evaluation_envelope(thought, action))
        attempt = 0
        last = "the evaluator seat produced no usable judgment"
        while True:
            self.boundaries.append(boundary)
            try:
                check = parse_evaluation(self._complete_once("", prompt))
                if check.allowed and check.evaluation is not None:
                    return EvaluatorOutcome(evaluation=check.evaluation, attempts=attempt + 1)
                last = check.reason or last
            except Exception as exc:  # noqa: BLE001 - any transport failure is seat loss
                last = f"{type(exc).__name__}: {exc}"
            if self._loss.decide_on_evaluator_loss(attempt) == "block":
                return EvaluatorOutcome(
                    block_reason=(
                        f"blocked at the {boundary!r} boundary: the evaluator seat is "
                        f"unavailable after {attempt + 1} attempt(s) -- {last}. "
                        "The episode does not proceed unevaluated."
                    ),
                    attempts=attempt + 1,
                )
            attempt += 1


# ---------------------------------------------------------------------------
# TaeSession -- the one object the tool loop holds
# ---------------------------------------------------------------------------


def render_thought_brief(thought: Thought) -> str:
    """The worker-facing rendering of a committed thought.

    A plain JSON object under a stable label so the worker's next consequential
    action can NAME the thought id it is bound to. Deterministic (sorted keys)
    so an unchanged thought never perturbs the history.
    """
    return "[committed thought] " + json.dumps(thought.to_dict(), sort_keys=True)


@dataclass
class _Superseded:
    """A thought committed while an action was in flight, awaiting adoption."""

    thought: Thought
    note: str = ""


class TaeSession:
    """The control loop's single seam object.

    Holds the three seats, the append-only ledger, the live thought, and the
    small amount of per-episode state the enumerated boundaries need. Every
    method is safe to call unconditionally -- the loop's own guard is simply
    ``ctx.tae is not None``.
    """

    def __init__(
        self,
        *,
        front: FrontSeat,
        evaluator: EvaluatorSeat,
        worker_model: str = "",
    ) -> None:
        self.front = front
        self.evaluator = evaluator
        self.worker_model = worker_model
        self.ledger = EvaluationLedger()
        self.live_thought: Optional[Thought] = None
        self.superseded_ids: set[str] = set()
        #: Set once the episode has been blocked; every later gate short-circuits.
        self.blocked_reason: str = ""
        #: The supersession policy chosen at each superseding observation.
        self.supersessions: list[str] = []
        self._thought_seq = 0
        self._action_seq = 0
        self._action_in_flight: Optional[str] = None
        self._pending: Optional[_Superseded] = None
        self._consecutive_replans = 0
        #: Front-authored lines the loop should inject as user turns.
        self.pending_injections: list[str] = []

    # -- ids ---------------------------------------------------------------
    def _next_thought_id(self) -> str:
        self._thought_seq += 1
        return f"thought-{self._thought_seq}"

    def _next_action_id(self) -> str:
        self._action_seq += 1
        return f"action-{self._action_seq}"

    # -- boundary 1: initial plan commit -----------------------------------
    def commit_initial_plan(self, instruction: str) -> Optional[Thought]:
        """The ``initial_plan_commit`` boundary: the front commits thought 1.

        The front runs its COMMITMENT cadence (bounded thinking). A successful
        commitment is recorded on the ledger and queued for injection so the
        worker acts under a named thought; a failed one commits nothing, which
        is what later denies the worker action authority.
        """
        thought = self.front.commit(objective=instruction, thought_id=self._next_thought_id())
        if thought is None:
            return None
        self._adopt(thought, detail="initial plan committed")
        return thought

    def _adopt(self, thought: Thought, *, detail: str) -> None:
        if self.live_thought is not None and self.live_thought.thought_id != thought.thought_id:
            self.superseded_ids.add(self.live_thought.thought_id)
        self.live_thought = thought
        self._consecutive_replans = 0
        self.ledger.append(
            KIND_THOUGHT,
            thought_id=thought.thought_id,
            detail=detail,
            seat=SEAT_FRONT,
            model=self.front.model,
        )
        self.pending_injections.append(render_thought_brief(thought))

    # -- observations: operator words go to the FRONT, never to the worker --
    def observe(self, text: str, *, source: str = "guidance") -> str:
        """Route one mid-run operator/environment message to the FRONT.

        This is the whole point of criterion 5: under the armed mode a pilot's
        words are an OBSERVATION for the front, never a raw user turn that
        silently redefines the running thought behind the evaluator's back.

        The front decides. If it commits a new thought, the objective really
        did change and the new thought SUPERSEDES the old one; if it answers in
        presence mode, nothing about the plan changes (criterion 7). The return
        value is a short trace line for the caller.
        """
        if self.live_thought is None:
            thought = self.front.commit(
                objective=text, thought_id=self._next_thought_id(), observation_refs=[source]
            )
            if thought is not None:
                self._adopt(thought, detail=f"committed from {source} observation")
                return f"front committed {thought.thought_id}"
            return self._record_presence(self.front.presence(text), source)

        utterance = self.front.presence(text)
        if utterance is None or not self._implies_objective_change(text):
            return self._record_presence(utterance, source)

        thought = self.front.commit(
            objective=text,
            thought_id=self._next_thought_id(),
            supersedes=self.live_thought.thought_id,
            observation_refs=[source],
        )
        if thought is None:
            return self._record_presence(utterance, source)
        return self._supersede(thought, source)

    def _supersede(self, thought: Thought, source: str) -> str:
        """Adopt (or defer) a superseding thought per the supersession policy.

        ``complete_then_re_evaluate`` when an action is in flight -- completing
        avoids half-applied tool state, and the outcome is compared against the
        NEW thought at the next boundary; ``adopt_immediately`` otherwise.
        """
        policy = supersession_policy(self._action_in_flight is not None)
        self.supersessions.append(policy)
        if policy == "adopt_immediately":
            self._adopt(thought, detail=f"superseded via {source} observation")
            return f"front committed {thought.thought_id}"
        self._pending = _Superseded(thought, note=f"superseded via {source} observation")
        live = cast(Thought, self.live_thought)
        self.ledger.append(
            KIND_REROUTE,
            thought_id=live.thought_id,
            action_id=self._action_in_flight,
            detail=(
                f"supersession deferred: {policy} -- thought {thought.thought_id} "
                "is adopted once the in-flight action completes"
            ),
            seat=SEAT_HOST,
        )
        return f"deferred {thought.thought_id} ({policy})"

    @staticmethod
    def _implies_objective_change(text: str) -> bool:
        """Whether an observation asks for a DIFFERENT objective.

        Deterministic and host-owned, mirroring :mod:`colleague.frontdoor`'s
        stance: a model never gets to decide, on its own recognisance, that the
        operator changed the plan. Ambiguous wording falls through to presence
        mode -- the safe direction, since a presence utterance grants no action
        authority at all.
        """
        lowered = text.lower()
        markers = (
            "instead",
            "actually",
            "change of plan",
            "new objective",
            "forget that",
            "stop doing",
            "rather than",
        )
        return any(marker in lowered for marker in markers)

    def _record_presence(self, utterance: Optional[PresenceUtterance], source: str) -> str:
        """Record a presence-mode reply -- which authorises NOTHING.

        No :class:`~colleague.actionproposal.ActionProposal` is built, no
        thought is committed, and ``may_plan_action`` on the utterance is
        ``False``. The reply is not injected into the worker's history either:
        presence-mode prose must not become something the worker can infer a
        hidden plan from.
        """
        thought_id = self.live_thought.thought_id if self.live_thought is not None else ""
        text = utterance.text if utterance is not None else "(front unavailable)"
        self.ledger.append(
            KIND_OUTCOME,
            thought_id=thought_id,
            detail=f"presence reply to {source} (no action authority): {text[:160]}",
            seat=SEAT_FRONT,
            model=self.front.model,
        )
        return "presence"

    # -- boundary 2/4: the per-tool-call gate ------------------------------
    def before_tool_call(
        self, tool: str, arguments: dict[str, Any], *, policy: Any = None
    ) -> GateDecision:
        """The tool loop's ONE gate call.

        Ordinary (non-consequential) tool calls return an allowed decision
        WITHOUT touching the evaluator -- that is criterion 2, enforced here by
        the host's enumerated :data:`CONSEQUENTIAL_TOOLS` classification rather
        than by anything the model said.
        """
        if self.blocked_reason:
            return GateDecision(False, self.blocked_reason, route=ROUTE_BLOCK, actor="host")
        worker_flag = bool(arguments.get("consequential", False))
        if not host_classifies_consequential(tool, worker_flag):
            return GateDecision(True)
        if not may_plan_action(self.live_thought):
            reason = (
                f"blocked: {tool!r} is a host-classified consequential action but no "
                "committed thought grants action-planning authority "
                "(a presence-mode utterance never does)"
            )
            self.ledger.append(KIND_REROUTE, thought_id="", detail=reason, seat=SEAT_HOST)
            return GateDecision(False, reason, route=ROUTE_BLOCK, actor="host")

        thought = cast(Thought, self.live_thought)
        action = self._build_action(thought, tool, arguments)
        if action is None:
            reason = f"blocked: could not bind {tool!r} to thought {thought.thought_id!r}"
            self.ledger.append(
                KIND_REROUTE, thought_id=thought.thought_id, detail=reason, seat=SEAT_HOST
            )
            return GateDecision(False, reason, route=ROUTE_BLOCK, actor="host")
        self.ledger.append(
            KIND_ACTION,
            thought_id=thought.thought_id,
            action_id=action.action_id,
            detail=f"{tool}: {action.proposed_action}",
            seat=SEAT_WORKER,
            model=self.worker_model,
        )
        boundary = (
            BOUNDARY_DRIFT
            if self._consecutive_replans >= DRIFT_REPLAN_THRESHOLD
            else BOUNDARY_CONSEQUENTIAL
        )
        return self._route(boundary, thought, action, tool, arguments, policy)

    def _build_action(
        self, thought: Thought, tool: str, arguments: dict[str, Any]
    ) -> Optional[ActionProposal]:
        payload = {
            "thought_id": thought.thought_id,
            "action_id": self._next_action_id(),
            "proposed_action": f"{tool}({_summarize_arguments(arguments)})",
            "expected_effect": f"the repository reflects {thought.intent}",
            "evidence_refs": list(thought.observation_refs),
            "consequential": True,
        }
        verdict = validate_action_proposal(
            payload,
            frozenset({thought.thought_id}),
            frozenset(self.superseded_ids),
        )
        if not verdict.allowed:
            return None
        return ActionProposal.from_dict(payload)

    def _route(
        self,
        boundary: str,
        thought: Thought,
        action: ActionProposal,
        tool: str,
        arguments: dict[str, Any],
        policy: Any,
    ) -> GateDecision:
        outcome = self.evaluator.evaluate(boundary, thought, action)
        if outcome.evaluation is None:
            self.blocked_reason = outcome.block_reason
            self.ledger.append(
                KIND_REROUTE,
                thought_id=thought.thought_id,
                action_id=action.action_id,
                detail=outcome.block_reason,
                seat=SEAT_HOST,
            )
            return GateDecision(False, outcome.block_reason, route=ROUTE_BLOCK, actor="host")
        evaluation = outcome.evaluation
        self.ledger.append(
            KIND_EVALUATION,
            thought_id=thought.thought_id,
            action_id=action.action_id,
            detail=f"{boundary}: {evaluation.verdict} -> {evaluation.route} ({evaluation.reason})",
            seat=SEAT_EVALUATOR,
            model=self.evaluator.model,
        )
        actor = next_actor(evaluation.route)
        if evaluation.route == ROUTE_EXECUTE:
            self._consecutive_replans = 0
            return self._authorize(evaluation, thought, action, tool, arguments, policy, actor)
        if evaluation.route == ROUTE_REPLAN:
            self._consecutive_replans += 1
        return self._reroute(evaluation, thought, action, actor)

    def _authorize(
        self,
        evaluation: Evaluation,
        thought: Thought,
        action: ActionProposal,
        tool: str,
        arguments: dict[str, Any],
        policy: Any,
        actor: str,
    ) -> GateDecision:
        """Alignment is not permission -- the host's approval gate decides.

        For ``run_command`` the operator's real :class:`colleague.policy.Policy`
        is consulted through :func:`colleague.evaluation.authorize_execution`,
        which denies an ``aligned``/``execute`` evaluation the gate refuses (and
        treats a missing policy as a denial). For every other consequential
        tool the host gate is ``colleague/loop.py``'s own untouched
        ``_deny_by_policy`` + ``pre_tool`` hooks, which run around this call --
        this seam never widens either.
        """
        if tool == "run_command":
            decision = authorize_execution(evaluation, policy, str(arguments.get("command", "")))
            if not decision.allowed:
                reason = f"denied by {decision.denied_by}: {decision.reason}"
                self.ledger.append(
                    KIND_REROUTE,
                    thought_id=thought.thought_id,
                    action_id=action.action_id,
                    detail=reason,
                    seat=SEAT_HOST,
                )
                return GateDecision(
                    False,
                    reason,
                    route=evaluation.route,
                    actor="host",
                    thought_id=thought.thought_id,
                    action_id=action.action_id,
                )
        elif not may_execute(evaluation):  # pragma: no cover - route already checked
            return GateDecision(False, "evaluation does not route to execution")
        self.ledger.append(
            KIND_EXECUTION,
            thought_id=thought.thought_id,
            action_id=action.action_id,
            detail=f"authorized: {tool}",
            seat=SEAT_HOST,
        )
        self._action_in_flight = action.action_id
        return GateDecision(
            True,
            route=evaluation.route,
            actor=actor,
            thought_id=thought.thought_id,
            action_id=action.action_id,
        )

    def _reroute(
        self, evaluation: Evaluation, thought: Thought, action: ActionProposal, actor: str
    ) -> GateDecision:
        """Apply a non-executing route: ``rethink`` -> front, ``replan`` -> worker.

        ``replan`` keeps the SAME thought (``route_preserves_thought``) -- the
        action was wrong, the thought stands. ``rethink`` says the thought
        itself is ambiguous, so the FRONT re-commits (superseding), and the
        worker's next action names the new id.
        """
        preserved = route_preserves_thought(evaluation.route)
        detail = (
            f"{evaluation.route} -> {actor} "
            f"({'thought preserved' if preserved else 'thought re-opened'}): "
            f"{evaluation.reason}"
        )
        self.ledger.append(
            KIND_REROUTE,
            thought_id=thought.thought_id,
            action_id=action.action_id,
            detail=detail,
            seat=SEAT_HOST,
        )
        if evaluation.route == ROUTE_RETHINK:
            replacement = self.front.commit(
                objective=f"{thought.intent}\nThe evaluator re-opened this: {evaluation.reason}",
                thought_id=self._next_thought_id(),
                supersedes=thought.thought_id,
                observation_refs=list(thought.observation_refs),
            )
            if replacement is not None:
                self._adopt(replacement, detail="re-committed after rethink")
        return GateDecision(
            False,
            detail,
            route=evaluation.route,
            actor=actor,
            thought_id=thought.thought_id,
            action_id=action.action_id,
        )

    # -- the in-flight completion half of the supersession policy ----------
    def after_tool_call(self, tool: str, ok: bool) -> None:
        """Close an authorized action and adopt any deferred supersession.

        This is the second half of ``complete_then_re_evaluate``: the in-flight
        action ran to completion (no half-applied tool state), and only now is
        the superseding thought adopted, so the worker's NEXT consequential
        action names the new thought_id.
        """
        if self._action_in_flight is None:
            return
        action_id = self._action_in_flight
        self._action_in_flight = None
        thought_id = self.live_thought.thought_id if self.live_thought is not None else ""
        self.ledger.append(
            KIND_OUTCOME,
            thought_id=thought_id,
            action_id=action_id,
            detail=f"{tool} completed ok={ok}",
            seat=SEAT_WORKER,
            model=self.worker_model,
        )
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self._adopt(pending.thought, detail=pending.note)

    # -- boundary 3/5: episode end ----------------------------------------
    def finish_episode(self, *, summary: str, delivered: bool) -> None:
        """The ``episode_completion`` / ``declared_infeasible`` boundary.

        A delivered episode is judged at ``episode_completion``; an episode that
        produced no deliverable is the honest ``declared_infeasible`` boundary.
        Advisory only -- like every other pre-finish gate in this repo it
        records and never flips the run's status.
        """
        if self.live_thought is None:
            return
        boundary = BOUNDARY_EPISODE if delivered else BOUNDARY_INFEASIBLE
        action = ActionProposal(
            thought_id=self.live_thought.thought_id,
            action_id=self._next_action_id(),
            proposed_action="episode outcome",
            expected_effect=summary or "(no summary)",
        )
        outcome = self.evaluator.evaluate(boundary, self.live_thought, action)
        judged = outcome.evaluation is not None
        detail = (
            f"{boundary}: {outcome.evaluation.verdict} -> {outcome.evaluation.route}"
            if outcome.evaluation is not None
            else f"{boundary}: {outcome.block_reason}"
        )
        self.ledger.append(
            KIND_OUTCOME,
            thought_id=self.live_thought.thought_id,
            action_id=action.action_id,
            detail=detail,
            seat=SEAT_EVALUATOR if judged else SEAT_HOST,
            model=self.evaluator.model if judged else "",
        )

    # -- artifact ----------------------------------------------------------
    def ledger_dict(self) -> Optional[dict[str, Any]]:
        """The ledger for ``TaskResult.evaluation_ledger``; ``None`` when empty.

        ``None`` keeps the omit-when-None contract the t11 field already has --
        an armed run that never committed anything adds no artifact key.
        """
        if len(self.ledger) == 0:
            return None
        return self.ledger.to_dict()

    def drain_injections(self) -> list[str]:
        """Front-authored lines the loop should append as user turns, once."""
        lines, self.pending_injections = self.pending_injections, []
        return lines


def _summarize_arguments(arguments: dict[str, Any]) -> str:
    """A short, deterministic rendering of a tool call's arguments."""
    return ", ".join(f"{key}={str(arguments[key])[:80]}" for key in sorted(arguments))


# ---------------------------------------------------------------------------
# The all-engines factory
# ---------------------------------------------------------------------------


def make_tae_session(config: Any, engine_name: str) -> Optional[TaeSession]:
    """Build the session for an ARMED config, else ``None`` (a strict no-op).

    The :func:`colleague.senses.make_senses_run` twin: every backend calls this
    with its own name and forwards the result through
    :meth:`colleague.loop.ContextControls.from_config`, so the mode behaves
    identically on ``mock`` and ``vllm-openai`` (the all-engines rule). Unarmed
    -- or armed on a config predating the t12 fields -- returns ``None`` and
    the loop stays byte-identical.
    """
    if not getattr(config, "thought_action_evaluation", False):
        return None
    seats = getattr(config, "evaluation_seats", None)
    if seats is None:
        return None
    from colleague import registry  # local: keeps the engine registry off import time

    # FAIL CLOSED. Every TAE call site in the loop is guarded by
    # ``if ctx.tae is None: return``, so swallowing this failure would make an
    # ARMED run silently indistinguishable from an unarmed one: no thought
    # commitment, no evaluator boundary, no ledger — while the operator
    # believes the three-seat controls are in force. That is the exact
    # silent-degradation this mode exists to prevent, so an armed config whose
    # engine cannot be loaded raises instead (qodo-code-review, PR #403
    # comment 3746426182). Unarmed configs still return None above, untouched.
    try:
        engine = registry.load(engine_name)
    except Exception as exc:  # noqa: BLE001 - re-raised loudly below
        raise CliError(
            EXIT_USER_ERROR,
            "thought→action→evaluation mode is armed "
            "(thought_action_evaluation) but its seats cannot be built: "
            f"loading engine {engine_name!r} failed ({exc}) — refusing to run "
            "unevaluated",
            "fix the engine so it loads, or unset thought_action_evaluation "
            "to run without the three-seat controls",
        ) from exc
    make_complete = engine.make_complete
    return TaeSession(
        front=FrontSeat(
            seat_config=seat_engine_config(config, seats.front, seat_name="senses"),
            make_complete=make_complete,
        ),
        evaluator=EvaluatorSeat(
            seat_config=seat_engine_config(config, seats.evaluator, seat_name="evaluator"),
            make_complete=make_complete,
        ),
        worker_model=seats.worker.model,
    )


__all__ = [
    "BOUNDARY_CONSEQUENTIAL",
    "BOUNDARY_DRIFT",
    "BOUNDARY_EPISODE",
    "BOUNDARY_INFEASIBLE",
    "CADENCE_COMMITMENT",
    "CADENCE_PRESENCE",
    "COMMITMENT_MAX_ATTEMPTS",
    "CONSEQUENTIAL_TOOLS",
    "DRIFT_REPLAN_THRESHOLD",
    "FRONT_OFFERED_TOOLS",
    "EvaluatorOutcome",
    "EvaluatorSeat",
    "FrontSeat",
    "GateDecision",
    "TaeSession",
    "host_classifies_consequential",
    "make_tae_session",
    "render_thought_brief",
    "seat_engine_config",
]

"""Pure control-logic for the thought-action-evaluation (TAE) mode.

This module is **logic only** — it does NOT wire anything into
:mod:`colleague.loop`. A later step wires the loop; this module owns the
decision functions the loop will call.

Pure stdlib (dataclasses, typing, enum) — no I/O, no subprocess, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

from colleague.thought import grants_action_authority

# ---------------------------------------------------------------------------
# 1. Evaluator boundaries — the guard that keeps the slow evaluator seat off
#    every tool call (spec c23 / honesty h23).
# ---------------------------------------------------------------------------

#: The ONLY boundary names that may trigger an evaluator invocation.
#: An ordinary tool call is NOT a boundary.
EVALUATOR_BOUNDARIES: tuple[str, ...] = (
    "initial_plan_commit",
    "consequential_action",
    "declared_infeasible",
    "drift_threshold",
    "episode_completion",
)


def should_invoke_evaluator(boundary: str) -> bool:
    """Return ``True`` only when *boundary* is one of the five sanctioned
    boundary names.  An ordinary tool call (e.g. ``"tool_call"``) returns
    ``False``, keeping the slow evaluator seat off every tool call."""
    return boundary in EVALUATOR_BOUNDARIES


# ---------------------------------------------------------------------------
# 2. Routing table — closed vocabulary from colleague/evaluation.py.
# ---------------------------------------------------------------------------

#: Mapping from route string to the next actor seat.
_ROUTE_TABLE: dict[str, str] = {
    "execute": "worker",
    "rethink": "front",
    "replan": "worker",
    "block": "host",
}


def next_actor(route: str) -> str:
    """Return the seat that owns the next step for *route*.

    * ``"execute"`` -> ``"worker"`` (proceed; host policy still gates
      actual execution).
    * ``"rethink"`` -> ``"front"`` (the thought itself is ambiguous/incomplete).
    * ``"replan"``  -> ``"worker"`` (the action is wrong but the thought
      stands UNCHANGED).
    * ``"block"``   -> ``"host"`` (operator/policy decision needed).

    Raises ``ValueError`` for any route outside the closed vocabulary.
    """
    if route not in _ROUTE_TABLE:
        raise ValueError(
            f"unknown route {route!r} — the closed set is {sorted(_ROUTE_TABLE.keys())}"
        )
    return _ROUTE_TABLE[route]


def route_preserves_thought(route: str) -> bool:
    """Return ``True`` when the route keeps the SAME thought.

    ``"replan"`` and ``"execute"`` preserve the thought; ``"rethink"`` does
    not (the thought itself is ambiguous/incomplete).
    """
    return route in ("replan", "execute")


# ---------------------------------------------------------------------------
# 3. Consequential classification — HOST owns this.
# ---------------------------------------------------------------------------


def classify_consequential(worker_flag: bool, host_verdict: bool) -> bool:
    """Classify whether an action is consequential.

    The worker's flag is **EVIDENCE ONLY**.  The host owns the final
    classification, so the return value equals *host_verdict* and ignores
    *worker_flag* entirely.  A worker claiming ``consequential=False``
    cannot stop a host-classified consequential action from being treated
    as consequential.

    *worker_flag* is therefore accepted and DELIBERATELY discarded. Keeping it
    in the signature is the point: callers pass the worker's claim, and the
    discard below is where "evidence, not authority" is enforced. Dropping the
    parameter to satisfy an unused-argument check would move that boundary out
    of the code and into a comment (SonarCloud S1172).
    """
    del worker_flag  # evidence only — never an input to the classification
    return host_verdict


# ---------------------------------------------------------------------------
# 4. Supersession policy — avoid half-applied tool state.
# ---------------------------------------------------------------------------

_SUPERSEDE_COMPLETE_THEN_REEVAL = "complete_then_re_evaluate"
_SUPERSEDE_ADOPT_IMMEDIATELY = "adopt_immediately"


def supersession_policy(action_in_flight: bool) -> str:
    """Decide how to handle a new thought arriving while an action is in flight.

    Returns ``"complete_then_re_evaluate"`` when an action is in flight —
    completing avoids half-applied tool state; the outcome is then compared
    against the NEW thought at the next boundary.  Returns
    ``"adopt_immediately"`` when no action is in flight.
    """
    if action_in_flight:
        return _SUPERSEDE_COMPLETE_THEN_REEVAL
    return _SUPERSEDE_ADOPT_IMMEDIATELY


# ---------------------------------------------------------------------------
# 5. Evaluator loss policy — bounded-retry-then-block.
# ---------------------------------------------------------------------------


@dataclass
class EvaluatorLossPolicy:
    """Bounded-retry-then-block for evaluator unavailability.

    Given a *max_retries* cap, decide_on_evaluator_loss(attempt) returns
    ``"retry"`` while attempt < max_retries, else ``"block"``.  It NEVER
    returns anything that lets the episode proceed unevaluated.
    """

    max_retries: int = 2

    def decide_on_evaluator_loss(self, attempt: int) -> str:
        """Return ``"retry"`` while *attempt* < max_retries, else ``"block"``.

        This policy never yields a proceed/execute outcome — the episode
        must stop when the evaluator is lost beyond retries.
        """
        if attempt < self.max_retries:
            return "retry"
        return "block"


# ---------------------------------------------------------------------------
# 6. may_plan_action — front output must be a committed Thought.
# ---------------------------------------------------------------------------


def may_plan_action(front_output: object) -> bool:
    """Return ``True`` only when *front_output* is a committed :class:`Thought`.

    Delegates to :func:`colleague.thought.grants_action_authority`; a
    :class:`PresenceUtterance` yields ``False`` even when its text clearly
    implies an objective.
    """
    return grants_action_authority(front_output)

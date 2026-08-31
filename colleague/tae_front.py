"""The front seat -- tools-off perceive/commit plumbing for TAE mode (t13).

Split out of :mod:`colleague.tae_loop` (hard-1000-line-file-limit t11) to keep
that module under the repo's line-count gate. Purely a lift-and-shift: no
behavior changed, and every name here is re-exported from
:mod:`colleague.tae_loop` so existing importers keep resolving unchanged.

:class:`_ToolsOffSeat` is the shared plumbing for BOTH non-acting seats --
the front here, and the evaluator that stays in :mod:`colleague.tae_loop`
(its ``self._complete_once("", prompt)`` call site is pinned verbatim by
``tests/test_prompt_surface_unification.py``, so the evaluator itself must
not move).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from colleague.config import EngineConfig
from colleague.plan.cli_driver import _extract_json_object, robust_simple_complete
from colleague.thought import PresenceUtterance, Thought, validate_presence, validate_thought

#: The front seat's offered tool list on EVERY completion. An explicit empty
#: list, never ``None`` -- ``vllm_openai._build_chat_payload`` omits BOTH
#: ``tools`` and ``tool_choice`` for an empty list, so the front structurally
#: cannot carry a repo tool schema on the wire (the honest tools-off invariant).
FRONT_OFFERED_TOOLS: list[dict[str, Any]] = []

#: The front's two cadences (spec c36 / :mod:`colleague.thought` "Two cadences").
#: ``presence`` -- thinking off: ONE completion, output structurally limited to
#: free text (:class:`~colleague.thought.PresenceUtterance`). ``commitment`` --
#: bounded thinking: at most :data:`COMMITMENT_MAX_ATTEMPTS` completions to
#: produce a schema-valid :class:`~colleague.thought.Thought`.
CADENCE_PRESENCE = "presence"
CADENCE_COMMITMENT = "commitment"

#: The bound on the commitment cadence's deliberation. "Bounded thinking" is
#: this number, not an unbounded retry: a front that cannot produce a valid
#: thought in this many attempts commits nothing (and the worker therefore has
#: no action authority) rather than being retried forever.
COMMITMENT_MAX_ATTEMPTS = 2

_PRESENCE_SYSTEM = (
    "You are the FRONT seat of a coding agent, in PRESENCE mode: cheap "
    "conversational and environmental contact, thinking OFF. You have NO "
    "repository tools and you never plan work. Reply with ONE JSON object and "
    'nothing else: {"text": "<your short reply>"}. The object must carry the '
    'single key "text" -- no intent, no plan, no constraints. Even if the '
    "operator implies an objective, you may only acknowledge it here; "
    "committing to it is a separate, deliberate act."
)

_COMMITMENT_SYSTEM = (
    "You are the FRONT seat of a coding agent, in THOUGHT-COMMITMENT mode: "
    "bounded thinking. You have NO repository tools and you never call one. "
    "Commit ONE typed thought as a single JSON object and nothing else:\n"
    '{"thought_id": "<opaque id>", "intent": "<what to do>", '
    '"why": "<rationale>", "constraints": [], "success_conditions": [], '
    '"uncertainties": [], "observation_refs": []}\n'
    'Optionally add "supersedes": "<the thought_id this replaces>". '
    "A thought is an INSPECTABLE decision artifact -- it owns intent, not "
    "evidence, and must never encode an executable tool call."
)


class _ToolsOffSeat:
    """Shared plumbing for the two non-acting seats.

    Both the front and the evaluator speak through ONE tools-off completion per
    attempt: ``make_complete(seat_config, tools=[])`` -- an explicit empty list,
    never ``None``. ``offered_tools`` records what was actually passed so a test
    can prove the seat was never handed a repo tool schema.
    """

    def __init__(
        self,
        *,
        seat_config: Optional[EngineConfig],
        make_complete: Callable[..., Callable[[list[dict[str, Any]]], Any]],
    ) -> None:
        self._config = seat_config
        self._make_complete = make_complete
        #: The offered-tools list handed to each completion, in order.
        self.offered_tools: list[list[dict[str, Any]]] = []

    @property
    def model(self) -> str:
        return getattr(self._config, "model", "") or ""

    def _complete_once(self, system_prompt: str, user_prompt: str) -> str:
        """ONE tools-off completion. Raises whatever the transport raises."""
        # A FRESH empty list per call, and a snapshot of it in the audit trail --
        # sharing the module-level FRONT_OFFERED_TOOLS object meant every recorded
        # entry aliased one list, so one accidental mutation would retroactively
        # rewrite the whole tools-off trail (qodo-code-review, PR #403 comment
        # 3746426184). The invariant: an explicit empty list, never None, so the
        # adapter omits tools/tool_choice.
        offered: list[dict[str, Any]] = []
        self.offered_tools.append(list(offered))
        complete = self._make_complete(self._config, tools=offered)
        simple = robust_simple_complete(complete)
        return simple(system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# The front seat -- two cadences, typed Thoughts, no repo tools
# ---------------------------------------------------------------------------


class FrontSeat(_ToolsOffSeat):
    """The front seat: perceives, and commits typed thoughts.

    Reuses the senses front's own proven shape -- the ``make_complete(config,
    tools=[])`` seam plus
    :func:`colleague.plan.cli_driver.robust_simple_complete` and
    ``_extract_json_object``, exactly as
    :func:`colleague.senses.run_senses_frontdoor` and
    :meth:`colleague.senses_loop.SensesLoopDriver._one_completion` do -- so a
    reasoning model that puts its JSON in prose, a fence, or the reasoning
    channel still reads.

    :meth:`presence` and :meth:`commit` are the two cadences. Neither ever
    raises: a failed or refused completion yields ``None``, and ``None`` grants
    no action authority.
    """

    def __init__(
        self,
        *,
        seat_config: Optional[EngineConfig],
        make_complete: Callable[..., Callable[[list[dict[str, Any]]], Any]],
    ) -> None:
        super().__init__(seat_config=seat_config, make_complete=make_complete)
        #: The cadence of each completion issued, in order.
        self.cadences: list[str] = []

    # -- presence cadence: thinking off ------------------------------------
    def presence(self, text: str) -> Optional[PresenceUtterance]:
        """ONE cheap completion; returns a :class:`PresenceUtterance` or ``None``.

        Thinking off: exactly one attempt, and the output type structurally
        cannot carry an intent (``validate_presence`` refuses whole on any key
        beyond ``text``). A presence utterance NEVER grants action authority,
        however clearly its text implies an objective.
        """
        self.cadences.append(CADENCE_PRESENCE)
        try:
            raw = self._complete_once(
                _PRESENCE_SYSTEM,
                f"Operator/environment contact (reply in presence mode):\n{text}",
            )
            payload = _extract_json_object(raw, required_key="text")
        except Exception:
            return None
        if not validate_presence(payload).allowed:
            return None
        return PresenceUtterance.from_dict(payload)

    # -- commitment cadence: bounded thinking ------------------------------
    def commit(
        self,
        *,
        objective: str,
        thought_id: str,
        supersedes: Optional[str] = None,
        observation_refs: Optional[list[str]] = None,
    ) -> Optional[Thought]:
        """Commit ONE typed thought, within :data:`COMMITMENT_MAX_ATTEMPTS`.

        The caller assigns ``thought_id``/``supersedes``: identity is the
        host's to keep (the ledger keys off it), not something a model may
        invent or collide. A model-supplied id is overwritten, never trusted.
        Returns ``None`` when no attempt produced a schema-valid thought -- the
        honest "no commitment", which leaves the worker without action
        authority rather than fabricating one.
        """
        refs = list(observation_refs or [])
        supersede_note = (
            f"\nThis supersedes thought {supersedes!r}; say why the objective changed."
            if supersedes
            else ""
        )
        for _ in range(COMMITMENT_MAX_ATTEMPTS):
            self.cadences.append(CADENCE_COMMITMENT)
            try:
                raw = self._complete_once(
                    _COMMITMENT_SYSTEM,
                    f"Commit a thought for this objective:\n{objective}{supersede_note}",
                )
                payload = dict(_extract_json_object(raw, required_key="intent"))
            except Exception:  # nosec B112 - a failed attempt spends one of the
                # BOUNDED attempts and moves on; exhausting them commits nothing
                # (the honest "no commitment"), which is the safe direction.
                continue
            payload["thought_id"] = thought_id
            if supersedes:
                payload["supersedes"] = supersedes
            else:
                payload.pop("supersedes", None)
            if not validate_thought(payload).allowed:
                continue
            thought = Thought.from_dict(payload)
            thought.observation_refs = refs + [
                ref for ref in thought.observation_refs if ref not in refs
            ]
            return thought
        return None


__all__ = [
    "CADENCE_COMMITMENT",
    "CADENCE_PRESENCE",
    "COMMITMENT_MAX_ATTEMPTS",
    "FRONT_OFFERED_TOOLS",
    "FrontSeat",
    "_ToolsOffSeat",
]

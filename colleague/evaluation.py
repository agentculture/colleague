"""Evaluation contract: closed verdicts over a tools-off envelope (#397, t10).

Pure stdlib, no I/O, no subprocess, no network, nothing tool-shaped on the
wire — the same discipline as :mod:`colleague.thought` and
:mod:`colleague.senses_moves`.

This module is the **third seat** of the experimental thought -> action ->
evaluation execution mode (issue #397). The front commits a typed
:class:`colleague.thought.Thought`; the worker (t9) proposes an action bound
to exactly one ``thought_id``; the **evaluator** answers exactly ONE
question:

    Does this action faithfully realize this thought under the available
    evidence?

It may detect a constraint violation, an implementation that does not satisfy
the intent, an unsupported expected effect, ambiguity in the thought, action
drift after several tool steps, or an outcome that does not meet the
thought's success conditions — one closed :data:`VERDICTS` token each.

Alignment is not permission, correctness, or wisdom
---------------------------------------------------

This is the load-bearing invariant of the whole module, and it is encoded as
a TEST (``tests/test_evaluation.py::TestAlignmentIsNotPermission``), not as a
comment. The evaluator's strongest possible output —
``verdict="aligned", route="execute"`` — is a *fidelity* judgment. It is
**never** an authorization:

* it does not grant tool permission and cannot bypass approvals/hooks/policy;
* it does not widen the worker's authority;
* it performs no repository work;
* it never rewrites the thought or the action (a payload smuggling
  thought-/action-authoring content refuses whole — see :data:`_ALLOWED_KEYS`);
* it never claims an aligned action is *safe* merely because it is aligned.

:func:`authorize_execution` is the shape that encodes it: execution requires
BOTH an ``execute``-routed evaluation AND the operator's real approval gate
(:class:`colleague.policy.Policy`) saying yes. The gate is the hard
authority; the evaluation is only a necessary precondition. (The approval
gate remains a **policy gate, not a sandbox** — see :mod:`colleague.policy`.)

The closed vocabulary (spec c23)
--------------------------------

Two enumerated sets, each declared in exactly ONE place:

* :data:`VERDICTS` — what the evaluator observed.
* :data:`ROUTES` — where the run goes next: ``execute`` (aligned; the host
  still decides whether execution is permitted), ``rethink`` (the thought
  itself is ambiguous or incomplete — back to the front), ``replan`` (the
  action does not express an otherwise usable thought — back to the worker),
  ``block`` (structural policy boundary, missing required evidence, or
  operator decision needed).

Validation refuses the **WHOLE** payload (mirroring
:mod:`colleague.lattice`'s unknown-key stance) on: a non-dict, an unknown or
missing key, a wrong-typed field, a version mismatch, a verdict or route
string outside the closed sets (no case-folding, no whitespace coercion —
``"Execute"`` is not ``"execute"``), or the single cross-field rule below.
A refused payload yields NO :class:`Evaluation` object at all — never a
partial or repaired one — and validation **never raises**.

**The one cross-field rule:** only :data:`VERDICT_ALIGNED` may carry
:data:`ROUTE_EXECUTE`. Alignment is the *necessary* condition for execution
and never the sufficient one; an aligned verdict may still route to
``block``.

The bounded envelope (spec h16 / c28)
-------------------------------------

:func:`build_evaluation_envelope` builds the evaluator's ONLY input: a
bounded thought/action/evidence envelope. It is deliberately **not** the
worker's conversation history — feeding the evaluator the worker's reasoning
transcript would let the worker's framing contaminate an independent fidelity
judgment, and it would blow a small reasoner seat's context. There is no
parameter, key, or code path here through which a transcript can arrive: the
builder reads a fixed list of FIELD NAMES off the thought/action and ignores
everything else, and every text/list is capped
(:data:`MAX_ENVELOPE_TEXT_CHARS` / :data:`MAX_ENVELOPE_LIST_ITEMS` /
:data:`MAX_ENVELOPE_EVIDENCE_ITEMS`) with the truncation recorded honestly on
:data:`EvaluationEnvelope.truncated`.

Tools-off wire discipline
-------------------------

Like :mod:`colleague.senses_moves`, this module builds prompt TEXT and parses
a completion's TEXT; it never touches the model wire itself and never
constructs anything tool-shaped. A caller feeds
:func:`build_evaluation_prompt` to a completion with an EMPTY offered-tools
list — ``colleague/engines/vllm_openai.py``'s ``_build_chat_payload`` then
omits ``tools``/``tool_choice`` entirely, which is what "tools-off" means
here.

Left for later tasks
--------------------

* ``t11`` — the append-only thought/action/evaluation/outcome ledger with
  seat/model attribution. Nothing here writes a ledger.
* ``t13`` — the control loop and the invocation-boundary policy (the
  evaluator must NOT run on every tool call). Nothing here decides when the
  evaluator runs.
* ``t12`` — arming/config. This module is contract-only and is not wired into
  :mod:`colleague.loop`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from colleague.plan.cli_driver import _extract_json_object
from colleague.policy import Policy

#: The current evaluation-result schema version. A raw payload MAY omit
#: ``version``; if present it MUST equal this exactly, so a future schema
#: change is a deliberate, visible bump rather than silent drift (same stance
#: as :data:`colleague.thought.THOUGHT_SCHEMA_VERSION`).
EVALUATION_SCHEMA_VERSION = 1

#: The version stamped on a built envelope (the evaluator's INPUT shape,
#: versioned independently of the result shape above).
ENVELOPE_SCHEMA_VERSION = 1

#: The ONE question the evaluator answers. Rendered verbatim into the prompt
#: and into every envelope, so the seat cannot drift into a second job.
EVALUATION_QUESTION = (
    "Does this action faithfully realize this thought under the available evidence?"
)


# ---------------------------------------------------------------------------
# The closed vocabulary — verdicts
# ---------------------------------------------------------------------------

#: The action faithfully realizes the thought under the available evidence.
VERDICT_ALIGNED = "aligned"
#: The action violates a constraint the thought states.
VERDICT_CONSTRAINT_VIOLATION = "constraint_violation"
#: The action is implemented in a way that does not satisfy the intent.
VERDICT_INTENT_NOT_SATISFIED = "intent_not_satisfied"
#: The action's expected effect is not supported by the available evidence.
VERDICT_UNSUPPORTED_EFFECT = "unsupported_effect"
#: The thought itself is ambiguous or incomplete.
VERDICT_THOUGHT_AMBIGUOUS = "thought_ambiguous"
#: The action has drifted from the thought over several tool steps.
VERDICT_ACTION_DRIFT = "action_drift"
#: The observed outcome does not meet the thought's success conditions.
VERDICT_SUCCESS_CONDITIONS_UNMET = "success_conditions_unmet"

#: The single source of truth for the verdict vocabulary: verdict -> short
#: description. :data:`VERDICTS` and the rendered instruction are DERIVED from
#: this mapping, never re-listed by hand, so the vocabulary cannot drift.
VERDICT_SCHEMA: "dict[str, str]" = {
    VERDICT_ALIGNED: "the action faithfully realizes the thought under the available evidence",
    VERDICT_CONSTRAINT_VIOLATION: "the action violates a constraint the thought states",
    VERDICT_INTENT_NOT_SATISFIED: ("the implementation does not satisfy the thought's intent"),
    VERDICT_UNSUPPORTED_EFFECT: (
        "the action's expected effect is not supported by the available evidence"
    ),
    VERDICT_THOUGHT_AMBIGUOUS: "the thought itself is ambiguous or incomplete",
    VERDICT_ACTION_DRIFT: "the action has drifted from the thought over several steps",
    VERDICT_SUCCESS_CONDITIONS_UNMET: (
        "the observed outcome does not meet the thought's success conditions"
    ),
}

#: The complete, ONLY-valid verdict set. Anything else refuses the whole
#: payload (:func:`validate_evaluation`).
VERDICTS: "frozenset[str]" = frozenset(VERDICT_SCHEMA)


# ---------------------------------------------------------------------------
# The closed vocabulary — routes
# ---------------------------------------------------------------------------

#: Aligned. **Host policy still decides whether execution is permitted.**
ROUTE_EXECUTE = "execute"
#: The thought itself is ambiguous or incomplete; return to the front.
ROUTE_RETHINK = "rethink"
#: The action does not express an otherwise usable thought; return to the worker.
ROUTE_REPLAN = "replan"
#: Structural policy boundary, missing required evidence, or operator decision.
ROUTE_BLOCK = "block"

#: The single source of truth for the route vocabulary (verbatim from issue
#: #397), route -> short description.
ROUTE_SCHEMA: "dict[str, str]" = {
    ROUTE_EXECUTE: (
        "aligned; the host's approval gate still decides whether execution is permitted"
    ),
    ROUTE_RETHINK: "the thought itself is ambiguous or incomplete; return to the front",
    ROUTE_REPLAN: ("the action does not express an otherwise usable thought; return to the worker"),
    ROUTE_BLOCK: (
        "structural policy boundary, missing required evidence, or operator decision needed"
    ),
}

#: The complete, ONLY-valid route set.
ROUTES: "frozenset[str]" = frozenset(ROUTE_SCHEMA)

#: The ONLY route that can ever reach execution — and only in combination
#: with the host's approval gate (:func:`authorize_execution`).
_EXECUTING_ROUTES: "frozenset[str]" = frozenset({ROUTE_EXECUTE})


# ---------------------------------------------------------------------------
# Result-payload schema
# ---------------------------------------------------------------------------

#: The only valid keys on a raw evaluation payload. Deliberately DISJOINT
#: from the thought-authoring keys (``intent``/``constraints``/
#: ``success_conditions``/``why``) and the action-authoring keys
#: (``expected_effect``/``command``/``patch``/``tool_calls``): a payload
#: carrying one of those is trying to rewrite the thought or the action, and
#: refuses whole (spec c28).
_ALLOWED_KEYS = frozenset(
    {
        "version",
        "thought_id",
        "action_id",
        "verdict",
        "route",
        "reason",
        "evidence_gaps",
    }
)

#: Required, non-empty string keys on a raw evaluation payload.
_REQUIRED_STRING_KEYS = ("thought_id", "action_id", "verdict", "route", "reason")


@dataclass(frozen=True)
class Evaluation:
    """One closed-vocabulary fidelity judgment.

    Fields
    ------
    thought_id / action_id:
        Opaque ids binding this judgment to exactly one thought and one
        action — the keys a later ledger (t11) joins on.
    verdict:
        A member of :data:`VERDICTS` — what the evaluator observed.
    route:
        A member of :data:`ROUTES` — where the run goes next.
    reason:
        A legible, non-empty explanation. A refusal a human cannot read is
        not a refusal.
    evidence_gaps:
        Named pieces of missing evidence (the honest half of a ``block``).
    version:
        :data:`EVALUATION_SCHEMA_VERSION`.

    This type carries NO permission-granting surface: no approve/allow/grant
    field or method exists, and none may be added (a test enforces it). An
    ``aligned``/``execute`` instance is a judgment, never an authorization.
    """

    thought_id: str
    action_id: str
    verdict: str
    route: str
    reason: str
    evidence_gaps: "list[str]" = field(default_factory=list)
    version: int = EVALUATION_SCHEMA_VERSION

    def to_dict(self) -> "dict[str, Any]":
        return {
            "version": self.version,
            "thought_id": self.thought_id,
            "action_id": self.action_id,
            "verdict": self.verdict,
            "route": self.route,
            "reason": self.reason,
            "evidence_gaps": list(self.evidence_gaps),
        }


@dataclass(frozen=True)
class EvaluationCheck:
    """The outcome of validating/parsing one raw evaluation payload.

    Named ``Check`` rather than ``Verdict`` on purpose: "verdict" is already
    the evaluator's OWN closed field, and overloading it would blur the two.
    Same refuse-whole contract as :class:`colleague.thought.ThoughtVerdict`:

    * ``allowed=True`` -> ``evaluation`` carries the typed result, ``reason``
      is empty.
    * ``allowed=False`` -> ``evaluation`` is ``None`` (never a partial or
      repaired result) and ``reason`` says why.
    """

    allowed: bool
    reason: str = ""
    evaluation: Optional[Evaluation] = None


# ---------------------------------------------------------------------------
# validate_evaluation — the public refuse-whole entry point
# ---------------------------------------------------------------------------


def _refuse(reason: str) -> EvaluationCheck:
    return EvaluationCheck(False, reason)


def _check_shape(data: "dict[str, Any]") -> Optional[EvaluationCheck]:
    extra = sorted(k for k in data if k not in _ALLOWED_KEYS)
    if extra:
        return _refuse(
            f"refused: unknown key(s) {extra!r} on evaluation payload "
            f"(only {sorted(_ALLOWED_KEYS)!r} are valid — the evaluator returns a "
            "fidelity verdict, never a rewritten thought or action)"
        )
    missing = [k for k in _REQUIRED_STRING_KEYS if k not in data]
    if missing:
        return _refuse(f"refused: missing required key(s) {missing!r}")
    for key in _REQUIRED_STRING_KEYS:
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            return _refuse(f"refused: {key!r} must be a non-empty (non-whitespace) string")
    gaps = data.get("evidence_gaps", [])
    if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
        return _refuse("refused: 'evidence_gaps' must be a list of strings")
    if "version" in data and data["version"] != EVALUATION_SCHEMA_VERSION:
        return _refuse(
            f"refused: unsupported evaluation schema version {data['version']!r} "
            f"(expected {EVALUATION_SCHEMA_VERSION})"
        )
    return None


def _check_vocabulary(data: "dict[str, Any]") -> Optional[EvaluationCheck]:
    verdict = data["verdict"]
    route = data["route"]
    if verdict not in VERDICTS:
        return _refuse(
            f"refused: unknown verdict {verdict!r} "
            f"(the closed vocabulary is {sorted(VERDICTS)!r})"
        )
    if route not in ROUTES:
        return _refuse(
            f"refused: unknown route {route!r} (the closed vocabulary is {sorted(ROUTES)!r})"
        )
    if route in _EXECUTING_ROUTES and verdict != VERDICT_ALIGNED:
        return _refuse(
            f"refused: verdict {verdict!r} may not carry route {route!r} — only "
            f"{VERDICT_ALIGNED!r} can route to execution, and even then the host's "
            "approval gate decides whether execution is permitted"
        )
    return None


def validate_evaluation(payload: object) -> EvaluationCheck:
    """Validate a raw evaluation payload against the closed vocabulary.

    A valid payload is a ``dict`` carrying ``thought_id``/``action_id``/
    ``verdict``/``route``/``reason`` (non-empty strings), optionally
    ``evidence_gaps`` (a list of strings) and ``version`` (must equal
    :data:`EVALUATION_SCHEMA_VERSION` when present). ``verdict`` must be a
    member of :data:`VERDICTS` and ``route`` of :data:`ROUTES`, matched
    EXACTLY — no case-folding, no stripping, no nearest-neighbour coercion.
    Only :data:`VERDICT_ALIGNED` may carry :data:`ROUTE_EXECUTE`.

    Anything else refuses the WHOLE payload: the returned
    :class:`EvaluationCheck` has ``allowed=False``, a legible ``reason``, and
    ``evaluation=None``. **Never raises.**
    """
    if not isinstance(payload, dict):
        return _refuse(f"refused: input is not a JSON object (got {type(payload).__name__})")
    bad = _check_shape(payload)
    if bad is not None:
        return bad
    bad = _check_vocabulary(payload)
    if bad is not None:
        return bad
    return EvaluationCheck(
        True,
        evaluation=Evaluation(
            thought_id=payload["thought_id"],
            action_id=payload["action_id"],
            verdict=payload["verdict"],
            route=payload["route"],
            reason=payload["reason"],
            evidence_gaps=list(payload.get("evidence_gaps", [])),
            version=int(payload.get("version", EVALUATION_SCHEMA_VERSION)),
        ),
    )


def parse_evaluation(raw: object) -> EvaluationCheck:
    """Recover an evaluation from a tools-off completion's raw TEXT.

    Reuses the solved JSON-recovery path
    (:func:`colleague.plan.cli_driver._extract_json_object`, the same helper
    :func:`colleague.senses_moves.parse_move` uses) so a served model wrapping
    its JSON in prose or a ``json`` fence still reads.

    Unlike ``parse_move``, there is **no** degradation default here: an empty,
    unparseable, or non-evaluation completion REFUSES (``allowed=False``,
    ``evaluation=None``). A judgment seat must never be given a default
    opinion — least of all ``aligned``. **Never raises.**
    """
    if not isinstance(raw, str) or not raw.strip():
        return _refuse("refused: empty or non-text evaluation completion")
    try:
        obj = _extract_json_object(raw, required_key="verdict")
    except ValueError:
        return _refuse(
            "refused: no evaluation object found in the completion "
            "(the evaluator must reply with a single JSON object)"
        )
    return validate_evaluation(obj)


# ---------------------------------------------------------------------------
# Execution authority — alignment is NOT permission
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionDecision:
    """Whether an action may actually run, and who said no.

    ``denied_by`` is ``"evaluation"`` when the fidelity judgment did not route
    to execution, ``"policy"`` when the operator's approval gate refused (or
    could not be consulted), and ``None`` on an allowed decision.
    """

    allowed: bool
    reason: str = ""
    denied_by: Optional[str] = None


def may_execute(evaluation: object) -> bool:
    """Whether *evaluation* routes to execution — a NECESSARY, never
    sufficient, condition (see :func:`authorize_execution`).

    Returns ``False`` for anything that is not a real :class:`Evaluation`
    (a dict, a bare route string, ``None``): only a validated evaluation can
    speak here, mirroring
    :func:`colleague.thought.grants_action_authority`.
    """
    return isinstance(evaluation, Evaluation) and evaluation.route in _EXECUTING_ROUTES


def authorize_execution(
    evaluation: object,
    policy: Optional[Policy],
    command: str,
) -> ExecutionDecision:
    """Combine the fidelity judgment with the operator's REAL approval gate.

    Execution requires BOTH, in this order:

    1. an :class:`Evaluation` routing to :data:`ROUTE_EXECUTE` — a ``block``
       (or ``rethink``/``replan``) never reaches the gate at all;
    2. the operator's :class:`colleague.policy.Policy` allowing *command*.

    **Alignment is not permission.** An ``aligned``/``execute`` evaluation
    cannot run a command the gate denies, and a missing policy object is a
    denial (cannot consult the gate -> withhold approval, the same safe
    direction :func:`colleague.policy.verify_checksum` takes). Nothing here
    mutates, widens, or re-reads the policy: the gate's own verdict is
    returned verbatim.
    """
    if not may_execute(evaluation):
        route = evaluation.route if isinstance(evaluation, Evaluation) else None
        return ExecutionDecision(
            False,
            (
                f"evaluation routed to {route!r}, not {ROUTE_EXECUTE!r}"
                if route
                else "no valid evaluation routes this action to execution"
            ),
            denied_by="evaluation",
        )
    if policy is None:
        return ExecutionDecision(
            False,
            "no approval policy supplied — an aligned evaluation is not permission",
            denied_by="policy",
        )
    verdict = policy.check_run_command(command)
    if not verdict.allowed:
        return ExecutionDecision(False, verdict.reason, denied_by="policy")
    return ExecutionDecision(True)


# ---------------------------------------------------------------------------
# The bounded thought/action/evidence envelope
# ---------------------------------------------------------------------------

#: Per-text-field character cap inside the envelope.
MAX_ENVELOPE_TEXT_CHARS = 600
#: Per-list-field item cap inside the envelope.
MAX_ENVELOPE_LIST_ITEMS = 12
#: Cap on the number of evidence excerpts carried.
MAX_ENVELOPE_EVIDENCE_ITEMS = 8

#: The complete, ONLY key set of a serialized envelope. Deliberately carries
#: no conversation/history/transcript/message key — and none may be added.
ENVELOPE_ALLOWED_KEYS = (
    "envelope_version",
    "question",
    "thought",
    "action",
    "evidence",
    "truncated",
)

#: The thought fields the envelope carries (read BY NAME off the thought).
_THOUGHT_TEXT_FIELDS = ("thought_id", "intent", "why")
_THOUGHT_LIST_FIELDS = (
    "constraints",
    "success_conditions",
    "uncertainties",
    "observation_refs",
)

#: The action fields the envelope carries. Each entry is
#: ``(envelope key, accepted source names)`` — t9's ``ActionProposal`` binds an
#: action to exactly one ``thought_id`` with ``expected_effect`` +
#: ``evidence_refs``; the aliases keep this builder working against either the
#: dataclass or a plain mapping while that module lands in parallel.
_ACTION_TEXT_FIELDS = (
    ("action_id", ("action_id", "id")),
    ("thought_id", ("thought_id",)),
    ("proposed_action", ("proposed_action", "summary", "description", "action")),
    ("expected_effect", ("expected_effect",)),
    ("command", ("command",)),
)
_ACTION_LIST_FIELDS = (("evidence_refs", ("evidence_refs",)),)


def _read(source: object, names: "tuple[str, ...]") -> object:
    """Read the first present, non-``None`` attribute/key among *names*.

    Deliberately name-driven: an object may carry anything else at all (a
    worker seat's ``messages``/``history``/``transcript``, a raw model
    response) and none of it can reach the envelope, because nothing here
    ever iterates a source object's attributes or keys.
    """
    for name in names:
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def _bounded_text(value: object, label: str, truncated: "list[str]") -> str:
    if isinstance(value, str):
        text = value
    elif value is None:
        text = ""
    else:
        text = str(value)
    if len(text) > MAX_ENVELOPE_TEXT_CHARS:
        truncated.append(label)
        return text[: MAX_ENVELOPE_TEXT_CHARS - 3] + "..."
    return text


def _bounded_list(value: object, label: str, truncated: "list[str]") -> "list[str]":
    if not isinstance(value, (list, tuple)):
        return []
    items = [item if isinstance(item, str) else str(item) for item in value]
    if len(items) > MAX_ENVELOPE_LIST_ITEMS:
        truncated.append(label)
        items = items[:MAX_ENVELOPE_LIST_ITEMS]
    return [_bounded_text(item, f"{label}[]", truncated) for item in items]


@dataclass(frozen=True)
class EvaluationEnvelope:
    """The evaluator's complete, bounded input.

    Three parts and nothing else: the committed thought, the proposed action,
    and bounded evidence excerpts. **Not** the worker's conversation history —
    see the module docstring; ``tests/test_evaluation.py`` asserts the absence
    directly (of the content, of any history-shaped key, and of any builder
    parameter through which one could arrive).

    ``truncated`` names every field the caps shortened, so a reader can tell a
    bounded envelope from a complete one instead of guessing.
    """

    thought: "dict[str, Any]"
    action: "dict[str, Any]"
    evidence: "list[dict[str, str]]" = field(default_factory=list)
    truncated: "tuple[str, ...]" = ()
    version: int = ENVELOPE_SCHEMA_VERSION

    def to_dict(self) -> "dict[str, Any]":
        return {
            "envelope_version": self.version,
            "question": EVALUATION_QUESTION,
            "thought": dict(self.thought),
            "action": dict(self.action),
            "evidence": [dict(item) for item in self.evidence],
            "truncated": list(self.truncated),
        }


def build_evaluation_envelope(
    thought: object,
    action: object,
    evidence: "Optional[list[dict[str, str]]]" = None,
) -> EvaluationEnvelope:
    """Build the bounded thought/action/evidence envelope.

    *thought* is a :class:`colleague.thought.Thought` (or a thought-shaped
    mapping) and *action* is t9's ``ActionProposal`` (or an action-shaped
    mapping); both are read BY FIELD NAME — see :data:`_THOUGHT_TEXT_FIELDS` /
    :data:`_ACTION_TEXT_FIELDS`. Any other attribute on either object is
    invisible to this builder by construction.

    *evidence* is an optional list of ``{"ref": ..., "text": ...}`` excerpts.
    It is the ONLY free-form input, and it is capped at
    :data:`MAX_ENVELOPE_EVIDENCE_ITEMS` items of
    :data:`MAX_ENVELOPE_TEXT_CHARS` characters each.

    There is deliberately **no** parameter for the worker's conversation,
    messages, transcript, or trace: the evaluator's judgment must be
    independent of the worker's framing, and a small reasoner seat's context
    cannot carry one anyway.

    A binding mismatch (the action naming a different ``thought_id``) is
    carried through VERBATIM, never silently retargeted — surfacing it is the
    evaluator's job.
    """
    truncated: "list[str]" = []

    thought_data: "dict[str, Any]" = {
        name: _bounded_text(_read(thought, (name,)), f"thought.{name}", truncated)
        for name in _THOUGHT_TEXT_FIELDS
    }
    for name in _THOUGHT_LIST_FIELDS:
        thought_data[name] = _bounded_list(_read(thought, (name,)), f"thought.{name}", truncated)

    action_data: "dict[str, Any]" = {
        key: _bounded_text(_read(action, names), f"action.{key}", truncated)
        for key, names in _ACTION_TEXT_FIELDS
    }
    for key, names in _ACTION_LIST_FIELDS:
        action_data[key] = _bounded_list(_read(action, names), f"action.{key}", truncated)

    items = list(evidence or [])
    if len(items) > MAX_ENVELOPE_EVIDENCE_ITEMS:
        truncated.append("evidence")
        items = items[:MAX_ENVELOPE_EVIDENCE_ITEMS]
    bounded_evidence = [
        {
            "ref": _bounded_text(_read(item, ("ref", "id")), "evidence.ref", truncated),
            "text": _bounded_text(_read(item, ("text",)), "evidence.text", truncated),
        }
        for item in items
    ]

    return EvaluationEnvelope(
        thought=thought_data,
        action=action_data,
        evidence=bounded_evidence,
        truncated=tuple(dict.fromkeys(truncated)),
    )


# ---------------------------------------------------------------------------
# Prompt rendering (TEXT only — this module never touches the model wire)
# ---------------------------------------------------------------------------


def build_evaluation_instruction() -> str:
    """Render the closed vocabulary into prompt text for a tools-off completion.

    Derived from :data:`VERDICT_SCHEMA` / :data:`ROUTE_SCHEMA` — never
    hand-duplicated — so the prompt cannot drift from what
    :func:`validate_evaluation` accepts. Builds TEXT only; the caller feeds it
    to a completion with an EMPTY offered-tools list.
    """
    lines = [
        "You are the evaluator. You answer exactly ONE question:",
        f"  {EVALUATION_QUESTION}",
        "",
        "You do not perform repository work, rewrite the thought or the action, "
        "grant tool permission, or widen anyone's authority. Alignment is not "
        "permission, correctness, or wisdom: even an aligned action must still "
        "pass the host's approval gate before anything runs.",
        "",
        "Reply with ONLY a single JSON object:",
        "  "
        + json.dumps(
            {
                "thought_id": "...",
                "action_id": "...",
                "verdict": "<one verdict below>",
                "route": "<one route below>",
                "reason": "...",
                "evidence_gaps": ["..."],
            }
        ),
        "",
        "verdict — exactly one of:",
    ]
    lines.extend(f"  {name} — {desc}" for name, desc in VERDICT_SCHEMA.items())
    lines.append("")
    lines.append("route — exactly one of:")
    lines.extend(f"  {name} — {desc}" for name, desc in ROUTE_SCHEMA.items())
    lines.append("")
    lines.append(
        f"Only {VERDICT_ALIGNED!r} may use route {ROUTE_EXECUTE!r}. Any other "
        "verdict or route string is refused whole. No prose outside the JSON object."
    )
    return "\n".join(lines)


def build_evaluation_prompt(envelope: EvaluationEnvelope) -> str:
    """Render *envelope* + the instruction into one tools-off prompt string.

    The envelope is serialized as JSON exactly as :meth:`
    EvaluationEnvelope.to_dict` produces it — the prompt therefore contains
    precisely what the envelope contains, and nothing more (in particular, no
    worker conversation history).
    """
    return "\n".join(
        [
            build_evaluation_instruction(),
            "",
            "Envelope:",
            json.dumps(envelope.to_dict(), indent=2, sort_keys=True),
        ]
    )

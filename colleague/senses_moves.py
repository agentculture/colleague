"""Senses' coordination-move protocol + executor (presence-default-everywhere
arc, task t1).

Colleague drives with two lobes: **cortex** (drives the bounded tool loop —
the ONLY mind that touches the repo) and **senses** (a tools-off front door
that perceives/presents). This arc gives senses its own bounded coordination
loop so the operator can converse with it continuously while cortex works —
the FOURTH sanctioned router-exclusion increment (see
``docs/specs/2026-07-08-colleague-s-middle-manager-presence-is-now-its-def.md``,
"Scope / boundaries"). The hard guardrail that keeps this sanctionable:
senses' loop tool surface is CURATED and coordination-only — never repo
tools. This module IS that surface: it does not drive a loop (a later task
wires this executor into one) and it does not touch the model wire at all —
it is pure protocol + dispatch, exercised entirely through injected
callbacks.

Two pieces:

- The **move protocol** — :data:`MOVE_SCHEMA` / :data:`MOVES` enumerate the
  six coordination moves senses may take, in exactly ONE place.
  :func:`build_moves_instruction` renders that schema into prompt text (the
  form a caller feeds to a tools-off completion — mirroring
  :mod:`colleague.senses`'s ``tools=[]`` completions, which this module never
  issues itself); :func:`parse_move` recovers a move object from the raw
  completion text a served model returns. Because the reference rig's served
  model has no server-side tool parser, "calling a move" here means the model
  writes a small JSON object — nothing tool-shaped ever goes on the wire.
- The **executor** — :class:`SensesMoveExecutor` routes a parsed move to an
  injected coordination callback (dispatch-to-cortex, guide-cortex,
  read-flight, reply, clarify; ``wait`` needs none). It refuses — never
  executes, never raises — any move name outside :data:`MOVES`, so a
  hallucinated move can never reach an injected callback.

Structural boundary (pinned by ``tests/test_senses_moves.py``, mirroring
``colleague/senses.py``'s existing no-ToolExecutor/no-subprocess pin): this
module imports neither ``subprocess`` nor
:class:`colleague.tools.ToolExecutor`, and it never constructs anything
shaped like an OpenAI tool schema — there is no code path here that could
ever hand a non-empty ``tools=`` list to a completion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from colleague.plan.cli_driver import _extract_json_object

# ---------------------------------------------------------------------------
# The coordination moves — enumerated in exactly ONE place (MOVE_SCHEMA).
# Every other name/constant/instruction/executor keying below is DERIVED from
# this one dict, never re-listed by hand, so the move list cannot drift.
# ---------------------------------------------------------------------------

#: Hand the task to cortex, carrying the operator's verbatim words.
MOVE_DISPATCH_TO_CORTEX = "dispatch_to_cortex"
#: Inject mid-run guidance into the running cortex work item.
MOVE_GUIDE_CORTEX = "guide_cortex"
#: Read the running work item's flight-feed / status.
MOVE_READ_FLIGHT = "read_flight"
#: Say something conversational to the operator.
MOVE_REPLY_TO_OPERATOR = "reply_to_operator"
#: Ask the operator a clarifying question before dispatching.
MOVE_CLARIFY = "clarify"
#: Do nothing this turn.
MOVE_WAIT = "wait"

#: The single source of truth for the coordination move protocol: for each
#: move, the positional parameter names the executor extracts from the parsed
#: move object (in order), a short human description, and one example JSON
#: object — both :func:`build_moves_instruction` and
#: :class:`SensesMoveExecutor` are DERIVED from this dict, never re-declared.
MOVE_SCHEMA: "dict[str, dict[str, Any]]" = {
    MOVE_DISPATCH_TO_CORTEX: {
        "params": ("instruction",),
        "description": "hand the task to cortex, carrying the operator's verbatim words",
        "example": {"move": MOVE_DISPATCH_TO_CORTEX, "instruction": "..."},
    },
    MOVE_GUIDE_CORTEX: {
        "params": ("guidance",),
        "description": "inject mid-run guidance into the running cortex work item",
        "example": {"move": MOVE_GUIDE_CORTEX, "guidance": "..."},
    },
    MOVE_READ_FLIGHT: {
        "params": (),
        "description": "read the running work item's flight-feed / status",
        "example": {"move": MOVE_READ_FLIGHT},
    },
    MOVE_REPLY_TO_OPERATOR: {
        "params": ("text",),
        "description": (
            "say something conversational to the operator — answer the current "
            "message from the current result first; background knowledge never "
            "replaces it"
        ),
        "example": {"move": MOVE_REPLY_TO_OPERATOR, "text": "..."},
    },
    MOVE_CLARIFY: {
        "params": ("question",),
        "description": "ask the operator a clarifying question before dispatching",
        "example": {"move": MOVE_CLARIFY, "question": "..."},
    },
    MOVE_WAIT: {
        "params": (),
        "description": "do nothing this turn",
        "example": {"move": MOVE_WAIT},
    },
}

#: The complete, ONLY-valid set of coordination moves senses may take.
#: Anything else is a hallucination :meth:`SensesMoveExecutor.execute` refuses.
MOVES: "frozenset[str]" = frozenset(MOVE_SCHEMA)


def build_moves_instruction() -> str:
    """Render :data:`MOVE_SCHEMA` into prompt text for a tools-off completion.

    Instructs the model to reply with ONLY a single JSON object naming one
    move, listing each move's example shape + description (derived from
    :data:`MOVE_SCHEMA`, never hand-duplicated). The caller feeds this
    alongside its own grounding context to a ``tools=[]`` completion — this
    function builds TEXT only; it never touches the model wire itself.
    """
    lines = [
        "Reply with ONLY a single JSON object naming exactly one coordination "
        'move — the object always has a "move" field plus that move\'s own '
        "parameters, if any. Valid moves:",
    ]
    for schema in MOVE_SCHEMA.values():
        example = json.dumps(schema["example"])
        lines.append(f"  {example} — {schema['description']}")
    lines.append("Choose exactly one move per turn. No prose outside the JSON object.")
    return "\n".join(lines)


def parse_move(raw: str) -> "dict[str, Any]":
    """Recover a move object from *raw* senses completion text; never raises.

    Reuses the solved JSON-recovery path
    (:func:`colleague.plan.cli_driver._extract_json_object`) to tolerate a
    served model wrapping its move in prose or a fenced block, and a
    truncated trailing object gets the same bounded repair every other
    caller of that helper gets.

    Degrades to ``{"move": "reply_to_operator", "text": raw}`` — carrying the
    raw text VERBATIM — whenever the completion cannot be read as a move:
    empty text, unparseable/unbalanced JSON, or a parsed object with no
    usable string ``"move"`` field. This is the parser's ONLY degradation
    path; it never invents a move name, and it never raises.

    A well-formed object naming a move OUTSIDE :data:`MOVES` (a
    hallucination) is returned AS-IS — rejecting it is
    :class:`SensesMoveExecutor`'s job, not the parser's, so the executor's
    refusal is exercised on the actual hallucinated name rather than on a
    parser-substituted one.
    """
    text = raw if isinstance(raw, str) else ""
    try:
        obj = _extract_json_object(text, required_key="move")
    except ValueError:
        return {"move": MOVE_REPLY_TO_OPERATOR, "text": text.strip()}
    move = obj.get("move")
    if not isinstance(move, str) or not move.strip():
        return {"move": MOVE_REPLY_TO_OPERATOR, "text": text.strip()}
    return obj


@dataclass(frozen=True)
class MoveResult:
    """The record of one attempted coordination move — artifact-shaped.

    Exactly one of the three outcomes holds:

    - a clean execution: ``refused=False``, ``degraded=False``, ``outcome``
      carries whatever the injected callback returned.
    - a refusal: ``refused=True`` — the move name was outside :data:`MOVES`,
      or (defensively) an enumerated move had no callback bound. The
      callback is NEVER invoked on this path; ``outcome`` stays ``None``.
    - a degradation: ``degraded=True`` — the move WAS enumerated and its
      callback WAS invoked, but the callback itself raised; the exception is
      caught and never propagates (mirrors :mod:`colleague.senses`'s
      degrade-never-raise convention). ``outcome`` stays ``None``.

    ``detail`` carries a short human-readable reason for a refusal or
    degradation; it is ``None`` on a clean execution.
    """

    move: str
    outcome: Any = None
    refused: bool = False
    degraded: bool = False
    detail: Optional[str] = None


#: A coordination callback's shape varies by move (zero or one positional
#: string argument — see ``MOVE_SCHEMA[move]["params"]``); this alias just
#: documents the family. Every callback may return anything (recorded
#: verbatim on ``MoveResult.outcome``) and may raise (caught and degraded).
MoveCallback = Callable[..., Any]


class SensesMoveExecutor:
    """Route a parsed coordination move to an injected callback.

    Takes ONE optional callback per enumerated move (keyword-only,
    :data:`MoveCallback`) — no repo tool, no subprocess, no I/O of its own:

    - ``dispatch_to_cortex(instruction: str)`` — hand a task to cortex.
    - ``guide_cortex(guidance: str)`` — inject mid-run guidance.
    - ``read_flight()`` — read the run's flight-feed/status.
    - ``reply_to_operator(text: str)`` — say something to the operator.
    - ``clarify(question: str)`` — ask the operator a clarifying question.
    - ``wait()`` — optional; defaults to a no-op when omitted, since "do
      nothing" needs no caller-supplied behavior.

    :meth:`execute` is the ONLY entry point. It NEVER raises: an unknown move
    name (outside :data:`MOVES`) or an enumerated move with no callback bound
    is REFUSED — recorded as a no-op :class:`MoveResult`, the callback never
    invoked — and a bound callback that itself raises DEGRADES the same way,
    the exception caught rather than propagated.
    """

    def __init__(
        self,
        *,
        dispatch_to_cortex: Optional[MoveCallback] = None,
        guide_cortex: Optional[MoveCallback] = None,
        read_flight: Optional[MoveCallback] = None,
        reply_to_operator: Optional[MoveCallback] = None,
        clarify: Optional[MoveCallback] = None,
        wait: Optional[MoveCallback] = None,
    ) -> None:
        self._handlers: "dict[str, Optional[MoveCallback]]" = {
            MOVE_DISPATCH_TO_CORTEX: dispatch_to_cortex,
            MOVE_GUIDE_CORTEX: guide_cortex,
            MOVE_READ_FLIGHT: read_flight,
            MOVE_REPLY_TO_OPERATOR: reply_to_operator,
            MOVE_CLARIFY: clarify,
            # "wait" needs no caller-supplied behavior; default it to a no-op
            # so an omitted `wait=` is a normal clean execution, not a refusal.
            MOVE_WAIT: wait if wait is not None else (lambda: None),
        }

    def execute(self, move_obj: "dict[str, Any]") -> MoveResult:
        """Execute the move named by ``move_obj["move"]``; never raises.

        *move_obj* is typically :func:`parse_move`'s return value, but any
        mapping-like object with a ``"move"`` key (plus that move's own
        parameter keys) is accepted. A missing/non-string/unenumerated
        ``"move"`` refuses immediately with no callback invoked.
        """
        move = move_obj.get("move") if hasattr(move_obj, "get") else None
        if not isinstance(move, str) or move not in MOVES:
            label = move if isinstance(move, str) else repr(move)
            return MoveResult(
                move=label,
                refused=True,
                detail=f"unknown coordination move {label!r}; refused, nothing executed",
            )

        handler = self._handlers.get(move)
        if handler is None:
            return MoveResult(
                move=move,
                refused=True,
                detail=f"no callback bound for move {move!r}; refused, nothing executed",
            )

        param_names = MOVE_SCHEMA[move]["params"]
        args = [move_obj.get(name, "") for name in param_names]
        try:
            outcome = handler(*args)
        except Exception as exc:  # degrade-never-raise (colleague.senses convention)
            return MoveResult(move=move, degraded=True, detail=str(exc))
        return MoveResult(move=move, outcome=outcome)

"""Always-on loop guards for the tool loop (adopt-from-qwen-code, plan t16, spec c20/h15).

Two guards that halt a run instead of letting it grind:

* **identical-calls** — a tool call identical (same name AND same arguments)
  to the four recorded steps before it would be the fifth in a row
  (:data:`IDENTICAL_CALL_THRESHOLD`); the run of five may also fall entirely
  inside one turn's batch;
* **calls-per-turn** — one model turn asked for more than
  :data:`MAX_TOOL_CALLS_PER_TURN` tool calls.

On a trip the loop records ONE named warning (``kind: loop-guard``) on
``TaskResult.warnings``, drops the turn's pending calls (none of them
executes) and ends the run — never silently continues. Only the two
always-on guards qwen-code keeps unconditional transfer; its heuristic
content/thought-repetition tier is off upstream for false positives and is
NOT ported (spec c17 / c20). colleague's existing unknown-tool streak guard
(``loop._tool_protocol_broken``, #321) is untouched and runs beside these.

adapted-from: qwen-code packages/core/src/services/loopDetectionService.ts:35
(TOOL_CALL_LOOP_THRESHOLD = 5), :140 (DEFAULT_MAX_TOOL_CALLS_PER_TURN = 100),
core/client.ts:3717 (pending tool calls dropped on a trip).
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

IDENTICAL_CALL_THRESHOLD = 5
MAX_TOOL_CALLS_PER_TURN = 100
WARNING_KIND = "loop-guard"
GUARD_IDENTICAL = "identical-calls"
GUARD_PER_TURN = "calls-per-turn"


def _key(name: str, arguments: Any) -> str:
    """A stable identity for one call: name + canonical JSON of its arguments."""
    try:
        canon = json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canon = repr(arguments)
    return f"{name}\x00{canon}"


def check(prior_steps: Sequence[Any], calls: Sequence[Any]) -> Optional[dict[str, Any]]:
    """Return the ``loop-guard`` warning a turn's *calls* would trip, or ``None``.

    *prior_steps* are the run's recorded :class:`colleague.contract.Step`
    objects so far (``.tool`` / ``.arguments``); *calls* are the incoming
    :class:`colleague.loop.ToolCall` objects (``.name`` / ``.arguments``).
    The per-turn cap is checked first (a 101-call turn is refused whole).
    """
    if len(calls) > MAX_TOOL_CALLS_PER_TURN:
        return {
            "kind": WARNING_KIND,
            "guard": GUARD_PER_TURN,
            "calls": len(calls),
            "limit": MAX_TOOL_CALLS_PER_TURN,
            "dropped": len(calls),
        }
    history = [_key(s.tool, s.arguments) for s in prior_steps]
    incoming = [_key(c.name, c.arguments) for c in calls]
    sequence = history + incoming
    run = 1
    for i in range(1, len(sequence)):
        run = run + 1 if sequence[i] == sequence[i - 1] else 1
        if run >= IDENTICAL_CALL_THRESHOLD and i >= len(history):
            name = calls[i - len(history)].name
            return {
                "kind": WARNING_KIND,
                "guard": GUARD_IDENTICAL,
                "tool": name,
                "repeats": run,
                "limit": IDENTICAL_CALL_THRESHOLD,
                "dropped": len(calls),
            }
    return None


def summary_note(warning: dict[str, Any], step_count: int) -> str:
    """The one-line summary the run ends with after a trip."""
    if warning.get("guard") == GUARD_PER_TURN:
        detail = f"{warning.get('calls')} tool calls in one turn (limit {warning.get('limit')})"
    else:
        detail = (
            f"{warning.get('repeats')} consecutive identical {warning.get('tool')!r} calls "
            f"(limit {warning.get('limit')})"
        )
    return (
        f"Stopped after {step_count} step(s): loop guard tripped — {detail}; "
        "the pending calls were dropped (see warnings)."
    )

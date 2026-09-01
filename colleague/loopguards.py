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
executes) and ends the run — never silently continues. colleague's existing
unknown-tool streak guard (``loop._tool_protocol_broken``, #321) is untouched
and runs beside these.

**The repetition tier was ported after all (#479, t6) — this docstring's
earlier claim that it "is off upstream for false positives and is NOT ported
(spec c17 / c20)" no longer holds, and is recorded here rather than quietly
dropped.** Only HALF of qwen-code's repetition detector crossed over:

* **ported** — the VERBATIM-TAIL content tier, as
  :mod:`colleague.repetitionguard`, wired into the two transports by
  :mod:`colleague.loop_transport`. The evidence that overturned the earlier
  decision is colleague run ``2bd306a6916a``: at ``low`` effort it emitted
  **271,486 characters** of ONE insight repeated verbatim until
  ``finish_reason=length``, delivering no answer, while every existing guard
  stood down (the stream guards' idle clock restarts on arriving payload bytes,
  so a fast spiral looks maximally alive).
* **still NOT ported** — the ENTROPY / content-heuristic tier, which remains off
  upstream for false positives. Nothing here judges whether text is *repetitive
  enough*; only exact verbatim recurrence trips.

The false-positive risk being accepted: any turn whose reasoning genuinely ends
with a >=48-character unit repeated >=8 times verbatim has its TURN CUT (not the
run ended) and one ``repetition-guard`` warning recorded — legitimate output
shaped that way (a repeated separator line, a generated table of identical rows
emitted in the reasoning channel) would be cut too. The incident carried ~5
orders of magnitude of margin over that threshold, and the trip semantics differ
from this module's on purpose: a loop-guard trip ENDS the run, a repetition trip
CUTS THE TURN into the existing tighter-window retry and only ends the run at
:data:`colleague.repetitionguard.ESCALATION_TRIP_LIMIT` trips — so a false
positive costs one retried turn, not a lost run.

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

"""The thought->action->evaluation adapters the loop calls at its boundaries.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
``_tae_commit_initial_plan`` stays in ``colleague/loop.py`` because it calls
``_build_user_message`` through the loop's own namespace. A pure move.
"""

from __future__ import annotations

from contextlib import suppress

from colleague.loop_constants import _EXIT_FINISHED
from colleague.loop_types import _Work
from colleague.loop_wire import ToolCall


def _tae_drain(ctx: _Work) -> None:
    """Append any front-authored thought briefs as user turns (once each)."""
    if ctx.tae is None:
        return
    for line in ctx.tae.drain_injections():
        ctx.messages.append({"role": "user", "content": line})


def _tae_verdict(ctx: _Work, call: ToolCall) -> str | None:
    """Host classification + the evaluator boundary (t13): the deny reason, or ``None``.

    Decision only — the caller records the refusal (:func:`_record_denial`) so a TAE
    denial reads like every other refusal in the trace. A strict no-op returning
    ``None`` when the mode is unarmed.
    """
    if ctx.tae is None:
        return None
    decision = ctx.tae.before_tool_call(call.name, call.arguments, policy=ctx.policy)
    _tae_drain(ctx)
    return None if decision.allowed else decision.reason


def _tae_close(ctx: _Work, tool: str, ok: bool) -> None:
    """Close an authorized action: the completion half of the supersession policy.

    ``complete_then_re_evaluate`` means a thought that superseded mid-action is
    adopted HERE, once the tool ran to completion — never half-way through, so
    no half-applied tool state exists. A strict no-op when unarmed or when no
    action was in flight.
    """
    if ctx.tae is None:
        return
    ctx.tae.after_tool_call(tool, ok)
    _tae_drain(ctx)


def _tae_finalize(ctx: _Work, outcome: str) -> None:
    """The episode-end boundary + the ledger fold onto the artifact.

    ``episode_completion`` for a finished episode, ``declared_infeasible`` for
    one that ended without a deliverable — both members of the enumerated
    boundary list. The ledger rides ``TaskResult.evaluation_ledger`` (t11's
    omit-when-None field), so an unarmed run adds no artifact key.
    """
    if ctx.tae is None:
        return
    with suppress(Exception):
        ctx.tae.finish_episode(summary=ctx.result.summary, delivered=outcome == _EXIT_FINISHED)
    ctx.result.evaluation_ledger = ctx.tae.ledger_dict()

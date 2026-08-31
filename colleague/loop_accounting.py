"""Per-turn usage accounting — the one place a completion's ``usage`` folds onto
``TaskResult.stats``.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15) into
its own module because BOTH the context lane (compaction) and the transport lane
call it — keeping it here is what makes those two siblings a DAG instead of a
cycle. Tokens are exactly what ``usage`` reports, never estimated. A pure move.
"""

from __future__ import annotations

from colleague import runcounts as _runcounts
from colleague import toolmarkup as _toolmarkup
from colleague.loop_types import _Work
from colleague.loop_wire import ModelResponse


def _account_turn(ctx: _Work, resp: ModelResponse) -> None:
    """Per-turn bookkeeping (always-on): usage, telemetry, stats, last-substantive.

    Counts the turn and accumulates the generated reasoning/answer sizes (chars +
    bytes), mirrored into the optional telemetry as a strict no-op when off. Also
    tracks the last non-empty ``resp.content`` across ALL turns (including
    tool-call turns) — the t2 candidate ``run`` falls back to for the summary —
    via the mutable proxy so the frozen ``_Work`` binding stays intact.

    Also COUNTS (never executes) tool calls the turn emitted as literal markup
    text in its content (#360 / t6, :mod:`colleague.toolmarkup`): the harness
    drops that text, which looks exactly like "the model ignored the tools", so
    the count is what tells the two apart on the artifact.
    """
    ctx.result.usage.add(resp.prompt_tokens, resp.completion_tokens)
    ctx.telemetry.on_completion(resp.prompt_tokens, resp.completion_tokens)
    ctx.result.stats.model_turns += 1
    ctx.result.stats.add_generated(reasoning=resp.reasoning, answer=resp.content)
    ctx.telemetry.on_generated(reasoning=resp.reasoning, answer=resp.content)
    if resp.content:
        ctx._last_substantive[:] = [resp.content]
        _runcounts.bump(ctx.result, "markup_tool_calls", _toolmarkup.count(resp.content))
    # Track the LAST turn's raw finish_reason (t1, c4/h4) — unconditional
    # (even a "" value overwrites), matching the wire's own semantics of "the
    # last completion's own reason", not merely the last non-empty one.
    ctx._last_finish_reason[:] = [resp.finish_reason]
    if resp.served_model and not ctx._served_model:
        ctx._served_model[:] = [resp.served_model]

"""The no-tool-call turn: the continue-working nudge and literal-finish recovery.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
A pure move.
"""

from __future__ import annotations

from colleague.loop_constants import (
    _EXIT_FINISHED,
    _EXIT_STOPPED,
    _FINISH_NUDGE,
    _parse_literal_finish,
)
from colleague.loop_types import _Work
from colleague.loop_wire import ModelResponse


def _handle_no_tool_turn(ctx: _Work, resp: ModelResponse, nudges: int) -> tuple[int, str | None]:
    """Handle a turn that requested no tool — nudge up to the cap, else stop (#142).

    The contract is to call ``finish``; a bare prose turn is usually the model
    trailing off mid-task. Returns ``(nudges, exit)``: while under the configurable
    cap (``ctx.max_continue_nudges``, colleague PR #198) it appends the model's prose
    + a one-line finish reminder and returns ``(nudges + 1, None)`` (caller continues
    the loop); once the cap is reached it returns ``(nudges, _EXIT_STOPPED)`` WITHOUT
    setting ``result.summary`` — the trailing prose is often a mid-thought trail-off
    ("Let me check:"), so leaving the summary empty lets :func:`_maybe_force_synthesis`
    (#191) produce a clean summary from what was read; the prose still survives as the
    ``_last_substantive`` floor when synthesis (and the compaction fallback) yield
    nothing (auto-compact-on-finish, t3).
    """
    # Literal finish-markup recovery (#248 mode B): the "no-tool turn" may actually
    # BE the finish — the model emitted it as literal tool-call text in content.
    # Re-parse it as the finish payload instead of nudging a model that already
    # answered (the nudge/stop path would lose the report from the artifact).
    recovered = _parse_literal_finish(resp.content or "")
    if recovered is not None:
        ctx.result.summary = recovered
        ctx.result.finish_recovered = "literal-markup"
        return nudges, _EXIT_FINISHED
    if nudges < ctx.max_continue_nudges:
        if resp.content:
            ctx.messages.append({"role": "assistant", "content": resp.content})
        ctx.messages.append({"role": "user", "content": _FINISH_NUDGE})
        return nudges + 1, None
    # Do NOT pre-set the trailing prose as the summary (auto-compact-on-finish, t3):
    # a context-rich stop is usually a mid-thought trail-off ("Let me check:") — the
    # t5 failure. Leaving ``result.summary`` empty lets ``_maybe_force_synthesis``
    # (#191) produce a clean summary from what was read; the prose still survives as
    # the ``_last_substantive`` floor when synthesis (and compaction) yield nothing.
    return nudges, _EXIT_STOPPED

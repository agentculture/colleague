"""Tool-call execution primitives: the policy verdict, the executor call, the
unknown-tool streak.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
:func:`_execute_tool` deliberately touches NO loop state (``ctx`` / ``_Work``):
it is the function the read-only tool-batch pool calls off the main thread
(``colleague/toolbatch_loop.py``), which is why it is a free function here and
is re-exported from ``colleague.loop``. A pure move.
"""

from __future__ import annotations

import os
from typing import Any

from colleague.loop_constants import _UNKNOWN_TOOL_STREAK_CAP
from colleague.loop_types import _Work
from colleague.loop_wire import ToolCall
from colleague.tools import ToolError, ToolExecutor, UnknownToolError


def _policy_verdict(ctx: _Work, call: ToolCall) -> str | None:
    """The approval policy on ``run_command`` (decision only): the deny reason, or ``None``.

    Only ``run_command`` is gated — every other tool passes through unchanged.
    """
    if call.name != "run_command":
        return None
    verdict = ctx.policy.check_run_command(str(call.arguments.get("command", "")))
    return None if verdict.allowed else verdict.reason


_EXECUTE_ERRORS = (ToolError, KeyError, TypeError, ValueError)


def _execute_tool(executor: ToolExecutor, name: str, arguments: Any) -> tuple[Any, Any]:
    """Execute ONE tool call: ``(outcome, None)``, or ``(None, exc)`` for the model's own mistake.

    ToolError is the tools' own contract. KeyError/TypeError/ValueError are the
    argument-shaped residue of a malformed MODEL tool call that slipped past
    per-tool validation (live: work item 4c6a96107269 died mid-run on a bare
    KeyError('path') the old ToolError-only catch let escape as an engine failure).
    Either way it costs ONE non-ok step — never the run. Anything else
    (AttributeError, OSError, …) is a genuine harness bug and still aborts loudly.
    This is the ONLY function the read-only batch pool runs (c35/h24): it holds no
    ``_Work`` state, so a worker thread never touches ``ctx``.
    """
    try:
        return executor.execute(name, arguments), None
    except _EXECUTE_ERRORS as exc:
        return None, exc


def _track_unknown_tool(ctx: _Work, name: str, exc: Exception | None) -> None:
    """Advance or reset the unknown-tool streak cell (#321).

    ``exc`` is the failure the call raised — an :class:`UnknownToolError` extends
    the streak; anything else (including ``None``, a call that reached a real
    tool) resets it, because a real dispatch proves the protocol still works.
    """
    cell = ctx._unknown_tool_streak
    if isinstance(exc, UnknownToolError):
        if cell:
            cell[0] += 1
            cell[1] = name
        else:
            cell.extend([1, name])
    elif cell:
        cell[0] = 0


def _unknown_tool_cap() -> int:
    """Operator-tunable unknown-tool streak cap (#321).

    ``COLLEAGUE_MAX_UNKNOWN_TOOL`` overrides ``_UNKNOWN_TOOL_STREAK_CAP`` when it
    parses as an int >= 1; a missing or invalid value falls back to the default,
    so an unset environment stays byte-identical.
    """
    try:
        cap = int(os.environ.get("COLLEAGUE_MAX_UNKNOWN_TOOL", ""))
    except ValueError:
        return _UNKNOWN_TOOL_STREAK_CAP
    return cap if cap >= 1 else _UNKNOWN_TOOL_STREAK_CAP


def _tool_protocol_broken(ctx: _Work) -> bool:
    """True when the unknown-tool streak has hit the cap (#321)."""
    cell = ctx._unknown_tool_streak
    return bool(cell) and cell[0] >= _unknown_tool_cap()

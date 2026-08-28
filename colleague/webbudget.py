"""colleague/webbudget.py — the operator-facing web-call budget (plan t9).

Every ``web`` tool call (colleague/web_schemas.py, plan t2) counts against a
per-work-item budget: ``COLLEAGUE_WEB_MAX_CALLS`` (default 20). Call N+1 is
refused with a :class:`~colleague.tools.ToolError` naming the knob — WITHOUT
spawning webglass — so a chatty model still finishes with the evidence it
already gathered rather than looping forever. The counter lives on the
:class:`~colleague.tools.ToolExecutor` instance (mirrors ``bytes_written``):
``executor.web_calls``/``web_failed`` — so each subagent child, which builds
its own executor, carries its own independent counter, never the parent's.

Two seams tie the counter to the rest of the runtime, both no-wiring (the
same pattern :func:`colleague.editgate.continuation_id` already uses for
``context_note``):

* :func:`finalize` — called once at loop exit (``colleague.loop._finalize_stats``,
  mirroring ``colleague.runcounts.finalize``): copies the counters onto
  :class:`~colleague.contract.WorkStats` and, if the cap was hit this work
  item, appends the ONE ``TaskResult.warnings`` line pointing at
  ``work --continue``/``session /continue``.
* :func:`resume_counts` — called once at loop start (``colleague.loop.run``):
  reads the counters back out of a continuation seed's embedded prose
  (written by :func:`colleague.escalation.build_continuation`) with no
  wiring between ``colleague.continuation``/``colleague.chain`` and the
  executor — so a chained (``--until-done``) or resumed (``work --continue``)
  episode inherits the running total automatically.
"""

from __future__ import annotations

import os
import re
from typing import Any

#: The knob; default 20 (also the fallback for an unset/invalid value).
ENV_MAX_CALLS = "COLLEAGUE_WEB_MAX_CALLS"
DEFAULT_MAX_CALLS = 20

#: The ``kind`` the one cap-reached ``TaskResult.warnings`` entry carries.
WARNING_KIND = "web-budget-cap"

#: What :func:`colleague.escalation.build_continuation` embeds in the seed
#: prose (Section 1) and what :func:`resume_counts` parses back out.
_RESUME_RE = re.compile(r"\*\*Web calls:\*\* (\d+) \(failed: (\d+)\)")


def resolve_max_calls() -> int:
    """``COLLEAGUE_WEB_MAX_CALLS``, defaulting (and falling back) to 20 for an
    unset, non-integer, or non-positive value."""
    raw = os.environ.get(ENV_MAX_CALLS)
    if raw is None:
        return DEFAULT_MAX_CALLS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CALLS
    return value if value > 0 else DEFAULT_MAX_CALLS


def cap_message(max_calls: int) -> str:
    """The :class:`ToolError` text for call N+1 — names the knob and tells the
    model to finish with the evidence it already has."""
    return (
        f"web budget reached: {max_calls} web call(s) already made this work item "
        f"({ENV_MAX_CALLS}={max_calls}) — no more web calls this run; finish with "
        "the evidence already gathered."
    )


def cap_warning(max_calls: int, task_id: str) -> dict[str, str]:
    """The one ``TaskResult.warnings`` entry for a cap hit — its ``detail`` is
    the exact operator-facing line the acceptance criteria specify."""
    detail = (
        f"web cap {max_calls} reached — continue with {ENV_MAX_CALLS}=<higher> via "
        f"work --continue {task_id} / session /continue"
    )
    return {"kind": WARNING_KIND, "detail": detail}


def check_and_increment(executor: Any) -> None:
    """Refuse call N+1 (raise :class:`~colleague.tools.ToolError`, no spawn);
    otherwise increment ``executor.web_calls``. Called ONCE, before
    ``web.run_web`` (colleague/web_schemas.py ``dispatch``)."""
    from colleague.tools import ToolError  # local: avoids the import cycle

    max_calls = resolve_max_calls()
    if executor.web_calls >= max_calls:
        executor.web_cap_hit = max_calls
        raise ToolError(cap_message(max_calls))
    executor.web_calls += 1


def record_result(executor: Any, envelope: Any) -> None:
    """Count one completed call as failed when its envelope is unparseable (None
    or not a dict — t13's fallback shapes) or carries ``lifecycle_state: failed``.
    Called ONCE, after ``web.run_web``."""
    if not isinstance(envelope, dict) or envelope.get("lifecycle_state") == "failed":
        executor.web_failed += 1


def finalize(result: Any, executor: Any) -> None:
    """Copy the executor's counters onto ``result.stats`` and, if the cap was
    hit, append the cap warning — the loop-exit seam (mirrors
    ``colleague.runcounts.finalize``)."""
    result.stats.web_calls = executor.web_calls
    result.stats.web_failed = executor.web_failed
    cap_hit = getattr(executor, "web_cap_hit", None)
    if cap_hit is not None:
        result.warnings.append(cap_warning(cap_hit, result.task_id))


def resume_counts(instruction: str) -> "tuple[int, int]":
    """The ``(web_calls, web_failed)`` counters embedded in a continuation
    seed's prose (:func:`colleague.escalation.build_continuation`), or
    ``(0, 0)`` for an ordinary (or ledger-seeded) work item — the same
    no-wiring seam as :func:`colleague.editgate.continuation_id`."""
    match = _RESUME_RE.search(instruction)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

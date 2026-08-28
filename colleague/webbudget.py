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


def resolve_max_calls(override: "int | None" = None) -> int:
    """*override* when given (t7, c33/h32 — the ONE work-item-wide budget a
    purpose child inherits as its own effective cap, non-negative, 0 meaning
    "no calls left"); otherwise ``COLLEAGUE_WEB_MAX_CALLS``, defaulting (and
    falling back) to 20 for an unset, non-integer, or non-positive value —
    unchanged for every caller that omits *override* (byte-identical). A
    non-``int`` *override* (e.g. a test double's ``MagicMock`` attribute) is
    treated as absent, never crashing the cap check."""
    if isinstance(override, int) and not isinstance(override, bool):
        return max(override, 0)
    raw = os.environ.get(ENV_MAX_CALLS)
    if raw is None:
        return DEFAULT_MAX_CALLS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CALLS
    return value if value > 0 else DEFAULT_MAX_CALLS


def _spawn_config_attr(executor: Any, name: str) -> Any:
    """*name* off the ``EngineConfig`` this *executor* was built from, reached
    via ``executor._spawn.parent_config`` (:func:`colleague.subagents.make_spawn`'s
    no-wiring seam, t7) — ``None`` when the executor carries no spawn callable
    or the callable carries no ``parent_config`` (every construction path
    before t7). Shared by :func:`check_and_increment` (the per-child cap
    override) and :mod:`colleague.purpose_schemas` (the per-seat effort
    overrides / kill-switch)."""
    spawn = getattr(executor, "_spawn", None)
    config = getattr(spawn, "parent_config", None)
    return getattr(config, name, None)


def remaining_for_child(executor: Any) -> int:
    """The ONE work-item-wide web budget a purpose child should inherit (c33/
    h32): this *executor*'s own effective cap (itself honoring an inherited
    ``web_calls_remaining``, so a purpose-within-purpose child stays bounded)
    minus what it has already spent, floored at 0 — never negative."""
    max_calls = resolve_max_calls(_spawn_config_attr(executor, "web_calls_remaining"))
    return max(max_calls - executor.web_calls, 0)


def fold_child_counts(executor: Any, sub: Any) -> None:
    """Fold a returned purpose child's web-call counters onto *executor*
    (c33/h32) — ``sub.web_calls``/``web_failed`` are dynamic attributes
    :func:`colleague.web_schemas.attach_web_report` sets, absent for a child
    that made no ``web`` call (a strict no-op then)."""
    web_calls = getattr(sub, "web_calls", None)
    if not web_calls:
        return
    executor.web_calls += web_calls
    executor.web_failed += getattr(sub, "web_failed", 0) or 0


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

    max_calls = resolve_max_calls(_spawn_config_attr(executor, "web_calls_remaining"))
    if executor.web_calls >= max_calls:
        executor.web_cap_hit = max_calls
        raise ToolError(cap_message(max_calls))
    executor.web_calls += 1


def record_result(executor: Any, envelope: Any, *, exit_code: int = 0) -> None:
    """Count one completed call as failed when the envelope is not a dict,
    lacks ``lifecycle_state`` (e.g. the CLI's usage-error JSON), carries
    ``lifecycle_state: failed``, or the ``run_web`` output's ``exit=`` code is
    non-zero. Called ONCE, after ``web.run_web``."""
    if (
        not isinstance(envelope, dict)
        or "lifecycle_state" not in envelope
        or envelope.get("lifecycle_state") == "failed"
        or exit_code != 0
    ):
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

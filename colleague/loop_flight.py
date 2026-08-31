"""The flight plane the loop feeds: arm, record, fold the talk lane, reap.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
``_flight_stop_requested`` — the ONE call site that reads the control file and
the ONE that appends pilot guidance to ``ctx.messages`` — deliberately stays in
``colleague/loop.py``: a second injection path is exactly what
``tests/test_senses_live_presence_proofs.py`` forbids. A pure move.
"""

from __future__ import annotations

import time
from contextlib import suppress

from colleague import flight as flightmod
from colleague.contract import Task
from colleague.loop_senses import _ensure_senses_block, _record_senses_injection
from colleague.loop_types import _Work
from colleague.loop_wire import ModelResponse


def _record_applied_injection(ctx: _Work, message: str) -> None:
    """Record ONE applied operator-to-cortex guidance injection (live-presence, t5).

    Every guidance message applied at a turn boundary — from the pilot
    (``colleague flight guide``) or the senses talk lane's relay — is made visible
    on BOTH the ephemeral feed and the durable artifact, so the operator's mid-run
    steering is reconstructable from feed + artifact alone (h8 awareness invariant).

    The #206 invariant holds: the feed line carries the CURRENT ``step_count`` and
    adds no step (its ``tool`` is ``None`` — an injection marker, not a tool step),
    and the ``SensesRecord``/``injections`` write never touches ``step_count``. The
    ``at`` timestamp is a wall-clock float, never estimated.
    """
    with suppress(Exception):
        ctx.flight.append_feed(
            step_index=ctx.result.stats.step_count,
            tool=None,
            intent=f"[guidance applied] {message}",
            stats=ctx.result.stats.to_dict(),
        )
    _record_senses_injection(ctx.result, {"text": message, "at": time.time(), "source": "guidance"})
    if ctx.agents is not None:  # #411 t15: mid-run operator input outranks every summary
        ctx.agents.operator_input(message, via="guidance")


def _fold_flight_chat(ctx: _Work) -> None:
    """Fold the talk-lane chat log into ``TaskResult.senses`` at finish (t5).

    Reads the flight chat JSONL (written by the talk-lane clients — ``colleague
    talk`` and the session concurrent lane) BEFORE the reap deletes it, and appends
    each exchange onto ``result.senses.chat`` so the operator's mid-run conversation
    survives in the artifact. A strict no-op when the work item was not a flight or
    no talk lane was used (``read_chat`` -> ``[]``), so a run with no live lane stays
    byte-identical. Never masks the task result.
    """
    if ctx.flight is None:
        return
    with suppress(Exception):
        records = flightmod.read_chat(_flight_repo_path(ctx.task), ctx.task.id)
        if records:
            _ensure_senses_block(ctx.result, mode="cortex-only").chat.extend(records)


def _flight_record(ctx: _Work, resp: ModelResponse) -> None:
    """Append one live-feed record for the turn just processed (no-op when unwatched)."""
    if ctx.flight is None:
        return
    tool = ctx.result.steps[-1].tool if ctx.result.steps else None
    intent = (resp.content or "").strip()[:200] or (f"tool:{tool}" if tool else None)
    ctx.flight.append_feed(
        step_index=ctx.result.stats.step_count,
        tool=tool,
        intent=intent,
        stats=ctx.result.stats.to_dict(),
    )


def _flight_repo_path(task: Task) -> str:
    """Resolve WHERE the flight plane lives for this task (#310).

    ``task.flight_repo_path`` (the OPERATOR repo, set by ``_setup_isolation`` on
    an isolated run) when present, else ``task.repo_path`` (the pre-#310
    behaviour — the in-place session path, byte-identical). The single source of
    truth so the arm side (``_arm_flight``) and every read side
    (``_fold_flight_chat``, the ``FlightSession`` methods it hands back) resolve
    to the SAME directory the operator's ``colleague talk`` / ``colleague flight``
    read and write.
    """
    return task.flight_repo_path or task.repo_path


def _arm_flight(task: Task) -> "flightmod.FlightSession | None":
    """Arm the flight-control plane for a watchable work item, else ``None`` (no-op).

    Built from the existing ``task`` so :func:`run` needs no new parameter (it sits
    near the S107 ceiling); ``arm`` creates the empty feed so a pilot can attach.
    Armed at :func:`_flight_repo_path` (the operator repo on an isolated run, #310)
    so the plane the loop writes is the plane the operator reads.
    """
    return flightmod.arm(_flight_repo_path(task), task.id) if task.watch else None


def _reap_flight(ctx: _Work) -> None:
    """Reap the live flight feed/control on finish (a no-op when not a flight).

    The authoritative result lives in the artifact, not the feed, so the live
    plane stays ephemeral — mirroring the neighbour cleanup. A reap failure must
    never mask the task result.
    """
    if ctx.flight is not None:
        with suppress(Exception):
            ctx.flight.reap()

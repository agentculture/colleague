"""Run-scoped seat-effort recording (effort-v4 t5, c6/c14/h5/h6).

The observability half of the thinking-effort ladder (#416/#476): the loop
records the EFFECTIVE resolved rung of every seat built during a run onto the
artifact — ``FinishRecord.reasoning_effort`` for the seats that carry finish
records ("main", "senses"), and a top-level ``TaskResult.effort`` block
(``{seat: rung}``) that also names the no-finish-record seats (a scout/purpose
child by its role, the distill pass).

A NEW focused module (not more lines in ``colleague/effort.py`` /
``colleague/loop_outcomes.py``) purely for the file-length ratchet
(``tests/test_file_length_ratchet.py`` — both siblings sit at their
baselines). Pure stdlib + one import from :mod:`colleague.effort`.

The recorded value is never recomputed per consumer (t5 instruction): the
acting seat's rung is :func:`colleague.effort.effort_of` — documented as
exactly what ``vllm_openai._effort_for`` sends on the wire — resolved ONCE in
``ContextControls.from_config`` and threaded through the loop's ``ctx``; a
child seat's rung is read off the ``reasoning_effort_seat`` its builder
already set (``SubResult.reasoning_effort``); the distill seat's rung is the
already-resolved ``DistillAuthor.effort``. :func:`seat_effort` below is the
ONE shared formula for a named non-acting seat (the senses builder calls it
too, so the recorded senses rung and the built senses seat can never
diverge).

Presence rule (t5 spec): a seat that resolved ``"off"`` records ``"off"``; a
seat that never resolved (``None`` = send nothing, e.g. the ``default``
kill-switch, or a direct ``run()`` caller with no config) is simply ABSENT
from the block — never an invented row. The ladder-400 retry warning
(``vllm_payload.ladder_retry_warnings_as_dicts``) stays the marker for a
dropped key (c29): a run can honestly carry BOTH the recorded rung and the
retry warning — neither erases the other.
"""

from __future__ import annotations

from typing import Any, Optional

from colleague import effort


def seat_effort(config: Any, seat: str) -> Optional[str]:
    """Resolve named non-acting *seat*'s rung — the seat builders' formula.

    Kill-switch (global ``reasoning_effort == "default"``) > the per-seat
    override (``reasoning_effort_seats[seat]``) > the seat table — exactly
    the resolution ``senses.py``'s seat builder applies (which now calls this
    helper), so the recorded value IS the built seat's value, not a
    recomputation that could drift.
    """
    return effort.resolve_effort(
        kill_switch=(getattr(config, "reasoning_effort", None) == effort.DEFAULT_SENTINEL),
        seat_override=(getattr(config, "reasoning_effort_seats", {}) or {}).get(seat),
        seat=seat,
    )


def record(result: Any, seat: str, rung: Optional[str]) -> None:
    """Fold one built seat's resolved rung onto ``result.effort``.

    ``None`` (never resolved / send-nothing) records NOTHING — the seat stays
    absent, matching the omit-when-None artifact convention. ``"off"`` is a
    real resolved rung and IS recorded. Later same-seat records overwrite
    (idempotent for the fixed per-seat tables). The block is created lazily so
    a run that resolves no seat serializes byte-identically (no ``effort``
    key).
    """
    if rung is None:
        return
    block = dict(getattr(result, "effort", None) or {})
    block[seat] = rung
    result.effort = block


def fold_run_seats(ctx: Any) -> None:
    """Record every seat the run built, from what the loop already carries.

    Called from ``loop_outcomes._finalize_finish_states`` (both exit paths):
    the acting seat under its finish-record name ``"main"``; ``"senses"`` only
    when senses actually produced records (the same condition its finish
    record keys on); each delegated child under its role name (``"subagent"``
    for the default full-surface delegation), read live off the executor —
    ``result.sub_results`` is snapshotted after this point on some paths. The
    distill seat records separately at its own launch site
    (``loop_memory._distill_pass``), which can run after this fold.
    """
    record(ctx.result, "main", ctx.reasoning_effort_main)
    senses = ctx.result.senses
    if senses is not None and senses.records:
        record(ctx.result, "senses", ctx.reasoning_effort_senses)
    for sub in getattr(ctx.executor, "sub_results", []) or []:
        record(ctx.result, sub.role or "subagent", getattr(sub, "reasoning_effort", None))

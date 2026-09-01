"""Per-turn usage accounting — the one place a completion's ``usage`` folds onto
``TaskResult.stats``.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15) into
its own module because BOTH the context lane (compaction) and the transport lane
call it — keeping it here is what makes those two siblings a DAG instead of a
cycle. Tokens are exactly what ``usage`` reports, never estimated. A pure move.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Sequence

from colleague import reasoninglog as _reasoninglog
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
    _record_turn_reasoning(ctx, resp)
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


# ---------------------------------------------------------------------------
# Reasoning sidecar (effort-v4 plan task t6, spec c16/h7/c34/h20).
#
# Display/disk only: nothing here touches ``ctx.messages`` — the model context
# is byte-identical with and without the sidecar (h7), and the off-knob
# (``COLLEAGUE_REASONING_LOG=0``) writes nothing at all (checked inside
# :func:`colleague.reasoninglog.append`). Chain-episode semantics (plan risk
# r1, decided here): per-run append — one file per task id, episodes of an
# armed chain (which reuse the id) APPEND to the same file under the t3
# module's per-file size cap; no per-episode file is minted.
# ---------------------------------------------------------------------------


def _sidecar_destination(task: Any) -> tuple[str, str, "str | None"]:
    """``(repo_dir, task_id, child_id)`` for this run's sidecar.

    The destination repo follows the flight-plane precedent (#310):
    ``reasoning_repo_path`` (a subagent child tagged to the operator repo, h20)
    > ``flight_repo_path`` (an isolated parent run) > ``repo_path``. A child
    (``reasoning_parent_id`` set) files under the PARENT id with its own id as
    the tag — ``<parent>.<child>.reasoning.jsonl``."""
    repo = (
        getattr(task, "reasoning_repo_path", None)
        or getattr(task, "flight_repo_path", None)
        or task.repo_path
    )
    parent = getattr(task, "reasoning_parent_id", None)
    if parent:
        return repo, parent, task.id
    return repo, task.id, None


def _next_request_index(ctx: Any) -> int:
    """Consume one within-turn dispatch ordinal (c34); ``0`` without a cell."""
    cell = getattr(ctx, "_reasoning_ordinal", None)
    if cell is None:
        return 0
    if not cell:
        cell.append(0)
    index = cell[0]
    cell[0] = index + 1
    return index


def _append_record(ctx: Any, *, index: int, ts: str, text: str) -> None:
    """One sidecar record; a write failure never fails the run (disk-only)."""
    task = getattr(ctx, "task", None)
    if task is None:  # a bare test double without a task: nothing to file under
        return
    repo, task_id, child_id = _sidecar_destination(task)
    record = {
        "seat": getattr(ctx, "seat", "main"),
        "turn": getattr(getattr(ctx.result, "stats", None), "model_turns", 0),
        "request_ts": ts,
        "request_index": index,
        "text": text,
    }
    with suppress(OSError):
        _reasoninglog.append(repo, task_id, record, child_id=child_id)


def _record_turn_reasoning(ctx: _Work, resp: ModelResponse) -> None:
    """One sidecar record per model turn, when the turn carried reasoning.

    Always resets the within-turn ordinal and consumes ordinal 0 for the
    completion itself — reasoning or not — so the turn's tool dispatches number
    identically whether or not the model emitted a reasoning field. The cell's
    second element marks the turn ACTIVE (it carried reasoning): a
    reasoning-free turn writes no records at all — not even tool-call records —
    so a reasoning-free run leaves the tree untouched and a mid-run
    ``list_dir`` byte-identical to a run that never had the sidecar (h7: the
    sidecar materializes only when there is reasoning to journal)."""
    active = bool(resp.reasoning)
    cell = getattr(ctx, "_reasoning_ordinal", None)
    if cell is not None:
        cell[:] = [0, 1 if active else 0]
    index = _next_request_index(ctx)
    if not active:
        return
    _append_record(ctx, index=index, ts=_reasoninglog.now_ts(), text=resp.reasoning)


def _turn_active(ctx: Any) -> bool:
    """Whether the current turn carried reasoning (True for a cell-less double,
    whose missing ``task`` already keeps :func:`_append_record` a no-op)."""
    cell = getattr(ctx, "_reasoning_ordinal", None)
    if cell is None or len(cell) < 2:
        return True
    return bool(cell[1])


def record_tool_dispatch(ctx: Any, calls: Sequence[Any]) -> None:
    """N tool-call sidecar records sharing ONE ``request_ts``/``request_index``.

    Called by :mod:`colleague.toolbatch_loop` once per dispatch — a parallel
    batch passes its whole request-ordered batch (N records, one shared
    timestamp + ordinal), the sequential path passes one call at a time (each
    consuming its own ordinal), which is exactly the c34 contract: batch
    members share the turn's ONE index, a sequential pair gets two. The
    ordinal is consumed even when nothing lands on disk (off-knob, or a
    reasoning-free turn — see :func:`_record_turn_reasoning`), so indices are
    stable either way."""
    if not calls:
        return
    index = _next_request_index(ctx)
    if not _turn_active(ctx) or not _reasoninglog.enabled():
        return
    ts = _reasoninglog.now_ts()
    for call in calls:
        _append_record(ctx, index=index, ts=ts, text=f"tool_call: {getattr(call, 'name', '')}")

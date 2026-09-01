"""Run-scoped seat-sampling recording (#479 t9, c38/h30).

The observability half of the per-model sampling arc (#479), mirroring
:mod:`colleague.effortrecord` exactly — same presence rule, same
"resolve once, thread the already-resolved value, never recompute per
consumer" discipline — but for the resolved :class:`colleague.sampling.
SamplingProfile` instead of the thinking-effort rung.

**Where it lands.** Each resolved seat's record folds onto
``TaskResult.sampling``, a dedicated top-level field with the same
omit-when-``None`` treatment ``effort`` gets — so a run whose model matched no
row serializes byte-identically to a pre-#479 artifact.

*Integrator note:* t9 as briefed could not touch ``colleague/contract.py`` /
``colleague/contract_taskresult_io.py``, so it originally rode
``TaskResult.warnings`` — the codebase's generic kind-tagged bag. That worked,
but a sampling record is not a warning, and because the default config matches
the builtin Qwen3.8 row it made ``warnings`` unconditionally non-empty on an
ordinary run. The field was added at merge time (#479 arc deviation d5) so the
module now follows ``effortrecord`` all the way down, as its instruction asked.

**Row vs wire (t9 instruction).** A :class:`~colleague.sampling.SamplingProfile`
is the card's ROW — every key the row explicitly sets, via
:func:`colleague.sampling.sampling_payload`. The WIRE is what
:func:`colleague.samplingwire.wire_fragment` renders after dropping any key
that already equals :data:`colleague.samplingwire.SERVER_DEFAULT_SAMPLING`
(e.g. on the Qwen3.8 thinking row, ``min_p``/``presence_penalty``/
``repetition_penalty`` are in the ROW but not the WIRE). Both are recorded,
each under its own labeled key, so a reader can never mistake "the card says"
for "the request carried" (the exact misstatement already fixed once in
``config show``, arc deviation d4).

**Presence rule (t9 instruction, mirrors effortrecord.py exactly).** A seat
whose model+rung resolves NO row (an unmatched model, an off/never-resolved
rung) is simply ABSENT from ``result.sampling`` — no entry is appended. Never an
invented/empty placeholder entry.

**Honest limits on fidelity (Qodo #485 finding 6).** This module resolves
against :data:`colleague.sampling.BUILTIN_SAMPLING_ROWS` only. Two consequences,
both recorded rather than papered over:

* ``COLLEAGUE_SAMPLING=0`` IS honoured — the kill switch sent no sampling keys,
  so :func:`record` writes nothing and absence reads as "nothing was sent".
* An operator ``.colleague/models.json`` row that OVERRIDES a builtin is NOT
  reflected here: the adapter layers those rows (``vllm_payload.
  _operator_sampling_rows``) and this module does not, so a run whose operator
  table overrides a builtin records the BUILTIN values. The same limit applies
  to ``config show`` (risk r7). Threading the payload path's own resolution
  into finalization is the real fix and is a follow-up, not a claim made here.

**Scope of the fold (honest limit).** Only seats that actually run through
the adapter's ``_sampling_fragment`` write site are recorded: the acting
("main") seat and any delegated child (each riding its own resolved model +
rung, read off ``SubResult.model``/``.role``/``.reasoning_effort`` exactly
like ``effortrecord.fold_run_seats`` reads them). The senses lane is
deliberately NOT recorded here: ``colleague/senses.py`` never calls
``_sampling_fragment`` today, so a senses entry would claim a card applied
that the current wire never actually sends — recording it would misstate
"resolved" as "sent" for the one seat where those two are not the same
fact yet. Widening senses sampling is future work, not this task.

Only against the BUILTIN table (:data:`colleague.sampling.BUILTIN_SAMPLING_ROWS`,
``rows=None``): this leaf has no access to an operator ``models.json`` merge
(that needs the repo root + config plumbing ``_operator_sampling_rows`` reads
inside ``colleague/engines/vllm_payload.py``, out of this task's file
ownership) — so an operator override row is not reflected in this record even
though it would be reflected on the real wire. Documented, not silent.

Pure stdlib plus :mod:`colleague.sampling` / :mod:`colleague.samplingwire`.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from colleague import sampling, samplingwire

__all__ = ["KIND", "fold_run_seats", "record", "resolve_seat_record"]

#: The record tag for one seat's resolved sampling record. Retained for
#: readers that filtered on it while these records rode ``warnings``.
KIND = "sampling"


def resolve_seat_record(model: Any, role: Optional[str], rung: Any) -> Optional[dict]:
    """Resolve one seat's sampling record, or ``None`` for genuine absence.

    ``None`` covers every non-match: an unparseable/never-resolved rung (no
    half), the kill-switch sentinel, or a model no builtin row claims. The
    caller must not synthesize a placeholder for any of these — that is the
    presence rule this function exists to enforce in one place.
    """
    # The SAME merged table the adapter sends: builtin rows plus the
    # operator's models.json, operator last so an equal-specificity row wins
    # (Qodo #485 finding 6 / risk r7 — recording builtin-only made the
    # artifact describe a request that was never sent).
    root = os.environ.get("COLLEAGUE_MEMORY_ROOT") or os.getcwd()
    rows = sampling.BUILTIN_SAMPLING_ROWS + samplingwire.operator_rows(root)
    profile = sampling.resolve_sampling(model, role=role, rung=rung, rows=rows)
    if profile is None:
        return None
    return {
        "half": sampling.half_for_rung(rung),
        "row": sampling.sampling_payload(profile),
        "wire": samplingwire.wire_fragment(profile),
    }


def record(result: Any, seat: str, model: Any, role: Optional[str], rung: Any) -> None:
    """Fold one seat's resolved sampling record onto ``result.sampling``.

    A seat that does not resolve (:func:`resolve_seat_record` returns
    ``None``) is left untouched — never an invented entry. Later same-seat
    records for one run replace the prior entry (idempotent for the fixed
    per-run resolution), matching ``effortrecord.record``'s overwrite
    semantics for its ``{seat: rung}`` block.
    """
    if not samplingwire.sampling_enabled():
        # The kill switch sent NO sampling keys, so recording a row would
        # describe a request that never happened (Qodo #485 finding 6,
        # reproduced: COLLEAGUE_SAMPLING=0 sent temperature 0.0 while the
        # record claimed the full thinking row). Absence is the honest record.
        return
    resolved = resolve_seat_record(model, role, rung)
    if resolved is None:
        return
    entries = [
        e
        for e in (getattr(result, "sampling", None) or [])
        if not (isinstance(e, dict) and e.get("seat") == seat)
    ]
    entries.append({"seat": seat, **resolved})
    result.sampling = entries


def fold_run_seats(ctx: Any) -> None:
    """Record every seat this run resolved a sampling profile for.

    Called from ``loop_outcomes._finalize_finish_states``, right beside the
    ``effortrecord.fold_run_seats`` call it mirrors: the acting seat under its
    finish-record name ``"main"`` (model ``ctx.model``, role ``None`` — the
    builtin table's rows all claim ``role=None``, "any role", matching how
    ``vllm_payload._sampling_fragment`` resolves the main completion), then
    each delegated child under its role name, read live off the executor
    exactly like ``effortrecord.fold_run_seats`` does (``sub.model``/
    ``sub.role``/``sub.reasoning_effort``). The senses seat is deliberately
    excluded (see module docstring).
    """
    record(ctx.result, "main", ctx.model, None, ctx.reasoning_effort_main)
    for sub in getattr(ctx.executor, "sub_results", []) or []:
        record(
            ctx.result,
            sub.role or "subagent",
            getattr(sub, "model", ""),
            sub.role,
            getattr(sub, "reasoning_effort", None),
        )

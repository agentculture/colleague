"""Exact per-run harness counters on the artifact (plan t20, spec c43/h32).

Five integers land on ``WorkStats.counts`` — the adopt-from-qwen-code
mechanisms' own scoreboard, every one an exact count incremented by the code
path that did the work (never estimated):

* ``batches_run`` — parallel read-only tool batches the loop executed
  (:mod:`colleague.toolbatch_loop`, plan t15);
* ``calls_parallelised`` — tool calls that ran inside those batches;
* ``results_blanked`` — old tool results the microcompaction floor blanked
  (:mod:`colleague.turnbudget`, plan t16 — derived from its
  ``microcompaction`` warnings, which are the per-pass record);
* ``outputs_spilled`` — tool outputs whose full text went to
  ``.colleague/tool-output/`` (:mod:`colleague.readpage` /
  :mod:`colleague.truncation`, plan t9/t11);
* ``guard_trips`` — always-on loop guards that halted the run
  (:mod:`colleague.loopguards`, plan t16 — derived from its warnings).

Shape rule (all-engines, c19/h14): ``WorkStats.to_dict`` emits the ``counts``
block ONLY when at least one counter is non-zero, so a run that never touched
a mechanism — every ``mock`` run today — keeps the pre-arc 14-key stats
block byte-for-byte. :func:`counts_of` gives readers the full five-key view
with zeros filled in.
"""

from __future__ import annotations

from typing import Any

#: The five counter keys, in artifact order.
KEYS: tuple[str, ...] = (
    "batches_run",
    "calls_parallelised",
    "results_blanked",
    "outputs_spilled",
    "guard_trips",
)

#: Warning kinds whose records the finalizer folds into a counter.
_MICROCOMPACTION_KIND = "microcompaction"
_LOOP_GUARD_KIND = "loop-guard"


def bump(result: Any, key: str, n: int = 1) -> None:
    """Add *n* to counter *key* on ``result.stats.counts`` (a no-op for ``n <= 0``)."""
    if key not in KEYS:
        raise KeyError(f"unknown run counter {key!r}; expected one of {KEYS}")
    if n <= 0:
        return
    counts = result.stats.counts
    counts[key] = int(counts.get(key, 0)) + int(n)


def counts_of(result: Any) -> dict[str, int]:
    """The five counters with zeros filled in — the reader-side view."""
    counts = getattr(getattr(result, "stats", None), "counts", None) or {}
    return {key: int(counts.get(key, 0)) for key in KEYS}


def finalize(result: Any, executor: Any = None) -> None:
    """Fold the derived counters in at loop exit (called from ``_finalize_stats``).

    ``results_blanked`` and ``guard_trips`` are read back from the warnings the
    mechanisms already record per event (so the counter and the record can
    never disagree); ``outputs_spilled`` is the executor's spill tally
    (:func:`colleague.readpage.bound_output` stamps it). The two batch counters
    are bumped live by :mod:`colleague.toolbatch_loop`. Idempotent: derived
    counters are recomputed, not accumulated.
    """
    warnings = list(getattr(result, "warnings", None) or [])
    blanked = sum(
        int(w.get("blanked", 0))
        for w in warnings
        if isinstance(w, dict) and w.get("kind") == _MICROCOMPACTION_KIND
    )
    trips = sum(1 for w in warnings if isinstance(w, dict) and w.get("kind") == _LOOP_GUARD_KIND)
    spilled = int(getattr(executor, "outputs_spilled", 0) or 0)
    counts = result.stats.counts
    for key, value in (
        ("results_blanked", blanked),
        ("guard_trips", trips),
        ("outputs_spilled", spilled),
    ):
        if value > 0:
            counts[key] = value
        else:
            counts.pop(key, None)

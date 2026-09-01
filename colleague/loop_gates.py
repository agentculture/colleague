"""The pre-finish gate lane: the chain deferral branch, the changed-file set, the
lint gate and the coherence gate.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
The bounded fix turns re-enter the loop through the ``work_loop`` callable the
caller threads in — ``colleague/loop.py`` passes its own ``_work_loop``. That
injection is what keeps this module out of an import cycle with the loop; it is
the same function object as before, so behavior is unchanged.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Callable

from colleague import coherence as _coherencemod
from colleague import lint as _lint
from colleague.loop_constants import _EXIT_FINISHED, _LINT_FIX_PROMPT, _LINT_FIX_STEPS
from colleague.loop_gatebase import (
    _gate_changed_set,
    _gates_deferred_to_chain,
    _record_gate_deferral,
)
from colleague.loop_testgates import (
    _maybe_run_affected_tests_gate,
    _maybe_run_import_check_gate,
    _maybe_run_test_integrity_gate,
)
from colleague.loop_types import _Work
from colleague.loop_wire import CompleteFn


def _run_pre_finish_gates(
    ctx: _Work,
    complete: CompleteFn,
    outcome: str,
    aborted: Exception | None,
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Run the five pre-finish gates — or record their chain deferral (#335, c8/c10).

    A chain episode exiting on a continuation shape (budget-exhausted, or a
    declared fill-line finish-with-handoff — the SAME signals
    ``colleague/chain.py`` continues on) skips the gates: the next episode
    rewrites this tree, so mid-chain gates would spend per-episode budget
    grading intermediate state. Recorded ONCE per episode on the artifact (the
    :func:`_record_fillline_cap` precedent) — never silent. The chain's FINAL
    (finish-shaped) episode runs them over union(this episode's changed,
    prior_changed) via :func:`_gate_changed_set` (c23), keeping the live-loop
    fix-turn / re-examine paths intact — the post-hoc gate shape was rejected
    for exactly that loss. A non-chained run never defers (byte-identical),
    incl. an ``until_done`` run without a chain dispatch and every subagent
    child (c22). Each gate keeps its own aborted guard + best-effort wrapping
    (it can never abort :func:`run`); ordering is load-bearing — coherence,
    test-integrity, affected-tests, and import-check all grade the
    lint-fixed changed set. Import-check (#482/t6) is the fifth gate, added
    after t1/t3 landed: it deliberately sits behind the SAME chain-deferral
    early-return as the other four (mirroring the affected-tests precedent)
    even though it has no ``ContextControls`` enable flag of its own — see
    :func:`colleague.loop_testgates._maybe_run_import_check_gate`.
    Extracted from :func:`run` so the deferral branch keeps ``run()`` under
    the S3776 cognitive-complexity ceiling (the PR #338 Sonar catch).

    ``work_loop`` is :func:`colleague.loop._work_loop`, threaded in rather than
    imported so this module never imports ``colleague.loop`` (the gate lanes
    live in siblings; the loop is the top of the import DAG). Same function
    object as before — the bounded fix turns re-enter the identical loop.
    """
    if _gates_deferred_to_chain(ctx, outcome, aborted):
        _record_gate_deferral(ctx)
        return
    # Lint (#200): auto-fix changed files; residual reporter violations after a
    # clean finish get ONE bounded model fix-turn per remaining retry.
    _maybe_run_lint_gate(ctx, complete, outcome, aborted, work_loop=work_loop)
    # Coherence (#294, colleague#291 S3): score the changed .md files; warn-only.
    _maybe_run_coherence_gate(ctx, aborted)
    # Test-integrity (#203): flag the mirror signature; advisory + non-blocking.
    _maybe_run_test_integrity_gate(ctx, complete, outcome, aborted, work_loop=work_loop)
    # Affected-tests (#213): run the tests transitively importing the changed
    # module(s); advisory + non-blocking.
    _maybe_run_affected_tests_gate(ctx, complete, outcome, aborted, work_loop=work_loop)
    # Import-check (#482/t6, h4): py_compile + subprocess import smoke of the
    # changed .py files, on EVERY outcome (no fix-turn, no outcome gating) —
    # closes the row-67 gap where a non-importing branch shipped on a
    # budget-exhausted outcome and told no one.
    _maybe_run_import_check_gate(ctx, aborted)


def _maybe_run_lint_gate(
    ctx: _Work,
    complete: CompleteFn,
    outcome: str,
    aborted: Exception | None,
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Run the pre-finish lint gate: auto-fix changed files, then surface residual (#200).

    Deterministic fixers (black/isort/ruff) run first; if reporter (flake8 / ruff
    check) violations remain AND the main loop finished cleanly AND a fix-turn budget
    is left, ONE bounded model fix-turn is injected per remaining retry (capped by
    ``ctx.lint_fix_retries``), re-running the gate after each. Non-blocking: the
    handoff always proceeds; the final :class:`~colleague.contract.LintReport` is
    attached to ``result.lint_report``. A strict no-op when the loop aborted, lint is
    disabled, no files changed, or no linters are configured (the gate returns
    ``None``). The model fix-turn is held to a clean finish — an incomplete run
    (budget/stop) should not spend extra turns chasing lint nits, and its INCOMPLETE
    status must stand.

    Best-effort + fail-safe (#209 review): the body is wrapped in ``suppress`` so a
    linter that hangs/errors past :mod:`colleague.lint`'s own guards can NEVER abort
    ``run()`` (which calls this AFTER its main try/except, before the changed_files
    snapshot). Mirrors the neighbour-clone / hook fail-safes.
    """
    if aborted is not None or not ctx.lint_enabled:
        return
    with suppress(Exception):
        changed = _gate_changed_set(ctx)
        if not changed:
            return
        report = _lint.run_lint_gate(ctx.task.repo_path, changed)
        if report is None:
            return
        retries = ctx.lint_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.residual and retries > 0:
            _run_lint_fix_turn(ctx, complete, report.residual, work_loop=work_loop)
            retries -= 1
            next_report = _lint.run_lint_gate(ctx.task.repo_path, _gate_changed_set(ctx))
            if next_report is None:
                break
            report = next_report
        ctx.result.lint_report = report


def _run_lint_fix_turn(
    ctx: _Work,
    complete: CompleteFn,
    residual: list[str],
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Inject ONE bounded model turn to fix residual lint, preserving terminal state.

    Re-enters :func:`_work_loop` with a small extra step budget after appending a fix
    instruction listing the residual violations. The main work's terminal fields
    (``summary`` / ``status`` / the two outcome flags) are saved and restored so a
    fix-turn ``finish`` cannot clobber the work item's real summary or flip its status.
    Any fix-turn failure is suppressed — the lint gate is best-effort and must never
    abort the work item (the same fail-safe as hooks / neighbour clones).
    """
    saved = (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    )
    ctx.messages.append({"role": "user", "content": _LINT_FIX_PROMPT + "\n".join(residual[:50])})
    budget = ctx.result.stats.model_turns + _LINT_FIX_STEPS
    with suppress(Exception):
        work_loop(ctx, complete, budget)
    (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    ) = saved


def _maybe_run_coherence_gate(ctx: _Work, aborted: Exception | None) -> None:
    """Run the coherence pre-finish gate on the changed docs (#294, #291 S3).

    Shells ``coherence meaning score <file> --json`` per changed ``.md`` file
    (:func:`colleague.coherence.run_coherence_gate`), recording the result on
    ``result.coherence_report`` with the measurement's frame provenance (the
    embedder env the subprocess saw — the lobes-injected one when armed,
    ``ctx.embed_env``). Advisory + warn-only: no fix-turn, never blocks the
    handoff, and a run with no changed docs / no CLI / the gate disabled is
    byte-identical (omit-when-None). Best-effort + fail-safe like the lint
    gate: the body is wrapped so it can never abort ``run()``.
    """
    if aborted is not None or not ctx.coherence_enabled:
        return
    with suppress(Exception):
        changed = _gate_changed_set(ctx)
        if not changed:
            return
        report = _coherencemod.run_coherence_gate(
            ctx.task.repo_path, changed, env_overrides=ctx.embed_env
        )
        if report is None:
            return
        ctx.result.coherence_report = report

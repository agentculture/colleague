"""The test-facing gates: acceptance self-check, test integrity, affected tests.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
Like ``colleague/loop_gates.py``, the bounded fix turns re-enter the loop via an
injected ``work_loop`` callable rather than importing ``colleague.loop``.
A pure move.
"""

from __future__ import annotations

import json
import shlex
import sys
from contextlib import suppress
from typing import Any, Callable

from colleague import affectedtests as _affectedtests
from colleague import testintegrity as _testintegrity
from colleague.config import MAX_SUBAGENT_FANOUT
from colleague.loop_accounting import _account_turn
from colleague.loop_constants import (
    _ACCEPTANCE_CHECK_PROMPT,
    _AFFECTEDTESTS_FIX_PROMPT,
    _AFFECTEDTESTS_FIX_STEPS,
    _EXIT_FINISHED,
    _TESTINTEGRITY_FIX_PROMPT,
    _TESTINTEGRITY_FIX_STEPS,
    _TESTINTEGRITY_REVIEWER_PROMPT,
)
from colleague.loop_gatebase import _gate_changed_set
from colleague.loop_senses import _record_deepthink
from colleague.loop_transport import _complete_with_degradation
from colleague.loop_types import ContextControls, _Work
from colleague.loop_wire import CompleteFn


def _parse_acceptance_outcomes(text: str, criteria: list[str]) -> list[dict[str, object]]:
    """Parse the self-check turn's JSON into per-criterion outcome records.

    Tolerant by contract (the check is advisory and must never raise): any
    parse failure returns ``[]`` (nothing recorded). Entries are matched to the
    task's criteria BY POSITION and the criterion text is taken from the TASK
    (authoritative), so a model that paraphrases or hallucinates criteria can
    only ever grade the real ones; a missing entry reads as ``met=False`` with
    empty evidence — the conservative default.
    """
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        data = json.loads(text[start:end])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    outcomes: list[dict[str, object]] = []
    for index, criterion in enumerate(criteria):
        entry = data[index] if index < len(data) and isinstance(data[index], dict) else {}
        outcomes.append(
            {
                "criterion": criterion,
                "met": bool(entry.get("met", False)),
                "evidence": str(entry.get("evidence") or ""),
            }
        )
    return outcomes


def _maybe_run_acceptance_selfcheck(
    ctx: _Work, complete: CompleteFn, outcome: str, aborted: Exception | None
) -> None:
    """ONE bounded self-check turn recording per-criterion outcomes (t15 / R6 / #259).

    Fires only when the task declared ``acceptance`` criteria AND the loop
    finished cleanly (an incomplete/aborted run should not spend a turn grading
    itself; its honest status must stand untouched). The check is a SINGLE
    completion — never a re-entered tool loop — so it structurally cannot call
    ``finish`` and cannot clobber the work item's terminal summary/status (a
    stronger invariant than the lint fix-turn's save/restore, by construction).
    ADVISORY only: outcomes land on ``result.acceptance_outcomes`` for the
    feedback/ROI loop; ``met=False`` never flips the run status — operator
    judgment stays the authority (the devague-tool convention: the backend
    cannot self-confirm). Best-effort + fail-safe like the sibling gates.
    """
    if aborted is not None or outcome != _EXIT_FINISHED or not ctx.task.acceptance:
        return
    with suppress(Exception):
        criteria = [str(criterion) for criterion in ctx.task.acceptance]
        # Dual-model escalation (t5 / spec c10c): grading criteria is a judgment
        # call, so a dual-model run asks the DEEPTHINK model first — with a
        # self-contained digest (instruction + goal + summary + criteria), never
        # the full history, so the prompt fits the deepthink model's own smaller
        # window (the seam windows it besides). A degraded or unparseable
        # escalation FALLS BACK to the main-model turn below (spec c13/h5) — the
        # attempt is recorded either way, the run never fails because of it.
        if _selfcheck_via_deepthink(ctx, criteria):
            return
        ctx.messages.append(
            {
                "role": "user",
                "content": _ACCEPTANCE_CHECK_PROMPT
                + "\n".join(f"- {criterion}" for criterion in criteria),
            }
        )
        resp = _complete_with_degradation(ctx, complete)
        _account_turn(ctx, resp)
        outcomes = _parse_acceptance_outcomes(resp.content or resp.reasoning or "", criteria)
        if outcomes:
            ctx.result.acceptance_outcomes = outcomes


def _selfcheck_via_deepthink(ctx: _Work, criteria: list[str]) -> bool:
    """Grade the acceptance criteria via the deepthink model (t5 / spec c10c).

    Returns ``True`` when the escalation produced usable per-criterion outcomes
    (recorded on ``ctx.result.acceptance_outcomes``); ``False`` when there is no
    binding (single-model run) or the escalation degraded / returned nothing
    parseable — the caller then runs the existing main-model self-check turn,
    the c13 degradation ladder. The escalation attempt (including a degraded
    one) is recorded on ``result.deepthink`` — visible, never silent.
    """
    if ctx.deepthink_run is None:
        return False
    digest = (
        "You are grading a completed repo work item against its acceptance "
        "criteria. You see ONLY this digest — no repo, no conversation.\n\n"
        f"Task instruction:\n{ctx.task.instruction}\n\n"
        + (f"Goal: {ctx.task.goal}\n\n" if ctx.task.goal else "")
        + f"Result summary:\n{ctx.result.summary or '(no summary recorded)'}\n\n"
        + _ACCEPTANCE_CHECK_PROMPT
        + "\n".join(f"- {criterion}" for criterion in criteria)
    )
    res = ctx.deepthink_run(digest, "", point="acceptance_selfcheck")
    call = getattr(res, "call", None)
    if call is not None:
        _record_deepthink(ctx.result, call)
    if call is None or getattr(call, "degraded", False):
        return False
    outcomes = _parse_acceptance_outcomes(str(getattr(res, "text", "") or ""), criteria)
    if not outcomes:
        return False
    ctx.result.acceptance_outcomes = outcomes
    return True


def _maybe_run_test_integrity_gate(
    ctx: _Work,
    complete: CompleteFn,
    outcome: str,
    aborted: Exception | None,
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Run the post-loop test-integrity gate: flag the mirror signature (#203).

    Deterministic and code-locked: on a non-aborted exit it runs the
    mirror-detection heuristic (:func:`colleague.testintegrity.detect_mirror`) on
    the work item's changed files REGARDLESS of model behaviour — the model cannot
    skip it — and records any findings on ``result.test_integrity_report`` plus a
    line on stderr. The mirror signature is a novel identifier (attribute access or
    string-literal dict key) co-introduced in BOTH a changed test file and a changed
    module-under-test yet found nowhere else in the repo — the mechanical signal that
    a test merely mirrors the implementation's own (possibly wrong) assumption (the
    #203 self-confirming false positive).

    Bounded re-examine turn (#203 t3): when findings remain after a CLEAN finish
    (``outcome == _EXIT_FINISHED``) and a fix-turn budget is left
    (``ctx.testintegrity_fix_retries``), ONE bounded model turn is injected per
    remaining retry asking the model to verify the flagged symbol against the REAL
    API shape and fix it if wrong, re-running the gate after each. Conservative by
    default (``testintegrity_fix_retries`` defaults to 0 — detect-and-record only).
    Effectively a no-op on ``mock`` (the replayed script has already finished, so the
    fix-turn does nothing) and the work item's terminal summary/status are saved and
    restored either way, so a fix-turn ``finish`` can never clobber the real result.

    Advisory + non-blocking: it NEVER blocks the git handoff and makes NO network
    call. A no-finding run is byte-identical — the report stays ``None`` and is
    omitted from the artifact (the h6 omit-when-None guarantee). A strict no-op when
    the loop aborted, the gate is disabled, or no files changed.

    Best-effort + fail-safe (mirrors the lint-gate / neighbour-clone / hook
    fail-safes): the body is wrapped in ``suppress`` so detection can NEVER abort
    ``run()`` (which calls this after its main try/except, before the changed_files
    snapshot). The diverse-model reviewer is layered on in #203 task t4.
    """
    if aborted is not None or not ctx.testintegrity_enabled:
        return
    with suppress(Exception):
        changed = _gate_changed_set(ctx)
        if not changed:
            return
        report = _testintegrity.detect_mirror(ctx.task.repo_path, changed)
        if not report.findings:
            return
        ctx.result.test_integrity_report = report
        _surface_test_integrity(report)
        # Bounded re-examine turn(s) — only after a clean finish with budget left.
        retries = ctx.testintegrity_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.findings and retries > 0:
            _run_test_integrity_fix_turn(ctx, complete, report.findings, work_loop=work_loop)
            retries -= 1
            report = _testintegrity.detect_mirror(ctx.task.repo_path, _gate_changed_set(ctx))
            ctx.result.test_integrity_report = report if report.findings else None
        # Diverse-model reviewer — the robust guard: a same-model re-examine turn can
        # re-confirm its own mirror, so spawn a DIFFERENT model to re-derive the real
        # API shape independently. Only when findings remain and a reviewer is wired.
        if ctx.result.test_integrity_report is not None and report.findings:
            _maybe_spawn_test_integrity_reviewer(ctx, report.findings)


def _run_test_integrity_fix_turn(
    ctx: _Work,
    complete: CompleteFn,
    findings: "list[_testintegrity.MirrorFinding]",
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Inject ONE bounded model turn to re-examine a flagged symbol, preserving state.

    Re-enters :func:`_work_loop` with a small extra step budget after appending the
    re-examine instruction. The main work's terminal fields (summary / status / the
    two outcome flags) are saved and restored so a re-examine ``finish`` cannot
    clobber the work item's real result — the exact lint-fix-turn precedent. Any
    failure is suppressed (the gate is best-effort and must never abort the work item).
    """
    saved = (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    )
    detail = "\n".join(
        f"- {f.symbol} ({f.kind}) in {f.test_file} & {f.impl_file}" for f in findings[:50]
    )
    ctx.messages.append({"role": "user", "content": _TESTINTEGRITY_FIX_PROMPT + detail})
    budget = ctx.result.stats.model_turns + _TESTINTEGRITY_FIX_STEPS
    with suppress(Exception):
        work_loop(ctx, complete, budget)
    (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    ) = saved


def _maybe_run_affected_tests_gate(
    ctx: _Work,
    complete: CompleteFn,
    outcome: str,
    aborted: Exception | None,
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Run the pre-finish affected-tests gate (#213): run the tests that (transitively)
    import the changed module(s), so a scoped edit can't hide a regression in another
    file the model never ran.

    Advisory + non-blocking: selects the test files whose bounded-depth transitive
    import closure reaches a changed module (or uses the explicit ``--test`` override),
    runs pytest on them, and records an
    :class:`~colleague.affectedtests.AffectedTestsReport` on
    ``result.affected_tests_report``. On a FAILED status after a clean finish with a
    fix-turn budget left (``ctx.affectedtests_fix_retries``), ONE bounded model fix-turn
    is injected per remaining retry, re-running the gate after each. The handoff ALWAYS
    proceeds (never blocks). A strict no-op when the loop aborted, the gate is disabled,
    no files changed, nothing is affected, or pytest is unavailable (the report stays
    None / is omitted, keeping the result byte-identical).

    Best-effort + fail-safe (mirrors the lint / test-integrity gates): the body is
    wrapped in ``suppress`` so a hung/erroring pytest can NEVER abort ``run()``.
    """
    if aborted is not None or not ctx.affectedtests_enabled:
        return
    with suppress(Exception):
        override = shlex.split(ctx.affectedtests_override) if ctx.affectedtests_override else None
        changed = _gate_changed_set(ctx)
        if not changed and override is None:
            return
        report = _affectedtests.run_affected_tests(
            ctx.task.repo_path,
            changed,
            depth=ctx.affectedtests_depth,
            max_files=ctx.affectedtests_max_files,
            pytest_args=override,
        )
        if report is None:
            return
        ctx.result.affected_tests_report = report
        _surface_affected_tests(report)
        retries = ctx.affectedtests_fix_retries if outcome == _EXIT_FINISHED else 0
        while report.status == "failed" and retries > 0:
            _run_affected_tests_fix_turn(ctx, complete, report, work_loop=work_loop)
            retries -= 1
            next_report = _affectedtests.run_affected_tests(
                ctx.task.repo_path,
                _gate_changed_set(ctx),
                depth=ctx.affectedtests_depth,
                max_files=ctx.affectedtests_max_files,
                pytest_args=override,
            )
            if next_report is None:
                break
            report = next_report
            ctx.result.affected_tests_report = report
            _surface_affected_tests(report)


def _run_affected_tests_fix_turn(
    ctx: _Work,
    complete: CompleteFn,
    report: "_affectedtests.AffectedTestsReport",
    *,
    work_loop: "Callable[..., str]",
) -> None:
    """Inject ONE bounded model turn to fix a failing affected test, preserving state.

    Mirrors the lint / test-integrity fix-turn: saves & restores the work item's
    terminal fields so a fix-turn ``finish`` cannot clobber the real result; any failure
    is suppressed (the gate is best-effort and must never abort the work item).
    """
    saved = (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    )
    ctx.messages.append(
        {
            "role": "user",
            "content": _AFFECTEDTESTS_FIX_PROMPT + "\n".join(report.selected[:50]),
        }
    )
    budget = ctx.result.stats.model_turns + _AFFECTEDTESTS_FIX_STEPS
    with suppress(Exception):
        work_loop(ctx, complete, budget)
    (
        ctx.result.summary,
        ctx.result.status,
        ctx.result.not_finished,
        ctx.result.stopped_without_finish,
    ) = saved


def _surface_affected_tests(report: "_affectedtests.AffectedTestsReport") -> None:
    """Write the affected-tests summary to stderr (advisory; never raises)."""
    with suppress(OSError):
        sys.stderr.write(report.summary_line() + "\n")


def _surface_test_integrity(report: "_testintegrity.TestIntegrityReport") -> None:
    """Write the mirror-signature findings to stderr (advisory; never raises)."""
    detail = "; ".join(
        f"{f.symbol} ({f.kind}) co-introduced in {f.test_file} & {f.impl_file}"
        for f in report.findings
    )
    with suppress(OSError):
        sys.stderr.write(
            "test-integrity: possible self-confirming test(s) — mirror signature "
            f"flagged: {detail}\n"
        )


def _maybe_spawn_test_integrity_reviewer(
    ctx: _Work, findings: "list[_testintegrity.MirrorFinding]"
) -> None:
    """Spawn a DIFFERENT-model reviewer subagent to vet a flagged mirror (#203 t4).

    The same-model re-examine turn can re-confirm its own mirror, so the robust guard
    is an independent second mind: when ``ctx.testintegrity_reviewer_model`` names a
    model AND a single-spawn callback is wired into the executor, spawn ONE reviewer
    subagent on that model (read-only) to re-derive the real API shape and report
    disagreement. Its :class:`~colleague.contract.SubResult` is appended to the
    executor's accumulator so the standard snapshot folds it into
    ``result.sub_results``. Reuses the existing subagent launcher with NO new
    worktree/merge code, and is bounded by the existing fan-out cap.

    Reviewer-write reconciliation (Qodo PR #211): the single-subagent launcher
    (``make_spawn`` → ``run_subagent``) runs the child **in-place** in the work
    item's tree (only the *batch* path uses isolated worktrees), and the handoff
    stages the whole tree (``git add -u``). So although the reviewer is prompted
    read-only, any file it nonetheless writes WOULD be committed — and would be
    *invisible* if left out of ``executor.changed``. We therefore merge the
    reviewer's ``changed_files`` into ``executor.changed`` (so they are tracked in
    ``TaskResult.changed_files`` and the artifact agrees with the commit) and emit a
    stderr warning, rather than letting a read-only-contract violation ship silently.

    Degrades to record-only — a strict no-op — when no reviewer model is configured,
    no spawn callback is wired, or the per-work-item fan-out cap is already reached.
    Best-effort: any launcher/engine error is suppressed so the gate never aborts.
    """
    reviewer_model = (ctx.testintegrity_reviewer_model or "").strip()
    spawn = getattr(ctx.executor, "_spawn", None)
    if not reviewer_model or spawn is None:
        return
    if len(ctx.executor.sub_results) >= MAX_SUBAGENT_FANOUT:
        return
    detail = "\n".join(
        f"- {f.symbol} ({f.kind}) in {f.test_file} & {f.impl_file}" for f in findings[:50]
    )
    with suppress(Exception):
        sub = spawn(_TESTINTEGRITY_REVIEWER_PROMPT + detail, None, reviewer_model)
        if sub is None:
            return
        ctx.executor.sub_results.append(sub)
        # The reviewer should not write (read-only prompt), but the in-place spawn +
        # `git add -u` handoff mean any writes WOULD be committed; track them so they
        # are never silent/untracked, and warn on the contract violation.
        if sub.changed_files:
            ctx.executor.changed.update(sub.changed_files)
            with suppress(OSError):
                sys.stderr.write(
                    "test-integrity: reviewer subagent modified "
                    f"{len(sub.changed_files)} file(s) despite the read-only review "
                    "contract — tracked in changed_files (not silent): "
                    f"{', '.join(sorted(sub.changed_files)[:20])}\n"
                )


def _affectedtests_controls(controls: "ContextControls") -> dict[str, Any]:
    """The affected-tests gate kwargs for ``_Work``, defaulting each unset
    (``None``) ContextControls field. Kept out of ``run()`` so the per-field
    ``or``-defaults don't inflate its cognitive complexity (all-engines rule)."""
    return {
        "affectedtests_enabled": bool(controls.affectedtests),
        "affectedtests_fix_retries": controls.affectedtests_fix_retries or 0,
        "affectedtests_depth": controls.affectedtests_depth or 3,
        "affectedtests_max_files": controls.affectedtests_max_files or 20,
        "affectedtests_override": controls.affectedtests_override,
    }

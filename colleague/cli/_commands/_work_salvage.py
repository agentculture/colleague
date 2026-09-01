"""Isolation, interrupt salvage and run-outcome helpers for ``colleague work``.

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16). ``_arm_interrupt_commit`` deliberately
does NOT live here: :mod:`colleague.salvage`'s own docstring documents it as
``colleague.cli._commands.work._arm_interrupt_commit``, so it stays where the
documentation says it is (and where the tests import it from).
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from colleague import salvage, tasktext, worktrees
from colleague.artifact import artifact_dir, failed_result, write
from colleague.cli._commands._work_chain import ChainEpisodeOptions, _arm_chain_dispatch
from colleague.cli._commands._work_support import _guard_clean_tree, _repo_relative
from colleague.cli._output import emit_diagnostic
from colleague.config import EngineConfig
from colleague.contract import ERROR, OK, IncompletionRecord, Task, TaskResult
from colleague.feedback import set_last_work
from colleague.handoff import branch_name, head_sha, untracked_snapshot
from colleague.roles import is_read_only
from colleague.telemetry import Telemetry


def _setup_isolation(
    repo: Path, task: Task, isolate: bool, base_ref: str | None = None
) -> tuple[Path, str | None, str | None, Task]:
    """Worktree-isolate a write item (#196/#201); returns ``(work_repo, base_sha,
    worktree_path, task)``.

    An isolated run drives the loop in a throwaway git worktree at the operator's
    HEAD on the ``colleague/<id>`` branch — operator tree/branch untouchable, a
    model self-commit lands on that branch, concurrent runs can't cross-pollute.
    Only isolates when there is a HEAD to isolate from (``head_sha`` not None) and
    the worktree creates cleanly; otherwise falls back to the in-place path so a
    work item that ran before always still runs (h7). Extracted from
    :func:`execute_work` to keep its cognitive complexity under the S3776 threshold
    (PR #207 review).

    ``base_ref`` (indefinite-run c6, the t4 interface): a chained episode passes
    the prior episode's branch so its worktree carries the prior TREE, not just
    the continuation seed. Uses the outcome form
    (:func:`~colleague.worktrees.isolation_worktree_add_outcome`) so a
    missing/reaped base ref's HEAD degrade is *recorded* — the warning is
    surfaced as a diagnostic (h6), never a crash. With a base ref actually
    used, ``base_sha`` is re-read from the worktree's own HEAD (the episode's
    true base) so the #196 self-commit detection and ``changed_files`` compare
    against the prior tip, not the operator's HEAD; the ``base_ref=None`` path
    is byte-identical to before."""
    if not isolate:
        return repo, None, None, task
    base_sha = head_sha(repo)
    if base_sha is None:
        return repo, None, None, task
    try:
        outcome = worktrees.isolation_worktree_add_outcome(
            str(repo), task.id, branch_name(task.id, task.instruction), base_ref=base_ref
        )
    except Exception as exc:  # noqa: BLE001 - isolation must never break a work item
        emit_diagnostic(f"isolation worktree unavailable ({exc}); running in place")
        return repo, None, None, task
    worktree_path = outcome.path
    if outcome.warning:
        emit_diagnostic(f"isolation: {outcome.warning}")
    work_repo = Path(worktree_path)
    if outcome.base_ref is not None:
        # A chained episode's honest base is the prior tip the worktree was
        # actually created at — read it from the worktree itself.
        base_sha = head_sha(work_repo) or base_sha
    # #310: the loop runs in the worktree (repo_path=work_repo) but the flight
    # plane must live in the OPERATOR repo (flight_repo_path=repo) so
    # `colleague talk` / `colleague flight` reach it and it survives the
    # worktree removal on finish. The in-place path leaves flight_repo_path
    # None (arm at repo_path), byte-identical.
    return (
        work_repo,
        base_sha,
        worktree_path,
        replace(task, repo_path=str(work_repo), flight_repo_path=str(repo)),
    )


def finalize_interrupted(
    result: TaskResult,
    *,
    reason: str,
    command_name: str | None,
    mode: str | None,
    continued_from: str | None,
) -> TaskResult:
    """Stamp the interrupt onto a live partial so its artifact is an honest seed (#410).

    ``status`` becomes ``error`` with the signal named; an incompletion record
    points the operator at ``work --continue``; ``command``/``mode``/
    ``continued_from`` mirror what the normal write path records. Idempotent —
    a second signal stamps the same facts.
    """
    steps = len(result.steps)
    result.status = ERROR
    result.error = f"interrupted by {reason} after {steps} step(s)"
    if not result.summary:
        result.summary = f"interrupted by {reason} after {steps} step(s) (partial)"
    result.incompletion = IncompletionRecord(
        reason="interrupted",
        evidence=result.error,
        recommendation=f"resume with: colleague work --continue {result.task_id}",
    )
    result.command = command_name
    result.mode = mode
    result.continued_from = continued_from
    return result


def _make_salvage_writer(
    task: Task,
    repo: Path,
    *,
    command_name: str | None,
    mode: str | None,
    continued_from: str | None,
    continuation_task_text: str | None = None,
) -> Callable[[str], None]:
    """Build the SIGTERM/SIGINT salvage writer for *task* (#410).

    Reads the loop's live partial (:func:`colleague.salvage.peek`), stamps it via
    :func:`finalize_interrupted`, and writes the artifact + ``last_work`` pointer
    under the OPERATOR repo — the same location the normal path writes, so
    ``work --continue`` finds it. No live partial (the loop never started) →
    a ``failed_result`` is written instead, so the artifact is UNCONDITIONAL.
    """

    def _write(reason: str) -> None:
        partial = salvage.peek(task.id)
        if partial is None:
            partial = failed_result(
                task.id,
                f"interrupted by {reason} before the loop started",
                request=task.instruction,
            )
        if not partial.stats.request:
            # The loop stamps the request at its own finalize — which this
            # interrupt never reaches — so carry it here: the artifact keeps the
            # normal <id>.<slug>.json name and stays discoverable by request.
            partial.stats.request = task.instruction
        finalize_interrupted(
            partial,
            reason=reason,
            command_name=command_name,
            mode=mode,
            continued_from=continued_from,
        )
        # A continued run's live partial carries the loop's early-stamped
        # task_text — the synthesized continuation SEED, not the brief; the
        # normal path overrides it at _stamp_lineage, which this interrupt
        # never reaches. Same override here (c22/h15: a seed is never a brief).
        tasktext.apply_continuation_task_text(
            partial,
            continued_from=continued_from,
            continuation_task_text=continuation_task_text,
        )
        write(partial, artifact_dir(repo))
        with suppress(Exception):
            set_last_work(repo, partial.task_id)
        salvage.unregister(task.id)

    return _write


def _baseline_untracked_for(work_repo: Path, repo: Path, tui_events: str | None) -> list[str]:
    """Untracked-file baseline for the handoff, registering a ``--tui-events`` stream.

    Snapshots untracked files before the loop so the handoff stages only what the work
    item produces, never pre-existing operator WIP (#39); a live ``--tui-events`` path
    written into the repo is harness telemetry, registered as baseline so the handoff
    never sweeps it into the work branch (#74 A3). Extracted from :func:`execute_work`
    to keep its cognitive complexity under the S3776 threshold (review of #228).
    """
    baseline = untracked_snapshot(work_repo)
    if tui_events:
        ev_rel = _repo_relative(repo, tui_events)
        if ev_rel is not None:
            baseline.append(ev_rel)
    return baseline


def _preserve_isolated_wip(worktree_path: str | None, status: str) -> bool:
    """Commit a non-OK isolated run's WIP to its ``colleague/<id>`` branch (#222).

    The git handoff only runs on an ``OK`` result, so a cooperative ``flight stop`` or
    a budget/incomplete exit would otherwise lose the model's WIP when the worktree is
    torn down. This commits it first so a stopped run stays inspectable and mergeable.
    A no-op when not isolated (``worktree_path is None`` — the in-place session path)
    and best-effort (empty diff = no-op; a commit failure never masks the result).
    Returns ``True`` when a WIP commit was actually made — the engine-failure path
    (#268) uses that to point the operator at the surviving branch in the error hint.
    Extracted from :func:`execute_work` to keep its cognitive complexity under the
    S3776 threshold (review of #228, SonarCloud).
    """
    if worktree_path is None:
        return False
    with suppress(Exception):
        return worktrees.commit_iso_worktree_wip(worktree_path, reason=f"stop ({status})")
    return False


def _preserve_non_ok_wip(
    worktree_path: str | None, result: TaskResult, task: Task, *, chained: bool
) -> None:
    """The non-OK exit's #222 WIP sweep + the chained episode's branch record.

    Commits the WIP via :func:`_preserve_isolated_wip`; when the run is a
    CHAINED episode that actually made a WIP commit, records the iso branch
    (the same ``branch_name`` recipe ``_isolate_for_write`` minted it with) on
    the result BEFORE the artifact write — so a chain resumed via
    ``--continue`` can resolve an INHERITED deferred episode's ungated WIP
    branch from the episode's own artifact (Qodo, PR #345; see
    :func:`_resolve_deferred_branch`). An unchained non-OK run keeps today's
    artifact shape (``branch`` null); the #268 engine-failure hint names its
    surviving branch in the error text instead. Extracted from
    :func:`execute_work` to keep its control flow flat (S3776).
    """
    if _preserve_isolated_wip(worktree_path, result.status) and chained:
        result.branch = branch_name(task.id, task.instruction)


def _finalize_run_outcome(
    *,
    result: TaskResult,
    read_only_role: bool,
    work_repo: Path,
    task: Task,
    baseline_untracked: list[str],
    open_pr: bool,
    base: str,
    telemetry: Telemetry,
    base_sha: str | None,
    worktree_path: str | None,
    chain: "ChainEpisodeOptions | None",
) -> None:
    """Land the run's outcome: handoff on OK, else preserve non-OK isolated WIP.

    A read-only role (explorer/reviewer/planner/validator) never triggers the
    handoff sweep — there is nothing to sweep, and a read-only handoff would
    silently revert the operator's own uncommitted WIP (Qodo, PR #245). A
    non-OK isolated exit instead preserves the model's WIP on
    ``colleague/<id>`` (#222) via :func:`_preserve_non_ok_wip`. Extracted
    from :func:`execute_work` to keep its cognitive complexity under the
    S3776 ceiling (the :func:`_moded_config` precedent).
    """
    # `_handoff_result` stays in `work.py` (colleague/contract.py documents it
    # there as the owner of the handoff-written TaskResult fields), so it is
    # imported lazily here — a plain module-level import would be circular.
    from colleague.cli._commands.work import _handoff_result

    if result.status == OK and not read_only_role:
        _handoff_result(
            repo=work_repo,
            task=task,
            result=result,
            baseline_untracked=baseline_untracked,
            open_pr=open_pr,
            base=base,
            telemetry=telemetry,
            base_sha=base_sha,
        )
    elif result.status != OK:
        # Cooperative stop / non-OK isolated exit (#222): the handoff only runs
        # on OK, so preserve the model's WIP on colleague/<id> before teardown.
        # A no-op when not isolated (worktree_path is None). A chained
        # episode additionally records its WIP branch on the result
        # (Qodo, PR #345 — see _preserve_non_ok_wip).
        _preserve_non_ok_wip(worktree_path, result, task, chained=chain is not None)


@dataclass(frozen=True)
class _RunSetup:
    """What :func:`_prepare_run` resolved for ONE dispatch of :func:`execute_work`.

    The pre-loop half of the work path, bundled so ``execute_work`` reads as a
    sequence of named steps rather than one 370-line hub (plan t16). Nothing
    here is new behaviour: the fields are exactly the locals the inlined
    version carried into its telemetry span.
    """

    #: The repo the loop drives — the isolation worktree, else the operator repo.
    work_repo: Path
    #: The sha the isolated worktree was created at (``None`` in place).
    base_sha: str | None
    #: The isolation worktree's path (``None`` in place) — the #222 WIP sweeps
    #: and the ``finally`` teardown key on it.
    worktree_path: str | None
    #: The task, re-pointed at the worktree when isolated (#310 keeps the
    #: flight plane at the operator repo).
    task: Task
    #: A provably-non-writing role: skips the dirty-tree guard and the handoff.
    read_only_role: bool
    #: Restores the operator's prior signal disposition (#222).
    restore_signals: Callable[[], None]


def _prepare_run(
    *,
    repo: Path,
    task: Task,
    config: EngineConfig,
    allow_dirty: bool,
    isolate: bool,
    chain: "ChainEpisodeOptions | None",
    command_name: str | None,
    mode: str | None,
    continued_from: str | None,
    continuation_task_text: str | None = None,
) -> _RunSetup:
    """Everything :func:`execute_work` settles BEFORE the telemetry span opens.

    In order: the read-only-role resolution + dirty-tree guard, the chain
    dispatch marker, worktree isolation, the memory root, and the interrupt
    handlers. Extracted (plan t16) with the call order preserved verbatim —
    the guard must precede isolation (a refused run creates no worktree) and
    the signal arming must follow it (the handler commits that worktree's WIP).
    """
    # A read-only role (explorer/reviewer/planner/validator) provably writes
    # nothing, so it (a) bypasses the dirty-tree guard — there is no handoff sweep
    # to protect against — and (b) skips the write handoff entirely below. Without
    # the handoff skip the handoff's `git add -u` would sweep the operator's
    # uncommitted WIP onto colleague/<id> and then restore HEAD over it, silently
    # reverting in-progress work (Qodo, PR #245). Runtime-owned so every read-only
    # caller (session explore/review, ask-colleague) inherits it identically.
    read_only_role = is_read_only(getattr(config, "role", None))
    _guard_clean_tree(repo, allow_dirty=allow_dirty or read_only_role)
    episode_base_ref = _arm_chain_dispatch(config, chain)
    work_repo, base_sha, worktree_path, task = _setup_isolation(
        repo, task, isolate, base_ref=episode_base_ref
    )
    # Memory targets the OPERATOR repo (spec R1 / plan t2): an isolated run's
    # worktree is reaped after handoff, so a lesson written there would be lost.
    config.memory_root = str(repo)
    # Interruption safety (#222): on the isolated path, a SIGTERM (a caller's
    # `timeout`) / Ctrl-C now commits the model's WIP to colleague/<id> before the
    # process exits, instead of stranding it as uncommitted files in an orphan
    # worktree. A None worktree (the in-place session path) arms nothing. Restored
    # in the finally.
    # `_arm_interrupt_commit` stays in `work.py` (colleague/salvage.py's
    # docstring names it there); imported lazily — a module-level import
    # would be circular.
    from colleague.cli._commands.work import _arm_interrupt_commit

    restore_signals: Callable[[], None] = _arm_interrupt_commit(
        worktree_path,
        salvage_write=_make_salvage_writer(
            task,
            repo,
            command_name=command_name,
            mode=mode,
            continued_from=continued_from,
            continuation_task_text=continuation_task_text,
        ),
    )
    return _RunSetup(
        work_repo=work_repo,
        base_sha=base_sha,
        worktree_path=worktree_path,
        task=task,
        read_only_role=read_only_role,
        restore_signals=restore_signals,
    )

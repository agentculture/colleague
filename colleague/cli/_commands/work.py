"""``colleague work`` — assign a repo task to a coder backend.

The headline verb: select an engine (a discovered wheel), run the bounded
agentic loop against a repo, write the result artifact, and hand the change off
as a branch + PR. The *same* invocation works for every backend — only
``--engine`` changes (honesty conditions h11/h12).

A failed work item still writes a result artifact (``status=error``) before exiting
non-zero, so a crash never leaves an empty run report (h5).

``--command NAME`` (and optional positional args) expands a saved command
template into the Task via :func:`colleague.commands.expand_command` and
records the originating command name on the result (``TaskResult.command``).
Exactly one of a positional instruction or ``--command`` must be supplied.

:func:`execute_work` is the shared helper that performs the work item orchestration
(load engine → run loop → handoff → write artifact) and returns the
``(TaskResult, artifact_path)`` pair.  Both ``cmd_work`` and the ``session``
palette delegate to it so the work path is never duplicated (honesty h11).
"""

from __future__ import annotations

import argparse
import os
import signal
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Callable, Collection

from colleague import flight, registry, worktrees
from colleague.artifact import artifact_dir, failed_result, write
from colleague.cli._banner import emit_banner
from colleague.cli._commands._tui_sink import CockpitProgressSink, build_progress
from colleague.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_diagnostic, emit_result
from colleague.commands import CommandError, expand_command
from colleague.config import EngineConfig, apply_mode_profile, resolve_engine
from colleague.contract import INCOMPLETE, OK, Task, TaskResult
from colleague.feedback import set_last_work
from colleague.handoff import (
    HandoffError,
    branch_name,
    handoff,
    head_sha,
    untracked_snapshot,
    working_tree_dirty,
)
from colleague.roles import is_read_only
from colleague.subagents import make_batch_spawn, make_spawn, new_agent_budget
from colleague.telemetry import Telemetry, load_telemetry


def _step_progress(step_index: int, tool: str, target: str, ok: bool) -> None:
    """Per-step progress line to stderr during a work item (#38).

    stdout carries only the result stream (the ``--json`` ``TaskResult``), so a
    progress line here never pollutes the parseable output — it is emitted in all
    modes. Wired onto :class:`~colleague.config.EngineConfig` by
    :func:`execute_work`, so both ``work`` and ``session`` (and every backend)
    report progress identically.

    A phase notice (colleague#206) arrives with an EMPTY ``tool`` name: render its
    detail (carried in ``target``) as a standalone line — never shaped like a
    ``step N:`` line — so a long model turn, above all the final synthesis turn, is
    visibly "working, not stalled" on a slow backend instead of going silent.
    """
    if not tool:
        if target:
            emit_diagnostic(target)
        return
    detail = f" {target}" if target else ""
    emit_diagnostic(f"step {step_index}: {tool}{detail} [{'ok' if ok else 'err'}]")


def _repo_relative(repo: Path, path_str: str) -> str | None:
    """Repo-relative POSIX path for *path_str* if it lives inside *repo*, else None.

    Used to recognise a `--tui-events` stream written into the repo so the handoff
    can treat it as baseline (telemetry) rather than work-produced output.
    """
    try:
        rel = Path(path_str).expanduser().resolve().relative_to(repo.resolve())
    except (ValueError, OSError):
        return None
    return rel.as_posix()


def _render(result: TaskResult, engine: str, artifact_path: Path) -> str:
    lines = [
        f"task: {result.task_id}",
        f"engine: {engine}",
        f"status: {result.status}",
        f"summary: {result.summary}",
        "changed files: " + (", ".join(result.changed_files) or "(none)"),
    ]
    if result.branch:
        lines.append(f"branch: {result.branch}")
    lines.append(f"PR: {result.pr_url or '(none)'}")
    lines.append(f"artifact: {artifact_path}")
    # The ROI-loop nudge: every completed work item is gradable (the artifact survives
    # even on a failed work item — a 1/5 is exactly the ROI signal), so mirror the
    # ask-colleague wrapper's `grade:` hint here pointing at the native feedback verb.
    # `_render` is the text path only; the `--json` branch bypasses it, so the
    # hint never pollutes machine output.
    if result.task_id:
        lines.append(f"grade: colleague feedback record {result.task_id} --rating N")
    return "\n".join(lines)


def _handoff_result(
    *,
    repo: Path,
    task: Task,
    result: TaskResult,
    baseline_untracked: list[str],
    open_pr: bool,
    base: str,
    telemetry: Telemetry,
    base_sha: str | None = None,
) -> None:
    """Branch/commit (+push/PR) a successful work item; fold the outcome onto *result*.

    A :class:`~colleague.handoff.HandoffError` is non-fatal — the work item still
    succeeded, so it is surfaced as a diagnostic and the result keeps its local
    state. Extracted from :func:`execute_work` to keep that function's control
    flow flat.
    """
    with telemetry.handoff_span() as handoff_span:
        try:
            outcome = handoff(
                repo,
                task.id,
                instruction=task.instruction,
                changed_files=result.changed_files,
                baseline_untracked=baseline_untracked,
                open_pr=open_pr,
                base_branch=base,
                base_sha=base_sha,
            )
        except HandoffError as exc:
            emit_diagnostic(f"handoff skipped: {exc}")
            return
        result.branch = outcome.branch
        result.pr_url = outcome.pr_url
        if not result.changed_files:
            result.changed_files = outcome.changed_files
        handoff_span.set(
            branch=outcome.branch,
            committed=outcome.committed,
            pushed=outcome.pushed,
            pr_url=outcome.pr_url,
        )
        if outcome.note:
            emit_diagnostic(f"handoff: {outcome.note}")


def _guard_clean_tree(repo: Path, *, allow_dirty: bool) -> None:
    """Refuse to run a work item against a dirty tree unless opted in (#149).

    A work item ends in the handoff's ``git add -u``, which would sweep the
    operator's uncommitted *tracked* edits onto the work branch and then restore
    HEAD over them — silently swallowing in-progress work. Called from the shared
    path so ``work``, ``drive``, and ``session`` are all protected (and every
    backend, since this is upstream of the loop). Untracked WIP is already
    protected by the handoff's baseline snapshot, so this checks tracked changes
    only (see :func:`~colleague.handoff.working_tree_dirty`).
    """
    if allow_dirty or not working_tree_dirty(repo):
        return
    raise CliError(
        EXIT_USER_ERROR,
        "working tree has uncommitted changes — refusing to run against a dirty repo",
        "commit or stash your changes first, or pass --allow-dirty to "
        "commit them onto the work branch",
    )


def _apply_lint_optout(args: argparse.Namespace, config: EngineConfig) -> None:
    """Apply the ``--no-lint`` opt-out — the highest-precedence lint switch (#200).

    Applied AFTER ``EngineConfig.resolve`` (which handled env > config.json >
    default-on for ``config.lint``); the flag wins last. Extracted to keep
    ``cmd_work`` under the S3776 cognitive-complexity threshold.
    """
    if getattr(args, "no_lint", False):
        config.lint = False


def _apply_affected_tests_optout(args: argparse.Namespace, config: EngineConfig) -> None:
    """Apply the ``--no-affected-tests`` and ``--test`` opt-outs (#213).

    Applied AFTER ``EngineConfig.resolve`` (which handled env > config.json >
    default-on for ``config.affected_tests``); the flags win last. Extracted to
    keep ``cmd_work`` under the S3776 cognitive-complexity threshold.
    """
    if getattr(args, "no_affected_tests", False):
        config.affected_tests = False
    if getattr(args, "test", None):
        config.affected_tests_override = args.test


def _surface_lint_residual(result: TaskResult) -> None:
    """Surface lint violations the gate could not auto-fix on stderr (#200).

    A diagnostic, never the stdout result stream; the full report is in the
    artifact (``result.lint_report``). Extracted to keep ``cmd_work`` under the
    S3776 cognitive-complexity threshold.
    """
    if result.lint_report and result.lint_report.residual:
        n = len(result.lint_report.residual)
        emit_diagnostic(
            f"lint: {n} issue(s) not auto-fixed:\n" + "\n".join(result.lint_report.residual)
        )


def _setup_isolation(
    repo: Path, task: Task, isolate: bool
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
    (PR #207 review)."""
    if not isolate:
        return repo, None, None, task
    base_sha = head_sha(repo)
    if base_sha is None:
        return repo, None, None, task
    try:
        worktree_path = worktrees.isolation_worktree_add(
            str(repo), task.id, branch_name(task.id, task.instruction)
        )
    except Exception as exc:  # noqa: BLE001 - isolation must never break a work item
        emit_diagnostic(f"isolation worktree unavailable ({exc}); running in place")
        return repo, None, None, task
    work_repo = Path(worktree_path)
    return work_repo, base_sha, worktree_path, replace(task, repo_path=str(work_repo))


def _arm_interrupt_commit(worktree_path: str | None) -> Callable[[], None]:
    """Install SIGTERM+SIGINT handlers that commit the iso worktree's WIP before exit (#222).

    The isolated work path's success teardown lives in a ``finally`` that a SIGTERM
    (a caller's ``timeout``) bypasses entirely, stranding the model's WIP as
    uncommitted files in an orphan worktree. This arms a handler that, on
    SIGTERM/SIGINT, commits whatever the model wrote onto its ``colleague/<id>``
    branch (best-effort, empty diff = no-op), restores the prior disposition, and
    raises ``SystemExit(128 + signum)`` — which unwinds through the normal ``finally``
    teardown (the branch keeps the WIP commit) and exits the CLI **cleanly** with the
    conventional signal exit code (143 for SIGTERM, 130 for SIGINT) and **no
    traceback**. Raising ``SystemExit`` rather than ``KeyboardInterrupt`` matters: the
    CLI dispatcher catches only ``Exception``, so a bare ``KeyboardInterrupt`` would
    print a Python traceback on a caller's ``timeout`` (review of #228, Qodo).

    A ``None`` worktree (the in-place ``session`` path) installs nothing and returns a
    no-op restore, so only the isolated path is armed. The returned callable restores
    the previous handlers and MUST be invoked on every exit. A non-main-thread /
    unsupported platform degrades gracefully (handlers simply not installed) — never
    breaking a work item. Signals are stdlib: no new dependency, daemon, or thread.
    """
    if worktree_path is None:
        return lambda: None

    previous: dict[int, object] = {}

    def _handler(signum: int, _frame: object) -> None:
        with suppress(Exception):
            worktrees.commit_iso_worktree_wip(worktree_path, reason=signal.Signals(signum).name)
        # Restore prior handlers before exiting so a second signal can't re-enter this
        # handler mid-commit; SystemExit unwinds through the normal finally blocks
        # (cockpit close, telemetry flush, worktree remove) and exits without a traceback.
        for sig, prev in previous.items():
            with suppress(Exception):
                signal.signal(sig, prev)  # type: ignore[arg-type]
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[sig] = signal.signal(sig, _handler)
        except (ValueError, OSError):  # not the main thread / unsupported — skip
            pass

    def _restore() -> None:
        for sig, prev in previous.items():
            with suppress(Exception):
                signal.signal(sig, prev)  # type: ignore[arg-type]

    return _restore


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


def _preserve_isolated_wip(worktree_path: str | None, status: str) -> None:
    """Commit a non-OK isolated run's WIP to its ``colleague/<id>`` branch (#222).

    The git handoff only runs on an ``OK`` result, so a cooperative ``flight stop`` or
    a budget/incomplete exit would otherwise lose the model's WIP when the worktree is
    torn down. This commits it first so a stopped run stays inspectable and mergeable.
    A no-op when not isolated (``worktree_path is None`` — the in-place session path)
    and best-effort (empty diff = no-op; a commit failure never masks the result).
    Extracted from :func:`execute_work` to keep its cognitive complexity under the
    S3776 threshold (review of #228, SonarCloud).
    """
    if worktree_path is None:
        return
    with suppress(Exception):
        worktrees.commit_iso_worktree_wip(worktree_path, reason=f"stop ({status})")


def execute_work(
    *,
    repo: Path,
    engine_name: str,
    task: Task,
    open_pr: bool,
    base: str,
    config: EngineConfig,
    allow_dirty: bool = False,
    isolate: bool = False,
    command_name: str | None = None,
    tui: bool | None = None,
    tui_events: str | None = None,
    progress_sink: "CockpitProgressSink | None" = None,
    mode: str | None = None,
    explicit_knobs: "Collection[str]" = (),
) -> tuple[TaskResult, Path]:
    """Shared work orchestration: load engine → loop → handoff → write artifact.

    This helper is the single implementation of the work path.  Both
    :func:`cmd_work` and the ``session`` palette call it so the loop, hooks,
    and artifact logic are never duplicated (honesty condition h11).

    Parameters
    ----------
    repo:
        Absolute path to the target repository.
    engine_name:
        Name of the backend plugin to load (e.g. ``"mock"``).
    task:
        A fully constructed :class:`~colleague.contract.Task`.
    open_pr:
        When ``True`` attempt to push and open a PR; ``False`` commits locally only.
    base:
        Base branch for the PR (passed to :func:`~colleague.handoff.handoff`).
    config:
        Resolved :class:`~colleague.config.EngineConfig`.
    allow_dirty:
        When ``False`` (the default) the work path refuses to run against a
        repo with uncommitted tracked changes — the handoff would otherwise
        sweep them onto the work branch (#149). ``True`` opts in to that.
    command_name:
        Originating command-template name (``None`` for a plain instruction).
        Recorded on the result before *every* artifact write — including the
        failure path — so the run report never loses the origin (R5 / c12).
    tui:
        Live-cockpit activation (#74 A1): ``True`` forces it on, ``False`` off,
        ``None`` (default) is auto — on when stderr is an interactive TTY. When
        off, the plain ``step N:`` stderr sink is used unchanged.
    tui_events:
        Optional path (#74 A3): when set, one `WorkStep` JSONL line is appended
        per step as the work item runs, so an agent can follow / `tui replay` it.
    progress_sink:
        Optional caller-supplied cockpit sink (#74 A2): the interactive ``session``
        passes a sink bound to its own `CockpitState` + frame-writer so a work item
        renders into the session's one shared screen. Replaces the auto-constructed
        cockpit; ``None`` (the default) preserves the byte-identical `work` path.
    mode:
        Constraint-profile mode (t3 / spec R1 / #254). When set, the mode's
        profile (``colleague.profiles`` + operator overlays) fills the
        constraint knobs the operator left untouched, via
        :func:`colleague.config.apply_mode_profile` — the ONE code path shared
        by the ``work --mode`` flag and the session's mode selection. ``None``
        (the default) is a strict no-op (byte-identical config).
    explicit_knobs:
        EngineConfig field names the caller set from explicit CLI flags (e.g.
        ``{"max_steps"}`` when ``--max-steps`` was given) — those knobs are
        never overwritten by the mode profile (precedence h1).

    Returns
    -------
    tuple[TaskResult, Path]
        The task result and the path of the written artifact JSON.

    Raises
    ------
    :class:`~colleague.cli._errors.CliError`
        On unknown engine or engine-level failure (artifact is still written
        before the exception is raised — honesty h5).
    """
    # Mode-profile layer (t3 / R1 / #254): fill profile defaults for knobs the
    # operator left untouched, BEFORE anything reads the config. One code path
    # for every entry door (work CLI --mode, session mode selection); a strict
    # no-op when no mode is set (h1).
    if mode:
        config = apply_mode_profile(config, mode, explicit=explicit_knobs, repo_path=repo)

    try:
        engine = registry.load(engine_name)
    except registry.UnknownEngine as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "list engines with: colleague backends list"
        ) from exc

    # A read-only role (explorer/reviewer/planner/validator) provably writes
    # nothing, so it (a) bypasses the dirty-tree guard — there is no handoff sweep
    # to protect against — and (b) skips the write handoff entirely below. Without
    # the handoff skip the handoff's `git add -u` would sweep the operator's
    # uncommitted WIP onto colleague/<id> and then restore HEAD over it, silently
    # reverting in-progress work (Qodo, PR #245). Runtime-owned so every read-only
    # caller (session explore/review, ask-colleague) inherits it identically.
    read_only_role = is_read_only(getattr(config, "role", None))
    _guard_clean_tree(repo, allow_dirty=allow_dirty or read_only_role)
    work_repo, base_sha, worktree_path, task = _setup_isolation(repo, task, isolate)
    # Interruption safety (#222): on the isolated path, a SIGTERM (a caller's
    # `timeout`) / Ctrl-C now commits the model's WIP to colleague/<id> before the
    # process exits, instead of stranding it as uncommitted files in an orphan
    # worktree. A None worktree (the in-place session path) arms nothing. Restored
    # in the finally.
    _restore_signals: Callable[[], None] = _arm_interrupt_commit(worktree_path)

    # Telemetry: the root span wraps engine.work() + handoff() + the artifact write, so
    # the loop's tool spans nest under it. A no-op unless telemetry is enabled.
    # The same shared path serves `work` and `session`, so both are instrumented.
    telemetry = load_telemetry()
    try:
        with telemetry.work_span(
            task_id=task.id,
            engine=engine_name,
            model=config.model,
            max_steps=config.max_steps,
        ) as work_span:
            trace_id = telemetry.trace_id_hex()
            if trace_id:
                emit_diagnostic(f"trace: {trace_id}")

            # Snapshot untracked files BEFORE the work item so the handoff stages only
            # the files the work item itself produces — never pre-existing operator
            # work-in-progress (#39), with a live --tui-events stream registered as
            # baseline (#74 A3). Extracted to a helper (review of #228, S3776).
            baseline_untracked = _baseline_untracked_for(work_repo, repo, tui_events)

            # Per-step progress (#38) — wired here so both `work` and `session`,
            # and every backend (which forwards `config.progress`), report
            # identically. By default the plain `step N:` stderr sink; with the
            # cockpit active (#74 A1, auto-on a TTY) and/or `--tui-events` (A3) the
            # sinks are composed with per-sink failure isolation. When neither TUI
            # surface is requested, `_step_progress` is used verbatim — the default
            # path stays byte-identical.
            config.progress, cockpit_sink = build_progress(
                default_sink=_step_progress,
                task_id=task.id,
                engine=engine_name,
                tui=tui,
                tui_events=tui_events,
                diag=emit_diagnostic,
                external_sink=progress_sink,
            )
            # Subagent delegation (t6) — the top-level spawn callback is built here
            # so both `work` and `session`, and every backend (which forwards
            # `config.subagent_spawn`), can delegate identically. depth defaults to
            # 1; the launcher binds each child to depth+1, so recursion is bounded
            # by MAX_SUBAGENT_DEPTH. ONE shared agent budget is threaded into BOTH
            # callbacks so the global MAX_SUBAGENT_TOTAL cap is actually enforced
            # across single + batch + nested delegation (#t4 Q3 wiring fix).
            budget = new_agent_budget(config)
            config.subagent_spawn = make_spawn(task.repo_path, config, task.engine, counter=budget)
            config.subagent_batch_spawn = make_batch_spawn(
                task.repo_path, config, task.engine, counter=budget
            )
            try:
                result = engine.work(task, config)
            except Exception as exc:  # noqa: BLE001 - any failure still writes an artifact (h5)
                # Prefer the partial result the loop preserved on an engine raise
                # (#37): its steps / usage / changed_files + trace reflect the work
                # done up to the failure. Fall back to a fresh failed_result for a
                # failure with no partial (e.g. an error before the loop starts).
                partial = getattr(exc, "result", None)
                if isinstance(partial, TaskResult):
                    result = partial
                    original: BaseException = exc.__cause__ or exc
                    # A partial run has accumulated steps -> the trace is non-empty.
                    artifact_note = "a result artifact (with the partial trace) was still written"
                else:
                    # Carry the request into stats so even an early-failure
                    # artifact stays discoverable-by-request / sortable in
                    # `feedback list` and is named with a slug (#132).
                    result = failed_result(
                        task.id, f"{type(exc).__name__}: {exc}", request=task.instruction
                    )
                    original = exc
                    # No partial result -> the trace is empty; don't claim otherwise.
                    artifact_note = "a result artifact was still written"
                result.command = command_name
                work_span.set(status=result.status)
                write(result, artifact_dir(repo))
                # The work item happened (even if it failed) — record it as 'last' so
                # `feedback last` can still grade it. Best-effort: never mask the error.
                with suppress(Exception):
                    set_last_work(repo, result.task_id)
                raise CliError(
                    EXIT_ENV_ERROR,
                    f"engine '{engine_name}' failed: {original}",
                    f"check the engine config / vLLM server; {artifact_note}",
                    result=result if isinstance(partial, TaskResult) else None,
                ) from exc
            finally:
                # Close the live cockpit on every exit path (success or engine
                # failure) so the final frame shows the work item as finished. Best-
                # effort: a render glitch must never mask the real outcome.
                if cockpit_sink is not None:
                    with suppress(Exception):
                        cockpit_sink.close()

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
                # A no-op when not isolated (worktree_path is None).
                _preserve_isolated_wip(worktree_path, result.status)

            work_span.set(
                status=result.status,
                step_count=len(result.steps),
                pr_url=result.pr_url,
            )
            result.command = command_name
            artifact_path = write(result, artifact_dir(repo))
            # Record this as the repo's most recent work item so `colleague feedback
            # last` resolves to it. Best-effort: a pointer write must never break
            # a successful work item.
            with suppress(Exception):
                set_last_work(repo, result.task_id)
            return result, artifact_path
    finally:
        # Restore the operator's prior signal disposition (#222) before teardown, so
        # the interrupt-commit handler is never left armed past this work item.
        _restore_signals()
        telemetry.flush()
        # Tear down the isolation worktree on every exit path (success, engine
        # failure, handoff error), KEEPING its colleague/<id> branch — the branch
        # is the deliverable the operator merges; only the working dir is disposable.
        # On an interrupt the WIP is already committed to that branch (the handler /
        # the cooperative-stop path above), so removing the working dir loses nothing.
        if worktree_path is not None:
            with suppress(Exception):
                worktrees.isolation_worktree_remove(str(repo), worktree_path)


def _build_task(args: argparse.Namespace, repo: Path, engine: str, config: EngineConfig) -> Task:
    """Resolve the positional tokens into a :class:`Task` (instruction or --command).

    ``args.instruction`` is a list (nargs="*"). With ``--command`` set the tokens
    are template arguments (expanded via :func:`expand_command`); without it they
    are a plain instruction. Raises :class:`CliError` when neither is supplied or
    a template fails to expand. Extracted from :func:`cmd_work` to keep that
    function's cognitive complexity under the threshold (SonarCloud S3776).
    """
    positional_tokens: list[str] = getattr(args, "instruction", None) or []
    command_name: str | None = getattr(args, "command_name", None)
    has_command = bool(command_name)
    has_instruction = not has_command and bool(positional_tokens)

    if not has_instruction and not has_command:
        raise CliError(
            EXIT_USER_ERROR,
            "missing required argument: provide an instruction or --command <name>",
            "run 'colleague work --help' to see usage",
        )

    if has_command:
        # Positional tokens are template arguments when --command is set.
        try:
            return expand_command(
                repo,
                command_name,
                positional_tokens,
                engine_default=engine,
                model=config.model,
            )
        except CommandError as exc:
            raise CliError(
                EXIT_USER_ERROR,
                str(exc),
                "list available commands with: colleague commands list --repo <path>",
            ) from exc

    # Plain instruction path (original behaviour).
    return Task.new(str(repo), " ".join(positional_tokens), engine=engine)


def _validated_mode(mode: str | None) -> str | None:
    """Validate a ``--mode`` value against the session-mode catalog.

    ``None`` passes through (no profile). An unknown name raises a clean,
    choices-shaped :class:`CliError` — never a silent no-op profile.
    """
    if mode is None:
        return None
    # Lazy import: session_modes is a leaf catalog; keep work's import graph flat.
    from colleague.session_modes import MODES

    if mode not in MODES:
        raise CliError(
            EXIT_USER_ERROR,
            f"unknown mode: {mode}",
            f"valid modes: {', '.join(MODES)}",
        )
    return mode


def cmd_work(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))

    # Decorative startup banner — interactive TTY only, suppressed in --json so
    # neither stdout (the result stream) nor agent-parsed stderr is polluted (issue #15).
    emit_banner(emit_diagnostic, json_mode=json_mode)

    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        raise CliError(
            EXIT_USER_ERROR,
            f"repo path is not a directory: {args.repo}",
            "pass --repo pointing at an existing repository",
        )

    # Resolve the engine: explicit --engine > COLLEAGUE_ENGINE > vllm-openai.
    # A bare work item never silently falls through to the no-op mock (#53).
    engine = resolve_engine(args.engine)

    config = EngineConfig.resolve(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_steps=args.max_steps,
        repo_path=repo,
    )

    config.role = getattr(args, "role", None)

    # Mode validation (t3): a typo must fail loudly with the valid choices, not
    # silently no-op. Validated explicitly + early (the --algo idiom — a
    # value-carrying flag cannot take a parse-time choices= without colliding
    # with its signature-derived flag at App build time).
    mode = _validated_mode(getattr(args, "mode", None))

    _apply_lint_optout(args, config)
    _apply_affected_tests_optout(args, config)

    command_name: str | None = getattr(args, "command_name", None)
    task = _build_task(args, repo, engine, config)

    watch = bool(getattr(args, "watch", False))
    task.watch = watch
    if watch:
        if flight.depth_exceeded():
            raise CliError(
                EXIT_USER_ERROR,
                "flight depth cap reached — refusing to nest another sub-flight",
                "a flight may pilot a sub-flight, but not unbounded recursion",
            )
        os.environ.update(flight.child_depth_env())
        emit_diagnostic(
            f"flight: {task.id}\n"
            f"feed: {flight.feed_path(repo, task.id)}\n"
            f"control: {flight.control_path(repo, task.id)}"
        )

    # Delegate the full work orchestration to the shared helper, which records
    # the originating command on the result before every artifact write.
    try:
        result, artifact_path = execute_work(
            repo=repo,
            engine_name=engine,
            task=task,
            open_pr=not args.no_pr,
            allow_dirty=getattr(args, "allow_dirty", False),
            # `colleague work`/`drive` (and `ask-colleague write --apply`) ALWAYS
            # run worktree-isolated, so the result lands on colleague/<id> and the
            # operator's tree/branch are never touched (#196/#201). `session` keeps
            # its in-place interactive path (it calls execute_work without isolate).
            isolate=True,
            base=args.base,
            config=config,
            command_name=command_name or None,
            tui=getattr(args, "tui", None),
            tui_events=getattr(args, "tui_events", None),
            mode=mode,
            explicit_knobs=(
                frozenset({"max_steps"}) if args.max_steps is not None else frozenset()
            ),
        )
    except CliError as exc:
        # On a partial-bearing failure, surface the preserved partial TaskResult to
        # stdout (--json only) so machine consumers (e.g. ask-colleague.sh) can parse it.
        # The diagnostic stays on stderr and the exit code stays non-zero — both are
        # handled by the _dispatch layer that catches this re-raise.
        if json_mode and exc.result is not None:
            emit_result(exc.result.to_dict(), json_mode=True)
        raise

    # Surface the warn-only "too big for one repo" capacity warning (#156) on stderr
    # — a diagnostic, so it never pollutes the stdout result stream and reaches the
    # caller (agent or human) in both text and --json modes; it is also recorded in
    # the artifact (result.to_dict()).
    if result.capacity_warning:
        emit_diagnostic(f"capacity warning: {result.capacity_warning}")

    _surface_lint_residual(result)

    if json_mode:
        emit_result(result.to_dict(), json_mode=True)
    else:
        emit_result(_render(result, engine, artifact_path), json_mode=False)
    if result.status == OK:
        return 0
    if result.status == INCOMPLETE:
        return 2
    return 1


def _configure_work_parser(p: argparse.ArgumentParser) -> None:
    """Add ``work``'s positional + flags to an already-created parser.

    Shared by the legacy :func:`_add_work_parser` (the pre-flip argparse path)
    and the agentfront host-command ``configure`` hook (:func:`register_into`),
    so the two registration doors build a byte-identical surface. It does NOT
    call ``set_defaults(func=...)``: the legacy path sets ``func=cmd_work`` after
    calling this; the host-command path lets agentfront set ``func=`` to the
    handler it was registered with (also ``cmd_work``).
    """
    # ``instruction`` is now zero-or-more positional tokens (nargs="*") so
    # ``--command`` can be the sole input without argparse raising an error.
    p.add_argument(
        "instruction",
        nargs="*",
        help=(
            "A goal or instruction to pursue autonomously.  "
            "Mutually exclusive with --command.  "
            "When --command is used, any positional tokens are passed as template arguments."
        ),
    )
    p.add_argument(
        "--command",
        dest="command_name",
        metavar="NAME",
        default=None,
        help="Expand a saved command template and run it (mutually exclusive with instruction).",
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Backend plugin to use (default: COLLEAGUE_ENGINE or vllm-openai).",
    )
    p.add_argument("--no-pr", action="store_true", help="Commit locally; do not push or open a PR.")
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Run even when the working tree has uncommitted tracked changes "
            "(they get committed onto the work branch). Default: refuse, to "
            "protect in-progress work (#149)."
        ),
    )
    p.add_argument(
        "--no-lint",
        action="store_true",
        help=(
            "Skip the pre-finish lint gate (by default the repo's configured "
            "linters are run + auto-fixed before handoff; this opts out). Also "
            'via COLLEAGUE_LINT=0 or .colleague/config.json {"lint": false}.'
        ),
    )
    p.add_argument(
        "--no-affected-tests",
        action="store_true",
        dest="no_affected_tests",
        help=(
            "Skip the pre-finish affected-tests gate (by default the tests that "
            "transitively import the changed module(s) are run before handoff; "
            "this opts out). Also via COLLEAGUE_AFFECTED_TESTS=0 or "
            '.colleague/config.json {"affected_tests": false}.'
        ),
    )
    p.add_argument(
        "--test",
        metavar="PYTEST_ARGS",
        help=(
            "Run this explicit pytest selection as the affected-tests gate "
            "instead of the auto reverse-import selection."
        ),
    )
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument(
        "--role",
        default=None,
        help="Run the work item as a typed subagent role (e.g. explorer, reviewer, writer).",
    )
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument(
        "--mode",
        default=None,
        help=(
            "Constraint-profile mode (auto|work|plan|explore|review): applies the "
            "mode's step/context/reserve/timeout/fill-line profile as DEFAULTS — "
            "explicit flags and COLLEAGUE_* env vars still win. Profiles only; the "
            "tool surface is selected by --role."
        ),
    )
    p.add_argument(
        "--tui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render a live cockpit (with popups) on stderr during the work item. "
            "Default: auto — on when stderr is an interactive TTY. "
            "Use --no-tui to force the plain 'step N:' lines."
        ),
    )
    p.add_argument(
        "--tui-events",
        metavar="PATH",
        default=None,
        help="Append a live WorkStep JSONL stream to PATH (replay with 'tui replay').",
    )
    p.add_argument("--json", action="store_true", help="Emit the result as structured JSON.")
    p.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Arm a flight-control plane so a pilot can watch/guide/stop "
            "this work item (see 'colleague flight')."
        ),
    )


_WORK_HELP = (
    "Work toward a goal: act autonomously on a request or instruction "
    "through a coder backend, then hand off the result."
)


def _add_work_parser(sub: argparse._SubParsersAction, name: str, *, help_text: str) -> None:
    p = sub.add_parser(name, help=help_text)
    _configure_work_parser(p)
    p.set_defaults(func=cmd_work)


def register(sub: argparse._SubParsersAction) -> None:
    _add_work_parser(sub, "work", help_text=_WORK_HELP)
    # Deprecated alias of `work` (the old car-themed verb), kept for
    # back-compatibility. Labelled in --help so the surface nudges toward `work`.
    _add_work_parser(sub, "drive", help_text="Deprecated alias of 'colleague work'.")


def register_into(app) -> None:
    """Register ``work`` (deprecated alias ``drive``) as an agentfront host command.

    ``work`` is deliberately NOT a rendered registry tool. It owns CLI-specific
    semantics the agentfront tool dispatch (return-value → ``emit_result``, exit
    always 0; raise → structured error) cannot express:

    * **custom exit codes with the result still on stdout** — ``0`` on ``OK``,
      ``2`` on ``INCOMPLETE`` (#192, a load-bearing contract a caller branches
      on), ``1`` on a soft error — none of which a "return a value, exit 0" tool
      can produce;
    * a streamed per-step progress feed + an interactive banner;
    * its own ``--json`` ``TaskResult`` emission (a tool func never receives
      ``json_mode``).

    So it is registered as a **host command**, reusing :func:`cmd_work`'s
    ``(args) -> int`` handler verbatim (agentfront's ``_dispatch`` still gives it
    the ``AgentfrontError`` → structured-stderr + no-traceback wrapper, and a
    :class:`~colleague.cli._errors.CliError` is an ``AgentfrontError`` subclass).
    The ``drive`` alias rides along on the same handler + configure.
    """
    app.add_command(
        "work",
        cmd_work,
        help=_WORK_HELP,
        configure=_configure_work_parser,
        aliases=("drive",),
    )

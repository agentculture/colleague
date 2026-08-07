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
import json
import os
import signal
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable

from colleague import background, flight, media, registry, rig, worktrees
from colleague.artifact import (
    artifact_dir,
    failed_result,
    find_artifact,
    read_chain_view,
    update_config_events,
    write,
)
from colleague.cli._banner import emit_banner
from colleague.cli._commands._presence_sink import (
    ack_packet_for_task,
    build_foreground_presence,
    build_watch_presence,
    compose_presence_sink,
    fold_presence_snapshot,
)
from colleague.cli._commands._tui_sink import CockpitProgressSink, build_progress
from colleague.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_diagnostic, emit_result
from colleague.commands import CommandError, expand_command
from colleague.config import EngineConfig, apply_mode_profile, resolve_engine
from colleague.contract import INCOMPLETE, OK, ChainView, Task, TaskResult
from colleague.feedback import set_last_work
from colleague.handoff import (
    HandoffError,
    branch_name,
    chain_handoff_finalize,
    commits_ahead,
    handoff,
    head_sha,
    reap_chain_intermediates,
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
        result.tip_sha = outcome.tip_sha
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


def _apply_coherence_optout(args: argparse.Namespace, config: EngineConfig) -> None:
    """Apply the ``--no-coherence`` opt-out — the highest-precedence switch (#294).

    Applied AFTER ``EngineConfig.resolve`` (which handled env > config.json >
    default-on for ``config.coherence``); the flag wins last — the exact
    ``--no-lint`` precedent.
    """
    if getattr(args, "no_coherence", False):
        config.coherence = False


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


def _surface_coherence_hints(result: TaskResult) -> None:
    """Surface coherence diagnostics/errors on stderr (#294) — advisory only.

    A diagnostic, never the stdout result stream; the full report (with frame
    provenance) is in the artifact (``result.coherence_report``).
    """
    if not result.coherence_report:
        return
    from colleague import coherence as _coherencemod

    for line in _coherencemod.diagnostics_lines(result.coherence_report):
        emit_diagnostic(line)


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


def _engine_failure_error(
    exc: Exception,
    *,
    task: Task,
    repo: Path,
    engine_name: str,
    command_name: str | None,
    mode: str | None,
    work_span,
    continued_from: str | None = None,
    worktree_path: str | None = None,
    presence: "object | None" = None,
    presence_fold_chat: bool = False,
) -> CliError:
    """Turn an engine raise into the failure artifact + a diagnosable CliError.

    The engine-failure ``except`` body from :func:`execute_work`, extracted to
    keep that function under the S3776 cognitive-complexity threshold. Returns
    (never raises) the :class:`CliError` so the caller can ``raise ... from exc``
    at the original site.

    Prefers the partial result the loop preserved on an engine raise (#37): its
    steps / usage / changed_files + trace reflect the work done up to the
    failure; falls back to a fresh ``failed_result`` for a failure with no
    partial (e.g. an error before the loop starts). Writes the artifact and the
    ``last_work`` pointer (the work item happened even if it failed — a 1/5 is
    exactly the ROI signal), and names the exception class when the payload is
    bare (#269: ``KeyError: 'path'`` instead of ``'path'``). With a
    *worktree_path*, the iso worktree's uncommitted progress is swept onto the
    ``colleague/<id>`` branch and the hint names the surviving branch (#268
    ask 3 — the #222 sweep extended to the exception path). With a *presence*
    (t9 — background presence), any accumulated cost/injection records still
    fold onto the failure artifact before it is written, so an engine crash
    never silently drops the senses cost the run already incurred.
    """
    partial = getattr(exc, "result", None)
    if isinstance(partial, TaskResult):
        result = partial
        original: BaseException = exc.__cause__ or exc
        # A partial run has accumulated steps -> the trace is non-empty.
        artifact_note = "a result artifact (with the partial trace) was still written"
    else:
        # Carry the request into stats so even an early-failure artifact stays
        # discoverable-by-request / sortable in `feedback list` (#132).
        result = failed_result(task.id, f"{type(exc).__name__}: {exc}", request=task.instruction)
        original = exc
        # No partial result -> the trace is empty; don't claim otherwise.
        artifact_note = "a result artifact was still written"
    result.command = command_name
    # Mode (t7 / spec R3 / #256): recorded on the failure path too — a moded run
    # that raises still carries the mode that drove it.
    result.mode = mode
    # Lineage (#167): the failure path keeps it too — a continued run that
    # crashes still names what it was continuing.
    result.continued_from = continued_from
    if presence is not None:
        fold_presence_snapshot(result, presence, fold_chat=presence_fold_chat)
    work_span.set(status=result.status)
    write(result, artifact_dir(repo))
    # Best-effort: never mask the error.
    with suppress(Exception):
        set_last_work(repo, result.task_id)
    # A bare exception payload (e.g. KeyError('path') -> "'path'") tells the
    # operator nothing — name the exception class so the error is diagnosable
    # from the message alone (#269).
    detail = str(original)
    if not detail or not any(ch.isspace() for ch in detail):
        detail = f"{type(original).__name__}: {detail}".rstrip(": ")
    # #268 ask 3: an engine-failure abort must not strand the model's uncommitted
    # progress in the (about-to-be-removed) iso worktree. Commit it onto the
    # colleague/<id> branch — the same #222 sweep the signal and non-OK paths
    # already get — and point the operator at the surviving branch, so an
    # orchestrator can resume from the partial work instead of spelunking for it.
    wip_note = ""
    if _preserve_isolated_wip(worktree_path, f"engine failure: {detail[:80]}"):
        wip_note = f"; partial work preserved on branch {branch_name(task.id, task.instruction)}"
    return CliError(
        EXIT_ENV_ERROR,
        f"engine '{engine_name}' failed: {detail}",
        f"check the engine config / vLLM server; {artifact_note}{wip_note}",
        result=result if isinstance(partial, TaskResult) else None,
    )


def _moded_config(config: EngineConfig, mode: str | None, repo: Path) -> EngineConfig:
    """Apply *mode*'s constraint profile to *config* (t3 / spec R1 / #254).

    A strict no-op without a mode (h1). The caller's explicit CLI knobs travel
    on ``config.explicit_knobs`` (a runtime-only field, the ``role`` precedent
    — keeps execute_work under the S107 parameter ceiling) and are never
    overwritten. Extracted from :func:`execute_work` (SonarCloud S3776).
    """
    if not mode:
        return config
    return apply_mode_profile(config, mode, explicit=config.explicit_knobs, repo_path=repo)


def _announce_flight(task: Task, repo: Path, progress_sink: "CockpitProgressSink | None") -> None:
    """Emit the flight-attach handle for a watched non-session run (#307/#310).

    Called AFTER every guard (dirty tree, unknown engine) and isolation, so a
    REFUSED run never prints a stray handle before its "error:" line
    (armed-by-default made every early error hit that ordering). Uses *repo*
    (the operator repo — the plane lives there, not the worktree, #310). Only
    fires on the non-session work path (``progress_sink is None``); the
    interactive session has its own live UI and needs no stderr handle.
    Extracted from :func:`execute_work` to keep its cognitive complexity under
    the S3776 threshold.
    """
    if task.watch and progress_sink is None:
        emit_diagnostic(
            f"flight: {task.id}\n"
            f"feed: {flight.feed_path(repo, task.id)}\n"
            f"control: {flight.control_path(repo, task.id)}"
        )


def _arm_delta_stream(config: EngineConfig, cockpit_sink: object) -> None:
    """Arm the token-delta seam on a cockpit sink that wants it (t6, extended t4/ssv).

    Live generation tail (feels-alive arc): arms the runtime's optional
    token-delta seam (`EngineConfig.on_delta`, task t3). *cockpit_sink* is
    non-None on two shapes: the standalone `work --tui`/auto-detected-colour-TTY
    cockpit (`build_progress`'s `cockpit_active` gate — a genuinely
    live-rendering surface, `CockpitProgressSink`), and the interactive
    session's own bookkeeping sink (`_WorkSink`), built for EVERY session work
    item regardless of render tier. `wants_delta_stream` is what each sink
    kind decides for itself: `CockpitProgressSink` is always True (it only
    exists when live rendering is already on); `_WorkSink` is ALSO always
    True (task t4/ssv, c19/h16) — a session cortex turn arms the seam on
    every tier, not only its dynamic ANSI one, because arming has a second
    job besides display: it flips the engine onto its per-read-timeout-
    resetting streamed request path (`config.on_delta is not None` is the
    ONLY blocking-vs-streaming decision, `vllm_openai._make_complete`), which
    a long turn on a slow model needs regardless of whether anything redraws.
    The VISIBLE redraw stays ANSI-only, decided entirely inside `_WorkSink`
    itself (`on_delta`/`__call__`'s own `sess.view == "ansi"` checks) — a
    piped/`--json`/Markdown session still never streams into a frame nobody
    redraws, it just also gets the timeout-reset benefit now. No new CLI
    flag: this is a resolution change, not an opt-in.
    The default is OPT-OUT (`getattr(..., False)`): both live cockpit sinks
    declare the property explicitly, while an EXTERNAL caller-supplied sink
    that never heard of deltas stays unarmed (an opt-in default crashed such
    callers on the missing `on_delta` attribute). Every other path — bare
    non-TTY `work`, `--no-tui`, `--tui-events` alone, i.e. `cockpit_sink is
    None` — passes ``None``, so `config.on_delta` keeps its byte-identical
    default; this path is untouched by t4/ssv. Extracted from
    :func:`execute_work` to keep its cognitive complexity under the S3776
    threshold.

    The reset is UNCONDITIONAL (mirroring how ``config.progress`` is
    overwritten every run): any long-lived caller that reuses one
    ``EngineConfig`` across work items (the session, an embedding host) must
    never carry a previous run's armed sink — a stale bound method — into a
    later run whose own sink is absent or declines (Qodo #318 review, comment
    3560546632).
    """
    config.on_delta = None
    if cockpit_sink is not None and getattr(cockpit_sink, "wants_delta_stream", False):
        config.on_delta = cockpit_sink.on_delta


@dataclass(frozen=True)
class DisplayOptions:
    """The cockpit/TUI display knobs, bundled (SonarCloud S107 — the recorded
    hot-signature pattern: rarely-passed presentation knobs ride one frozen
    options object instead of two positional-adjacent params)."""

    #: Live-cockpit activation (#74 A1): True forces on, False off, None auto.
    tui: bool | None = None
    #: Optional WorkStep-JSONL path (#74 A3) an agent can follow / `tui replay`.
    tui_events: str | None = None
    #: Optional caller-supplied cockpit sink (#74 A2): the interactive
    #: ``session`` binds one to its own ``CockpitState`` + frame-writer so a
    #: work item renders into the session's one shared screen (replacing the
    #: auto-constructed cockpit). ``None`` (the default) preserves the
    #: byte-identical ``work`` path. Rides this bundle since v1.47.0
    #: (SonarCloud S107 on ``execute_work`` — same recorded pattern).
    sink: "CockpitProgressSink | None" = None


#: The constraint-profile modes whose work items are read-only by INTENT
#: (their chains use read-only progress semantics + stay handoff-free, the
#: read-only-role treatment — t12 live-dogfood catch).
_READ_ONLY_MODES = frozenset({"explore", "review"})


# ---------------------------------------------------------------------------
# Config-plane arming (change-content consumption lane, plan task t9 —
# spec docs/specs/2026-08-06-change-content-consumption-lane.md, c5/h5/c28/h22)
# ---------------------------------------------------------------------------
#
# The three-tier design lets cortex CONFIGURE the worker episode (a narrowed
# tool set, a bounded strategist note, extra knowledge) via
# colleague/configlifecycle.py + colleague/configurator.py — both complete
# and tested, but nothing in either CLI or session front ever constructed a
# lifecycle or called colleague.chain.run_configurator_window (d3). This
# section is that missing caller: arming lives HERE (execute_work /
# execute_work_chain), never in cmd_work's argv parsing, so both the CLI and
# the session palette (which calls these two functions directly) inherit it
# identically. All imports below are LAZY — a run that never arms three-tier
# (config.worker is None, the default) never pays for the config-plane
# machinery's import graph, mirroring colleague/chain.py's own lazy
# colleague.configurator import.


@dataclass
class _ConfigPlaneState:
    """Bookkeeping for ONE top-level task's config plane.

    Bundles the :class:`~colleague.configlifecycle.EpisodeConfigLifecycle`
    every engine consumes via ``config.config_lifecycle`` (attached at
    construction, so the loop/engines see it from the very first dispatch),
    the configurator's own :class:`~colleague.configevents.ConfigEventStream`
    (a SEPARATE audit trail — see :func:`_combined_config_events`), the
    :class:`~colleague.lattice.CapabilityCatalog` resolved once and reused by
    every window this task runs, and the APPLIED
    :class:`~colleague.lattice.ChangeUnit` objects accumulated across every
    window so far (q5 — the only way an applied strategist unit's verbatim
    content can ride the folded artifact, since neither the lifecycle's own
    event nor :class:`~colleague.configlifecycle.ConfigApplication` carries
    it).

    Constructed EXACTLY ONCE per top-level task (h22: "one
    ``EpisodeConfigLifecycle`` instance belongs to exactly one TOP-LEVEL
    task") — a standalone (non-chained) :func:`execute_work` call builds its
    own via :func:`_arm_config_plane`; an armed ``--until-done`` chain is
    itself ONE top-level task, so :func:`execute_work_chain` builds ONE and
    threads it to every episode via ``ChainEpisodeOptions.config_plane``
    rather than each episode building its own (which would violate h22 and
    lose the prior episodes' event history).
    """

    lifecycle: "object"
    stream: "object"
    catalog: "object"
    applied_units: list = field(default_factory=list)


def _build_capability_catalog(config: EngineConfig, repo_path: str) -> "object":
    """The run's actually-resolved tool surface, derived the SAME way the
    engines derive it (``colleague/engines/mock.py``/``vllm_openai.py``:
    ``resolve_role(config, task.repo_path)`` then ``curate_schemas(role)``)
    — the :class:`~colleague.lattice.CapabilityCatalog` contract: "built
    ONLY from a caller-supplied resolved tool allow-list", never minted by
    the lattice itself.

    ``deepthink`` stays at :func:`~colleague.tools.curate_schemas`'s default
    ``False``: deepthink is absent in three-tier mode (an architecture
    invariant — three-tier and dual-model deepthink are mutually exclusive
    escalation surfaces), so the offered surface here never includes the
    deepthink tool schema.
    """
    from colleague.lattice import CapabilityCatalog
    from colleague.loop import resolve_role
    from colleague.tools import curate_schemas

    role = resolve_role(config, repo_path)
    schemas = curate_schemas(role)
    tool_ids = tuple(s["function"]["name"] for s in schemas)
    return CapabilityCatalog(tool_ids=tool_ids)


def _accumulate_applied(state: "_ConfigPlaneState", window_result: "object") -> None:
    """Fold ONE window's applied :class:`~colleague.lattice.ChangeUnit`
    objects onto *state* (q5) — the ACCUMULATED list :func:`_combined_config_events`
    later matches positionally against every "applied" event the lifecycle
    ever recorded, across every window this top-level task has run.

    A no-op unless the window actually reviewed AND applied something: an
    unarmed configurator (``reviewed=False``), a degraded review, or a
    healthy ``{"changes": []}`` reply each apply nothing, so there is
    nothing to accumulate — mirrors
    :func:`colleague.configurator.record_applied`'s own precondition
    (``review.verified`` is exactly what *application* drained, for the ONE
    sanctioned review-then-apply call sequence
    :func:`colleague.chain.run_configurator_window` makes).
    """
    if not window_result.reviewed or window_result.application is None:
        return
    if window_result.application.applied_count == 0:
        return
    state.applied_units.extend(window_result.review.verified)


def _arm_config_plane(
    config: EngineConfig, *, repo: Path, task: Task, engine_name: str
) -> "_ConfigPlaneState | None":
    """Construct the config plane and run its ``WINDOW_BEFORE_EPISODE_1``
    window — a strict no-op (returns ``None``) unless three-tier is armed
    (``config.worker is not None``: config.py's own resolution already made
    the worker role MANDATORY-if-armed, c25/h21, so this reads arming from
    the RESOLVED config rather than re-deriving it from the lobes gateway).

    The ONE construction site for a top-level task's lifecycle (h22): a
    standalone (non-chained) :func:`execute_work` call reaches this
    directly, before its own single dispatch; an armed ``--until-done``
    chain reaches it exactly once, from :func:`execute_work_chain`, before
    its FIRST episode dispatches — later episodes thread the SAME state via
    ``ChainEpisodeOptions.config_plane`` instead of calling this again.

    The lifecycle is attached to ``config.config_lifecycle`` BEFORE the
    window runs, so it is live (loop/engines will consume it) regardless of
    whether the configurator itself is armed. The configurator's OWN opt-in
    flag (:func:`colleague.configurator.configurator_enabled` — a SEPARATE
    default-off flag from ``three_tier`` itself) is resolved fresh here and
    passed as ``armed=`` to :func:`colleague.chain.run_configurator_window`,
    which is called UNCONDITIONALLY once three-tier is armed but is itself a
    strict no-op (``reviewed=False``, zero completions issued) when the
    configurator is off (acceptance criterion 2) — so the lifecycle is
    always constructed once three-tier is armed, independent of the
    configurator's own arming.

    The catalog is resolved from *repo* (the OPERATOR repo, not a per-episode
    isolated worktree) — deliberately symmetric with
    :func:`execute_work_chain`'s own arming call, which necessarily runs
    BEFORE any per-episode isolation exists. In practice this is the SAME
    tree an isolated episode's worktree checks out (role override files, if
    any, travel with the commit), so the resolved tool surface does not
    differ from what the engine itself later resolves off the isolated
    ``task.repo_path`` — documented here rather than left implicit.
    """
    if config.worker is None:
        return None
    from colleague import chain as chainmod
    from colleague.configevents import ConfigEventStream
    from colleague.configlifecycle import EpisodeConfigLifecycle
    from colleague.configurator import configurator_enabled
    from colleague.reviewinput import assemble_before_episode

    catalog = _build_capability_catalog(config, str(repo))
    lifecycle = EpisodeConfigLifecycle(catalog=catalog)
    stream = ConfigEventStream()
    config.config_lifecycle = lifecycle
    state = _ConfigPlaneState(lifecycle=lifecycle, stream=stream, catalog=catalog)

    window_result = chainmod.run_configurator_window(
        lifecycle,
        chainmod.WINDOW_BEFORE_EPISODE_1,
        armed=configurator_enabled(repo_path=repo),
        review_input=assemble_before_episode(task),
        catalog=catalog,
        stream=stream,
        config=config,
        engine_name=engine_name,
    )
    _accumulate_applied(state, window_result)
    return state


def _run_between_episodes_window(
    state: "_ConfigPlaneState",
    *,
    repo: Path,
    task: Task,
    result: TaskResult,
    config: EngineConfig,
    engine_name: str,
) -> None:
    """Run the config plane's ``WINDOW_BETWEEN_EPISODES`` window (t9) — the
    other of the two sanctioned windows (:data:`colleague.chain.
    WINDOW_BEFORE_EPISODE_1` is the ONE :func:`_arm_config_plane` runs).

    Called from :func:`execute_work_chain`'s go-verdict path — after
    :func:`_chain_should_start_next` decides episode N+1 may dispatch, before
    it actually does — with *task*/*result* the JUST-FINISHED episode's own
    (:func:`colleague.reviewinput.assemble_between_episodes` composes the
    review digest from its terminal facts). A no-op call site guard lives in
    the caller (``if config_plane is not None``); this function itself
    always runs its window once reached, same as :func:`_arm_config_plane`.
    """
    from colleague import chain as chainmod
    from colleague.configurator import configurator_enabled
    from colleague.reviewinput import assemble_between_episodes

    window_result = chainmod.run_configurator_window(
        state.lifecycle,
        chainmod.WINDOW_BETWEEN_EPISODES,
        armed=configurator_enabled(repo_path=repo),
        review_input=assemble_between_episodes(task, result),
        catalog=state.catalog,
        stream=state.stream,
        config=config,
        engine_name=engine_name,
    )
    _accumulate_applied(state, window_result)


def _combined_config_events(state: "_ConfigPlaneState") -> list:
    """Fold the config plane's two append-only records into ONE durable trail
    — never double-counted (spec requirement: "pick ONE source of truth for
    overlapping kinds").

    The CONFIGURATOR STREAM is the source of truth for the whole review
    cycle — proposed / verified / refused / applied / degraded — because it
    is the only record that sees EVERY refusal shape (a malformed reply or
    a change entry that fails to build refuses BEFORE ``lifecycle.propose``
    is ever called, so the lifecycle's own trail is silent about it — Qodo
    #369 review, thread 1) and because it records the cycle in true causal
    order (proposed -> verified -> applied per unit; the previous
    lifecycle-first construction appended every "verified" after every
    "applied" — thread 2). Stream events pass through
    :func:`colleague.contract.map_configlifecycle_events` for the
    class-selective applied-content enrichment (q5, via
    *state.applied_units* — the stream's applied events are 1:1 and
    same-order with the accumulated applied units) and reason preservation.

    The LIFECYCLE contributes ONLY its "boundary" events (mapped onto
    ``EVENT_KIND_BASELINE`` — an episode-boundary marker the stream has no
    equivalent of, recorded once per ``run()`` exit), appended after the
    cycle trail. For a single-episode run this IS chronological (the
    boundary fires at run exit, after the one window); on a chain the
    per-window interleave is approximated — each boundary event carries its
    own boundary index and effective-config digest, which is what anchors
    it to a config state, not its list position (documented approximation,
    deliberate).

    ``seq`` is renumbered across the COMBINED list — a monotonic index into
    what ``TaskResult.config_events`` actually carries, never trusted from
    either source's own internal numbering.
    """
    from dataclasses import replace as _replace

    from colleague.contract import map_configlifecycle_events

    cycle = map_configlifecycle_events(state.stream.replay(), applied_units=state.applied_units)
    boundaries = map_configlifecycle_events(
        [e for e in state.lifecycle.events() if getattr(e, "kind", "") == "boundary"]
    )
    combined = cycle + boundaries
    return [_replace(event, seq=i) for i, event in enumerate(combined)]


def _fold_config_plane(
    state: "_ConfigPlaneState", *, repo: Path, task_id: str, result: TaskResult
) -> None:
    """The cumulative fold (q2): land the combined config events on *result*
    AND rewrite the ALREADY-PERSISTED artifact — the ONE place both copies
    are kept in sync (acceptance criterion 3), mirroring
    :func:`colleague.artifact.update_config_events`'s own docstring ("the
    loop writes a work item's artifact exactly once, at run end ... the
    config-plane fold happens AFTER that").

    Crash-window honesty (acceptance criterion 3, stated here and pinned by
    a test): by the time this function runs, :func:`colleague.artifact.write`
    has ALREADY durably persisted *result*'s base shape (steps, usage,
    status, branch, everything) — this function only ever ADDS the
    ``config_events``/``config_digest`` keys via a REWRITE
    (:func:`colleague.artifact.update_config_events`). A process killed
    between ``result.config_events = events`` below and that rewrite
    finishing therefore loses AT MOST the events THIS window alone
    contributed — every EARLIER window's fold already landed durably on a
    PRIOR call to this same function (one per episode), so the loss is
    bounded to "the last window", never the whole audit trail.
    """
    from colleague.contract import config_digest_for

    events = _combined_config_events(state)
    result.config_events = events
    # ``config_digest`` is its OWN TaskResult field (not auto-derived by
    # to_dict()) — recomputed here from *events* alone, the same way
    # colleague.artifact.update_config_events recomputes it for the on-disk
    # copy, so the in-memory result and the rewritten artifact never
    # independently drift (both derive it from config_digest_for(events)).
    result.config_digest = config_digest_for(events)
    update_config_events(repo, task_id, events)


@dataclass(frozen=True)
class ChainEpisodeOptions:
    """Per-episode chain-dispatch knobs (indefinite-run t5) — the S107-safe
    bundle (the :class:`DisplayOptions` precedent). Non-``None`` exactly when
    :func:`execute_work` is dispatched by the ``--until-done`` chain loop
    (:func:`_run_chain`); ``None`` (every other caller) is byte-identical to
    the pre-chain behavior."""

    #: The prior episode's ``colleague/<id>`` branch — episode N+1's worktree
    #: base (tree carry, c6/h6). ``None`` on the chain's first episode.
    base_ref: str | None = None
    #: The chain view stamped on the PRIOR episode's artifact (``None`` on the
    #: first episode); this episode's ``result.chain`` accumulates onto it
    #: (sums of per-episode exact usage, c20/h19).
    prior_view: ChainView | None = None
    #: The UNION of every prior episode's ``result.changed_files`` so far
    #: (sorted, deduped) — ``()`` on the chain's first episode. Accumulated by
    #: :func:`execute_work_chain`'s loop and threaded by :func:`execute_work`
    #: into :class:`~colleague.loop.ContextControls.chain_prior_changed`
    #: (indefinite-run follow-up, issue #335, decision c22). Read by the NEXT
    #: task's gate-skip guard — dormant plumbing here.
    prior_changed: tuple[str, ...] = ()
    #: The whole top-level task's shared config-plane state (change-content
    #: consumption lane, plan task t9 — h22). Constructed ONCE by
    #: :func:`execute_work_chain` when three-tier is armed and threaded to
    #: EVERY episode, so each episode's fold sees the SAME
    #: lifecycle/stream/accumulated-applied-units. ``None`` for an unarmed
    #: chain (byte-identical) — a standalone (non-chained) call to
    #: :func:`execute_work` never reads this field; it arms its OWN state via
    #: :func:`_arm_config_plane` instead.
    config_plane: "_ConfigPlaneState | None" = None


def _arm_chain_dispatch(config: EngineConfig, chain: "ChainEpisodeOptions | None") -> str | None:
    """Stamp the chain-episode dispatch marker; return the episode base_ref (#335, c22).

    Keyed on ``chain``'s PRESENCE for THIS call, never on ``config.until_done``
    — set unconditionally (including the ``False``/``()`` branch) so a config
    object reused across dispatches (the session's one long-lived
    ``EngineConfig``) never leaks a prior chained call's marker onto a later
    unchained one. A subagent child never sees a ``True`` value regardless:
    ``run_subagent`` resets both fields on the child config it builds via
    ``dataclasses.replace``. Returns ``chain.base_ref`` (the prior episode's
    ``colleague/<id>`` tip, c6) for :func:`_setup_isolation`, ``None`` for an
    unchained dispatch or the chain's first episode. Extracted from
    :func:`execute_work` to keep its cognitive complexity under the S3776
    ceiling (the :func:`_moded_config` precedent; PR #338 Sonar catch).
    """
    config.chain_episode = chain is not None
    if chain is None:
        config.chain_prior_changed = ()
        return None
    config.chain_prior_changed = chain.prior_changed
    return chain.base_ref


def _build_run_presence(
    *, task: Task, config: EngineConfig, engine, external_sink
) -> "tuple[object | None, bool]":
    """Build the run's presence engine, if any — ``(presence, foreground)``.

    The presence-builder half of :func:`execute_work` (extracted for the S3776
    budget, the ``_preserve_isolated_wip`` precedent). Skipped entirely when an
    external ``progress_sink`` was supplied (the interactive ``session`` already
    runs its own middle-manager lane — wiring a second engine would double every
    ack/update). Otherwise the watched builder is tried first, then the
    foreground sibling — the two are gated on ``task.watch`` in opposite
    directions, so at most one returns non-None. ``foreground`` is ``True`` only
    for a one-shot (non-watched) presence, whose chat must be folded from the
    snapshot (no flight plane exists to carry it). Both builds ride
    ``suppress``: narration must never break cortex.
    """
    if external_sink is not None:
        return None, False
    presence = None
    with suppress(Exception):
        presence = build_watch_presence(task=task, config=config, engine=engine)
    if presence is not None:
        return presence, False
    with suppress(Exception):
        presence = build_foreground_presence(
            task=task, config=config, engine=engine, render=emit_diagnostic
        )
        return presence, presence is not None
    return None, False


def _resolve_config_plane(
    chain: "ChainEpisodeOptions | None",
    config: EngineConfig,
    *,
    repo: Path,
    task: Task,
    engine_name: str,
) -> "_ConfigPlaneState | None":
    """Resolve THIS call's config-plane state (change-content consumption
    lane, plan task t9 — h22): a chained episode reuses the state
    :func:`execute_work_chain` already constructed once at arming (one
    lifecycle per top-level task); a standalone (non-chained) call arms its
    OWN state here, before its single dispatch. Both stay ``None`` — a
    strict no-op — unless three-tier is armed (``config.worker is not
    None``). Extracted from :func:`execute_work` to keep its cognitive
    complexity under the S3776 ceiling (the :func:`_moded_config` precedent).
    """
    if chain is not None:
        return chain.config_plane
    if config.worker is not None:
        return _arm_config_plane(config, repo=repo, task=task, engine_name=engine_name)
    return None


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
    display: "DisplayOptions | None" = None,
    mode: str | None = None,
    continued_from: str | None = None,
    chain: "ChainEpisodeOptions | None" = None,
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
    display:
        The bundled cockpit/TUI display knobs (:class:`DisplayOptions` —
        ``tui`` live-cockpit activation #74 A1, ``tui_events`` WorkStep-JSONL
        path #74 A3, ``sink`` the caller-supplied cockpit sink #74 A2 — the
        interactive ``session`` binds one to its own `CockpitState` +
        frame-writer so a work item renders into the session's one shared
        screen, replacing the auto-constructed cockpit); ``None`` (default)
        means every knob at its ``None`` default, byte-identical to the
        pre-bundle behavior.
    continued_from:
        The prior work item's task id when this run CONTINUES it (#167), else
        ``None``. Recorded on the result before every artifact write — the
        one-way lineage the continue path (``work --continue`` / session
        ``/continue``) stamps; omit-when-None keeps ordinary runs byte-identical.
    mode:
        Constraint-profile mode (t3 / spec R1 / #254). When set, the mode's
        profile (``colleague.profiles`` + operator overlays) fills the
        constraint knobs the operator left untouched, via
        :func:`colleague.config.apply_mode_profile` — the ONE code path shared
        by the ``work --mode`` flag and the session's mode selection. ``None``
        (the default) is a strict no-op (byte-identical config). Also recorded
        on ``result.mode`` before *every* artifact write — including the failure
        path — mirroring ``command_name`` above (t7 / spec R3 / #256); omitted
        from the serialized artifact when ``None``.
        The caller's explicit CLI knobs travel on ``config.explicit_knobs``
        (a runtime-only EngineConfig field, the ``role`` precedent) — those
        are never overwritten by the mode profile (precedence h1).
    chain:
        Set (a :class:`ChainEpisodeOptions`) exactly when this run is ONE
        EPISODE of an armed ``--until-done`` chain (indefinite-run t5):
        ``base_ref`` bases the isolation worktree on the prior episode's
        branch tip (tree carry, c6), and the running :class:`ChainView` is
        accumulated onto ``result.chain`` before the artifact write (c20).
        A chained episode also SKIPS the mode-profile application here — the
        chain loop applied it once at arming, so a mid-chain overlay-file
        change is never re-read (inheritance c28). ``None`` (the default,
        every non-chain caller) is byte-identical to the pre-chain behavior.

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
    display = display or DisplayOptions()
    tui, tui_events, progress_sink = display.tui, display.tui_events, display.sink
    # Mode-profile layer (t3 / R1 / #254): fill profile defaults for knobs the
    # operator left untouched, BEFORE anything reads the config (extracted to
    # _moded_config for the S3776 budget). One code path for every entry door.
    # A chained episode (indefinite-run c28) arrives with the profile ALREADY
    # applied once by the chain loop; re-applying here would re-read the mode
    # overlay files mid-chain, so an episode could silently run under a config
    # the operator changed after arming — exactly what c28 forbids.
    if chain is None:
        config = _moded_config(config, mode, repo)

    try:
        engine = registry.load(engine_name)
    except registry.UnknownEngine as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "list engines with: colleague backends list"
        ) from exc

    # Config-plane arming (change-content consumption lane, t9): a chained
    # episode's state was already constructed ONCE by execute_work_chain
    # (h22 — one lifecycle per top-level task, and an armed chain IS one) and
    # rides `chain.config_plane`; a standalone (non-chained) call arms its
    # OWN state here, before the first (only) dispatch. Both are a strict
    # no-op (`config_plane` stays None) unless three-tier is armed
    # (config.worker is not None) — byte-identical to today either way.
    config_plane = _resolve_config_plane(
        chain, config, repo=repo, task=task, engine_name=engine_name
    )

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

            _announce_flight(task, repo, progress_sink)

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
            _arm_delta_stream(config, cockpit_sink)
            # Background presence (presence-default-everywhere arc, task t9):
            # wire the front-agnostic PresenceEngine onto this SAME progress-sink
            # boundary for a watched, non-session work item — a background
            # child (auto-armed --watch) or a plain `colleague work --watch`.
            # Skipped when an external `progress_sink` was supplied (the
            # interactive `session`, which already runs its own middle-manager
            # lane — colleague/cli/_commands/session.py — so wiring a second
            # engine here would double every ack/update). `build_watch_presence`
            # itself is a strict no-op (returns None, byte-identical) when
            # senses is unarmed/disarmed (incl. --cortex-only) or the task is
            # not a flight. Wrapped in suppress: narration must never break cortex.
            # One-shot foreground presence (presence-default-everywhere arc,
            # task t10): the sibling for a plain `colleague work "<task>"` —
            # NOT `--watch`, NOT a session — which has no flight plane at all
            # for `build_watch_presence` to render onto. `build_foreground_presence`
            # is gated the other way round (`task.watch` False), so at most one
            # of the two builders ever returns non-None for a given work item —
            # never a doubled ack/update. Renders straight to stderr via
            # `emit_diagnostic` as labeled `senses:` lines; stdout (the `--json`
            # result stream) is never touched, so presence can never corrupt the
            # machine-parseable contract.
            presence, presence_foreground = _build_run_presence(
                task=task, config=config, engine=engine, external_sink=progress_sink
            )
            if presence is not None:
                with suppress(Exception):
                    presence.acknowledge(ack_packet_for_task(task))
                config.progress = compose_presence_sink(config.progress, presence)
            # Subagent delegation (t6) — the top-level spawn callback is built here
            # so both `work` and `session`, and every backend (which forwards
            # `config.subagent_spawn`), can delegate identically. depth defaults to
            # 1; the launcher binds each child to depth+1, so recursion is bounded
            # by MAX_SUBAGENT_DEPTH. ONE shared agent budget is threaded into BOTH
            # callbacks so the global MAX_SUBAGENT_TOTAL cap is actually enforced
            # across single + batch + nested delegation (#t4 Q3 wiring fix).
            # `parent_task_id=task.id` (spec R6 / plan t16 / #259) records THIS
            # work item's id on every direct child's `SubResult.parent`, so a
            # subagent tree is walkable from artifacts alone.
            budget = new_agent_budget(config)
            config.subagent_spawn = make_spawn(
                task.repo_path,
                config,
                task.engine,
                counter=budget,
                parent_task_id=task.id,
            )
            config.subagent_batch_spawn = make_batch_spawn(
                task.repo_path,
                config,
                task.engine,
                counter=budget,
                parent_task_id=task.id,
            )
            # Rig-level cooperative concurrency budget (t13 / spec R5 / #258): hold
            # ONE slot for the whole model-driving loop, so concurrent TOP-LEVEL
            # work items sharing this repo's endpoint serialize to the operator's
            # declared width instead of starving each other toward the timeout
            # (#239's interference class). Deliberately NOT taken per subagent
            # child: a parent holding a slot would starve its own children
            # (deadlock-by-composition) — in-run fan-out is already budgeted by
            # width-scaled child budgets (t12) + the backpressure throttle (t6).
            # Strict no-op without .colleague/rig.json; degrades OPEN after the
            # wait cap (an advisory backstop, never a wedge).
            try:
                with rig.rig_slot(repo, on_wait=emit_diagnostic):
                    result = engine.work(task, config)
            except Exception as exc:  # noqa: BLE001 - any failure still writes an artifact (h5)
                raise _engine_failure_error(
                    exc,
                    task=task,
                    repo=repo,
                    engine_name=engine_name,
                    command_name=command_name,
                    continued_from=continued_from,
                    mode=mode,
                    work_span=work_span,
                    worktree_path=worktree_path,
                    presence=presence,
                    presence_fold_chat=presence_foreground,
                ) from exc
            finally:
                # Close the live cockpit on every exit path (success or engine
                # failure) so the final frame shows the work item as finished. Best-
                # effort: a render glitch must never mask the real outcome.
                if cockpit_sink is not None:
                    with suppress(Exception):
                        cockpit_sink.close()

            # Fold the presence engine's cost/injection records onto the artifact
            # (t9) — every non-raising exit (OK/INCOMPLETE/ERROR), so an
            # unattended watched run still records what it cost regardless of
            # whether an operator ever attaches via `colleague talk`.
            if presence is not None:
                fold_presence_snapshot(result, presence, fold_chat=presence_foreground)

            _finalize_run_outcome(
                result=result,
                read_only_role=read_only_role,
                work_repo=work_repo,
                task=task,
                baseline_untracked=baseline_untracked,
                open_pr=open_pr,
                base=base,
                telemetry=telemetry,
                base_sha=base_sha,
                worktree_path=worktree_path,
                chain=chain,
            )

            work_span.set(
                status=result.status,
                step_count=len(result.steps),
                pr_url=result.pr_url,
            )
            result.command = command_name
            # Mode (t7 / spec R3 / #256): recorded before the artifact write, mirroring
            # command_name just above. `mode` is None when no mode was selected, and
            # TaskResult.to_dict() omits the key in that case (byte-identical shape).
            result.mode = mode
            # Lineage (#167): recorded before the artifact write, mirroring mode
            # just above; None (an ordinary run) is omitted from the artifact.
            result.continued_from = continued_from
            # Chain accounting (indefinite-run c20/h19): a chained episode's
            # artifact carries the RUNNING chain view — prior totals plus this
            # episode's exact usage/steps, accumulated before the write so
            # every episode's artifact is self-describing (the final episode's
            # view is the whole chain's). None (every non-chain run) keeps the
            # serialized shape byte-identical (omit-when-None).
            if chain is not None:
                result.chain = ChainView.accumulate(chain.prior_view, result)
            # Stale-pin refresh warnings (t11): fold config's refresh warnings
            # into the result before the artifact write, so background/one-shot
            # runs surface them after the fact (h21). No-op when empty.
            if config.model_refresh_warnings:
                result.warnings.extend(asdict(w) for w in config.model_refresh_warnings)
            artifact_path = write(result, artifact_dir(repo))
            # The cumulative config-plane fold (t9, acceptance criterion 3):
            # AFTER the base artifact is durably written, land the combined
            # config events on `result` AND rewrite the just-written artifact
            # so the two copies never drift (see _fold_config_plane's own
            # docstring for the crash-window honesty this ordering buys).
            # A strict no-op (config_plane is None) unless three-tier armed.
            if config_plane is not None:
                _fold_config_plane(config_plane, repo=repo, task_id=result.task_id, result=result)
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


def _collect_attachments(args: argparse.Namespace) -> list[dict] | None:
    """Validate and collect ``--attach PATH`` (repeatable) into attachment dicts.

    Returns ``None`` when no ``--attach`` was given (byte-identical
    ``Task.attachments`` for the common case); otherwise the list of
    :func:`colleague.media.validate_attachment` results, in flag order.
    Raises the same :class:`CliError` as before on an invalid attachment.
    Extracted from :func:`_build_task` to keep that function's cognitive
    complexity under the threshold (SonarCloud S3776).
    """
    raw_attach: list[str] = getattr(args, "attach", None) or []
    if not raw_attach:
        return None
    attachments: list[dict] = []
    for path_str in raw_attach:
        try:
            validated = media.validate_attachment(path_str)
        except ValueError as exc:
            raise CliError(
                EXIT_USER_ERROR,
                f"attachment error: {exc}",
                "pass --attach pointing at an existing file with a known media extension",
            ) from exc
        attachments.append(validated)
    return attachments


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

    continue_ref: str | None = getattr(args, "continue_ref", None)
    if continue_ref is not None:
        return _build_continued_task(args, repo, engine, continue_ref, positional_tokens)

    if not has_instruction and not has_command:
        raise CliError(
            EXIT_USER_ERROR,
            "missing required argument: provide an instruction or --command <name>",
            "run 'colleague work --help' to see usage",
        )

    attachments = _collect_attachments(args)

    if has_command:
        # Positional tokens are template arguments when --command is set.
        try:
            task = expand_command(
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
        # expand_command has no attachments parameter (its Task.new shape is
        # template-owned); --attach applies to a template task the same way
        # the session surface does — assigned post-construction.
        if attachments:
            task.attachments = attachments
        return task

    # Plain instruction path (original behaviour).
    return Task.new(str(repo), " ".join(positional_tokens), engine=engine, attachments=attachments)


def _build_continued_task(
    args: argparse.Namespace,
    repo: Path,
    engine: str,
    continue_ref: str,
    positional_tokens: list[str],
) -> Task:
    """Seed a Task from a prior work item's persisted artifact (#167).

    The flag value is validated here explicitly — never via ``choices=``
    (agentfront#38: a value-carrying flag's choices are not enforced at App
    build time). Positional tokens, when present, are EXTRA operator guidance
    appended after the seed; ``--command`` cannot combine with ``--continue``
    (a template would fight the seed for the instruction). The resolved prior
    id rides ``args._continued_from_resolved`` so :func:`cmd_work` can thread
    it into :func:`execute_work` for the lineage stamp.
    """
    # Lazy import: the continue path is opt-in; keep work's import graph flat.
    from colleague.continuation import ContinuationError, resolve_continuation

    if getattr(args, "command_name", None):
        raise CliError(
            EXIT_USER_ERROR,
            "--continue cannot be combined with --command",
            "run the template fresh, or continue without --command",
        )
    ref = continue_ref.strip()
    if not ref:
        raise CliError(
            EXIT_USER_ERROR,
            "--continue needs a work item reference",
            "pass an explicit task id, or 'last' for the most recent work item",
        )
    try:
        prior_id, seed = resolve_continuation(repo, ref)
    except ContinuationError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            str(exc),
            "list recent work items with: colleague feedback list --repo <path>",
        ) from exc
    instruction = seed
    if positional_tokens:
        instruction += "\n\nAdditional operator guidance:\n" + " ".join(positional_tokens)
    args._continued_from_resolved = prior_id
    task = Task.new(str(repo), instruction, engine=engine, attachments=_collect_attachments(args))
    return task


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


def _resolve_chain_arming(args: argparse.Namespace, config: EngineConfig) -> tuple[int, bool]:
    """Resolve the ``(cap, armed)`` chain pair — the standard knob precedence (c21).

    Explicit flag > env > config.json > default: the env/config.json legs were
    already folded into ``EngineConfig.resolve`` by t3
    (``COLLEAGUE_UNTIL_DONE`` / ``COLLEAGUE_MAX_EPISODES`` →
    ``config.until_done`` / ``config.max_episodes``), so this only lets the
    explicit CLI flags win last — the ``max_steps`` idiom. ``--until-done``
    is arm-only (a bare switch, no ``--no-until-done``), so a config-armed
    chain stays armed. Cap ``0`` (or negative) means unlimited.
    """
    armed = bool(getattr(args, "until_done", False)) or bool(getattr(config, "until_done", False))
    explicit_cap = getattr(args, "max_episodes", None)
    cap = explicit_cap if explicit_cap is not None else int(getattr(config, "max_episodes", 5))
    return cap, armed


def _chain_should_start_next(
    repo: Path, result: TaskResult, state, *, progressed: bool | None, watch: bool
) -> tuple[tuple[str, str] | None, "object"]:
    """Decide the chain's move at ONE episode boundary — the t6 extension seam.

    Everything that happens BETWEEN two episodes funnels through here, in
    order: (1) the pure verdict — ok-guard, continuable allow-list,
    no-progress guard, episode cap (:func:`colleague.chain.should_continue`);
    (2) the between-episode pilot stop (t6): on a WATCHED chain, read the
    JUST-FINISHED episode's flight control — the pilot's live handle — and
    halt (reason :data:`~colleague.chain.HALT_PILOT_STOP`) when a cooperative
    ``stop`` landed in the boundary window, so a stop never dispatches another
    episode (an unwatched chain ignores it, matching the in-episode unwatched
    semantics; :func:`colleague.flight.read_stop` is a pure peek — absent
    control file = no stop); (3) the continuation seed resolution (the
    ok-guard and wrong-run guard live inside
    :func:`~colleague.continuation.resolve_continuation`, wrapped by
    :func:`~colleague.chain.resolve_chain_seed` so a ``ContinuationError`` is
    a clean halt, never a crash).

    Returns ``(seed, verdict)``: ``seed`` is ``(prior_task_id, seed_text)``
    when episode N+1 may dispatch, else ``None``; ``verdict`` is the
    :class:`~colleague.chain.ChainVerdict` that decided it (the halt reason,
    or the continuable exit reason on a go).
    """
    # Lazy import: the chain path is opt-in; keep work's import graph flat.
    from colleague import chain as chainmod

    verdict = chainmod.should_continue(
        result, state.episode_count, state.cap, progressed=progressed
    )
    if not verdict.should_continue:
        return None, verdict
    if watch and flight.read_stop(repo, result.task_id):
        return None, chainmod.ChainVerdict(
            should_continue=False,
            reason=chainmod.HALT_PILOT_STOP,
            detail=(
                f"pilot stop on {result.task_id}'s flight control — episode "
                f"{state.episode_count + 1} was never dispatched"
            ),
        )
    seed, halt = chainmod.resolve_chain_seed(repo, result.task_id)
    if halt is not None:
        return None, halt
    return seed, verdict


def _chain_finalize(
    repo: Path,
    result: TaskResult,
    episode_branches: list[str],
    *,
    instruction: str,
    open_pr: bool,
    base: str,
    pr_body: str | None = None,
) -> Path:
    """The chain's ONE handoff + intermediate reap, on a COMPLETED chain (c26).

    Every episode ran with push/PR suppressed, so this performs the arming
    invocation's handoff choice exactly once: push the FINAL episode's branch
    — which carries the cumulative diff, because each episode based its
    worktree on the prior tip — and open the single PR
    (:func:`~colleague.handoff.chain_handoff_finalize`, gated by the same h7
    predicate as any handoff; ``--no-pr``/no remote/no ``gh`` stays local).
    The final artifact is re-written so it records the REAL ``pr_url``/push
    outcome — never a synthesized one (the #167-arc rule); the rewrite hits
    the same path (same task id + request slug).

    Then the intermediate ``colleague/<id>`` branches are reaped
    (:func:`~colleague.handoff.reap_chain_intermediates` — ancestors of the
    kept final branch only, so a degraded-base episode's unique work is never
    destroyed; artifacts keep the evidence). A HALTED chain never reaches
    this function — every branch is left for the operator (the WIP rule).
    """
    final_branch = episode_branches[-1]
    # ``pr_body`` (#340 b3): the gate-deferral warning rides the PR body so the
    # human reviewer at gate 3 sees it; None keeps the --fill body byte-identical.
    outcome = chain_handoff_finalize(
        repo,
        result.task_id,
        final_branch,
        instruction=instruction,
        open_pr=open_pr,
        base_branch=base,
        body=pr_body,
    )
    result.branch = outcome.branch
    if outcome.pr_url:
        result.pr_url = outcome.pr_url
    if outcome.tip_sha:
        result.tip_sha = outcome.tip_sha
    if outcome.note:
        emit_diagnostic(f"chain handoff: {outcome.note}")
    artifact_path = write(result, artifact_dir(repo))
    reaped = reap_chain_intermediates(repo, episode_branches[:-1], keep=final_branch)
    reaped_refs = [r["ref"] for r in reaped if r["action"] == "reaped"]
    if reaped_refs:
        emit_diagnostic(
            f"chain: reaped {len(reaped_refs)} intermediate branch(es): " + ", ".join(reaped_refs)
        )
    return artifact_path


def _chain_progress(
    repo: Path,
    result: TaskResult,
    state,
    *,
    read_only: bool,
    prior_ref: str,
    episode_branch: str,
) -> bool | None:
    """The no-progress guard's evidence for one episode (c22) — deterministic.

    Feeds :func:`colleague.chain.episode_progressed` exactly two signals:

    - ``new_commits`` — ``git rev-list --count <prior_ref>..<episode_branch>``
      (:func:`~colleague.handoff.commits_ahead`), where ``prior_ref`` is the
      prior episode's branch (or the chain-start HEAD sha for episode 1); a
      budget-exhausted episode's WIP commit (#222) counts here.
    - ``new_evidence`` — :meth:`~colleague.chain.ChainState.record_episode`'s
      verdict: a changed-file path from this episode's artifact that no prior
      episode reported.

    ``record_episode`` is called for EVERY episode (it also keeps the chain's
    episode ledger). A read-only role returns ``None`` — commits and changed
    files are structurally impossible for it, so the c22 evidence inputs
    cannot apply; the episode cap bounds a read-only chain instead.
    """
    new_evidence = state.record_episode(result.task_id, result.changed_files)
    if read_only:
        return None
    new_commits = commits_ahead(repo, prior_ref, episode_branch)
    # Lazy import mirrors _chain_should_start_next (opt-in chain path).
    from colleague import chain as chainmod

    return chainmod.episode_progressed(new_commits=new_commits, new_evidence=new_evidence)


def _announce_episode_transition(
    repo: Path, prior_id: str, next_id: str, state, watch: bool
) -> None:
    """Announce one chain hop (t6) — sink line + the flight transition marker.

    Extracted from :func:`execute_work_chain` for the S3776 budget. The
    announcement rides the #38 progress channel; the marker lands on the PRIOR
    episode's flight feed (type="episode-transition", best-effort, watch-gated
    like every flight write) so a pilot following episode 1 can locate every
    later episode. Announcement text and marker intent are the same string.
    """
    announcement = flight.transition_announcement(prior_id, state.episode_count + 1, state.cap)
    emit_diagnostic(f"chain: {announcement}")
    if watch:
        flight.append_episode_transition(
            repo,
            prior_id,
            next_task_id=next_id,
            episode_index=state.episode_count + 1,
            cap=state.cap,
        )


def _resolve_deferred_branch(repo: Path | None, task_id: str) -> str | None:
    """A deferred episode's WIP branch, read from its own artifact (best-effort).

    An INHERITED deferred id — a chain resumed via ``--continue`` carries the
    cut run's ``deferred_gate_episodes`` forward (``ChainView.accumulate``) —
    has no entry in the resumed invocation's id→branch map; its branch lives
    only on the episode's persisted artifact (``branch``, recorded when the
    #222 WIP sweep preserved a chained episode's work — see
    :func:`_preserve_non_ok_wip`). Any failure — no repo threaded, artifact
    gone, corrupt JSON, a null field (a pre-fix or no-WIP episode) — returns
    ``None``; the caller renders the explicit unresolved marker instead, never
    a silently shorter branch list (Qodo, PR #345).
    """
    if repo is None:
        return None
    path = find_artifact(repo, task_id)
    if path is None:
        return None
    try:
        branch = json.loads(path.read_text(encoding="utf-8")).get("branch")
    except (OSError, json.JSONDecodeError):
        return None
    return branch if isinstance(branch, str) and branch else None


def _emit_chain_outcome(
    verdict,
    state,
    *,
    completed: bool,
    branches: list[str],
    deferred: tuple[str, ...] = (),
    repo: Path | None = None,
) -> None:
    """The chain's terminal diagnostics (extracted for the S3776 budget).

    ``deferred`` is the chain's accumulated deferred-gate episode ids
    (``ChainView.deferred_gate_episodes``, the #341 typed record — never
    parsed out of ``capacity_warning``). A HALTED chain names the deferring
    episodes and their kept WIP branches (#341: the per-episode note alone
    left ungated WIP silent at the outcome level); a deferred id the current
    invocation didn't run (a ``--continue`` resumed chain inherits the cut
    run's deferrals) resolves its branch from the episode's own artifact via
    *repo* (optional — absent keeps other callers working), and an id still
    unresolved is marked ``(branch not resolved)`` explicitly — the line never
    silently claims the branch list is complete when it is not (Qodo,
    PR #345). A COMPLETED chain warns only when the FINAL episode deferred —
    the one ok-finish + declared fill-line handoff shape whose handoff fires
    ungated (#340 b1); every other completed chain re-gated the union on its
    final episode, so it renders byte-identically to today.
    """
    detail = f": {verdict.detail}" if verdict.detail else ""
    emit_diagnostic(
        f"chain: {'completed' if completed else 'halted'} after "
        f"{state.episode_count} episode(s) — {verdict.reason}{detail}"
    )
    if not completed and branches:
        emit_diagnostic("chain: episode branches kept (WIP): " + ", ".join(branches))
    if not deferred:
        return
    if completed:
        final_id = state.episode_ids[-1] if state.episode_ids else ""
        if final_id and final_id in deferred:
            emit_diagnostic(
                "chain: WARNING — chain completed and handed off with the final "
                f"episode's pre-finish gates deferred ({final_id}; ok-finish + "
                "declared fill-line handoff, #340)"
            )
        return
    id_to_branch = dict(zip(state.episode_ids, branches))
    named_branches = [
        id_to_branch.get(tid)
        or _resolve_deferred_branch(repo, tid)
        or f"{tid} (branch not resolved)"
        for tid in deferred
    ]
    emit_diagnostic(
        "chain: gates deferred on episode(s) "
        + ", ".join(deferred)
        + " — halted chain keeps ungated WIP on branch(es): "
        + ", ".join(named_branches)
    )


def _maybe_finalize_chain(
    repo: Path,
    result: TaskResult,
    branches: list[str],
    *,
    completed: bool,
    read_only: bool,
    chain_base: str,
    instruction: str,
    open_pr: bool,
    base: str,
    artifact_path: Path,
    pr_body: str | None = None,
) -> Path:
    """Finalize a COMPLETED chain once — or honestly decline to (extracted, S3776).

    Three declines, each deliberate: a HALTED chain never pushes (the operator
    may want the WIP); a read-only chain stays handoff-free (h21); and a
    completed chain that landed NO commits mirrors ``handoff()``'s "no changes
    to hand off" semantics — no push, no PR, no reap, one explicit diagnostic
    (Qodo, PR #333; ``commits_ahead`` degrades to 0 on any git error, which
    conservatively declines too). Returns the (possibly re-written) artifact
    path — unchanged on every decline.
    """
    if not completed or read_only or not branches:
        return artifact_path
    if commits_ahead(repo, chain_base, branches[-1]) <= 0:
        emit_diagnostic("chain: completed with no changes; no handoff performed")
        return artifact_path
    return _chain_finalize(
        repo,
        result,
        branches,
        instruction=instruction,
        open_pr=open_pr,
        base=base,
        pr_body=pr_body,
    )


def _chain_deferral_surfacing(
    result: TaskResult, completed: bool
) -> tuple[tuple[str, ...], str | None]:
    """The chain's gate-deferral surfacing inputs (#341/#340; extracted, S3776).

    ``deferred`` is the typed chain record — accumulated per episode by
    ``ChainView.accumulate`` off ``result.gates_deferred`` — that feeds the
    outcome line. ``pr_body`` is non-None only on the #340 corner (a COMPLETED
    chain whose FINAL episode deferred: ok-finish + declared fill-line
    handoff), so the warning rides the handoff PR body and the human reviewer
    at gate 3 sees the diff went ungated.
    """
    deferred = tuple(result.chain.deferred_gate_episodes) if result.chain else ()
    pr_body: str | None = None
    if completed and getattr(result, "gates_deferred", False):
        pr_body = (
            "WARNING: this chain completed via a declared fill-line "
            "finish-with-handoff, so the pre-finish gates (lint / coherence / "
            "test-integrity / affected-tests) were deferred on its final episode "
            "and this diff was handed off ungated (#340). Deferring episode(s): "
            + ", ".join(deferred)
            + "."
        )
    return deferred, pr_body


def execute_work_chain(
    *,
    repo: Path,
    engine_name: str,
    task: Task,
    open_pr: bool,
    base: str,
    config: EngineConfig,
    cap: int,
    allow_dirty: bool = False,
    command_name: str | None = None,
    display: "DisplayOptions | None" = None,
    progress_sink: "CockpitProgressSink | None" = None,
    mode: str | None = None,
    continued_from: str | None = None,
) -> tuple[TaskResult, Path]:
    """The ``--until-done`` episode chain loop (indefinite-run t5/t9).

    The single implementation of episode chaining, shared by BOTH fronts (the
    h11 ``execute_work`` precedent): :func:`_run_chain` adapts ``cmd_work``'s
    parsed argv onto it, and the interactive ``session``'s armed dispatch
    calls it directly (``_dispatch_work`` — same kwargs shape as its
    single-episode ``work_fn`` call, plus *cap*), so the session front can
    never fork the chain semantics. Returns the FINAL episode's
    ``(result, artifact_path)`` pair — the caller owns outcome emission
    (exit-code mapping for the CLI, the feed line for the session).

    Wraps :func:`execute_work`: each episode is an ordinary bounded work item
    with its own artifact; the chain decisions are pure ``colleague.chain``
    verdicts over the episode's persisted terminal facts. The loop owns:

    - **handoff-once** (c26): every episode dispatches with ``open_pr=False``
      (finality is unknowable before an episode runs), and a COMPLETED chain
      (ok-finish) performs the arming invocation's push/PR choice exactly once
      via :func:`_chain_finalize`, then reaps the intermediate branches. A
      HALTED chain (non-continuable exit, no progress, cap, continuation
      error) leaves every episode branch alone — the operator may want the
      WIP — and never pushes.
    - **verbatim inheritance** (c28/h23): every episode re-dispatches with the
      SAME resolved locals — ``engine``, ``config`` (resolved once in
      :func:`cmd_work`; mode profile applied once below), ``open_pr``,
      ``allow_dirty``, display knobs, attachments — never re-reading env or
      ``config.json`` mid-chain (the ``_CHILD_FLAG_TABLE`` background-child
      precedent, held as locals).
    - **tree carry** (c6): episode N+1's isolation worktree bases on episode
      N's ``colleague/<id>`` branch tip (``ChainEpisodeOptions.base_ref``);
      a missing/reaped tip degrades to HEAD with a recorded warning (h6).
    - **lineage + accounting** (c20): ``continued_from`` stamps episode-to-
      episode, and each episode's artifact carries the running
      :class:`~colleague.contract.ChainView` (sums of exact usage, h19).
      ``--continue`` combines: episode 1 is the continued task (dispatched at
      HEAD, exactly like an unchained ``--continue``), and a cut CHAINED
      run's accounting resumes via :func:`~colleague.artifact.read_chain_view`.

    A halted chain returns its last episode's honest result (#313 stays
    intact) — the CLI adapter maps it to the exit code (0 ok / 2 incomplete /
    1 error).
    """
    display = display or DisplayOptions()
    if progress_sink is not None and display.sink is None:
        # The session front still passes its sink positionally-adjacent; fold it
        # into the bundle execute_work reads (S107 — sink rides DisplayOptions).
        display = replace(display, sink=progress_sink)
    # c28: apply the mode profile ONCE at arming; every episode reuses this
    # resolved config verbatim (execute_work skips re-application when chained,
    # so a mid-chain overlay change is never re-read).
    config = _moded_config(config, mode, repo)
    attachments = task.attachments
    arming_instruction = task.instruction
    # Read-only chain semantics arm on the read-only ROLE or a read-only MODE
    # (explore/review): both produce commits structurally never, so the c22
    # commit-evidence guard cannot apply (progressed=None; the episode cap
    # bounds the chain) and the chain stays handoff-free (h21). Live-dogfood
    # catch (t12): a `--mode review --until-done` chain otherwise halts
    # 'no-progress' after episode 1 — the arc's own review chain proved it.
    read_only_chain = is_read_only(getattr(config, "role", None)) or mode in _READ_ONLY_MODES
    # Lazy import: the chain path is opt-in; keep work's import graph flat.
    from colleague import chain as chainmod

    # Config-plane arming (change-content consumption lane, t9): ONE
    # lifecycle for the WHOLE chain (h22 — an armed --until-done chain is
    # itself one top-level task), constructed + its WINDOW_BEFORE_EPISODE_1
    # run BEFORE episode 1 ever dispatches, then threaded to every episode
    # via ChainEpisodeOptions.config_plane below (never re-armed mid-chain).
    # A strict no-op (config_plane stays None) unless three-tier is armed
    # (config.worker is not None) — byte-identical to today either way.
    config_plane = _arm_config_plane(config, repo=repo, task=task, engine_name=engine_name)

    # --continue + --until-done: resume the cut run's chain accounting when it
    # carried a view (an ordinary cut run yields None → fresh accounting).
    prior_view = read_chain_view(repo, continued_from) if continued_from else None
    chain_base = head_sha(repo) or "HEAD"
    state = chainmod.ChainState(cap=cap)
    episode_task = task
    prior_branch: str | None = None
    episode_branches: list[str] = []
    # Cumulative changed-files union across episodes (#335, c22): each episode
    # sees every PRIOR episode's touched files, sorted+deduped, on
    # ``ChainEpisodeOptions.prior_changed`` — ``()`` on the first episode.
    changed_so_far: set[str] = set()

    while True:
        result, artifact_path = execute_work(
            repo=repo,
            engine_name=engine_name,
            task=episode_task,
            open_pr=False,  # c26: per-episode push/PR suppressed; see _chain_finalize
            allow_dirty=allow_dirty,
            isolate=True,
            base=base,
            config=config,
            command_name=command_name,
            display=display,
            mode=mode,
            continued_from=continued_from,
            chain=ChainEpisodeOptions(
                base_ref=prior_branch,
                prior_view=prior_view,
                prior_changed=tuple(sorted(changed_so_far)),
                config_plane=config_plane,
            ),
        )
        prior_view = result.chain
        changed_so_far |= set(result.changed_files)
        episode_branch = result.branch or branch_name(episode_task.id, episode_task.instruction)
        episode_branches.append(episode_branch)

        progressed = _chain_progress(
            repo,
            result,
            state,
            read_only=read_only_chain,
            prior_ref=prior_branch or chain_base,
            episode_branch=episode_branch,
        )
        seed, verdict = _chain_should_start_next(
            repo, result, state, progressed=progressed, watch=task.watch
        )
        if seed is None:
            break
        # Config-plane between-episode window (t9): the go-verdict path —
        # decided to continue, not yet dispatched episode N+1. Reviews the
        # JUST-FINISHED episode's terminal facts (episode_task/result, still
        # unreassigned at this point in the loop). A no-op unless three-tier
        # is armed (config_plane is None).
        if config_plane is not None:
            _run_between_episodes_window(
                config_plane,
                repo=repo,
                task=episode_task,
                result=result,
                config=config,
                engine_name=engine_name,
            )
        emit_diagnostic(
            f"chain: episode {state.episode_count} ({result.task_id}) exit "
            f"{verdict.reason!r} — continuing (episode {state.episode_count + 1})"
        )
        continued_from, seed_text = seed
        prior_branch = episode_branch
        episode_task = Task.new(
            str(repo),
            seed_text,
            engine=engine_name,
            attachments=list(attachments) if attachments else None,
        )
        # The flight arming resolved once for the arming invocation (c28).
        episode_task.watch = task.watch
        _announce_episode_transition(repo, result.task_id, episode_task.id, state, task.watch)

    completed = verdict.reason == chainmod.HALT_OK_FINISH
    deferred, pr_body = _chain_deferral_surfacing(result, completed)
    artifact_path = _maybe_finalize_chain(
        repo,
        result,
        episode_branches,
        completed=completed,
        read_only=read_only_chain,
        chain_base=chain_base,
        instruction=arming_instruction,
        open_pr=open_pr,
        base=base,
        artifact_path=artifact_path,
        pr_body=pr_body,
    )
    _emit_chain_outcome(
        verdict,
        state,
        completed=completed,
        branches=episode_branches,
        deferred=deferred,
        repo=repo,
    )
    return result, artifact_path


def _run_chain(
    args: argparse.Namespace,
    repo: Path,
    engine: str,
    config: EngineConfig,
    task: Task,
    *,
    command_name: str | None,
    mode: str | None,
) -> int:
    """``cmd_work``'s thin adapter onto :func:`execute_work_chain` (t5/t9).

    Unpacks the parsed argv (open-pr choice, display knobs, the resolved
    ``--continue`` lineage) onto the shared chain loop and maps the FINAL
    episode's result to the exit code via :func:`_emit_work_outcome`
    (0 ok / 2 incomplete / 1 error — a halted chain reports its last episode
    honestly, #313). The session front calls ``execute_work_chain`` directly,
    so the chain semantics live in exactly one place.
    """
    json_mode = bool(getattr(args, "json", False))
    cap, _ = _resolve_chain_arming(args, config)
    try:
        result, artifact_path = execute_work_chain(
            repo=repo,
            engine_name=engine,
            task=task,
            open_pr=not args.no_pr,
            base=args.base,
            config=config,
            cap=cap,
            allow_dirty=bool(getattr(args, "allow_dirty", False)),
            command_name=command_name,
            display=DisplayOptions(
                tui=getattr(args, "tui", None), tui_events=getattr(args, "tui_events", None)
            ),
            mode=mode,
            continued_from=getattr(args, "_continued_from_resolved", None),
        )
    except CliError as exc:
        # An episode crash halts the chain like a single run's failure —
        # branches stay (the operator may want the WIP); same --json
        # partial surface as cmd_work's unchained path.
        if json_mode and exc.result is not None:
            emit_result(exc.result.to_dict(), json_mode=True)
        raise
    return _emit_work_outcome(result, engine, artifact_path, json_mode)


# The forwardable ``work`` flags a background child inherits verbatim, in CLI
# order: ``(args attr, flag, kind)`` where kind "value" carries an argument and
# "bool" is a bare switch. max_steps / mode / tui / tui-events / json have
# non-uniform shapes and stay explicit in _background_child_argv.
_CHILD_FLAG_TABLE: tuple[tuple[str, str, str], ...] = (
    ("engine", "--engine", "value"),
    ("no_pr", "--no-pr", "bool"),
    ("allow_dirty", "--allow-dirty", "bool"),
    ("until_done", "--until-done", "bool"),
    ("no_lint", "--no-lint", "bool"),
    ("no_coherence", "--no-coherence", "bool"),
    ("no_affected_tests", "--no-affected-tests", "bool"),
    ("test", "--test", "value"),
    ("base", "--base", "value"),
    ("base_url", "--base-url", "value"),
    ("model", "--model", "value"),
    ("role", "--role", "value"),
    ("api_key", "--api-key", "value"),
)


def _child_tail_argv(args: argparse.Namespace) -> list[str]:
    """Non-uniform ``work`` child flags, in CLI order.

    These flags don't fit the ``_CHILD_FLAG_TABLE`` value/bool pattern — a
    tri-state (``--tui``/``--no-tui``) or a repeatable one (``--attach``) —
    so they're built here. Extracted from :func:`_background_child_argv` so
    that function stays under SonarCloud's cognitive-complexity threshold
    (S3776).
    """
    tail: list[str] = []
    if getattr(args, "max_steps", None) is not None:
        tail += ["--max-steps", str(args.max_steps)]
    # --max-episodes carries a value where 0 (explicit unlimited) is falsy, so
    # it rides here with the max_steps `is not None` idiom, not the flag table.
    if getattr(args, "max_episodes", None) is not None:
        tail += ["--max-episodes", str(args.max_episodes)]
    if getattr(args, "mode", None):
        tail += ["--mode", args.mode]
    tui = getattr(args, "tui", None)
    if tui is True:
        tail.append("--tui")
    elif tui is False:
        tail.append("--no-tui")
    if getattr(args, "tui_events", None):
        tail += ["--tui-events", args.tui_events]
    if getattr(args, "json", False):
        tail.append("--json")
    # Forward each --attach value (repeatable), resolved to an ABSOLUTE path here
    # in the parent: the child may run with a different cwd, and
    # media.validate_attachment() resolves a relative path against cwd, so a
    # relative --attach would silently miss (or hit the wrong file) in the
    # detached child. Without this the attachment was dropped entirely (Qodo).
    for attach_path in getattr(args, "attach", None) or []:
        tail += ["--attach", str(Path(attach_path).resolve())]
    return tail


def _background_child_argv(args: argparse.Namespace, repo: Path) -> list[str]:
    """Rebuild ``work``'s CLI argv for the detached background child (t12).

    The same invocation the parent received, minus ``--background`` (so the
    child runs the ordinary foreground path instead of forking again) and with
    ``--watch`` force-added (auto-arming the flight control plane — the
    detached run's only pilot interface, per spec R4). Built from the parsed
    ``args`` Namespace rather than raw ``sys.argv`` so it is correct whether
    ``work`` was invoked directly or reached via the legacy ``drive`` alias,
    and ``--repo`` always carries the fully resolved absolute path (not
    whatever relative string the caller typed) so the child is unambiguous
    about which repo it targets. Each ``--attach`` value is likewise forwarded
    as a resolved absolute path (not the table-driven flags below — repeatable,
    non-uniform shape) so a relative attachment path still resolves correctly
    against the child's own cwd.
    """
    argv: list[str] = ["work"]
    command_name = getattr(args, "command_name", None)
    if command_name:
        argv += ["--command", command_name]
    argv += list(getattr(args, "instruction", None) or [])
    argv += ["--repo", str(repo)]
    # Table-driven forwarding (order preserved from the CLI surface): "value"
    # appends flag + str(value) when truthy, "bool" appends the bare flag.
    for attr, flag, kind in _CHILD_FLAG_TABLE:
        value = getattr(args, attr, None)
        if kind == "bool":
            if value:
                argv.append(flag)
        elif value:
            argv += [flag, str(value)]
    # Non-uniform tail flags (tri-state --tui, repeatable --attach, etc.) live
    # in a helper so this function stays under the S3776 complexity threshold.
    argv += _child_tail_argv(args)
    # Force-arm the flight control plane: a detached run has no other pilot
    # interface, so --watch is not optional here (spec R4 — the flight feed +
    # 'colleague flight status/guide/stop' is the ONLY way to observe/steer it).
    argv.append("--watch")
    return argv


def _render_background(payload: dict) -> str:
    lines = [
        f"background: {payload['id']}",
        f"pid: {payload['pid']}",
        f"log_dir: {payload['log_dir']}",
        f"flight: {payload['flight'] or '(none)'}",
    ]
    if payload.get("flight"):
        lines.append(f"pilot: colleague flight status {payload['flight']} --repo <repo>")
    return "\n".join(lines)


def _cmd_work_background(args: argparse.Namespace, repo: Path, json_mode: bool) -> int:
    """Detach this work item as a background one-shot child (t12, spec R4 / h10).

    Pre-mints the handle id here (parent side), builds the child's argv (the
    same invocation minus ``--background``, with ``--watch`` force-added), and
    hands off to :func:`colleague.background.spawn_background` — a one-shot
    ``subprocess.Popen(start_new_session=True)`` re-invoking ``python -m
    colleague`` so the child always runs the exact package currently
    executing, never a stale PATH install. Returns immediately with the
    machine-readable start payload; the child runs the ordinary foreground
    work path (:func:`cmd_work` again, this time without ``--background``)
    start to finish entirely on its own — no polling, no daemon.
    """
    handle_id = background.new_handle_id()
    child_argv = _background_child_argv(args, repo)
    handle = background.spawn_background(
        repo,
        [sys.executable, "-m", "colleague", *child_argv],
        handle_id=handle_id,
        flight_id=handle_id,
    )
    payload = handle.to_dict()
    emit_result(payload if json_mode else _render_background(payload), json_mode=json_mode)
    return 0


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

    # Cortex/senses (t8): --cortex-only bypasses the senses front door for this run
    # (a one-shot `work` never runs text intake anyway — q1 — so this suppresses
    # the senses media bridge). A strict no-op when no senses model is resolved.
    if getattr(args, "cortex_only", False):
        config.senses = None

    # Mode validation (t3): a typo must fail loudly with the valid choices, not
    # silently no-op. Validated explicitly + early (the --algo idiom — a
    # value-carrying flag cannot take a parse-time choices= without colliding
    # with its signature-derived flag at App build time). Explicit CLI knobs
    # ride config.explicit_knobs (runtime-only, the role precedent) so the
    # profile never overwrites them.
    mode = _validated_mode(getattr(args, "mode", None))
    if args.max_steps is not None:
        config.explicit_knobs = frozenset({"max_steps"})

    _apply_lint_optout(args, config)
    _apply_coherence_optout(args, config)
    _apply_affected_tests_optout(args, config)

    command_name: str | None = getattr(args, "command_name", None)
    task = _build_task(args, repo, engine, config)

    # Background one-shot child (t12, spec R4 / h10): when this process IS the
    # detached child, COLLEAGUE_BACKGROUND_ID carries the handle id the parent
    # pre-minted, so the child's artifact/flight/logs are all findable from the
    # SAME id the parent printed in its start payload. A strict no-op for every
    # ordinary invocation — the env var is only ever set by
    # background.spawn_background, and only in the child's own environment.
    bg_id = os.environ.get(background.BACKGROUND_ID_ENV)
    if bg_id:
        task.id = bg_id

    if getattr(args, "background", False):
        # Detach and return immediately — never runs the loop in this process.
        return _cmd_work_background(args, repo, json_mode)

    _arm_watch(args, task, config)

    # Episode chaining (indefinite-run t5): an armed run (--until-done, or
    # until_done via COLLEAGUE_UNTIL_DONE / config.json — c21) dispatches
    # through the chain loop, which owns handoff-once (c26) and verbatim
    # inheritance (c28). An unarmed run takes the single-episode path below,
    # byte-identical to today.
    _, chain_armed = _resolve_chain_arming(args, config)
    if chain_armed:
        return _run_chain(
            args, repo, engine, config, task, command_name=command_name or None, mode=mode
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
            display=DisplayOptions(
                tui=getattr(args, "tui", None),
                tui_events=getattr(args, "tui_events", None),
            ),
            mode=mode,
            continued_from=getattr(args, "_continued_from_resolved", None),
        )
    except CliError as exc:
        # On a partial-bearing failure, surface the preserved partial TaskResult to
        # stdout (--json only) so machine consumers (e.g. ask-colleague.sh) can parse it.
        # The diagnostic stays on stderr and the exit code stays non-zero — both are
        # handled by the _dispatch layer that catches this re-raise.
        if json_mode and exc.result is not None:
            emit_result(exc.result.to_dict(), json_mode=True)
        raise

    return _emit_work_outcome(result, engine, artifact_path, json_mode)


def _arm_watch(args: argparse.Namespace, task, config) -> None:
    """Arm the flight control plane, armed by default (#307).

    Precedence (flag > env > config > default-on): an explicit ``--no-watch``
    disarms; an explicit ``--watch`` arms; otherwise ``config.watch`` (which
    resolved ``COLLEAGUE_WATCH`` > ``.colleague/config.json`` ``{watch}`` >
    default-on) decides. Extracted from :func:`cmd_work` to keep its cognitive
    complexity in budget (S3776).
    """
    explicit_watch = bool(getattr(args, "watch", False))
    if bool(getattr(args, "no_watch", False)):
        task.watch = False
        return
    watch = True if explicit_watch else bool(getattr(config, "watch", True))
    if not watch:
        task.watch = False
        return
    if flight.depth_exceeded():
        # Default-on watch must NEVER break a nested run: degrade to no-watch
        # silently when watch was DEFAULTED. Only an EXPLICIT --watch at depth is a
        # hard error (the operator asked for something that can't nest).
        if explicit_watch:
            raise CliError(
                EXIT_USER_ERROR,
                "flight depth cap reached — refusing to nest another sub-flight",
                "a flight may pilot a sub-flight, but not unbounded recursion",
            )
        task.watch = False
        return
    task.watch = True
    os.environ.update(flight.child_depth_env())
    # The flight-attach handle is emitted from execute_work, AFTER its guards
    # (dirty tree, unknown engine, ...), so a refused run never prints a stray
    # handle before its "error:" line (#307 armed-by-default made every early
    # error hit that ordering). See execute_work's `if task.watch and ...` block.


def _emit_work_outcome(result, engine: str, artifact_path, json_mode: bool) -> int:
    """Surface warnings + the result, and map status to the exit code (extracted
    from :func:`cmd_work` to keep its cognitive complexity in budget — S3776)."""
    # Surface the warn-only "too big for one repo" capacity warning (#156) on stderr
    # — a diagnostic, so it never pollutes the stdout result stream and reaches the
    # caller (agent or human) in both text and --json modes; it is also recorded in
    # the artifact (result.to_dict()).
    if result.capacity_warning:
        emit_diagnostic(f"capacity warning: {result.capacity_warning}")

    _surface_lint_residual(result)
    _surface_coherence_hints(result)

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
    # #268 ask 4: the timeout surface is documented where the operator looks for
    # it — `colleague work --help` — not only in the error string after a loss.
    p.epilog = (
        "env knobs: COLLEAGUE_TIMEOUT — seconds per model turn (default 120; a "
        "mid-flight turn timeout or armed backpressure raises it once, bounded "
        "x2, before the flight is failed); COLLEAGUE_CONTEXT_BUDGET — tokens "
        "per turn window (default 48000, sized to the reference rig's served "
        "64K window). `colleague doctor` reports the effective values."
    )
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
    p.add_argument(
        "--continue",
        "-c",
        dest="continue_ref",
        metavar="ID|last",
        default=None,
        help=(
            "Resume a cut work item (#167): seed this run from its persisted "
            "artifact's continuation record. 'last' resolves the most recent "
            "work item; a completed (ok) item is refused. Positional text "
            "becomes extra guidance appended after the seed."
        ),
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
        "--no-coherence",
        action="store_true",
        help=(
            "Skip the coherence pre-finish gate (by default changed .md files "
            "are scored via the coherence CLI, advisory/warn-only; this opts "
            'out). Also via COLLEAGUE_COHERENCE=0 or config.json {"coherence": false}.'
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
        "--until-done",
        action="store_true",
        dest="until_done",
        help=(
            "Chain bounded episodes until the task finishes ok (or the chain halts: "
            "a non-continuable exit, no progress, or the episode cap). Each episode "
            "is an ordinary work item with its own artifact; push/PR happens ONCE, "
            "at chain end. Also via COLLEAGUE_UNTIL_DONE=1 or .colleague/config.json "
            '{"until_done": true}.'
        ),
    )
    p.add_argument(
        "--max-episodes",
        type=int,
        default=None,
        dest="max_episodes",
        help=(
            "Episode cap for an armed --until-done chain (default 5; 0 = unlimited). "
            'Also via COLLEAGUE_MAX_EPISODES or .colleague/config.json {"max_episodes": N}.'
        ),
    )
    p.add_argument(
        "--cortex-only",
        action="store_true",
        help=(
            "Bypass the senses front door for this run (suppresses the senses media "
            "bridge). A strict no-op when no senses model is resolved. (cortex/senses arc)"
        ),
    )
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
            "this work item (see 'colleague flight'). Armed by default (#307); "
            "this flag is the explicit alias."
        ),
    )
    p.add_argument(
        "--no-watch",
        action="store_true",
        help=(
            "Do NOT arm the flight-control plane (opt out of the #307 default). "
            "Also settable via COLLEAGUE_WATCH=0 or .colleague/config.json "
            '{"watch": false}.'
        ),
    )
    p.add_argument(
        "--background",
        action="store_true",
        help=(
            "Detach this work item as a one-shot background child (no daemon, "
            "no polling) and return immediately with a JSON start payload "
            "{background, id, pid, log_dir, flight}. Auto-arms --watch so the "
            "detached run is pilotable via 'colleague flight'; a crashed "
            "background run's residue is reaped by 'colleague clean'."
        ),
    )
    p.add_argument(
        "--attach",
        action="append",
        metavar="PATH",
        default=None,
        help=(
            "Attach a media file (image or audio) to the work item. "
            "May be repeated. The file is validated (must exist, known extension) "
            "and passed to the backend as an attachment."
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

"""``colleague drive`` — assign a repo task to a coder engine.

The headline verb: select an engine (a discovered wheel), run the bounded
agentic loop against a repo, write the result artifact, and hand the change off
as a branch + PR. The *same* invocation works for every backend — only
``--engine`` changes (honesty conditions h11/h12).

A failed drive still writes a result artifact (``status=error``) before exiting
non-zero, so a crash never leaves an empty run report (h5).

``--command NAME`` (and optional positional args) expands a saved command
template into the Task via :func:`colleague.commands.expand_command` and
records the originating command name on the result (``TaskResult.command``).
Exactly one of a positional instruction or ``--command`` must be supplied.

:func:`execute_drive` is the shared helper that performs the drive orchestration
(load engine → run loop → handoff → write artifact) and returns the
``(TaskResult, artifact_path)`` pair.  Both ``cmd_drive`` and the ``session``
palette delegate to it so the drive path is never duplicated (honesty h11).
"""

from __future__ import annotations

import argparse
from contextlib import suppress
from pathlib import Path

from colleague import registry
from colleague.artifact import artifact_dir, failed_result, write
from colleague.cli._banner import emit_banner
from colleague.cli._commands._tui_sink import CockpitProgressSink, build_progress
from colleague.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_diagnostic, emit_result
from colleague.commands import CommandError, expand_command
from colleague.config import EngineConfig, resolve_engine
from colleague.contract import OK, Task, TaskResult
from colleague.feedback import set_last_drive
from colleague.handoff import HandoffError, handoff, untracked_snapshot
from colleague.subagents import make_batch_spawn, make_spawn
from colleague.telemetry import Telemetry, load_telemetry


def _step_progress(step_index: int, tool: str, target: str, ok: bool) -> None:
    """Per-step progress line to stderr during a drive (#38).

    stdout carries only the result stream (the ``--json`` ``TaskResult``), so a
    progress line here never pollutes the parseable output — it is emitted in all
    modes. Wired onto :class:`~colleague.config.EngineConfig` by
    :func:`execute_drive`, so both ``drive`` and ``session`` (and every backend)
    report progress identically.
    """
    detail = f" {target}" if target else ""
    emit_diagnostic(f"step {step_index}: {tool}{detail} [{'ok' if ok else 'err'}]")


def _repo_relative(repo: Path, path_str: str) -> str | None:
    """Repo-relative POSIX path for *path_str* if it lives inside *repo*, else None.

    Used to recognise a `--tui-events` stream written into the repo so the handoff
    can treat it as baseline (telemetry) rather than drive-produced output.
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
) -> None:
    """Branch/commit (+push/PR) a successful drive; fold the outcome onto *result*.

    A :class:`~colleague.handoff.HandoffError` is non-fatal — the drive still
    succeeded, so it is surfaced as a diagnostic and the result keeps its local
    state. Extracted from :func:`execute_drive` to keep that function's control
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


def execute_drive(
    *,
    repo: Path,
    engine_name: str,
    task: Task,
    open_pr: bool,
    base: str,
    config: EngineConfig,
    command_name: str | None = None,
    tui: bool | None = None,
    tui_events: str | None = None,
    progress_sink: "CockpitProgressSink | None" = None,
) -> tuple[TaskResult, Path]:
    """Shared drive orchestration: load engine → loop → handoff → write artifact.

    This helper is the single implementation of the drive path.  Both
    :func:`cmd_drive` and the ``session`` palette call it so the loop, hooks,
    and artifact logic are never duplicated (honesty condition h11).

    Parameters
    ----------
    repo:
        Absolute path to the target repository.
    engine_name:
        Name of the engine wheel to load (e.g. ``"mock"``).
    task:
        A fully constructed :class:`~colleague.contract.Task`.
    open_pr:
        When ``True`` attempt to push and open a PR; ``False`` commits locally only.
    base:
        Base branch for the PR (passed to :func:`~colleague.handoff.handoff`).
    config:
        Resolved :class:`~colleague.config.EngineConfig`.
    command_name:
        Originating command-template name (``None`` for a plain instruction).
        Recorded on the result before *every* artifact write — including the
        failure path — so the run report never loses the origin (R5 / c12).
    tui:
        Live-cockpit activation (#74 A1): ``True`` forces it on, ``False`` off,
        ``None`` (default) is auto — on when stderr is an interactive TTY. When
        off, the plain ``step N:`` stderr sink is used unchanged.
    tui_events:
        Optional path (#74 A3): when set, one `DriveStep` JSONL line is appended
        per step as the drive runs, so an agent can follow / `tui replay` it.
    progress_sink:
        Optional caller-supplied cockpit sink (#74 A2): the interactive ``session``
        passes a sink bound to its own `CockpitState` + frame-writer so a drive
        renders into the session's one shared screen. Replaces the auto-constructed
        cockpit; ``None`` (the default) preserves the byte-identical `drive` path.

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
    try:
        engine = registry.load(engine_name)
    except registry.UnknownEngine as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "list engines with: colleague wheels list"
        ) from exc

    # Telemetry: the root span wraps engine.drive() + handoff() + the artifact write, so
    # the loop's tool spans nest under it. A no-op unless telemetry is enabled.
    # The same shared path serves `drive` and `session`, so both are instrumented.
    telemetry = load_telemetry()
    try:
        with telemetry.drive_span(
            task_id=task.id,
            engine=engine_name,
            model=config.model,
            max_steps=config.max_steps,
        ) as drive_span:
            trace_id = telemetry.trace_id_hex()
            if trace_id:
                emit_diagnostic(f"trace: {trace_id}")

            # Snapshot untracked files BEFORE the drive so the handoff stages only
            # the files the drive itself produces — never pre-existing operator
            # work-in-progress (#39).
            baseline_untracked = untracked_snapshot(repo)
            # A live `--tui-events` stream written into the repo is harness
            # telemetry, not drive output: register it as baseline so the handoff
            # never sweeps it into the drive branch (after which the branch-restore
            # would delete it). Paths outside the repo / under .colleague/ are
            # already excluded by the handoff (#74 A3).
            if tui_events:
                ev_rel = _repo_relative(repo, tui_events)
                if ev_rel is not None:
                    baseline_untracked.append(ev_rel)

            # Per-step progress (#38) — wired here so both `drive` and `session`,
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
            # so both `drive` and `session`, and every backend (which forwards
            # `config.subagent_spawn`), can delegate identically. depth defaults to
            # 1; the launcher binds each child to depth+1, so recursion is bounded
            # by MAX_SUBAGENT_DEPTH.
            config.subagent_spawn = make_spawn(task.repo_path, config, task.engine)
            config.subagent_batch_spawn = make_batch_spawn(task.repo_path, config, task.engine)
            try:
                result = engine.drive(task, config)
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
                    result = failed_result(task.id, f"{type(exc).__name__}: {exc}")
                    original = exc
                    # No partial result -> the trace is empty; don't claim otherwise.
                    artifact_note = "a result artifact was still written"
                result.command = command_name
                drive_span.set(status=result.status)
                write(result, artifact_dir(repo))
                # The drive happened (even if it failed) — record it as 'last' so
                # `feedback last` can still grade it. Best-effort: never mask the error.
                with suppress(Exception):
                    set_last_drive(repo, result.task_id)
                raise CliError(
                    EXIT_ENV_ERROR,
                    f"engine '{engine_name}' failed: {original}",
                    f"check the engine config / vLLM server; {artifact_note}",
                    result=result if isinstance(partial, TaskResult) else None,
                ) from exc
            finally:
                # Close the live cockpit on every exit path (success or engine
                # failure) so the final frame shows the drive as finished. Best-
                # effort: a render glitch must never mask the real outcome.
                if cockpit_sink is not None:
                    with suppress(Exception):
                        cockpit_sink.close()

            if result.status == OK:
                _handoff_result(
                    repo=repo,
                    task=task,
                    result=result,
                    baseline_untracked=baseline_untracked,
                    open_pr=open_pr,
                    base=base,
                    telemetry=telemetry,
                )

            drive_span.set(
                status=result.status,
                step_count=len(result.steps),
                pr_url=result.pr_url,
            )
            result.command = command_name
            artifact_path = write(result, artifact_dir(repo))
            # Record this as the repo's most recent drive so `colleague feedback
            # last` resolves to it. Best-effort: a pointer write must never break
            # a successful drive.
            with suppress(Exception):
                set_last_drive(repo, result.task_id)
            return result, artifact_path
    finally:
        telemetry.flush()


def _build_task(args: argparse.Namespace, repo: Path, engine: str, config: EngineConfig) -> Task:
    """Resolve the positional tokens into a :class:`Task` (instruction or --command).

    ``args.instruction`` is a list (nargs="*"). With ``--command`` set the tokens
    are template arguments (expanded via :func:`expand_command`); without it they
    are a plain instruction. Raises :class:`CliError` when neither is supplied or
    a template fails to expand. Extracted from :func:`cmd_drive` to keep that
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
            "run 'colleague drive --help' to see usage",
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


def cmd_drive(args: argparse.Namespace) -> int:
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
    # A bare drive never silently falls through to the no-op mock (#53).
    engine = resolve_engine(args.engine)

    config = EngineConfig.resolve(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_steps=args.max_steps,
    )

    command_name: str | None = getattr(args, "command_name", None)
    task = _build_task(args, repo, engine, config)

    # Delegate the full drive orchestration to the shared helper, which records
    # the originating command on the result before every artifact write.
    try:
        result, artifact_path = execute_drive(
            repo=repo,
            engine_name=engine,
            task=task,
            open_pr=not args.no_pr,
            base=args.base,
            config=config,
            command_name=command_name or None,
            tui=getattr(args, "tui", None),
            tui_events=getattr(args, "tui_events", None),
        )
    except CliError as exc:
        # On a partial-bearing failure, surface the preserved partial TaskResult to
        # stdout (--json only) so machine consumers (e.g. outsource.sh) can parse it.
        # The diagnostic stays on stderr and the exit code stays non-zero — both are
        # handled by the _dispatch layer that catches this re-raise.
        if json_mode and exc.result is not None:
            emit_result(exc.result.to_dict(), json_mode=True)
        raise

    if json_mode:
        emit_result(result.to_dict(), json_mode=True)
    else:
        emit_result(_render(result, engine, artifact_path), json_mode=False)
    return 0 if result.status == OK else 1


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "drive",
        help=(
            "Drive toward a goal: work autonomously on a request or instruction "
            "through a coder engine, then hand off the result."
        ),
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
        help="Expand a saved command template and drive it (mutually exclusive with instruction).",
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Engine wheel to drive (default: COLLEAGUE_ENGINE or vllm-openai).",
    )
    p.add_argument("--no-pr", action="store_true", help="Commit locally; do not push or open a PR.")
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument(
        "--tui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render a live cockpit (with popups) on stderr during the drive. "
            "Default: auto — on when stderr is an interactive TTY. "
            "Use --no-tui to force the plain 'step N:' lines."
        ),
    )
    p.add_argument(
        "--tui-events",
        metavar="PATH",
        default=None,
        help="Append a live DriveStep JSONL stream to PATH (replay with 'tui replay').",
    )
    p.add_argument("--json", action="store_true", help="Emit the result as structured JSON.")
    p.set_defaults(func=cmd_drive)

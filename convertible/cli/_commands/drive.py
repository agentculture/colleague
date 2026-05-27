"""``convertible drive`` — assign a repo task to a coder engine.

The headline verb: select an engine (a discovered wheel), run the bounded
agentic loop against a repo, write the result artifact, and hand the change off
as a branch + PR. The *same* invocation works for every engine — only
``--engine`` changes (honesty conditions h11/h12).

A failed drive still writes a result artifact (``status=error``) before exiting
non-zero, so a crash never leaves an empty dashboard (h5).

``--command NAME`` (and optional positional args) expands a saved command
template into the Task via :func:`convertible.commands.expand_command` and
records the originating command name on the result (``TaskResult.command``).
Exactly one of a positional instruction or ``--command`` must be supplied.

:func:`execute_drive` is the shared helper that performs the drive orchestration
(load engine → run loop → handoff → write artifact) and returns the
``(TaskResult, artifact_path)`` pair.  Both ``cmd_drive`` and the ``session``
palette delegate to it so the drive path is never duplicated (honesty h11).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convertible import registry
from convertible.artifact import artifact_dir, failed_result, write
from convertible.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from convertible.cli._output import emit_diagnostic, emit_result
from convertible.commands import CommandError, expand_command
from convertible.config import EngineConfig
from convertible.contract import OK, Task, TaskResult
from convertible.handoff import HandoffError, handoff


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


def execute_drive(
    *,
    repo: Path,
    engine_name: str,
    task: Task,
    open_pr: bool,
    base: str,
    config: EngineConfig,
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
        A fully constructed :class:`~convertible.contract.Task`.
    open_pr:
        When ``True`` attempt to push and open a PR; ``False`` commits locally only.
    base:
        Base branch for the PR (passed to :func:`~convertible.handoff.handoff`).
    config:
        Resolved :class:`~convertible.config.EngineConfig`.

    Returns
    -------
    tuple[TaskResult, Path]
        The task result and the path of the written artifact JSON.

    Raises
    ------
    :class:`~convertible.cli._errors.CliError`
        On unknown engine or engine-level failure (artifact is still written
        before the exception is raised — honesty h5).
    """
    try:
        engine = registry.load(engine_name)
    except registry.UnknownEngine as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "list engines with: convertible wheels list"
        ) from exc

    try:
        result = engine.drive(task, config)
    except Exception as exc:  # noqa: BLE001 - any failure still writes an artifact (h5)
        result = failed_result(task.id, f"{type(exc).__name__}: {exc}")
        write(result, artifact_dir(repo))
        raise CliError(
            EXIT_ENV_ERROR,
            f"engine '{engine_name}' failed: {exc}",
            "check the engine config / vLLM server; a result artifact was still written",
        ) from exc

    if result.status == OK:
        try:
            outcome = handoff(
                repo,
                task.id,
                instruction=task.instruction,
                open_pr=open_pr,
                base_branch=base,
            )
            result.branch = outcome.branch
            result.pr_url = outcome.pr_url
            if not result.changed_files:
                result.changed_files = outcome.changed_files
            if outcome.note:
                emit_diagnostic(f"handoff: {outcome.note}")
        except HandoffError as exc:
            emit_diagnostic(f"handoff skipped: {exc}")

    artifact_path = write(result, artifact_dir(repo))
    return result, artifact_path


def cmd_drive(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))

    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        raise CliError(
            EXIT_USER_ERROR,
            f"repo path is not a directory: {args.repo}",
            "pass --repo pointing at an existing repository",
        )

    # Resolve instruction vs. --command.
    # ``args.instruction`` is a list (nargs="*") — positional tokens.
    # When ``--command`` is supplied, positional tokens are template arguments.
    # When ``--command`` is absent, positional tokens are the plain instruction.
    positional_tokens: list[str] = getattr(args, "instruction", None) or []
    command_name: str | None = getattr(args, "command_name", None)

    has_command = bool(command_name)
    # A plain instruction requires at least one non-empty token.
    instruction_tokens: list[str] = positional_tokens if not has_command else []
    has_instruction = not has_command and bool(positional_tokens)

    if not has_instruction and not has_command:
        raise CliError(
            EXIT_USER_ERROR,
            "missing required argument: provide an instruction or --command <name>",
            "run 'convertible drive --help' to see usage",
        )

    config = EngineConfig.resolve(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_steps=args.max_steps,
    )

    if has_command:
        # Expand a saved command template.
        assert command_name is not None  # narrowing
        # Positional tokens are template arguments when --command is set.
        cmd_args = positional_tokens
        try:
            task = expand_command(
                repo,
                command_name,
                cmd_args,
                engine_default=args.engine,
            )
        except CommandError as exc:
            raise CliError(
                EXIT_USER_ERROR,
                str(exc),
                "list available commands with: convertible commands list --repo <path>",
            ) from exc
    else:
        # Plain instruction path (original behaviour).
        instruction = " ".join(instruction_tokens)
        task = Task.new(str(repo), instruction, engine=args.engine)

    # Delegate the full drive orchestration to the shared helper.
    result, artifact_path = execute_drive(
        repo=repo,
        engine_name=args.engine,
        task=task,
        open_pr=not args.no_pr,
        base=args.base,
        config=config,
    )

    # Record the originating command name (None for plain instructions).
    result.command = command_name if has_command else None
    # Re-write the artifact with the updated command field.
    artifact_path = write(result, artifact_dir(repo))

    if json_mode:
        emit_result(result.to_dict(), json_mode=True)
    else:
        emit_result(_render(result, args.engine, artifact_path), json_mode=False)
    return 0 if result.status == OK else 1


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "drive",
        help="Run a repo task through a coder engine and hand off the result.",
    )
    # ``instruction`` is now zero-or-more positional tokens (nargs="*") so
    # ``--command`` can be the sole input without argparse raising an error.
    p.add_argument(
        "instruction",
        nargs="*",
        help=(
            "What the engine should do in the repo.  "
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
    p.add_argument("--engine", default="mock", help="Engine wheel to drive (default: mock).")
    p.add_argument("--no-pr", action="store_true", help="Commit locally; do not push or open a PR.")
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument("--json", action="store_true", help="Emit the result as structured JSON.")
    p.set_defaults(func=cmd_drive)

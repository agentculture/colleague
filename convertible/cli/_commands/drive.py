"""``convertible drive`` — assign a repo task to a coder engine.

The headline verb: select an engine (a discovered wheel), run the bounded
agentic loop against a repo, write the result artifact, and hand the change off
as a branch + PR. The *same* invocation works for every engine — only
``--engine`` changes (honesty conditions h11/h12).

A failed drive still writes a result artifact (``status=error``) before exiting
non-zero, so a crash never leaves an empty dashboard (h5).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from convertible import registry
from convertible.artifact import artifact_dir, failed_result, write
from convertible.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from convertible.cli._output import emit_diagnostic, emit_result
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


def cmd_drive(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))

    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        raise CliError(
            EXIT_USER_ERROR,
            f"repo path is not a directory: {args.repo}",
            "pass --repo pointing at an existing repository",
        )

    try:
        engine = registry.load(args.engine)
    except registry.UnknownEngine as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "list engines with: convertible wheels list"
        ) from exc

    config = EngineConfig.resolve(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_steps=args.max_steps,
    )
    task = Task.new(str(repo), args.instruction, engine=args.engine)

    try:
        result = engine.drive(task, config)
    except Exception as exc:  # noqa: BLE001 - any engine/network failure still writes an artifact
        result = failed_result(task.id, f"{type(exc).__name__}: {exc}")
        write(result, artifact_dir(repo))
        raise CliError(
            EXIT_ENV_ERROR,
            f"engine '{args.engine}' failed: {exc}",
            "check the engine config / vLLM server; a result artifact was still written",
        ) from exc

    if result.status == OK and result.changed_files:
        try:
            outcome = handoff(
                repo,
                task.id,
                instruction=args.instruction,
                open_pr=not args.no_pr,
                base_branch=args.base,
            )
            result.branch = outcome.branch
            result.pr_url = outcome.pr_url
            if outcome.note:
                emit_diagnostic(f"handoff: {outcome.note}")
        except HandoffError as exc:
            emit_diagnostic(f"handoff skipped: {exc}")

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
    p.add_argument("instruction", help="What the engine should do in the repo.")
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

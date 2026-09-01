"""Task construction for ``colleague work`` (instruction / template / continue).

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague import media
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_diagnostic
from colleague.commands import CommandError, expand_command
from colleague.config import EngineConfig
from colleague.contract import Task


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
        return _build_continued_task(args, repo, engine, continue_ref, positional_tokens, config)

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
    config: EngineConfig | None,
) -> Task:
    """Seed a Task from a prior work item's persisted artifact (#167).

    The flag value is validated here explicitly — never via ``choices=``
    (agentfront#38: a value-carrying flag's choices are not enforced at App
    build time). Positional tokens, when present, are EXTRA operator guidance
    appended after the seed; ``--command`` cannot combine with ``--continue``
    (a template would fight the seed for the instruction). The resolved prior
    id rides ``args._continued_from_resolved`` so :func:`cmd_work` can thread
    it into :func:`execute_work` for the lineage stamp.

    ``config`` (the resolved :class:`~colleague.config.EngineConfig`) supplies
    the ``agents`` mode flag: when armed, the continuation seed rehydrates from
    the task ledger instead of the prose recap (Qodo, PR #414). ``None`` (a
    test double that never resolved a config) keeps the unarmed prose path.
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
    warnings: list[dict] = []
    try:
        prior_id, seed = resolve_continuation(
            repo,
            ref,
            agents_armed=bool(getattr(config, "agents", False)),
            warnings=warnings,
        )
    except ContinuationError as exc:
        raise CliError(
            EXIT_USER_ERROR,
            str(exc),
            "list recent work items with: colleague feedback list --repo <path>",
        ) from exc
    # Re-apply the prior run's recorded acting-seat rung (effort-v4 t8, c32).
    # An explicit --effort on THIS invocation wins: maybe_list_and_apply
    # already applied it before _build_task runs, so the re-apply stands down
    # entirely rather than clobbering it. Loud on mismatch (h19): the warning
    # is staged on config.continuation_warnings for the TaskResult stamp and
    # printed below with the other continuation diagnostics.
    if getattr(args, "effort", None) is None:
        from colleague.cli._commands._listing import reapply_recorded_effort

        reapply_recorded_effort(config, repo, prior_id, warnings=warnings)
    for warning in warnings:
        emit_diagnostic(f"continuation: {warning['detail']}")
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

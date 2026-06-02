"""``convertible session`` — foreground interactive palette over the drive path.

Opens a numbered command palette in the foreground, reads a line of input, and
dispatches the selection through the **same** drive path used by
``convertible drive`` (via :func:`~convertible.cli._commands.drive.execute_drive`).
The loop continues until the user enters a quit token (``q`` or an empty line).

The session is entirely foreground (no sockets, no daemons) and uses only
stdlib — stdin/stdout only (honesty h11 / c28).

Testability
-----------
:func:`run_session` accepts injectable ``input_fn`` and ``out`` callables so
tests can drive the palette without a real TTY.  The ``_drive_fn`` keyword
argument (default: :func:`execute_drive`) is a test seam used to capture
``TaskResult`` objects without re-implementing the drive path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional

from convertible.cli._banner import emit_banner
from convertible.cli._commands.drive import execute_drive as _default_drive
from convertible.cli._errors import CliError
from convertible.commands import CommandError, discover_commands, expand_command, load_command
from convertible.config import EngineConfig, resolve_engine
from convertible.contract import Task, TaskResult

# ---------------------------------------------------------------------------
# Types for the injectable seams
# ---------------------------------------------------------------------------

_DriveFn = Callable[
    ...,  # keyword-only: repo, engine_name, task, open_pr, base, config
    tuple[TaskResult, Path],
]

_QUIT_TOKENS = frozenset({"q", "quit", "exit", "bye"})


def _eprint(*args: object, **kwargs: object) -> None:
    """Default diagnostics sink — writes to stderr (kept off stdout)."""
    print(*args, file=sys.stderr, **kwargs)  # type: ignore[arg-type]


def _render_palette(
    commands: list[tuple[str, str]],  # (name, description)
    out: Callable[..., None],
    engine: str,
    repo: str,
) -> None:
    """Print the numbered command palette header."""
    out("")
    out(f"=== convertible session (engine: {engine}, repo: {repo}) ===")
    out("")
    if commands:
        out("Command templates:")
        for i, (name, desc) in enumerate(commands, start=1):
            if desc:
                out(f"  {i:2d}. {name} — {desc}")
            else:
                out(f"  {i:2d}. {name}")
        out("")
    out(
        "Type a number or template name to run a template, "
        "or type a free-text instruction (ad-hoc task), "
        "or 'q' / empty line to quit."
    )
    out(">>> ", end="")


def _render_result_summary(result: TaskResult, out: Callable[..., None]) -> None:
    """Print a one-line result summary after a drive completes."""
    changed = ", ".join(result.changed_files) if result.changed_files else "(none)"
    out(f"\n  status: {result.status}")
    out(f"  summary: {result.summary}")
    out(f"  changed files: {changed}")
    if result.branch:
        out(f"  branch: {result.branch}")
    out("")


def _read_line(input_fn: Optional[Iterator[str]]) -> Optional[str]:
    """Return the next input line, or None on EOF / StopIteration.

    With ``input_fn`` (test seam) the next item is pulled from the iterator;
    otherwise the real :func:`input` builtin reads from stdin.
    """
    if input_fn is not None:
        try:
            return next(input_fn)  # type: ignore[call-overload]
        except StopIteration:
            return None
    try:
        return input()
    except EOFError:
        return None


def _resolve_selection(
    line: str,
    palette: list[tuple[str, str]],
    discovered: dict[str, Path],
    repo: Path,
    engine_name: str,
    err: Callable[..., None],
    model: str | None = None,
) -> Optional[tuple[Task, Optional[str]]]:
    """Resolve a palette input line to a ``(task, command_name)`` pair.

    A bare number selects a palette entry; an exact name selects a command
    template; anything else is a free-text ad-hoc instruction (``command_name``
    is ``None``). Returns ``None`` when the line cannot be resolved (out-of-range
    number, or an unknown/erroring command) — the reason is already written to
    ``err`` and the caller should simply prompt again.
    """
    command_name: Optional[str] = None

    if line.isdigit():
        idx = int(line)
        if not 1 <= idx <= len(palette):
            err(f"  (no entry {idx} in the palette; type a number 1–{len(palette)})")
            return None
        command_name = palette[idx - 1][0]
    elif line in discovered:
        command_name = line
    else:
        # Free-text ad-hoc instruction — no originating command.
        return Task.new(str(repo), line, engine=engine_name), None

    # A command was selected (by number or name) — expand it into a Task.
    try:
        task = expand_command(repo, command_name, [], engine_default=engine_name, model=model)
    except CommandError as exc:
        err(f"  error: {exc}")
        return None
    return task, command_name


def _run_one(
    task: Task,
    command_name: Optional[str],
    *,
    repo: Path,
    engine_name: str,
    open_pr: bool,
    base: str,
    config: EngineConfig,
    drive_fn: _DriveFn,
    json_mode: bool,
    out: Callable[..., None],
    chrome: Callable[..., None],
    err: Callable[..., None],
) -> None:
    """Run one resolved task through the shared drive path and render the result.

    Errors go to ``err`` (stderr); the result goes to ``out`` as one JSON object
    in ``--json`` mode, else a human summary as interactive chrome. Passing
    ``command_name`` lets the drive helper persist the originating command in the
    artifact (R5 / c12).
    """
    try:
        result, _artifact_path = drive_fn(
            repo=repo,
            engine_name=engine_name,
            task=task,
            open_pr=open_pr,
            base=base,
            config=config,
            command_name=command_name,
            # Keep the plain `step N:` sink: the session's own palette chrome owns
            # the screen, so the auto-on-TTY live cockpit would clobber it. The
            # session cockpit is #74 A2 (a follow-up); force it off here.
            tui=False,
        )
    except CliError as exc:
        err(f"  error: {exc.message}")
        if exc.remediation:
            err(f"  hint: {exc.remediation}")
        return
    except Exception as exc:  # noqa: BLE001
        err(f"  error: {type(exc).__name__}: {exc}")
        return

    if json_mode:
        out(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        _render_result_summary(result, chrome)


def run_session(
    args: argparse.Namespace,
    *,
    input_fn: Optional[Iterator[str]] = None,
    out: Callable[..., None] = print,
    err: Optional[Callable[..., None]] = None,
    _drive_fn: _DriveFn = _default_drive,
) -> int:
    """Run the interactive session loop.

    Output contract: results go to ``out`` (stdout) and all diagnostics —
    errors, hints, and the interactive palette chrome in ``--json`` mode — go to
    ``err`` (stderr), so the two streams are never mixed. With ``--json`` set,
    ``out`` carries only one JSON object per completed drive.

    Parameters
    ----------
    args:
        Parsed CLI namespace (must carry ``repo``, ``engine``, ``base``,
        ``base_url``, ``model``, ``api_key``, ``max_steps``, ``json``; ``pr`` is
        read via ``getattr`` and defaults to ``False`` — commit-local, no PR).
    input_fn:
        Iterator of input lines (for testing).  When ``None`` the real
        :func:`input` builtin is used.
    out:
        Result sink (stdout).  Defaults to :func:`print`.
    err:
        Diagnostics sink (stderr).  Defaults to :func:`_eprint`.
    _drive_fn:
        Drive callable (test seam).  Defaults to :func:`execute_drive`.

    Returns
    -------
    int
        Exit code (always ``0`` — the session exits cleanly on quit/EOF).
    """
    repo = Path(args.repo).expanduser()
    # Resolve the engine like ``drive`` (explicit > CONVERTIBLE_ENGINE >
    # vllm-openai); a bare session never silently drives the no-op mock (#53).
    engine_name: str = resolve_engine(args.engine)
    # Session is a "talk + iterate" loop: by default it commits locally but does
    # NOT push/open a PR per typed line (#53). ``--pr`` opts back into handoff.
    open_pr: bool = bool(getattr(args, "pr", False))
    base: str = args.base
    json_mode: bool = bool(getattr(args, "json", False))
    if err is None:
        err = _eprint
    # Interactive chrome (palette, prompts, summaries) goes to stdout in normal
    # mode, but to stderr in --json mode so stdout carries only JSON results.
    chrome: Callable[..., None] = err if json_mode else out

    # Decorative startup banner — interactive TTY only, suppressed in --json (issue #15).
    # Printed once here (not in the loop) so it greets the session, not each prompt.
    emit_banner(err, json_mode=json_mode)

    config = EngineConfig.resolve(
        base_url=getattr(args, "base_url", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        max_steps=getattr(args, "max_steps", None),
    )

    # Discover templates once per session (they don't change mid-session).
    discovered = discover_commands(repo)
    # Build a sorted list of (name, description) for the palette.
    palette: list[tuple[str, str]] = []
    for name in sorted(discovered.keys()):
        cmd = load_command(discovered[name])
        palette.append((name, cmd.description))

    while True:
        _render_palette(palette, chrome, engine_name, str(repo))
        raw = _read_line(input_fn)

        # EOF or no input — treat as quit.
        if raw is None:
            chrome("\n(session ended)")
            break

        line = raw.strip()

        # Quit tokens.
        if line == "" or line.lower() in _QUIT_TOKENS:
            chrome("\n(session ended)")
            break

        # Resolve the line to a task (None → already reported; prompt again).
        resolved = _resolve_selection(
            line, palette, discovered, repo, engine_name, err, model=config.model
        )
        if resolved is None:
            continue
        task, command_name = resolved

        _run_one(
            task,
            command_name,
            repo=repo,
            engine_name=engine_name,
            open_pr=open_pr,
            base=base,
            config=config,
            drive_fn=_drive_fn,
            json_mode=json_mode,
            out=out,
            chrome=chrome,
            err=err,
        )

    return 0


def cmd_session(args: argparse.Namespace) -> int:
    """Handler for the ``convertible session`` verb."""
    return run_session(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "session",
        help=(
            "Open a foreground interactive palette: browse command templates, "
            "run them or type ad-hoc instructions, loop until quit."
        ),
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Engine wheel to drive (default: CONVERTIBLE_ENGINE or vllm-openai).",
    )
    p.add_argument(
        "--pr",
        action="store_true",
        help="Push and open a PR after each drive (default: commit locally only, no PR).",
    )
    p.add_argument("--base", default="main", help="Base branch for the PR (default: main).")
    p.add_argument("--base-url", default=None, help="Override the engine base URL.")
    p.add_argument("--model", default=None, help="Override the engine model name.")
    p.add_argument("--api-key", default=None, help="Override the engine API key.")
    p.add_argument("--max-steps", type=int, default=None, help="Override the loop step budget.")
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON result object per drive to stdout; palette chrome goes to stderr.",
    )
    p.set_defaults(func=cmd_session)

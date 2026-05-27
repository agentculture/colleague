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

from convertible.cli._commands.drive import execute_drive as _default_drive
from convertible.cli._errors import CliError
from convertible.commands import CommandError, discover_commands, expand_command, load_command
from convertible.config import EngineConfig
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
        Parsed CLI namespace (must carry ``repo``, ``engine``, ``no_pr``,
        ``base``, ``base_url``, ``model``, ``api_key``, ``max_steps``, ``json``).
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
    engine_name: str = args.engine
    open_pr: bool = not args.no_pr
    base: str = args.base
    json_mode: bool = bool(getattr(args, "json", False))
    if err is None:
        err = _eprint
    # Interactive chrome (palette, prompts, summaries) goes to stdout in normal
    # mode, but to stderr in --json mode so stdout carries only JSON results.
    chrome: Callable[..., None] = err if json_mode else out

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

    def _next_line() -> Optional[str]:
        """Return the next input line, or None on EOF / StopIteration."""
        if input_fn is not None:
            try:
                return next(input_fn)  # type: ignore[call-overload]
            except StopIteration:
                return None
        try:
            return input()
        except EOFError:
            return None

    while True:
        _render_palette(palette, chrome, engine_name, str(repo))
        raw = _next_line()

        # EOF or no input — treat as quit.
        if raw is None:
            chrome("\n(session ended)")
            break

        line = raw.strip()

        # Quit tokens.
        if line == "" or line.lower() in _QUIT_TOKENS:
            chrome("\n(session ended)")
            break

        # --- Resolve the selection ---
        task: Optional[Task] = None
        command_name: Optional[str] = None

        # Check if it's a number selecting a palette entry.
        if line.isdigit():
            idx = int(line)
            if 1 <= idx <= len(palette):
                command_name = palette[idx - 1][0]
            else:
                err(f"  (no entry {idx} in the palette; type a number 1–{len(palette)})")
                continue

        # Check if it matches a command name directly.
        elif line in discovered:
            command_name = line

        # Free-text ad-hoc instruction.
        else:
            task = Task.new(str(repo), line, engine=engine_name)

        if command_name is not None:
            try:
                task = expand_command(repo, command_name, [], engine_default=engine_name)
            except CommandError as exc:
                err(f"  error: {exc}")
                continue

        assert task is not None  # mypy narrowing

        # Run through the shared drive path. Passing command_name lets the
        # helper persist the originating command in the artifact (R5 / c12).
        try:
            result, _artifact_path = _drive_fn(
                repo=repo,
                engine_name=engine_name,
                task=task,
                open_pr=open_pr,
                base=base,
                config=config,
                command_name=command_name,
            )
        except CliError as exc:
            err(f"  error: {exc.message}")
            if exc.remediation:
                err(f"  hint: {exc.remediation}")
            continue
        except Exception as exc:  # noqa: BLE001
            err(f"  error: {type(exc).__name__}: {exc}")
            continue

        # Result → stdout: one JSON object per drive in --json mode, else a
        # human summary as interactive chrome.
        if json_mode:
            out(json.dumps(result.to_dict(), ensure_ascii=False))
        else:
            _render_result_summary(result, chrome)

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
    p.add_argument("--engine", default="mock", help="Engine wheel to drive (default: mock).")
    p.add_argument("--no-pr", action="store_true", help="Commit locally; do not push or open a PR.")
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

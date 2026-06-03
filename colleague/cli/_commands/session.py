"""``colleague session`` — the interactive cockpit over the drive path.

Opens a foreground interactive **cockpit**: it renders one
:class:`~colleague.tui.state.CockpitState` (a command palette + a running
conversation + popups), reads a line of input, and dispatches it through the
**same** drive path used by ``colleague drive``
(:func:`~colleague.cli._commands.drive.execute_drive`). The loop runs until a
quit token (``q`` / ``/quit`` / empty line / EOF).

Three render tiers of the one state (#74 A2), chosen automatically:

* **interactive (a colour TTY, not ``--json``)** — the dynamic ANSI cockpit
  (popups, redraw-in-place during a drive);
* **non-interactive (piped / captured)** — **Markdown** menus (the static but
  *full* agent-readable view), the default off a TTY;
* **``--json``** — stdout carries only the drive ``TaskResult`` (one JSON object
  each, preserving the machine contract); the Markdown cockpit renders to stderr
  as chrome. (The TAUI JSON mirror lives under ``colleague tui state``.)

Input is **line-based**. Plain text (a number / template name / free-text task)
runs a drive; a line starting with ``/`` is a **slash command** — the meta/system
namespace (introspection of existing nouns + live config actions).

The session is entirely foreground (no sockets, no daemons) and stdlib-only.

Testability
-----------
:func:`run_session` keeps the injectable ``input_fn`` / ``out`` / ``err`` /
``_drive_fn`` seams. ``_color`` forces the interactive-vs-static tier without a
real TTY.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional

from colleague import registry
from colleague.cli._banner import emit_banner
from colleague.cli._commands.drive import execute_drive as _default_drive
from colleague.cli._errors import CliError
from colleague.commands import CommandError, discover_commands, expand_command, load_command
from colleague.config import EngineConfig, resolve_engine
from colleague.contract import Task, TaskResult
from colleague.tui.colors import should_color
from colleague.tui.events import UserInput
from colleague.tui.from_drive import drive_step
from colleague.tui.reducer import reduce
from colleague.tui.render.ansi import render as _render_ansi
from colleague.tui.render.layout import detect_width
from colleague.tui.render.markdown import render_markdown as _render_markdown
from colleague.tui.state import CockpitState, Panel, PanelItem, Status
from colleague.tui.widgets.prompt_input import plain_prompt

# ---------------------------------------------------------------------------
# Types for the injectable seams
# ---------------------------------------------------------------------------

_DriveFn = Callable[..., tuple[TaskResult, Path]]

_QUIT_TOKENS = frozenset({"q", "quit", "exit", "bye"})
_CONVERSATION_PANEL_ID = "panel.conversation"
#: CSI clear-screen + cursor-home, so the dynamic ANSI view redraws in place.
_CLEAR_HOME = "\x1b[H\x1b[2J"
_PROMPT_HINT = "Type a number / template name / free-text task, or /help for commands."


def _eprint(*args: object, **kwargs: object) -> None:
    """Default diagnostics sink — writes to stderr (kept off stdout)."""
    print(*args, file=sys.stderr, **kwargs)  # type: ignore[arg-type]


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
    note: Callable[[str], None],
    model: str | None = None,
) -> Optional[tuple[Task, Optional[str]]]:
    """Resolve a palette input line to a ``(task, command_name)`` pair.

    A bare number selects a palette entry; an exact name selects a command
    template; anything else is a free-text ad-hoc instruction (``command_name``
    is ``None``). Returns ``None`` when the line cannot be resolved (out-of-range
    number, or an unknown/erroring command) — the reason is passed to *note* and
    the caller should simply prompt again.
    """
    command_name: Optional[str] = None

    if line.isdigit():
        idx = int(line)
        if not 1 <= idx <= len(palette):
            note(f"no entry {idx} in the palette; type a number 1–{len(palette)}")
            return None
        command_name = palette[idx - 1][0]
    elif line in discovered:
        command_name = line
    else:
        # Free-text ad-hoc instruction — no originating command.
        return Task.new(str(repo), line, engine=engine_name), None

    try:
        task = expand_command(repo, command_name, [], engine_default=engine_name, model=model)
    except CommandError as exc:
        note(f"error: {exc}")
        return None
    return task, command_name


class _DriveSink:
    """Progress sink for an in-session drive: fold each step into the session's
    one shared :class:`CockpitState` and (on the dynamic ANSI tier) redraw live."""

    def __init__(self, session: "_Session") -> None:
        self._session = session

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        sess = self._session
        sess.state = reduce(sess.state, drive_step(tool, target, ok))
        if sess.view == "ansi":
            sess.emit()  # live redraw per step

    def close(self) -> None:  # called by execute_drive on every exit path
        return None


class _Session:
    """Holds the interactive session's mutable state and renders one cockpit."""

    def __init__(
        self,
        *,
        repo: Path,
        engine_name: str,
        open_pr: bool,
        base: str,
        config: EngineConfig,
        json_mode: bool,
        view: str,
        out: Callable[..., None],
        err: Callable[..., None],
        drive_fn: _DriveFn,
    ) -> None:
        self.repo = repo
        self.engine_name = engine_name  # mutable via /engine
        self.open_pr = open_pr  # mutable via /pr
        self.base = base  # mutable via /base
        self.config = config  # .model mutable via /model
        self.json_mode = json_mode
        self.view = view  # "ansi" (dynamic) | "markdown" (static)
        self.out = out
        self.err = err
        # The rendered cockpit is interactive chrome: stdout normally, but stderr
        # in --json mode so stdout carries only the drive TaskResult(s).
        self.chrome = err if json_mode else out
        self.drive_fn = drive_fn

        self.discovered = discover_commands(repo)
        self.palette: list[tuple[str, str]] = [
            (name, load_command(self.discovered[name]).description)
            for name in sorted(self.discovered)
        ]
        self.state = self._initial_state()

    # ── state construction / mutation ────────────────────────────────────────

    def _initial_state(self) -> CockpitState:
        items = [
            PanelItem(
                id=f"command.{name}",
                label=(f"{name} — {desc}" if desc else name),
                status="available",
            )
            for name, desc in self.palette
        ]
        return CockpitState(
            panels=[
                Panel(id="commands", title="Commands", visible=True, items=items),
                Panel(
                    id=_CONVERSATION_PANEL_ID,
                    title="Session",
                    visible=True,
                    content_summary=_PROMPT_HINT,
                ),
            ],
            status=self._status(),
        )

    def _status(self) -> Status:
        pr = "PR" if self.open_pr else "local"
        engine, model = self.engine_name, self.config.model
        message = f"colleague session · engine {engine} · model {model} · {pr}"
        return Status(severity="info", message=message)

    def _log(self, text: str) -> None:
        """Append a line (or block) to the conversation via the pure reducer."""
        self.state = reduce(self.state, UserInput(text=text))

    def _error(self, text: str) -> None:
        """Report a diagnostic to stderr (agent-first convention); also fold it into
        the conversation in the dynamic ANSI tier so a redraw doesn't hide it."""
        self.err(text)
        if self.view == "ansi":
            self._log(text)

    def _refresh_status(self) -> None:
        self.state.status = self._status()

    # ── rendering (one path; three views) ────────────────────────────────────

    def _frame(self, *, include_prompt: bool = True) -> str:
        if self.view == "ansi":
            return _CLEAR_HOME + _render_ansi(
                self.state, width=detect_width(), include_prompt=include_prompt
            )
        return _render_markdown(self.state)

    def emit(self) -> None:
        self.chrome(self._frame())

    def _read_live_ansi(self) -> Optional[str]:
        """Live ANSI read: draw the frame (without its prompt line) and read input
        via ``input`` so the typed cursor anchors right on ``colleague ❯``.

        Used only on a real TTY (no injected ``input_fn``); tests and the static
        Markdown view go through :meth:`emit` + :func:`_read_line` instead.
        """
        sys.stdout.write(self._frame(include_prompt=False) + "\n")
        sys.stdout.flush()
        try:
            return input(plain_prompt())
        except EOFError:
            return None

    # ── the loop ─────────────────────────────────────────────────────────────

    def run(self, input_fn: Optional[Iterator[str]]) -> int:
        emit_banner(self.err, json_mode=self.json_mode)
        live_ansi = input_fn is None and self.view == "ansi"
        while True:
            if live_ansi:
                raw = self._read_live_ansi()
            else:
                self.emit()
                raw = _read_line(input_fn)
            if raw is None:
                break
            line = raw.strip()
            if line == "" or line.lower() in _QUIT_TOKENS:
                break
            if not self._handle(line):
                break
        self.err("(session ended)")
        return 0

    def _handle(self, line: str) -> bool:
        """Process one input line; return ``False`` to quit the session."""
        self._log(line)  # echo the input into the conversation
        if line.startswith("/"):
            return self._slash(line)
        self._drive_line(line)
        return True

    # ── slash commands ───────────────────────────────────────────────────────

    def _slash(self, line: str) -> bool:
        parts = line[1:].split()
        verb = parts[0].lower() if parts else ""
        rest = parts[1:]

        if verb in ("quit", "exit", "q"):
            return False
        if verb in ("help", ""):
            self._log(_HELP_TEXT)
            return True

        introspect = _INTROSPECT.get(verb)
        if introspect is not None:
            self._log(self._run_cli(*introspect(self)))
            return True

        action = _CONFIG_ACTIONS.get(verb)
        if action is not None:
            try:
                confirmation = action(self, rest)
            except ValueError as exc:
                self._error(str(exc))
                return True
            self._log(confirmation)
            self._refresh_status()
            return True

        self._error(f"unknown command: /{verb} — try /help")
        return True

    def _run_cli(self, *argv: str) -> str:
        """Run a colleague CLI noun in-process and capture its stdout.

        Reuses the real parser (so every noun's args/defaults are correct) and
        folds the output into the cockpit. No subprocess; errors are reported, not
        raised. ``argv`` is built from the fixed slash table (never user input), so
        ``parse_args`` does not error — a regression in a mapping is caught by the
        slash-command tests, not at runtime.
        """
        from colleague.cli import _build_parser

        parser = _build_parser()
        ns = parser.parse_args(list(argv))
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(io.StringIO()):
                ns.func(ns)
        except CliError as exc:
            return f"error: {exc.message}"
        # Slash output is advisory — report any noun failure, never crash the session.
        except Exception as exc:  # noqa: BLE001
            return f"error: {type(exc).__name__}: {exc}"
        return sink.getvalue().rstrip() or "(no output)"

    # ── drive ────────────────────────────────────────────────────────────────

    def _drive_line(self, line: str) -> None:
        resolved = _resolve_selection(
            line,
            self.palette,
            self.discovered,
            self.repo,
            self.engine_name,
            self._error,
            model=self.config.model,
        )
        if resolved is None:
            return
        task, command_name = resolved
        self._run_drive(task, command_name)

    def _run_drive(self, task: Task, command_name: Optional[str]) -> None:
        try:
            result, _artifact = self.drive_fn(
                repo=self.repo,
                engine_name=self.engine_name,
                task=task,
                open_pr=self.open_pr,
                base=self.base,
                config=self.config,
                command_name=command_name,
                progress_sink=_DriveSink(self),
            )
        except CliError as exc:
            hint = f" (hint: {exc.remediation})" if exc.remediation else ""
            self._error(f"error: {exc.message}{hint}")
            return
        except Exception as exc:  # noqa: BLE001
            self._error(f"error: {type(exc).__name__}: {exc}")
            return

        if self.json_mode:
            self.out(json.dumps(result.to_dict(), ensure_ascii=False))
        changed = ", ".join(result.changed_files) or "(none)"
        branch = f" → {result.branch}" if result.branch else ""
        self._log(f"{result.status}: {result.summary} [{changed}]{branch}")


# ---------------------------------------------------------------------------
# Slash-command tables
# ---------------------------------------------------------------------------

_HELP_TEXT = (
    "slash commands:\n"
    "  /help                 this list\n"
    "  /commands             list command templates\n"
    "  /skills               resolved skill docs\n"
    "  /agents               resolved AGENTS layers\n"
    "  /config               configuration readiness (doctor)\n"
    "  /engines              discovered backend plugins\n"
    "  /telemetry            telemetry configuration\n"
    "  /feedback             feedback for the last drive\n"
    "  /engine <name>        switch the engine for the next drive\n"
    "  /model <name>         switch the model\n"
    "  /base <branch>        set the PR base branch\n"
    "  /pr                   toggle push + open PR on each drive\n"
    "  /quit                 end the session\n"
    "plain text (a number / template name / free-text task) runs a drive."
)

# Read-only introspection: map a verb to the argv passed to the real CLI parser.
_INTROSPECT: dict[str, Callable[["_Session"], list[str]]] = {
    "commands": lambda s: ["commands", "list", "--repo", str(s.repo)],
    "skills": lambda s: ["skills", "list", "--repo", str(s.repo), "--model", s.config.model],
    "agents": lambda s: ["agents", "list", "--repo", str(s.repo), "--model", s.config.model],
    "config": lambda s: ["doctor"],
    "engines": lambda s: ["wheels", "list"],
    "telemetry": lambda s: ["telemetry", "status"],
    "feedback": lambda s: ["feedback", "show", "last", "--repo", str(s.repo)],
}


def _act_engine(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /engine <name>")
    name = rest[0]
    if name not in registry.names():
        raise ValueError(
            f"unknown engine '{name}'; available: {', '.join(registry.names()) or '(none)'}"
        )
    s.engine_name = name
    return f"engine → {name}"


def _act_model(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /model <name>")
    s.config.model = rest[0]
    return f"model → {rest[0]}"


def _act_base(s: "_Session", rest: list[str]) -> str:
    if not rest:
        raise ValueError("usage: /base <branch>")
    s.base = rest[0]
    return f"base branch → {rest[0]}"


def _act_pr(s: "_Session", rest: list[str]) -> str:
    s.open_pr = not s.open_pr
    return f"push + PR on each drive → {'on' if s.open_pr else 'off'}"


# Live config actions: map a verb to a mutating handler returning a confirmation.
_CONFIG_ACTIONS: dict[str, Callable[["_Session", list[str]], str]] = {
    "engine": _act_engine,
    "model": _act_model,
    "base": _act_base,
    "pr": _act_pr,
}


def _resolve_view(args: argparse.Namespace, *, color: bool) -> str:
    """Pick the render tier.

    ``--json`` renders the static Markdown cockpit as chrome (to stderr; stdout
    stays pure result JSON). Otherwise ``--tui``/``--no-tui`` force the dynamic
    ANSI vs. static Markdown view, defaulting to ANSI only on a colour TTY.
    """
    if bool(getattr(args, "json", False)):
        return "markdown"
    tui = getattr(args, "tui", None)
    if tui is False:
        return "markdown"
    if tui is True:
        return "ansi"
    return "ansi" if color else "markdown"


def run_session(
    args: argparse.Namespace,
    *,
    input_fn: Optional[Iterator[str]] = None,
    out: Callable[..., None] = print,
    err: Optional[Callable[..., None]] = None,
    _drive_fn: _DriveFn = _default_drive,
    _color: Optional[bool] = None,
) -> int:
    """Run the interactive cockpit session loop.

    Output contract: outside ``--json`` the rendered cockpit goes to ``out``
    (stdout) — an ANSI frame or Markdown menus per the resolved tier. In
    ``--json`` mode the cockpit renders as chrome to ``err`` (stderr) and ``out``
    (stdout) carries only each completed drive's ``TaskResult`` as JSON (one
    object per drive, preserving the machine contract). The banner, diagnostics,
    and the closing notice always go to ``err`` (stderr). Always returns ``0``
    (clean exit on quit/EOF).

    The ``input_fn`` / ``out`` / ``err`` / ``_drive_fn`` seams are for tests;
    ``_color`` overrides the colour-TTY detection that picks ANSI vs. Markdown.
    """
    repo = Path(args.repo).expanduser()
    # Resolve the engine like ``drive`` (explicit > COLLEAGUE_ENGINE > vllm-openai).
    engine_name = resolve_engine(args.engine)
    open_pr = bool(getattr(args, "pr", False))
    base = args.base
    json_mode = bool(getattr(args, "json", False))
    if err is None:
        err = _eprint

    config = EngineConfig.resolve(
        base_url=getattr(args, "base_url", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        max_steps=getattr(args, "max_steps", None),
    )

    color = _color if _color is not None else should_color(sys.stdout)
    view = _resolve_view(args, color=color)

    session = _Session(
        repo=repo,
        engine_name=engine_name,
        open_pr=open_pr,
        base=base,
        config=config,
        json_mode=json_mode,
        view=view,
        out=out,
        err=err,
        drive_fn=_drive_fn,
    )
    return session.run(input_fn)


def cmd_session(args: argparse.Namespace) -> int:
    """Handler for the ``colleague session`` verb."""
    return run_session(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "session",
        help=(
            "Open the interactive cockpit: a command palette + slash commands over "
            "the drive path; run templates or ad-hoc tasks, loop until quit."
        ),
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Backend plugin to drive (default: COLLEAGUE_ENGINE or vllm-openai).",
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
        "--tui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Render the dynamic ANSI cockpit (default: auto — on a colour TTY). "
            "Use --no-tui for the static Markdown view."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit one JSON TaskResult per drive to stdout; render the cockpit as "
            "chrome to stderr. (The TAUI JSON mirror lives under 'tui state'.)"
        ),
    )
    p.set_defaults(func=cmd_session)

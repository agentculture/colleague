"""``colleague session`` — the interactive cockpit over the work path.

Opens a foreground interactive **cockpit**: it renders one
:class:`~colleague.tui.state.CockpitState` (a command palette + a running
conversation + popups), reads a line of input, and dispatches it through the
**same** work path used by ``colleague work``
(:func:`~colleague.cli._commands.work.execute_work`). The loop runs until a
quit token (``q`` / ``/quit`` / empty line / EOF).

Three render tiers of the one state (#74 A2), chosen automatically:

* **interactive (a colour TTY, not ``--json``)** — the dynamic ANSI cockpit
  (popups, redraw-in-place during a work item);
* **non-interactive (piped / captured)** — **Markdown** menus (the static but
  *full* agent-readable view), the default off a TTY;
* **``--json``** — stdout carries only the work ``TaskResult`` (one JSON object
  each, preserving the machine contract); the Markdown cockpit renders to stderr
  as chrome. (The TAUI JSON mirror lives under ``colleague tui state``.)

Input is **line-based**. Plain text (a number / template name / free-text task)
runs a work item; a line starting with ``/`` is a **slash command** — the meta/system
namespace (introspection of existing nouns + live config actions).

The session is entirely foreground (no sockets, no daemons) and stdlib-only.

Testability
-----------
:func:`run_session` keeps the injectable ``input_fn`` / ``out`` / ``err`` /
``_work_fn`` seams. ``_color`` forces the interactive-vs-static tier without a
real TTY.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

from colleague import feedback, handoff, identity, layers, registry
from colleague.cli._banner import emit_banner
from colleague.cli._commands.work import execute_work as _default_work
from colleague.cli._errors import CliError
from colleague.commands import CommandError, discover_commands, expand_command, load_command
from colleague.config import EngineConfig, resolve_engine
from colleague.contract import Task, TaskResult
from colleague.policy import load_policy
from colleague.telemetry import TelemetryConfig
from colleague.tui.colors import should_color
from colleague.tui.events import UserInput
from colleague.tui.from_work import work_step
from colleague.tui.reducer import reduce
from colleague.tui.render.ansi_flat import render_flat as _render_flat
from colleague.tui.render.layout import detect_width
from colleague.tui.render.markdown import render_markdown as _render_markdown
from colleague.tui.state import CockpitState, Panel, PanelItem, Status, WorkItem
from colleague.tui.widgets.prompt_input import plain_prompt
from colleague.tui.widgets.slash_autocomplete import GROUP_ICON, SLASH_GROUPS, format_tags

# ---------------------------------------------------------------------------
# Types for the injectable seams
# ---------------------------------------------------------------------------

_WorkFn = Callable[..., tuple[TaskResult, Path]]

_QUIT_TOKENS = frozenset({"q", "quit", "exit", "bye"})
_CONVERSATION_PANEL_ID = "panel.conversation"
#: CSI clear-screen + cursor-home, so the dynamic ANSI view redraws in place.
_CLEAR_HOME = "\x1b[H\x1b[2J"
#: Leading-line markers identifying a previously-rendered suggested action, so a
#: refresh replaces it in place rather than stacking duplicates in the Session panel.
_SUGGESTION_PREFIXES = ("Safest next:", "⚠ Safest next:")


def _coerce_strs(value: object) -> list[str]:
    """Coerce a policy config value to a list of strings, tolerating bad shapes.

    Mirrors :func:`colleague.policy._str_list` so the cockpit presents exactly
    what the gate enforces: a non-list (or a list with non-string members)
    degrades to the surviving string members, never raising on a malformed
    ``approvals.json``.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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


class _WorkSink:
    """Progress sink for an in-session work item: fold each step into the session's
    one shared :class:`CockpitState` and (on the dynamic ANSI tier) redraw live."""

    def __init__(self, session: "_Session") -> None:
        self._session = session

    def __call__(self, step_index: int, tool: str, target: str, ok: bool) -> None:
        sess = self._session
        sess.state = reduce(sess.state, work_step(tool, target, ok))
        if sess.view == "ansi":
            sess.emit()  # live redraw per step

    def close(self) -> None:  # called by execute_work on every exit path
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
        allow_dirty: bool = False,
        view: str,
        out: Callable[..., None],
        err: Callable[..., None],
        work_fn: _WorkFn,
        user_home: Optional[Path] = None,
    ) -> None:
        self.repo = repo
        self.engine_name = engine_name  # mutable via /engine
        self.open_pr = open_pr  # mutable via /pr
        self.allow_dirty = allow_dirty  # dirty-tree guard opt-out (#149)
        self.base = base  # mutable via /base
        self.config = config  # .model mutable via /model
        self.json_mode = json_mode
        self.view = view  # "ansi" (dynamic) | "markdown" (static)
        self.out = out
        self.err = err
        # The rendered cockpit is interactive chrome: stdout normally, but stderr
        # in --json mode so stdout carries only the work TaskResult(s).
        self.chrome = err if json_mode else out
        self.work_fn = work_fn

        # ``user_home`` overrides the home dir command discovery scans (default
        # ``Path.home()``). Real sessions leave it ``None`` (scan the user's home);
        # hermetic callers (e.g. tools.tui_sim) pin it so personal
        # ``~/.colleague/commands`` can't leak into a reproducible run.
        self.discovered = discover_commands(repo, user_home=user_home)
        self.palette: list[tuple[str, str]] = [
            (name, load_command(self.discovered[name]).description)
            for name in sorted(self.discovered)
        ]
        self.state = self._initial_state()

    # ── state construction / mutation ────────────────────────────────────────

    def _initial_state(self) -> CockpitState:
        facts = self._facts()
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
                self._policy_panel(facts),
                self._context_panel(facts),
                Panel(id="commands", title="Work templates", visible=True, items=items),
                Panel(
                    id=_CONVERSATION_PANEL_ID,
                    title="Session",
                    visible=True,
                    content_summary=self._suggested_action(facts),
                ),
                *build_slash_panels(),
            ],
            status=self._status(),
        )

    def _status(self) -> Status:
        pr = "push+PR" if self.open_pr else "local"
        message = f"colleague session · {self.engine_name} · {pr}"
        return Status(severity="info", message=message)

    # ── cockpit facts (resolved once at startup / on a config change) ────────

    def _facts(self) -> dict:
        """Resolve the cockpit's context + policy facts from existing read-only
        helpers, in one guarded pass.

        Every value degrades to a safe default (``"unknown"`` / ``"none"`` /
        ``False``) rather than raising — a cockpit that can't resolve a fact must
        still open. Called at construction and after each context-mutating slash
        action / completed work item — **never** on the per-frame render path
        (which runs per keystroke + per work step).
        """
        facts: dict = {
            "branch": "unknown",
            "dirty": False,
            "agents": 0,
            "skills": [],
            "telemetry": False,
            "runcfg": None,
            "hooks_gated": False,
            "ident": self.repo.name,
            "last": None,
            "feedback": None,
        }
        try:
            facts["branch"] = handoff.current_ref(self.repo) or "unknown"
            facts["dirty"] = handoff.working_tree_dirty(self.repo)
            facts["agents"] = len(layers.resolve_agents(self.repo, self.config.model))
            facts["skills"] = sorted(layers.resolve_skills(self.repo, self.config.model))
            facts["telemetry"] = TelemetryConfig.resolve().enabled
            pol = load_policy(self.repo, model=self.config.model)
            facts["runcfg"] = pol.run_command_config()
            facts["hooks_gated"] = pol.section_present("hooks") or pol.section_present("commands")
            facts["ident"] = identity.resolve_identity(self.repo) or self.repo.name
            last = feedback.get_last_work(self.repo)
            facts["last"] = last
            if last:
                try:
                    facts["feedback"] = feedback.read_feedback(self.repo, last)
                except feedback.FeedbackError:
                    facts["feedback"] = None
        except Exception:  # nosec B110 - the cockpit must open even if a fact won't resolve
            pass
        return facts

    @staticmethod
    def _run_command_status(runcfg: dict | None) -> tuple[str, str, bool]:
        """``(status text, emoji, gated?)`` for the run_command line.

        Honest labels mirror :meth:`~colleague.policy.Policy.check_run_command`:
        an allow-list only gates when non-empty; an empty allow-list with a
        deny-list is deny-only (all others allowed); both empty is effectively
        ungated. Both lists are coerced so a malformed ``approvals.json`` can't
        crash render."""
        if runcfg is None:
            return "ungated (any command)", "⚠️", False
        allow = _coerce_strs(runcfg.get("allow"))
        deny = _coerce_strs(runcfg.get("deny"))
        if allow:
            shown = ", ".join(allow[:3]) + ("…" if len(allow) > 3 else "")
            return f"allow-list: {shown}", "🛡️", True
        if deny:
            shown = ", ".join(deny[:3]) + ("…" if len(deny) > 3 else "")
            return f"deny-list: {shown} (all others allowed)", "🛡️", True
        return "present, no rules (effectively ungated)", "⚠️", False

    def _policy_panel(self, facts: dict) -> Panel:
        """The *Run policy* panel — the safety surface (AC #3). Honest labels: the
        loop can write any repo file and run any command unless ``run_command`` is
        gated; the only real outward gate is push/PR. No sandbox is claimed."""
        run_status, run_emoji, gated = self._run_command_status(facts["runcfg"])
        edits = "read + write within repo"
        if facts["hooks_gated"]:
            edits += " · hooks/commands checksum-gated"
        if self.open_pr:
            handoff_status, handoff_emoji = f"on — push + open PR onto '{self.base}'", "🚀"
        else:
            handoff_status, handoff_emoji = "off (local commit only)", "🔒"
        summary = (
            f"run_command: {'gated' if gated else 'ungated'} · "
            f"edits: repo-local · push/PR: {'on' if self.open_pr else 'off'}"
        )
        return Panel(
            id="policy",
            title="Run policy",
            visible=True,
            content_summary=summary,
            items=[
                PanelItem(
                    id="pol.run_command", label=f"{run_emoji} run_command", status=run_status
                ),
                PanelItem(id="pol.files", label="✏️ file edits", status=edits),
                PanelItem(
                    id="pol.handoff", label=f"{handoff_emoji} push + PR", status=handoff_status
                ),
            ],
        )

    def _context_panel(self, facts: dict) -> Panel:
        """The *Context* panel — what world this colleague inhabits (AC #4/#5)."""
        skills = facts["skills"]
        if skills:
            shown = ", ".join(skills[:3]) + ("…" if len(skills) > 3 else "")
            skills_status = f"{shown} ({len(skills)})"
        else:
            skills_status = "none"
        agents_status = f"{facts['agents']} resolved" if facts["agents"] else "none"
        tree_status = "dirty (tracked changes)" if facts["dirty"] else "clean"
        fb, last = facts["feedback"], facts["last"]
        if last and fb is not None:
            fb_status = f"last graded ★{fb.rating}" + (f" by {fb.by}" if fb.by else "")
        elif last:
            fb_status = "last work ungraded — /feedback to grade"
        else:
            fb_status = "no work recorded yet"
        summary = (
            f"engine {self.engine_name} · model {self.config.model} · "
            f"{'PR' if self.open_pr else 'local'} · base {self.base}"
        )
        return Panel(
            id="context",
            title="Context",
            visible=True,
            content_summary=summary,
            items=[
                PanelItem(id="ctx.repo", label="📁 repo", status=facts["ident"]),
                PanelItem(id="ctx.branch", label="🌿 branch", status=facts["branch"]),
                PanelItem(id="ctx.tree", label="🧭 working tree", status=tree_status),
                PanelItem(id="ctx.agents", label="📋 AGENTS layers", status=agents_status),
                PanelItem(id="ctx.skills", label="🧩 skills", status=skills_status),
                PanelItem(
                    id="ctx.telemetry",
                    label="📡 telemetry",
                    status="on" if facts["telemetry"] else "off",
                ),
                PanelItem(id="ctx.feedback", label="⭐ /feedback", status=fb_status),
            ],
        )

    def _suggested_action(self, facts: dict) -> str:
        """The safest/most-useful next move (AC #1) — always answers 'what now?'."""
        if facts["dirty"] and not self.allow_dirty:
            return (
                "⚠ Safest next: commit or stash first (working tree is dirty), then "
                "type a number to run a template — or /help."
            )
        if self.palette:
            first = self.palette[0][0]
            effect = "pushes a PR" if self.open_pr else "commits locally, no PR"
            return (
                f"Safest next: type 1 to run '{first}' ({effect}). "
                "/pr toggles push · /help for commands."
            )
        return (
            "Safest next: type a free-text task (runs locally, no PR until /pr). "
            "/help for commands."
        )

    def _refresh_context(self) -> None:
        """Rebuild the policy + context panels in place (preserving the running
        conversation + work-templates panels) and refresh the Session panel's
        suggested-action line. Called after a config change or a completed work
        item — both can shift branch / dirty / policy / feedback, and the
        suggested action depends on dirty-state + push/PR, so it must not go
        stale (the cockpit promises to always answer 'what now?')."""
        facts = self._facts()
        suggested = self._suggested_action(facts)
        rebuilt = {"policy": self._policy_panel(facts), "context": self._context_panel(facts)}
        self.state.panels = [
            (
                self._with_suggestion(p, suggested)
                if p.id == _CONVERSATION_PANEL_ID
                else rebuilt.get(p.id, p)
            )
            for p in self.state.panels
        ]

    @staticmethod
    def _with_suggestion(panel: Panel, suggested: str) -> Panel:
        """Return the Session panel with its leading suggested-action line refreshed,
        preserving the running conversation that follows it. The suggestion is the
        first line of ``content_summary`` (set in :meth:`_initial_state`); replace it
        when it still looks like a suggestion, otherwise prepend the fresh one."""
        lines = panel.content_summary.split("\n") if panel.content_summary else []
        if lines and lines[0].startswith(_SUGGESTION_PREFIXES):
            lines[0] = suggested
        else:
            lines.insert(0, suggested)
        # Rebuild the Panel directly (not dataclasses.replace, whose inferred
        # return type defeats static type checks); copy every field, swap summary.
        return Panel(
            id=panel.id,
            title=panel.title,
            visible=panel.visible,
            content_summary="\n".join(lines),
            items=list(panel.items),
        )

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
            return _CLEAR_HOME + _render_flat(
                self.state, width=detect_width(), include_prompt=include_prompt
            )
        return _render_markdown(self.state)

    def emit(self) -> None:
        self.chrome(self._frame())

    def _read_live_ansi(self) -> Optional[str]:
        """Live ANSI read with a slash-command autocomplete popup.

        On a POSIX colour TTY this runs the raw per-keystroke reader: typing
        ``/`` opens a filtered popup of slash commands (Tab/Enter completes,
        arrows select, Esc dismisses). When raw mode is unavailable (non-TTY,
        ``termios`` missing, Windows) it falls back to the plain ``input`` path —
        byte-identical to before — so piped / ``--json`` / agent callers are
        unaffected. Tests and the static Markdown view never reach here; they go
        through :meth:`emit` + :func:`_read_line`.
        """
        from colleague.cli._commands._session_input import read_line_with_popup
        from colleague.tui.widgets.slash_autocomplete import render_slash_autocomplete

        def _fallback() -> Optional[str]:
            sys.stdout.write(self._frame(include_prompt=False) + "\n")
            sys.stdout.flush()
            try:
                return input(plain_prompt())
            except EOFError:
                return None

        def _render(buffer: str, matches: list, selected: int) -> str:
            parts = [self._frame(include_prompt=False)]
            if matches:
                parts.append(
                    render_slash_autocomplete(
                        matches, selected, width=detect_width(), style=_slash_tag_style()
                    )
                )
            parts.append(plain_prompt() + buffer)
            return "\n".join(parts)

        return read_line_with_popup(_SLASH_COMMANDS, _render, filter_slash, fallback=_fallback)

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
        self._work_line(line)
        return True

    # ── slash commands ───────────────────────────────────────────────────────

    def _slash(self, line: str) -> bool:
        parts = line[1:].split()
        verb = parts[0].lower() if parts else ""
        rest = parts[1:]

        if verb in ("quit", "exit", "q"):
            return False
        if verb in ("help", ""):
            arg = rest[0].lower() if rest else ""
            self._log({"verbose": _HELP_VERBOSE, "compact": _HELP_COMPACT}.get(arg, _HELP_TEXT))
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
            self._refresh_context()
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

    # ── work ────────────────────────────────────────────────────────────────

    def _work_line(self, line: str) -> None:
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
        self._run_work(task, command_name)

    def _run_work(self, task: Task, command_name: Optional[str]) -> None:
        # Mark a work item active so the cockpit's state glyph animates per step
        # (the sink's WorkStep reductions advance ``work_item.step_count``).
        self.state.work_item = WorkItem(task_id=task.id, engine=self.engine_name, running=True)
        try:
            result, _artifact = self.work_fn(
                repo=self.repo,
                engine_name=self.engine_name,
                task=task,
                open_pr=self.open_pr,
                allow_dirty=self.allow_dirty,
                base=self.base,
                config=self.config,
                command_name=command_name,
                progress_sink=_WorkSink(self),
            )
        except CliError as exc:
            hint = f" (hint: {exc.remediation})" if exc.remediation else ""
            self._error(f"error: {exc.message}{hint}")
            return
        except Exception as exc:  # noqa: BLE001
            self._error(f"error: {type(exc).__name__}: {exc}")
            return
        finally:
            if self.state.work_item is not None:
                self.state.work_item.running = False

        if self.json_mode:
            self.out(json.dumps(result.to_dict(), ensure_ascii=False))
        changed = ", ".join(result.changed_files) or "(none)"
        branch = f" → {result.branch}" if result.branch else ""
        self._log(f"{result.status}: {result.summary} [{changed}]{branch}")
        # A completed work item can change branch / dirty / last-feedback state.
        self._refresh_context()


# ---------------------------------------------------------------------------
# Slash-command tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlashSpec:
    """One slash command: its name, an optional arg hint, a one-line help, the
    intent ``group`` it belongs to (``controls`` / ``inspect`` / ``session``) so
    ``/help`` and the popup can present a grouped tree, and ``tags`` — small
    capability/risk badges (``read-only`` / ``writes`` / ``git`` / ``pr`` …,
    issue #160) shown next to the command."""

    name: str
    arg_hint: str
    description: str
    group: str = "session"
    tags: tuple[str, ...] = ()


#: The single source of truth for every slash command — the ``/help`` text, the
#: live autocomplete popup, AND the cockpit slash panels are all derived from
#: this list, so they cannot drift (a drift test pins that every dispatch verb
#: appears here).
_SLASH_COMMANDS: list[SlashSpec] = [
    SlashSpec("help", "", "this list (/help verbose|compact for more)", "session"),
    SlashSpec("commands", "", "list command templates", "inspect", ("read-only", "config")),
    SlashSpec("skills", "", "resolved skill docs", "inspect", ("read-only", "config")),
    SlashSpec("agents", "", "resolved AGENTS layers", "inspect", ("read-only", "config")),
    SlashSpec(
        "config",
        "",
        "configuration readiness (doctor)",
        "inspect",
        ("read-only", "config", "audit"),
    ),
    SlashSpec("engines", "", "discovered backend plugins", "inspect", ("read-only", "model")),
    SlashSpec(
        "telemetry", "", "telemetry configuration", "inspect", ("read-only", "telemetry", "config")
    ),
    SlashSpec(
        "feedback",
        "",
        "feedback for the last work item",
        "inspect",
        ("human-loop", "memory", "interactive"),
    ),
    SlashSpec(
        "engine",
        "<name>",
        "switch the engine for the next work item",
        "controls",
        ("model", "config"),
    ),
    SlashSpec("model", "<name>", "switch the model", "controls", ("model", "config")),
    SlashSpec("base", "<branch>", "set the PR base branch", "controls", ("git", "config")),
    SlashSpec(
        "pr",
        "",
        "toggle push + open PR on each work item",
        "controls",
        ("git", "pr", "writes", "human-loop"),
    ),
    SlashSpec("quit", "", "end the session", "session", ("safe",)),
]


def filter_slash(prefix: str, specs: Optional[Sequence[SlashSpec]] = None) -> list[SlashSpec]:
    """Return the slash commands whose name starts with *prefix* (case-insensitive).

    An empty prefix returns the full list (popup just opened); a non-matching
    prefix returns ``[]`` (the popup vanishes). This is the pure, TTY-free core
    of the autofilter.
    """
    pool = _SLASH_COMMANDS if specs is None else list(specs)
    needle = prefix.strip().lower()
    return [s for s in pool if s.name.lower().startswith(needle)]


def _grouped(specs: Sequence[SlashSpec]) -> dict[str, list[SlashSpec]]:
    """Bucket *specs* by their ``group``, preserving catalog order within a group."""
    groups: dict[str, list[SlashSpec]] = {}
    for s in specs:
        groups.setdefault(s.group or "session", []).append(s)
    return groups


def _format_help(specs: Sequence[SlashSpec], style: str = "text") -> str:
    """Compact, grouped ``/help`` — one ``📁`` heading per intent group, each
    command on its own line with its tag badges (issue #160). Every ``/<name>``
    still appears (the drift test pins that), and the literal token ``slash
    commands`` is kept. *style* selects the tag form (``text`` | ``icons``)."""
    groups = _grouped(specs)
    rows = ["slash commands  (/help verbose for descriptions · /help compact for icons)"]
    for key, title in SLASH_GROUPS:
        members = groups.get(key, [])
        if not members:
            continue
        rows.append("")
        rows.append(f"{GROUP_ICON} {title}")
        for s in members:
            left = f"/{s.name}" + (f" {s.arg_hint}" if s.arg_hint else "")
            rows.append(f"  {left:<18} {format_tags(s.tags, style)}".rstrip())
    rows.append("")
    rows.append("plain text (a number / template name / free-text task) runs a work item.")
    return "\n".join(rows)


def _format_help_verbose(specs: Sequence[SlashSpec], style: str = "text") -> str:
    """Verbose ``/help`` — every command grouped, with arg hints, descriptions,
    and tag badges."""
    groups = _grouped(specs)
    rows = ["slash commands (verbose)"]
    for key, title in SLASH_GROUPS:
        members = groups.get(key, [])
        if not members:
            continue
        rows.append("")
        rows.append(f"{GROUP_ICON} {title}")
        for s in members:
            left = f"/{s.name}" + (f" {s.arg_hint}" if s.arg_hint else "")
            tags = format_tags(s.tags, style)
            suffix = f"  {tags}" if tags else ""
            rows.append(f"  {left:<18} {s.description}{suffix}")
    rows.append("")
    rows.append("Work: type a number to run a template, or free text for an ad-hoc task.")
    rows.append("      /pr before a task to push + open a PR; /base sets the PR base branch.")
    return "\n".join(rows)


def build_slash_panels() -> list[Panel]:
    """The slash catalog as cockpit panels — one ``Panel`` per intent group, each
    item carrying the command's ``tags`` — so the grouped tree + tag badges reach
    the agent-facing Markdown/TAUI tiers (issue #160). The live ANSI session
    surfaces the same commands through the ``/`` popup, so ``render_flat`` skips
    these ``slash.*`` panels."""
    groups = _grouped(_SLASH_COMMANDS)
    panels: list[Panel] = []
    for key, title in SLASH_GROUPS:
        members = groups.get(key, [])
        if not members:
            continue
        items = [
            PanelItem(
                id=f"slash.{s.name}",
                label=f"/{s.name}" + (f" {s.arg_hint}" if s.arg_hint else ""),
                tags=list(s.tags),
            )
            for s in members
        ]
        panels.append(Panel(id=f"slash.{key}", title=f"{GROUP_ICON} {title}", items=items))
    return panels


def _slash_tag_style() -> str:
    """Tag badge style for the live ``/`` popup: ``icons`` when
    ``COLLEAGUE_SLASH_TAG_STYLE=icons``, else the default ``text``."""
    return "icons" if os.environ.get("COLLEAGUE_SLASH_TAG_STYLE", "").lower() == "icons" else "text"


_HELP_TEXT = _format_help(_SLASH_COMMANDS)
_HELP_VERBOSE = _format_help_verbose(_SLASH_COMMANDS)
_HELP_COMPACT = _format_help(_SLASH_COMMANDS, style="icons")

# Read-only introspection: map a verb to the argv passed to the real CLI parser.
_INTROSPECT: dict[str, Callable[["_Session"], list[str]]] = {
    "commands": lambda s: ["commands", "list", "--repo", str(s.repo)],
    "skills": lambda s: ["skills", "list", "--repo", str(s.repo), "--model", s.config.model],
    "agents": lambda s: ["agents", "list", "--repo", str(s.repo), "--model", s.config.model],
    "config": lambda s: ["doctor"],
    "engines": lambda s: ["backends", "list"],
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
    return f"push + PR on each work item → {'on' if s.open_pr else 'off'}"


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
    _work_fn: _WorkFn = _default_work,
    _color: Optional[bool] = None,
) -> int:
    """Run the interactive cockpit session loop.

    Output contract: outside ``--json`` the rendered cockpit goes to ``out``
    (stdout) — an ANSI frame or Markdown menus per the resolved tier. In
    ``--json`` mode the cockpit renders as chrome to ``err`` (stderr) and ``out``
    (stdout) carries only each completed work item's ``TaskResult`` as JSON (one
    object per work item, preserving the machine contract). The banner, diagnostics,
    and the closing notice always go to ``err`` (stderr). Always returns ``0``
    (clean exit on quit/EOF).

    The ``input_fn`` / ``out`` / ``err`` / ``_work_fn`` seams are for tests;
    ``_color`` overrides the colour-TTY detection that picks ANSI vs. Markdown.
    """
    repo = Path(args.repo).expanduser()
    # Resolve the engine like ``work`` (explicit > COLLEAGUE_ENGINE > vllm-openai).
    engine_name = resolve_engine(args.engine)
    open_pr = bool(getattr(args, "pr", False))
    allow_dirty = bool(getattr(args, "allow_dirty", False))
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
        allow_dirty=allow_dirty,
        base=base,
        config=config,
        json_mode=json_mode,
        view=view,
        out=out,
        err=err,
        work_fn=_work_fn,
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
            "the work path; run templates or ad-hoc tasks, loop until quit."
        ),
    )
    p.add_argument("--repo", default=".", help="Path to the target repository (default: cwd).")
    p.add_argument(
        "--engine",
        default=None,
        help="Backend plugin to use (default: COLLEAGUE_ENGINE or vllm-openai).",
    )
    p.add_argument(
        "--pr",
        action="store_true",
        help="Push and open a PR after each work item (default: commit locally only, no PR).",
    )
    p.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Run work items even when the working tree has uncommitted tracked "
            "changes (they get committed onto the work branch). Default: refuse, "
            "to protect in-progress work (#149)."
        ),
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
            "Emit one JSON TaskResult per work item to stdout; render the cockpit as "
            "chrome to stderr. (The TAUI JSON mirror lives under 'tui state'.)"
        ),
    )
    p.set_defaults(func=cmd_session)

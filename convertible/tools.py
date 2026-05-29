"""The tool surface the agentic loop offers an engine, plus a repo-confined executor.

Seven tools — ``read_file``, ``write_file``, ``list_dir``, ``run_command``,
``culture``, ``devague``, and ``finish`` — are exposed to the model as OpenAI
function/tool schemas (:data:`SCHEMAS`). :class:`ToolExecutor` runs a requested
call against a fixed repo root.

Confinement (honesty condition h3): ``read_file`` / ``write_file`` / ``list_dir``
resolve their path against the root and refuse anything that escapes it (``..``
traversal, absolute paths outside the tree). ``run_command`` runs with ``cwd``
pinned to the root. v0 trusts the command itself (decision D2); sandboxing is a
later wheel.
"""

from __future__ import annotations

import subprocess  # nosec B404 - running model-issued commands is the point (trusted, D2)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from convertible import culture, devague

FINISH = "finish"

# Cap tool output fed back to the model so a huge file/command can't blow the
# context window. Tunable; deliberately conservative.
_MAX_OUTPUT_CHARS = 20_000


class ToolError(Exception):
    """A tool call that cannot be honored (bad path, escape attempt, missing file)."""


@dataclass
class ToolOutcome:
    """Result of executing one tool call."""

    result: str
    changed_file: str | None = None
    finished: bool = False
    finish_summary: str = ""
    destination: str | None = None
    """The devague goal-frame slug the drive aimed at, or ``None`` when the
    engine did not declare a destination on finish."""
    announcement: str | None = None
    """The announcement text declared on arrival at the destination, or ``None``
    when the engine did not declare one."""


# OpenAI tool/function schemas — handed to the model verbatim in the loop.
SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file, relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repo root."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a UTF-8 text file, relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repo root."},
                    "content": {"type": "string", "description": "Full file contents to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the entries of a directory, relative to the repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory relative to the repo root (default: root).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command with the working directory at the repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command line to run."}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "culture",
            "description": (
                "Run an operator-installed AgentCulture CLI, with the agent's "
                "identity injected and the working directory at the repo root. "
                "'agtag' works the mesh issue tracker (e.g. issue post/fetch/reply); "
                "'agex' inspects a repo's agent-first surface (e.g. explain/overview/"
                "learn). Only these two CLIs are permitted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cli": {
                        "type": "string",
                        "enum": sorted(culture.ALLOWED_CLIS),
                        "description": "Which AgentCulture CLI to run.",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Argument vector passed to the CLI (after its name).",
                    },
                },
                "required": ["cli"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "devague",
            "description": (
                "Run a curated devague move against the operator-installed devague CLI. "
                "Use this to set or check a goal-frame (destination) for the current task — "
                "e.g. 'new' to open a fresh frame, 'capture' to record a claim, "
                "'interrogate' to probe a claim, 'park' to defer a thread, "
                "'converge' to signal the frame is ready to converge, "
                "'status' to inspect the current frame, or 'show' to display it. "
                "Convergence is *advisory* — the final confirm/reject decision belongs "
                "to the user, and export is operator-only. "
                "confirm, reject, and export are intentionally NOT available through "
                "this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "move": {
                        "type": "string",
                        "enum": sorted(devague.ALLOWED_MOVES),
                        "description": "The devague move to execute.",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Argument vector passed to the CLI (after the move name).",
                    },
                },
                "required": ["move"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": FINISH,
            "description": "Signal the task is complete. Provide a short summary of what changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Summary of the work done."},
                    "destination": {
                        "type": "string",
                        "description": (
                            "Optional. The devague goal-frame slug the drive aimed at "
                            "(e.g. 'ship-core-widget', 'improve-test-suite') — match the "
                            "frame slug created/used during the drive. Omit when no "
                            "destination was set."
                        ),
                    },
                    "announcement": {
                        "type": "string",
                        "description": (
                            "Optional. The announcement text declared on arrival at the "
                            "destination. Omit when not applicable."
                        ),
                    },
                },
            },
        },
    },
]

TOOL_NAMES: list[str] = [s["function"]["name"] for s in SCHEMAS]


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"\n... [truncated at {_MAX_OUTPUT_CHARS} chars]"


class ToolExecutor:
    """Executes tool calls against a single repo root, confining file access to it."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.changed: set[str] = set()

    def _safe_path(self, rel: str) -> Path:
        """Resolve ``rel`` under the root, refusing any path that escapes it."""
        candidate = (self.root / rel).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"path '{rel}' escapes the repo root")
        return candidate

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name == "read_file":
            return self._read_file(arguments)
        if name == "write_file":
            return self._write_file(arguments)
        if name == "list_dir":
            return self._list_dir(arguments)
        if name == "run_command":
            return self._run_command(arguments)
        if name == "culture":
            return self._culture(arguments)
        if name == "devague":
            return self._devague(arguments)
        if name == FINISH:
            return ToolOutcome(
                result="finished",
                finished=True,
                finish_summary=str(arguments.get("summary", "")),
                destination=arguments.get("destination") or None,
                announcement=arguments.get("announcement") or None,
            )
        raise ToolError(f"unknown tool '{name}'")

    def _read_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        path = self._safe_path(str(arguments["path"]))
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ToolError(f"no such file: {arguments['path']}") from exc
        except OSError as exc:
            raise ToolError(f"cannot read {arguments['path']}: {exc}") from exc
        return ToolOutcome(result=_truncate(text))

    def _write_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        rel = str(arguments["path"])
        path = self._safe_path(rel)
        # Neighbour clones are read-only source (honesty condition h12): the model
        # may read them but never write into them. _safe_path only confines to the
        # repo root, which includes the clone tree — so guard writes explicitly.
        clone_root = (self.root / self._CLONE_SUBDIR).resolve()
        if path == clone_root or clone_root in path.parents:
            raise ToolError(
                f"write refused: '{rel}' is inside the neighbour clone directory "
                f"('{self._CLONE_SUBDIR}'), which is read-only source. "
                "Clones are inert — they may be read, never written."
            )
        content = str(arguments.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.changed.add(rel)
        return ToolOutcome(result=f"wrote {len(content)} bytes to {rel}", changed_file=rel)

    def _list_dir(self, arguments: dict[str, Any]) -> ToolOutcome:
        path = self._safe_path(str(arguments.get("path", ".")))
        if not path.is_dir():
            raise ToolError(f"not a directory: {arguments.get('path', '.')}")
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return ToolOutcome(result=_truncate("\n".join(entries)))

    # Relative path prefix used by the never-execute guard below.
    _CLONE_SUBDIR = ".convertible/neighbours"

    def _run_command(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Execute a shell command with cwd pinned to the repo root.

        Never-execute confinement (AC2, best-effort): this guard refuses any
        command string that contains the clone subdirectory path
        (``.convertible/neighbours``), which is the read-only source tree for
        neighbour clones. Clones exist only to be *read*; executing scripts or
        binaries from them is not part of the contract.

        Honest limitation: the guard is a substring check on the raw command
        string. A sufficiently obfuscated command (e.g. variable expansion,
        concatenation, here-docs) could bypass it. It is best-effort — an
        airtight sandbox is out of v0 scope (see CLAUDE.md). The guard covers
        the obvious / accidental case; document rather than overclaim.
        """
        command = str(arguments["command"])

        # Best-effort guard: refuse commands that reference the clone dir.
        # Checks both the canonical relative prefix and the absolute path so
        # that both "sh .convertible/neighbours/foo/bar.sh" and
        # "sh /abs/path/.convertible/neighbours/foo/bar.sh" are blocked.
        clone_rel = self._CLONE_SUBDIR
        clone_abs = str(self.root / clone_rel)
        if clone_rel in command or clone_abs in command:
            raise ToolError(
                f"run_command refused: commands must not execute paths inside the "
                f"neighbour clone directory ('{clone_rel}'). "
                f"Clone files are read-only source — use read_file to inspect them."
            )

        proc = subprocess.run(  # nosec B602 - shell by design; trusted operator env (D2)
            command,
            shell=True,
            cwd=str(self.root),
            capture_output=True,
            text=True,
            timeout=300,
        )
        body = (proc.stdout or "") + (proc.stderr or "")
        result = f"exit={proc.returncode}\n{body}"
        return ToolOutcome(result=_truncate(result))

    def _culture(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the shared ``culture`` tool to an allow-listed AgentCulture CLI.

        The subprocess launch, identity injection, and absent-CLI handling live
        in :mod:`convertible.culture`; here we just translate its error type into
        the loop's :class:`ToolError` so a bad CLI name or an uninstalled CLI
        becomes a clean string fed back to the model, never a crash.
        """
        cli = arguments.get("cli")
        if not cli or not isinstance(cli, str):
            raise ToolError("culture tool requires a 'cli' name (agtag or agex)")
        args = culture.normalize_args(arguments.get("args"))
        try:
            output = culture.run_culture(cli, args, root=self.root)
        except culture.CultureToolError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutcome(result=output)

    def _devague(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the shared ``devague`` tool to the operator-installed devague CLI.

        The subprocess launch, identity injection, and allow-list enforcement live
        in :mod:`convertible.devague`; here we translate its error type into the
        loop's :class:`ToolError` so a disallowed move or an uninstalled CLI
        becomes a clean string fed back to the model, never a crash.
        """
        move = str(arguments.get("move", ""))
        args = devague.normalize_args(arguments.get("args"))
        try:
            output = devague.run_devague(move, args, root=self.root)
        except devague.DevagueToolError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutcome(result=output)

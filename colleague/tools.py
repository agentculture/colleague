"""The tool surface the agentic loop offers an engine, plus a repo-confined executor.

Nine tools — ``read_file``, ``write_file``, ``list_dir``, ``run_command``,
``culture``, ``devague``, ``subagent``, ``subagents``, and ``finish`` — are exposed
to the model as OpenAI function/tool schemas (:data:`SCHEMAS`). :class:`ToolExecutor`
runs a requested call against a fixed repo root.

Confinement (honesty condition h3): ``read_file`` / ``write_file`` / ``list_dir``
resolve their path against the root and refuse anything that escapes it (``..``
traversal, absolute paths outside the tree). ``run_command`` runs with ``cwd``
pinned to the root. v0 trusts the command itself (decision D2); sandboxing is a
later wheel.
"""

from __future__ import annotations

import shlex
import subprocess  # nosec B404 - running model-issued commands is the point (trusted, D2)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from colleague import culture, devague
from colleague.config import _DEFAULT_MAX_OUTPUT_CHARS, MAX_SUBAGENT_FANOUT
from colleague.contract import SubResult

FINISH = "finish"

#: Bound a runaway model-issued command so it cannot stall the loop indefinitely
#: (mirrors culture/devague ``_TIMEOUT_SECONDS`` and neighbours ``_GIT_TIMEOUT_SECONDS``).
_COMMAND_TIMEOUT_SECONDS = 300


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
    """The devague goal-frame slug the work item aimed at, or ``None`` when the
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
            "description": (
                "Run a shell command. Each call runs in a FRESH shell with the "
                "working directory already at the repo root, so `cd` and "
                "environment changes do NOT persist to later calls — never `cd` to "
                "reach a path; use repo-relative paths directly."
            ),
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
                "'devex' inspects a repo's agent-first surface (e.g. explain/overview/"
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
            "name": "subagent",
            "description": (
                "Delegate a scoped sub-task to a nested in-process child work item, "
                "optionally on a different engine or model. The child work item runs "
                "the full bounded tool-loop (no git handoff) and returns a result "
                "summary; any files the child writes are merged into the parent's "
                "changed-file set so they reach the single top-level handoff. "
                "Use this to break a large task into independently executable "
                "pieces or to run part of the work on a specialised model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "A scoped sub-task for a nested child work item.",
                    },
                    "engine": {
                        "type": "string",
                        "description": "Engine wheel for the subagent (omit to inherit parent).",
                    },
                    "model": {
                        "type": "string",
                        "description": "Model override for the subagent (omit to inherit parent).",
                    },
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subagents",
            "description": (
                "Fan out a batch of scoped sub-tasks to nested in-process child work items "
                "that run in parallel, each optionally on a different engine or model. "
                "Each child work item runs the full bounded tool-loop (no git handoff) and "
                "returns a result summary; a final merge child integrates each child's "
                "branch back into the working tree. All sub-results (children + merge) "
                "are recorded on the parent drive. "
                "Use this to parallelise independent work across multiple children. "
                "Capped at 3 instructions per batch (one slot is reserved for the merge "
                "child within the MAX_SUBAGENT_FANOUT=4 limit)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instructions": {
                        "type": "array",
                        "description": (
                            "A list of scoped sub-tasks to fan out in parallel (1–3 items)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "instruction": {
                                    "type": "string",
                                    "description": (
                                        "A scoped sub-task for a nested child work item."
                                    ),
                                },
                                "engine": {
                                    "type": "string",
                                    "description": (
                                        "Engine wheel for this child (omit to inherit parent)."
                                    ),
                                },
                                "model": {
                                    "type": "string",
                                    "description": (
                                        "Model override for this child (omit to inherit parent)."
                                    ),
                                },
                            },
                            "required": ["instruction"],
                        },
                    },
                },
                "required": ["instructions"],
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
                            "Optional. The devague goal-frame slug the work item aimed at "
                            "(e.g. 'ship-core-widget', 'improve-test-suite') — match the "
                            "frame slug created/used during the work item. Omit when no "
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


class ToolExecutor:
    """Executes tool calls against a single repo root, confining file access to it."""

    def __init__(
        self,
        root: str | Path,
        *,
        spawn=None,
        batch_spawn=None,
        max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self.root = Path(root).resolve()
        self.changed: set[str] = set()
        # Total UTF-8 bytes written to files via write_file across the work item — the
        # exact "tokens written" measure (no tokenizer, so bytes not tokens). The
        # loop snapshots it onto WorkStats, mirroring the changed_files snapshot.
        self.bytes_written: int = 0
        self._spawn = spawn
        # Batch spawn callable: ``batch_spawn(items) -> list[SubResult]``.
        # Injected by the loop (t5); None means the subagents tool is unavailable.
        self._batch_spawn = batch_spawn
        # Cap on each tool result fed back to the model so a huge file/command
        # can't blow the context window. Resolved from EngineConfig (env
        # COLLEAGUE_MAX_OUTPUT_CHARS); sized for the served model's window.
        self._max_output_chars = max_output_chars
        self.sub_results: list[SubResult] = []

    def _truncate(self, text: str) -> str:
        limit = self._max_output_chars
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated at {limit} chars]"

    def _safe_path(self, rel: str) -> Path:
        """Resolve ``rel`` under the root, refusing any path that escapes it."""
        candidate = (self.root / rel).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"path '{rel}' escapes the repo root")
        return candidate

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch a single tool call by name to its handler.

        Returns the matching handler's ToolOutcome.
        """
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
        if name == "subagent":
            return self._subagent(arguments)
        if name == "subagents":
            return self._subagents(arguments)
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
        return ToolOutcome(result=self._truncate(text))

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
        # newline="" disables newline translation so the on-disk bytes equal
        # len(content.encode("utf-8")) on EVERY platform (default newline=None
        # would rewrite "\n" -> "\r\n" on Windows, inflating the file and making
        # bytes_written wrong). Keeps file writes byte-deterministic cross-platform.
        path.write_text(content, encoding="utf-8", newline="")
        self.changed.add(rel)
        # Accumulate exact UTF-8 bytes written (== the on-disk size, given
        # newline=""), summed across every write_file — snapshotted into WorkStats.
        n_bytes = len(content.encode("utf-8"))
        self.bytes_written += n_bytes
        return ToolOutcome(result=f"wrote {n_bytes} bytes to {rel}", changed_file=rel)

    def _list_dir(self, arguments: dict[str, Any]) -> ToolOutcome:
        path = self._safe_path(str(arguments.get("path", ".")))
        if not path.is_dir():
            raise ToolError(f"not a directory: {arguments.get('path', '.')}")
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return ToolOutcome(result=self._truncate("\n".join(entries)))

    # Relative path prefix used by the never-execute guard below.
    _CLONE_SUBDIR = ".colleague/neighbours"

    def _run_command(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Execute a shell command with cwd pinned to the repo root.

        Never-execute confinement (AC2, best-effort): this guard refuses any
        command string that contains the clone subdirectory path
        (``.colleague/neighbours``), which is the read-only source tree for
        neighbour clones. Clones exist only to be *read*; executing scripts or
        binaries from them is not part of the contract.

        Honest limitation: the guard is a substring check on the raw command
        string. A sufficiently obfuscated command (e.g. variable expansion,
        concatenation, here-docs) could bypass it. It is best-effort — an
        airtight sandbox is out of v0 scope (see CLAUDE.md). The guard covers
        the obvious / accidental case; document rather than overclaim.
        """
        command = str(arguments["command"])

        # Best-effort guard: refuse commands that EXECUTE a path inside the clone
        # dir. Token-aware (shlex) so a benign command that merely *mentions* the
        # path inside a quoted string (e.g. echo "see .colleague/neighbours") is no
        # longer a false positive — only a token that resolves to the clone root,
        # or under it, is refused. On unbalanced quotes (shlex ValueError) fall back
        # to the stricter substring check so a malformed command never slips
        # through. Honest limit: like the rest of this gate (D2), it is bypassable
        # by sh -c, pipelines, and shell expansion — a guard, not a sandbox.
        clone_rel = self._CLONE_SUBDIR
        # The guard must NEVER raise — a raw exception here would escape tool
        # execution and abort the whole drive. Resolving the clone root can fail on
        # a pathological tree (symlink loop → RuntimeError, permissions → OSError),
        # so compute it defensively and fall back to the unresolved substring check.
        try:
            clone_root: Path | None = (self.root / clone_rel).resolve()
        except (OSError, RuntimeError, ValueError):
            clone_root = None

        def _targets_clone(token: str) -> bool:
            try:
                candidate = (self.root / token).resolve()
            except (OSError, RuntimeError, ValueError):
                # Unresolvable token (e.g. an embedded NUL byte) is not a clone-dir
                # target; let it fall through to subprocess.run, whose own error is
                # mapped to a clean ToolError below rather than escaping the guard.
                return False
            return candidate == clone_root or clone_root in candidate.parents

        try:
            tokens: list[str] | None = shlex.split(command)
        except ValueError:
            tokens = None  # unparseable command → conservative substring fallback
        if clone_root is not None and tokens is not None:
            blocked = any(_targets_clone(t) for t in tokens)
        else:
            # Token-aware check unavailable (unresolvable clone root or unparseable
            # command) → conservative substring fallback on the *unresolved* absolute
            # path, which never raises.
            clone_abs = str(self.root / clone_rel)
            blocked = clone_rel in command or clone_abs in command
        if blocked:
            raise ToolError(
                f"run_command refused: commands must not execute paths inside the "
                f"neighbour clone directory ('{clone_rel}'). "
                f"Clone files are read-only source — use read_file to inspect them."
            )

        try:
            proc = subprocess.run(  # nosec B602 - shell by design; trusted operator env (D2)
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            # A hung command must surface as a recoverable ToolError, not an
            # uncaught exception that escapes the executor and aborts the whole
            # drive — the loop only catches ToolError around tool execution
            # (see colleague/loop.py), mirroring culture/devague/hooks.
            raise ToolError(
                f"run_command timed out after {_COMMAND_TIMEOUT_SECONDS}s: {command}"
            ) from exc
        except OSError as exc:
            # Launch/IO failure (e.g. too many open files, no shell) → clean error.
            raise ToolError(f"run_command failed to launch: {exc}") from exc
        except Exception as exc:
            # Any other failure from subprocess.run (e.g. ValueError on an embedded
            # NUL byte in a model-issued command) must ALSO be recoverable, not
            # abort the work item — the whole point of run_command error mapping. Mirrors
            # the _subagent/_subagents catch-all in this module. KeyboardInterrupt is
            # a BaseException and still propagates.
            raise ToolError(f"run_command failed: {type(exc).__name__}: {exc}") from exc
        body = (proc.stdout or "") + (proc.stderr or "")
        result = f"exit={proc.returncode}\n{body}"
        return ToolOutcome(result=self._truncate(result))

    def _culture(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the shared ``culture`` tool to an allow-listed AgentCulture CLI.

        The subprocess launch, identity injection, and absent-CLI handling live
        in :mod:`colleague.culture`; here we just translate its error type into
        the loop's :class:`ToolError` so a bad CLI name or an uninstalled CLI
        becomes a clean string fed back to the model, never a crash.
        """
        cli = arguments.get("cli")
        if not cli or not isinstance(cli, str):
            raise ToolError("culture tool requires a 'cli' name (agtag or devex)")
        args = culture.normalize_args(arguments.get("args"))
        try:
            output = culture.run_culture(cli, args, root=self.root)
        except culture.CultureToolError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutcome(result=output)

    def _devague(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the shared ``devague`` tool to the operator-installed devague CLI.

        The subprocess launch, identity injection, and allow-list enforcement live
        in :mod:`colleague.devague`; here we translate its error type into the
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

    def _subagent(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Delegate a scoped sub-task to a nested child work item via the injected spawn.

        The actual launching lives in the injected ``spawn`` callable (set by the
        loop in t6); here we only validate inputs, enforce the per-work-item fan-out
        cap, call the spawn, and translate any non-ToolError exception into a clean
        :class:`ToolError` so a launcher/engine error is fed back to the model and
        never crashes the parent drive.

        The child's changed files are merged into ``self.changed`` so they reach
        the single top-level handoff. ``self.sub_results`` accumulates all children
        for the parent ``TaskResult``.
        """
        if self._spawn is None:
            raise ToolError("subagent delegation is not available in this drive")

        instruction = arguments.get("instruction")
        if not instruction or not isinstance(instruction, str):
            raise ToolError("subagent tool requires an 'instruction'")

        engine = arguments.get("engine") or None
        model = arguments.get("model") or None

        if len(self.sub_results) >= MAX_SUBAGENT_FANOUT:
            raise ToolError(
                f"subagent fan-out limit ({MAX_SUBAGENT_FANOUT}) reached for this drive"
            )

        try:
            sub = self._spawn(instruction, engine, model)
        except ToolError:
            raise
        except Exception as exc:  # launcher/engine errors -> clean string for the model
            raise ToolError(f"subagent failed: {exc}") from exc

        self.sub_results.append(sub)
        self.changed.update(sub.changed_files)

        result = (
            f"subagent[{sub.engine}/{sub.model}] {sub.status}: {sub.summary}\n"
            f"changed files: " + (", ".join(sub.changed_files) or "(none)")
        )
        return ToolOutcome(result=self._truncate(result))

    def _subagents(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Fan out a batch of sub-tasks to nested child work items via the injected batch spawn.

        The actual launching lives in the injected ``batch_spawn`` callable (set by
        the loop in t5); here we validate inputs, enforce the per-work-item batch
        fan-out cap (MAX_SUBAGENT_FANOUT - 1 = 3 parallel children, reserving one
        slot for the merge child), call the batch spawn, and translate any
        non-ToolError exception into a clean :class:`ToolError`.

        The returned list includes N child ``SubResult`` objects (in input order)
        followed by exactly one merge child — the shape produced by
        :func:`colleague.subagents.make_batch_spawn`. All are appended to
        ``self.sub_results``; the engine cannot exceed the operator's
        COLLEAGUE_SUBAGENT_CONCURRENCY, which governs actual parallelism.
        """
        if self._batch_spawn is None:
            raise ToolError("subagents delegation is not available in this drive")

        raw_instructions = arguments.get("instructions")
        if not raw_instructions or not isinstance(raw_instructions, list):
            raise ToolError("subagents tool requires a non-empty 'instructions' list")

        # Validate each item has a non-empty 'instruction' string.
        items = []
        for i, item in enumerate(raw_instructions):
            if not isinstance(item, dict):
                raise ToolError(f"subagents: item {i} must be an object with 'instruction'")
            instruction = item.get("instruction")
            if not instruction or not isinstance(instruction, str):
                raise ToolError(f"subagents: item {i} is missing a required 'instruction' string")
            items.append(
                {
                    "instruction": instruction,
                    "engine": item.get("engine") or None,
                    "model": item.get("model") or None,
                }
            )

        # Fan-out cap: reserve one slot for the merge child.  The batch may have
        # at most MAX_SUBAGENT_FANOUT - 1 parallel children.
        _batch_cap = MAX_SUBAGENT_FANOUT - 1
        if len(items) > _batch_cap:
            raise ToolError(
                f"subagents fan-out limit ({_batch_cap} parallel children) exceeded; "
                f"got {len(items)} instructions (one slot is reserved for the merge child)"
            )

        try:
            batch_results = self._batch_spawn(items)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"subagents failed: {exc}") from exc

        self.sub_results.extend(batch_results)

        # Build a summary line: report each child's status + the merge outcome.
        lines = []
        for sub in batch_results:
            lines.append(f"  [{sub.engine}/{sub.model}] {sub.status}: {sub.summary}")
        result = f"subagents batch ({len(items)} children):\n" + "\n".join(lines)
        return ToolOutcome(result=self._truncate(result))

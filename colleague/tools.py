"""The tool surface the agentic loop offers an engine, plus a repo-confined executor.

Ten tools — ``read_file``, ``write_file``, ``edit_file``, ``list_dir``,
``run_command``, ``culture``, ``devague``, ``subagent``, ``subagents``, and
``finish`` — are exposed to the model as OpenAI function/tool schemas
(:data:`SCHEMAS`). :class:`ToolExecutor` runs a requested call against a fixed repo
root. ``edit_file`` (#174) is the partial-edit primitive: an exact-string replace
whose cost scales with the change, not the file size, so a scoped edit to a large
existing file no longer needs a whole-file ``write_file`` rewrite.

Confinement (honesty condition h3): ``read_file`` / ``write_file`` / ``edit_file`` /
``list_dir`` resolve their path against the root and refuse anything that escapes it
(``..`` traversal, absolute paths outside the tree); ``write_file`` and ``edit_file``
additionally refuse writes into the read-only neighbour clone tree. ``run_command``
runs with ``cwd`` pinned to the root. v0 trusts the command itself (decision D2);
sandboxing is a later wheel.

``read_file`` line-grounding (#240): the raw text the loop fed back to the model
carried no line markers, so a model citing "line N" had to re-count from its own
(possibly windowed/truncated) context — the root cause of a ~240-line citation
drift seen live in ``ask-colleague explore``. :func:`_number_lines` now prefixes
every real line with its true 1-based line number, ``cat -n`` style
(``"   12\t<content>"``), before the result is (still) run through
:meth:`ToolExecutor._truncate`, so a cited line number is copy-derived from tool
output, never re-counted, and any surviving prefix after truncation still names
the real file line. This is read-display only: numbering is never written to
disk and never round-trips into ``edit_file`` — ``_edit_file`` reads the file
itself via a separate ``path.read_text()`` call and matches ``old_string``
against that raw content, so a numbered prefix pasted from a ``read_file``
result will simply fail to match (by design).

A curated ``deepthink`` tool (:data:`DEEPTHINK_SCHEMA`, plan t4) is deliberately
kept OUT of :data:`SCHEMAS` — it is appended only by :func:`curate_schemas` when a
caller opts in (``deepthink=True``), which the loop does only when a dual-model
config is present. A single-model run offers exactly the schemas above.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess  # nosec B404 - running model-issued commands is the point (trusted, D2)
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from colleague.roles import Role

from colleague import culture, devague, media, memory, testintegrity
from colleague.config import _DEFAULT_MAX_OUTPUT_CHARS, MAX_SUBAGENT_FANOUT
from colleague.contract import SubResult

FINISH = "finish"
DEEPTHINK = "deepthink"

#: Shared description for the repo-relative ``path`` parameter, reused across the
#: file tool schemas (read_file / write_file / edit_file) so the literal lives once.
_PATH_DESC = "Path relative to the repo root."

#: Size cap for ``view_media`` files (task t5). Base64 inflates bytes ~4/3 and
#: the encoded part rides every subsequent windowed prompt, so the cap bounds
#: wire + context cost; a typical screenshot is well under it.
MAX_MEDIA_BYTES = 4 * 1024 * 1024

#: Bound a runaway model-issued command so it cannot stall the loop indefinitely
#: (mirrors culture/devague ``_TIMEOUT_SECONDS`` and neighbours ``_GIT_TIMEOUT_SECONDS``).
_COMMAND_TIMEOUT_SECONDS = 300

#: Timeout for the curated pytest runner (mirrors lint.py's _LINT_TIMEOUT).
_TESTS_TIMEOUT_SECONDS = 300


class ToolError(Exception):
    """A tool call that cannot be honored (bad path, escape attempt, missing file)."""


class UnknownToolError(ToolError):
    """A tool call naming a tool the harness does not have (#321).

    Distinguished from a plain :class:`ToolError` so the loop can tell a broken
    tool-call *protocol* (a name that can never exist — a serving-side parser /
    template mismatch, see #320) from an ordinary bad call to a real tool, and
    stop a run that would otherwise burn its whole step budget on them.
    """


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
    media_part: dict[str, Any] | None = None
    """An OpenAI content part produced by ``view_media`` (task t5), or ``None``
    for every other tool. The loop folds a non-None part into a follow-up user
    parts message — tool-message content itself stays a plain string (the
    wire-safe convention every OpenAI-compatible server accepts)."""


# OpenAI tool/function schemas — handed to the model verbatim in the loop.
SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file, relative to the repo root. Each line "
                "in the result is prefixed with its exact 1-based line number "
                "and a tab (cat -n style, e.g. '    12\\tsome code'), so you "
                "can cite an exact file:line location. The line-number prefix "
                "is DISPLAY ONLY — it is never part of the file on disk, so "
                "never include it in edit_file's old_string."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": _PATH_DESC}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_media",
            "description": (
                "Load an image file from the repo into the conversation so you "
                "can see it (the media sibling of read_file — read-only, "
                "repo-confined, images only). The image arrives as a content "
                "part on the next turn. Only useful when the serving model "
                "accepts image input; a text-only model will see a placeholder."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": _PATH_DESC}},
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
                    "path": {"type": "string", "description": _PATH_DESC},
                    "content": {"type": "string", "description": "Full file contents to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact string in an existing UTF-8 text file. Prefer this "
                "over write_file for ANY change to an existing file: it only needs the "
                "changed text, not the whole file, so it is far faster and cheaper on "
                "large files. 'old_string' must match the file exactly, including "
                "whitespace and indentation, and must be unique unless 'replace_all' is "
                "true. Use write_file only to create a new file or do a wholesale rewrite."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": _PATH_DESC},
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to replace (must match the file verbatim).",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Text to replace it with.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": (
                            "Replace every occurrence instead of requiring a unique "
                            "match (default false)."
                        ),
                    },
                },
                "required": ["path", "old_string", "new_string"],
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
                    "role": {
                        "type": "string",
                        "description": "Role name for the subagent (e.g. 'explorer', 'writer').",
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
                    "role": {
                        "type": "string",
                        "description": "Role name for the subagents (e.g. 'explorer', 'writer').",
                    },
                },
                "required": ["instructions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_test_integrity",
            "description": (
                "Check your changed test+impl files for the mirror signature (a novel "
                "symbol co-introduced in both a test and the module under test, found "
                "nowhere else) — a self-check against self-confirming tests."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run the repository's test suite via pytest. Optionally supply "
                "specific test paths to narrow the run. Read-only: this tool "
                "never writes files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of test file/module paths to pass to "
                            "pytest (e.g. ['tests/test_foo.py']). Omit to run "
                            "the full suite."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": (
                "Search or store memory records via the eidetic CLI. "
                "Use 'recall' to search for past context, 'remember' to "
                "store a new record."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verb": {
                        "type": "string",
                        "enum": ["recall", "remember"],
                        "description": (
                            "The memory operation: 'recall' to search, 'remember' to store."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for recall (required when verb=recall).",
                    },
                    "record": {
                        "type": "object",
                        "description": "Record dict to store (required when verb=remember).",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Max results for recall (default 5).",
                    },
                },
                "required": ["verb"],
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

#: The ``deepthink`` loop tool (plan t4 / spec c10(a), c5, h14) — a backend-judged
#: escalation the MAIN model MAY call mid-work to hand ONE hard judgment call to a
#: stronger, slower reasoning model. Deliberately kept OUT of the module-level
#: :data:`SCHEMAS` list (and therefore out of :data:`TOOL_NAMES`): a single-model
#: run must offer today's tool list byte-identically, so this schema is only ever
#: appended by :func:`curate_schemas` when the caller opts in (``deepthink=True``,
#: wired by the loop only when a dual-model config is present — task t5).
DEEPTHINK_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": DEEPTHINK,
        "description": (
            "Escalate ONE hard judgment call to a stronger, slower reasoning "
            "model — a verdict, a design decision, a plan critique. Use this to "
            "escalate JUDGMENT, never mechanical work: do NOT call it to read "
            "files, run commands, or make edits — do that yourself first, then "
            "escalate only the decision. Compose a SELF-CONTAINED 'question' (the "
            "judgment you want decided) plus an optional 'context' digest "
            "distilling the relevant code/diff/findings — the deepthink model "
            "sees ONLY what you pass here: it has no repo access, no tool "
            "access, and no conversation history, so the digest must fit its "
            "smaller context budget. It returns exactly one bounded text "
            "answer. Use sparingly: it is slower than the model driving this "
            "loop."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The judgment being escalated — a clear, self-contained "
                        "question (e.g. a verdict to render, a decision to make, "
                        "a plan to critique)."
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional self-composed digest of the relevant code, "
                        "diff, or findings — the ONLY context the deepthink "
                        "model will see, so include what it needs to answer "
                        "well. Keep it focused: it must fit the deepthink "
                        "model's (smaller) context budget."
                    ),
                },
            },
            "required": ["question"],
        },
    },
}


def curate_schemas(role: "Role | str | None", *, deepthink: bool = False) -> list[dict[str, Any]]:
    """Return only the schemas whose tool name is in *role*'s allow-list.

    Accepts a :class:`Role` instance, a role name string (looked up in
    :data:`colleague.roles.BUILTIN_ROLES`), or ``None`` meaning "full surface" —
    the historical shape callers relied on before curation existed (mirrors the
    ``curate_schemas(role) if role is not None else SCHEMAS`` guard at call
    sites). Names in the allow-list that are not present in :data:`SCHEMAS` are
    silently skipped.

    ``deepthink`` (default ``False`` — additive/opt-in, task t4) appends
    :data:`DEEPTHINK_SCHEMA` when the resolved role allows it (or *role* is
    ``None``, i.e. full surface). The deepthink schema is never part of
    :data:`SCHEMAS` itself, so a caller that never passes ``deepthink=True``
    sees a byte-identical schema list to before this feature existed — a
    single-model run (no dual-model config) never opts in, so it is offered
    today's tool list exactly.
    """
    from colleague.roles import BUILTIN_ROLES, Role

    allow: Optional[set[str]]
    if role is None:
        allow = None  # None = no filtering, full surface
    elif isinstance(role, str):
        role_obj = BUILTIN_ROLES.get(role)
        if role_obj is None:
            raise ValueError(f"unknown role '{role}'")
        allow = set(role_obj.tool_allowlist)
    elif isinstance(role, Role):
        allow = set(role.tool_allowlist)
    else:
        raise TypeError(f"curate_schemas expects a Role or role name, got {type(role).__name__}")

    curated = [s for s in SCHEMAS if allow is None or s["function"]["name"] in allow]
    if deepthink and (allow is None or DEEPTHINK in allow):
        curated = curated + [DEEPTHINK_SCHEMA]
    return curated


#: Column width for the ``cat -n`` style line-number prefix (matches GNU
#: ``cat -n``'s default right-justified 6-column number).
_LINE_NUMBER_WIDTH = 6


def _number_lines(text: str) -> str:
    """Ground *text* for citation: prefix every real line with its true line number.

    ``cat -n`` style — ``f"{n:6d}\\t{line}"`` — so a model quoting a result line
    is quoting a copy-derived ``file:line``, never a re-counted one (issue #240:
    a served model citing "line N" from its own windowed/truncated context
    drifted by ~240 lines from the real file). Splits on bare ``"\\n"`` only,
    NOT :meth:`str.splitlines`, which also breaks on ``\\v``/``\\f``/``\\x1c``-``\\x1e``/
    ``\\x85``/``\\u2028``/``\\u2029`` — a wider set that would silently invent phantom
    line boundaries a real ``grep -n``/editor would never count. A trailing
    newline terminates the last line without minting a phantom extra line (the
    same convention as ``cat -n``/``grep -n``); an empty file grounds to an
    empty string (no lines to number).

    Display-only: the numbering is never written to disk and never read back
    by ``edit_file`` — that tool re-reads the file itself and matches
    ``old_string`` against the raw, unnumbered content.
    """
    if text == "":
        return ""
    body = text[:-1] if text.endswith("\n") else text
    lines = body.split("\n")
    return "\n".join(f"{i:{_LINE_NUMBER_WIDTH}d}\t{line}" for i, line in enumerate(lines, start=1))


def _require(arguments: dict[str, Any], key: str, tool: str) -> Any:
    """Fetch a required tool argument or raise a self-correcting :class:`ToolError`.

    A served model sometimes emits a tool call with empty/missing arguments
    (live: work item ``4c6a96107269`` died at step 12 when a bare
    ``arguments["path"]`` raised ``KeyError`` and escaped the dispatch, which
    caught only ``ToolError`` — aborting a 12-step run with 4 folded
    sub-results). A missing required argument is a MODEL error, not a harness
    bug: it must cost one non-ok step carrying a message the model can act on,
    never the run.
    """
    if key not in arguments:
        raise ToolError(f"{tool} requires '{key}'")
    return arguments[key]


def _parse_batch_items(raw_instructions: list) -> list[dict[str, Any]]:
    """Validate + normalize the ``subagents`` tool's instruction items.

    Each item must be an object carrying a non-empty ``instruction`` string;
    ``engine``/``model``/``role`` are optional. Extracted from
    :meth:`ToolExecutor._subagents` to keep that method's cognitive complexity
    within budget (SonarCloud S3776).
    """
    items: list[dict[str, Any]] = []
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
                "role": item.get("role") or None,
            }
        )
    return items


class ToolExecutor:
    """Executes tool calls against a single repo root, confining file access to it."""

    def __init__(
        self,
        root: str | Path,
        *,
        spawn=None,
        batch_spawn=None,
        deepthink: Callable[..., Any] | None = None,
        max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
        allowlist: "Role | tuple[str, ...] | None" = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.changed: set[str] = set()
        # Total UTF-8 bytes the model authored into files via write_file/edit_file
        # across the work item — the exact "tokens written" measure (no tokenizer, so
        # bytes not tokens). An edit_file contributes only its replacement bytes, not
        # the whole file, so this stays the honest cost-of-output signal. The loop
        # snapshots it onto WorkStats, mirroring the changed_files snapshot.
        self.bytes_written: int = 0
        self._spawn = spawn
        # Batch spawn callable: ``batch_spawn(items) -> list[SubResult]``.
        # Injected by the loop (t5); None means the subagents tool is unavailable.
        self._batch_spawn = batch_spawn
        # Deepthink escalation callable (t5): the bound ``DeepthinkRun`` seam,
        # ``deepthink(question, context, *, point="tool") -> DeepthinkResult``
        # (:func:`colleague.deepthink.make_deepthink_run`). Injected by the engine
        # only when a dual-model config is present; None means the deepthink tool
        # is unavailable for this drive — the schema should not have been offered
        # in that case (curate_schemas gates it), but a hallucinated call is
        # handled defensively (see ``_deepthink_tool``). A plain str-returning
        # callable is still honored (back-compat: answers, records nothing).
        self._deepthink = deepthink
        # Every DeepthinkCall record the tool dispatch accumulated, in firing
        # order. The loop snapshots this onto ``TaskResult.deepthink`` (spec c14)
        # exactly like ``sub_results`` — empty stays empty → omitted artifact key.
        self.deepthink_calls: list[Any] = []
        # Cap on each tool result fed back to the model so a huge file/command
        # can't blow the context window. Resolved from EngineConfig (env
        # COLLEAGUE_MAX_OUTPUT_CHARS); sized for the served model's window.
        self._max_output_chars = max_output_chars
        self.sub_results: list[SubResult] = []
        # Optional role-aware allow-list: when set, only listed tools may be
        # dispatched; everything else raises ToolError.  Accepts a Role object
        # (uses role.tool_allowlist) or a plain tuple of tool-name strings.
        if allowlist is None:
            self._allowlist: set[str] | None = None
        elif hasattr(allowlist, "tool_allowlist"):
            self._allowlist = set(allowlist.tool_allowlist)
        else:
            self._allowlist = set(allowlist)

        # Read-only flag for role-aware tool restrictions (e.g. memory remember)
        self._is_read_only: bool = False
        if hasattr(allowlist, "read_only"):
            self._is_read_only = allowlist.read_only

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

    def _refuse_clone_write(self, path: Path, rel: str) -> None:
        """Refuse a write into the neighbour clone tree (honesty condition h12).

        Neighbour clones are read-only source: the model may read them but never
        write into them. ``_safe_path`` only confines to the repo root, which
        includes the clone tree — so every write path (write_file, edit_file)
        guards explicitly via this helper.
        """
        clone_root = (self.root / self._CLONE_SUBDIR).resolve()
        if path == clone_root or clone_root in path.parents:
            raise ToolError(
                f"write refused: '{rel}' is inside the neighbour clone directory "
                f"('{self._CLONE_SUBDIR}'), which is read-only source. "
                "Clones are inert — they may be read, never written."
            )

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch a single tool call by name to its handler.

        Returns the matching handler's ToolOutcome.  When an allow-list is active
        (set via ``allowlist`` on construction), tools not in the list raise
        :class:`ToolError` instead of being executed.
        """
        if self._allowlist is not None and name not in self._allowlist:
            raise ToolError(f"tool '{name}' is not allowed for this role")
        # Table-driven dispatch (was a long if-chain; flattened to keep cognitive
        # complexity in budget — S3776). check_test_integrity takes no args.
        dispatch = {
            "read_file": self._read_file,
            "view_media": self._view_media,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "list_dir": self._list_dir,
            "run_command": self._run_command,
            "culture": self._culture,
            "devague": self._devague,
            "memory": self._memory,
            "subagent": self._subagent,
            "subagents": self._subagents,
            "run_tests": self._run_tests,
            "check_test_integrity": lambda _a: self._check_test_integrity(),
            DEEPTHINK: self._deepthink_tool,
            FINISH: self._finish,
        }
        handler = dispatch.get(name)
        if handler is None:
            raise UnknownToolError(
                f"unknown tool '{name}' — valid tools: {', '.join(sorted(dispatch))}"
            )
        try:
            return handler(arguments)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - defense-in-depth (#269)
            # A handler crash on model-supplied input is a MODEL-visible step
            # error, never a run abort: the per-arg `_require` guards cover the
            # known required keys, but any future unguarded KeyError/TypeError in
            # a handler must still bounce back to the model as a self-correcting
            # observation naming the tool (the live 1.30.0 failure aborted a
            # flight with a bare "'path'" — unknown-tool errors already recovered,
            # malformed-call errors must behave the same).
            raise ToolError(
                f"{name} failed: {type(exc).__name__}: {exc} — check the tool's "
                f"argument schema and retry"
            ) from exc

    def _finish(self, arguments: dict[str, Any]) -> ToolOutcome:
        """The ``finish`` tool — record the terminal summary + optional destination."""
        return ToolOutcome(
            result="finished",
            finished=True,
            finish_summary=str(arguments.get("summary", "")),
            destination=arguments.get("destination") or None,
            announcement=arguments.get("announcement") or None,
        )

    def _read_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        path = self._safe_path(str(_require(arguments, "path", "read_file")))
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ToolError(f"no such file: {arguments['path']}") from exc
        except OSError as exc:
            raise ToolError(f"cannot read {arguments['path']}: {exc}") from exc
        # Ground every line with its true 1-based number BEFORE truncating (#240)
        # so a surviving line's prefix always matches the real file — truncation
        # only ever drops the tail, never renumbers what remains — and the
        # existing max_output_chars budget still bounds the final string.
        return ToolOutcome(result=self._truncate(_number_lines(text)))

    def _view_media(self, arguments: dict[str, Any]) -> ToolOutcome:
        """The ``view_media`` tool (t5) — load a repo image as a content part.

        Pure read: same ``_safe_path`` confinement as ``read_file``, a byte cap
        (:data:`MAX_MEDIA_BYTES`) so one call can't flood the wire/context, and
        images only — audio has no mid-work read use while the serving rig
        drops it, and ``validate_attachment`` already rejects non-media.
        """
        rel = str(_require(arguments, "path", "view_media"))
        path = self._safe_path(rel)
        if not path.is_file():
            raise ToolError(f"no such file: {rel}")
        size = path.stat().st_size
        if size > MAX_MEDIA_BYTES:
            raise ToolError(
                f"cannot view {rel}: {size} bytes exceeds the {MAX_MEDIA_BYTES}-byte "
                "media size cap"
            )
        try:
            attachment = media.validate_attachment(str(path))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        if not attachment["media_type"].startswith("image/"):
            raise ToolError(f"view_media is images only: {rel} is {attachment['media_type']}")
        try:
            part = media.build_part(attachment)
        except OSError as exc:
            raise ToolError(f"cannot read {rel}: {exc}") from exc
        return ToolOutcome(
            result=f"loaded image {rel} ({size} bytes) into the conversation",
            media_part=part,
        )

    def _write_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        rel = str(_require(arguments, "path", "write_file"))
        path = self._safe_path(rel)
        self._refuse_clone_write(path, rel)
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

    def _edit_file(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Replace an exact string in an existing file (partial edit, #174).

        Edit cost scales with the change, not the file size — the structural fix
        for full-file ``write_file`` timing out on large existing files. ``old_string``
        must be unique unless ``replace_all`` is set.
        """
        rel = str(_require(arguments, "path", "edit_file"))
        path = self._safe_path(rel)
        self._refuse_clone_write(path, rel)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ToolError(
                f"no such file: {rel} (edit_file only edits existing files; "
                "use write_file to create)"
            ) from exc
        except UnicodeDecodeError as exc:
            raise ToolError(
                f"cannot edit {rel}: not valid UTF-8 text (edit_file works on text files)"
            ) from exc
        except OSError as exc:
            raise ToolError(f"cannot read {rel}: {exc}") from exc

        old = str(_require(arguments, "old_string", "edit_file"))
        new = str(_require(arguments, "new_string", "edit_file"))
        replace_all = bool(arguments.get("replace_all", False))
        if old == "":
            raise ToolError("old_string must be non-empty; use write_file to create a file")
        if old == new:
            raise ToolError("old_string and new_string are identical (no-op edit)")
        count = text.count(old)
        if count == 0:
            raise ToolError(
                f"old_string not found in {rel} (it must match the file exactly, "
                "including whitespace and indentation)"
            )
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string is not unique in {rel} ({count} matches); add surrounding "
                "context to disambiguate, or set replace_all=true"
            )

        replacements = count if replace_all else 1
        # The guards above leave exactly two cases here: replace_all (any count) or a
        # single unique match. The `1` cap is the explicit single-replace for the
        # latter — not dead code, it documents that a non-replace_all edit touches one
        # occurrence. str.replace is a single left-to-right pass, so a new_string that
        # contains old_string is NOT re-scanned (no runaway expansion).
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        # newline="" keeps the on-disk bytes byte-deterministic cross-platform,
        # exactly as _write_file does. Translate a write failure (permissions,
        # read-only, IO error) into a ToolError so the loop records a recoverable
        # failed step instead of aborting the work item (the loop only catches
        # ToolError around tool execution).
        try:
            path.write_text(updated, encoding="utf-8", newline="")
        except OSError as exc:
            raise ToolError(f"cannot write {rel}: {exc}") from exc
        self.changed.add(rel)
        # Account only the bytes this edit authored into the file (replacement text
        # times the occurrences replaced) — the honest cost-of-output signal that
        # makes an edit's ROI visible against a full-file rewrite (#174).
        self.bytes_written += replacements * len(new.encode("utf-8"))
        plural = "occurrence" if replacements == 1 else "occurrences"
        return ToolOutcome(
            result=f"edited {rel}: replaced {replacements} {plural}", changed_file=rel
        )

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
        command = str(_require(arguments, "command", "run_command"))

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

    def _memory(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the memory tool to the eidetic CLI via colleague.memory.

        Enforces role-aware verb restrictions: read-only roles may only use
        'recall' (search); 'remember' (store) is refused with a clear error.
        When the eidetic CLI is absent, recall returns an empty JSON array
        and remember returns 'ok' — never crashes.
        """
        verb = str(arguments.get("verb", ""))
        if verb not in ("recall", "remember"):
            raise ToolError("memory tool requires verb 'recall' or 'remember'")

        # Role-aware refusal: read-only roles cannot use 'remember'
        if verb == "remember" and self._is_read_only:
            raise ToolError(
                "memory 'remember' is not allowed for read-only roles; "
                "use 'recall' to search instead"
            )

        if verb == "recall":
            query = str(arguments.get("query", ""))
            if not query:
                raise ToolError("memory 'recall' requires a 'query' string")
            top_k = int(arguments.get("top_k", 5))
            hits = memory.recall(self.root, query, top_k=top_k)
            # Bounded like every other tool result (PR #267 review): a store
            # with huge records must not blow the tool-output budget.
            return ToolOutcome(result=self._truncate(json.dumps(hits)))
        else:
            # verb == "remember"
            record = arguments.get("record")
            if not isinstance(record, dict):
                raise ToolError("memory 'remember' requires a 'record' object")
            ok = memory.remember(self.root, record)
            return ToolOutcome(result="ok" if ok else "failed")

    def _deepthink_tool(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Dispatch the ``deepthink`` tool to the injected one-shot escalation seam.

        The actual completion call (windowing to the deepthink model's own budget,
        the tools-off invariant, degradation) lives in the injected ``deepthink``
        callable (set by the loop only when a dual-model config is present — task
        t5, see :func:`colleague.deepthink.run_deepthink`); here we validate the
        inputs and translate a missing seam into a clean, non-crashing result
        string.

        Defensive floor (never raises for a missing seam): ``curate_schemas``
        only offers :data:`DEEPTHINK_SCHEMA` when a role allows it AND the loop
        opted in, so a live drive should never reach this branch with
        ``self._deepthink is None`` — but a hallucinated call must still degrade
        gracefully rather than crash the drive.
        """
        question = arguments.get("question")
        if not question or not isinstance(question, str):
            raise ToolError("deepthink tool requires a 'question'")
        context = str(arguments.get("context") or "")

        if self._deepthink is None:
            return ToolOutcome(result="deepthink is not configured for this run")

        try:
            answer = self._deepthink(question, context)
        except Exception as exc:  # the injected seam degrades internally; defense-in-depth
            raise ToolError(f"deepthink failed: {exc}") from exc

        # The bound DeepthinkRun seam returns a DeepthinkResult carrying its call
        # record — accumulate it for the loop's TaskResult.deepthink snapshot
        # (spec c14) and translate a degraded escalation into an honest notice
        # (spec c13: the model proceeds on its own judgment, the run never fails).
        call = getattr(answer, "call", None)
        if call is not None:
            self.deepthink_calls.append(call)
            if getattr(call, "degraded", False):
                return ToolOutcome(
                    result="deepthink is unavailable (degraded) — proceed with your own judgment."
                )
            return ToolOutcome(result=self._truncate(str(getattr(answer, "text", ""))))
        # Back-compat: a plain str-returning seam answers but records nothing.
        return ToolOutcome(result=self._truncate(str(answer)))

    def _check_test_integrity(self) -> ToolOutcome:
        """Run the mirror-detection heuristic on the work item's changed files.

        Takes no arguments — it inspects the work item's already-changed files
        (``self.changed``), so the schema declares no parameters.
        """
        report = testintegrity.detect_mirror(str(self.root), sorted(self.changed))
        if not report.findings:
            return ToolOutcome(result="no mirror findings")
        lines = [
            f"  {f.symbol} ({f.kind}) in {f.test_file} + {f.impl_file}" for f in report.findings
        ]
        return ToolOutcome(result="mirror findings:\n" + "\n".join(lines))

    def _run_tests(self, arguments: dict[str, Any]) -> ToolOutcome:
        """Run the repository's test suite via pytest.

        Curated runner: the command is fixed to ``python -m pytest [paths]`` —
        never taken from the model, so a read-only validator role can run tests
        without access to ``run_command``. Mirrors lint.py's ``_run`` pattern
        (curated program set, per-call timeout, graceful degradation).

        Returns a concise pass/fail summary string.  Never writes files.
        """
        raw_paths: list[str] = arguments.get("paths") or []
        # Confine + de-weaponize the model-supplied paths (#t4 Q2): reject option-like
        # args and anything escaping the repo root, then pass them AFTER ``--`` so
        # pytest treats every one as a POSITIONAL test path, never an option — closing
        # the ``--junitxml=…`` / ``-p plugin`` injection that could write a file or
        # load arbitrary code despite the validator role being "read-only".
        safe_paths: list[str] = []
        for p in raw_paths:
            if not isinstance(p, str) or p.startswith("-"):
                return ToolOutcome(result=f"run_tests skipped: invalid test path {p!r}")
            try:
                self._safe_path(p)
            except ToolError:
                return ToolOutcome(result=f"run_tests skipped: path {p!r} escapes the repo root")
            safe_paths.append(p)
        # Keep the validator role's "never writes files" promise literally true
        # (#221 qodo): pytest/python otherwise drop ``.pytest_cache`` and
        # ``__pycache__`` into the tree. ``-p no:cacheprovider`` disables pytest's
        # cache plugin and ``PYTHONDONTWRITEBYTECODE=1`` stops bytecode caches, so a
        # read-only run leaves the tree byte-identical.
        cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--", *safe_paths]
        # The ``--`` separator de-weaponizes CLI args but NOT the env: pytest honors
        # ``PYTEST_ADDOPTS`` (arbitrary options) and ``PYTEST_PLUGINS`` (arbitrary
        # plugin imports) from the environment regardless. Strip both so an inherited
        # env can't re-open the option/plugin-injection vector behind the validator's
        # back, and disable bytecode caches to keep the tree byte-identical.
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("PYTEST_ADDOPTS", None)
        env.pop("PYTEST_PLUGINS", None)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                check=False,
                timeout=_TESTS_TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolOutcome(
                result=f"run_tests skipped: timed out after {_TESTS_TIMEOUT_SECONDS}s"
            )
        except (OSError, ValueError) as exc:
            return ToolOutcome(result=f"run_tests skipped: {exc}")

        body = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            return ToolOutcome(result="tests passed")
        # Non-zero: include last ~20 lines of output for context.
        last_lines = "\n".join(body.splitlines()[-20:])
        return ToolOutcome(result=f"tests FAILED (exit={proc.returncode})\n{last_lines}")

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
        role = arguments.get("role") or None

        if len(self.sub_results) >= MAX_SUBAGENT_FANOUT:
            raise ToolError(
                f"subagent fan-out limit ({MAX_SUBAGENT_FANOUT}) reached for this drive"
            )

        try:
            sub = self._spawn(instruction, engine, model, role)
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

        # Validate + normalize each item (extracted to keep this method's cognitive
        # complexity in budget — S3776).
        items = _parse_batch_items(raw_instructions)

        # Batch-level role (#t4): applies to every child unless an item set its own.
        batch_role = arguments.get("role") or None

        # Fan-out cap: reserve one slot for the merge child — EXCEPT for a batch
        # whose children are ALL read-only roles (t12): they provably cannot
        # write, so the merge child is a structural no-op and the reservation
        # is freed (the full MAX_SUBAGENT_FANOUT is usable).
        from colleague.roles import is_read_only

        all_read_only = bool(items) and all(
            is_read_only(item.get("role") or batch_role) for item in items
        )
        _batch_cap = MAX_SUBAGENT_FANOUT if all_read_only else MAX_SUBAGENT_FANOUT - 1
        if len(items) > _batch_cap:
            reason = (
                "the read-only batch limit"
                if all_read_only
                else "one slot is reserved for the merge child"
            )
            raise ToolError(
                f"subagents fan-out limit ({_batch_cap} parallel children) exceeded; "
                f"got {len(items)} instructions ({reason})"
            )

        try:
            batch_results = self._batch_spawn(items, batch_role)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"subagents failed: {exc}") from exc

        self.sub_results.extend(batch_results)
        # Merge every child's changed files into the parent tracker (#263) — the
        # single-`subagent` path already does this (see `_subagent`); without it a
        # batch child's edits are invisible to the artifact's `changed_files` AND
        # to every changed-file-scoped pre-handoff gate (lint / test-integrity /
        # affected-tests), silently under-scoping all three.
        for sub in batch_results:
            self.changed.update(sub.changed_files)

        # Build a summary line: report each child's status + the merge outcome.
        lines = []
        for sub in batch_results:
            lines.append(f"  [{sub.engine}/{sub.model}] {sub.status}: {sub.summary}")
        result = f"subagents batch ({len(items)} children):\n" + "\n".join(lines)
        return ToolOutcome(result=self._truncate(result))

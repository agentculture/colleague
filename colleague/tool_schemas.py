"""OpenAI tool/function schemas for the loop's tool surface, plus curation.

Split out of :mod:`colleague.tools` (plan `hard-1000-line-file-limit`, task t5)
to keep that module under the repo's file-length gate: this sibling carries
the pure data/helpers — :data:`SCHEMAS`, :data:`TOOL_NAMES`,
:data:`DEEPTHINK_SCHEMA`, :func:`curate_schemas`, and
:func:`narrow_role_by_tool_set` — while :class:`colleague.tools.ToolExecutor`
(the subprocess/threading-using half) stays in ``tools.py``. Every name here
is re-exported from :mod:`colleague.tools` so every existing
``from colleague.tools import ...`` call site keeps resolving unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from colleague.roles import Role

import colleague.hire_schemas as hire_schemas
import colleague.purpose_schemas as purpose_schemas
import colleague.search_schemas as search_schemas
import colleague.web_schemas as web_schemas
from colleague import culture, devague, readpage

FINISH = "finish"
DEEPTHINK = "deepthink"

#: Shared description for the repo-relative ``path`` parameter, reused across the
#: file tool schemas (read_file / write_file / edit_file) so the literal lives once.
_PATH_DESC = "Path relative to the repo root."


SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file (relative to the repo root), cat -n style: every line is "
                "prefixed with its exact 1-based number + a tab (DISPLAY ONLY — never put it in "
                "edit_file's old_string). Long files are paged: pass offset (1-based first line) "
                "and limit (line count); a cut result ends with 'Read lines X-Y of N' — page on."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": _PATH_DESC},
                    "offset": {"type": "integer", "description": readpage.OFFSET_DESC},
                    "limit": {"type": "integer", "description": readpage.LIMIT_DESC},
                },
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
    *search_schemas.SEARCH_SCHEMAS,
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
    web_schemas.WEB_SCHEMA,
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
                    "profile": {
                        "type": "string",
                        "description": (
                            "Agent purpose for the child (agents mode, #411): one of "
                            "'thinker_coder', 'associate', 'worker', 'talker' — binds the "
                            "child to that purpose's lobes role when served (a recorded "
                            "cortex fallback otherwise); omit to inherit the parent's seat."
                        ),
                    },
                    "context_mode": {
                        "type": "string",
                        "enum": ["inherit", "clear"],
                        "description": (
                            "'inherit' (default) carries the parent context; 'clear' gives the "
                            "child a fresh mind with only a handover summary (use for reviewers)."
                        ),
                    },
                    "effort": {
                        "type": "string",
                        "enum": ["off", "low", "medium", "high", "xhigh", "default"],
                        "description": (
                            "Optional thinking-effort override for the subagent (#416). Omit to "
                            "let the child resolve its own rung from its role/seat; 'default' "
                            "sends no effort hint at all."
                        ),
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
                                "effort": {
                                    "type": "string",
                                    "enum": ["off", "low", "medium", "high", "xhigh", "default"],
                                    "description": (
                                        "Optional per-child thinking-effort override (#416). "
                                        "Omit to let the child resolve its own rung from its "
                                        "role/seat; 'default' sends no effort hint at all."
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
#: escalation to a stronger, slower reasoning model. Kept OUT of :data:`SCHEMAS` /
#: :data:`TOOL_NAMES`; appended by :func:`curate_schemas` only when opted in
#: (``deepthink=True``, wired by the loop only for a dual-model config).
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


def curate_schemas(
    role: "Role | str | None", *, deepthink: bool = False, config: Any = None
) -> list[dict[str, Any]]:
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

    curated = [
        s
        for s in SCHEMAS
        if search_schemas.offered(s["function"]["name"], allow)
        and web_schemas.offered(s["function"]["name"], allow)
    ]
    if deepthink and (allow is None or DEEPTHINK in allow):
        curated = curated + [DEEPTHINK_SCHEMA]
    # Purpose tools (t5): spliced only for a concrete role's allow-list — a
    # bare full surface (allow is None) stays byte-identical, unaffected.
    if allow is not None:
        curated = curated + [
            purpose_schemas.PURPOSE_SCHEMAS[n]
            for n in purpose_schemas.PURPOSE_TOOL_NAMES
            if purpose_schemas.offered(n, allow)
        ]
        # Hire tools (delegation-follow-ups t10, c17/h8): appended exactly as
        # the purpose schemas above, and hidden — BOTH names — unless the
        # resolved ``config.hire`` flag is armed (``config`` is the resolved
        # EngineConfig threaded from the caller; ``None`` = unarmed,
        # byte-identical). The full raw surface (allow is None) stays pinned
        # and never carries them, exactly like the purpose splice.
        curated = curated + [
            hire_schemas.HIRE_SCHEMAS[n]
            for n in hire_schemas.HIRE_TOOL_NAMES
            if hire_schemas.offered(n, allow, config)
        ]
    return curated


def narrow_role_by_tool_set(
    role: "Role | str | None",
    tool_set: tuple[str, ...] = (),
    drop: tuple[str, ...] = (),
) -> "Role | str | None":
    """Compose *role*'s curated surface with a config-lifecycle ``tool_set`` narrowing.

    The change-content consumption lane (plan task t3, spec c8/h8): when a
    cortex-applied ``worker.tools`` proposal narrows the episode's
    ``EpisodeConfigSnapshot.tool_set`` (``colleague/configlifecycle.py``), the
    value this function returns is handed to BOTH :func:`curate_schemas` (the
    offered-schema half of the existing role mechanism) and
    :class:`ToolExecutor`'s existing ``allowlist=`` seam (the refusal half) —
    the SAME composed value threads through both, so the two halves can never
    diverge and no second refusal mechanism is ever needed. Both call sites
    keep writing ``allowlist=role`` / ``curate_schemas(role, ...)`` — *role*
    is simply this function's return value instead of the raw resolved role.

    ``tool_set`` empty/default — the snapshot's not-narrowed value (c26 made
    narrow-to-nothing unrepresentable at the lattice: an empty ``tool_ids``
    list refuses whole before it can ever reach a snapshot) — returns *role*
    unchanged, byte-identical to today on both engines.

    Non-empty narrows the role-curated surface down to its INTERSECTION with
    ``tool_set``: a ``tool_set`` entry outside *role*'s surface adds nothing
    (narrowing only ever removes tools, never adds one the role withholds).
    *role* ``None`` (the pre-role "full surface" default) narrows straight to
    ``tool_set`` (minus ``drop``, in ``tool_set`` order); the returned
    synthetic :class:`Role` is non-read-only
    (``None`` meant unrestricted). :data:`SCHEMAS`'s silent-unknown-name skip
    and :class:`ToolExecutor`'s exact-name check do the rest, so an
    unresolvable name in ``tool_set`` is simply never offered/callable.

    ``drop`` (plan t8, the acting-seat-scoped drop knob): a NAMED drop-set
    applied AFTER the ``tool_set`` intersection — the tools the acting seat
    must not offer or call (``COLLEAGUE_ACTING_DROP_TOOLS``). Same single
    composed value, so a dropped tool is hidden from the schema AND refused
    at dispatch — no second refusal mechanism. Empty ``drop`` (the default)
    is a strict no-op. *role* ``None`` + a non-empty ``drop`` narrows the
    FULL surface (:data:`TOOL_NAMES`) to everything-but-the-drop; dropping
    only ever removes tools, never adds one.
    """
    if not tool_set and not drop:
        return role
    from colleague.roles import BUILTIN_ROLES, Role

    keep = set(tool_set)
    drop_set = set(drop)
    if role is None:
        source = tool_set if tool_set else TOOL_NAMES
        allowlist = tuple(t for t in source if t not in drop_set)
        return Role(
            name="narrowed",
            prompt_fragment="",
            tool_allowlist=allowlist,
            skill_subset=None,
            read_only=False,
        )
    if isinstance(role, str):
        role_obj = BUILTIN_ROLES.get(role)
        if role_obj is None:
            raise ValueError(f"unknown role '{role}'")
        role = role_obj
    if isinstance(role, Role):
        narrowed_allowlist = tuple(
            t for t in role.tool_allowlist if (not tool_set or t in keep) and t not in drop_set
        )
        return replace(role, tool_allowlist=narrowed_allowlist)
    raise TypeError(
        f"narrow_role_by_tool_set expects a Role, role name, or None, got {type(role).__name__}"
    )

"""``grep_search`` + ``glob`` — the tool declarations and dispatch glue (plan t14).

The search backends live in :mod:`colleague.search_tools` (plan t5); this
module is the thin layer that puts them on the model's tool surface: the two
OpenAI function schemas (spliced into :data:`colleague.tools.SCHEMAS`), the
executor-side handlers (spliced into ``ToolExecutor.execute``'s dispatch
table), the plain-text rendering of results, and the ``COLLEAGUE_TOOLS_LEGACY``
knob that hides both tools again — the byte-identical proof path (h1/c44):
with the knob set, ``curate_schemas`` offers exactly the pre-arc surface and a
dispatch attempt is refused with a clear error.

adapted-from: qwen-code packages/core/src/tools/ripGrep.ts, tools/grep.ts,
tools/glob.ts (the tool declarations: name, description, parameter shape).
Copyright 2025 Google LLC, Copyright 2026 Qwen Team, Apache-2.0.

Both tools are read-only and repo-confined (``search_tools.confine`` mirrors
``read_file``'s resolve()-based check) and are listed in
:data:`colleague.toolbatch.CONCURRENCY_SAFE_TOOLS` — a batch of searches may
run in parallel (plan t15). Output goes through the same truncation as every
other tool (:mod:`colleague.truncation` via ``ToolExecutor._truncate``).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — search_tools imports tools.ToolError at module top
    from colleague.search_tools import SearchMatch

__all__ = [
    "GLOB_SCHEMA",
    "GREP_SEARCH_SCHEMA",
    "LEGACY_ENV",
    "SEARCH_SCHEMAS",
    "DEFAULT_MAX_RESULTS",
    "SEARCH_TOOL_NAMES",
    "dispatch",
    "hidden_names",
    "offered",
    "legacy_hidden",
    "render_matches",
    "render_paths",
    "run_glob",
    "run_grep_search",
]

#: The knob that hides both tools (schemas AND dispatch) — the pre-arc surface.
LEGACY_ENV = "COLLEAGUE_TOOLS_LEGACY"

#: The two tool names this module contributes to the surface.
SEARCH_TOOL_NAMES: tuple[str, ...] = ("grep_search", "glob")

_PATH_DESC = "Directory relative to the repo root to search under (default: the whole repo)."
#: Mirrors ``search_tools.DEFAULT_MAX_RESULTS`` (pinned by a test; not imported here
#: because search_tools imports ``tools.ToolError`` at module top — a cycle at import time).
DEFAULT_MAX_RESULTS = 200

_MAX_RESULTS_DESC = (
    f"Cap on returned matches (default {DEFAULT_MAX_RESULTS}); "
    "narrow the pattern or path instead of raising it."
)

GREP_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "grep_search",
        "description": (
            "Search file CONTENTS for a regular expression (ripgrep-style, case-insensitive; "
            "Python re syntax) under the repo root. Returns 'path:line: text' hits sorted by "
            "path then line. Prefer this over run_command grep/rg — it is read-only, "
            "repo-confined and may run in parallel with other reads. Narrow with path "
            "(a subdirectory) and/or glob (a filename pattern such as '*.py')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The regular expression to find."},
                "path": {"type": "string", "description": _PATH_DESC},
                "glob": {
                    "type": "string",
                    "description": "Only search files whose name matches this glob (e.g. '*.py').",
                },
                "max_results": {"type": "integer", "description": _MAX_RESULTS_DESC},
            },
            "required": ["pattern"],
        },
    },
}

GLOB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "glob",
        "description": (
            "Find FILES by name pattern (ripgrep/gitignore-style glob: '*', '?', '[seq]', "
            "'**' for any depth, e.g. 'tests/**/test_*.py') under the repo root, newest "
            "modification first. Prefer this over run_command find/ls — read-only, "
            "repo-confined, parallel-safe. Use grep_search to look INSIDE files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The glob pattern to match."},
                "path": {"type": "string", "description": _PATH_DESC},
                "max_results": {"type": "integer", "description": _MAX_RESULTS_DESC},
            },
            "required": ["pattern"],
        },
    },
}

#: The schemas in the order they join :data:`colleague.tools.SCHEMAS`.
SEARCH_SCHEMAS: list[dict[str, Any]] = [GREP_SEARCH_SCHEMA, GLOB_SCHEMA]

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def legacy_hidden() -> bool:
    """``True`` when ``COLLEAGUE_TOOLS_LEGACY`` asks for the pre-arc tool surface."""
    return os.environ.get(LEGACY_ENV, "").strip().lower() in _TRUTHY


def hidden_names() -> frozenset[str]:
    """The tool names ``curate_schemas`` must drop right now (empty unless legacy)."""
    return frozenset(SEARCH_TOOL_NAMES) if legacy_hidden() else frozenset()


def offered(name: str, allow: "set[str] | None") -> bool:
    """``curate_schemas``'s filter: in *allow* (``None`` = full surface) and not hidden."""
    return (allow is None or name in allow) and name not in hidden_names()


def render_matches(matches: "Sequence[SearchMatch]", *, capped: bool) -> str:
    """Render grep hits as ``path:line: text`` lines (a stable, greppable shape)."""
    if not matches:
        return "no matches"
    lines = [f"{m.path}:{m.line}: {m.text}" for m in matches]
    if capped:
        lines.append(f"... [capped at {len(matches)} matches — narrow the pattern or path]")
    return "\n".join(lines)


def render_paths(paths: Sequence[str], *, capped: bool) -> str:
    """Render glob results one path per line, newest first."""
    if not paths:
        return "no files match"
    lines = list(paths)
    if capped:
        lines.append(f"... [capped at {len(paths)} files — narrow the pattern or path]")
    return "\n".join(lines)


def _require_pattern(arguments: dict[str, Any], tool: str) -> str:
    from colleague.tools import ToolError  # local: tools.py imports this module

    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ToolError(f"{tool} needs a non-empty 'pattern' argument")
    return pattern


def _max_results(arguments: dict[str, Any], tool: str) -> int:
    from colleague.tools import ToolError  # local: tools.py imports this module

    raw = arguments.get("max_results", DEFAULT_MAX_RESULTS)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ToolError(f"{tool}: max_results must be a positive integer, got {raw!r}")
    return raw


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value)


def run_grep_search(root: Path, arguments: dict[str, Any]) -> str:
    """Execute one ``grep_search`` call and return its rendered text."""
    from colleague import search_tools  # local: import-cycle guard (see module docstring)

    pattern = _require_pattern(arguments, "grep_search")
    cap = _max_results(arguments, "grep_search")
    matches = search_tools.grep_search(
        root,
        pattern,
        path=_optional_str(arguments, "path"),
        glob=_optional_str(arguments, "glob"),
        max_results=cap,
    )
    return render_matches(matches, capped=len(matches) >= cap)


def run_glob(root: Path, arguments: dict[str, Any]) -> str:
    """Execute one ``glob`` call and return its rendered text."""
    from colleague import search_tools  # local: import-cycle guard (see module docstring)

    pattern = _require_pattern(arguments, "glob")
    cap = _max_results(arguments, "glob")
    paths = search_tools.glob(root, pattern, path=_optional_str(arguments, "path"), max_results=cap)
    return render_paths(paths, capped=len(paths) >= cap)


_RUNNERS: dict[str, Callable[[Path, dict[str, Any]], str]] = {
    "grep_search": run_grep_search,
    "glob": run_glob,
}


def dispatch(executor: Any) -> dict[str, Callable[[dict[str, Any]], Any]]:
    """The two ``ToolExecutor.execute`` handlers, bound to *executor*.

    Each handler runs the search under ``executor.root`` and passes the rendered
    text through ``executor._truncate(text, tool)`` so both tools get the same
    head+tail / spill treatment as every other tool. Under the legacy knob the
    handler refuses (the schema is hidden too, so a model only reaches this by
    guessing the name).
    """
    from colleague.tools import ToolError, ToolOutcome  # local: avoids the import cycle

    def _bind(tool: str) -> Callable[[dict[str, Any]], Any]:
        def handler(arguments: dict[str, Any]) -> Any:
            if legacy_hidden():
                raise ToolError(
                    f"tool '{tool}' is hidden by {LEGACY_ENV} (the pre-arc tool surface) — "
                    "unset it to search with grep_search/glob"
                )
            text = _RUNNERS[tool](executor.root, arguments)
            return ToolOutcome(result=executor._truncate(text, tool))

        return handler

    return {tool: _bind(tool) for tool in SEARCH_TOOL_NAMES}

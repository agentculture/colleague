"""stdout / stderr helpers with a strict split (stable-contract).

Rule: **results go to stdout, diagnostics and errors go to stderr.** Agents
parsing output can rely on this invariant. JSON mode routes structured
payloads to the same streams — never mixes them.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from colleague.cli._errors import CliError

# Shared help text for the ``--json`` flag every command exposes (agent-first
# convention: every verb supports ``--json``). One definition keeps the wording
# identical across the CLI surface.
JSON_HELP = "Emit structured JSON."


class _RenderedDict(dict):
    """A dict result that renders as ``text`` in CLI text mode, JSON under ``--json``."""

    def __init__(self, data: Any, text: str) -> None:
        super().__init__(data)
        self._text = text

    def __str__(self) -> str:  # text mode goes through str(); --json json.dump()s the dict
        return self._text


class _RenderedList(list):
    """A list result that renders as ``text`` in CLI text mode, JSON under ``--json``."""

    def __init__(self, data: Any, text: str) -> None:
        super().__init__(data)
        self._text = text

    def __str__(self) -> str:
        return self._text


def rendered(data: Any, text: str) -> Any:
    """Wrap a command result for dual rendering by the agentfront-rendered CLI.

    A registry tool function returns ``rendered(structured_data, pretty_text)``
    and agentfront's :func:`emit_result` does the right thing from ONE return
    value: ``--json`` dumps ``structured_data`` (a dict or list), text mode emits
    ``pretty_text`` via ``str()``. This lets a migrated verb keep colleague's
    exact dual output without a per-handler ``--json`` branch (a tool func cannot
    receive ``json_mode`` — the ``--json`` flag is owned by agentfront's dispatch).

    Use with :func:`emit_result` directly too: ``emit_result(rendered(d, t),
    json_mode=...)`` emits ``t`` or ``json.dumps(d)`` — so the old ``(args)``
    handler adapters and the new registry tool funcs share one rendering.
    """
    if isinstance(data, list):
        return _RenderedList(data, text)
    return _RenderedDict(data, text)


def emit_result(data: Any, *, json_mode: bool, stream: TextIO | None = None) -> None:
    """Write a command result to stdout (or ``stream``)."""
    s = stream if stream is not None else sys.stdout
    if json_mode:
        json.dump(data, s, ensure_ascii=False)
        s.write("\n")
        return
    text = data if isinstance(data, str) else str(data)
    s.write(text)
    if not text.endswith("\n"):
        s.write("\n")


def emit_error(err: CliError, *, json_mode: bool, stream: TextIO | None = None) -> None:
    """Write a :class:`CliError` to stderr.

    Text mode renders as two lines when a remediation is present::

        error: <message>
        hint: <remediation>

    The ``hint:`` prefix is required by the agent-first error rubric.
    """
    s = stream if stream is not None else sys.stderr
    if json_mode:
        json.dump(err.to_dict(), s, ensure_ascii=False)
        s.write("\n")
        return
    s.write(f"error: {err.message}\n")
    if err.remediation:
        s.write(f"hint: {err.remediation}\n")


def emit_diagnostic(message: str, *, stream: TextIO | None = None) -> None:
    """Write a human diagnostic (progress, summary) to stderr."""
    s = stream if stream is not None else sys.stderr
    s.write(message if message.endswith("\n") else message + "\n")

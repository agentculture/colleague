"""Head+tail tool-output truncation with spill-to-disk (decision c10/h8).

adapted-from: qwen-code packages/core/src/tools/truncation.ts:22,200-296, tools/shell.ts:91-112

A tool result (a file read, a shell command's stdout/stderr, ...) can be far
larger than the served model's context window can afford. This module gives
the tool layer one small, stdlib-only primitive: bound a result to a
head+tail preview, and — unless disabled — persist the FULL original text to
disk so nothing is lost, naming the spilled file's absolute path in the
returned preview so a later ``read_file`` can recover it.

Per-tool budgets (decision c50): every tool other than ``run_command`` reads
25000 chars / 1000 lines by default (:data:`DEFAULT_TOOL_MAX_CHARS` /
:data:`DEFAULT_TOOL_MAX_LINES`); ``run_command`` reads 30000 chars
(:data:`DEFAULT_SHELL_MAX_CHARS`) — mirroring qwen-code's shell-specific
threshold (``tools/shell.ts``'s ``DEFAULT_SHELL_OUTPUT_THRESHOLD``). The
legacy-wide ``COLLEAGUE_MAX_OUTPUT_CHARS`` knob is a CEILING over *both*: it
can only lower the effective per-tool budget, never raise it above the
per-tool default/override — so ``COLLEAGUE_MAX_OUTPUT_CHARS=100000`` leaves
``read_file`` at its 25000 default (100000 is not tighter). A tool-specific
override — ``COLLEAGUE_READ_MAX_CHARS`` / ``COLLEAGUE_SHELL_MAX_CHARS`` —
replaces the per-tool default, and the ceiling still applies on top of that
override (:func:`resolve_max_chars`).

Spilling persists the untouched original text under ``spill_dir`` (the
caller passes ``<repo>/.colleague/tool-output/`` — a reap hook is wired in a
later task) named by a content hash, mode ``0o600`` (owner-only: tool output
can carry secrets). A module-level session counter tracks bytes spilled this
process (:func:`session_bytes_spilled`) against a 500 MB cap
(:data:`MAX_SESSION_SPILL_BYTES`, mirroring qwen-code's ``MAX_SESSION_BYTES``);
once the cap would be exceeded, spilling stops and a ``RuntimeWarning`` is
recorded (in addition to a note in the returned text) — the fallback is
head+tail only, same as ``COLLEAGUE_TOOL_SPILL=0`` (disables spilling
outright). :func:`reset_session_spill_bytes` clears the counter (tests; a
long-lived process may also reset it at a natural episode boundary).

This module is intentionally standalone: stdlib only, and it imports nothing
from ``colleague.loop`` / ``colleague.tools`` — wiring it into the tool
executor and the loop is a separate task.
"""

from __future__ import annotations

import hashlib
import os
import warnings
from pathlib import Path

#: Per-tool defaults (decision c50). ``run_command`` uses a higher char
#: budget than every other tool; the line budget is shared.
DEFAULT_TOOL_MAX_CHARS = 25_000
DEFAULT_TOOL_MAX_LINES = 1_000
DEFAULT_SHELL_MAX_CHARS = 30_000

#: Env knobs. ``COLLEAGUE_MAX_OUTPUT_CHARS`` is the legacy-wide CEILING;
#: the two ``_MAX_CHARS`` knobs set a single tool's budget beneath it.
ENV_MAX_OUTPUT_CHARS = "COLLEAGUE_MAX_OUTPUT_CHARS"
ENV_READ_MAX_CHARS = "COLLEAGUE_READ_MAX_CHARS"
ENV_SHELL_MAX_CHARS = "COLLEAGUE_SHELL_MAX_CHARS"
ENV_TOOL_SPILL = "COLLEAGUE_TOOL_SPILL"

#: Session-wide spill cap (mirrors qwen-code's ``MAX_SESSION_BYTES``).
MAX_SESSION_SPILL_BYTES = 500 * 1024 * 1024

#: Separator inserted between the retained head and tail.
_SEPARATOR = "\n\n---\n... [CONTENT TRUNCATED] ...\n---\n\n"

#: Owner-only permission bits the spilled file is created with. Tool output
#: can contain secrets (env dumps, credentials in a log) so the spill file is
#: never group/world readable. # nosec B103 - the restrictive mode IS the point.
_SPILL_FILE_MODE = 0o600

_session_bytes_spilled = 0


def reset_session_spill_bytes() -> None:
    """Reset the module-level session spill counter to zero.

    Exists so tests (and a long-lived host process, at a natural episode
    boundary) can start a fresh 500 MB budget without restarting the
    interpreter.
    """
    global _session_bytes_spilled
    _session_bytes_spilled = 0


def session_bytes_spilled() -> int:
    """Bytes spilled to disk by :func:`truncate_output` so far this process."""
    return _session_bytes_spilled


def _spill_enabled() -> bool:
    raw = os.environ.get(ENV_TOOL_SPILL)
    return raw not in ("0", "false", "False")


def resolve_max_chars(tool_name: str = "read_file") -> int:
    """Resolve the effective char budget for ``tool_name`` (decision c50).

    ``run_command`` reads its default from :data:`DEFAULT_SHELL_MAX_CHARS`
    (30000) and its override from ``COLLEAGUE_SHELL_MAX_CHARS``; every other
    tool name reads :data:`DEFAULT_TOOL_MAX_CHARS` (25000) and
    ``COLLEAGUE_READ_MAX_CHARS``. ``COLLEAGUE_MAX_OUTPUT_CHARS``, when set, is
    then applied as a ceiling — ``min(value, ceiling)`` — so it can only
    tighten the result, never loosen it.
    """
    is_shell = tool_name == "run_command"
    default = DEFAULT_SHELL_MAX_CHARS if is_shell else DEFAULT_TOOL_MAX_CHARS
    override_env = ENV_SHELL_MAX_CHARS if is_shell else ENV_READ_MAX_CHARS
    override = os.environ.get(override_env)
    value = int(override) if override not in (None, "") else default

    ceiling = os.environ.get(ENV_MAX_OUTPUT_CHARS)
    if ceiling not in (None, ""):
        value = min(value, int(ceiling))
    return value


def resolve_max_lines() -> int:
    """Resolve the effective line budget. Shared across every tool (c50)."""
    return DEFAULT_TOOL_MAX_LINES


def _head_and_tail(text: str, max_chars: int, max_lines: int) -> tuple[str, bool]:
    """Build a head+tail preview of ``text`` within both budgets.

    Returns ``(preview, was_truncated)``. When ``text`` already fits both
    budgets, ``preview is text`` and ``was_truncated`` is ``False`` — the
    caller short-circuits before touching disk.
    """
    lines = text.split("\n")
    if len(text) <= max_chars and len(lines) <= max_lines:
        return text, False

    effective_lines = min(max_lines, len(lines))
    head_n = max(effective_lines // 5, 1)
    tail_n = max(effective_lines - head_n, 0)
    head_lines = lines[:head_n]
    tail_lines = lines[-tail_n:] if tail_n else []

    char_budget = max(max_chars - len(_SEPARATOR), 0)
    head_budget = char_budget // 5
    tail_budget = char_budget - head_budget

    head_text = "\n".join(head_lines)
    if len(head_text) > head_budget:
        head_text = head_text[:head_budget]

    tail_text = "\n".join(tail_lines)
    if len(tail_text) > tail_budget:
        tail_text = tail_text[-tail_budget:] if tail_budget else ""

    return head_text + _SEPARATOR + tail_text, True


def truncate_output(
    text: str,
    max_chars: int,
    max_lines: int,
    spill_dir: str | Path,
) -> str:
    """Bound ``text`` to a head+tail preview, spilling the full text to disk.

    When ``text`` already fits ``max_chars``/``max_lines``, it is returned
    unchanged and nothing is written to disk. Otherwise a preview is built
    (:func:`_head_and_tail`) and, unless spilling is disabled
    (``COLLEAGUE_TOOL_SPILL=0``) or the 500 MB session cap would be exceeded,
    the untouched original ``text`` is written under ``spill_dir`` as
    ``<sha256-of-text>.txt`` with mode 0o600, and the returned preview names
    that file's absolute path. On either fallback path (disabled, or the cap
    reached — the latter also records a ``RuntimeWarning``) the preview is
    returned with a short note instead, never a file path.
    """
    preview, was_truncated = _head_and_tail(text, max_chars, max_lines)
    if not was_truncated:
        return text

    if not _spill_enabled():
        return (
            "Tool output was too large and has been truncated "
            f"(COLLEAGUE_TOOL_SPILL=0, full output not saved to disk).\n\n{preview}"
        )

    encoded = text.encode("utf-8")
    size = len(encoded)
    global _session_bytes_spilled
    if _session_bytes_spilled + size > MAX_SESSION_SPILL_BYTES:
        warnings.warn(
            "colleague.truncation: session tool-output spill budget "
            f"({MAX_SESSION_SPILL_BYTES} bytes) exhausted; falling back to "
            "head+tail truncation without spilling to disk",
            RuntimeWarning,
            stacklevel=2,
        )
        return (
            "Tool output was too large and has been truncated "
            "(session spill budget exhausted, full output not saved to disk).\n\n"
            f"{preview}"
        )

    digest = hashlib.sha256(encoded).hexdigest()
    spill_path = Path(spill_dir)
    try:
        spill_path.mkdir(parents=True, exist_ok=True)
        out_file = spill_path / f"{digest}.txt"
        out_file.write_text(text, encoding="utf-8")
        os.chmod(out_file, _SPILL_FILE_MODE)
    except OSError as exc:
        return (
            "Tool output was too large and has been truncated "
            f"(could not save full output to disk: {exc}).\n\n{preview}"
        )

    _session_bytes_spilled += size
    abs_path = str(out_file.resolve())
    return (
        "Tool output was too large and has been truncated.\n"
        f"The full output has been saved to: {abs_path}\n"
        "To read the complete output, use the read_file tool with the "
        "absolute file path above.\n\n"
        f"{preview}"
    )

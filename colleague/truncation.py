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
import secrets
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
#: The separator's own newline count — its lines count against ``max_lines``
#: too (finding #441-9 / B), not just its chars.
_SEPARATOR_NEWLINES = _SEPARATOR.count("\n")

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

    The returned preview (head + :data:`_SEPARATOR` + tail) itself always
    fits ``max_chars``/``max_lines`` (finding #441-9 / B): both the
    separator's own chars (already budgeted before this fix) AND its own
    ``_SEPARATOR_NEWLINES`` line breaks are reserved out of the budget
    BEFORE any content lines are picked, instead of the separator being
    spliced in on top of an already-full head+tail selection.
    """
    lines = text.split("\n")
    if len(text) <= max_chars and len(lines) <= max_lines:
        return text, False

    # Reserve room for the separator's own newlines (+1 for the trailing
    # partial "line" the final count()+1 accounts for) before handing out
    # any of the remaining budget to actual content lines.
    available_lines = max(max_lines - _SEPARATOR_NEWLINES - 1, 0)
    effective_lines = min(available_lines, len(lines))
    if effective_lines <= 0:
        head_n = 0
        tail_n = 0
    else:
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


def _bounded_preview(text: str, prefix: str, max_chars: int, max_lines: int) -> str:
    """The head+tail preview sized so ``prefix + preview`` itself stays
    within ``max_chars``/``max_lines`` (finding #441-9 / B).

    ``truncate_output`` always appends ``prefix`` (a status/path note) BEFORE
    the preview and nothing after it, so budgeting is a straight subtraction:
    the preview gets whatever chars/lines remain once ``prefix`` is paid for.
    """
    budget_chars = max(max_chars - len(prefix), 0)
    budget_lines = max(max_lines - prefix.count("\n"), 0)
    preview, _ = _head_and_tail(text, budget_chars, budget_lines)
    return preview


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
    fits = len(text) <= max_chars and (text.count("\n") + 1) <= max_lines
    if fits:
        return text

    if not _spill_enabled():
        prefix = (
            "Tool output was too large and has been truncated "
            "(COLLEAGUE_TOOL_SPILL=0, full output not saved to disk).\n\n"
        )
        return prefix + _bounded_preview(text, prefix, max_chars, max_lines)

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
        prefix = (
            "Tool output was too large and has been truncated "
            "(session spill budget exhausted, full output not saved to disk).\n\n"
        )
        return prefix + _bounded_preview(text, prefix, max_chars, max_lines)

    digest = hashlib.sha256(encoded).hexdigest()
    spill_path = Path(spill_dir)
    try:
        spill_path.mkdir(parents=True, exist_ok=True)
        out_file = _create_spill_file(spill_path, digest, encoded)
    except OSError as exc:
        prefix = (
            "Tool output was too large and has been truncated "
            f"(could not save full output to disk: {exc}).\n\n"
        )
        return prefix + _bounded_preview(text, prefix, max_chars, max_lines)

    _session_bytes_spilled += size
    abs_path = str(out_file.resolve())
    prefix = (
        "Tool output was too large and has been truncated.\n"
        f"The full output has been saved to: {abs_path}\n"
        "To read the complete output, use the read_file tool with the "
        "absolute file path above.\n\n"
    )
    return prefix + _bounded_preview(text, prefix, max_chars, max_lines)


def _create_spill_file(spill_dir: Path, digest: str, encoded: bytes) -> Path:
    """Create the spilled file ATOMICALLY at ``spill_dir / f"{digest}.txt"``,
    refusing to follow a pre-planted symlink (finding #441-5 / A).

    The digest filename is deterministic and ``spill_dir`` is repository-
    local (thus attacker-writable in a hostile checkout): the previous
    ``Path.write_text()`` + ``os.chmod()`` sequence followed whatever the
    digest path resolved to, including a symlink planted ahead of time
    pointing outside the spill dir — silently overwriting (and then
    chmod-ing) an arbitrary file the colleague process can write.

    ``os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW`` makes create+open a single
    atomic kernel call that fails instead of following an existing symlink,
    and the mode is passed to ``open()`` itself (never a separate ``chmod``
    afterwards, which would still race a symlink planted between create and
    chmod). ``# nosec B103`` — ``_SPILL_FILE_MODE`` (0o600) is the
    deliberately restrictive, owner-only mode this fix exists to enforce.

    On a name collision (``FileExistsError``) the existing entry is reused
    only when it is a REGULAR, non-symlink file whose content already equals
    ``encoded`` (two tools spilling byte-identical output, the common case);
    anything else — a symlink, a directory, or a regular file with
    different content (a SHA-256 collision, or an unrelated pre-existing
    file) — falls back to a fresh name suffixed with a short random token
    from :mod:`secrets` (never :mod:`random` — the suffix must not be
    guessable ahead of time, or the same symlink-plant attack just moves to
    the fallback name).
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    candidate = spill_dir / f"{digest}.txt"
    try:
        fd = os.open(candidate, flags, _SPILL_FILE_MODE)  # nosec B103
    except FileExistsError:
        if not candidate.is_symlink() and candidate.is_file():
            try:
                if candidate.read_bytes() == encoded:
                    return candidate
            except OSError:
                pass
        candidate = spill_dir / f"{digest}-{secrets.token_hex(4)}.txt"
        fd = os.open(candidate, flags, _SPILL_FILE_MODE)  # nosec B103
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
    return candidate


def reap_spill_dir(repo_path: str | "Path", *, dry_run: bool = False) -> dict:
    """Reap ``<repo>/.colleague/tool-output/`` (``colleague clean``, plan t20).

    Spilled tool outputs are re-readable scratch for the run that produced
    them, never a gradable record, so ``clean`` removes every ``*.txt`` there
    and reports the bytes freed: ``{dir, files, bytes_freed, action}`` with
    ``action`` in ``reaped`` / ``would-reap`` (dry-run) / ``none`` (nothing
    there). A missing directory is a no-op; an unlink failure is skipped and
    counted neither as a file nor as bytes.
    """
    spill_dir = Path(repo_path) / ".colleague" / "tool-output"
    files, freed = 0, 0
    if spill_dir.is_dir():
        for path in sorted(spill_dir.glob("*.txt")):
            try:
                size = path.stat().st_size
                if not dry_run:
                    path.unlink()
            except OSError:
                continue
            files += 1
            freed += size
    # Sonar S3358: plain if/else instead of a nested conditional expression
    # (no behaviour change — finding #441-14 / C).
    if files == 0:
        action = "none"
    elif dry_run:
        action = "would-reap"
    else:
        action = "reaped"
    return {"dir": str(spill_dir), "files": files, "bytes_freed": freed, "action": action}

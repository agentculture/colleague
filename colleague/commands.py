"""Command template discovery and expansion.

Discovers named command-template files under ``.colleague/commands/*.md``
(repo-level then user-level, via :mod:`colleague.configdir`), parses
optional YAML-like metadata from an opening ``---`` block, and expands a
named command with positional arguments into a :class:`~colleague.contract.Task`.

This is the "slash command" analog for the one-shot colleague harness:
instead of typing out a full instruction each time, operators author reusable
``.md`` templates with ``$1``/``$2``/``$ARGUMENTS`` substitution placeholders.

Template file format
--------------------
A command file ``<.colleague>/commands/<name>.md`` may begin with an
optional metadata block delimited by ``---`` lines::

    ---
    description: Fix lint errors in a path
    engine: mock
    constraints: keep diffs minimal, run the formatter
    arg-hint: <path>
    ---
    Fix all lint errors under $1. Then run the formatter. $ARGUMENTS

Supported metadata keys: ``description``, ``engine``, ``constraints``
(comma-separated → list), ``arg-hint``.  Unknown keys are silently ignored.
If no opening ``---`` block is present, the entire file content is the body.

Argument substitution
---------------------
- ``$ARGUMENTS`` — all args joined by a single space.
- ``$1``, ``$2``, ... — the N-th positional arg (1-indexed); missing → ``""``.

Stdlib only — no third-party dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from colleague.configdir import collect_files
from colleague.contract import Task
from colleague.policy import load_policy


class CommandError(Exception):
    """Raised when an unknown command name is requested."""


@dataclass
class Command:
    """A parsed command template.

    Attributes
    ----------
    name:
        The command's stem (filename without ``.md``).
    description:
        Human-readable description from the metadata block, or ``""`` if absent.
    engine:
        The engine to use when running this command, or ``None`` if not set
        (callers fall back to their own default).
    constraints:
        List of constraint strings parsed from the metadata ``constraints`` key.
    arg_hint:
        Short hint shown in listings (e.g. ``"<path>"``), or ``""`` if absent.
    body:
        The template body text after metadata stripping.
    """

    name: str
    description: str = ""
    engine: Optional[str] = None
    constraints: list[str] = field(default_factory=list)
    arg_hint: str = ""
    body: str = ""


# Regex matching a ``$N`` positional placeholder (``$1`` ... ``$99``).
# re.ASCII keeps ``\d`` to ASCII 0-9 — without it ``\d`` also matches Unicode
# digits (e.g. Arabic-Indic), which would mis-parse a placeholder index.
_POSITIONAL_RE = re.compile(r"\$([1-9]\d?)", re.ASCII)


def discover_commands(
    repo_path: str | Path, *, user_home: str | Path | None = None
) -> dict[str, Path]:
    """Discover command-template files under ``.colleague/commands/``.

    Uses :func:`~colleague.configdir.collect_files` so repo-level files
    shadow user-level files by stem.  Only ``*.md`` files are returned.

    Parameters
    ----------
    repo_path:
        Root of the repository being driven.
    user_home:
        (test fixture) Inject an alternative home directory; defaults to
        ``Path.home()``.

    Returns
    -------
    dict[str, Path]
        Mapping of command stem to the resolved ``Path`` of the template file.
    """
    return collect_files(repo_path, "commands", suffix=".md", user_home=user_home)


def _engine_or_none(value: str) -> Optional[str]:
    """Empty ``engine:`` → ``None`` (callers fall back to their own default)."""
    return value if value else None


def _split_constraints(value: str) -> list[str]:
    """Comma-separated ``constraints:`` → a stripped, empties-dropped list."""
    return [c.strip() for c in value.split(",") if c.strip()]


# Maps a metadata key to (Command field name, value parser). Keys absent from
# this table are silently ignored. Replaces an if/elif key chain so each key's
# transform stays a one-liner and the dispatch is a single lookup.
_META_PARSERS: dict[str, tuple[str, Callable[[str], object]]] = {
    "description": ("description", str),
    "engine": ("engine", _engine_or_none),
    "constraints": ("constraints", _split_constraints),
    "arg-hint": ("arg_hint", str),
}


def _parse_metadata(lines: list[str]) -> tuple[dict[str, object], Optional[int]]:
    """Parse a leading ``---`` / ``---`` metadata block.

    Returns the parsed :class:`Command` field overrides and the index of the
    closing ``---`` line, or ``({}, None)`` when there is no complete metadata
    block (no opening fence, or an opening fence with no closing one) — in which
    case the caller treats the whole file as the body.
    """
    # A metadata block must open with "---" as the first line.
    if not (lines and lines[0].rstrip("\r\n") == "---"):
        return {}, None

    closing_idx: Optional[int] = None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            closing_idx = i
            break
    if closing_idx is None:
        return {}, None

    fields: dict[str, object] = {}
    for meta_line in lines[1:closing_idx]:
        stripped = meta_line.rstrip("\r\n")
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        parser = _META_PARSERS.get(key.strip())
        if parser is not None:
            field_name, transform = parser
            fields[field_name] = transform(value.strip())
    return fields, closing_idx


def load_command(path: str | Path) -> Command:
    """Parse a command-template file into a :class:`Command`.

    The file stem becomes ``Command.name``.  An optional leading ``---`` /
    ``---`` metadata block is parsed for supported keys; the remainder (or the
    whole file if no such block is present) becomes ``Command.body``.

    Parameters
    ----------
    path:
        Absolute or relative path to the ``.md`` template file.

    Returns
    -------
    Command
        Populated command object.
    """
    path = Path(path)
    raw = path.read_text()
    lines = raw.splitlines(keepends=True)

    fields, closing_idx = _parse_metadata(lines)
    # Body is everything after the closing ---; with no metadata block the whole
    # file is the body.
    body = "".join(lines[closing_idx + 1 :]) if closing_idx is not None else raw

    return Command(name=path.stem, body=body, **fields)


def _substitute(body: str, args: list[str]) -> str:
    """Apply argument substitution to a template body.

    Rules:
    - ``$ARGUMENTS`` → all *args* joined by a single space.
    - ``$N`` (1-indexed) → the N-th positional arg, or ``""`` if out of range.

    Substitution order: positional placeholders first (highest index first to
    avoid partial replacement), then ``$ARGUMENTS``.

    Parameters
    ----------
    body:
        Raw template body text.
    args:
        Positional arguments supplied by the caller.

    Returns
    -------
    str
        The substituted instruction text.
    """
    all_args = " ".join(args)

    def _replace_positional(match: re.Match) -> str:
        idx = int(match.group(1))  # 1-indexed
        return args[idx - 1] if idx <= len(args) else ""

    result = _POSITIONAL_RE.sub(_replace_positional, body)
    result = result.replace("$ARGUMENTS", all_args)
    return result


def expand_command(
    repo_path: str | Path,
    name: str,
    args: list[str],
    *,
    engine_default: str = "mock",
    model: Optional[str] = None,
    user_home: str | Path | None = None,
) -> Task:
    """Expand a named command template into a :class:`~colleague.contract.Task`.

    Discovers the named command file via :func:`discover_commands`, parses it
    with :func:`load_command`, substitutes *args* into the body, and returns a
    :class:`~colleague.contract.Task` built through
    :meth:`~colleague.contract.Task.new` so the shape is guaranteed identical
    to any other task in the system.

    Before building the task the resolved template path is checked against the
    operator-declared approval policy (``approvals.json`` via
    :func:`~colleague.policy.load_policy`).  When the policy's ``commands``
    section is **absent** the gate is a strict no-op and the call proceeds
    exactly as before.  When the section is **present** the named template must
    have a recorded and matching checksum; a mismatch, drift, or unlisted name
    raises :class:`CommandError` before any engine runs.

    Parameters
    ----------
    repo_path:
        Root of the repository being driven.
    name:
        The command name (stem of the ``.md`` file).
    args:
        Positional arguments for ``$1`` / ``$2`` / ``$ARGUMENTS`` substitution.
    engine_default:
        Engine to use when the command file does not specify one.
    model:
        Optional engine model identifier; passed to :func:`~colleague.policy.load_policy`
        so a per-model overlay can be consulted for the approval gate.
    user_home:
        (test fixture) Inject an alternative home directory.

    Returns
    -------
    Task
        A fully populated task ready to hand to an engine.

    Raises
    ------
    CommandError
        When *name* does not match any discovered command template, or when the
        approval policy denies the template (drift / tamper / unapproved).
    """
    discovered = discover_commands(repo_path, user_home=user_home)
    if name not in discovered:
        raise CommandError(
            f"Unknown command {name!r}. Available: {sorted(discovered.keys()) or '(none)'}"
        )

    # --- Approval gate ---
    # Consult the policy BEFORE parsing or running the template.  When no
    # ``commands`` section is present in approvals.json the policy is a strict
    # no-op and check_file returns Verdict(True) unchanged.
    policy = load_policy(repo_path, model=model, user_home=user_home)
    verdict = policy.check_file("commands", name, discovered[name])
    if not verdict.allowed:
        raise CommandError(f"command {name!r} refused by approval policy: {verdict.reason}")

    cmd = load_command(discovered[name])
    instruction = _substitute(cmd.body, args)
    engine = cmd.engine if cmd.engine is not None else engine_default

    return Task.new(
        str(repo_path),
        instruction,
        engine=engine,
        constraints=cmd.constraints,
    )

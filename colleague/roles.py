"""Typed-subagent roles: data model, built-in defaults, and per-model loader.

A *role* is a named profile that carries a prompt fragment, a curated tool
allow-list, an optional skill subset, and a read-only flag. Built-in roles
(explorer, planner, reviewer, validator, writer) cover the common subagent
shapes. Operator-authored overrides live under ``.colleague/agents/<name>.md``
with per-model overlays at ``.colleague/<model>/agents/<name>.md``.

When no role config is present the default is the full-surface *writer* role,
so behaviour is byte-identical to today (purely additive).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from colleague import layers

# ---------------------------------------------------------------------------
# Role data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Role:
    """A typed-subagent role profile.

    Attributes
    ----------
    name:
        Human-readable role name (e.g. ``"explorer"``).
    prompt_fragment:
        Markdown fragment appended to the child's system prompt.
    tool_allowlist:
        Tuple of tool-name strings the child may invoke.  When the loop
        builds the child's schema it filters ``colleague.tools.SCHEMAS`` to
        only those names.
    skill_subset:
        Tuple of skill-name strings the child may use, or ``None`` meaning
        "all skills".
    read_only:
        ``True`` when the role must never mutate the repo tree.  Read-only
        roles exclude ``write_file``, ``edit_file``, and ``run_command`` from
        their allow-list.
    """

    name: str
    prompt_fragment: str
    tool_allowlist: tuple[str, ...]
    skill_subset: Optional[tuple[str, ...]]
    read_only: bool


# ---------------------------------------------------------------------------
# Built-in default roles
# ---------------------------------------------------------------------------

#: Tools that mutate the repo tree — excluded from every read-only role.
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "run_command"})

#: Read-only tools available to explorer / planner / reviewer.
#: Strictly pure-read so a read-only role *provably cannot mutate the tree*:
#: ``culture``/``devague`` are deliberately excluded because they shell out to
#: write-capable CLIs (``devex``, ``devague converge`` writes a frame), which
#: would quietly contradict the read-only guarantee. ``finish`` is REQUIRED —
#: without it a curated read-only child has no way to complete cleanly and
#: would always burn to budget exhaustion.
_READONLY_TOOLS = (
    "read_file",
    "list_dir",
    "check_test_integrity",
    "finish",
)

#: Read-only tools for the validator role (includes the dedicated test runner).
_VALIDATOR_TOOLS = _READONLY_TOOLS + ("run_tests",)


def _writer_allowlist() -> tuple[str, ...]:
    """Return the full tool surface derived from the current SCHEMAS."""
    from colleague.tools import SCHEMAS

    return tuple(s["function"]["name"] for s in SCHEMAS)


BUILTIN_ROLES: dict[str, Role] = {
    "explorer": Role(
        name="explorer",
        prompt_fragment=(
            "You are an explorer. Inspect the repository, read files, and "
            "gather context. Do not write or execute commands."
        ),
        tool_allowlist=_READONLY_TOOLS,
        skill_subset=None,
        read_only=True,
    ),
    "planner": Role(
        name="planner",
        prompt_fragment=(
            "You are a planner. Analyse the task, reason about approach, and "
            "produce a structured plan. Do not write or execute commands."
        ),
        tool_allowlist=_READONLY_TOOLS,
        skill_subset=None,
        read_only=True,
    ),
    "reviewer": Role(
        name="reviewer",
        prompt_fragment=(
            "You are a reviewer. Read code and provide critique. Do not write "
            "or execute commands."
        ),
        tool_allowlist=_READONLY_TOOLS,
        skill_subset=None,
        read_only=True,
    ),
    "validator": Role(
        name="validator",
        prompt_fragment=(
            "You are a validator. Read code and run tests to verify correctness. "
            "Do not write files or execute arbitrary commands."
        ),
        tool_allowlist=_VALIDATOR_TOOLS,
        skill_subset=None,
        read_only=True,
    ),
    "writer": Role(
        name="writer",
        prompt_fragment=(
            "You are a writer. You have full access to read, write, edit, and "
            "execute commands within the repository."
        ),
        tool_allowlist=(),  # populated dynamically below
        skill_subset=None,
        read_only=False,
    ),
}

# Populate the writer's allowlist dynamically so it stays in sync with SCHEMAS.
BUILTIN_ROLES["writer"] = replace(
    BUILTIN_ROLES["writer"],
    tool_allowlist=_writer_allowlist(),
)


# ---------------------------------------------------------------------------
# Default role (additive / byte-identical fallback)
# ---------------------------------------------------------------------------


def default_role() -> Role:
    """Return the default role used when no role is explicitly requested.

    This is the full-surface *writer* role, so behaviour is byte-identical to
    today when no role config is present.
    """
    return BUILTIN_ROLES["writer"]


# ---------------------------------------------------------------------------
# Per-model loader
# ---------------------------------------------------------------------------


def load_role(
    name: str,
    repo_path: str | Path,
    model: str,
) -> Optional[Role]:
    """Load a role by *name*, resolving operator-authored config.

    Resolution order (most specific first):

    1. Per-model overlay: ``.colleague/<model>/agents/<name>.md``
       (``<model>`` is sanitised via :func:`colleague.layers.sanitize_model`).
    2. Base role file: ``.colleague/agents/<name>.md``.
    3. Built-in default from :data:`BUILTIN_ROLES`.

    When no file is present the built-in default is returned.  An unknown
    role name with no file on disk returns ``None``.

    The overlay is composed by exact path — no sibling globbing — matching the
    established pattern in :mod:`colleague.layers`.
    """
    repo = Path(repo_path)
    safe_model = layers.sanitize_model(model)

    # 1. Per-model overlay (exact path, no globbing)
    overlay_path = repo / ".colleague" / safe_model / "agents" / f"{name}.md"
    # 2. Base role file
    base_path = repo / ".colleague" / "agents" / f"{name}.md"

    # Read whichever file exists (overlay shadows base).
    role_file: Path | None = None
    if overlay_path.is_file():
        role_file = overlay_path
    elif base_path.is_file():
        role_file = base_path

    # If a file exists, use its contents as the prompt fragment; otherwise
    # fall back to the built-in role's prompt.
    if role_file is not None:
        try:
            prompt = role_file.read_text(encoding="utf-8")
        except OSError:
            prompt = ""
    else:
        prompt = None  # will use built-in prompt below

    # Look up the built-in default for this name.
    builtin = BUILTIN_ROLES.get(name)
    if builtin is None:
        # Unknown role name with no file on disk.
        return None

    # Compose the final role: file prompt overrides built-in prompt.
    final_prompt = prompt if prompt is not None else builtin.prompt_fragment
    return replace(builtin, prompt_fragment=final_prompt)

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

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, cast

from colleague import effort as _effort
from colleague import layers
from colleague.configdir import CONFIG_DIR_NAME

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
        Tuple of skill-name-or-glob-pattern strings the child may use (each
        entry is matched via :func:`colleague.layers._filter_skills`, so a
        plain name matches exactly and a wildcard pattern like ``"cicd*"``
        matches a whole class of skills), or ``None`` meaning "all skills"
        (byte-identical to the unfiltered catalog — the no-silent-loss floor).
    read_only:
        ``True`` when the role must never mutate the repo tree.  Read-only
        roles exclude ``write_file``, ``edit_file``, and ``run_command`` from
        their allow-list.
    effort:
        Optional per-seat thinking-effort ladder rung (#416 t5) — one of
        :data:`colleague.effort.LADDER` or ``None`` (unset). Built-in roles
        default to their :data:`colleague.effort.ROLE_TABLE` row (single
        source, set once below); an operator role overlay's leading
        ``effort: <rung>`` line (validated via
        :func:`colleague.effort.validate_effort`) overrides it. Consumed by
        :mod:`colleague.subagents`' child builds as the ``role=`` input to
        :func:`colleague.effort.resolve_effort` — never read directly by the
        loop.
    """

    name: str
    prompt_fragment: str
    tool_allowlist: tuple[str, ...]
    skill_subset: Optional[tuple[str, ...]]
    read_only: bool
    effort: Optional[str] = None


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
#: would always burn to budget exhaustion. ``deepthink`` (plan t4) is included
#: too: it is pure computation — ONE bounded tools-off completion against a
#: second model, no writes, no shell — so a read-only reviewer/explorer/planner
#: can escalate a hard verdict without weakening the read-only guarantee at all.
#: ``memory`` is included for recall (search) only — the executor enforces that
#: read-only roles cannot use the 'remember' verb (write-capable shell-out).
_READONLY_TOOLS = (
    "read_file",
    "view_media",
    "list_dir",
    "check_test_integrity",
    "deepthink",
    "memory",
    "finish",
)

#: Read-only tools for the validator role (includes the dedicated test runner).
_VALIDATOR_TOOLS = _READONLY_TOOLS + ("run_tests",)

#: Curated skill-subset patterns for the read-and-report built-in roles
#: (explorer / planner / reviewer / validator, t10).
#:
#: BUILTIN_ROLES is a single module-level constant shared by *every* repo
#: colleague drives, so this can't be a hardcoded list of this repo's current
#: ``.colleague/skills/*.md`` filenames — it has to travel by NAMING
#: CONVENTION (an fnmatch-style glob via ``colleague.layers._filter_skills``)
#: so a subset composed against a different repo's skill catalog still makes
#: sense. Each pattern below is an INCLUDE — a class of skill the read-only
#: roles are trusted to know about because it is itself investigation/
#: reporting-shaped (reads state, writes nothing). Everything NOT matched is
#: excluded by omission: this repo's own release/side-effect-shaped skills —
#: ``cicd`` (opens/pushes PRs), ``version-bump`` (releases), ``pypi-maintainer``
#: (mutates the install source), ``assign-to-workforce`` (spawns writing
#: subagents), ``communicate`` (files issues / sends mesh messages),
#: ``ask-colleague`` (its own ``write --apply``/``--pr`` verbs mutate/push),
#: and ``promote`` (graduates a resident mesh peer) — are all deliberately
#: left out, and a pattern matching none of a repo's skills just composes an
#: empty skills section (never an error; see ``_filter_skills``).
_INVESTIGATION_SKILL_PATTERNS: tuple[str, ...] = (
    "recall*",  # shared eidetic-memory search — pure read, never writes
    "explore*",  # investigation/survey-shaped skills (e.g. "explore-notes")
    "review*",  # second-opinion/critique-shaped skills — report, never apply
    "agent-config*",  # read-only "show agent config" inspection
    "doc-test-alignment*",  # verifies docs/tests/code still agree — report only
    "sonarclaude*",  # queries hosted code-quality data — read-only reporting
)

#: The validator's purpose is verifying correctness by *running* tests (via
#: its dedicated ``run_tests`` tool), so it additionally keeps the matching
#: skill doc describing that workflow — still non-mutating (running the
#: existing suite writes no repo content the model authored).
_VALIDATOR_SKILL_PATTERNS: tuple[str, ...] = _INVESTIGATION_SKILL_PATTERNS + ("run-tests*",)


def _writer_allowlist() -> tuple[str, ...]:
    """Return the full tool surface derived from the current SCHEMAS, plus ``deepthink``.

    ``deepthink`` (plan t4) is deliberately NOT part of the module-level
    :data:`colleague.tools.SCHEMAS` list (a single-model run must offer today's
    tool list byte-identically), so it does not fall out of the SCHEMAS-derived
    tuple below automatically. It is appended explicitly here for the same
    reason it is added to every other built-in role: it is pure computation —
    one bounded completion, no writes, no shell — so the full-surface writer
    role allows it too. It is a no-op unless the loop actually offers the
    schema (a dual-model config is present).
    """
    from colleague.tools import DEEPTHINK, SCHEMAS

    names = tuple(s["function"]["name"] for s in SCHEMAS)
    return names + (DEEPTHINK,)


BUILTIN_ROLES: dict[str, Role] = {
    "explorer": Role(
        name="explorer",
        prompt_fragment=(
            "You are an explorer. Inspect the repository, read files, and "
            "gather context. Do not write or execute commands."
        ),
        tool_allowlist=_READONLY_TOOLS,
        skill_subset=_INVESTIGATION_SKILL_PATTERNS,
        read_only=True,
    ),
    "planner": Role(
        name="planner",
        prompt_fragment=(
            "You are a planner. Analyse the task, reason about approach, and "
            "produce a structured plan. Do not write or execute commands."
        ),
        tool_allowlist=_READONLY_TOOLS,
        skill_subset=_INVESTIGATION_SKILL_PATTERNS,
        read_only=True,
    ),
    "reviewer": Role(
        name="reviewer",
        prompt_fragment=(
            "You are a reviewer. Read code and provide critique. Do not write "
            "or execute commands."
        ),
        tool_allowlist=_READONLY_TOOLS,
        skill_subset=_INVESTIGATION_SKILL_PATTERNS,
        read_only=True,
    ),
    "validator": Role(
        name="validator",
        prompt_fragment=(
            "You are a validator. Read code and run tests to verify correctness. "
            "Do not write files or execute arbitrary commands."
        ),
        tool_allowlist=_VALIDATOR_TOOLS,
        skill_subset=_VALIDATOR_SKILL_PATTERNS,
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

# Populate every built-in role's default effort from the single-source table
# (#416 t5, c13/h8): colleague.effort.ROLE_TABLE is the ONE place the
# writer/planner/reviewer/validator/explorer rungs are declared; a role with
# no table row (there are none today) stays unset (``None``).
for _role_name in tuple(BUILTIN_ROLES):
    BUILTIN_ROLES[_role_name] = replace(
        BUILTIN_ROLES[_role_name],
        effort=_effort.ROLE_TABLE.get(_role_name),
    )
del _role_name


# ---------------------------------------------------------------------------
# Default role (additive / byte-identical fallback)
# ---------------------------------------------------------------------------


def default_role() -> Role:
    """Return the default role used when no role is explicitly requested.

    This is the full-surface *writer* role, so behaviour is byte-identical to
    today when no role config is present.
    """
    return BUILTIN_ROLES["writer"]


def is_read_only(name: Optional[str]) -> bool:
    """True iff *name* is a built-in **read-only** role (explorer/reviewer/planner/
    validator) — one whose curated tool surface withholds every write tool.

    Keyed on the built-in's ``read_only`` flag, which an operator overlay can never
    flip (v1 overlays change only the prompt, not the allowlist), so this is the
    authoritative read-only test for a role *name*. ``None`` (no role) and the
    full-surface ``writer`` are not read-only. Used by the runtime to skip the
    write handoff + the dirty-tree guard for a read-only run (there is nothing the
    model wrote to hand off, and the handoff's ``git add -u`` must never sweep the
    operator's uncommitted WIP — Qodo, PR #245).
    """
    role = BUILTIN_ROLES.get(name) if name else None
    return bool(role and role.read_only)


# ---------------------------------------------------------------------------
# Per-model loader
# ---------------------------------------------------------------------------


def _within_config(path: Path, config_dir: Path) -> bool:
    """True if *path* resolves to *config_dir* or somewhere beneath it.

    Both sides are fully resolved (symlinks included), mirroring
    :func:`colleague.layers._within` / :meth:`colleague.tools.ToolExecutor._safe_path`,
    so a symlink whose target escapes the config dir is refused.
    """
    try:
        resolved = path.resolve()
        base = config_dir.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def _resolve_role_prompt(repo: Path, safe_model: str, name: str) -> Optional[str]:
    """Return the operator-authored prompt for *name*, or ``None`` to fall back to
    the built-in default.

    Resolves the per-model overlay then the base file (exact paths, no sibling
    globbing), both confined to the config dir — a role file that resolves OUTSIDE
    ``.colleague/`` (a symlink planted in the config dir) is refused so it can never
    pull an arbitrary file into the system prompt. An unreadable file is treated as
    absent (fall back to the built-in), never an empty prompt.
    """
    config_dir = repo / CONFIG_DIR_NAME
    candidates = (
        config_dir / safe_model / "agents" / f"{name}.md",  # 1. per-model overlay
        config_dir / "agents" / f"{name}.md",  # 2. base role file
    )
    role_file = next((c for c in candidates if c.is_file()), None)
    if role_file is None or not _within_config(role_file, config_dir):
        return None
    try:
        return role_file.read_text(encoding="utf-8")
    except OSError:
        return None


#: An operator role overlay's OPTIONAL leading line — ``effort: <rung>`` —
#: overriding the built-in's table-derived :attr:`Role.effort` (#416 t5).
#: Anchored to the start of the file so it can never be confused with the
#: same text appearing later in the prompt body.
_EFFORT_FRONTMATTER_RE = re.compile(r"\A[ \t]*effort:[ \t]*(\S+)[ \t]*\r?\n?")


def _split_effort_frontmatter(text: str) -> tuple[Optional[str], str]:
    """Split an optional leading ``effort: <rung>`` line off *text*.

    Returns ``(override_or_None, remaining_prompt_text)``. The rung is
    validated via :func:`colleague.effort.validate_effort` — an unrecognised
    value raises :class:`colleague.cli._errors.CliError` naming the full
    ladder, exactly like every other operator-facing effort input (env,
    config.json, the CLI flag). Text with no leading ``effort:`` line is
    returned unchanged with ``None`` — the pre-t5, prompt-only shape.
    """
    match = _EFFORT_FRONTMATTER_RE.match(text)
    if match is None:
        return None, text
    value = _effort.validate_effort(match.group(1))
    return value, text[match.end() :]


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

    The *name* is validated as a simple identifier before it is interpolated into
    a path (#t4 Q1): a role name is never a path, so a name carrying a separator,
    dot, or ``..`` traversal is rejected (returns ``None``). The resolved file is
    additionally confined to ``.colleague/`` (symlink-safe) by
    :func:`_resolve_role_prompt`, so it can never read an arbitrary file off disk.
    """
    # Reject anything that is not a bare identifier (letters/digits/_/-). This stops
    # ``../../etc/passwd``-style traversal (and symlink-bait) before any path build.
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        return None

    # Unknown role name with no built-in default → not a role at all.
    builtin = BUILTIN_ROLES.get(name)
    if builtin is None:
        return None

    prompt = _resolve_role_prompt(Path(repo_path), layers.sanitize_model(model), name)
    # The file prompt overrides the built-in; ``None`` keeps the built-in. An
    # operator file may ALSO lead with an ``effort: <rung>`` line (#416 t5):
    # split it off (validated) before the remaining text becomes the prompt,
    # so the rung never leaks into the served system prompt.
    effort_override: Optional[str] = None
    if prompt is not None:
        effort_override, prompt = _split_effort_frontmatter(prompt)
    final_prompt = prompt if prompt is not None else builtin.prompt_fragment
    final_effort = effort_override if effort_override is not None else builtin.effort
    # The cast is for the static analyser: Sonar models dataclasses.replace()'s
    # return as a generic DataclassInstance, not Role, which trips S5886 (mirrors
    # the same cast in colleague/subagents.py for EngineConfig).
    return cast(Role, replace(builtin, prompt_fragment=final_prompt, effort=final_effort))

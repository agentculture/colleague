"""Layered, per-model config: AGENTS instructions + skills.

This module resolves operator-authored config *relative to the model currently
driving*, with strict per-model isolation: when driving model X, the loader
builds X's exact filenames/dirnames and reads only those plus the shared base.
It never globs ``AGENTS.colleague.*.md`` or iterates sibling
``.colleague/*/skills/`` directories — so model X can never load model Y's
files. Isolation is **structural** (exact-path construction), not filtering.

Two families ship here:

1. **AGENTS instructions** — concatenated into the engine system prompt, read
   from the *repo root* (the cross-tool standard location; sibling agent tools
   read ``AGENTS.md`` there too) with a user-level fallback under
   ``~/.colleague/``::

       AGENTS.md                          (shared base)
       AGENTS.colleague.md              (colleague overlay)
       AGENTS.colleague.<model>.md      (model overlay)

   Composed general -> specific, so model-specific guidance lands last.

2. **Skills** — markdown capability docs folded into the system prompt as a
   compact name + one-line-summary catalog, read from ``.colleague/`` (a
   colleague-internal concept) via :mod:`colleague.configdir`::

       .colleague/skills/*.md           (base)
       .colleague/<model>/skills/*.md   (model overlay, shadows base by stem)

MCP layering is intentionally **not** built here — a live MCP client (transport,
tool discovery, tool-call routing) needs its own spec (see ``CLAUDE.md`` scope
notes); colleague does not read ``mcp.json`` today. Only stdlib is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from colleague.configdir import collect_files, config_roots

#: Repo-root-resolved config (AGENTS) falls back to this user-level home subdir.
_USER_CONFIG_SUBDIR = ".colleague"
#: Deprecated legacy user-level subdir (pre-rename); read-only fallback below the
#: new name, kept so an existing ``~/.convertible/`` AGENTS file still resolves.
_LEGACY_USER_CONFIG_SUBDIR = ".convertible"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _within(path: Path, root: Path) -> bool:
    """True if *path* resolves to *root* or somewhere beneath it.

    Both sides are fully resolved (symlinks included), mirroring
    :meth:`colleague.tools.ToolExecutor._safe_path`. A repo-authored symlink
    whose target escapes the allowed root is rejected, so a layer file can never
    pull an arbitrary local file (``/etc/passwd``, ``~/.ssh/…``) into the system
    prompt that is then sent verbatim to a remote engine — the same confinement
    the tool loop enforces for file reads.
    """
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def _within_any(path: Path, roots: list[Path]) -> bool:
    """True if *path* is confined to at least one of *roots*."""
    return any(_within(path, root) for root in roots)


def sanitize_model(model: str) -> str:
    """Map a model id to a filename-safe token.

    Every run of characters outside ``[A-Za-z0-9._-]`` collapses to a single
    ``-``; leading/trailing ``-``/``.`` are stripped. An empty or degenerate id
    yields ``"default"``. Dots are preserved (``Qwen3.6`` and ``NVFP4`` carry
    meaning).

    Examples::

        "Qwen/Qwen3-32B"             -> "Qwen-Qwen3-32B"
        "mmangkad/Qwen3.6-27B-NVFP4" -> "mmangkad-Qwen3.6-27B-NVFP4"
        ""                           -> "default"

    Note: distinct ids can collide (``a/b`` and ``a-b`` both -> ``a-b``).
    Operators control their own model strings, so this is acceptable for v0.
    """
    token = _UNSAFE.sub("-", (model or "").strip()).strip("-.")
    return token or "default"


def resolve_root_file(
    repo_path: str | Path, relative: str, *, user_home: str | Path | None = None
) -> Path | None:
    """Return the first existing ``relative`` in [repo root, ``~/.colleague/``].

    The repo-level layer lives at the repo *root* (the cross-tool standard
    location for ``AGENTS.md``); the user-level fallback is confined to
    ``~/.colleague/`` (never bare ``~/``), with the deprecated legacy
    ``~/.convertible/`` honored at lowest precedence (read-only back-compat for
    the rename). Repo shadows user; the new user dir shadows the legacy one.
    Returns ``None`` if the file exists in none. This is the repo-root analog of
    :func:`colleague.configdir.resolve_file`, kept here so configdir's
    documented ``.colleague/``-only contract stays intact.

    A candidate whose resolved target escapes the root it was found under (e.g.
    a symlink pointing outside the repo) is skipped — layer files are confined
    just like tool reads, so they cannot smuggle external file contents into the
    system prompt.
    """
    repo_path = Path(repo_path)
    user_home = Path.home() if user_home is None else Path(user_home)
    user_root = user_home / _USER_CONFIG_SUBDIR
    legacy_user_root = user_home / _LEGACY_USER_CONFIG_SUBDIR

    # Each candidate must stay within the root it is found under.
    for candidate, root in (
        (repo_path / relative, repo_path),
        (user_root / relative, user_root),
        (legacy_user_root / relative, legacy_user_root),
    ):
        if candidate.is_file() and _within(candidate, root):
            return candidate
    return None


# --- AGENTS instructions ----------------------------------------------------

#: AGENTS layer scopes, in cascade order (general -> specific).
AGENTS_BASE = "base"
AGENTS_COLLEAGUE = "colleague"
AGENTS_MODEL = "model"


@dataclass
class AgentsLayer:
    """One resolved AGENTS instruction file."""

    path: Path
    scope: str  # AGENTS_BASE | AGENTS_COLLEAGUE | AGENTS_MODEL
    text: str


def resolve_agents(
    repo_path: str | Path, model: str, *, user_home: str | Path | None = None
) -> list[AgentsLayer]:
    """Resolve AGENTS instruction layers for *model only*, general -> specific.

    Builds three exact relative names and reads each that exists::

        AGENTS.md  ->  AGENTS.colleague.md  ->  AGENTS.colleague.<model>.md

    The ``<model>`` token comes from :func:`sanitize_model` and is *constructed*,
    never matched by glob, so another model's overlay is structurally invisible.
    Missing or unreadable layers are skipped, never raised.
    """
    safe = sanitize_model(model)
    relnames = [
        (AGENTS_BASE, "AGENTS.md"),
        (AGENTS_COLLEAGUE, "AGENTS.colleague.md"),
        (AGENTS_MODEL, f"AGENTS.colleague.{safe}.md"),
    ]
    layers: list[AgentsLayer] = []
    for scope, rel in relnames:
        path = resolve_root_file(repo_path, rel, user_home=user_home)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        layers.append(AgentsLayer(path=path, scope=scope, text=text))
    return layers


def compose_agents(layers: list[AgentsLayer]) -> str:
    """Concatenate layer texts general -> specific, blank-line separated."""
    return "\n\n".join(layer.text.strip() for layer in layers if layer.text.strip())


# --- Skills -----------------------------------------------------------------

#: Skill layer scopes.
SKILL_BASE = "base"
SKILL_MODEL = "model"


@dataclass
class Skill:
    """One resolved skill doc."""

    name: str
    path: Path
    scope: str  # SKILL_BASE | SKILL_MODEL


def resolve_skills(
    repo_path: str | Path, model: str, *, user_home: str | Path | None = None
) -> dict[str, Skill]:
    """Resolve skill docs for *model only*; model overlay shadows base by stem.

    base:  ``.colleague/skills/*.md``
    model: ``.colleague/<model>/skills/*.md``

    Each axis reuses :func:`colleague.configdir.collect_files`, so repo-level
    ``.colleague/`` already shadows user-level ``~/.colleague/`` underneath —
    two orthogonal precedence axes, both structural. The ``<model>`` directory
    name is constructed from :func:`sanitize_model`; sibling model dirs are never
    iterated.

    A skill file whose resolved target escapes every ``.colleague/`` root (e.g.
    a symlink pointing outside the config dirs) is skipped, so a repo cannot
    smuggle external file contents into the system prompt via a skill doc.
    """
    safe = sanitize_model(model)
    roots = config_roots(repo_path, user_home=user_home)
    base = collect_files(repo_path, "skills", suffix=".md", user_home=user_home)
    overlay = collect_files(repo_path, f"{safe}/skills", suffix=".md", user_home=user_home)

    skills: dict[str, Skill] = {}
    for name, path in base.items():
        if _within_any(path, roots):
            skills[name] = Skill(name=name, path=path, scope=SKILL_BASE)
    for name, path in overlay.items():
        if _within_any(path, roots):
            skills[name] = Skill(name=name, path=path, scope=SKILL_MODEL)
    return skills


def _first_summary_line(text: str) -> str:
    """First descriptive line of a skill doc, as a one-line summary.

    Prefers the first non-empty, non-heading line — skill bodies usually open
    with an ``# H1`` title that just repeats the skill name, so the prose line
    beneath it is the useful summary. Falls back to the first heading's text if
    the doc is heading-only.
    """
    fallback = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if not fallback:
                fallback = stripped.lstrip("#").strip()
            continue
        return stripped
    return fallback


def compose_skills(skills: dict[str, Skill]) -> str:
    """Render resolved skills as a compact name + one-line-summary catalog.

    Token-cheap: never inlines full bodies. Returns ``""`` when there are no
    skills. Skill docs are read here for their summary line; an unreadable doc
    degrades to a name-only entry rather than raising.
    """
    if not skills:
        return ""
    lines = ["Available skills (operator-authored capability docs):"]
    for name in sorted(skills):
        try:
            summary = _first_summary_line(skills[name].path.read_text(encoding="utf-8"))
        except OSError:
            summary = ""
        lines.append(f"- {name}: {summary}" if summary else f"- {name}")
    return "\n".join(lines)


# --- Composition ------------------------------------------------------------


def system_prompt_for(
    repo_path: str | Path,
    model: str,
    *,
    user_home: str | Path | None = None,
    base: str,
) -> str | None:
    """Compose the system prompt for *model*: ``base`` + AGENTS + skills catalog.

    Order is general -> specific: the engine's ``base`` default first, then the
    composed AGENTS layers, then the skills catalog. Returns ``None`` when there
    are no AGENTS layers and no skills, so the caller keeps its own default and
    behavior is byte-identical to a layer-free run.
    """
    agents_text = compose_agents(resolve_agents(repo_path, model, user_home=user_home))
    skills_text = compose_skills(resolve_skills(repo_path, model, user_home=user_home))
    if not agents_text and not skills_text:
        return None
    return "\n\n".join(part for part in (base, agents_text, skills_text) if part)

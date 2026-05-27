"""Layered, per-model config: AGENTS instructions + skills.

This module resolves operator-authored config *relative to the model currently
driving*, with strict per-model isolation: when driving model X, the loader
builds X's exact filenames/dirnames and reads only those plus the shared base.
It never globs ``AGENTS.convertible.*.md`` or iterates sibling
``.convertible/*/skills/`` directories — so model X can never load model Y's
files. Isolation is **structural** (exact-path construction), not filtering.

Two families ship here:

1. **AGENTS instructions** — concatenated into the engine system prompt, read
   from the *repo root* (the cross-tool standard location; sibling agent tools
   read ``AGENTS.md`` there too) with a user-level fallback under
   ``~/.convertible/``::

       AGENTS.md                          (shared base)
       AGENTS.convertible.md              (convertible overlay)
       AGENTS.convertible.<model>.md      (model overlay)

   Composed general -> specific, so model-specific guidance lands last.

2. **Skills** — markdown capability docs folded into the system prompt as a
   compact name + one-line-summary catalog, read from ``.convertible/`` (a
   convertible-internal concept) via :mod:`convertible.configdir`::

       .convertible/skills/*.md           (base)
       .convertible/<model>/skills/*.md   (model overlay, shadows base by stem)

MCP layering is intentionally **not** built here — a live MCP client (transport,
tool discovery, tool-call routing) needs its own spec (see ``CLAUDE.md`` scope
notes); convertible does not read ``mcp.json`` today. Only stdlib is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from convertible.configdir import collect_files

#: Repo-root-resolved config (AGENTS) falls back to this user-level home subdir.
_USER_CONFIG_SUBDIR = ".convertible"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


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
    """Return the first existing ``relative`` in [repo root, ``~/.convertible/``].

    The repo-level layer lives at the repo *root* (the cross-tool standard
    location for ``AGENTS.md``); the user-level fallback is confined to
    ``~/.convertible/`` (never bare ``~/``). Repo shadows user. Returns ``None``
    if the file exists in neither. This is the repo-root analog of
    :func:`convertible.configdir.resolve_file`, kept here so configdir's
    documented ``.convertible/``-only contract stays intact.
    """
    repo_path = Path(repo_path)
    user_home = Path.home() if user_home is None else Path(user_home)

    for candidate in (
        repo_path / relative,
        user_home / _USER_CONFIG_SUBDIR / relative,
    ):
        if candidate.is_file():
            return candidate
    return None


# --- AGENTS instructions ----------------------------------------------------

#: AGENTS layer scopes, in cascade order (general -> specific).
AGENTS_BASE = "base"
AGENTS_CONVERTIBLE = "convertible"
AGENTS_MODEL = "model"


@dataclass
class AgentsLayer:
    """One resolved AGENTS instruction file."""

    path: Path
    scope: str  # AGENTS_BASE | AGENTS_CONVERTIBLE | AGENTS_MODEL
    text: str


def resolve_agents(
    repo_path: str | Path, model: str, *, user_home: str | Path | None = None
) -> list[AgentsLayer]:
    """Resolve AGENTS instruction layers for *model only*, general -> specific.

    Builds three exact relative names and reads each that exists::

        AGENTS.md  ->  AGENTS.convertible.md  ->  AGENTS.convertible.<model>.md

    The ``<model>`` token comes from :func:`sanitize_model` and is *constructed*,
    never matched by glob, so another model's overlay is structurally invisible.
    Missing or unreadable layers are skipped, never raised.
    """
    safe = sanitize_model(model)
    relnames = [
        (AGENTS_BASE, "AGENTS.md"),
        (AGENTS_CONVERTIBLE, "AGENTS.convertible.md"),
        (AGENTS_MODEL, f"AGENTS.convertible.{safe}.md"),
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

    base:  ``.convertible/skills/*.md``
    model: ``.convertible/<model>/skills/*.md``

    Each axis reuses :func:`convertible.configdir.collect_files`, so repo-level
    ``.convertible/`` already shadows user-level ``~/.convertible/`` underneath —
    two orthogonal precedence axes, both structural. The ``<model>`` directory
    name is constructed from :func:`sanitize_model`; sibling model dirs are never
    iterated.
    """
    safe = sanitize_model(model)
    base = collect_files(repo_path, "skills", suffix=".md", user_home=user_home)
    overlay = collect_files(repo_path, f"{safe}/skills", suffix=".md", user_home=user_home)

    skills: dict[str, Skill] = {
        name: Skill(name=name, path=path, scope=SKILL_BASE) for name, path in base.items()
    }
    for name, path in overlay.items():
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

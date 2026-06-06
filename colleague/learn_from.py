"""learn-from adapter core (stage 1).

Turns ``.claude/skills/<name>/SKILL.md`` (Claude Code directory-per-skill with
YAML frontmatter) into flat ``.colleague/skills/<name>.md`` files that
``colleague/layers.py`` can fold into the model system prompt.

Only stdlib is used.  No subprocess, threading, or concurrent.futures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROVENANCE_PREFIX = "<!-- learned-from:"  # marker line prefix


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ClaudeSkill:
    """Parsed Claude skill."""

    name: str  # frontmatter ``name``, else the skill directory name
    description: str  # folded to a single line ("" if none)
    body: str  # markdown body after the closing ``---`` (or whole file if none)
    source: Path  # the SKILL.md path
    scripts_dir: Path | None  # <skill_dir>/scripts if it exists, else None


@dataclass
class AdaptResult:
    """Result of adapting one skill."""

    name: str
    source: str  # str(source SKILL.md path)
    dest: str  # str(dest .colleague/skills/<name>.md path)
    # created|updated|skipped|would-create|would-update|would-skip|protected|not-found
    action: str
    runnable_estimate: str  # full | partial | instructional-only
    note: str = ""  # short human note, e.g. why protected/skipped


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    """``(open_idx, close_idx)`` of the ``---`` fences, or None if absent.

    Leading blank lines before the opening fence are skipped; None means there is
    no opening fence, or it is never closed (an unterminated frontmatter).
    """
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return None
    for i in range(idx + 1, len(lines)):
        if lines[i].strip() == "---":
            return (idx, i)
    return None


def _collect_block(lines: list[str], start: int, close_idx: int) -> tuple[list[str], int]:
    """Collect a block scalar's lines (blank or indented) from *start*.

    Returns the raw collected lines and the index of the first unconsumed line.
    """
    block: list[str] = []
    j = start
    while j < close_idx and (lines[j] == "" or lines[j][:1] in (" ", "\t")):
        block.append(lines[j])
        j += 1
    return block, j


def _fold_block(block: list[str]) -> str:
    """YAML folded scalar (``>``): join non-blank lines, collapse whitespace."""
    folded = " ".join(ln.strip() for ln in block if ln.strip())
    return re.sub(r"\s+", " ", folded).strip()


def _literal_block(block: list[str]) -> str:
    """YAML literal scalar (``|``): keep interior newlines, strip the common indent."""
    indent = next((len(b) - len(b.lstrip()) for b in block if b.strip()), 0)
    dedented = [b[indent:] if len(b) >= indent else b for b in block]
    while dedented and not dedented[0].strip():
        dedented.pop(0)
    while dedented and not dedented[-1].strip():
        dedented.pop()
    return "\n".join(dedented)


def _strip_quotes(value: str) -> str:
    """Strip one layer of matching surrounding single/double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _extract_body(lines: list[str], close_idx: int) -> str:
    """Lines after the closing fence, with leading/trailing blank lines removed."""
    body = lines[close_idx + 1 :]
    while body and body[0].strip() == "":
        body.pop(0)
    while body and body[-1].strip() == "":
        body.pop()
    return "\n".join(body)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ({key: value, ...}, body).

    - If the text does not start (after an optional UTF-8 BOM / leading blank
      lines) with a line that is exactly ``---``, return ({}, text) — no frontmatter.
    - Otherwise parse ``key: value`` lines until the closing ``---``.
    - Block scalars: if a value is exactly ``>``, ``>-``, ``|``, or ``|-`` (ignoring
      trailing spaces), read subsequent more-indented (or blank) lines as the
      value. Fold ``>``/``>-`` by joining non-blank lines with a single space and
      collapsing internal whitespace runs to one space. Keep ``|``/``|-`` newlines.
    - Strip matching surrounding single/double quotes from simple scalar values.
    - body is everything after the closing ``---``, with leading blank lines removed.
    - An unterminated frontmatter (no closing ``---``) => treat the WHOLE text as
      body and return ({}, text).
    """
    # Strip BOM if present
    if text.startswith("\ufeff"):
        text = text[len("\ufeff") :]

    lines = text.split("\n")
    bounds = _frontmatter_bounds(lines)
    if bounds is None:  # no opening fence, or unterminated -> whole text is body
        return ({}, text)
    open_idx, close_idx = bounds

    meta: dict[str, str] = {}
    i = open_idx + 1
    while i < close_idx:
        line = lines[i]
        m = re.match(r"^(\w[\w\-]*):\s*(.*)", line) if line.strip() else None
        if m is None:  # blank or non-key line
            i += 1
            continue
        key, raw_value = m.group(1), m.group(2).strip()
        if raw_value in (">", ">-", "|", "|-"):
            block, i = _collect_block(lines, i + 1, close_idx)
            meta[key] = _fold_block(block) if raw_value[0] == ">" else _literal_block(block)
        else:
            meta[key] = _strip_quotes(raw_value)
            i += 1

    return (meta, _extract_body(lines, close_idx))


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------


def load_claude_skill(skill_dir: Path) -> ClaudeSkill | None:
    """Read <skill_dir>/SKILL.md. Return None if it is missing/unreadable.

    name falls back to skill_dir.name when frontmatter has no ``name``.
    """
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError:
        return None

    meta, body = parse_frontmatter(text)

    name = meta.get("name", "").strip() or skill_dir.name
    description = meta.get("description", "").strip()

    # Strip leading blank lines from body
    body = body.lstrip("\n")

    scripts_dir: Path | None = None
    scripts_candidate = skill_dir / "scripts"
    if scripts_candidate.is_dir():
        scripts_dir = scripts_candidate

    return ClaudeSkill(
        name=name,
        description=description,
        body=body,
        source=skill_file,
        scripts_dir=scripts_dir,
    )


# ---------------------------------------------------------------------------
# Runnable estimate
# ---------------------------------------------------------------------------


def estimate_runnable(skill: ClaudeSkill) -> str:
    """Honest heuristic from the body text (case-insensitive).

    Returns one of:
    - ``'instructional-only'`` if the body references scripts (e.g. ``scripts/``,
      ``.sh``, ``python3 ``, ``./``) OR Claude-specific machinery (``Skill tool``,
      ``slash command``, a leading-slash command token like ``/think``, ``/cicd``).
    - ``'partial'`` if it mentions running commands generally but not the above.
    - ``'full'`` otherwise (pure instructional prose).

    This is a heuristic — it inspects the body text for patterns that suggest
    the skill requires external tooling or scripts to be useful.
    """
    body_lower = skill.body.lower()

    # Instructional-only patterns
    instructional_patterns = [
        "scripts/",
        ".sh",
        "python3 ",
        "./",
        "skill tool",
        "slash command",
    ]
    for pat in instructional_patterns:
        if pat in body_lower:
            return "instructional-only"

    # Leading-slash command tokens like /think, /cicd
    if re.search(r"/[a-z]+", body_lower):
        return "instructional-only"

    # Partial: mentions running commands generally
    command_patterns = [
        "run ",
        "execute ",
        "execute",
        "command",
        "terminal",
        "shell",
        "bash",
        "script",
    ]
    for pat in command_patterns:
        if pat in body_lower:
            return "partial"

    return "full"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_colleague_skill(skill: ClaudeSkill) -> str:
    """Deterministic adapted markdown.

    EXACT shape (note the description line is FIRST so _first_summary_line
    returns the description, NOT the comment)::

        <description folded to one line, or the body's first line if empty>

        <!-- learned-from: claude; source: <path>; scripts: <path|->; adapt: pending -->

        # <name>

        <body>

    If description is empty AND the body has no usable first line, the doc may
    start directly with the provenance comment then ``# <name>`` then body.

    Must be idempotent: same ClaudeSkill in => byte-identical string out (no
    timestamps, no randomness). End with exactly one trailing newline.
    """
    parts: list[str] = []

    # Determine the first summary line
    first_summary = skill.description
    if not first_summary:
        # Try to get the body's own first summary line
        for raw in skill.body.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            first_summary = stripped
            break

    if first_summary:
        parts.append(first_summary)

    # Provenance comment
    scripts_str = str(skill.scripts_dir) if skill.scripts_dir else "-"
    provenance = (
        f"<!-- learned-from: claude; source: {skill.source}; "
        f"scripts: {scripts_str}; adapt: pending -->"
    )
    parts.append(provenance)

    # Name heading
    parts.append(f"# {skill.name}")

    # Body
    if skill.body:
        parts.append(skill.body)

    result = "\n\n".join(parts)
    # Ensure exactly one trailing newline
    result = result.rstrip("\n") + "\n"
    return result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_claude_skills(root: Path, *, user: bool = False) -> dict[str, Path]:
    """Map skill name -> SKILL.md path.

    - user=False: scan <root>/.claude/skills/*/SKILL.md
    - user=True: scan <Path.home()/.claude/skills/*/SKILL.md
    Skill name is the immediate parent directory name. Sorted, deterministic.
    Missing dir => empty dict (never raise).
    """
    if user:
        base = Path.home() / ".claude" / "skills"
    else:
        base = root / ".claude" / "skills"

    result: dict[str, Path] = {}
    if not base.is_dir():
        return result

    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            result[entry.name] = skill_file

    return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _discover_claude(root: Path, user: bool) -> dict[str, Path]:
    """Discoverer callable for the claude source."""
    return discover_claude_skills(root, user=user)


_SOURCES: dict[str, Callable[[Path, bool], dict[str, Path]]] = {
    "claude": _discover_claude,
}


def available_sources() -> list[str]:
    """Sorted list of known learn-from source names (currently just ``claude``)."""
    return sorted(_SOURCES)


def _safe_stem(name: str) -> str:
    """A filesystem-safe, single-component stem for a skill *name*.

    A SKILL.md ``name`` (or a CLI-supplied name) is untrusted input. Strip any
    path separators / parent refs and unsafe characters so it can never address a
    file outside ``.colleague/skills/`` (path-injection defense, S2083). Falls
    back to ``"skill"`` for a degenerate name.
    """
    base = re.split(r"[\\/]", name.strip())[-1]  # keep only the last path component
    base = re.sub(r"[^A-Za-z0-9._-]", "-", base).strip(".-")
    return base or "skill"


def _skill_dest(repo: Path, name: str) -> Path:
    """Confined output path for a learned skill — always inside ``.colleague/skills/``.

    The stem is sanitized via :func:`_safe_stem`, so the result is structurally a
    direct child of the skills dir; a crafted *name* can never traverse out.
    """
    return repo / ".colleague" / "skills" / f"{_safe_stem(name)}.md"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _select_skills(
    skills_map: dict[str, Path], names: list[str] | None
) -> tuple[dict[str, Path], set[str]]:
    """Split discovered skills into (selected, requested-but-not-found)."""
    if names is None:
        return skills_map, set()
    selected = {n: skills_map[n] for n in names if n in skills_map}
    return selected, set(names) - set(skills_map)


def _plan_write(dest: Path, rendered: str, *, dry_run: bool, force: bool) -> tuple[str, str]:
    """Decide the action for one rendered skill, performing the write when due.

    Returns ``(action, note)``. Writes to *dest* only on a real (non-dry-run)
    create or update. Mirrors the documented create/skip/update/protect rules.
    """
    if not dest.exists():
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(rendered, encoding="utf-8")
        return ("would-create" if dry_run else "created", "")

    existing = dest.read_text(encoding="utf-8")
    if existing == rendered:
        return ("would-skip" if dry_run else "skipped", "")

    owned = any(ln.startswith(PROVENANCE_PREFIX) for ln in existing.split("\n"))
    if not force:
        if owned:
            return ("would-skip" if dry_run else "skipped", "differs; pass --force")
        return ("protected", "hand-authored; pass --force to overwrite")
    if not dry_run:
        dest.write_text(rendered, encoding="utf-8")
    return ("would-update" if dry_run else "updated", "")


def _adapt_one(
    repo: Path, name: str, skill_path: Path, *, dry_run: bool, force: bool
) -> AdaptResult:
    """Adapt a single discovered skill into an :class:`AdaptResult`."""
    skill = load_claude_skill(skill_path.parent)
    if skill is None:
        return AdaptResult(
            name=name,
            source=str(skill_path),
            dest=str(_skill_dest(repo, name)),
            action="not-found",
            runnable_estimate="instructional-only",
            note="SKILL.md unreadable",
        )
    rendered = render_colleague_skill(skill)
    dest = _skill_dest(repo, skill.name)
    action, note = _plan_write(dest, rendered, dry_run=dry_run, force=force)
    return AdaptResult(
        name=skill.name,
        source=str(skill.source),
        dest=str(dest),
        action=action,
        runnable_estimate=estimate_runnable(skill),
        note=note,
    )


def adapt_skills(
    repo: Path,
    *,
    source: str,
    names: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    user: bool = False,
) -> list[AdaptResult]:
    """The single entry point the CLI calls.

    - source must be a key in the module-level registry ``_SOURCES`` (currently
      only 'claude'); an unknown source raises ``ValueError``.
    - Discover skills via the registered discoverer. If ``names`` is given, filter
      to those; a requested name not discovered yields an ``AdaptResult`` with
      action='not-found' (do not raise).
    - For each skill: render the colleague doc; dest is
      ``<repo>/.colleague/skills/<name>.md``.
        * dest missing: action 'created' (or 'would-create' if dry_run).
        * dest exists, byte-identical to rendered: action 'skipped'/'would-skip'.
        * dest exists, differs, and CONTAINS a line starting with
          PROVENANCE_PREFIX (colleague-owned): update only if force
          (action 'updated'/'would-update'), else 'skipped' with a note
          'differs; pass --force'.
        * dest exists, differs, and has NO provenance marker (hand-authored):
          'protected' with a note unless force (then 'updated'/'would-update').
    - Create ``<repo>/.colleague/skills/`` when needed (only when actually writing,
      i.e. not dry_run). Never write on dry_run.
    - Return results sorted by name, deterministic order.
    """
    if source not in _SOURCES:
        raise ValueError(f"unknown source: {source}")

    skills_map = _SOURCES[source](repo, user=user)
    selected, not_found = _select_skills(skills_map, names)

    results: list[AdaptResult] = [
        AdaptResult(
            name=n,
            source="",
            dest=str(_skill_dest(repo, n)),
            action="not-found",
            runnable_estimate="instructional-only",
            note="skill not found in source",
        )
        for n in sorted(not_found)
    ]
    for name in sorted(selected):
        results.append(_adapt_one(repo, name, selected[name], dry_run=dry_run, force=force))

    results.sort(key=lambda r: r.name)
    return results

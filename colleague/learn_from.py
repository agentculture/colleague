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

    # Find the opening --- (skip leading blank lines)
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1

    if idx >= len(lines) or lines[idx].strip() != "---":
        # No frontmatter
        return ({}, text)

    # We have an opening ---. Now look for the closing ---.
    # If we never find it, treat the whole text as body.
    close_idx = None
    for i in range(idx + 1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        # Unterminated frontmatter — treat whole text as body
        return ({}, text)

    # Parse key: value lines between opening and closing ---
    meta: dict[str, str] = {}
    i = idx + 1
    while i < close_idx:
        line = lines[i]
        # Skip blank lines inside frontmatter
        if line.strip() == "":
            i += 1
            continue
        # Check for key: value
        m = re.match(r"^(\w[\w\-]*):\s*(.*)", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        raw_value = m.group(2).strip()

        # Check for block scalar indicator
        if raw_value in (">", ">-", "|", "|-"):
            # Collect subsequent lines that are more indented or blank
            block_lines: list[str] = []
            j = i + 1
            while j < close_idx:
                next_line = lines[j]
                # Block content: blank lines or lines that start with whitespace
                # (more indented than the key: line, which has no leading space)
                if next_line == "" or next_line[:1] in (" ", "\t"):
                    block_lines.append(next_line)
                    j += 1
                else:
                    break
            i = j

            if raw_value in (">", ">-"):
                # Fold: join non-blank lines with single space, collapse whitespace
                non_blank = [ln.strip() for ln in block_lines if ln.strip()]
                value = " ".join(non_blank)
                # Collapse internal whitespace runs to one space
                value = re.sub(r"\s+", " ", value).strip()
            else:
                # Literal: keep newlines, but strip the block's common leading
                # indent (YAML determines it from the first non-blank line).
                indent = 0
                for bl in block_lines:
                    if bl.strip():
                        indent = len(bl) - len(bl.lstrip())
                        break
                dedented = [bl[indent:] if len(bl) >= indent else bl for bl in block_lines]
                # Drop leading/trailing blank lines, then keep interior newlines.
                while dedented and not dedented[0].strip():
                    dedented.pop(0)
                while dedented and not dedented[-1].strip():
                    dedented.pop()
                value = "\n".join(dedented)
            meta[key] = value
            # block-scalar branch already advanced i to j (the next unconsumed line)
        else:
            # Simple scalar — strip surrounding quotes
            value = raw_value
            if len(value) >= 2:
                if (value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'"):
                    value = value[1:-1]
            meta[key] = value
            i += 1

    # Body is everything after the closing ---, with surrounding blank lines removed
    body_lines = lines[close_idx + 1 :]
    # Strip leading blank lines
    while body_lines and body_lines[0].strip() == "":
        body_lines.pop(0)
    # Strip trailing blank lines (e.g. the final newline's empty split element)
    while body_lines and body_lines[-1].strip() == "":
        body_lines.pop()
    body = "\n".join(body_lines)

    return (meta, body)


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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


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

    discoverer = _SOURCES[source]
    skills_map = discoverer(repo, user=user)

    # Filter by names if provided
    if names is not None:
        filtered: dict[str, Path] = {}
        for n in names:
            if n in skills_map:
                filtered[n] = skills_map[n]
        # Track requested names not found
        not_found_names = set(names) - set(skills_map.keys())
    else:
        filtered = skills_map
        not_found_names = set()

    results: list[AdaptResult] = []

    # Handle not-found names
    for n in sorted(not_found_names):
        dest = repo / ".colleague" / "skills" / f"{n}.md"
        results.append(
            AdaptResult(
                name=n,
                source="",
                dest=str(dest),
                action="not-found",
                runnable_estimate="instructional-only",
                note="skill not found in source",
            )
        )

    # Process discovered skills
    for name in sorted(filtered.keys()):
        skill_path = filtered[name]
        skill = load_claude_skill(skill_path.parent)
        if skill is None:
            dest = repo / ".colleague" / "skills" / f"{name}.md"
            results.append(
                AdaptResult(
                    name=name,
                    source=str(skill_path),
                    dest=str(dest),
                    action="not-found",
                    runnable_estimate="instructional-only",
                    note="SKILL.md unreadable",
                )
            )
            continue

        rendered = render_colleague_skill(skill)
        dest = repo / ".colleague" / "skills" / f"{skill.name}.md"
        runnable = estimate_runnable(skill)

        if not dest.exists():
            if dry_run:
                action = "would-create"
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(rendered, encoding="utf-8")
                action = "created"
            results.append(
                AdaptResult(
                    name=skill.name,
                    source=str(skill.source),
                    dest=str(dest),
                    action=action,
                    runnable_estimate=runnable,
                )
            )
        else:
            existing = dest.read_text(encoding="utf-8")
            if existing == rendered:
                action = "would-skip" if dry_run else "skipped"
                results.append(
                    AdaptResult(
                        name=skill.name,
                        source=str(skill.source),
                        dest=str(dest),
                        action=action,
                        runnable_estimate=runnable,
                    )
                )
            else:
                # Differs — check for provenance marker
                note = ""
                has_marker = any(
                    line.startswith(PROVENANCE_PREFIX) for line in existing.split("\n")
                )

                if has_marker:
                    # Colleague-owned
                    if force:
                        if dry_run:
                            action = "would-update"
                        else:
                            dest.write_text(rendered, encoding="utf-8")
                            action = "updated"
                    else:
                        action = "skipped"
                        note = "differs; pass --force"
                else:
                    # Hand-authored
                    if force:
                        if dry_run:
                            action = "would-update"
                        else:
                            dest.write_text(rendered, encoding="utf-8")
                            action = "updated"
                        note = ""
                    else:
                        action = "protected"
                        note = "hand-authored; pass --force to overwrite"

                results.append(
                    AdaptResult(
                        name=skill.name,
                        source=str(skill.source),
                        dest=str(dest),
                        action=action,
                        runnable_estimate=runnable,
                        note=note,
                    )
                )

    # Sort by name
    results.sort(key=lambda r: r.name)
    return results

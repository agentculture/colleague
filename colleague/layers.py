"""Layered, per-model config: AGENTS instructions + skills + typed roles.

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

   The composed catalog can be **token-capped** (:func:`compose_skills`,
   :func:`resolve_skills_token_cap`, :func:`select_skills_within_budget`): an
   optional ``<!-- skill-priority: N -->`` marker (lower ``N`` = higher
   priority, default 100) decides which WHOLE skills survive when a cap
   would otherwise be exceeded — never a mid-skill truncation, and always an
   explicit ``omitted N skill(s) over the token cap: ...`` note. A cap of
   ``0`` (the default, whether from an explicit parameter or the absent
   ``COLLEAGUE_SKILLS_TOKEN_CAP`` env var) is uncapped: byte-identical to the
   catalog with no cap awareness at all.

3. **Typed roles** — :func:`compose_role_prompt` extends the existing
   prompt-assembly path with an optional role: the role's ``prompt_fragment``
   composes after AGENTS layers, and the role's ``skill_subset`` filters the
   skills catalog.  Composition order (fixed, documented)::

       base (engine default)
       AGENTS layers (general -> specific)
       role prompt_fragment (when non-empty)
       skills catalog (filtered by role.skill_subset)

   Per-model role-prompt overlays live at
   ``.colleague/<model>/agents/<name>.md`` (exact path via :func:`sanitize_model`,
   no sibling globbing) — matching the established skills/hooks overlay
   convention.  :func:`colleague.roles.load_role` reads these overlays.

4. **Task-local evaluator section** (plan ``three-tier-execution`` t5) —
   :func:`compose_evaluator_section` renders an optional, task-local,
   cortex- or host-authored note as ONE named, bounded markdown section
   (heading :data:`EVALUATOR_SECTION_HEADING`).  :func:`system_prompt_for`
   and :func:`compose_role_prompt` both accept it via the
   ``evaluator_section``/``evaluator_seat`` keyword-only parameters and
   append it through the SAME composition path documented above — no second
   assembly path.  ``None``/empty text renders nothing (byte-identical to a
   call that omits the parameter).  This module does not decide *who*
   supplies the text or *when* it is composed (that is a later task, e.g. an
   opt-in cortex configurator writing through the ``colleague.lattice``
   ``worker.prompt.evaluator`` / ``senses.prompt.evaluator`` targets) — it
   only provides the bounded rendering primitive.

MCP layering is intentionally **not** built here — a live MCP client (transport,
tool discovery, tool-call routing) needs its own spec (see ``CLAUDE.md`` scope
notes); colleague does not read ``mcp.json`` today. Only stdlib is used.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from colleague.configdir import collect_files, config_roots
from colleague.context import count_tokens_chars

if TYPE_CHECKING:
    from colleague.roles import Role

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
    yields ``"default"``. Dots are preserved (``Qwen3.8`` and ``NVFP4`` carry
    meaning).

    Examples::

        "Qwen/Qwen3-32B"             -> "Qwen-Qwen3-32B"
        "unsloth/Qwen3.8-27B-NVFP4"  -> "unsloth-Qwen3.8-27B-NVFP4"
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


#: A single-line HTML comment, e.g. ``<!-- learned-from: ... -->`` or
#: ``<!-- skill-priority: 5 -->`` — a metadata marker, never the summary.
_HTML_COMMENT_LINE_RE = re.compile(r"^<!--.*-->$")


def _first_summary_line(text: str) -> str:
    """First descriptive line of a skill doc, as a one-line summary.

    Prefers the first non-empty, non-heading, non-comment-marker line — skill
    bodies usually open with an ``# H1`` title that just repeats the skill
    name, so the prose line beneath it is the useful summary. A single-line
    HTML comment (the ``<!-- learned-from: ... -->`` provenance marker or the
    ``<!-- skill-priority: N -->`` marker) is skipped wherever it appears, so
    an operator-authored priority marker never leaks into the composed
    catalog as if it were the summary. Falls back to the first heading's text
    if the doc is heading-only.
    """
    fallback = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if _HTML_COMMENT_LINE_RE.match(stripped):
            continue
        if stripped.startswith("#"):
            if not fallback:
                fallback = stripped.lstrip("#").strip()
            continue
        return stripped
    return fallback


# --- Priority marker + token-capped composition -----------------------------

#: ``<!-- skill-priority: N -->`` — the same HTML-comment-marker idiom as
#: learn-from's ``<!-- learned-from: ... -->`` provenance marker. Lower ``N``
#: means higher priority (survives longest when the catalog must be capped).
_SKILL_PRIORITY_RE = re.compile(r"<!--\s*skill-priority:\s*(-?\d+)\s*-->")

#: Priority assigned to a skill doc that carries no (or a malformed)
#: ``skill-priority`` marker. A neutral middle value: an explicitly
#: high-priority skill (``N < 100``) always outranks an unmarked one, and an
#: explicitly low-priority skill (``N > 100``) is dropped before an unmarked
#: one.
SKILL_PRIORITY_DEFAULT = 100

#: Env vars resolving the skills-catalog token cap, highest precedence first.
#: ``CONVERTIBLE_*`` is the deprecated legacy name honored as a read fallback
#: (matches every other ``COLLEAGUE_*``/``CONVERTIBLE_*`` pair in the repo).
_SKILLS_TOKEN_CAP_ENV = ("COLLEAGUE_SKILLS_TOKEN_CAP", "CONVERTIBLE_SKILLS_TOKEN_CAP")

#: 0 = uncapped. This is the honesty-condition-h4 floor: with no explicit cap
#: (no parameter, no env var) composition is byte-identical to today.
_DEFAULT_SKILLS_TOKEN_CAP = 0


def parse_skill_priority(text: str) -> int:
    """Parse the optional ``<!-- skill-priority: N -->`` marker from *text*.

    Returns :data:`SKILL_PRIORITY_DEFAULT` (100) when the marker is absent or
    does not match (e.g. a non-integer value) — never raises.
    """
    match = _SKILL_PRIORITY_RE.search(text)
    if not match:
        return SKILL_PRIORITY_DEFAULT
    return int(match.group(1))


def skill_priority(skill: Skill) -> int:
    """Read + parse *skill*'s declared priority (see :func:`parse_skill_priority`).

    Convenience for a caller that only has a :class:`Skill` (e.g. the
    ``skills`` CLI inspection verb) — degrades to
    :data:`SKILL_PRIORITY_DEFAULT` on an unreadable doc, same as an absent
    marker.
    """
    return parse_skill_priority(_read_skill_text(skill))


def count_skill_tokens_chars(text: str) -> int:
    """Default token-cap counter for skill-catalog text.

    The skills catalog is composed as flat markdown text, not the OpenAI
    chat-message-list shape :func:`colleague.context.count_tokens_chars`
    expects, so this adapts one into the other rather than re-implementing
    the char-heuristic (chars // 4, minimum 1 for non-empty text) — the two
    heuristics can never drift apart because this delegates directly.
    """
    if not text:
        return 0
    return count_tokens_chars([{"content": text}])


def resolve_skills_token_cap(explicit: int | None = None) -> int:
    """Resolve the skills-catalog token cap.

    Precedence: *explicit* parameter wins; else the
    ``COLLEAGUE_SKILLS_TOKEN_CAP`` env var; else the legacy
    ``CONVERTIBLE_SKILLS_TOKEN_CAP`` env var; else the built-in default
    (``0`` = uncapped). A malformed env value is skipped, not raised.
    """
    if explicit is not None:
        return explicit
    for key in _SKILLS_TOKEN_CAP_ENV:
        raw = os.environ.get(key)
        if raw:
            try:
                return int(raw)
            except ValueError:
                continue
    return _DEFAULT_SKILLS_TOKEN_CAP


def select_skills_within_budget(
    skills: dict[str, Skill],
    token_cap: int,
    *,
    count_tokens: Callable[[str], int] | None = None,
) -> tuple[dict[str, Skill], list[str]]:
    """Select the subset of *skills* whose composed catalog fits *token_cap*.

    ``token_cap <= 0`` is **uncapped**: every skill is kept, nothing omitted
    (byte-identical to a cap-unaware composition — the h4 floor).

    Otherwise, whole skills are dropped **lowest-priority first** (an
    optional ``<!-- skill-priority: N -->`` marker in the skill doc, default
    :data:`SKILL_PRIORITY_DEFAULT`, lower ``N`` = higher priority — see
    :func:`parse_skill_priority`) until the composed catalog (rendered the
    same way :func:`compose_skills` renders it, sans any omitted-note) fits
    within the cap. A skill is **never partially included** — it is either
    fully present or fully omitted; nothing is truncated mid-text.

    Ties (equal priority) are broken by **reverse name order**: the
    alphabetically LATER name is dropped first. This is deterministic and
    documented, not implementation-incidental.

    Returns ``(kept, omitted_names)`` where ``omitted_names`` lists the
    dropped skills in the order they were dropped (worst-priority-first,
    ties reverse-name-first) — the same order surfaced in
    :func:`compose_skills`'s "omitted N skill(s)" note.
    """
    if not skills or token_cap <= 0:
        return dict(skills), []

    count = count_tokens if count_tokens is not None else count_skill_tokens_chars
    names = sorted(skills)
    kept = list(names)

    if count(_render_skill_catalog(skills, kept)) <= token_cap:
        return dict(skills), []

    priorities = {name: skill_priority(skills[name]) for name in names}
    # Drop order: highest priority NUMBER (lowest priority) first; ties broken
    # by descending name (the alphabetically later name is dropped first).
    drop_order = sorted(names, key=lambda n: (priorities[n], n), reverse=True)

    omitted: list[str] = []
    for victim in drop_order:
        if count(_render_skill_catalog(skills, kept)) <= token_cap:
            break
        kept.remove(victim)
        omitted.append(victim)

    return {name: skills[name] for name in kept}, omitted


def _read_skill_text(skill: Skill) -> str:
    """Read *skill*'s doc text, degrading to ``""`` on any read error.

    Never raises — mirrors the try/except-OSError degrade every other reader
    of a skill doc in this module already uses (an unreadable doc degrades to
    a name-only catalog entry / default priority, not a crash).
    """
    try:
        return skill.path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _render_skill_catalog(skills: dict[str, Skill], names: list[str]) -> str:
    """Render *names* (already in the desired order) as the compact name +
    one-line-summary catalog. Returns ``""`` for an empty *names* list (never
    a header-only catalog) — the shared rendering both :func:`compose_skills`
    and :func:`select_skills_within_budget`'s internal fit-check use, so the
    two can never drift apart.
    """
    if not names:
        return ""
    lines = ["Available skills (operator-authored capability docs):"]
    for name in names:
        summary = _first_summary_line(_read_skill_text(skills[name]))
        lines.append(f"- {name}: {summary}" if summary else f"- {name}")
    return "\n".join(lines)


def compose_skills(
    skills: dict[str, Skill],
    *,
    token_cap: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> str:
    """Render resolved skills as a compact name + one-line-summary catalog.

    Token-cheap: never inlines full bodies. Returns ``""`` when there are no
    skills. Skill docs are read here for their summary line; an unreadable doc
    degrades to a name-only entry rather than raising.

    ``token_cap`` (optional) caps the composed catalog. Resolution is
    explicit-parameter-wins; otherwise it falls back to
    :func:`resolve_skills_token_cap` (the ``COLLEAGUE_SKILLS_TOKEN_CAP``
    env var, legacy ``CONVERTIBLE_SKILLS_TOKEN_CAP`` fallback, default 0).
    A cap of ``0`` (or negative) is **uncapped** — byte-identical to a
    cap-unaware call (the honesty condition h4 floor: no explicit cap means
    no silent skill loss).

    When the composed catalog would exceed a positive cap,
    :func:`select_skills_within_budget` drops WHOLE skills, lowest-priority
    first, never truncating one mid-text, and one explicit note line is
    appended::

        omitted N skill(s) over the token cap: <name1>, <name2>

    ``count_tokens`` defaults to :func:`count_skill_tokens_chars` (the same
    zero-dependency char-heuristic as :func:`colleague.context.count_tokens_chars`,
    adapted for plain text) — pass a different callable to plug in an exact
    tokenizer.
    """
    if not skills:
        return ""
    cap = token_cap if token_cap is not None else resolve_skills_token_cap()
    kept, omitted = select_skills_within_budget(skills, cap, count_tokens=count_tokens)
    body = _render_skill_catalog(kept, sorted(kept))
    if not omitted:
        return body
    note = f"omitted {len(omitted)} skill(s) over the token cap: {', '.join(omitted)}"
    return f"{body}\n\n{note}" if body else note


# --- Task-local evaluator section (plan three-tier-execution, t5) ----------

#: The two seats an evaluator section can target — the same vocabulary the t4
#: lattice's ``Target.WORKER_PROMPT_EVALUATOR`` / ``Target.SENSES_PROMPT_EVALUATOR``
#: name (``"worker.prompt.evaluator"`` / ``"senses.prompt.evaluator"``).  This
#: module deliberately does not import :mod:`colleague.lattice` — the seat
#: vocabulary is duplicated as plain strings so ``layers.py`` stays a pure,
#: standalone composition module; :func:`compose_evaluator_section` validates
#: against this pair so a caller cannot pass an unrelated string (e.g. a raw
#: lattice target dotted-string, or ``"cortex"``, an *origin* not a *seat*).
EVALUATOR_SEAT_WORKER = "worker"
EVALUATOR_SEAT_SENSES = "senses"
_EVALUATOR_SEATS = (EVALUATOR_SEAT_WORKER, EVALUATOR_SEAT_SENSES)

#: Heading for the composed task-local evaluator section — the exact example
#: from the t5 design notes. Fixed regardless of *seat*: each seat gets its
#: own composed system prompt via its own separate system_prompt_for /
#: compose_role_prompt call (once for the worker's model, once for senses'),
#: so no single composed prompt ever needs to disambiguate between seats
#: internally — ``evaluator_seat`` exists purely to validate the caller's
#: intent, not to alter the rendered text.
EVALUATOR_SECTION_HEADING = "## Evaluator (task-local)"

#: Size cap (characters, post-strip) for an evaluator section's raw text.
#: Chosen as a generous-but-bounded budget for a task-local note — comparable
#: in order of magnitude to a single AGENTS overlay file, well inside typical
#: context budgets, yet small enough that a runaway or adversarial cortex
#: proposal cannot balloon the composed prompt. An oversize section is a
#: caller/producer error, not something to silently truncate: truncating could
#: cut an evaluator instruction mid-sentence and change its meaning in a way
#: nobody asked for. So composition REFUSES LOUDLY — it raises
#: :class:`EvaluatorSectionTooLarge` (a caller-must-handle error) rather than
#: emitting a clipped section or silently downgrading to ``None``.
EVALUATOR_SECTION_MAX_CHARS = 4000


class EvaluatorSectionTooLarge(ValueError):
    """Raised when an evaluator section's stripped text exceeds
    :data:`EVALUATOR_SECTION_MAX_CHARS`.

    A :class:`ValueError` subclass (so a caller that only catches
    ``ValueError`` still catches this) — never emitted as a truncated
    section, per :data:`EVALUATOR_SECTION_MAX_CHARS`'s docstring.
    """


def compose_evaluator_section(text: str | None, seat: str) -> str | None:
    """Render *text* as ONE named, bounded, task-local evaluator section.

    *seat* must be :data:`EVALUATOR_SEAT_WORKER` or
    :data:`EVALUATOR_SEAT_SENSES`; an unrecognized seat raises
    :class:`ValueError` unconditionally — even when *text* is empty — because
    a bad seat is always a caller bug, not a data-dependent condition.

    ``None`` or whitespace-only *text* renders **nothing** (returns ``None``)
    — the "absent renders nothing" floor: composing with no evaluator text
    is byte-identical to a call that never mentions the feature.

    A non-empty *text* longer than :data:`EVALUATOR_SECTION_MAX_CHARS`
    (after stripping) raises :class:`EvaluatorSectionTooLarge` — refused
    loudly, never silently truncated.

    Otherwise returns ``f"{EVALUATOR_SECTION_HEADING}\\n\\n{stripped text}"``.
    """
    if seat not in _EVALUATOR_SEATS:
        raise ValueError(f"unknown evaluator seat {seat!r}; expected one of {_EVALUATOR_SEATS}")
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if len(stripped) > EVALUATOR_SECTION_MAX_CHARS:
        raise EvaluatorSectionTooLarge(
            f"evaluator section for seat {seat!r} is {len(stripped)} chars, "
            f"exceeding the {EVALUATOR_SECTION_MAX_CHARS}-char cap "
            "(refused whole, never silently truncated)"
        )
    return f"{EVALUATOR_SECTION_HEADING}\n\n{stripped}"


# --- Composition ------------------------------------------------------------


def system_prompt_for(
    repo_path: str | Path,
    model: str,
    *,
    user_home: str | Path | None = None,
    base: str,
    skills_token_cap: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
    evaluator_section: str | None = None,
    evaluator_seat: str = EVALUATOR_SEAT_WORKER,
) -> str | None:
    """Compose the system prompt for *model*: ``base`` + AGENTS + evaluator + skills.

    Order is general -> specific: the engine's ``base`` default first, then the
    composed AGENTS layers, then the optional task-local evaluator section
    (see :func:`compose_evaluator_section`), then the skills catalog. Returns
    ``None`` when there are no AGENTS layers, no evaluator section, and no
    skills, so the caller keeps its own default and behavior is byte-identical
    to a layer-free run.

    ``skills_token_cap`` / ``count_tokens`` pass straight through to
    :func:`compose_skills` (see its docstring for cap resolution); omitting
    both is byte-identical to today.

    ``evaluator_section`` / ``evaluator_seat`` pass straight through to
    :func:`compose_evaluator_section`; omitting ``evaluator_section`` (or
    passing ``None``) is byte-identical to a call that predates this
    parameter — the ``evaluator_seat`` default is only ever consulted when
    ``evaluator_section`` is non-empty.
    """
    agents_text = compose_agents(resolve_agents(repo_path, model, user_home=user_home))
    skills_text = compose_skills(
        resolve_skills(repo_path, model, user_home=user_home),
        token_cap=skills_token_cap,
        count_tokens=count_tokens,
    )
    evaluator_text = compose_evaluator_section(evaluator_section, evaluator_seat)
    if not agents_text and not evaluator_text and not skills_text:
        return None
    return "\n\n".join(part for part in (base, agents_text, evaluator_text, skills_text) if part)


# --- Role-aware composition -------------------------------------------------


def _filter_skills(skills: dict[str, Skill], subset: tuple[str, ...] | None) -> dict[str, Skill]:
    """Filter *skills* to *subset*, where each entry is either an exact skill
    name or an :mod:`fnmatch`-style glob pattern (e.g. ``"cicd*"``).

    When *subset* is ``None``, all skills pass through (byte-identical to the
    unfiltered dict — the "no silent skill loss" invariant a curated role/mode
    must never breach). When *subset* is an empty tuple, no skills pass.

    Matching uses :func:`fnmatch.fnmatchcase` so behaviour does not vary by
    platform casing rules; a plain literal name (no wildcard characters) still
    matches only that exact skill, so this is a strict superset of the old
    exact-name-only semantics — every existing exact-name subset keeps
    matching exactly what it matched before. This is what lets a **built-in**
    role's curated subset (a single module-level constant shared by every repo
    colleague drives) stay repo-portable: it names a class of skills by
    pattern (e.g. ``"explore*"``) rather than hardcoding one repo's current
    skill filenames. A pattern that matches nothing in a given repo's catalog
    simply composes an empty skills section — never an error.
    """
    if subset is None:
        return skills
    return {
        name: skill
        for name, skill in skills.items()
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in subset)
    }


def compose_role_prompt(
    role: "Role | str",
    repo_path: str | Path,
    model: str,
    *,
    user_home: str | Path | None = None,
    base: str,
    skills_token_cap: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
    evaluator_section: str | None = None,
    evaluator_seat: str = EVALUATOR_SEAT_WORKER,
) -> str | None:
    """Compose the system prompt for *model* with an optional *role*.

    Reuses the existing prompt-assembly path (resolve_agents → compose_agents,
    resolve_skills → compose_skills).  The role's ``prompt_fragment`` composes
    after AGENTS layers, the optional task-local evaluator section (see
    :func:`compose_evaluator_section`) composes after that, and the role's
    ``skill_subset`` filters the skills catalog.  Composition order (fixed,
    documented)::

        base (engine default)
        AGENTS layers (general -> specific)
        role prompt_fragment (when non-empty)
        task-local evaluator section (when non-empty)
        skills catalog (filtered by role.skill_subset, then token-capped)

    Skills are filtered to the role's subset FIRST, then the (optional) token
    cap is applied to that already-filtered catalog — a role's curated subset
    and a token budget compose together, never independently.

    When *role* is a string, it is treated as a role name and resolved via
    :func:`colleague.roles.load_role`.  When *role* is a :class:`Role` instance,
    it is used directly.

    ``skills_token_cap`` / ``count_tokens`` pass straight through to
    :func:`compose_skills` (see its docstring for cap resolution); omitting
    both is byte-identical to today.

    ``evaluator_section`` / ``evaluator_seat`` pass straight through to
    :func:`compose_evaluator_section` (see its docstring — including the
    unknown-role fallback branch below, so every path threads the same two
    parameters); omitting ``evaluator_section`` (or passing ``None``) is
    byte-identical to a call that predates this parameter.

    Returns ``None`` when there is nothing to add beyond the engine's ``base``
    (no AGENTS layers, no skills, no evaluator section, and an empty role
    fragment), so behaviour is byte-identical to a layer-free run.
    """
    from colleague.roles import load_role as _load_role

    if isinstance(role, str):
        role = _load_role(role, repo_path, model)
        if role is None:
            # Unknown role name → fall back to no-role composition.
            return system_prompt_for(
                repo_path,
                model,
                user_home=user_home,
                base=base,
                skills_token_cap=skills_token_cap,
                count_tokens=count_tokens,
                evaluator_section=evaluator_section,
                evaluator_seat=evaluator_seat,
            )

    agents_text = compose_agents(resolve_agents(repo_path, model, user_home=user_home))
    all_skills = resolve_skills(repo_path, model, user_home=user_home)
    filtered = _filter_skills(all_skills, role.skill_subset)
    skills_text = compose_skills(filtered, token_cap=skills_token_cap, count_tokens=count_tokens)
    role_fragment = role.prompt_fragment
    evaluator_text = compose_evaluator_section(evaluator_section, evaluator_seat)

    parts = [base]
    if agents_text:
        parts.append(agents_text)
    if role_fragment:
        parts.append(role_fragment)
    if evaluator_text:
        parts.append(evaluator_text)
    if skills_text:
        parts.append(skills_text)

    # If only the base remains, return None (caller keeps its own default).
    if len(parts) == 1:
        return None
    return "\n\n".join(parts)

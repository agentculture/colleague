"""Deterministic self-knowledge classifier and guide index for colleague.

Decides whether a free-text operator message is a *self-knowledge* turn: a
question about colleague itself (its identity, architecture, gates, or
capabilities). Mirrors :mod:`colleague.frontdoor` in structure, docstring
style, and pattern-table approach. Stdlib ``re`` only — keeps the base install
dep-free.

Bright-line invariant
----------------------
Self-knowledge is the confidently interrogative complement of repo work.
Questions about colleague itself -> True; ambiguous input always defaults to
False; imperative verbs (fix, add, edit, write, implement, refactor) at the
start of the message guard against repo work masquerading as self-knowledge.

Classification rubric (evaluated in this order — repo-work signals win)
------------------------------------------------------------------------
1. Empty / whitespace-only text -> False.
2. Any imperative-work signal -> False. The complete, single enumerated list
   lives in :data:`_WORK_SIGNALS`: an edit/build/run verb at the start of the
   message (fix, edit, change, add, remove, delete, refactor, rename,
   implement, write, create, update, run, build, test, install, commit, push,
   merge, debug, deploy, generate).
3. Any repo-touching signal -> False. The complete, single enumerated list
   lives in :data:`_REPO_SIGNALS`: a file path or code extension; a git/shell
   command token; or an explicit mention of reading/writing/inspecting the
   repo, code, or files.
4. ``True`` only when a self-knowledge trigger matches. The complete, single
   enumerated list lives in :data:`_SELFKNOWLEDGE_TRIGGERS`: a question about
   colleague itself, its identity, architecture, capabilities, or internal
   mechanisms (what model are you, which model is this, how does the
   affected-tests gate work, how do you work, what gates are enabled, why is
   there no --no-hooks flag).
5. Otherwise (ambiguous) -> False, the safe default.
"""

from __future__ import annotations

import re
from pathlib import Path

# ── Imperative-work signals (start-of-message, case-insensitive) — guard
# against repo work masquerading as self-knowledge. ──

_WORK_SIGNALS: tuple[re.Pattern, ...] = (
    re.compile(
        r"^\s*(fix|edit|change|add|remove|delete|refactor|rename|implement"
        r"|write|create|update|run|build|test|install|commit|push|merge"
        r"|debug|deploy|generate)\b",
        re.I,
    ),
)

# ── Repo-touching signals (word-boundary, case-insensitive) — the ONE
# enumerated allow-list; ANY match here blocks self-knowledge. ──

_REPO_SIGNALS: tuple[re.Pattern, ...] = (
    # File path or code extension.
    re.compile(
        r"\.(py|md|rst|txt|json|ya?ml|toml|cfg|ini|sh|bash|js|ts|tsx|jsx"
        r"|html|css|rs|go|java|c|cpp|h|hpp|rb|php)\b",
        re.I,
    ),
    re.compile(r"\b[\w.-]+/[\w./-]+\b"),
    # Git/shell/command tokens.
    re.compile(
        r"\b(git|pytest|npm|uv|pip|make|grep|sed|cat|ls|bash|sh)\b",
        re.I,
    ),
    # Explicit read/write/inspect of repo/code/files.
    re.compile(r"\b(repo|repository|codebase|code|files?)\b", re.I),
)

# ── Self-knowledge triggers (word-boundary, case-insensitive) — the ONE
# enumerated allow-list; only consulted once no work or repo signal matched.
# ──

_SELFKNOWLEDGE_TRIGGERS: tuple[re.Pattern, ...] = (
    # Identity questions.
    re.compile(r"\bwhat\s+model\s+(are\s+you|is\s+(you|this))\b", re.I),
    re.compile(r"\bwhich\s+model\s+is\s+this\b", re.I),
    re.compile(r"\bwhat\s+are\s+you\b", re.I),
    re.compile(r"\bwho\s+are\s+you\b", re.I),
    # Architecture / mechanism questions.
    re.compile(r"\bhow\s+do\s+you\s+work\b", re.I),
    re.compile(r"\bhow\s+does\b.*\bgate\b.*\bwork\b", re.I),
    re.compile(r"\bwhat\s+gates?\s+are\s+enabled\b", re.I),
    re.compile(r"\bwhy\s+is\s+there\s+no\b", re.I),
    re.compile(r"\bwhat\s+can\s+you\s+do\b", re.I),
    re.compile(r"\bwhat\s+do\s+you\s+do\b", re.I),
    re.compile(r"\bwhat\s+is\s+cortex\b", re.I),
    re.compile(r"\bwhat\s+is\s+senses\b", re.I),
    re.compile(r"\bexplain\s+yourself\b", re.I),
    re.compile(r"\btell\s+me\s+about\s+yourself\b", re.I),
    re.compile(r"\bwhat\s+are\s+your\s+capabilities\b", re.I),
    # Gate-specific questions.
    re.compile(r"\bhow\s+does\b.*\bgate\b", re.I),
    re.compile(r"\bwhat\s+is\b.*\bgate\b", re.I),
)


def classify_selfknowledge(text: str) -> bool:
    """Return ``True`` only for a confidently self-knowledge turn.

    Pure (no I/O, no module state mutated), deterministic, case-insensitive.
    Empty/whitespace-only text, imperative-work signals, and any repo-touching
    signal always return ``False``; ``True`` fires only for a self-knowledge
    trigger; anything left over (ambiguous) also defaults to ``False``.
    """
    if not text or not text.strip():
        return False

    for signal in _WORK_SIGNALS:
        if signal.search(text):
            return False

    for signal in _REPO_SIGNALS:
        if signal.search(text):
            return False

    for trigger in _SELFKNOWLEDGE_TRIGGERS:
        if trigger.search(text):
            return True

    return False


def build_guide_index(repo_path: str | Path) -> list[str]:
    """Return repo-relative paths of colleague's own guide docs that *exist*.

    Scans exactly two locations under *repo_path*:

    1. ``CLAUDE.md`` at the repo root.
    2. Every ``.md`` file under ``docs/features/``.

    Returns a sorted list of repo-relative path strings (e.g. ``["CLAUDE.md",
    "docs/features/affected-tests.md", ...]``). Only files that actually exist
    are included — no dead references. A missing ``docs/`` directory is
    silently skipped (never raises). Pure pathlib, no globbing outside the two
    locations.
    """
    root = Path(repo_path)
    paths: list[str] = []

    claude = root / "CLAUDE.md"
    if claude.is_file():
        paths.append("CLAUDE.md")

    features = root / "docs" / "features"
    if features.is_dir():
        for md in sorted(features.iterdir()):
            if md.is_file() and md.suffix.lower() == ".md":
                rel = md.relative_to(root)
                paths.append(str(rel))

    return paths

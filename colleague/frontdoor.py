"""Deterministic front-door classifier for senses' presence-default loop.

Decides whether a free-text operator message should be routed straight to
``SENSES_DIRECT`` (senses answers on its own, no repo access) or dispatched to
``CORTEX`` (the loop that actually drives the repo). Stdlib ``re`` only —
keeps the base install dep-free.

Bright-line invariant
----------------------
Anything touching the repo -> CORTEX; senses-direct is the confidently
non-repo complement; ambiguous input always defaults to CORTEX (cortex is
never withheld from a real task).

Classification rubric (evaluated in this order — repo signals win)
--------------------------------------------------------------------
1. Empty / whitespace-only text -> CORTEX.
2. Any repo-touching signal -> CORTEX. The complete, single enumerated list
   lives in :data:`_REPO_SIGNALS`: a file path or code extension (``.py``,
   ``.md``, ``.json``, ``foo/bar.py``, ``loop.py``); an edit/build/run verb
   (fix, edit, change, add, remove, delete, refactor, rename, implement,
   write, create, update, run, build, test, install, commit, push, merge,
   debug, deploy, generate); a git/shell/command token (git, pytest, npm, uv,
   pip, make, grep, sed, cat, ls, bash, sh); or an explicit mention of
   reading/writing/inspecting the repo, code, or files.
3. ``SENSES_DIRECT`` only when confidently non-repo. The complete, single
   enumerated list lives in :data:`_SENSES_DIRECT_TRIGGERS`: a greeting or
   social nicety (hi, hey, hello, yo, thanks, thank you, good
   morning/evening, how are you, how's it going, bye, cheers); a question
   about colleague itself / its identity / architecture / capabilities (what
   are you, who are you, what model are you, how do you work, what can you
   do, what do you do, what is cortex, what is senses, explain yourself,
   tell me about yourself, what are your capabilities); or general non-repo
   conversation/advice naming no file, command, or repo action (what should
   I work on, what should we do next, explain how <concept> works).
4. Otherwise (ambiguous) -> CORTEX, the safe default.
"""

from __future__ import annotations

import re

#: Front-door routing constants returned by :func:`classify_frontdoor`.
SENSES_DIRECT = "senses_direct"
CORTEX = "cortex"

# ── Repo-touching signals (word-boundary, case-insensitive) — the ONE
# enumerated allow-list; ANY match here wins over a senses-direct trigger. ──

_REPO_SIGNALS: tuple[re.Pattern, ...] = (
    # File path or code extension: "loop.py", "foo/bar.py", "notes.md", ...
    re.compile(
        r"\.(py|md|rst|txt|json|ya?ml|toml|cfg|ini|sh|bash|js|ts|tsx|jsx"
        r"|html|css|rs|go|java|c|cpp|h|hpp|rb|php)\b",
        re.I,
    ),
    re.compile(r"\b[\w.-]+/[\w./-]+\b"),
    # Edit/build/run verbs.
    re.compile(
        r"\b(fix|edit|change|add|remove|delete|refactor|rename|implement"
        r"|write|create|update|run|build|test|install|commit|push|merge"
        r"|debug|deploy|generate)\b",
        re.I,
    ),
    # Git/shell/command tokens.
    re.compile(
        r"\b(git|pytest|npm|uv|pip|make|grep|sed|cat|ls|bash|sh)\b",
        re.I,
    ),
    # Explicit read/write/inspect of repo/code/files.
    re.compile(r"\b(repo|repository|codebase|code|files?)\b", re.I),
)

# ── Senses-direct triggers (word-boundary, case-insensitive) — the ONE
# enumerated allow-list; only consulted once no repo signal matched. ──

_SENSES_DIRECT_TRIGGERS: tuple[re.Pattern, ...] = (
    # Greeting / social.
    re.compile(r"^\s*(hi|hey|hello|yo)\b", re.I),
    re.compile(r"\bthanks\b", re.I),
    re.compile(r"\bthank\s+you\b", re.I),
    re.compile(r"\bgood\s+(morning|evening|afternoon)\b", re.I),
    re.compile(r"\bhow\s+are\s+you\b", re.I),
    re.compile(r"\bhow['’]s\s+it\s+going\b", re.I),
    re.compile(r"^\s*bye\b", re.I),
    re.compile(r"\bcheers\b", re.I),
    # Identity / architecture / capabilities questions.
    re.compile(r"\bwhat\s+are\s+you\b", re.I),
    re.compile(r"\bwho\s+are\s+you\b", re.I),
    re.compile(r"\bwhat\s+model\s+are\s+you\b", re.I),
    re.compile(r"\bhow\s+do\s+you\s+work\b", re.I),
    re.compile(r"\bwhat\s+can\s+you\s+do\b", re.I),
    re.compile(r"\bwhat\s+do\s+you\s+do\b", re.I),
    re.compile(r"\bwhat\s+is\s+cortex\b", re.I),
    re.compile(r"\bwhat\s+is\s+senses\b", re.I),
    re.compile(r"\bexplain\s+yourself\b", re.I),
    re.compile(r"\btell\s+me\s+about\s+yourself\b", re.I),
    re.compile(r"\bwhat\s+are\s+your\s+capabilities\b", re.I),
    # General non-repo conversation / advice.
    re.compile(r"\bwhat\s+should\s+(i|we)\s+work\s+on\b", re.I),
    re.compile(r"\bwhat\s+should\s+(i|we)\s+do\s+next\b", re.I),
    re.compile(r"\bexplain\s+how\b.*\bworks?\b", re.I),
)


def classify_frontdoor(text: str) -> str:
    """Return ``CORTEX`` or ``SENSES_DIRECT`` for *text*.

    Pure (no I/O, no module state mutated), deterministic, case-insensitive.
    Empty/whitespace-only text and any repo-touching signal always route to
    ``CORTEX``; ``SENSES_DIRECT`` fires only for a confidently non-repo
    trigger; anything left over (ambiguous) also defaults to ``CORTEX``.
    """
    if not text or not text.strip():
        return CORTEX

    for signal in _REPO_SIGNALS:
        if signal.search(text):
            return CORTEX

    for trigger in _SENSES_DIRECT_TRIGGERS:
        if trigger.search(text):
            return SENSES_DIRECT

    return CORTEX

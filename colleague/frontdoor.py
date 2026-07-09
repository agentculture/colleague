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

import json
import re
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from colleague.contract import SensesDirectRecord, SensesRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.config import EngineConfig

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


@dataclass(frozen=True)
class FrontDoorOutcome:
    """The unified decide-and-answer outcome of :func:`run_frontdoor`.

    Composes the deterministic :func:`classify_frontdoor` verdict with the
    senses-direct answer (:func:`colleague.senses.run_senses_frontdoor`, when
    consulted) into ONE result shape a front (the interactive session or the
    mesh resident) can act on without re-deriving any of this logic itself.

    Fields
    ------
    route:
        :data:`SENSES_DIRECT` or :data:`CORTEX` — the classifier's verdict.
    dispatch:
        ``True`` iff the front should still run the cortex work item. ``True``
        for every path except a clean senses-direct answer.
    answered_directly:
        ``True`` iff senses produced a real (non-degraded) answer and no
        dispatch should happen — the front can show ``answer`` and stop.
    answer:
        The senses-direct answer text, or the degraded-fallback text when
        senses could not answer. ``None`` on the unarmed/cortex paths (senses
        was never consulted).
    degraded:
        ``True`` iff a senses-direct attempt was made but fell back /
        degraded (the caller should dispatch to cortex despite the
        ``senses_direct`` route).
    record:
        A :class:`~colleague.contract.SensesRecord` for
        ``TaskResult.senses.records``, or ``None`` when senses was never
        consulted (the unarmed path).
    chat_entry:
        A ``{"kind": "talk", "message", "answer", "at"}`` dict for
        ``TaskResult.senses.chat`` — the existing "talk" chat-entry shape,
        no new vocabulary — set only on a clean senses-direct answer.
    """

    route: str
    dispatch: bool
    answered_directly: bool
    answer: Optional[str] = None
    degraded: bool = False
    record: Optional[SensesRecord] = None
    chat_entry: Optional[dict[str, Any]] = None


def cortex_frontdoor_outcome() -> "FrontDoorOutcome":
    """The FrontDoorOutcome for a deterministic CORTEX route: dispatch to cortex,
    no senses consult, recorded as ``senses-frontdoor:cortex``. Shared by
    :func:`run_frontdoor` and the session's classify-first short-circuit so the
    cortex route is recorded WITHOUT resolving the senses engine (and even when the
    engine can't load)."""
    from colleague.senses import FRONTDOOR_POINT

    return FrontDoorOutcome(
        route=CORTEX,
        dispatch=True,
        answered_directly=False,
        record=SensesRecord(point=f"{FRONTDOOR_POINT}:cortex"),
    )


def _persist_senses_direct(
    record_repo: "Optional[str | Path]", route: str, text: str, res: dict
) -> None:
    """Write a standalone, auditable record of a senses-direct turn (#311).

    A senses-direct turn produces NO Task/TaskResult (there is no work item), so
    without this it is unauditable from artifacts alone. Emits ONE
    ``.colleague/senses-direct/<id>.json`` :class:`SensesDirectRecord` with the
    operator's VERBATIM ``text`` — for BOTH a clean answer AND a degraded/misroute
    fallback, so an offline "were any non-repo turns misrouted?" audit works.
    Best-effort (suppressed) and a strict no-op when ``record_repo`` is None
    (unarmed / not-consulted paths never reach here), so observability never
    breaks the front door.
    """
    if record_repo is None:
        return
    with suppress(Exception):
        record = SensesDirectRecord(
            route=route,
            text=text,
            answer=str(res.get("answer", "")),
            latency=res.get("latency"),
            tokens=res.get("tokens"),
            degraded=bool(res.get("degraded")),
            at=time.time(),
        )
        out_dir = Path(record_repo) / ".colleague" / "senses-direct"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{uuid.uuid4().hex[:12]}.json").write_text(
            json.dumps(record.to_dict()), encoding="utf-8"
        )


def run_frontdoor(
    text: str,
    *,
    senses_config: "Optional[EngineConfig]",
    make_complete: "Callable[..., Callable[[list[dict[str, Any]]], Any]]",
    facts: Optional[str] = None,
    make_count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
    history: "Optional[list[dict[str, str]]]" = None,
    record_repo: "Optional[str | Path]" = None,
) -> FrontDoorOutcome:
    """The ONE shared front-agnostic front-door entry.

    Composes the deterministic :func:`classify_frontdoor` with the senses
    answer (:func:`colleague.senses.run_senses_frontdoor`) so BOTH the
    interactive session and the mesh resident can decide-and-answer through
    one call, instead of each re-implementing the classify → consult-senses →
    fall-back-to-cortex sequence.

    Never raises: :func:`~colleague.senses.run_senses_frontdoor` already
    degrades internally on any completion failure; this function just maps
    its result onto a :class:`FrontDoorOutcome`.

    Parameters
    ----------
    text:
        The operator's verbatim message.
    senses_config:
        The senses-pointed :class:`~colleague.config.EngineConfig`, or
        ``None`` when senses is unarmed. Unarmed is BYTE-IDENTICAL to
        pre-arc colleague: never classifies, never consults senses, never
        records — ``make_complete`` is never called.
    make_complete:
        The ``(config, tools=...) -> CompleteFn`` seam, forwarded verbatim to
        :func:`~colleague.senses.run_senses_frontdoor`.
    facts:
        The curated architecture/identity fact-set to ground a senses-direct
        answer in. Defaults to
        :func:`colleague.architecture_facts.load_architecture_facts` when
        omitted.
    make_count_tokens:
        Injectable token counter, forwarded verbatim.
    history:
        Optional rolling chat history, forwarded verbatim.

    Returns
    -------
    FrontDoorOutcome
        See the field docs above. ``route == CORTEX`` never consults senses
        (``make_complete`` is never called) — only ``route == SENSES_DIRECT``
        reaches the wire, and only when senses is armed.
    """
    if senses_config is None:
        # Unarmed: never classify, never consult senses, never record.
        return FrontDoorOutcome(route=CORTEX, dispatch=True, answered_directly=False, record=None)

    route = classify_frontdoor(text)

    if route == CORTEX:
        return cortex_frontdoor_outcome()

    # route == SENSES_DIRECT
    from colleague.architecture_facts import load_architecture_facts
    from colleague.senses import FRONTDOOR_POINT, run_senses_frontdoor

    res = run_senses_frontdoor(
        text,
        facts=facts if facts is not None else load_architecture_facts(),
        senses_config=senses_config,
        make_complete=make_complete,
        make_count_tokens=make_count_tokens,
        history=history,
    )
    if res is None:  # pragma: no cover - structurally unreachable
        # run_senses_frontdoor only returns None when senses_config is None,
        # and we already returned early above in that case.
        return FrontDoorOutcome(route=CORTEX, dispatch=True, answered_directly=False, record=None)

    rec = SensesRecord(
        point=f"{FRONTDOOR_POINT}:senses_direct",
        latency=res["latency"],
        tokens=res["tokens"],
        degraded=res["degraded"],
    )

    # #311: persist a standalone auditable record for EVERY senses-direct route —
    # a clean answer AND a degraded/misroute fallback — since a senses-direct turn
    # has no TaskResult. Strict no-op when record_repo is None.
    _persist_senses_direct(record_repo, SENSES_DIRECT, text, res)

    if res["degraded"]:
        # senses could not answer -> fall back to cortex.
        return FrontDoorOutcome(
            route=SENSES_DIRECT,
            dispatch=True,
            answered_directly=False,
            answer=res["answer"],
            degraded=True,
            record=rec,
            chat_entry=None,
        )

    return FrontDoorOutcome(
        route=SENSES_DIRECT,
        dispatch=False,
        answered_directly=True,
        answer=res["answer"],
        degraded=False,
        record=rec,
        chat_entry={
            "kind": "talk",
            "message": text,
            "answer": res["answer"],
            "at": time.time(),
        },
    )

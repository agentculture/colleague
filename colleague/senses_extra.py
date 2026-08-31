"""The narration + front-door senses lanes (split out of ``colleague/senses.py``,
fl-t6, hard-1000-line-file-limit, to keep that module under the 1000-line
ceiling).

:func:`run_senses_update` issues the proactive progress-narration turn
(task t3) and :func:`run_senses_frontdoor` issues the senses-direct
architecture/identity turn (talking-to-one-teammate arc, task t3) —
structural siblings of :func:`colleague.senses.run_senses_talk`, but neither
is source-text-pinned by name the way ``run_senses_talk`` is, so they moved
here rather than it. :func:`make_senses_run` — the loop's media-bridge
binder — moved alongside them since it shares no code with the talk lane
either.

Every name here is re-exported from :mod:`colleague.senses` so callers see no
difference from before the split. To avoid a module-import cycle (this module
needs :func:`colleague.senses.senses_engine_config` /
:func:`colleague.senses.run_senses_media_bridge`, and ``colleague.senses``
imports THIS module for the re-export), those two names are imported lazily,
inside :func:`make_senses_run`'s nested ``bound`` closure — by the time
``bound`` actually runs, :mod:`colleague.senses` has finished importing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from colleague.agents.talker import recording_complete as _talker_recorded
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import ContextPacket, SensesRecord
from colleague.plan.cli_driver import _extract_json_object, robust_simple_complete
from colleague.senses_common import (
    _BACKGROUND_LABEL,
    _FIDELITY_CLAUSE,
    _GROUNDING_CLAUSE,
    _TRUNCATION_NOTE,
    _fold_history,
    _TokenMeter,
    _window_text,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.engine import Engine

#: Fixed invocation-point labels recorded on each :class:`SensesRecord`
#: (mirrors the labels defined alongside the other lanes in
#: :mod:`colleague.senses`).
MEDIA_BRIDGE_POINT = "media-bridge"
UPDATE_POINT = "senses-update"
FRONTDOOR_POINT = "senses-frontdoor"

_UPDATE_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — narrating progress to the operator "
    "WHILE the cortex model drives a running work item. Read the recent flight-feed "
    "lines below and narrate in 1–2 first-person sentences what the run is doing "
    "RIGHT NOW. Quote or paraphrase real feed lines; if the feed shows nothing new, "
    "say exactly that. NEVER invent progress, files, or results not present in the "
    'feed. Reply with ONLY a JSON object of the form: {"update": "..."}. '
    "No prose outside the JSON. " + _GROUNDING_CLAUSE + " " + _FIDELITY_CLAUSE
)


_FRONTDOOR_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the front door the operator talks "
    "to first. Answer the operator's greeting or question about colleague "
    'itself directly, conversationally, and in the FIRST person ("I" / '
    '"colleague"), using ONLY the architecture facts given below and the '
    "operator's own words. Do NOT invent, guess, or assume any architecture or "
    "identity detail that is not stated in those facts — if the facts don't "
    "say, say PLAINLY that you don't know and that cortex can check, rather "
    "than fabricating an answer. This is a front-door answer only: you do not "
    "act, read, or write anything — cortex does the repo work. Reply with ONLY "
    'a JSON object of the form: {"answer": "..."}. No prose outside the JSON. '
    + _GROUNDING_CLAUSE
    + " "
    + _FIDELITY_CLAUSE
)


def run_senses_update(
    feed_tail: list[str],
    packet: Optional[ContextPacket],
    senses_config: Optional[EngineConfig],
    engine: "Engine",
    *,
    count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
    history: "Optional[list[dict[str, str]]]" = None,
) -> Optional[dict[str, Any]]:
    """Issue ONE proactive progress narration (task t3).

    The structural sibling of :func:`colleague.senses.run_senses_talk` for
    *proactive* progress narration — the "talking to colleague feels like
    talking to one person" arc. Issues exactly ONE tools-off completion,
    windowed to senses' OWN context budget via
    :func:`colleague.senses_common._window_text`, and returns an advisory
    ``{update, latency, tokens, degraded}`` record.

    Grounded: the system prompt instructs senses to narrate in 1–2 first-person
    sentences what the run is doing RIGHT NOW, derived ONLY from the given feed
    lines — quote or paraphrase real lines; if the feed shows nothing new, say
    exactly that; NEVER invent progress, files, or results not present in the
    feed. The same grounding contract as ``colleague.senses._TALK_SYSTEM_PROMPT``.

    Returns ``None`` when *senses_config* or *engine* is unusable (``None`` or
    missing). Otherwise NEVER raises: any failure (unreachable endpoint, request
    error, empty content) degrades to a record with ``update=None`` and
    ``degraded=True``.

    Parameters
    ----------
    feed_tail:
        Recent flight-feed lines (most recent last).
    packet:
        The run's :class:`~colleague.contract.ContextPacket`, or ``None``.
    senses_config:
        The senses-pointed :class:`EngineConfig`, or ``None`` (unarmed).
    engine:
        The :class:`~colleague.engine.Engine` instance.
    count_tokens:
        Injectable token counter; defaults to
        ``engine.make_count_tokens(senses_config)``.
    history:
        Optional rolling chat history (talking-to-one arc, task t4) — folded
        into the user prompt BEFORE the feed section, windowed the same way
        as :func:`colleague.senses.run_senses_intake`'s ``history``;
        ``None``/``[]`` is byte-identical to before this parameter existed.

    Returns
    -------
    dict | None
        ``None`` when unarmed. Otherwise
        ``{"update": str | None, "latency": float, "tokens": int | None,
        "degraded": bool}``.
    """
    if senses_config is None or engine is None:
        return None

    start = time.monotonic()
    meter = _TokenMeter()
    try:
        counter = (
            count_tokens if count_tokens is not None else engine.make_count_tokens(senses_config)
        )
        feed_text = "\n".join(feed_tail) if feed_tail else ""
        # Ground the narration in what the run is ABOUT (the intake packet's
        # interpretation) so a status line names the goal, not just raw feed —
        # the packet augments the feed, it never substitutes for it. This
        # ``about`` line is UNBOUNDED (a model-authored interpretation can run
        # long), so it must be windowed together with the feed below — never
        # windowed alone, and never appended after windowing.
        about = ""
        if packet is not None and packet.interpretation:
            about = f"The running work item is about: {packet.interpretation}\n\n"
        user_prompt = (
            f"{about}Recent flight feed (most recent last):\n{feed_text or '(no feed yet)'}"
        )
        # Window the WHOLE assembled prompt (about + header + feed) BEFORE
        # folding history: ``_fold_history`` only ever drops history entries,
        # it never trims ``primary_body`` (see its docstring) — so the primary
        # body must already fit the send budget on its own, or an unbounded
        # ``about`` line could push the assembled prompt over budget.
        user_prompt = _window_text(
            user_prompt,
            system_prompt=_UPDATE_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        user_prompt = _fold_history(
            user_prompt,
            history,
            system_prompt=_UPDATE_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        # Tools-off ALWAYS: an explicit empty tool list, never ``None``.
        complete = engine.make_complete(senses_config, tools=[])
        complete = _talker_recorded(
            complete, senses_config, engine=engine, truncation_marker=_TRUNCATION_NOTE
        )
        simple = robust_simple_complete(meter.wrap(complete))
        raw = simple(_UPDATE_SYSTEM_PROMPT, user_prompt)
        if not raw.strip():
            raise ValueError("empty senses update response")
        data = _extract_json_object(raw, required_key="update")
        update_text = str(data.get("update", "")).strip()
        latency = time.monotonic() - start
        return {
            "update": update_text if update_text else None,
            "latency": latency,
            "tokens": meter.value,
            "degraded": False,
        }
    except Exception:
        latency = time.monotonic() - start
        return {
            "update": None,
            "latency": latency,
            "tokens": None,
            "degraded": True,
        }


#: The bound senses media-bridge callable the loop threads through
#: :class:`~colleague.loop.ContextControls`. Signature:
#: ``(question: str, media_parts: list[dict]) -> (description | None, SensesRecord)``.
#: Built once per work item by :func:`make_senses_run`; never raises.
SensesRun = Callable[..., "tuple[Optional[str], SensesRecord]"]


def make_senses_run(config: EngineConfig, engine_name: str) -> "Optional[SensesRun]":
    """Bind :func:`colleague.senses.run_senses_media_bridge` to *config* +
    *engine_name* for the loop.

    Returns ``None`` when no senses config is present (``config.senses`` is
    ``None``) — the signal the loop keys off to leave the senses media bridge
    dormant (byte-identical). The returned callable loads the engine + builds the
    senses-pointed :class:`EngineConfig` on each call (mirroring
    :func:`colleague.deepthink.make_deepthink_run`), and never raises: an unknown
    engine name or a missing senses config degrades to ``(None, degraded record)``.
    """
    if config.senses is None:
        return None

    def bound(
        question: str,
        media_parts: "list[dict[str, Any]]",
    ) -> "tuple[Optional[str], SensesRecord]":
        start = time.monotonic()
        try:
            # Lazy import: colleague.senses imports THIS module for its
            # re-export, so a module-level import here would cycle.
            from colleague import registry
            from colleague.senses import run_senses_media_bridge, senses_engine_config

            senses_config = senses_engine_config(config)
            if senses_config is None:  # pragma: no cover - guarded by the None check above
                raise RuntimeError("no senses config resolved")
            engine = registry.load(engine_name)
            return run_senses_media_bridge(question, media_parts, senses_config, engine)
        except Exception:
            latency = time.monotonic() - start
            return None, SensesRecord(
                point=MEDIA_BRIDGE_POINT, latency=latency, tokens=None, degraded=True
            )

    return bound


def run_senses_frontdoor(
    text: str,
    *,
    facts: str,
    senses_config: Optional[EngineConfig],
    make_complete: "Callable[..., Callable[[list[dict[str, Any]]], Any]]",
    make_count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
    history: "Optional[list[dict[str, str]]]" = None,
) -> Optional[dict[str, Any]]:
    """Answer ONE senses-direct turn — a greeting or question about colleague
    itself — WITHOUT waking cortex (talking-to-one-teammate arc, task t3).

    The structural sibling of :func:`colleague.senses.run_senses_talk` for a
    front-door turn that never touches a running work item: no flight feed,
    no task state, no relay judgment — just the operator's words grounded
    against a caller-supplied curated fact-set
    (:func:`colleague.architecture_facts.load_architecture_facts`, though any
    string works — this function does not import or depend on that module).
    Issues exactly ONE tools-off completion against the senses model.

    Tools-off ALWAYS: *make_complete* is invoked as
    ``make_complete(senses_config, tools=[])`` — an explicit empty tool list,
    never ``None`` — mirroring ``colleague.senses.run_senses_talk``.
    *make_complete* is passed in directly (not a full engine), the same shape
    as ``run_senses_talk``.

    Grounded: the user prompt carries *facts* + *text* verbatim (never
    trimmed independently — the whole assembled body is windowed together),
    windowed to *senses_config*'s OWN ``context_budget_tokens`` via
    :func:`colleague.senses_common._window_text`, counted via
    *make_count_tokens* when given, else the zero-dep
    :func:`~colleague.context.count_tokens_chars` fallback (there is no engine
    object here to fall back to its own counter — the same
    ``make_count_tokens if make_count_tokens is not None else
    count_tokens_chars`` convention as ``run_senses_talk``).
    :data:`_FRONTDOOR_SYSTEM_PROMPT` instructs senses to answer ONLY from the
    given facts + the operator's words and to say plainly that it doesn't
    know (deferring to cortex) rather than invent an architecture/identity
    detail not present in *facts*.

    Conversation continuity: an optional *history* (a list of
    ``{"role": "operator"|"senses", "text": "..."}`` entries, oldest first)
    is folded into the user prompt via
    :func:`colleague.senses_common._fold_history` the same way as every
    other senses invocation function; ``None``/``[]`` is byte-identical
    to omitting it.

    Returns ``None`` when *senses_config* is ``None`` (senses unarmed) — the
    signal the caller uses to fall back to waking cortex directly. Otherwise
    NEVER raises: any failure (unreachable endpoint, request error, overflow,
    empty or unrecoverable content, an empty ``answer`` field) degrades to a
    record with ``degraded=True`` and a safe, non-fabricated ``answer``.

    Parameters
    ----------
    text:
        The operator's verbatim message (a greeting or a question about
        colleague itself).
    facts:
        The curated architecture/identity fact-set to ground the answer in
        (typically :func:`colleague.architecture_facts.load_architecture_facts`).
    senses_config:
        The senses-pointed :class:`EngineConfig`, or ``None`` (unarmed).
    make_complete:
        The ``(config, tools=...) -> CompleteFn`` seam, bound once per turn by
        the caller (mirrors ``run_senses_talk``).
    make_count_tokens:
        Injectable token counter; defaults to
        :func:`~colleague.context.count_tokens_chars`.
    history:
        Optional rolling chat history, folded in before the facts+message
        body via :func:`colleague.senses_common._fold_history`;
        ``None``/``[]`` is a strict no-op.

    Returns
    -------
    dict | None
        ``None`` when unarmed. Otherwise
        ``{"answer": str, "latency": float, "degraded": bool,
        "tokens": int | None}`` — a plain advisory dict (NOT a
        :class:`~colleague.contract.SensesRecord`; a caller wraps this into
        one, tagged :data:`FRONTDOOR_POINT`, for the artifact). ``tokens`` is
        the exact summed prompt+completion tokens on success, ``None`` on
        degradation (never estimated).
    """
    if senses_config is None:
        return None

    start = time.monotonic()
    meter = _TokenMeter()
    try:
        counter = make_count_tokens if make_count_tokens is not None else count_tokens_chars
        primary_body = (
            f"{_BACKGROUND_LABEL} architecture facts.\n{facts}\n\n"
            f"Operator's message (answer this; the facts above are background, "
            f"never a substitute for answering it): {text}"
        )
        user_prompt = _window_text(
            primary_body,
            system_prompt=_FRONTDOOR_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        user_prompt = _fold_history(
            user_prompt,
            history,
            system_prompt=_FRONTDOOR_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        # Tools-off ALWAYS: an explicit empty tool list, never ``None`` — a
        # front-door answer structurally cannot carry a tool schema on the wire.
        complete = make_complete(senses_config, tools=[])
        complete = _talker_recorded(complete, senses_config, truncation_marker=_TRUNCATION_NOTE)
        simple = robust_simple_complete(meter.wrap(complete))
        raw = simple(_FRONTDOOR_SYSTEM_PROMPT, user_prompt)
        if not raw.strip():
            raise ValueError("empty senses frontdoor response")
        data = _extract_json_object(raw, required_key="answer")
        answer = str(data.get("answer", "")).strip()
        if not answer:
            raise ValueError("empty senses frontdoor answer")
        latency = time.monotonic() - start
        return {
            "answer": answer,
            "latency": latency,
            "degraded": False,
            "tokens": meter.value,
        }
    except Exception:
        latency = time.monotonic() - start
        return {
            "answer": "senses can't answer that right now — cortex can.",
            "latency": latency,
            "degraded": True,
            "tokens": None,
        }

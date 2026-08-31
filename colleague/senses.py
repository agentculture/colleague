"""The cortex/senses "senses" invocation layer (cortex/senses arc, task t5).

Colleague drives with two lobes: a wide-window **cortex** model that drives the
tool loop, and a tools-off **senses** front door that reads the operator's
*verbatim* request before the loop and shapes the cortex's raw summary back into
a conversational reply after it. This module is the ONE place that turns a piece
of operator/cortex text into a bounded, tools-off completion against the senses
model — the structural sibling of :func:`colleague.deepthink.run_deepthink`:

- :func:`senses_engine_config` builds the :class:`~colleague.config.EngineConfig`
  a senses call should run against (``None`` when no senses config is declared) —
  the exact twin of :func:`colleague.deepthink.deepthink_engine_config`. It NEVER
  inherits the parent config's ``on_delta`` (plan task t2) — a senses call streams
  only when the caller explicitly arms ``senses_engine_config(config, on_delta=...)``,
  typically with :func:`make_senses_display_delta`, which decodes a streamed
  JSON-move envelope into display text incrementally via
  :class:`~colleague.senses_stream.EnvelopeStream`.
- :func:`run_senses_intake` perceives the operator's request into a structured
  :class:`~colleague.contract.ContextPacket`. The packet's ``original`` field is
  set to the caller's input **verbatim** — never from the model output — so the
  operator's exact request survives byte-for-byte (the arc's core invariant).
  The SAME completion also carries a senses-authored ``ack`` line onto
  ``packet.ack`` (talking-to-one arc, task t1) — zero extra calls, zero extra
  latency; a degraded intake carries no ack (the packet is ``None``).
- :func:`run_senses_speakback` shapes the cortex's raw work summary into a
  conversational display string.
- :func:`run_senses_talk` holds ONE live, tools-off conversational turn with
  the operator WHILE cortex is driving a work item (senses live presence,
  task t4) — grounded in the live flight-feed tail + the run's
  :class:`~colleague.contract.ContextPacket` + a caller-supplied task-state
  snapshot, windowed to senses' own budget, and returns an advisory
  ``{answer, relay, relay_text, latency, degraded, tokens}`` record. An
  explicit operator ``"cortex: ..."`` prefix is a DETERMINISTIC relay
  override that always wins over the model's own (advisory) relay judgment.
  Wiring this into the flight plane / `colleague talk` / the session lane is
  later tasks (t5-t7); this function is the invocation layer only.

Both invocations issue exactly ONE tools-off completion via the public
:meth:`colleague.engine.Engine.make_complete` seam with ``tools=[]`` (a senses
request structurally cannot carry a tool schema on the wire), window their prompt
to the senses model's OWN context budget first via
:meth:`colleague.engine.Engine.make_count_tokens`, and NEVER raise — any failure
(a dead port, a request error, an overflow, empty/unrecoverable content, bad or
lossy JSON) degrades to ``None`` plus a degraded
:class:`~colleague.contract.SensesRecord`, so intake can never lose the request
(the caller passes the raw text through) and speakback falls back to the raw
summary.

The JSON recovery for the served non-tool-calling model family reuses the SOLVED
path — :func:`colleague.plan.cli_driver.robust_simple_complete` (empty-content /
reasoning-channel / degradation-retry recovery) and ``_extract_json_object``
(prose-wrapped / truncated JSON) — rather than re-deriving a parser here.

Wiring this into the loop / the operator-facing surfaces is task t6 (a later
wave); this module is the invocation layer only.

Conversation continuity (talking-to-one arc, task t4): all four invocation
functions above (:func:`run_senses_intake`, :func:`run_senses_speakback`,
:func:`run_senses_talk`, :func:`run_senses_update`) accept an optional
keyword-only ``history`` — a rolling list of ``{"role": "operator"|"senses",
"text": "..."}`` entries (the session-side record of prior exchanges: ack,
updates, talk, clarify). When present and non-empty, :func:`_fold_history`
folds it into the USER message as an "Optional background" block (task t2's
:data:`_BACKGROUND_LABEL`; oldest first), positioned BEFORE the function's own
existing payload (the request / feed tail / summary) so the model reads prior
exchanges before the current turn, labeled plainly as background rather than
authoritative for it. The block participates in the same
:func:`_window_text`-style budget accounting: when the combined prompt would
exceed the senses model's own ``context_budget_tokens``, the OLDEST history
entries are dropped first (whole entries, never sliced) until it fits — the
function's own payload always wins, since it already fits the send budget
alone before history is folded in. ``history=None``/``[]`` (or an entry
:func:`_history_lines` defensively skips — an unrecognized role, missing/blank
text) is a strict no-op: the prompt is byte-identical to the pre-t4 shape.
This is orthogonal to the verbatim-original invariant above — history only
ever touches the *prompt sent to the model*, never ``ContextPacket.original``.

Structural senses relay fidelity (three-tier-execution arc, task t2): every
prompt-bearing surface in this module (and the senses coordination loop,
:mod:`colleague.senses_loop`) composes two clauses into its system prompt —
the grounding clause (:data:`_GROUNDING_CLAUSE`, "you can see only the status
block you are given") and the fidelity clause (:data:`_FIDELITY_CLAUSE`,
"answer the current message from the current result first; background
knowledge never replaces it") — but prompt wording alone is hope, not a
guarantee. :func:`run_senses_talk`'s optional ``worker_answer`` parameter
carries the acting mind's ("today cortex's; the seat name is never
hard-coded") current result for the current message, and
:func:`_enforce_fidelity` enforces STRUCTURALLY, in code, that the text
finally displayed to the operator CONTAINS it verbatim — falling back to the
raw ``worker_answer`` and recording a degradation when it does not. The same
guarantee is enforced in :mod:`colleague.senses_loop` for the coordination
loop's ``reply_to_operator`` move. Four additive counters
(``verbatim_presence``, ``knowledge_repetition``, ``fallback``, ``truncated``)
land on the :class:`~colleague.contract.SensesRecord` surface.

Talker identity (#411, task t16): when model-bound agents are ARMED
(``config.agents`` + the loop-set ``config.agents_ledger_path``), every
tools-off completion issued here is wrapped by
:func:`colleague.agents.talker.recording_complete`, which appends ONE
``invocation`` event (purpose ``talker``, model_role ``senses``, the digest of
the EMPTY tool surface) to the task ledger before calling through — identity
only, never a tool, never an authority; a failing ledger never breaks the
senses call. Unarmed, the wrapper is the identity and every call site is
byte-identical (``tools=[]`` stays on the wire at each one).
"""

from __future__ import annotations

import dataclasses
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional, cast

from colleague import media
from colleague.agents.talker import recording_complete as _talker_recorded
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import ContextPacket, SensesRecord
from colleague.plan.cli_driver import _extract_json_object, robust_simple_complete
from colleague.senses_common import (
    _FIDELITY_CLAUSE,
    _GROUNDING_CLAUSE,
    _TRUNCATION_NOTE,
    _coerce_ack,
    _coerce_confidence,
    _coerce_omissions,
    _fold_history,
    _TokenMeter,
    _window_text,
)

# Re-exported for backward compatibility: colleague/resident/appserver.py,
# colleague/frontdoor.py, colleague/engines/vllm_openai.py, and
# colleague/engines/mock.py all import these names from colleague.senses
# (not colleague.senses_extra, where they are now defined) — moving them
# there without a re-export here would break those call sites.
from colleague.senses_extra import (  # noqa: F401
    _FRONTDOOR_SYSTEM_PROMPT,
    _UPDATE_SYSTEM_PROMPT,
    FRONTDOOR_POINT,
    UPDATE_POINT,
    SensesRun,
    make_senses_run,
    run_senses_frontdoor,
    run_senses_update,
)
from colleague.senses_stream import EnvelopeStream

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.engine import Engine

# NOTE: _TRUNCATION_NOTE / _GROUNDING_CLAUSE / _FIDELITY_CLAUSE and the
# windowing/history/token-metering/coercion plumbing (_window_text,
# _fold_history, _TokenMeter, _coerce_confidence, _coerce_omissions,
# _coerce_ack) now live in colleague/senses_common.py (fl-t6,
# hard-1000-line-file-limit) — imported above and used directly below, which
# ALSO re-exports them from this module's namespace (colleague/senses_loop.py
# still does ``from colleague.senses import _TRUNCATION_NOTE, ...`` and keeps
# working unchanged). run_senses_talk stays HERE: source-read by
# tests/test_senses_live_presence_proofs.py for its FunctionDef by name.

#: Per-surface display-streaming envelope keys (d4/#374, ssv task t3). Senses
#: reply envelopes are key-inconsistent across surfaces: the coordination
#: loop's moves carry ``"text"`` (:class:`~colleague.senses_stream.
#: EnvelopeStream`'s default), while :func:`run_senses_frontdoor` and
#: :func:`run_senses_talk` both reply ``{"answer": ...}`` (each parses with
#: ``required_key="answer"`` below), and :func:`run_senses_speakback` replies
#: are BARE PROSE — no envelope at all, so a speak-back caller arms a raw
#: pass-through ``on_delta`` (the raw deltas ARE the display text), never the
#: extractor. These constants bind each surface's STREAMING field to the SAME
#: key its parser requires, in this one module, so the two can never drift —
#: arming the wrong key would never raise, it would just silently never
#: stream (the extractor withholds everything and fails only at ``finish()``).
FRONTDOOR_STREAM_FIELD = "answer"
TALK_STREAM_FIELD = "answer"

#: Fixed invocation-point labels recorded on each :class:`SensesRecord`.
#: UPDATE_POINT / FRONTDOOR_POINT are defined in colleague/senses_extra.py
#: (imported above for re-export) alongside the lanes that use them.
INTAKE_POINT = "senses-intake"
SPEAKBACK_POINT = "senses-speakback"
MEDIA_BRIDGE_POINT = "media-bridge"
TALK_POINT = "senses-talk"

_INTAKE_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the perception front door. Read the "
    "operator's request below and perceive what it means BEFORE the cortex model "
    "acts on it. Reply with ONLY a JSON object of the form: "
    '{"interpretation": "...", "confidence": 0.0, "task_type": "...", '
    '"omissions": ["..."], "ack": "..."}. '
    '"interpretation" is a normalized restatement of what the operator wants; '
    '"confidence" is your confidence in that reading as a number from 0.0 to 1.0; '
    '"task_type" is a short classification (e.g. bugfix, feature, docs, refactor, '
    'question); "omissions" lists, one short string each, what the request left '
    'implicit or unspecified; "ack" is a short, one- or two-sentence, '
    "first-person acknowledgment — in your own words — of what you understood "
    'and that you are handing the work to cortex now. "ack" may ONLY restate '
    'what "interpretation"/"task_type"/"omissions" above already say: no new '
    "claim, no promise about the outcome, nothing the rest of this reply doesn't "
    "already assert. Do NOT echo the original request text back. No prose "
    "outside the JSON. " + _GROUNDING_CLAUSE + " " + _FIDELITY_CLAUSE
)

_SPEAKBACK_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the voice that speaks back to the "
    "operator. Rewrite the cortex model's raw work summary below into a clear, "
    "concise, conversational reply for a human. Preserve every concrete fact "
    "(files changed, decisions, caveats); do not invent anything that is not in "
    "the summary. Reply with ONLY the reply text — no JSON, no preamble. "
    + _GROUNDING_CLAUSE
    + " "
    + _FIDELITY_CLAUSE
)

_TALK_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — a live conversational presence "
    "answering the operator WHILE the cortex model drives a running work item. "
    "Answer the operator's live message using ONLY the run context given in the "
    "user message below (the operator's original request, the current task "
    "state, and the recent flight-feed tail). If the context does not say, say "
    "plainly that you don't know rather than invent or guess run state. Reply "
    "with ONLY a JSON object of the form: "
    '{"answer": "...", "relay": true|false, "relay_text": "..."}. '
    '"answer" is what you say back to the operator; "relay" is true when this '
    "message should be forwarded to the cortex model as guidance for the "
    'running work item, false otherwise; "relay_text" is the exact text to '
    "inject into cortex when relay is true (default to the operator's own "
    "message). No prose outside the JSON. " + _GROUNDING_CLAUSE + " " + _FIDELITY_CLAUSE
)

# _UPDATE_SYSTEM_PROMPT / _FRONTDOOR_SYSTEM_PROMPT moved to
# colleague/senses_extra.py alongside run_senses_update / run_senses_frontdoor.


def senses_engine_config(
    config: EngineConfig, *, on_delta: Optional[Callable[[str], None]] = None
) -> Optional[EngineConfig]:
    """Build the :class:`EngineConfig` a senses call should run against.

    Returns ``None`` when *config* carries no senses declaration
    (``config.senses is None`` — the model IS the presence signal, exactly like
    deepthink). Otherwise returns a ``dataclasses.replace`` of *config* with
    ``model``/``base_url``/``api_key`` switched to the senses target and
    ``context_budget_tokens`` set to the senses model's OWN budget
    (``senses.context_budget``) — so a senses call is windowed against its own
    budget, never the main model's. Every other knob (``max_steps``,
    ``timeout``, ``max_output_chars``, …) inherits unchanged.

    This is the exact twin of
    :func:`colleague.deepthink.deepthink_engine_config`; the loop-wiring task
    (t6) calls it once to build the config it hands to the run functions below.

    ``on_delta`` streaming (plan task t2): the returned config's ``on_delta``
    is ALWAYS *on_delta* as given — ``None`` by default — NEVER *config*'s own
    ``on_delta``. Before this parameter existed, ``dataclasses.replace`` copied
    every field it didn't explicitly override, so a senses call silently
    inherited whatever delta sink the PARENT (cortex) completion happened to
    be armed with; that sink expects the cortex model's raw prose, not a
    senses reply, and a session surface arming cortex streaming had no way to
    say "not this one" for senses. A caller that wants the senses call ITSELF
    to stream now arms it explicitly by passing its own ``on_delta`` — see
    :func:`make_senses_display_delta` for the adapter that turns a raw
    per-chunk callback into one that decodes and forwards a JSON-move
    envelope's display text incrementally (:mod:`colleague.senses_stream`).
    Arming here is what makes the engine's EXISTING streamed-vs-blocking
    decision (``colleague.engines.vllm_openai._make_complete``: streaming iff
    ``config.on_delta is not None``) take the streamed path for this call —
    no engine code changes needed.
    """
    sc = config.senses
    if sc is None:
        return None
    # cast: dataclasses.replace()'s generic signature infers DataclassInstance,
    # not EngineConfig specifically (SonarCloud S5886); mirrors
    # colleague.deepthink.deepthink_engine_config's identical cast.
    seat = cast(
        EngineConfig,
        dataclasses.replace(
            config,
            model=sc.model,
            refresh_seat=None,
            base_url=sc.base_url,
            api_key=sc.api_key,
            context_budget_tokens=sc.context_budget,
            on_delta=on_delta,
        ),
    )
    # Talker records (#411 t16): the armed loop hands the task-ledger path to
    # the parent config as ``agents_ledger_path``; ``dataclasses.replace``
    # copies declared fields only, so a runtime-set attribute is carried over
    # here explicitly (a no-op when it is a declared field or absent).
    ledger_path = getattr(config, "agents_ledger_path", None)
    if ledger_path is not None and getattr(seat, "agents_ledger_path", None) is None:
        seat.agents_ledger_path = ledger_path  # type: ignore[attr-defined]
    # Per-seat thinking effort (#416 t4): the senses seat carries its own
    # table rung (off default) via the plain ``reasoning_effort_seat``
    # attribute that ``vllm_openai._effort_for`` honors ahead of the acting
    # seat's resolved rung.
    from colleague import effort

    setattr(
        seat,
        "reasoning_effort_seat",
        effort.resolve_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=config.reasoning_effort_seats.get("senses"),
            seat="senses",
        ),
    )
    return seat


def make_senses_display_delta(
    on_display_delta: Callable[[str], None], *, field: str = "text"
) -> Callable[[str], None]:
    """Build a raw ``on_delta`` callback that decodes a senses completion's
    streamed JSON-move envelope incrementally, forwarding display text to
    *on_display_delta* as it is decoded (plan task t2).

    The returned callable is meant to be armed as ``EngineConfig.on_delta``
    (via :func:`senses_engine_config`'s ``on_delta`` parameter) — the engine
    then feeds it the model's RAW per-chunk text as the completion streams
    (``colleague.engines.vllm_openai._make_complete``'s existing streamed
    path; unchanged by this task). Each raw chunk is fed through ONE
    :class:`~colleague.senses_stream.EnvelopeStream`, extracting the
    envelope's ``"text"`` field value incrementally — fence markers, braces,
    keys, and the closing quote/brace/fence are withheld, exactly as
    :class:`EnvelopeStream` documents.

    State (the ``EnvelopeStream`` instance) is carried in the closure across
    calls, since ``on_delta`` fires once per RAW chunk over the life of a
    SINGLE completion — build a FRESH adapter per completion (per
    :func:`senses_engine_config` call), never share one across turns.

    Never raises into the engine's read loop — the ``on_delta`` contract
    ``colleague.engines.vllm_openai._emit_delta`` already relies on.
    ``EnvelopeStream.feed`` itself never raises (see its own docstring);
    once the stream is judged hopeless (``.failed`` — e.g. a malformed reply,
    or a plain-text reply with no JSON envelope at all, such as
    :func:`run_senses_speakback`'s), forwarding simply STOPS for the rest of
    that completion. The caller's own fallback to a whole-reply render (a
    later task) decides what to show instead — this adapter's only job is to
    decode-and-forward or go quiet, never to raise and never to guess at
    content it never validated.

    *on_display_delta* itself may raise (a rendering sink) — swallowed here,
    mirroring ``_emit_delta``'s "a raising sink must never break the run"
    convention.
    """
    stream = EnvelopeStream(field=field)

    def on_delta(chunk: str) -> None:
        if stream.failed:
            return
        piece = stream.feed(chunk)
        if not piece:
            return
        with suppress(Exception):
            on_display_delta(piece)

    return on_delta


def run_senses_intake(
    text: str,
    senses_config: EngineConfig,
    engine: "Engine",
    *,
    point: str = INTAKE_POINT,
    count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
    history: "Optional[list[dict[str, str]]]" = None,
) -> "tuple[Optional[ContextPacket], SensesRecord]":
    """Perceive the operator's *text* into a structured :class:`ContextPacket`.

    Issues exactly ONE tools-off completion against the senses model, windowed
    to the senses model's own budget, and parses a structured
    ``{interpretation, confidence, task_type, omissions, ack}`` JSON reply via
    the solved recovery path (:func:`robust_simple_complete` +
    ``_extract_json_object``).

    The returned packet's ``original`` is set to *text* **VERBATIM** — the model
    supplies only the derived interpretation/confidence/task_type/omissions; the
    operator's exact request never comes from the model output. That invariant is
    the whole point of the senses front door.

    The reply's ``ack`` field — a short, senses-authored acknowledgment of what
    it understood and that it is handing the work to cortex — rides this SAME
    completion onto ``packet.ack`` (talking-to-one arc, task t1; the spec's
    ack-shape decision: zero extra calls, zero extra latency). ``_coerce_ack``
    strips and hard-caps it; a missing, empty, or non-string ``ack`` leaves
    ``packet.ack`` at its default ``None`` — never fabricated. This module never
    synthesizes a substitute ack on degradation: a degraded intake returns
    ``(None, ...)``, so there is structurally no ack anywhere; a caller-side
    fixed dispatch notice for that case belongs to a LATER task, not here.

    Never raises. On ANY failure — an unreachable endpoint, a request error, an
    overflow, empty content that cannot be recovered, or bad/lossy JSON — returns
    ``(None, degraded SensesRecord)`` so the caller passes the RAW *text* through
    untouched. Intake must never lose the request.

    Parameters
    ----------
    text:
        The operator's verbatim request. Preserved on ``packet.original``.
    senses_config:
        The :class:`EngineConfig` pointed at the senses endpoint and windowed to
        the senses budget — build it once with :func:`senses_engine_config`.
    engine:
        The :class:`~colleague.engine.Engine` instance to run the completion
        through (``engine.make_complete`` / ``engine.make_count_tokens``).
    point:
        The invocation-point label recorded on the :class:`SensesRecord`
        (default :data:`INTAKE_POINT`).
    count_tokens:
        Injectable token counter; defaults to
        ``engine.make_count_tokens(senses_config)`` (the engine's own exact-or-
        estimate counter). Tests inject a fake to avoid any real network call.
    history:
        Optional rolling chat history (talking-to-one arc, task t4) — a list
        of ``{"role": "operator"|"senses", "text": "..."}`` entries, oldest
        first. Folded into the user prompt BEFORE *text*, windowed to
        *senses_config*'s own budget (oldest entries dropped first when it
        doesn't fit); ``None``/``[]`` is byte-identical to before this
        parameter existed. Never affects ``packet.original``.

    Returns
    -------
    (ContextPacket | None, SensesRecord)
        On success: the parsed packet (``original`` = *text* verbatim) and a
        clean record (``degraded=False``, exact summed ``tokens``, measured
        ``latency``). On any degradation: ``(None, record)`` with
        ``degraded=True``, ``tokens=None``, and ``latency`` measured up to the
        failure (always >= 0).
    """
    start = time.monotonic()
    meter = _TokenMeter()
    try:
        counter = (
            count_tokens if count_tokens is not None else engine.make_count_tokens(senses_config)
        )
        user_prompt = _window_text(
            text,
            system_prompt=_INTAKE_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        user_prompt = _fold_history(
            user_prompt,
            history,
            system_prompt=_INTAKE_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        # Tools-off ALWAYS: an explicit empty tool list, never ``None`` — a senses
        # request structurally cannot carry a tool schema on the wire.
        complete = engine.make_complete(senses_config, tools=[])
        complete = _talker_recorded(
            complete, senses_config, engine=engine, truncation_marker=_TRUNCATION_NOTE
        )
        simple = robust_simple_complete(meter.wrap(complete))
        raw = simple(_INTAKE_SYSTEM_PROMPT, user_prompt)
        if not raw.strip():
            # Empty content that even the reasoning-channel recovery could not
            # rescue — treat as a lossy no-op (degrade, don't fabricate a packet).
            raise ValueError("empty senses intake response")
        data = _extract_json_object(raw)  # raises ValueError on no/lossy JSON
        packet = ContextPacket(
            original=text,  # VERBATIM — never from the model output.
            interpretation=str(data.get("interpretation", "")),
            confidence=_coerce_confidence(data.get("confidence")),
            task_type=str(data.get("task_type", "")),
            omissions=_coerce_omissions(data.get("omissions")),
            # The ack rides this SAME completion — zero extra calls, zero extra
            # latency (talking-to-one arc, task t1, the spec's ack-shape
            # decision). A missing/non-string/empty value degrades to ``None``,
            # never fabricated; there is no separate ack turn to retry.
            ack=_coerce_ack(data.get("ack")),
        )
        latency = time.monotonic() - start
        return packet, SensesRecord(
            point=point,
            latency=latency,
            tokens=meter.value,
            degraded=False,
        )
    except Exception:
        latency = time.monotonic() - start
        return None, SensesRecord(point=point, latency=latency, tokens=None, degraded=True)


def run_senses_speakback(
    summary: str,
    senses_config: EngineConfig,
    engine: "Engine",
    *,
    point: str = SPEAKBACK_POINT,
    count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
    history: "Optional[list[dict[str, str]]]" = None,
) -> "tuple[Optional[str], SensesRecord]":
    """Shape the cortex's raw *summary* into a conversational display string.

    Issues exactly ONE tools-off completion against the senses model, windowed to
    the senses model's own budget, and returns the model's reply text. Never
    raises. On ANY failure (unreachable endpoint, request error, overflow, or
    empty/unrecoverable content) returns ``(None, degraded SensesRecord)`` so the
    caller falls back to the raw *summary*.

    Parameters mirror :func:`run_senses_intake`, including the optional
    ``history`` (talking-to-one arc, task t4) folded before *summary* and
    windowed the same way. Returns ``(display_text | None,
    SensesRecord)``: on success the display string and a clean record; on
    degradation ``None`` plus a degraded record (``tokens=None``, ``latency``
    measured up to the failure).
    """
    start = time.monotonic()
    meter = _TokenMeter()
    try:
        counter = (
            count_tokens if count_tokens is not None else engine.make_count_tokens(senses_config)
        )
        user_prompt = _window_text(
            summary,
            system_prompt=_SPEAKBACK_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        user_prompt = _fold_history(
            user_prompt,
            history,
            system_prompt=_SPEAKBACK_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        complete = engine.make_complete(senses_config, tools=[])  # tools-off ALWAYS
        complete = _talker_recorded(
            complete, senses_config, engine=engine, truncation_marker=_TRUNCATION_NOTE
        )
        simple = robust_simple_complete(meter.wrap(complete))
        display = simple(_SPEAKBACK_SYSTEM_PROMPT, user_prompt)
        if not display.strip():
            raise ValueError("empty senses speakback response")
        latency = time.monotonic() - start
        return display, SensesRecord(
            point=point,
            latency=latency,
            tokens=meter.value,
            degraded=False,
        )
    except Exception:
        latency = time.monotonic() - start
        return None, SensesRecord(point=point, latency=latency, tokens=None, degraded=True)


def run_senses_media_bridge(
    question: str,
    media_parts: "list[dict[str, Any]]",
    senses_config: EngineConfig,
    engine: "Engine",
    *,
    point: str = MEDIA_BRIDGE_POINT,
    count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
) -> "tuple[Optional[str], SensesRecord]":
    """Describe attached media through the multimodal senses model (cortex/senses, t6).

    The senses-lobe twin of :func:`colleague.deepthink.run_media_bridge`: the
    operator declared the senses model multimodal, so the REAL media parts ride
    ONE tools-off completion to the senses endpoint — and only that endpoint; the
    text-only cortex wire never sees them (the loop flattens its copy). The
    *question* text is windowed to the senses budget minus a per-part media
    reserve, then the parts ride ONE appended user message.

    Never raises (the :func:`run_senses_intake` contract): any failure —
    unreachable endpoint, request error, overflow, empty content, or no media —
    returns ``(None, degraded SensesRecord)`` so the loop falls back to the
    (now text-only) cortex turn. On success returns ``(description, clean
    record)`` with the exact summed tokens + measured latency.
    """
    start = time.monotonic()
    if not media_parts:
        return None, SensesRecord(
            point=point, latency=time.monotonic() - start, tokens=None, degraded=True
        )
    meter = _TokenMeter()
    try:
        counter = (
            count_tokens if count_tokens is not None else engine.make_count_tokens(senses_config)
        )
        # Reserve budget for the media parts themselves so windowed text + parts
        # still fit the senses window (the deepthink.run_media_bridge currency).
        reserve = media.IMAGE_TOKEN_ESTIMATE * len(media_parts)
        text_budget = max(1, senses_config.context_budget_tokens - reserve)
        user_prompt = _window_text(
            question,
            system_prompt="",
            budget=text_budget,
            count_tokens=counter,
        )
        # Tools-off ALWAYS: an explicit empty tool list — a senses completion
        # structurally cannot carry a tool schema on the wire.
        complete = engine.make_complete(senses_config, tools=[])
        complete = meter.wrap(
            _talker_recorded(
                complete, senses_config, engine=engine, truncation_marker=_TRUNCATION_NOTE
            )
        )
        response = complete(
            [
                {"role": "user", "content": user_prompt},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "The attached media:"}]
                    + list(media_parts),
                },
            ]
        )
        text = getattr(response, "content", "") or ""
        if not text.strip():
            raise ValueError("empty senses media-bridge response")
        latency = time.monotonic() - start
        return text, SensesRecord(point=point, latency=latency, tokens=meter.value, degraded=False)
    except Exception:
        latency = time.monotonic() - start
        return None, SensesRecord(point=point, latency=latency, tokens=None, degraded=True)


def _relay_prefix_override(message: str, relay_prefix: str) -> Optional[str]:
    """Return the stripped relay text when *message* starts with *relay_prefix*.

    Returns ``None`` when the prefix is absent — the caller then falls back to
    the model's own (advisory) relay judgment. When present, this is the
    GUARANTEED relay path (senses live-presence spec, decision h3): an operator
    who deliberately types e.g. ``"cortex: focus on the config file"`` gets
    ``relay=True`` unconditionally, even if the senses model itself judges
    otherwise or is unreachable — the prefix is a deterministic operator
    convention, not a classification the model can override.
    """
    if not relay_prefix or not message.startswith(relay_prefix):
        return None
    return message[len(relay_prefix) :].strip()


def _format_talk_context(
    message: str,
    packet: Optional[ContextPacket],
    task_state: Any,
    worker_answer: Optional[str] = None,
) -> str:
    """Build the FIXED (never-windowed) portion of a talk-lane prompt.

    Carries the operator's original request + prior interpretation (from
    *packet*, when present), the caller-supplied *task_state* snapshot, the
    acting mind's *worker_answer* (its current result for *message*, when
    given — task t2), and the live *message* itself — everything the talk
    turn needs EXCEPT the flight feed tail, which :func:`run_senses_talk`
    windows separately so a long-running conversation's feed history never
    crowds out the message being asked right now. *worker_answer* is CURRENT
    content, not background — it stays here, never in the folded-history
    "optional background" block :func:`_fold_history` builds.
    """
    lines: list[str] = []
    if packet is not None:
        original = getattr(packet, "original", "") or ""
        interpretation = getattr(packet, "interpretation", "") or ""
        if original:
            lines.append(f"Operator's original request: {original}")
        if interpretation:
            lines.append(f"Senses' prior interpretation: {interpretation}")
    if task_state:
        lines.append(f"Current task state: {task_state}")
    if worker_answer:
        lines.append(
            "Current result from the acting mind (answer the message from "
            f"this first): {worker_answer}"
        )
    lines.append(f"Operator's live message: {message}")
    return "\n".join(lines)


#: Minimum length (characters) a background/knowledge snippet must reach
#: before a verbatim match against it counts as "unrelated-knowledge
#: repetition" (task t2) — a short common phrase (e.g. "ok") would
#: false-positive on coincidence; a real recited fact/history block is
#: comfortably longer than this floor.
_KNOWLEDGE_REPEAT_FLOOR = 20


def _repeats_background(text: str, snippets: "Iterable[Any]") -> bool:
    """True when *text* verbatim-reproduces a meaningful chunk of *snippets*.

    The structural signature of the fidelity failure this arc guards against
    (task t2): senses reciting its background/"knowledge" content (rolling
    history entries, curated facts) instead of relaying the current answer.
    Any snippet at least :data:`_KNOWLEDGE_REPEAT_FLOOR` characters long found
    verbatim inside *text* counts as a repetition; shorter or non-string
    snippets are skipped defensively. Never raises: a falsy *text* or an
    empty *snippets* iterable returns ``False``.
    """
    body = (text or "").strip()
    if not body:
        return False
    for snippet in snippets:
        if not isinstance(snippet, str):
            continue
        candidate = snippet.strip()
        if len(candidate) >= _KNOWLEDGE_REPEAT_FLOOR and candidate in body:
            return True
    return False


def _enforce_fidelity(
    answer: str,
    worker_answer: Optional[str],
    knowledge_snippets: "Iterable[Any]",
) -> "tuple[str, bool, bool, bool]":
    """Structural containment (task t2): when *worker_answer* is given, the
    text about to be displayed to the operator must CONTAIN it verbatim —
    enforced HERE in code, never left to the prompt alone (the two composed
    clauses, :data:`_GROUNDING_CLAUSE`/:data:`_FIDELITY_CLAUSE`, are prompt
    hygiene; this function is the actual guarantee).

    Returns ``(final_text, verbatim_presence, knowledge_repetition,
    fallback)``:

    - No *worker_answer* (``None``/blank after stripping) — *answer* passes
      through completely unchanged, all three flags ``False`` (nothing to
      check; the byte-identical no-op path).
    - *answer* already contains *worker_answer* verbatim — passes through
      unchanged, ``verbatim_presence=True``, the other two flags ``False``.
    - *answer* does NOT contain it — a fidelity failure: *final_text* becomes
      *worker_answer* itself (trivially verbatim, the raw-answer fallback),
      ``fallback=True``. When *answer* itself verbatim-reproduces a chunk of
      *knowledge_snippets* (:func:`_repeats_background`) instead of the
      current result, ``knowledge_repetition=True`` too — the "recited its
      knowledge block instead of the answer" failure shape a real embodiment
      live session exhibited.
    """
    worker = (worker_answer or "").strip()
    if not worker:
        return answer, False, False, False
    if worker in (answer or ""):
        return answer, True, False, False
    repetition = _repeats_background(answer, knowledge_snippets)
    return worker, False, repetition, True


def _apply_worker_answer_fidelity(
    result: dict[str, Any],
    answer: str,
    worker_answer: Optional[str],
    history: "Optional[list[dict[str, str]]]",
    truncated_prompt: bool,
) -> None:
    """Fold the structural fidelity check (task t2) onto *result* in place.

    A strict no-op when *worker_answer* is blank/``None`` — byte-identical to
    before this parameter existed. Otherwise checks (in code, via
    :func:`_enforce_fidelity`) that the displayed answer CONTAINS
    *worker_answer* verbatim, folds the four fidelity counters onto *result*,
    and — on a fidelity failure — additionally flips ``result["degraded"]``
    True (task t2, AC2), even though the completion itself succeeded.
    Extracted from :func:`run_senses_talk` to keep it under the SonarCloud
    S3776 ceiling (mirrors how the module already extracts
    :func:`_enforce_fidelity` / :func:`_format_talk_context` / etc.).
    """
    if not worker_answer:
        return
    knowledge_snippets = [entry.get("text") for entry in (history or []) if isinstance(entry, dict)]
    final_answer, verbatim_presence, knowledge_repetition, fallback = _enforce_fidelity(
        answer, worker_answer, knowledge_snippets
    )
    result["answer"] = final_answer
    result["verbatim_presence"] = verbatim_presence
    result["knowledge_repetition"] = knowledge_repetition
    result["fallback"] = fallback
    result["truncated"] = truncated_prompt
    if fallback:
        # A fidelity failure IS a degradation, even though the
        # completion itself succeeded (task t2, AC2).
        result["degraded"] = True


def run_senses_talk(
    message: str,
    *,
    feed_tail: str,
    packet: Optional[ContextPacket],
    task_state: Any,
    senses_config: Optional[EngineConfig],
    make_complete: "Callable[..., Callable[[list[dict[str, Any]]], Any]]",
    make_count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
    relay_prefix: str = "cortex:",
    history: "Optional[list[dict[str, str]]]" = None,
    worker_answer: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Hold ONE live, tools-off conversational turn with the operator (t4).

    The senses live-presence lane: while cortex drives a running work item,
    the operator can chat with senses concurrently. This issues exactly ONE
    tools-off completion grounded in the live run context — *feed_tail* (the
    recent flight-feed lines), *packet* (the run's
    :class:`~colleague.contract.ContextPacket`, or ``None``), and *task_state*
    (a short caller-supplied snapshot: step/phase/last tool, or ``None``) — and
    returns an advisory record the caller (the flight-attach verb / the
    session's concurrent lane) uses to display an answer and, optionally,
    inject guidance into the running cortex loop at the next tool-call
    boundary.

    Tools-off ALWAYS: *make_complete* is invoked as ``make_complete(senses_config,
    tools=[])`` — an explicit empty tool list, never ``None`` — mirroring
    :func:`run_senses_intake` / :func:`run_senses_speakback` /
    :func:`run_senses_media_bridge`. Unlike those, *make_complete* is passed in
    directly (not a full engine) so a flight-attach caller that already
    resolved ``engine.make_complete`` can bind it once per turn.

    Grounded: the fixed run context (packet + task_state + the message itself)
    is never trimmed; only *feed_tail* — the part that grows unbounded over a
    long-running conversation — is windowed to *senses_config*'s OWN
    ``context_budget_tokens`` (mirroring :func:`_window_text`'s use elsewhere),
    counted via *make_count_tokens* when given, else the zero-dep
    :func:`~colleague.context.count_tokens_chars` fallback (there is no engine
    object here to fall back to its own counter). The system prompt instructs
    senses to answer ONLY from the given context and to say it doesn't know
    rather than fabricate run state.

    Relay: the model's own JSON reply carries an advisory ``relay``/
    ``relay_text`` judgment. An explicit ``relay_prefix`` (default
    ``"cortex:"``) on *message* ALWAYS overrides it — see
    :func:`_relay_prefix_override` — regardless of the model's judgment AND
    regardless of whether the completion itself succeeds (the override is
    computed up front and applied on both the clean and the degraded return
    path, so the guaranteed relay path survives a dead senses endpoint too).

    Conversation continuity: an optional *history* (talking-to-one arc, task
    t4 — a list of ``{"role": "operator"|"senses", "text": "..."}`` entries,
    oldest first) is folded into the user prompt BEFORE the fixed run
    context + feed, windowed to *senses_config*'s own budget (oldest entries
    dropped first when it doesn't fit; the fixed context + feed always win).
    ``None``/``[]`` is byte-identical to before this parameter existed.

    Structural relay fidelity (task t2): an optional *worker_answer* —  the
    acting mind's ("today cortex's; the seat name is never hard-coded")
    current result for *message*, when the caller has one — is folded into
    the FIXED context (never trimmed, never treated as background) and,
    after the completion returns, the displayed ``answer`` is checked in
    CODE (:func:`_enforce_fidelity`) to CONTAIN *worker_answer* verbatim.
    When it does not — a fidelity failure — the raw *worker_answer* is
    presented instead (a guaranteed-verbatim fallback) and ``degraded`` is
    set ``True``, even though the completion itself may have succeeded.
    ``worker_answer=None`` (the default) is byte-identical to before this
    parameter existed: no fidelity keys are added to the returned dict at
    all.

    Returns ``None`` when *senses_config* is ``None`` (senses unarmed) — the
    signal the caller uses to degrade to a watch-only view, no talk lane.
    Otherwise NEVER raises: any failure (unreachable endpoint, request error,
    overflow, empty or unrecoverable content) degrades to a record with
    ``degraded=True`` and a safe, non-fabricated ``answer``.

    Returns
    -------
    dict | None
        ``None`` when unarmed. Otherwise
        ``{"answer": str, "relay": bool, "relay_text": str, "latency": float,
        "degraded": bool, "tokens": int | None}`` — a plain advisory dict (NOT
        a :class:`~colleague.contract.SensesRecord`; the caller wraps this into
        one, tagged :data:`TALK_POINT`, for the artifact). ``tokens`` is the
        exact summed prompt+completion tokens on success, ``None`` on
        degradation (never estimated). When *worker_answer* is given
        (non-blank), the dict ADDITIONALLY carries ``verbatim_presence``,
        ``knowledge_repetition``, ``fallback``, and ``truncated`` (all
        ``bool``) — the four structural fidelity counters (task t2).
    """
    if senses_config is None:
        return None

    start = time.monotonic()
    relay_override = _relay_prefix_override(message, relay_prefix)
    meter = _TokenMeter()
    try:
        counter = make_count_tokens if make_count_tokens is not None else count_tokens_chars
        fixed_context = _format_talk_context(message, packet, task_state, worker_answer)
        windowed_feed = _window_text(
            feed_tail or "",
            system_prompt=f"{_TALK_SYSTEM_PROMPT}\n\n{fixed_context}",
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        truncated_prompt = _TRUNCATION_NOTE in windowed_feed
        user_prompt = (
            f"{fixed_context}\n\nRecent flight feed (most recent last):\n"
            f"{windowed_feed or '(no feed yet)'}"
        )
        user_prompt = _fold_history(
            user_prompt,
            history,
            system_prompt=_TALK_SYSTEM_PROMPT,
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
        # Tools-off ALWAYS: an explicit empty tool list, never ``None`` — a
        # senses talk turn structurally cannot carry a tool schema on the wire.
        complete = make_complete(senses_config, tools=[])
        complete = _talker_recorded(complete, senses_config, truncation_marker=_TRUNCATION_NOTE)
        simple = robust_simple_complete(meter.wrap(complete))
        raw = simple(_TALK_SYSTEM_PROMPT, user_prompt)
        if not raw.strip():
            raise ValueError("empty senses talk response")
        data = _extract_json_object(raw, required_key="answer")
        answer = str(data.get("answer", "")).strip()
        if not answer:
            raise ValueError("empty senses talk answer")
        model_relay = bool(data.get("relay", False))
        model_relay_text = str(data.get("relay_text") or message)
        relay = relay_override is not None or model_relay
        relay_text = relay_override if relay_override is not None else model_relay_text
        latency = time.monotonic() - start
        result: dict[str, Any] = {
            "answer": answer,
            "relay": relay,
            "relay_text": relay_text,
            "latency": latency,
            "degraded": False,
            "tokens": meter.value,
        }
        _apply_worker_answer_fidelity(result, answer, worker_answer, history, truncated_prompt)
        return result
    except Exception:
        latency = time.monotonic() - start
        relay = relay_override is not None
        relay_text = relay_override if relay_override is not None else message
        return {
            "answer": "senses is unavailable right now.",
            "relay": relay,
            "relay_text": relay_text,
            "latency": latency,
            "degraded": True,
            "tokens": None,
        }


# run_senses_update / SensesRun / make_senses_run / run_senses_frontdoor moved
# to colleague/senses_extra.py (fl-t6, hard-1000-line-file-limit) and are
# imported near the top of this module for re-export.

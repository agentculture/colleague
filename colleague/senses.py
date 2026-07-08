"""The cortex/senses "senses" invocation layer (cortex/senses arc, task t5).

Colleague drives with two lobes: a wide-window **cortex** model that drives the
tool loop, and a tools-off **senses** front door that reads the operator's
*verbatim* request before the loop and shapes the cortex's raw summary back into
a conversational reply after it. This module is the ONE place that turns a piece
of operator/cortex text into a bounded, tools-off completion against the senses
model — the structural sibling of :func:`colleague.deepthink.run_deepthink`:

- :func:`senses_engine_config` builds the :class:`~colleague.config.EngineConfig`
  a senses call should run against (``None`` when no senses config is declared) —
  the exact twin of :func:`colleague.deepthink.deepthink_engine_config`.
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
folds it into the USER message as a "Conversation so far" block (oldest
first), positioned BEFORE the function's own existing payload (the request /
feed tail / summary) so the model reads prior exchanges before the current
turn. The block participates in the same :func:`_window_text`-style budget
accounting: when the combined prompt would exceed the senses model's own
``context_budget_tokens``, the OLDEST history entries are dropped first
(whole entries, never sliced) until it fits — the function's own payload
always wins, since it already fits the send budget alone before history is
folded in. ``history=None``/``[]`` (or an entry :func:`_history_lines`
defensively skips — an unrecognized role, missing/blank text) is a strict
no-op: the prompt is byte-identical to the pre-t4 shape. This is orthogonal to
the verbatim-original invariant above — history only ever touches the
*prompt sent to the model*, never ``ContextPacket.original``.
"""

from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

from colleague import media, registry
from colleague.config import EngineConfig
from colleague.context import count_tokens_chars
from colleague.contract import ContextPacket, SensesRecord
from colleague.plan.cli_driver import _extract_json_object, robust_simple_complete

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.engine import Engine

#: Appended to a prompt truncated to fit the senses model's send budget — a
#: visible marker so whoever reads the digest knows content was cut (mirrors
#: :data:`colleague.deepthink._TRUNCATION_NOTE`). Only the prompt SENT to the
#: senses model is ever truncated; ``ContextPacket.original`` always carries the
#: caller's full verbatim input regardless.
_TRUNCATION_NOTE = "[senses digest truncated to fit budget]"

#: Fixed invocation-point labels recorded on each :class:`SensesRecord`.
INTAKE_POINT = "senses-intake"
SPEAKBACK_POINT = "senses-speakback"
MEDIA_BRIDGE_POINT = "media-bridge"
TALK_POINT = "senses-talk"
UPDATE_POINT = "senses-update"
FRONTDOOR_POINT = "senses-frontdoor"

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
    "outside the JSON."
)

_SPEAKBACK_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the voice that speaks back to the "
    "operator. Rewrite the cortex model's raw work summary below into a clear, "
    "concise, conversational reply for a human. Preserve every concrete fact "
    "(files changed, decisions, caveats); do not invent anything that is not in "
    "the summary. Reply with ONLY the reply text — no JSON, no preamble."
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
    "message). No prose outside the JSON."
)

_UPDATE_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — narrating progress to the operator "
    "WHILE the cortex model drives a running work item. Read the recent flight-feed "
    "lines below and narrate in 1–2 first-person sentences what the run is doing "
    "RIGHT NOW. Quote or paraphrase real feed lines; if the feed shows nothing new, "
    "say exactly that. NEVER invent progress, files, or results not present in the "
    'feed. Reply with ONLY a JSON object of the form: {"update": "..."}. '
    "No prose outside the JSON."
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
    'a JSON object of the form: {"answer": "..."}. No prose outside the JSON.'
)


def senses_engine_config(config: EngineConfig) -> Optional[EngineConfig]:
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
    """
    sc = config.senses
    if sc is None:
        return None
    # cast: dataclasses.replace()'s generic signature infers DataclassInstance,
    # not EngineConfig specifically (SonarCloud S5886); mirrors
    # colleague.deepthink.deepthink_engine_config's identical cast.
    return cast(
        EngineConfig,
        dataclasses.replace(
            config,
            model=sc.model,
            base_url=sc.base_url,
            api_key=sc.api_key,
            context_budget_tokens=sc.context_budget,
        ),
    )


def _coerce_confidence(value: Any) -> float:
    """Best-effort float coercion for the model's ``confidence`` (default 0.0).

    Mirrors :meth:`ContextPacket.from_dict`'s handling — a value that cannot be
    parsed as ``float`` (e.g. the model wrote ``"high"``) degrades to ``0.0``
    rather than raising, since a bad confidence is advisory, not fatal.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_omissions(value: Any) -> list[str]:
    """Coerce the model's ``omissions`` into a list of short strings.

    A list/tuple becomes ``[str(x) for x in value]``; a bare string becomes a
    single-element list; anything else (``None``, a number, a dict) becomes
    ``[]`` — tolerant of model hallucination, never a crash.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return []


#: Hard cap on ``ContextPacket.ack`` length (talking-to-one arc, task t1). A
#: one/two-sentence acknowledgment never needs more; an over-long reply is
#: hard-truncated in place — never a second completion, never invented filler.
_MAX_ACK_LEN = 500


def _coerce_ack(value: Any) -> Optional[str]:
    """Best-effort extraction of the model's ``ack`` field (task t1).

    A non-empty string is stripped of surrounding whitespace and hard-capped to
    :data:`_MAX_ACK_LEN` characters. Anything else — missing, ``None``, an
    empty/whitespace-only string, or a non-string value (a number, list, dict)
    from a hallucinating model — degrades to ``None``: a reply with no usable
    ack is simply absent, never fabricated.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:_MAX_ACK_LEN]


def _window_text(
    text: str,
    *,
    system_prompt: str,
    budget: int,
    count_tokens: "Callable[[list[dict[str, Any]]], int]",
) -> str:
    """Return *text* truncated so ``[system, user=text]`` fits the send budget.

    Mirrors :func:`colleague.deepthink.window_messages`' arithmetic: reserve one
    quarter of *budget* for the completion, so the prompt must measure at or
    under ``budget - budget // 4``. A prompt that already fits passes through
    byte-identical. Otherwise the user text is binary-searched down (bounded
    number of ``count_tokens`` calls) with :data:`_TRUNCATION_NOTE` appended so
    the cut is always visible. The senses model's OWN counter/budget are used
    (the caller passes ``engine.make_count_tokens(senses_config)`` and
    ``senses_config.context_budget_tokens``).
    """
    reserve = max(1, budget // 4)
    send_budget = max(1, budget - reserve)

    def _messages(body: str) -> "list[dict[str, Any]]":
        msgs: "list[dict[str, Any]]" = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": body})
        return msgs

    if count_tokens(_messages(text)) <= send_budget:
        return text

    lo, hi = 0, len(text)
    best = _TRUNCATION_NOTE
    while lo <= hi:
        mid = (lo + hi) // 2
        prefix = text[:mid]
        candidate = f"{prefix}\n\n{_TRUNCATION_NOTE}" if prefix else _TRUNCATION_NOTE
        if count_tokens(_messages(candidate)) <= send_budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


#: The only two valid ``role`` values on a history entry (talking-to-one arc,
#: task t4) — the session-side rolling record of prior senses exchanges.
_VALID_HISTORY_ROLES = ("operator", "senses")


def _history_lines(history: "Optional[list[dict[str, str]]]") -> "list[str]":
    """Format *history* into ordered ``"role: text"`` lines (oldest first).

    Defensive, never raises: an entry that is not a ``dict``, carries a
    ``role`` other than ``"operator"``/``"senses"``, or has a missing/blank/
    non-string ``text`` is silently skipped — a malformed history entry never
    breaks a senses call. ``history`` being ``None`` or empty returns ``[]``,
    the caller's byte-identical no-history signal.
    """
    if not history:
        return []
    lines: "list[str]" = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role not in _VALID_HISTORY_ROLES:
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        lines.append(f"{role}: {text.strip()}")
    return lines


def _fold_history(
    primary_body: str,
    history: "Optional[list[dict[str, str]]]",
    *,
    system_prompt: str,
    budget: int,
    count_tokens: "Callable[[list[dict[str, Any]]], int]",
) -> str:
    """Prefix *primary_body* with a windowed "Conversation so far" block (t4).

    Folds *history* (oldest first) into a clearly-delimited "Conversation so
    far" block placed BEFORE *primary_body* — the caller's already-assembled
    request/feed/summary payload — so the model reads prior exchanges before
    the current turn. Participates in the SAME budget accounting as
    :func:`_window_text` (identical quarter-of-budget completion reserve):
    when the combined ``[system, user=block+primary_body]`` prompt would
    exceed the send budget, the OLDEST history entries are dropped first
    (whole entries, never sliced mid-entry) until it fits.

    *primary_body* is NEVER trimmed here — callers window it via
    :func:`_window_text` first, so it already fits the send budget alone;
    dropping every history entry always recovers that guarantee (the
    function's existing payload always wins over history).

    Returns *primary_body* completely UNCHANGED when *history* is ``None``,
    empty, or every entry is defensively skipped by :func:`_history_lines` —
    the byte-identical no-history path pinned by the existing senses tests.
    """
    lines = _history_lines(history)
    if not lines:
        return primary_body

    reserve = max(1, budget // 4)
    send_budget = max(1, budget - reserve)

    def _messages(body: str) -> "list[dict[str, Any]]":
        msgs: "list[dict[str, Any]]" = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": body})
        return msgs

    def _combine(remaining: "list[str]") -> str:
        if not remaining:
            return primary_body
        block = "Conversation so far:\n" + "\n".join(remaining)
        return f"{block}\n\n{primary_body}"

    remaining = list(lines)
    candidate = _combine(remaining)
    while remaining and count_tokens(_messages(candidate)) > send_budget:
        remaining = remaining[1:]  # drop the OLDEST entry first.
        candidate = _combine(remaining)
    return candidate


class _TokenMeter:
    """Accumulates exact prompt+completion tokens across a call's completions.

    :func:`robust_simple_complete` may issue more than one completion (an
    empty-content follow-up turn), so tokens are SUMMED across every completion
    the invocation actually paid for. Tokens are read verbatim from each
    response's ``prompt_tokens``/``completion_tokens`` — never estimated
    (the token-honesty rule; the senses-side mirror of
    :func:`colleague.deepthink._call_tokens`). ``value`` is ``None`` until at
    least one completion is seen, so a degraded call (which never reached the
    wire) records ``tokens=None``.
    """

    def __init__(self) -> None:
        self._total = 0
        self._seen = False

    def wrap(
        self, complete: "Callable[[list[dict[str, Any]]], Any]"
    ) -> "Callable[[list[dict[str, Any]]], Any]":
        def recording(messages: "list[dict[str, Any]]") -> Any:
            response = complete(messages)
            prompt = getattr(response, "prompt_tokens", 0) or 0
            completion = getattr(response, "completion_tokens", 0) or 0
            self._total += int(prompt) + int(completion)
            self._seen = True
            return response

        return recording

    @property
    def value(self) -> Optional[int]:
        return self._total if self._seen else None


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
        complete = meter.wrap(engine.make_complete(senses_config, tools=[]))
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


def _format_talk_context(message: str, packet: Optional[ContextPacket], task_state: Any) -> str:
    """Build the FIXED (never-windowed) portion of a talk-lane prompt.

    Carries the operator's original request + prior interpretation (from
    *packet*, when present), the caller-supplied *task_state* snapshot, and the
    live *message* itself — everything the talk turn needs EXCEPT the flight
    feed tail, which :func:`run_senses_talk` windows separately so a long-
    running conversation's feed history never crowds out the message being
    asked right now.
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
    lines.append(f"Operator's live message: {message}")
    return "\n".join(lines)


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
        degradation (never estimated).
    """
    if senses_config is None:
        return None

    start = time.monotonic()
    relay_override = _relay_prefix_override(message, relay_prefix)
    meter = _TokenMeter()
    try:
        counter = make_count_tokens if make_count_tokens is not None else count_tokens_chars
        fixed_context = _format_talk_context(message, packet, task_state)
        windowed_feed = _window_text(
            feed_tail or "",
            system_prompt=f"{_TALK_SYSTEM_PROMPT}\n\n{fixed_context}",
            budget=senses_config.context_budget_tokens,
            count_tokens=counter,
        )
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
        return {
            "answer": answer,
            "relay": relay,
            "relay_text": relay_text,
            "latency": latency,
            "degraded": False,
            "tokens": meter.value,
        }
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

    The structural sibling of :func:`run_senses_talk` for *proactive* progress
    narration — the "talking to colleague feels like talking to one person" arc.
    Issues exactly ONE tools-off completion, windowed to senses' OWN context
    budget via :func:`_window_text`, and returns an advisory
    ``{update, latency, tokens, degraded}`` record.

    Grounded: the system prompt instructs senses to narrate in 1–2 first-person
    sentences what the run is doing RIGHT NOW, derived ONLY from the given feed
    lines — quote or paraphrase real lines; if the feed shows nothing new, say
    exactly that; NEVER invent progress, files, or results not present in the
    feed. The same grounding contract as :data:`_TALK_SYSTEM_PROMPT`.

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
        as :func:`run_senses_intake`'s ``history``; ``None``/``[]`` is
        byte-identical to before this parameter existed.

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
    """Bind :func:`run_senses_media_bridge` to *config* + *engine_name* for the loop.

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

    The structural sibling of :func:`run_senses_talk` for a front-door turn
    that never touches a running work item: no flight feed, no task state, no
    relay judgment — just the operator's words grounded against a caller-
    supplied curated fact-set (:func:`colleague.architecture_facts.
    load_architecture_facts`, though any string works — this function does
    not import or depend on that module). Issues exactly ONE tools-off
    completion against the senses model.

    Tools-off ALWAYS: *make_complete* is invoked as
    ``make_complete(senses_config, tools=[])`` — an explicit empty tool list,
    never ``None`` — mirroring :func:`run_senses_talk`. *make_complete* is
    passed in directly (not a full engine), the same shape as
    :func:`run_senses_talk`.

    Grounded: the user prompt carries *facts* + *text* verbatim (never
    trimmed independently — the whole assembled body is windowed together),
    windowed to *senses_config*'s OWN ``context_budget_tokens`` via
    :func:`_window_text`, counted via *make_count_tokens* when given, else the
    zero-dep :func:`~colleague.context.count_tokens_chars` fallback (there is
    no engine object here to fall back to its own counter — the same
    ``make_count_tokens if make_count_tokens is not None else
    count_tokens_chars`` convention as :func:`run_senses_talk`).
    :data:`_FRONTDOOR_SYSTEM_PROMPT` instructs senses to answer ONLY from the
    given facts + the operator's words and to say plainly that it doesn't
    know (deferring to cortex) rather than invent an architecture/identity
    detail not present in *facts*.

    Conversation continuity: an optional *history* (a list of
    ``{"role": "operator"|"senses", "text": "..."}`` entries, oldest first)
    is folded into the user prompt via :func:`_fold_history` the same way as
    every other senses invocation function; ``None``/``[]`` is byte-identical
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
        the caller (mirrors :func:`run_senses_talk`).
    make_count_tokens:
        Injectable token counter; defaults to
        :func:`~colleague.context.count_tokens_chars`.
    history:
        Optional rolling chat history, folded in before the facts+message
        body via :func:`_fold_history`; ``None``/``[]`` is a strict no-op.

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
        primary_body = f"Architecture facts:\n{facts}\n\nOperator's message: {text}"
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

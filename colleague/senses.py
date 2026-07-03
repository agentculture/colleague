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
- :func:`run_senses_speakback` shapes the cortex's raw work summary into a
  conversational display string.

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
"""

from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from colleague.config import EngineConfig
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

_INTAKE_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the perception front door. Read the "
    "operator's request below and perceive what it means BEFORE the cortex model "
    "acts on it. Reply with ONLY a JSON object of the form: "
    '{"interpretation": "...", "confidence": 0.0, "task_type": "...", '
    '"omissions": ["..."]}. '
    '"interpretation" is a normalized restatement of what the operator wants; '
    '"confidence" is your confidence in that reading as a number from 0.0 to 1.0; '
    '"task_type" is a short classification (e.g. bugfix, feature, docs, refactor, '
    'question); "omissions" lists, one short string each, what the request left '
    "implicit or unspecified. Do NOT echo the original request text back. No prose "
    "outside the JSON."
)

_SPEAKBACK_SYSTEM_PROMPT = (
    "You are the senses lobe for colleague — the voice that speaks back to the "
    "operator. Rewrite the cortex model's raw work summary below into a clear, "
    "concise, conversational reply for a human. Preserve every concrete fact "
    "(files changed, decisions, caveats); do not invent anything that is not in "
    "the summary. Reply with ONLY the reply text — no JSON, no preamble."
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
    return dataclasses.replace(
        config,
        model=sc.model,
        base_url=sc.base_url,
        api_key=sc.api_key,
        context_budget_tokens=sc.context_budget,
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
) -> "tuple[Optional[ContextPacket], SensesRecord]":
    """Perceive the operator's *text* into a structured :class:`ContextPacket`.

    Issues exactly ONE tools-off completion against the senses model, windowed
    to the senses model's own budget, and parses a structured
    ``{interpretation, confidence, task_type, omissions}`` JSON reply via the
    solved recovery path (:func:`robust_simple_complete` + ``_extract_json_object``).

    The returned packet's ``original`` is set to *text* **VERBATIM** — the model
    supplies only the derived interpretation/confidence/task_type/omissions; the
    operator's exact request never comes from the model output. That invariant is
    the whole point of the senses front door.

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
) -> "tuple[Optional[str], SensesRecord]":
    """Shape the cortex's raw *summary* into a conversational display string.

    Issues exactly ONE tools-off completion against the senses model, windowed to
    the senses model's own budget, and returns the model's reply text. Never
    raises. On ANY failure (unreachable endpoint, request error, overflow, or
    empty/unrecoverable content) returns ``(None, degraded SensesRecord)`` so the
    caller falls back to the raw *summary*.

    Parameters mirror :func:`run_senses_intake`. Returns ``(display_text | None,
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

"""The dual-model "deepthink" escalation seam (plan task t2).

Colleague optionally pairs a fast, wide-window main model that drives the tool
loop with a second "deepthink" model escalated to for hard-reasoning moments
(planning, verdicts, self-checks, tricky decisions) — see
:class:`colleague.config.DeepthinkConfig` (task t1) and
:class:`colleague.contract.DeepthinkCall` (task t3). This module is the ONE
place that turns a question into a bounded, tools-off completion against the
deepthink model:

- :func:`deepthink_engine_config` builds the :class:`~colleague.config.EngineConfig`
  a deepthink call should run against (``None`` when no dual-model config is
  declared).
- :func:`run_deepthink` issues exactly ONE tools-off completion via the public
  :meth:`colleague.engine.Engine.make_complete` seam, windowing the prompt to
  the deepthink model's OWN context budget first, and NEVER raises — any
  failure anywhere (a bad engine name, a dead port, a request error, an
  overflow, an absent dual-model config) degrades to an empty result with
  ``call.degraded=True`` so the caller can fall back to the main model.

Enumerated callers (spec R3 / c7 / h15 / h3, pinned by a later boundary test):
the ``deepthink`` loop tool's executor, the acceptance self-check, plan-mode
proposals, and the test-integrity reviewer default. No other colleague module
may invoke this seam — that boundary is enforced by task t8's test, not here.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

from colleague import media, registry
from colleague.config import EngineConfig
from colleague.contract import DeepthinkCall

if TYPE_CHECKING:
    from colleague.engine import Engine
    from colleague.loop import ModelResponse

#: Appended to a question truncated to fit the deepthink model's send budget
#: (spec h4) — a visible marker so whoever reads the digest (the main model,
#: an operator inspecting the artifact) knows content was cut, never a silent
#: truncation.
_TRUNCATION_NOTE = "[deepthink digest truncated to fit budget]"


@dataclass
class DeepthinkResult:
    """The outcome of one :func:`run_deepthink` escalation call.

    ``text`` is the deepthink model's answer text — empty (``""``) whenever
    ``call.degraded`` is ``True``, since a degraded call never reached (or
    never usefully reached) the deepthink model. ``call`` is the
    :class:`~colleague.contract.DeepthinkCall` record the caller folds onto
    ``TaskResult.deepthink`` (tasks t3 / t5).
    """

    text: str
    call: DeepthinkCall


def deepthink_engine_config(config: EngineConfig) -> Optional[EngineConfig]:
    """Build the :class:`EngineConfig` a deepthink call should run against.

    Returns ``None`` when *config* carries no dual-model declaration
    (``config.deepthink is None`` — spec h1: the model IS the presence
    signal). Otherwise returns a ``dataclasses.replace`` of *config* with
    ``model``/``base_url``/``api_key`` switched to the deepthink target and
    ``context_budget_tokens`` set to the deepthink model's OWN budget
    (``deepthink.context_budget`` — spec h4: a deepthink call is windowed
    against its own budget, never the main model's). Every other knob
    (``max_steps``, ``timeout``, ``max_output_chars``, ``subagent_*``, …)
    inherits unchanged from *config* — a deepthink call reuses the same
    operational limits it would under the main endpoint, except for what
    dual-model explicitly overrides.
    """
    dt = config.deepthink
    if dt is None:
        return None
    seat = cast(
        EngineConfig,
        dataclasses.replace(
            config,
            model=dt.model,
            refresh_seat=None,
            base_url=dt.base_url,
            api_key=dt.api_key,
            context_budget_tokens=dt.context_budget,
        ),
    )
    # Per-seat thinking effort (#416 t4): the deepthink seat carries its own
    # table rung (xhigh default) via the plain ``reasoning_effort_seat``
    # attribute that ``vllm_openai._effort_for`` honors ahead of the acting
    # seat's resolved rung.
    from colleague import effort

    setattr(
        seat,
        "reasoning_effort_seat",
        effort.resolve_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=config.reasoning_effort_seats.get("deepthink"),
            seat="deepthink",
        ),
    )
    return seat


def _compose_messages(question: str, system_prompt: Optional[str]) -> "list[dict[str, Any]]":
    """Build the one-shot message list: an optional system turn + the question."""
    messages: "list[dict[str, Any]]" = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})
    return messages


def _truncated_text(question: str, cut: int) -> str:
    """The question truncated to its first *cut* characters, with the note appended."""
    prefix = question[:cut]
    if not prefix:
        return _TRUNCATION_NOTE
    return f"{prefix}\n\n{_TRUNCATION_NOTE}"


def _needs_flattening(messages: "list[dict[str, Any]]") -> bool:
    """``True`` iff any message in *messages* carries non-string content.

    A plain OpenAI-format message always has string content; a content-PARTS
    LIST (an image/audio-bearing turn — see :mod:`colleague.media`) is the one
    shape :func:`_flatten_history` must rewrite. Split out so
    :func:`_flatten_history` can skip rebuilding the list entirely when
    nothing needs it (task t7's byte-identical guard).
    """
    return any(not isinstance(m.get("content"), str) for m in messages)


def _flatten_history(messages: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """Flatten every message's ``content`` through :func:`colleague.media.flatten_parts`.

    The deepthink model may be TEXT-ONLY (today's served 27B), so a
    content-PARTS LIST — the shape the loop's own message history carries for
    a media-bearing user turn — must structurally never reach the wire (task
    t7). Every message's content is routed through
    :func:`colleague.media.flatten_parts`: a plain string passes through
    unchanged (``flatten_parts`` is the identity for ``str``), a parts list
    becomes readable text with ``[image attachment]``/``[audio attachment]``
    placeholders standing in for what a text-only model cannot see.

    Byte-identical when nothing needs it: if every message already carries
    string content, the ORIGINAL *messages* object is returned untouched (not
    a copy) — so a string-only history composed by today's callers (the
    `deepthink` tool's model-authored context, plan-mode's claim/text
    prompts) is indistinguishable from before this change, all the way down
    to object identity. Otherwise a NEW list is returned (the input is never
    mutated), each message a shallow copy with ``content`` replaced by its
    flattened string; every other key (``role``, …) is preserved unchanged.
    """
    if not _needs_flattening(messages):
        return messages
    return [dict(m, content=media.flatten_parts(m.get("content", ""))) for m in messages]


def window_messages(
    messages: "list[dict[str, Any]]",
    *,
    budget: int,
    count_tokens: "Callable[[list[dict[str, Any]]], int]",
) -> "list[dict[str, Any]]":
    """Window an already-composed message list to the deepthink send budget.

    The message-list twin of :func:`_window_question`, for the one enumerated
    caller that composes its own multi-turn prompt (plan-mode proposals) —
    spec h4 windows EVERY deepthink call against the deepthink model's OWN
    context budget before the request is sent. This is also the ONE point
    every deepthink message-list digest funnels through (directly here, or by
    way of :func:`_window_question` from :func:`run_deepthink`), so it is
    where :func:`_flatten_history` runs FIRST (task t7): a caller composing
    this digest from the loop's own message history may hand us a
    content-PARTS LIST (a media-bearing user turn), and that list is
    guaranteed flattened to a plain string before any budget arithmetic or
    truncation below ever looks at it — a list-typed content field must
    structurally never reach the second model's wire. A string-only history
    is untouched, including the "no copy" identity guarantee below.

    Reserves one quarter of *budget* for the completion, so the prompt must
    measure at or under ``budget - budget // 4``. A list that already fits is
    returned untouched (byte-identical pass-through). Otherwise the LAST user
    message — the payload turn in every caller's composition — is truncated
    (binary search on length, so the number of ``count_tokens`` calls is
    bounded) with :data:`_TRUNCATION_NOTE` appended, so whoever reads the
    prompt can always tell it was cut. Messages are never dropped and the
    input list is never mutated. A list with no user message is returned
    unchanged — nothing is safely truncatable, and the reactive shrink-retry
    ladder stays the floor.
    """
    messages = _flatten_history(messages)
    reserve = max(1, budget // 4)
    send_budget = max(1, budget - reserve)
    if count_tokens(messages) <= send_budget:
        return messages

    idx = next(
        (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
        None,
    )
    if idx is None:
        return messages

    original = str(messages[idx].get("content") or "")

    def with_content(text: str) -> "list[dict[str, Any]]":
        return [dict(m, content=text) if i == idx else m for i, m in enumerate(messages)]

    lo, hi = 0, len(original)
    best = _TRUNCATION_NOTE
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate_text = _truncated_text(original, mid)
        if count_tokens(with_content(candidate_text)) <= send_budget:
            best = candidate_text
            lo = mid + 1
        else:
            hi = mid - 1
    return with_content(best)


def _window_question(
    question: str,
    *,
    system_prompt: Optional[str],
    budget: int,
    count_tokens: "Callable[[list[dict[str, Any]]], int]",
) -> "list[dict[str, Any]]":
    """Window *question* to fit the deepthink model's send budget BEFORE the request.

    Composes the one-shot message list (optional system turn + the question)
    and delegates the budget arithmetic + truncation to
    :func:`window_messages` — ONE windowing implementation for every
    enumerated escalation point (spec h4). The question is the last (only)
    user message, so a small question passes through byte-identical and an
    oversized one is truncated with the visible :data:`_TRUNCATION_NOTE`.
    """
    return window_messages(
        _compose_messages(question, system_prompt),
        budget=budget,
        count_tokens=count_tokens,
    )


def _call_tokens(response: "ModelResponse") -> int:
    """Exact total tokens used by *response* — never estimated (spec: token honesty).

    Summed from the response's own ``prompt_tokens``/``completion_tokens`` —
    the same fields the loop's ``Usage`` accounting reads verbatim from the
    model's reported ``usage``.
    """
    return response.prompt_tokens + response.completion_tokens


def run_deepthink(
    question: str,
    *,
    config: EngineConfig,
    point: str,
    engine_name: str,
    system_prompt: Optional[str] = None,
    engine_loader: "Optional[Callable[[str], Engine]]" = None,
    count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
) -> DeepthinkResult:
    """Issue exactly ONE tools-off completion against the deepthink model.

    Never raises: any failure — no dual-model config, an unknown engine name,
    a dead port, a request error, a context overflow, anything else — is
    caught and returned as a degraded :class:`DeepthinkResult` (spec h5). The
    caller owns the fallback to the main model; this seam never surfaces an
    exception that could abort the run.

    Parameters
    ----------
    question:
        The question / self-composed digest to ask the deepthink model.
    config:
        The MAIN :class:`EngineConfig` (carrying ``config.deepthink``, if any).
    point:
        A free-form label naming which escalation point fired (e.g.
        ``"tool"``, ``"acceptance_selfcheck"``, ``"plan_proposal"``) — recorded
        on the returned :class:`~colleague.contract.DeepthinkCall` regardless
        of whether the call degraded.
    engine_name:
        The backend plugin name to load for the deepthink call (the deepthink
        endpoint speaks the same OpenAI surface through the same adapter as
        the main model, so this is typically the caller's own engine name).
    system_prompt:
        An optional system-role message prepended ahead of the question.
    engine_loader:
        Injectable engine loader, ``(name) -> Engine``; defaults to
        :func:`colleague.registry.load`. Tests inject a fake to avoid any
        real network call.
    count_tokens:
        Injectable token counter, ``(messages) -> int``; defaults to
        ``engine.make_count_tokens(dt_config)`` (the engine's own exact-or-
        estimate counter).

    Returns
    -------
    DeepthinkResult
        On success: ``text`` is the model's answer, ``call.degraded`` is
        ``False``, ``call.point`` is *point*, ``call.tokens`` is the exact
        summed prompt+completion tokens, ``call.duration`` is the measured
        wall-clock seconds. On any degradation: ``text`` is ``""``,
        ``call.degraded`` is ``True``, ``call.point`` is still *point*,
        ``call.duration`` is the measured wall-clock seconds up to the
        failure (always >= 0, never ``None``), ``call.tokens`` is ``None``.
    """
    start = time.monotonic()

    if config.deepthink is None:
        return DeepthinkResult(
            text="",
            call=DeepthinkCall(point=point, degraded=True, duration=time.monotonic() - start),
        )

    loader = engine_loader if engine_loader is not None else registry.load
    try:
        dt_config = deepthink_engine_config(config)
        if dt_config is None:  # pragma: no cover - guarded by the None check above
            raise RuntimeError("no deepthink config resolved")

        engine = loader(engine_name)
        counter = count_tokens if count_tokens is not None else engine.make_count_tokens(dt_config)
        messages = _window_question(
            question,
            system_prompt=system_prompt,
            budget=dt_config.context_budget_tokens,
            count_tokens=counter,
        )

        # Tools-off ALWAYS (spec h2 / confirmed invariant): an explicit empty
        # tool list, never ``None`` — a deepthink completion structurally
        # cannot call a tool or ``finish``.
        complete = engine.make_complete(dt_config, tools=[])
        response = complete(messages)
        duration = time.monotonic() - start
        return DeepthinkResult(
            text=response.content,
            call=DeepthinkCall(
                point=point,
                tokens=_call_tokens(response),
                duration=duration,
                degraded=False,
            ),
        )
    except Exception:
        duration = time.monotonic() - start
        return DeepthinkResult(
            text="",
            call=DeepthinkCall(point=point, degraded=True, duration=duration),
        )


def run_media_bridge(
    question: str,
    media_parts: "list[dict[str, Any]]",
    *,
    config: EngineConfig,
    point: str = "media-bridge",
    engine_name: str,
    system_prompt: Optional[str] = None,
    engine_loader: "Optional[Callable[[str], Engine]]" = None,
    count_tokens: "Optional[Callable[[list[dict[str, Any]]], int]]" = None,
) -> DeepthinkResult:
    """ONE tools-off completion carrying REAL media parts to the second model (t8).

    The deliberate inverse of the t7 flattening rule: the operator declared the
    SECOND model multimodal (``config.deepthink.multimodal``), so the media
    parts are sent un-flattened to THAT endpoint — and only that endpoint; the
    text-only main wire never sees them. The question text is windowed to the
    deepthink model's own budget minus a per-part media reserve, then the parts
    ride ONE appended user message. Mirrors :func:`run_deepthink`'s
    degrade-never-raise contract (spec h5/h18): any failure returns a degraded
    :class:`DeepthinkResult`, never an exception.
    """
    start = time.monotonic()

    if config.deepthink is None or not config.deepthink.multimodal or not media_parts:
        return DeepthinkResult(
            text="",
            call=DeepthinkCall(point=point, degraded=True, duration=time.monotonic() - start),
        )

    loader = engine_loader if engine_loader is not None else registry.load
    try:
        dt_config = deepthink_engine_config(config)
        if dt_config is None:  # pragma: no cover - guarded above
            raise RuntimeError("no deepthink config resolved")

        engine = loader(engine_name)
        counter = count_tokens if count_tokens is not None else engine.make_count_tokens(dt_config)
        # Reserve budget for the media parts themselves so the windowed text +
        # parts still fit the deepthink window (t6's estimate currency).
        reserve = media.IMAGE_TOKEN_ESTIMATE * len(media_parts)
        text_budget = max(1, dt_config.context_budget_tokens - reserve)
        messages = _window_question(
            question,
            system_prompt=system_prompt,
            budget=text_budget,
            count_tokens=counter,
        )
        messages = messages + [
            {
                "role": "user",
                "content": [{"type": "text", "text": "The attached media:"}] + list(media_parts),
            }
        ]

        complete = engine.make_complete(dt_config, tools=[])
        response = complete(messages)
        duration = time.monotonic() - start
        return DeepthinkResult(
            text=response.content,
            call=DeepthinkCall(
                point=point,
                tokens=_call_tokens(response),
                duration=duration,
                degraded=False,
            ),
        )
    except Exception:
        duration = time.monotonic() - start
        return DeepthinkResult(
            text="",
            call=DeepthinkCall(point=point, degraded=True, duration=duration),
        )


DeepthinkRun = Callable[..., DeepthinkResult]
"""The bound escalation callable the runtime threads through the loop.

Signature: ``(question: str, context: str = "", *, point: str = "tool") ->
DeepthinkResult``. Built once per work item by :func:`make_deepthink_run` and
handed BOTH to the tool executor (the model-facing ``deepthink`` tool) and to
:class:`~colleague.loop.ContextControls` (the runtime-owned escalation points,
e.g. the acceptance self-check) — one binding, every consumer (all-engines rule).
"""


def make_deepthink_run(config: EngineConfig, engine_name: str) -> Optional[DeepthinkRun]:
    """Bind :func:`run_deepthink` to *config* + *engine_name* for the loop.

    Returns ``None`` when no dual-model config is present (``config.deepthink``
    is ``None``) — the single-model signal every consumer keys off: the engine
    then offers no ``deepthink`` tool schema, the executor holds no seam, and
    the runtime escalation points stay dormant (byte-identical run).

    The returned callable never raises (it delegates to :func:`run_deepthink`,
    which degrades internally — spec h5). ``context`` is appended to the
    question as a labelled digest block so the deepthink model receives ONE
    self-contained prompt.
    """
    if config.deepthink is None:
        return None

    def bound(
        question: str,
        context: str = "",
        *,
        point: str = "tool",
        media_parts: "Optional[list[dict[str, Any]]]" = None,
    ) -> DeepthinkResult:
        prompt = question if not context else f"{question}\n\nContext digest:\n{context}"
        if media_parts:
            # The media-bridge path (t8): parts travel un-flattened to the
            # operator-declared multimodal second endpoint.
            return run_media_bridge(
                prompt,
                media_parts,
                config=config,
                point=point,
                engine_name=engine_name,
            )
        return run_deepthink(prompt, config=config, point=point, engine_name=engine_name)

    return bound

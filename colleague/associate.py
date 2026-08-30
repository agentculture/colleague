"""The associate seat builder — a fast, tool-capable NON-coding mind (t18).

adopt-from-qwen-code arc (spec docs/specs/2026-08-27-adopt-from-qwen-code.md,
claims c37/h26, c49/h36, decision c52; plan task t18). Mirrors
:func:`colleague.deepthink.deepthink_engine_config`'s shape: a
``dataclasses.replace`` of the acting config switched to the associate target,
plus the plain ``reasoning_effort_seat`` attribute ``vllm_openai._effort_for``
honours (the ``associate`` :data:`colleague.effort.SEAT_TABLE` row: ``off`` —
Nemotron spends its first tokens thinking; a scout seat must not).

Wire addressing (c49): a lobes-discovered seat sends the ROLE NAME as
``model`` (spark's gateway completes ``{"model": "associate"}`` through the
Orin proxy and refuses the raw served id with ``role_infeasible``); the
adapter reads the SERVED model back from the reply and, on a gateway that
rejects the role name, retries ONCE with the served id
(:meth:`~colleague.engines.vllm_openai.VllmOpenAIEngine._recover_http_error`).
What happens after that single retry is the CONSUMER's call (plan task t19):
the enumerated associate seats fall to cortex@low with a recorded warning.

Streaming (c52): nothing here touches ``on_delta``/``COLLEAGUE_STREAM`` — the
seat rides the same engine path as cortex, headless included, so it streams
exactly as cortex does.

Resolution only, never a router: which seats consume this config is a FIXED
tuple owned by task t19; the runtime never picks a model per turn.
"""

from __future__ import annotations

import dataclasses
import urllib.error
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

from colleague import effort
from colleague.config import ASSOCIATE_WIRE_MODEL, EngineConfig
from colleague.efforttables import resolve_associate_sub_seat_effort

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.associate_config import AssociateConfig

__all__ = [
    "ASSOCIATE_WIRE_MODEL",
    "ROLE_WIRE_ALIASES",
    "associate_engine_config",
    "recorded_model",
    "retry_role_alias",
    "served_model_expected",
    "wire_fallback_model",
]

#: Wire-model aliases that are ROLE NAMES, not served ids (c49): a run whose
#: configured model is one of these records the reply's served model instead.
ROLE_WIRE_ALIASES = frozenset({ASSOCIATE_WIRE_MODEL})

# Plain (non-field) attributes the seat builder stamps on its replaced config.
# Like ``reasoning_effort_seat``, ``dataclasses.replace`` drops them — a copy
# that never set them is not an associate seat.
_SERVED_MODEL_ATTR = "associate_served_model"
_PROFILE_ATTR = "associate_profile"
_WIRE_FALLBACK_ATTR = "associate_wire_fallback_model"


def served_window_budget(assoc: "AssociateConfig") -> int:
    """The associate seat's context budget clamped to its SERVED window (#460).

    The lobes advert for a proxied associate carries the model's nominal
    context (1,048,576 on the reference rig) while the deployment serves
    ``max_model_len`` 128,000 — a budget derived from the advert lets the
    child's history grow past what the server accepts (a context-length 400).
    ONE ``/tokenize`` probe per ``(tokenize url, wire model)`` per process
    (cached by the adapter) discovers the served window; the budget becomes
    ``min(assoc.context_budget, served - output margin)``. No probe result
    (a server without ``/tokenize``, a network error) leaves the configured
    budget untouched — retargeting stays a config change.
    """
    from colleague import outputclamp
    from colleague.engines import vllm_openai as _vllm  # lazy: vllm_openai imports this module

    url = _vllm._tokenize_url(assoc.base_url)
    served = _vllm.served_max_model_len(url, assoc.wire_model)
    if served is None:
        _vllm._tokenize_count(
            [{"role": "user", "content": "probe"}],
            url=url,
            model=assoc.wire_model,
            api_key=assoc.api_key,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        served = _vllm.served_max_model_len(url, assoc.wire_model)
    if not isinstance(served, int) or served <= 0:
        return assoc.context_budget
    return max(1, min(assoc.context_budget, served - outputclamp.output_clamp_margin(served)))


#: The seat-build probe's timeout — a slow/absent /tokenize must not stall a run.
_PROBE_TIMEOUT_SECONDS = 10.0


def associate_engine_config(
    config: EngineConfig, sub_seat: Optional[str] = None
) -> Optional[EngineConfig]:
    """Build the :class:`EngineConfig` an associate-seat call runs against.

    ``None`` when *config* carries no associate declaration (the model IS the
    presence signal — byte-identical to main). Otherwise a replace of *config*
    with ``model`` = the seat's WIRE model (the role name for a discovered
    seat, the id for an explicit one), ``base_url``/``api_key`` = the seat's
    own, ``context_budget_tokens`` = the seat's own budget, per-call knobs
    (``on_delta``/``refresh_seat``) cleared exactly like the other seat
    builders, and the effort rung set (c32 precedence: the ``default`` kill
    switch wins, then the ``"associate.<sub_seat>"`` sub-seat override, then
    the whole-seat ``reasoning_effort_seats["associate"]`` row, then the
    ``ASSOCIATE_SEAT_TABLE`` row for *sub_seat* — the plain ``associate``
    table row when *sub_seat* is ``None``).
    """
    assoc = config.associate
    if assoc is None:
        return None
    seat = cast(
        EngineConfig,
        dataclasses.replace(
            config,
            model=assoc.wire_model,
            on_delta=None,
            refresh_seat=None,
            base_url=assoc.base_url,
            api_key=assoc.api_key,
            # #460: the associate's budget is clamped to the SERVED window (one
            # /tokenize probe per (url, model) per process), never the advert's
            # nominal context; the operator's smaller value still wins.
            context_budget_tokens=served_window_budget(assoc),
            # The parent's lobes_context is CORTEX's advertised window — wrong
            # for this seat; None lets the /tokenize max_model_len win the
            # output clamp (outputclamp.resolve_window precedence).
            lobes_context=None,
        ),
    )
    seats = config.reasoning_effort_seats
    if sub_seat is None:
        rung = effort.resolve_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=seats.get("associate"),
            seat="associate",
        )
    else:
        rung = resolve_associate_sub_seat_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=seats.get(f"associate.{sub_seat}"),
            row_override=seats.get("associate"),
            seat=sub_seat,
        )
    setattr(seat, "reasoning_effort_seat", rung)
    setattr(seat, _SERVED_MODEL_ATTR, assoc.model)
    # t23: the seat carries its sampling/thinking profile; the payload builder
    # and the turn budget read it (cortex carries none — byte-identical).
    setattr(seat, _PROFILE_ATTR, assoc.profile)
    # The one-shot wire fallback exists only for a role-name-addressed seat.
    setattr(seat, _WIRE_FALLBACK_ATTR, assoc.model if assoc.addressed_as_role else None)
    return seat


def recorded_model(configured: str, served: str) -> str:
    """The model id the artifact records: the reply's SERVED id when the run
    was configured with a role-name alias (``associate``), else the configured
    id — a real model id is never overwritten by a served-model observation."""
    return served if (served and configured in ROLE_WIRE_ALIASES) else configured


def seat_profile(config: object):
    """The :class:`~colleague.associate_config.AssociateProfile` an associate seat
    carries (t23), or ``None`` for every other seat."""
    return getattr(config, _PROFILE_ATTR, None)


def served_model_expected(config: object) -> Optional[str]:
    """The served model id an associate seat config expects the reply to name."""
    return getattr(config, _SERVED_MODEL_ATTR, None)


def wire_fallback_model(config: object) -> Optional[str]:
    """The id to retry with ONCE if the gateway rejects the role-name address."""
    return getattr(config, _WIRE_FALLBACK_ATTR, None)


_CONTEXT_LENGTH_MARKERS = ("maximum context length", "context length", "context_length")


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    """The error body text already folded onto *exc* (the adapter folds it into
    ``exc.msg``; ``exc.reason`` merely aliases it), or ``""`` — never re-reads
    the stream. ``msg`` first, ``reason`` only as a fallback: joining both
    repeated every body twice in the folded ``refused:`` line (review, 2026-08-30)."""
    msg = str(getattr(exc, "msg", "") or "")
    return msg if msg else str(getattr(exc, "reason", "") or "")


def _is_context_length_error(exc: urllib.error.HTTPError) -> bool:
    """vLLM's over-long-prompt 400 shape (``This model's maximum context length
    is N tokens…``): the seat is fine, the request is too long (#460)."""
    body = _http_error_body(exc).lower()
    return exc.code == 400 and any(marker in body for marker in _CONTEXT_LENGTH_MARKERS)


def _folded_http_error(
    original: urllib.error.HTTPError, retry: urllib.error.HTTPError
) -> urllib.error.HTTPError:
    """One HTTPError carrying the ORIGINAL rejection and the served-id retry's
    failure in its message (#460): the artifact's ``refused:`` line names both."""
    msg = (
        f"{original.code} on the role-name address: {_http_error_body(original)[:400]} | "
        f"served-id retry then failed with {retry.code}: {_http_error_body(retry)[:400]}"
    )
    return urllib.error.HTTPError(retry.url, original.code, msg, retry.hdrs, None)


def retry_role_alias(
    exc: urllib.error.HTTPError,
    payload: "dict[str, Any]",
    config: EngineConfig,
    dispatch: "Callable[[], Any]",
) -> Optional[Any]:
    """ONE retry by served id when a gateway rejects a role-name address (c49/h36).

    Called from the vLLM adapter's single-shot recovery ladder
    (``VllmOpenAIEngine._recover_http_error``). Fires only for a seat this
    module stamped with a wire fallback (:func:`wire_fallback_model`) whose
    payload still carries the role-name alias, on a 400/404/422 — the gateway
    shapes observed for an unroutable role. Rewrites ``payload["model"]`` AND
    ``config.model`` to the served id (so later turns do not re-fail), records
    a :class:`~colleague.lobes.ModelRefreshWarning` (stderr +
    ``config.model_refresh_warnings``), and dispatches once. Never fires for
    the cortex/main seat (no stamp) and never twice (after the rewrite the
    alias is gone). A failure of the retry propagates unchanged — falling to
    cortex@low is the consumer's job (task t19).
    """
    from colleague import lobes as _lobes

    fallback_id = wire_fallback_model(config)
    if not fallback_id or exc.code not in (400, 404, 422):
        return None
    if _is_context_length_error(exc):
        # #460: a context-length 400 is the MODEL's window, not the gateway
        # rejecting the role-name address — retrying by served id can only
        # turn it into a 404 role_infeasible and hide the real cause.
        return None
    alias = payload.get("model")
    if alias != config.model or alias == fallback_id:
        return None
    warning = _lobes.ModelRefreshWarning(
        role="associate",
        stale_id=str(alias),
        source="call-time-role-alias-rejected",
        refreshed_id=fallback_id,
        point="call",
    )
    _lobes.emit_model_refresh_warning(warning)
    config.model_refresh_warnings = config.model_refresh_warnings + (warning,)
    config.model = fallback_id
    payload["model"] = fallback_id
    try:
        return dispatch()
    except urllib.error.HTTPError as retry_exc:
        # #460: the fallback failed too (on a proxied deployment the served id
        # is refused as role_infeasible) — surface BOTH bodies, never just the
        # retry's, so an artifact names the original rejection.
        raise _folded_http_error(exc, retry_exc) from retry_exc

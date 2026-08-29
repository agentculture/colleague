"""Distillation-child effort plumbing (#416 extension, spec c9/h9/c38/h36).

``colleague/distill.py`` is file-length-ratchet pinned (``tests/
test_file_length_ratchet.py``), so the per-seat thinking-effort ladder's
distill-child surface lives HERE instead — the fragment builder, the raised
``max_tokens`` envelope for an armed rung, the one-shot ladder-400 retry
(mirroring :func:`colleague.engines.vllm_openai.VllmOpenAIEngine.
_maybe_retry_ladder_400`'s single-retry rule WITHOUT importing the adapter),
and the ``finish_reason == "length"``-with-no-JSON failure classifier.

This module imports no ``subprocess`` and no ``urllib.request`` — the raw HTTP
POST stays exactly where it already lived, in ``distill.py``'s
``_openai_completion``; ``tests/test_boundary.py``'s sanctioned-subprocess
list is unaffected. It DOES import ``urllib.error`` (Qodo review 3883003365):
classifying a ladder-400 requires the response BODY, and the body-read plus
the legible re-raise of the non-ladder case are one indivisible single-read
step — splitting them across the two modules would either read the
single-shot body twice or leave ``distill.py`` (file-length-ratchet pinned)
carrying error-shaping code this module exists to hold. No socket is opened
here; ``urllib.error`` is exception types only.
"""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass
from typing import Any, Callable, Optional

from colleague import effort as _effort

#: The off/None/kill-switched envelope — the ORIGINAL measured cap (t3
#: sizing, see ``distill.py``'s ``_DISTILL_MAX_TOKENS`` comment).
OFF_MAX_TOKENS = 4096

#: An armed ladder rung (low/medium/high/xhigh) reserves headroom for the
#: heavier reasoning spend a live rung invites — well above the off-rung
#: envelope so raising effort doesn't immediately re-truncate the completion.
ARMED_MAX_TOKENS = 12288


def chat_template_fragment(rung: Optional[str]) -> Optional[dict]:
    """The ``chat_template_kwargs`` fragment for *rung* (t2's resolved
    ``DistillAuthor.effort``) — a thin re-export of
    :func:`colleague.effort.to_chat_template_kwargs` so callers in
    ``distill.py`` need not import ``colleague.effort`` directly."""
    return _effort.to_chat_template_kwargs(rung)


def max_tokens_for_rung(rung: Optional[str]) -> int:
    """The distill completion's ``max_tokens`` cap for the resolved *rung*.

    Off / ``None`` / the ``"default"`` kill-switch sentinel keep the
    original measured envelope (:data:`OFF_MAX_TOKENS`). Any live ladder
    rung (low/medium/high/xhigh) raises the cap to :data:`ARMED_MAX_TOKENS`.
    """
    if rung in (None, "off", _effort.DEFAULT_SENTINEL):
        return OFF_MAX_TOKENS
    return ARMED_MAX_TOKENS


def read_error_body(exc: Any) -> str:
    """Best-effort decode of an HTTPError response body (``""`` if
    unavailable) — mirrors
    :func:`colleague.engines.vllm_openai._read_error_body` without importing
    that module.

    An ``HTTPError`` body is a SINGLE-READ stream: call this exactly once per
    exception and pass the result on (:func:`handle_http_error` is the only
    caller in the distill path).
    """
    try:
        return exc.read().decode("utf-8", "replace").strip()
    except Exception:  # nosec B110 - body is advisory; never let decoding mask the HTTP error
        return ""


def apply_child_effort_env(env: "dict[str, str]", rung: Optional[str]) -> "dict[str, str]":
    """Make *env* reflect the parent's RESOLVED distill rung, authoritatively.

    An armed rung is exported as ``COLLEAGUE_DISTILL_EFFORT``; a resolved-off
    rung (``None`` — the ``reasoning_effort`` kill-switch, or simply no rung)
    REMOVES the key, so an operator's parent-side value can never silently
    re-arm a reasoning fragment (and the raised :data:`ARMED_MAX_TOKENS`
    envelope) in a child whose parent resolved none — an absent ``--effort``
    argv option must not be indistinguishable from an unset parent decision
    (Qodo 3883003379). ``distill.child_main``'s env fallback keeps working
    for a hand-run child, which has no spawning parent to contradict.
    """
    env.pop("COLLEAGUE_DISTILL_EFFORT", None)
    if rung:
        env["COLLEAGUE_DISTILL_EFFORT"] = rung
    return env


def is_ladder_400(exc: Any, detail: str = "") -> bool:
    """True for the "server rejects this reasoning-effort ladder rung"
    shape — mirrors :func:`colleague.engines.vllm_openai._is_ladder_400`
    (an HTTP 400 naming "reasoning effort", case-insensitive) without
    importing that module.

    The adapter classifies the ALREADY body-folded re-raise, so ``str(exc)``
    carries the server's text there. In the distill path the exception is
    still the raw ``HTTPError`` — whose ``str()`` renders only "HTTP Error
    400: Bad Request" — so the body arrives separately as *detail*
    (:func:`read_error_body`) and both are searched (Qodo 3883003365).
    """
    return getattr(exc, "code", None) == 400 and "reasoning effort" in f"{exc} {detail}".lower()


@dataclass(frozen=True)
class LadderRetryOutcome:
    """One ladder-400 retry's result: the retried response plus a warning
    string ready for the outcome marker."""

    response: Any
    warning: str


def retry_without_fragment_once(
    exc: Any,
    payload: "dict[str, Any]",
    dispatch: "Callable[[], Any]",
    detail: str = "",
) -> Optional[LadderRetryOutcome]:
    """One-shot ladder-400 retry (mirrors ``_maybe_retry_ladder_400``'s
    single-retry rule): drop ``chat_template_kwargs`` from *payload* and
    retry ONCE via *dispatch*.

    Returns ``None`` when *exc* is not a ladder-400 rejecting
    ``chat_template_kwargs`` — the caller re-raises. A second ladder-400
    (the caller's own re-raise on the retried ``dispatch()`` call)
    propagates unguarded, exactly like the adapter's own single-shot rule.
    """
    if "chat_template_kwargs" not in payload or not is_ladder_400(exc, detail):
        return None
    payload.pop("chat_template_kwargs", None)
    warning = (
        "colleague: distill ladder retry — the chat_template_kwargs fragment "
        f"was rejected by the server; retried once without it. Server said: "
        f"{detail or exc}"
    )
    return LadderRetryOutcome(response=dispatch(), warning=warning)


def handle_http_error(
    exc: "urllib.error.HTTPError",
    url: str,
    payload: "dict[str, Any]",
    dispatch: "Callable[[], Any]",
) -> LadderRetryOutcome:
    """The distill POST's whole HTTPError policy, body read exactly ONCE.

    Reads the single-shot response body, then either retries a ladder-400
    once without ``chat_template_kwargs`` (returning the outcome) or re-raises
    the error LEGIBLY with the body folded into the message — the same shape
    :func:`colleague.engines.vllm_openai._raise_legible_http_error` produces,
    so a non-ladder failure names what the server actually said instead of
    the bare "HTTP Error 400: Bad Request".

    A second ladder-400 raised by the retried *dispatch* propagates unguarded
    (the single-shot rule): it is raised from inside this handler and never
    re-enters it.
    """
    detail = read_error_body(exc)
    outcome = retry_without_fragment_once(exc, payload, dispatch, detail)
    if outcome is not None:
        return outcome
    if not detail:
        raise exc
    raise urllib.error.HTTPError(url, exc.code, f"{exc.msg}: {detail}", exc.headers, None) from exc


def reasoning_exhausted_reason(max_tokens: int, reasoning_chars: int, content_chars: int) -> str:
    """The failure-reason text for ``finish_reason == "length"`` with no
    lesson JSON extracted — named 'reasoning exhausted max_tokens' rather
    than a generic schema complaint (h10): the reasoning spend, not a bad
    prompt or a validator refusal, is what ate the budget."""
    return (
        f"reasoning exhausted max_tokens: the distillation completion hit "
        f"max_tokens={max_tokens} (finish_reason=length) with {reasoning_chars} "
        f"reasoning chars and {content_chars} content chars — the reasoning "
        f"consumed the budget before a complete lesson JSON was emitted "
        f"(truncated); raise max_tokens or shorten the distillation prompt"
    )

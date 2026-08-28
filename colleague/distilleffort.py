"""Distillation-child effort plumbing (#416 extension, spec c9/h9/c38/h36).

``colleague/distill.py`` is file-length-ratchet pinned (``tests/
test_file_length_ratchet.py``), so the per-seat thinking-effort ladder's
distill-child surface lives HERE instead — the fragment builder, the raised
``max_tokens`` envelope for an armed rung, the one-shot ladder-400 retry
(mirroring :func:`colleague.engines.vllm_openai.VllmOpenAIEngine.
_maybe_retry_ladder_400`'s single-retry rule WITHOUT importing the adapter),
and the ``finish_reason == "length"``-with-no-JSON failure classifier.

This module imports no ``subprocess`` and no ``urllib`` — the raw HTTP POST
stays exactly where it already lived, in ``distill.py``'s
``_openai_completion``; ``tests/test_boundary.py``'s sanctioned-subprocess
list is unaffected.
"""

from __future__ import annotations

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


def is_ladder_400(exc: Any) -> bool:
    """True for the "server rejects this reasoning-effort ladder rung"
    shape — mirrors :func:`colleague.engines.vllm_openai._is_ladder_400`
    (an HTTP 400 naming "reasoning effort", case-insensitive) without
    importing that module."""
    return getattr(exc, "code", None) == 400 and "reasoning effort" in str(exc).lower()


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
) -> Optional[LadderRetryOutcome]:
    """One-shot ladder-400 retry (mirrors ``_maybe_retry_ladder_400``'s
    single-retry rule): drop ``chat_template_kwargs`` from *payload* and
    retry ONCE via *dispatch*.

    Returns ``None`` when *exc* is not a ladder-400 rejecting
    ``chat_template_kwargs`` — the caller re-raises. A second ladder-400
    (the caller's own re-raise on the retried ``dispatch()`` call)
    propagates unguarded, exactly like the adapter's own single-shot rule.
    """
    if "chat_template_kwargs" not in payload or not is_ladder_400(exc):
        return None
    payload.pop("chat_template_kwargs", None)
    warning = (
        "colleague: distill ladder retry — the chat_template_kwargs fragment "
        f"was rejected by the server; retried once without it. Server said: {exc}"
    )
    return LadderRetryOutcome(response=dispatch(), warning=warning)


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

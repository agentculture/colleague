"""The wire filter: which resolved sampling keys actually go on the request.

A :class:`colleague.sampling.SamplingProfile` is the honest record of what a
model card *says*. This module decides what of it is worth putting on a
request body, and it is the ONE place that names the vLLM extension keys.

**Why a filter at all** (#479 claim c8). The Qwen3.8 rows set ``min_p 0.0``
and ``repetition_penalty 1.0`` because those are the card's values — but they
are also the server's own defaults, so sending them changes nothing while
widening colleague's non-OpenAI surface for nothing. The ROW keeps the card;
the WIRE drops any key whose value already equals the server default. That
leaves ``top_k`` as the only vLLM extension the builtin table actually needs
on the wire, which is what keeps the adapter's fourth carve-out to one key
rather than three.

**Why its own module.** Two call sites need this identical decision — the
adapter's payload builder (``colleague/engines/vllm_payload.py``) and the
detached distill child (``colleague/distill.py``, which must not import the
engines package). #479's t5 and t8 each landed a private copy; two copies of
"what counts as a server default" is exactly the kind of thing that drifts,
so they are reconciled here. Keeping it out of :mod:`colleague.sampling`
preserves that module's job — the card table and the match rule — from the
separate question of what a particular transport should send.

Pure stdlib plus :mod:`colleague.sampling`. Imports nothing from the engines
package, the loop or the config, so the detached child can import it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from colleague import sampling

__all__ = [
    "SAMPLING_COERCERS",
    "SAMPLING_DISABLING_VALUES",
    "SAMPLING_ENV_KEY",
    "SERVER_DEFAULT_SAMPLING",
    "sampling_enabled",
    "wire_fragment",
]

#: Sampling keys whose value equals the server's own default, and are
#: therefore dropped rather than sent (see the module docstring).
#:
#: ``temperature`` is deliberately ABSENT: a payload builder always writes a
#: temperature, so a row's temperature is an OVERRIDE of an existing key
#: rather than an addition — filtering it would leave the pre-#479 greedy
#: ``0.0`` on the wire, the exact bug this arc fixes.
#:
#: ``top_k`` is absent too: vLLM spells "disabled" as ``-1`` or ``0``
#: depending on version, so there is no single unambiguous default to compare
#: against.
SERVER_DEFAULT_SAMPLING: Dict[str, Any] = {
    "top_p": 1.0,
    "min_p": 0.0,
    "presence_penalty": 0.0,
    "repetition_penalty": 1.0,
}

_UNSET = object()


def wire_fragment(profile: Optional["sampling.SamplingProfile"]) -> Dict[str, Any]:
    """Render *profile* into the payload keys a request should actually carry.

    Only keys the row explicitly set (``None`` fields are omitted by
    :func:`colleague.sampling.sampling_payload`), minus any whose value
    already equals :data:`SERVER_DEFAULT_SAMPLING`. A ``None`` profile — no
    matching row, or a rung that yields no half — renders ``{}``, the
    byte-identical off-state.
    """
    return {
        key: value
        for key, value in sampling.sampling_payload(profile).items()
        if SERVER_DEFAULT_SAMPLING.get(key, _UNSET) != value
    }


#: The recognised sampling keys and how an operator-supplied value is coerced.
#: Lives here, beside :data:`SERVER_DEFAULT_SAMPLING`, so this module is the
#: single place in the tree that spells the vLLM extension key names — the
#: guard in ``tests/test_sampling_payload_wiring.py`` asserts exactly that.
#: The ``associate_config`` tolerance precedent applies at the call site: an
#: unparseable value is IGNORED, never a refusal.
SAMPLING_COERCERS: Dict[str, Callable[[Any], Any]] = {
    "temperature": float,
    "top_p": float,
    "top_k": int,
    "min_p": float,
    "presence_penalty": float,
    "repetition_penalty": float,
}


#: The per-process kill switch and the spellings that disable sampling.
#: Defined here so the adapter (which consumes it) and ``config show`` (which
#: REPORTS it) can never disagree — they did: the adapter disabled on any of
#: these four spellings while ``config show`` matched only the literal ``"0"``,
#: so ``COLLEAGUE_SAMPLING=off`` sent no keys while ``config show`` reported a
#: match (#479 arc deviation d6, found by the t11 doc pass).
SAMPLING_ENV_KEY = "COLLEAGUE_SAMPLING"
SAMPLING_DISABLING_VALUES = frozenset({"0", "false", "no", "off"})


def sampling_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """False only under an explicit :data:`SAMPLING_ENV_KEY` kill-switch value."""
    import os

    raw = (env if env is not None else os.environ).get(SAMPLING_ENV_KEY)
    if raw is None:
        return True
    return raw.strip().lower() not in SAMPLING_DISABLING_VALUES

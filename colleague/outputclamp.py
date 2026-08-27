"""Window-clamped ``max_tokens`` sizing with per-seat ceilings (pure, #416-adjacent).

adapted-from: qwen-code packages/core/src/core/tokenLimits.ts:36-77

Ports three pieces of qwen-code's ``clampOutputTokensToWindow`` machinery to
stdlib Python, unchanged in arithmetic:

- :func:`output_clamp_margin` — the safety headroom subtracted from the
  context window before sizing an output request (``outputClampMargin`` in
  the source): ``max(10_000, round(0.05 * window))``. Absorbs prompt-
  estimation error plus system/tool/schema overhead not captured by an
  API-reported prompt count.
- :func:`clamp_output_tokens` — sizes an output request to the room actually
  left in the window (``clampOutputTokensToWindow``):
  ``min(ceiling, max(MIN_CLAMPED_OUTPUT_TOKENS, window - prompt - margin))``.
  Floors the ROOM, then caps by the ceiling — never the reverse — so an
  explicit ceiling below :data:`MIN_CLAMPED_OUTPUT_TOKENS` is still
  respected rather than inflated to the floor.
- :data:`MIN_CLAMPED_OUTPUT_TOKENS` / :data:`OUTPUT_TOKEN_CEILING` — the
  source's floor (4000) and default acting-seat ceiling (64000, the same
  value as qwen-code's ``ESCALATED_MAX_TOKENS``/``OUTPUT_TOKEN_CEILING``).

Two colleague-side additions layered on top of the ported core (not present
in the qwen-code source, since colleague resolves the window from a
different precedence chain and has per-seat ceilings qwen-code doesn't):

- :func:`resolve_window` — picks the context window from the precedence
  lobes-reported context length -> ``/tokenize`` ``max_model_len`` ->
  ``COLLEAGUE_CONTEXT_BUDGET``-derived fallback, and reports which source
  won (for logging/diagnostics — never silently guessed).
- :func:`seat_ceiling` — resolves the output ceiling for a named seat (seat
  names recognised are exactly :data:`colleague.effort.SEAT_TABLE`'s keys):
  ``OUTPUT_TOKEN_CEILING`` (64000) for acting seats, the design ceiling
  (``COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN``, default 131072) for the two
  high-ceiling seats (``deepthink``, ``design``). ``COLLEAGUE_MAX_OUTPUT_TOKENS``
  set to ``0`` is the global kill-switch: no clamp at all (``None``),
  regardless of seat. A non-zero ``COLLEAGUE_MAX_OUTPUT_TOKENS`` overrides
  the acting-seat ceiling (design seats keep their own dedicated knob).

Pure functions only — this module reads ``os.environ`` directly (no
``colleague.config`` dependency) and imports nothing from
``colleague.loop``/``colleague.tools``/``colleague.engines``; wiring these
functions into the tool loop is a separate task (t15). The one cross-module
import, :data:`colleague.effort.SEAT_TABLE`, is a stdlib-only sibling module
(no config/loop coupling of its own) — it exists solely so this module
recognises the same seat vocabulary the effort ladder does, never a second,
drifting copy of that list.
"""

from __future__ import annotations

import os
from typing import Optional

from colleague.effort import SEAT_TABLE

# ---------------------------------------------------------------------------
# Ported constants (qwen-code tokenLimits.ts:11-35)
# ---------------------------------------------------------------------------

#: Floor applied to the window ROOM when clamping an output request (ported
#: unchanged from qwen-code's ``MIN_CLAMPED_OUTPUT_TOKENS``).
MIN_CLAMPED_OUTPUT_TOKENS = 4_000

#: Default ceiling on an auto-sized (non-user-configured) output request for
#: an *acting* seat — same value as qwen-code's ``OUTPUT_TOKEN_CEILING`` /
#: ``ESCALATED_MAX_TOKENS``.
OUTPUT_TOKEN_CEILING = 64_000

#: Default ceiling for the two high-ceiling (design/deepthink) seats when
#: ``COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN`` is unset.
DEFAULT_DESIGN_OUTPUT_CEILING = 131_072

#: Seats from :data:`colleague.effort.SEAT_TABLE` that get the higher design
#: ceiling instead of :data:`OUTPUT_TOKEN_CEILING`.
DESIGN_SEATS = frozenset({"deepthink", "design"})

_MAX_OUTPUT_TOKENS_ENV = "COLLEAGUE_MAX_OUTPUT_TOKENS"
_MAX_OUTPUT_TOKENS_DESIGN_ENV = "COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN"


# ---------------------------------------------------------------------------
# output_clamp_margin / clamp_output_tokens (ported: tokenLimits.ts:36-77)
# ---------------------------------------------------------------------------


def output_clamp_margin(context_window_size: int) -> int:
    """Safety headroom subtracted from *context_window_size* before sizing an
    output request: ``max(10_000, round(0.05 * context_window_size))``.

    Ported unchanged from qwen-code's ``outputClampMargin``. Deliberately
    conservative — a generous margin only trims output near compaction,
    while an under-sized one reintroduces truncation-provoked 400s.
    """
    return max(10_000, round(0.05 * context_window_size))


def clamp_output_tokens(output_ceiling: int, context_window_size: int, prompt_tokens: int) -> int:
    """Size an output request to the room left in the window.

    ``min(output_ceiling, max(MIN_CLAMPED_OUTPUT_TOKENS, room))`` where
    ``room = context_window_size - prompt_tokens - output_clamp_margin(...)``.
    Ported unchanged from qwen-code's ``clampOutputTokensToWindow``: the ROOM
    is floored first, then capped by the ceiling — never the other way
    around — so an explicit ceiling below the floor (a capacity-constrained
    backend deliberately configured low) is respected, not inflated.
    """
    room = context_window_size - prompt_tokens - output_clamp_margin(context_window_size)
    return min(output_ceiling, max(MIN_CLAMPED_OUTPUT_TOKENS, room))


# ---------------------------------------------------------------------------
# resolve_window (colleague-side addition: window-source precedence)
# ---------------------------------------------------------------------------


def resolve_window(
    lobes_context: Optional[int],
    tokenize_max_model_len: Optional[int],
    budget: int,
) -> tuple[int, str]:
    """Resolve the context window and report which source won.

    Precedence: a positive *lobes_context* (the lobes gateway's reported
    context length for the resolved model) wins first; else a positive
    *tokenize_max_model_len* (the vLLM ``/tokenize`` endpoint's reported
    ``max_model_len``, the c11 carve-out); else *budget* — the caller's
    already-resolved ``COLLEAGUE_CONTEXT_BUDGET`` fallback (this function
    does not re-read the env var itself; the caller supplies the resolved
    value so this stays a pure function of its arguments).

    Returns ``(window, source)`` where *source* is one of
    ``"lobes_context"``, ``"tokenize_max_model_len"``, or ``"context_budget"``.
    A non-positive or non-numeric candidate is treated as absent and falls
    through to the next rung.
    """
    if isinstance(lobes_context, int) and not isinstance(lobes_context, bool) and lobes_context > 0:
        return lobes_context, "lobes_context"
    if (
        isinstance(tokenize_max_model_len, int)
        and not isinstance(tokenize_max_model_len, bool)
        and tokenize_max_model_len > 0
    ):
        return tokenize_max_model_len, "tokenize_max_model_len"
    return budget, "context_budget"


# ---------------------------------------------------------------------------
# seat_ceiling (colleague-side addition: per-seat output ceiling)
# ---------------------------------------------------------------------------


def _read_int_env(name: str) -> Optional[int]:
    """Read an int env var; ``None`` if unset OR unparseable (never raises)."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def seat_ceiling(seat: str) -> Optional[int]:
    """Resolve the output-token ceiling for a named seat.

    *seat* must be one of :data:`colleague.effort.SEAT_TABLE`'s keys
    (``cortex``, ``worker``, ``deepthink``, ``evaluator``, ``senses``,
    ``design``) — the same seat vocabulary the thinking-effort ladder
    recognises, never a second drifting list.

    - ``COLLEAGUE_MAX_OUTPUT_TOKENS=0`` is the global kill-switch: returns
      ``None`` (no clamp) for ANY seat, regardless of the design knob below.
    - The two high-ceiling seats (:data:`DESIGN_SEATS` — ``deepthink`` and
      ``design``) resolve ``COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN``, default
      :data:`DEFAULT_DESIGN_OUTPUT_CEILING` (131072).
    - Every other (acting) seat resolves a non-zero
      ``COLLEAGUE_MAX_OUTPUT_TOKENS`` if set, else :data:`OUTPUT_TOKEN_CEILING`
      (64000).

    Raises :class:`ValueError` naming the valid seats if *seat* is not a
    recognised :data:`colleague.effort.SEAT_TABLE` key.
    """
    if seat not in SEAT_TABLE:
        valid = ", ".join(sorted(SEAT_TABLE))
        raise ValueError(f"unknown seat {seat!r}; expected one of: {valid}")

    kill_switch = _read_int_env(_MAX_OUTPUT_TOKENS_ENV)
    if kill_switch == 0:
        return None

    if seat in DESIGN_SEATS:
        design = _read_int_env(_MAX_OUTPUT_TOKENS_DESIGN_ENV)
        if design is not None:
            return design
        return DEFAULT_DESIGN_OUTPUT_CEILING

    if kill_switch is not None and kill_switch > 0:
        return kill_switch
    return OUTPUT_TOKEN_CEILING

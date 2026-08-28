"""``config show`` lines for the adopt-from-qwen-code harness knobs (plan t20, c43).

Split out of ``colleague/cli/_commands/config.py`` (file-length ratchet):
that module calls :func:`config_show_lines` once. Renders the per-seat
``max_tokens`` ceilings the clamp will apply (:mod:`colleague.outputclamp`,
plan t3/t16) and the context window the clamp is measured against, naming
the source that won — the lobes-advertised cortex context when the
resolution rung stamped ``EngineConfig.lobes_context`` (t20 closes deviation
d15), else the configured budget. A live run may still upgrade the window
from the run-start ``/tokenize`` probe (:mod:`colleague.tokenestimate`);
``config show`` reports what is knowable before a run.
"""

from __future__ import annotations

from typing import Any

from colleague import effort, outputclamp

#: Seats whose ceiling ``config show`` names, in render order.
_SEATS: tuple[str, ...] = ("cortex", "worker", "deepthink", "design")


def window_line(cfg: Any) -> tuple[int, str]:
    """``(window, source)`` as :func:`colleague.outputclamp.resolve_window` sees it pre-run."""
    return outputclamp.resolve_window(
        getattr(cfg, "lobes_context", None), None, int(getattr(cfg, "context_budget_tokens", 0))
    )


def config_show_lines(lines: list[str], cfg: Any) -> dict[str, Any]:
    """Append the ``max_tokens`` + ``window`` lines to *lines*; return the JSON fragment."""
    ceilings = {
        seat: outputclamp.seat_ceiling(seat) for seat in _SEATS if seat in effort.SEAT_TABLE
    }
    if all(value is None for value in ceilings.values()):
        lines.append("max_tokens:             off (COLLEAGUE_MAX_OUTPUT_TOKENS=0 — no clamp)")
    else:
        rendered = " ".join(f"{seat}={value}" for seat, value in ceilings.items())
        lines.append(f"max_tokens:             {rendered} (clamped to the window per turn)")
    window, source = window_line(cfg)
    lines.append(f"window:                 {window} ({source})")
    return {"max_tokens": ceilings, "window": {"tokens": window, "source": source}}

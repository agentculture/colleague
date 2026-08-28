"""Design call-site thinking-effort seat builder (#416 t6, spec c14/h9).

One-shot design/planning call sites — the plan spec/plan/workforce stages,
auto-split, the fill-line split decision, and subagent decomposition —
reason about STRUCTURE rather than write code, and default to heavier
effort than the steady-state seats (:mod:`colleague.effort`'s
``DESIGN_SITE_TABLE``, v3 c36/c40). This module is the seat-CONFIG builder
consuming that table — kept separate from :mod:`colleague.effort` (the pure
ladder/table module owned by t1) per the plan's instruction.

Unlike :mod:`colleague.deepthink`/:mod:`colleague.senses` (which switch
``model``/``base_url`` to a DIFFERENT declared endpoint), a design seat
ALWAYS stays on the cortex/acting seat's own model/base_url — a design call
reasons harder about the same task, it does not need a different model, only
a heavier ``reasoning_effort_seat`` rung.
"""

from __future__ import annotations

import dataclasses
from typing import cast

from colleague import effort
from colleague.cli._errors import EXIT_USER_ERROR, CliError
from colleague.config import EngineConfig

#: The closed set of one-shot design/planning call sites (c14/h9). Adding a
#: call site means editing this constant (and
#: :data:`colleague.effort.DESIGN_SITE_TABLE`) — never passing a literal
#: effort string at a new call site (the guard
#: ``tests/test_design_call_site.py`` pins this).
DESIGN_CALL_SITES = frozenset(
    {
        "plan.spec_stage",
        "plan.plan_stage",
        "plan.workforce",
        "autosplit",
        "fillline.split",
        "subagents.decompose",
    }
)


def design_effort(site: str) -> str:
    """Return the :data:`colleague.effort.DESIGN_SITE_TABLE` rung for *site*.

    Raises :class:`CliError` naming the closed site set when *site* isn't a
    recognized design call site (c14/h9).
    """
    if site not in DESIGN_CALL_SITES:
        allowed = ", ".join(sorted(DESIGN_CALL_SITES))
        raise CliError(
            EXIT_USER_ERROR,
            f"unknown design call site {site!r} — must be one of: {allowed}",
            f"pass one of: {allowed}",
        )
    return effort.DESIGN_SITE_TABLE[site]


def design_seat_config(config: EngineConfig, site: str) -> EngineConfig:
    """Build the design seat's ``EngineConfig`` for *site* (#416 t6, c14/h9).

    Stays on the cortex/acting seat's OWN model/base_url — mirrors the other seat
    builders' shape (deepthink/senses/tae_loop.build_seat): ``dataclasses.replace`` clears
    the per-call knobs a fresh seat must not inherit
    (``on_delta``/``refresh_seat``), then ``setattr`` the plain
    ``reasoning_effort_seat`` attribute that ``vllm_openai._effort_for``
    honors ahead of the acting seat's resolved rung. The c32 precedence
    order still applies: an explicit ``reasoning_effort_seats["design"]``
    override, or the global kill switch (``reasoning_effort == "default"``),
    wins over the design-site table.
    """
    seat = cast(
        EngineConfig,
        dataclasses.replace(config, on_delta=None, refresh_seat=None),
    )
    setattr(
        seat,
        "reasoning_effort_seat",
        effort.resolve_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=config.reasoning_effort_seats.get("design"),
            site=site,
        ),
    )
    setattr(seat, "output_seat", "design")  # t16: the high output ceiling (c48)
    return seat

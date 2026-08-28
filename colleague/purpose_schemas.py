"""Purpose tools — the six typed delegation tools (spec
``docs/specs/2026-08-28-purpose-tools-associate-seat.md``, plan task t4).

This module is the single source of truth for the purpose tool NAMES. Plan
task t9 (covers c7/h7) imports :data:`PURPOSE_TOOL_NAMES` into
``scripts/compare_arms.py`` so the measurement harness counts purpose steps
in the ``delegations`` / ``associate_calls`` columns without duplicating the
list. The schemas, ``PURPOSE_ROLE`` table, hidden-state rule and brief
templates land here in t4; the executor wiring in t6.
"""

from __future__ import annotations

#: The six purpose tool names, in spec order. ``web_survey`` and
#: ``code_survey`` run a scout child (the associate seat when armed);
#: ``review``/``validate``/``plan`` run a reviewer/validator/planner child on
#: cortex; ``handover_to_colleague`` is the writer purpose that replaces
#: subagent/subagents on the top-level acting surface.
PURPOSE_TOOL_NAMES: tuple[str, ...] = (
    "web_survey",
    "code_survey",
    "review",
    "validate",
    "plan",
    "handover_to_colleague",
)

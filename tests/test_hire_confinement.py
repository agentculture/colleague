"""Plan t11 (``delegation-follow-ups-a7-p3-hire``, covers c41/h25, c37/h21,
c19/h10): the hire pair never leaks below the acting seat.

Three confinement walls, each pinned here or in the named sibling files:

1. **Children** — :func:`colleague.actingsurface.strip_child_forbidden_tools`
   strips :data:`colleague.hire_schemas.HIRE_TOOL_NAMES` at depth >= 1, so a
   spawned child (a hire included) can never hire or assign — authority ⊆
   hirer by construction.
2. **Agents-mode tool sets** — ``colleague.agents.tools`` holds the pair
   knob-guarded (``COLLEAGUE_HIRE``) and never-inheritable (additions in
   ``tests/test_agents_tools.py``).
3. **The batch pool** — neither name is in
   :data:`colleague.toolbatch.CONCURRENCY_SAFE_TOOLS` (an allow-list: no
   change to ``toolbatch.py`` was needed; the test pins the exclusion), and a
   mixed batch runs the hire/assign step outside the pool in request order
   (``tests/test_toolbatch.py`` / ``tests/test_toolbatch_loop.py``).
"""

from __future__ import annotations

from dataclasses import replace

from colleague import actingsurface, toolbatch
from colleague.config import EngineConfig
from colleague.hire_schemas import HIRE_TOOL_NAMES
from colleague.roles import BUILTIN_ROLES
from colleague.tools import curate_schemas

# ---------------------------------------------------------------------------
# Acceptance 1 — strip_child_forbidden_tools strips HIRE_TOOL_NAMES at
# depth >= 1; a depth-1 curate_for_depth surface shows neither name.
# ---------------------------------------------------------------------------


def test_strip_child_forbidden_tools_removes_the_hire_pair() -> None:
    writer = BUILTIN_ROLES["writer"]
    # The writer allow-list carries the pair unconditionally (roles t10 —
    # hidden-state gates the offer); the strip must remove it anyway.
    assert set(HIRE_TOOL_NAMES) <= set(writer.tool_allowlist)
    stripped = actingsurface.strip_child_forbidden_tools(writer)
    assert set(stripped.tool_allowlist).isdisjoint(HIRE_TOOL_NAMES)


def test_strip_removes_the_pair_even_off_an_adversarial_allowlist() -> None:
    """Allow-list-independent: a role that explicitly carries both names
    (however it got them) still loses them at the child seam."""
    scout = BUILTIN_ROLES["scout"]
    armed = replace(scout, tool_allowlist=scout.tool_allowlist + HIRE_TOOL_NAMES)
    stripped = actingsurface.strip_child_forbidden_tools(armed)
    assert set(stripped.tool_allowlist).isdisjoint(HIRE_TOOL_NAMES)
    # The rest of the scout surface is untouched.
    assert set(stripped.tool_allowlist) == set(scout.tool_allowlist) - set(HIRE_TOOL_NAMES)


def test_depth_one_curate_for_depth_shows_neither_hire_name() -> None:
    """Even with ``config.hire`` armed, a depth-1 child's curated surface —
    allow-list AND rendered schemas — carries neither hire name."""
    config = EngineConfig(hire=True)
    setattr(config, actingsurface.CHILD_DEPTH_ATTR, 1)
    role = actingsurface.curate_for_depth(BUILTIN_ROLES["writer"], config)
    assert set(role.tool_allowlist).isdisjoint(HIRE_TOOL_NAMES)
    offered = {s["function"]["name"] for s in curate_schemas(role, config=config)}
    assert offered.isdisjoint(HIRE_TOOL_NAMES)


def test_depth_one_roleless_child_shows_neither_hire_name() -> None:
    config = EngineConfig(hire=True)
    setattr(config, actingsurface.CHILD_DEPTH_ATTR, 1)
    role = actingsurface.curate_for_depth(None, config)
    assert role is not None  # the bounded-writer default, never the raw surface
    assert set(role.tool_allowlist).isdisjoint(HIRE_TOOL_NAMES)


def test_depth_zero_armed_seat_still_offers_the_pair() -> None:
    """The contrast pin: the strip is a CHILD wall, not a second off-knob —
    the armed top-level acting seat keeps both schemas."""
    config = EngineConfig(hire=True)
    role = actingsurface.curate_for_depth(None, config)
    offered = {s["function"]["name"] for s in curate_schemas(role, config=config)}
    assert set(HIRE_TOOL_NAMES) <= offered


# ---------------------------------------------------------------------------
# Acceptance 3 (the allow-list half) — CONCURRENCY_SAFE_TOOLS never holds the
# pair. toolbatch.py itself is unchanged: the set is an allow-list, so the
# pin here is what keeps a future entry an explicit, reviewed decision.
# ---------------------------------------------------------------------------


def test_hire_pair_never_in_the_batch_pool_allowlist() -> None:
    assert frozenset(HIRE_TOOL_NAMES).isdisjoint(toolbatch.CONCURRENCY_SAFE_TOOLS)
    for name in HIRE_TOOL_NAMES:
        assert toolbatch.is_tool_call_concurrency_safe(name, {}) is False

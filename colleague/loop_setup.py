"""Run setup: role resolution, curated schemas, the first user message, and the
collaborator defaults.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
``resolve_role`` / ``curated_schemas`` stay importable from ``colleague.loop``
(the engines and ``colleague/actingsurface.py`` reach them by that name).
``_build_user_message`` is re-exported into the loop's namespace on purpose:
its caller ``_build_initial_content`` lives in ``colleague/loop.py``, so the
existing object-form patches on ``loop_module._build_user_message`` still bite.
A pure move.
"""

from __future__ import annotations

from typing import Any

from colleague.agents import runtime as _agents_runtime
from colleague.contract import Task
from colleague.loop_types import ContextControls, Spawns
from colleague.tools import ToolExecutor


def resolve_role(config, repo_path: str):
    """Resolve ``config.role`` to a :class:`~colleague.roles.Role` for the
    top-level acting seat; ``None`` only for an unknown role NAME (#t4).

    Runtime-owned so every backend types a child identically (all-engines rule):
    both bundled engines call this in ``work()`` to build the child's curated tool
    schema (``curate_schemas(role)``) and a role-aware ``ToolExecutor``
    (``allowlist=role``). The final :func:`colleague.actingsurface.curate_for_depth`
    call is the depth-aware seam (d14 bare-role fix, q9 child purpose-tool strip);
    the PROMPT is composed separately by :meth:`colleague.engine.Engine.system_prompt`.
    """
    name = getattr(config, "role", None)
    role = None
    if name:
        from colleague.roles import load_role

        role = load_role(name, repo_path, config.model)
    # Model-bound agents (#411 t15): a NARROWER purpose narrows the role through
    # the SAME value both halves consume — curate_schemas (offered) and
    # ToolExecutor(allowlist=) (refused) — so e.g. the worker is never offered
    # write_file/edit_file and is refused if it calls them anyway. A purpose
    # equal to TOOL_NAMES is a no-op (byte-identical, pre-t5 default).
    if getattr(config, "agents", False):
        from colleague.agents.tools import PURPOSE_TOOLS
        from colleague.tools import TOOL_NAMES, narrow_role_by_tool_set

        purpose = getattr(config, "agents_profile", None) or _agents_runtime.DEFAULT_ACTING_PURPOSE
        purpose_tools = PURPOSE_TOOLS.get(purpose)
        # Strict inequality, not subset (plan t5): a purpose surface may hold
        # names outside TOOL_NAMES (the six purpose tools) while still narrowing.
        if purpose_tools is not None and set(purpose_tools) != set(TOOL_NAMES):
            # An EMPTY purpose surface (the tools-off talker) means NO tools, not
            # "no narrowing" (narrow_role_by_tool_set's empty-tool_set sentinel,
            # c26, would otherwise fall through to the FULL surface) — build it.
            role = (
                _tools_off_role(purpose)
                if not purpose_tools
                else narrow_role_by_tool_set(role, tuple(sorted(purpose_tools)))
            )
    from colleague.actingsurface import curate_for_depth

    return curate_for_depth(role, config)


def curated_schemas(role, config, *, deepthink: bool = False) -> list[dict[str, Any]]:
    """Tool schemas offered to *role* under *config*, armed-facts applied (t8).

    ``curate_schemas(role)`` with :func:`colleague.delegation_text.apply_armed_facts`
    spliced on top — unarmed is byte-identical to the pre-t8 curated list.
    """
    from colleague.delegation_text import apply_armed_facts
    from colleague.tools import curate_schemas

    return apply_armed_facts(curate_schemas(role, deepthink=deepthink, config=config), config)


def _tools_off_role(purpose: str):
    """A role whose curated surface is EMPTY — the tools-off seat (#411).

    ``curate_schemas`` offers nothing for it and ``ToolExecutor(allowlist=…)``
    refuses every name, so a tools-off purpose provably cannot reach a tool.
    Read-only by construction: a seat with no tools can mutate nothing.
    """
    from colleague.roles import Role

    return Role(
        name=purpose,
        prompt_fragment="",
        tool_allowlist=(),
        skill_subset=None,
        read_only=True,
    )


def _build_user_message(task: Task) -> str:
    """Compose the first user turn from the instruction + optional context/constraints.

    Extracted from :func:`run` (a pure string build, no behavior change) so that
    function's cognitive complexity stays within budget.
    """
    user = task.instruction
    if task.context:
        user += f"\n\nContext:\n{task.context}"
    if task.constraints:
        user += "\n\nConstraints:\n" + "\n".join(f"- {c}" for c in task.constraints)
    # Goal block (t15 / spec R6 / #259): a task that declares its goal/acceptance
    # carries them as a DISTINCT block, so `finish` has a concrete target (#231)
    # instead of re-deriving intent from prose. Absent fields → byte-identical.
    if task.goal:
        user += f"\n\nGoal:\n{task.goal}"
    if task.acceptance:
        user += (
            "\n\nAcceptance criteria (the work is done when each of these holds):\n"
            + "\n".join(f"- {c}" for c in task.acceptance)
        )
    return user


def _resolve_run_collaborators(
    spawns: Spawns | None,
    context: ContextControls | None,
    executor: ToolExecutor | None,
    task: Task,
) -> tuple[Spawns, ContextControls, ToolExecutor]:
    """Default the three run-scoped collaborators (spawns/context/executor) when a
    caller didn't inject them. Kept out of ``run()`` so the per-field ``or``
    defaults don't inflate its cognitive complexity (mirrors
    ``_resolve_runtime_defaults``). Byte-identical to the inline defaulting:
    ``executor`` defaults to one confined to ``task.repo_path`` and wired to the
    resolved ``spawns``."""
    _spawns = spawns or Spawns()
    _context = context or ContextControls()
    _executor = executor or ToolExecutor(
        task.repo_path, spawn=_spawns.single, batch_spawn=_spawns.batch
    )
    return _spawns, _context, _executor

"""The ``assign_to_colleague`` handler + the run's hires block (plan t13).

``delegation-follow-ups-a7-p3-hire`` spec c38 / honesty h22: assigning one
scoped task to a live hire spawns ONE child through the executor's injected
spawn callable — the SAME seam every purpose tool uses
(:func:`colleague.purpose_schemas.dispatch`) — with the hire's base role, the
role's fixed rung (:data:`colleague.effort.ROLE_TABLE`), the read-only budget
exemption (``charges_budget = not roles.is_read_only(base)``), and the parent's
remaining web budget (:func:`colleague.webbudget.remaining_for_child`). The
child's result folds back through :func:`colleague.purpose_schemas._record`
and renders through :func:`colleague.purpose_schemas._render` — never a
duplicated fold — so an assignment result looks exactly like a purpose result,
``urls fetched:`` block included.

**How the hired prompt reaches the child (the seam finding, t13).** The plan's
literal ``role=hired_role(hire)`` would pass a :class:`colleague.roles.Role`
OBJECT where the spawn path accepts only a role NAME: ``run_subagent`` copies
``role`` verbatim onto the child ``EngineConfig.role`` and onto
``SubResult.role`` (a non-JSON object in the artifact), and the child's
``loop.resolve_role`` hands it to :func:`colleague.roles.load_role`, whose
bare-identifier check (``name.replace("_", "").replace("-", "").isalnum()``)
rejects an object outright — returning ``None``, which means the FULL surface,
silently widening the child. So this handler passes ``role=hire.base_role``
(the name — allow-list, read-only flag and effort all stay the base's, exactly
the prompt-never-grants rule) and carries the authored
``Hire.prompt_fragment`` through the one existing seam that reaches the
child's model without widening :mod:`colleague.subagents`: the assignment
BRIEF (the child's ``Task.instruction``), which opens with the authored
standing prompt verbatim. ``colleague/subagents.py`` is untouched.

The t12 composition seam: the run's roster is the lazily-created
``executor.hire_roster`` attribute ``colleague/hire_dispatch.py`` (t12, a
concurrent task) exposes; this module reads it via ``getattr`` and creates a
plain :class:`colleague.hire.Roster` under the SAME name when absent, so the
handler works standalone and composes unchanged at merge. Assignments land on
a sibling ``executor.hire_assignments`` dict (``agent_id -> list of
{task_id, status, changed_files}``); :func:`hires_block` folds roster +
assignments into the ``TaskResult.hires`` artifact block — each entry the
Hire's ``to_dict`` (the authored prompt TEXT rides the artifact; the ledger
carries only its digest) plus its ``assignments`` list.

Discipline mirrors :mod:`colleague.purpose_schemas`: no worktree/subprocess
machinery, no imports from :mod:`colleague.loop`; :mod:`colleague.tools` and
:mod:`colleague.roles` are imported lazily (both sit above/beside this module
in the import graph).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from colleague import purpose_schemas, webbudget
from colleague.effort import ROLE_TABLE

__all__ = [
    "TOOL_NAME",
    "assignment_brief",
    "dispatch",
    "hires_block",
]

#: The one tool this module handles (its schema lives in
#: :data:`colleague.hire_schemas.HIRE_SCHEMAS`; ``hire_colleague``'s handler
#: is t12's :mod:`colleague.hire_dispatch` — file-disjoint in the same wave).
TOOL_NAME = "assign_to_colleague"

#: The live status a hire must hold to be assignable (``colleague.hire.STATUSES``).
_LIVE = "live"


def assignment_brief(hire: Any, arguments: dict[str, Any]) -> str:
    """The child's brief: the authored standing prompt, then the scoped task.

    The ``prompt_fragment`` opens the brief VERBATIM — this is the documented
    seam that carries the hired prompt to the child (see the module
    docstring). The acceptance list renders exactly like a purpose brief's
    list block, and the brief closes with the fixed scope-containment
    sentence (the ``handover_to_colleague`` precedent — the task text is the
    model's own, so the boundary is fixed prose, not trust).
    """
    lines: list[str] = []
    if hire.prompt_fragment:
        lines.append(hire.prompt_fragment)
        lines.append("")
    lines.append(f"Assignment: {arguments.get('task', '')}")
    lines.extend(purpose_schemas._list_block("Acceptance criteria:", arguments.get("acceptance")))
    lines.append("Report what you did and stay within this assignment's scope.")
    return "\n".join(lines)


def _roster(executor: Any) -> Any:
    """The run's roster — t12's ``executor.hire_roster`` when present, else a
    lazily-created local :class:`colleague.hire.Roster` under the SAME name."""
    roster = getattr(executor, "hire_roster", None)
    if roster is None:
        from colleague.hire import Roster  # lazy: standalone fallback only

        roster = Roster()
        executor.hire_roster = roster
    return roster


def _record_assignment(executor: Any, agent_id: str, sub: Any) -> None:
    """Append one finished assignment under *agent_id* on the executor."""
    assignments = getattr(executor, "hire_assignments", None)
    if assignments is None:
        assignments = {}
        executor.hire_assignments = assignments
    assignments.setdefault(agent_id, []).append(
        {
            "task_id": sub.task_id,
            "status": sub.status,
            "changed_files": list(sub.changed_files),
        }
    )


def hires_block(executor: Any) -> list[dict[str, Any]]:
    """The ``TaskResult.hires`` artifact block for this run.

    Every roster entry — assigned or not — as the Hire's ``to_dict`` (the
    authored prompt TEXT included, h22/c38: the artifact carries the text, the
    ledger only its digest) plus an ``assignments`` list of
    ``{task_id, status, changed_files}`` per finished assignment, in
    assignment order. Empty (→ the omit-when-empty artifact key) when no
    roster exists or it holds no hires.
    """
    roster = getattr(executor, "hire_roster", None)
    if roster is None:
        return []
    assignments = getattr(executor, "hire_assignments", None) or {}
    return [
        {
            **hire.to_dict(),
            "assignments": [dict(a) for a in assignments.get(hire.agent_id, [])],
        }
        for hire in roster
    ]


def dispatch(executor: Any) -> dict[str, Callable[[dict[str, Any]], Any]]:
    """The ``assign_to_colleague`` handler, bound to *executor* (t13).

    Mirrors :func:`colleague.purpose_schemas.dispatch`'s handler shape: a
    refused launch (depth cap, agent budget, engine error) comes back as the
    tool RESULT text — one readable step, never a crashed drive; an unknown or
    non-live ``agent_id`` returns ``no live hire: <id>`` the same way.
    """
    from colleague.tools import ToolError, ToolOutcome  # local: avoids the import cycle

    def handler(arguments: dict[str, Any]) -> Any:
        for key in ("agent_id", "task"):
            value = arguments.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ToolError(f"{TOOL_NAME} requires a non-empty '{key}' string")
        agent_id = arguments["agent_id"]
        hire = _roster(executor).get(agent_id)
        if hire is None or hire.status != _LIVE:
            return ToolOutcome(result=f"no live hire: {agent_id}")
        spawn = getattr(executor, "_spawn", None)
        if spawn is None:
            raise ToolError(f"'{TOOL_NAME}' is not available in this drive")
        from colleague import roles  # lazy: colleague.roles sits above this module

        # No per-purpose step row for an assignment (it rides the caller's own
        # budget, the handover_to_colleague stance) — the exhausted-marker N is
        # the caller's budget, 0 when the executor carries none.
        steps = int(getattr(executor, "max_steps", 0) or 0)
        try:
            sub = spawn(
                assignment_brief(hire, arguments),
                engine=None,
                model=None,
                role=hire.base_role,  # the NAME — see the module docstring
                effort=ROLE_TABLE[hire.base_role],
                max_steps=None,
                charges_budget=not roles.is_read_only(hire.base_role),
                web_calls_remaining=webbudget.remaining_for_child(executor),
                purpose=TOOL_NAME,
            )
        except Exception as exc:  # refusal/launcher error -> a readable result
            return ToolOutcome(result=executor._truncate(f"{TOOL_NAME} refused: {exc}", TOOL_NAME))
        purpose_schemas._record(executor, arguments, sub)
        _record_assignment(executor, agent_id, sub)
        return ToolOutcome(
            result=executor._truncate(purpose_schemas._render(TOOL_NAME, sub, steps), TOOL_NAME)
        )

    return {TOOL_NAME: handler}

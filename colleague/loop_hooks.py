"""Hook firing: run every matching hook for one lifecycle event, in order.

Extracted from ``colleague/loop.py`` (plan hard-1000-line-file-limit, t15).
The hook subprocess runner is a PARAMETER, not an import: ``colleague/loop.py``
keeps the thin :func:`colleague.loop._fire_hooks` binding, which passes its own
``run_hook`` global, so the long-standing override seam on
``colleague.loop.run_hook`` still intercepts every firing. A pure move.
"""

from __future__ import annotations

from typing import Any, Callable

from colleague.contract import DECISION_DENY, DECISION_REWRITE, HookFiring, Task, TaskResult
from colleague.hooks import HookConfig, HookDecision, hook_approval_verdict
from colleague.policy import Policy


def fire_hooks(
    hooks: HookConfig,
    result: TaskResult,
    *,
    event: str,
    task: Task,
    runner: "Callable[..., HookDecision]",
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    policy: Policy | None = None,
) -> HookDecision | None:
    """Run every matching hook for *event*, record a firing per hook, in order.

    Returns the first control-bearing :class:`HookDecision` (a ``deny`` or
    ``rewrite``) seen, or ``None``. Only ``pre_tool`` callers act on the return;
    for the observe-only events (``task_start`` / ``post_tool`` / ``finish``) the
    caller ignores it. ``allow`` / ``observe`` decisions are recorded but never
    control-bearing, so scanning continues past them.

    ``runner`` is the hook subprocess runner — :func:`colleague.hooks.run_hook`,
    passed in by :func:`colleague.loop._fire_hooks` so that it resolves through
    the LOOP module's namespace at call time. An override of
    ``colleague.loop.run_hook`` therefore still intercepts every firing, exactly
    as it did before the split.

    A firing is appended for *every* hook that runs — including the allow/observe
    ones leading up to a decisive one — so the run report sees the full sequence.

    When *policy* is given and its ``hooks`` section is present, each entry's
    command is checked via :func:`~colleague.hooks.hook_approval_verdict` before
    being run.  An unapproved entry is recorded as a ``HookFiring(decision=
    "skipped")`` and skipped — it does NOT set the decisive deny/rewrite and does
    NOT block the tool for ``pre_tool``.  With no ``hooks`` section (the default)
    every entry fires exactly as before (strict no-op).
    """
    entries = hooks.hooks_for(event, tool=tool)
    if not entries:
        return None

    payload = {
        "event": event,
        "tool": tool,
        "arguments": arguments,
        "task_id": task.id,
        "repo_path": task.repo_path,
    }

    decisive = None
    for entry in entries:
        # --- Content-approval gate (r1) ---
        # Check the hook's referenced repo files against the policy before running.
        # A skip is NON-control-bearing: it does NOT set decisive and does NOT
        # block the tool for pre_tool.  With no hooks section this is a strict no-op.
        if policy is not None:
            approval = hook_approval_verdict(entry.command, policy, task.repo_path)
            if not approval.allowed:
                result.hook_firings.append(
                    HookFiring(
                        event=event,
                        tool=tool,
                        command=entry.command,
                        decision="skipped",
                        exit_code=None,
                        reason=approval.reason,
                    )
                )
                continue

        # A hook must never abort the work item. The runner already maps timeouts /
        # launch failures to a deny; this net catches any other unexpected error
        # and records it as a fail-closed deny firing rather than propagating.
        try:
            decision = runner(entry, payload, cwd=task.repo_path)
        # BLE001 justified: fail-closed — any hook error becomes a deny (see the
        # note above), never propagated, so a crashing hook cannot abort the work item.
        except Exception as exc:  # noqa: BLE001
            decision = HookDecision(
                decision=DECISION_DENY, reason=f"hook error: {exc}", exit_code=None
            )
        result.hook_firings.append(
            HookFiring(
                event=event,
                tool=tool,
                command=entry.command,
                decision=decision.decision,
                exit_code=decision.exit_code,
                reason=decision.reason,
            )
        )
        # The first deny/rewrite wins; allow/observe are non-decisive — keep going.
        if decisive is None and decision.decision in (DECISION_DENY, DECISION_REWRITE):
            decisive = decision
            # A decisive pre_tool verdict short-circuits the rest of the chain.
            if event == "pre_tool":
                break
    return decisive

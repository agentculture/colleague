"""The subagent launcher — a nested in-process child drive, depth-bounded.

Mid-drive, an engine can delegate a scoped sub-task to a NESTED child drive on a
chosen engine/model. This module is the launcher: it runs that child drive and
returns its :class:`~colleague.contract.SubResult`.

A child drive is exactly *a drive without handoff*. The git/PR handoff lives only
in the CLI ``execute_drive`` path, never in :meth:`Engine.drive` — so calling
``engine.drive(child_task, child_config)`` runs the bounded tool-loop and returns
a uniform ``TaskResult`` with **no** branch, commit, or PR side effects. The
launch is SYNCHRONOUS: a plain function call — no thread, process, asyncio, or
socket (the no-socket/no-daemon convention holds).

Termination is structural. ``run_subagent`` checks the depth cap *first, before
any work*: a child at ``depth > MAX_SUBAGENT_DEPTH`` is refused before its drive
ever starts, so there is no unbounded recursion and no growing call stack. Each
child is handed its OWN spawn callback bound to ``depth + 1`` (via
:func:`make_spawn`), so the bound is carried down every level once the loop wires
it.

The engine/model switch is pure configuration: ``run_subagent`` resolves the
child engine by name through :func:`colleague.registry.load` and inherits the
parent's :class:`~colleague.config.EngineConfig` with only the model overridden
(``dataclasses.replace``). No engine's own code is touched — selecting a
different model is a config-level switch, exactly the contract Colleague
promises.
"""

from __future__ import annotations

import dataclasses
from typing import Callable, Optional, cast

from colleague import registry
from colleague.config import MAX_SUBAGENT_DEPTH, EngineConfig
from colleague.contract import SubResult, Task

#: A spawn callback: ``spawn(instruction, engine=None, model=None) -> SubResult``.
#: Bound to a repo/parent-config/parent-engine/depth by :func:`make_spawn` and
#: assigned to ``EngineConfig.subagent_spawn`` so the loop can offer delegation.
SpawnFn = Callable[[str, Optional[str], Optional[str]], SubResult]


class SubagentError(Exception):
    """A subagent launch was refused — e.g. the depth cap was exceeded."""


def make_spawn(
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int = 1,
) -> SpawnFn:
    """Build a depth-bound spawn callback over :func:`run_subagent`.

    The returned closure captures ``repo_path``, ``parent_config``,
    ``parent_engine``, and this ``depth`` (the nesting level of the child it will
    launch — top-level children are ``depth=1``). The loop wiring (t6) calls
    ``make_spawn(task.repo_path, config, task.engine)`` (depth defaults to 1) and
    assigns the result to ``config.subagent_spawn``; the tool executor (t4) then
    calls ``spawn(instruction, engine, model)`` per delegation.

    Each launched child is itself handed a spawn callback bound to ``depth + 1``
    inside :func:`run_subagent`, so the recursion bound is carried down every
    level structurally.
    """

    def spawn(
        instruction: str,
        engine: Optional[str] = None,
        model: Optional[str] = None,
    ) -> SubResult:
        return run_subagent(
            instruction,
            repo_path=repo_path,
            parent_config=parent_config,
            parent_engine=parent_engine,
            depth=depth,
            engine=engine,
            model=model,
        )

    return spawn


def run_subagent(
    instruction: str,
    *,
    repo_path: str,
    parent_config: EngineConfig,
    parent_engine: str,
    depth: int,
    engine: Optional[str] = None,
    model: Optional[str] = None,
) -> SubResult:
    """Run one nested child drive and return its :class:`SubResult`.

    ``depth`` is the nesting level of THIS child (top-level children = 1). The
    cap is enforced *first, before any work*: a child past
    :data:`~colleague.config.MAX_SUBAGENT_DEPTH` is refused before its drive
    starts, guaranteeing termination.

    The child engine is ``engine or parent_engine``, resolved through
    :func:`colleague.registry.load`. The child config inherits the parent's
    unchanged except the model, which switches to ``model`` when provided
    (otherwise inherits the parent's) — a pure config-level switch with no engine
    code change. The child is given its own ``subagent_spawn`` bound to
    ``depth + 1`` so it can delegate further, still bounded.

    The drive runs via ``engine.drive`` — the bounded loop, **no** git handoff,
    fully synchronous.
    """
    # (a) Depth cap FIRST — before loading an engine or building any config, so a
    # refused level does zero work and starts no child drive. This is what makes
    # the recursion provably terminating.
    if depth > MAX_SUBAGENT_DEPTH:
        raise SubagentError(f"subagent depth limit ({MAX_SUBAGENT_DEPTH}) exceeded")

    # (b) Resolve + load the child engine by name. A bad name surfaces as a clean
    # SubagentError (never an unrelated crash upstream).
    child_engine = engine or parent_engine
    try:
        eng = registry.load(child_engine)
    except registry.UnknownEngine as exc:
        raise SubagentError(str(exc)) from exc

    # (c) Inherit the parent's config, overriding ONLY the model when provided.
    # dataclasses.replace keeps base_url/api_key/max_steps/temperature/timeout
    # (and any future field) intact and leaves the parent object untouched. The
    # cast is purely for the static analyser: Sonar models replace()'s return as a
    # generic DataclassInstance, not EngineConfig, which would trip S5655/S5890.
    child_config = cast(
        EngineConfig,
        dataclasses.replace(parent_config, model=(model or parent_config.model)),
    )

    # (d) Give the child its OWN spawn callback bound to depth + 1 so it can
    # delegate further, still bounded. (The loop won't consume this until t6
    # wires it, but binding it now makes the recursion structurally bounded.)
    child_config.subagent_spawn = make_spawn(repo_path, child_config, child_engine, depth + 1)

    # (e) Build + run the nested child drive. engine.drive runs the bounded loop
    # and never hands off; the call is synchronous (no thread/process/socket).
    child_task = Task.new(repo_path, instruction, engine=child_engine)
    result = eng.drive(child_task, child_config)

    # (f) Project the child's TaskResult onto the nested-only SubResult shape.
    return SubResult(
        task_id=result.task_id,
        engine=child_engine,
        model=child_config.model,
        status=result.status,
        summary=result.summary,
        changed_files=list(result.changed_files),
        usage=result.usage,
    )

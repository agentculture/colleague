"""The engine protocol — the driver contract every coder backend implements.

An :class:`Engine` is the *driver* in the car metaphor: it knows how to invoke
and control one specific model, but it speaks the shared task contract on both
ends. Given a :class:`~colleague.contract.Task` and an
:class:`~colleague.config.EngineConfig`, it returns a
:class:`~colleague.contract.TaskResult` of the uniform shape.

Engines do not re-implement the agentic loop — they delegate to
:func:`colleague.loop.run` and only supply *how the model is called*
(a ``complete`` function). The repo, the tool set, and the step budget that the
loop needs are derived from the task (``repo_path``) and the config
(``max_steps``).
"""

from __future__ import annotations

import abc

from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult


class Engine(abc.ABC):
    """Abstract coder-engine driver. Subclasses implement :meth:`drive`."""

    #: Stable engine name; matches the entry-point name it registers under.
    name: str = "engine"

    @abc.abstractmethod
    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        """Execute ``task`` and return a uniform :class:`TaskResult`.

        Implementations build a tool executor for ``task.repo_path``, run the
        bounded loop with ``config.max_steps`` as the budget, and produce the
        same result shape regardless of the model underneath.
        """
        raise NotImplementedError

    def system_prompt(self, task: Task, config: EngineConfig) -> str | None:
        """Compose the model-specific system prompt (AGENTS + skills layers).

        Resolved here on the base class — not in each ``drive`` — so *every*
        engine wheel inherits the layered instruction injection for free (the
        all-engines rule), mirroring how hooks are inherited via the loop.
        Subclasses pass the return value as ``system_prompt=`` to
        :func:`colleague.loop.run`. Returns ``None`` when no AGENTS/skills
        layers exist for ``config.model``, so the loop falls back to its own
        default and behavior is byte-identical to a layer-free run.
        """
        # Imported lazily to keep this module's import surface minimal and avoid
        # pulling the whole loop in at engine import time.
        from colleague.layers import system_prompt_for
        from colleague.loop import _DEFAULT_SYSTEM

        return system_prompt_for(task.repo_path, config.model, base=_DEFAULT_SYSTEM)

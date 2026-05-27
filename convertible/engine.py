"""The engine protocol — the driver contract every coder backend implements.

An :class:`Engine` is the *driver* in the car metaphor: it knows how to invoke
and control one specific model, but it speaks the shared task contract on both
ends. Given a :class:`~convertible.contract.Task` and an
:class:`~convertible.config.EngineConfig`, it returns a
:class:`~convertible.contract.TaskResult` of the uniform shape.

Engines do not re-implement the agentic loop — they delegate to
:func:`convertible.loop.run` and only supply *how the model is called*
(a ``complete`` function). The repo, the tool set, and the step budget that the
loop needs are derived from the task (``repo_path``) and the config
(``max_steps``).
"""

from __future__ import annotations

import abc

from convertible.config import EngineConfig
from convertible.contract import Task, TaskResult


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

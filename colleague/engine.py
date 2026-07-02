"""The engine protocol — the adapter contract every coder backend implements.

An :class:`Engine` is the *adapter*: it knows how to invoke
and control one specific model, but it speaks the shared task contract on both
ends. Given a :class:`~colleague.contract.Task` and an
:class:`~colleague.config.EngineConfig`, it returns a
:class:`~colleague.contract.TaskResult` of the uniform shape.

Backends do not re-implement the agentic loop — they delegate to
:func:`colleague.loop.run` and only supply *how the model is called*
(a ``complete`` function). The repo, the tool set, and the step budget that the
loop needs are derived from the task (``repo_path``) and the config
(``max_steps``).
"""

from __future__ import annotations

import abc
import warnings
from typing import TYPE_CHECKING, Any, Callable

from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult

if TYPE_CHECKING:
    from colleague.loop import CompleteFn


class Engine(abc.ABC):
    """Abstract coder-engine driver. Subclasses implement :meth:`work`.

    Back-compat (drive→work, v0.37.0): the method was renamed from ``drive`` to
    ``work``. An out-of-tree backend that still implements the legacy ``drive``
    keeps working — :meth:`__init_subclass__` bridges a ``drive``-only subclass's
    ``work`` to its ``drive`` (with a ``DeprecationWarning`` at call time), and the
    base :meth:`drive` delegates to :meth:`work` so callers using the old method
    name still work. Plugin authors should rename their method to ``work``.
    """

    #: Stable engine name; matches the entry-point name it registers under.
    name: str = "engine"

    @abc.abstractmethod
    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        """Execute ``task`` and return a uniform :class:`TaskResult`.

        Implementations build a tool executor for ``task.repo_path``, run the
        bounded loop with ``config.max_steps`` as the budget, and produce the
        same result shape regardless of the model underneath.
        """
        raise NotImplementedError

    def drive(self, task: Task, config: EngineConfig) -> TaskResult:
        """Deprecated alias of :meth:`work` (renamed in v0.37.0).

        Kept so callers using the old method name still work; subclasses should
        override :meth:`work`. A legacy subclass that overrides ``drive`` instead
        is bridged by :meth:`__init_subclass__`.
        """
        return self.work(task, config)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # A pre-rename plugin that implements legacy ``drive`` but not ``work``:
        # alias ``work`` to its ``drive`` so it still satisfies the ABC and runs.
        if "work" not in cls.__dict__ and "drive" in cls.__dict__:
            legacy_drive = cls.__dict__["drive"]

            def _work_via_legacy_drive(
                self: "Engine", task: Task, config: EngineConfig, *, _legacy=legacy_drive
            ) -> TaskResult:
                warnings.warn(
                    f"{cls.__name__} implements Engine.drive(), which was renamed to "
                    "Engine.work() in v0.37.0; rename the method to work().",
                    DeprecationWarning,
                    stacklevel=2,
                )
                return _legacy(self, task, config)

            cls.work = _work_via_legacy_drive  # type: ignore[method-assign]

    def make_complete(
        self, config: EngineConfig, tools: "list[dict[str, Any]] | None" = None
    ) -> "CompleteFn":
        """Return a one-shot completion callable (``messages -> ModelResponse``).

        The bounded work loop builds its own ``complete`` inside :meth:`work`;
        this public seam exposes the same capability to features that need a
        direct model turn *outside* the loop — e.g. ``colleague plan``, where the
        backend proposes spec claims and plan items, or the dual-model
        ``deepthink`` escalation seam (:mod:`colleague.deepthink`, task t2). The
        default raises: a backend without a live model (the ``mock`` engine)
        inherits it, so plan mode requires a real backend. The all-engines rule
        holds at the contract level — every live backend exposes this identically.

        ``tools`` controls what tool schema (if any) is offered on the wire:
        ``None`` (the default) means *engine default* — for ``vllm-openai`` that
        is today's behavior, the full tool schema, so a caller that omits
        ``tools`` (e.g. plan mode) is byte-identical to before this parameter
        existed. An EMPTY list (``[]``) means *tools-off*: nothing tool-related
        is sent on the wire at all — the deepthink seam always passes ``[]`` so
        its one-shot completion structurally cannot call a tool or ``finish``
        (the same invariant class as the acceptance self-check).
        """
        raise NotImplementedError(
            f"engine '{self.name}' does not support one-shot completions; "
            "plan mode needs a live backend (e.g. vllm-openai)"
        )

    def make_count_tokens(self, config: EngineConfig) -> "Callable[[list[dict[str, Any]]], int]":
        """Return a token counter (``messages -> int``) for use outside the loop.

        The bounded work loop windows its own history via a counter built inside
        :meth:`work`; this public seam exposes the same counting capability to
        features that call :meth:`make_complete` directly — e.g. the deepthink
        escalation seam (:mod:`colleague.deepthink`, task t2), which must window
        its prompt to the deepthink model's OWN context budget before sending it.

        The base default returns the zero-dependency char-heuristic estimator
        (:func:`colleague.context.count_tokens_chars`) — the same fallback the
        loop itself uses when a backend has no exact counter. A backend with an
        exact counter (e.g. vLLM's ``/tokenize`` endpoint) overrides this to
        return it, so a caller of this seam gets the same precision the loop
        gets. Imported lazily to keep this module's import surface minimal.
        """
        from colleague.context import count_tokens_chars

        return count_tokens_chars

    def system_prompt(self, task: Task, config: EngineConfig) -> str | None:
        """Compose the model-specific system prompt (AGENTS + skills layers).

        Resolved here on the base class — not in each ``drive`` — so *every*
        backend plugin inherits the layered instruction injection for free (the
        all-engines rule), mirroring how hooks are inherited via the loop.
        Subclasses pass the return value as ``system_prompt=`` to
        :func:`colleague.loop.run`. Returns ``None`` when no AGENTS/skills
        layers exist for ``config.model``, so the loop falls back to its own
        default and behavior is byte-identical to a layer-free run.
        """
        # Imported lazily to keep this module's import surface minimal and avoid
        # pulling the whole loop in at engine import time.
        from colleague.layers import compose_role_prompt, system_prompt_for
        from colleague.loop import _DEFAULT_SYSTEM

        # Typed-subagent role (#t4): when this work item runs as a role, compose the
        # base + AGENTS + the role's prompt_fragment + the role's curated skill subset
        # (one assembly path — compose_role_prompt reuses system_prompt_for's pieces).
        # An unknown/absent role falls back to the role-less prompt → byte-identical.
        role_name = getattr(config, "role", None)
        if role_name:
            from colleague.roles import load_role

            role = load_role(role_name, task.repo_path, config.model)
            if role is not None:
                return compose_role_prompt(role, task.repo_path, config.model, base=_DEFAULT_SYSTEM)
        return system_prompt_for(task.repo_path, config.model, base=_DEFAULT_SYSTEM)

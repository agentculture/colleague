"""Live partial-result registry for interrupt salvage (#410).

The bounded tool loop (:func:`colleague.loop.run`) registers the ``TaskResult``
it is populating the moment it is created and unregisters it on its own exit
paths. A SIGTERM/SIGINT handler installed by the work CLI
(:func:`colleague.cli._commands.work._arm_interrupt_commit`) reads the live
partial through :func:`peek` and writes the result artifact **before** the
process unwinds — independent of whatever state the request layer is stuck in.

Why a registry and not the exception flow: the interrupt is delivered as a
``SystemExit`` (a ``BaseException``) precisely so no ``except Exception`` in the
loop or a tool executor can swallow it (#222); that same property means the
loop's ``WorkAborted`` partial-preservation path never sees it. A plain,
process-local mapping keyed by task id gives the handler the live object with
no dependence on how the interrupt unwinds.

Leaf module: stdlib only, no threads, no I/O — the artifact write stays the
work CLI's. Safe under the GIL for the single-writer-per-task discipline the
loop already follows (subagent children register their OWN task ids).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.contract import TaskResult

__all__ = ["register", "unregister", "peek"]

_LIVE: dict[str, "TaskResult"] = {}


def register(task_id: str, result: "TaskResult") -> None:
    """Record *result* as the live partial for *task_id* (overwrites a stale entry)."""
    _LIVE[task_id] = result


def unregister(task_id: str) -> None:
    """Forget *task_id*'s live partial (a no-op when absent)."""
    _LIVE.pop(task_id, None)


def peek(task_id: str) -> Optional["TaskResult"]:
    """The live partial for *task_id*, or ``None`` when no loop is running it."""
    return _LIVE.get(task_id)

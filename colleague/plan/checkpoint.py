"""Durable file-based gate/checkpoint for colleague's plan mode.

A :class:`Checkpoint` persists, to disk, the originating request, the current
proposed item awaiting the operator, the recommended next move, and the gate
ids already resolved -- so that killing the process and running
``colleague plan continue`` (:mod:`colleague.cli._commands.plan`) resumes
without re-asking those resolved gates. This module only persists state; it
does not itself decide how a caller resumes (see ``cmd_plan_continue``).

Stdlib only: ``dataclasses``, ``json``, ``pathlib``.  No devague import, no
threads, no sockets, no daemon.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Checkpoint:
    """One checkpoint: the gate currently awaiting the operator.

    Fields
    ------
    plan_id:
        Identifier for the plan this checkpoint belongs to.
    proposed_item:
        Id or text of the item awaiting the operator; may be empty when
        there is nothing left to propose.
    recommended_move:
        The recommended next move for the operator.
    resolved_gates:
        Gate ids already resolved (append-only).
    request:
        The originating task instruction that started this plan run. Persisted
        so a later ``colleague plan continue`` (#t17) can resume without the
        caller re-typing the request. Defaults to ``""`` so a checkpoint
        written before this field existed still loads cleanly (an empty
        request is later treated as "nothing to resume").
    """

    plan_id: str
    proposed_item: str = ""
    recommended_move: str = ""
    resolved_gates: list[str] = field(default_factory=list)
    request: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "proposed_item": self.proposed_item,
            "recommended_move": self.recommended_move,
            "resolved_gates": list(self.resolved_gates),
            "request": self.request,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        return cls(
            plan_id=str(data["plan_id"]),
            proposed_item=str(data.get("proposed_item", "")),
            recommended_move=str(data.get("recommended_move", "")),
            resolved_gates=list(data.get("resolved_gates", [])),
            request=str(data.get("request", "")),
        )


def checkpoint_path(plan_id: str, repo_path: str | Path) -> Path:
    """The file path for a plan checkpoint.

    Writes target ``<repo_path>/.colleague/plan/<plan_id>.json``.
    """
    return Path(repo_path) / ".colleague" / "plan" / f"{plan_id}.json"


def save(checkpoint: Checkpoint, repo_path: str | Path) -> None:
    """Persist ``checkpoint`` to disk under its plan id.

    Creates parent directories as needed.
    """
    path = checkpoint_path(checkpoint.plan_id, repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(checkpoint.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load(plan_id: str, repo_path: str | Path) -> Optional[Checkpoint]:
    """Load a checkpoint by ``plan_id``, or ``None`` when absent.

    A missing file is a clean no-op (returns ``None``), never raises.
    """
    path = checkpoint_path(plan_id, repo_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return Checkpoint.from_dict(data)


def record_resolved_gate(
    plan_id: str,
    repo_path: str | Path,
    gate_id: str,
    next_item: str = "",
    next_move: str = "",
) -> Optional[Checkpoint]:
    """Record a resolved gate and advance to the next proposed item.

    Appends ``gate_id`` to ``resolved_gates``, sets ``proposed_item`` and
    ``recommended_move`` to the supplied next values, then persists the
    updated checkpoint to disk.

    If no checkpoint exists yet, creates a fresh one with the given
    ``plan_id``.  Returns the updated checkpoint, or ``None`` on I/O error.
    """
    cp = load(plan_id, repo_path)
    if cp is None:
        cp = Checkpoint(plan_id=plan_id)
    cp.resolved_gates.append(gate_id)
    cp.proposed_item = next_item
    cp.recommended_move = next_move
    save(cp, repo_path)
    return cp

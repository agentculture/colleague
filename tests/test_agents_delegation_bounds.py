"""Delegation bounds are ENFORCED on the spawn path (#411 t11; Qodo, PR #414).

``colleague.agents.delegation.validate_delegation`` owned the arithmetic —
child tools ``⊆`` parent tools, child ceiling ``≤`` parent ceiling — but
nothing on the spawn path called it, so an armed parent could hand a child a
WIDER surface than it holds itself by naming a different profile.

Pinned here:

(a) a WIDENING delegation is refused whole — no child work, no ``delegate``
    event on the parent's ledger;
(b) a NARROWING delegation still runs (the mechanism only refuses widening);
(c) a bare lobes-role profile INHERITS the parent's purpose instead of
    silently defaulting to the full ``thinker_coder`` surface;
(d) an authority ceiling may not rise (a read-only-role parent);
(e) UNARMED and armed-without-profile paths are untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.agents.runtime import seat_ceiling
from colleague.agents.state.ledger import TaskLedger, read_ledger
from colleague.agents.tools import PURPOSE_TOOLS
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult, Usage
from colleague.subagents import ChildSpec, SubagentError, run_subagent


class _Capture:
    """A fake engine recording every (task, config) it is handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[Task, EngineConfig]] = []

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        self.calls.append((task, config))
        return TaskResult(
            task_id=task.id, status=OK, summary="captured", changed_files=[], usage=Usage()
        )


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    from colleague import subagents as mod

    monkeypatch.setattr(mod.registry, "load", lambda name: cap)
    return cap


def _armed(purpose: str | None = None, **over) -> EngineConfig:
    """An armed parent seat running on *purpose* (no gateway: the main-seat floor)."""
    config = EngineConfig(agents=True, model="parent-model", lobes_gateway_url=None, **over)
    if purpose is not None:
        setattr(config, "agents_profile", purpose)
    return config


def _spawn(tmp_path: Path, parent: EngineConfig, spec: ChildSpec, role: str | None = None):
    return run_subagent(
        "do the thing",
        repo_path=str(tmp_path),
        parent_config=parent,
        parent_engine="mock",
        depth=1,
        role=role,
        spec=spec,
    )


# ---------------------------------------------------------------------------
# (a) widening refuses whole
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wider", ["thinker_coder", "associate"])
def test_worker_parent_cannot_delegate_a_wider_surface(
    tmp_path: Path, capture: _Capture, wider: str
) -> None:
    """The dormant ``worker`` holds no ``write_file``/``edit_file``; a child of
    its may not carry them either."""
    parent = _armed("worker")
    with pytest.raises(SubagentError) as excinfo:
        _spawn(tmp_path, parent, ChildSpec(profile=wider))
    message = str(excinfo.value)
    assert "delegation refused" in message
    assert "write_file" in message and "edit_file" in message
    assert capture.calls == []  # refused BEFORE any child work


def test_refused_delegation_writes_no_ledger_event(tmp_path: Path, capture: _Capture) -> None:
    """A refused delegation records nothing: no ``delegate``, no ``return``."""
    ledger_file = tmp_path / ".colleague" / "ledger" / "p1.jsonl"
    ledger = TaskLedger(ledger_file, task_id="p1")
    ledger.append("operator_request", {"ref": "op:1", "text": "build the widget"})
    parent = _armed("worker")
    parent.agents_ledger_path = str(ledger_file)
    with pytest.raises(SubagentError):
        _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"))
    kinds = [event.kind for event in read_ledger(ledger_file).events]
    assert "delegate" not in kinds and "return" not in kinds


# ---------------------------------------------------------------------------
# (b) narrowing still runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("narrower", ["worker", "talker"])
def test_narrowing_delegation_is_allowed(tmp_path: Path, capture: _Capture, narrower: str) -> None:
    parent = _armed("thinker_coder")
    sub = _spawn(tmp_path, parent, ChildSpec(profile=narrower))
    assert sub.status == OK
    assert len(capture.calls) == 1
    _task, child_cfg = capture.calls[0]
    assert getattr(child_cfg, "agents_profile") == narrower
    assert set(PURPOSE_TOOLS[narrower]) <= set(PURPOSE_TOOLS["thinker_coder"])


def test_same_purpose_delegation_is_allowed(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed("worker")
    sub = _spawn(tmp_path, parent, ChildSpec(profile="worker"))
    assert sub.status == OK


# ---------------------------------------------------------------------------
# (c) a bare role name switches the MODEL, never the surface
# ---------------------------------------------------------------------------


def test_bare_role_profile_inherits_the_parent_purpose(tmp_path: Path, capture: _Capture) -> None:
    """``profile="cortex"`` under a ``worker`` parent must not hand the child
    the full ``thinker_coder`` surface via the acting-seat default."""
    parent = _armed("worker")
    _spawn(tmp_path, parent, ChildSpec(profile="cortex"))
    _task, child_cfg = capture.calls[0]
    assert getattr(child_cfg, "agents_profile") == "worker"


# ---------------------------------------------------------------------------
# (d) the authority ceiling may not rise
# ---------------------------------------------------------------------------


def test_seat_ceiling_ranks_read_only_lowest() -> None:
    assert seat_ceiling(EngineConfig(), "explorer") == "read_only"
    no_publish = EngineConfig()
    setattr(no_publish, "no_pr", True)
    assert seat_ceiling(no_publish) == "repo_patch_no_publish"
    assert seat_ceiling(EngineConfig()) == "repo_patch_publish"


def test_read_only_parent_cannot_delegate_a_writing_child(
    tmp_path: Path, capture: _Capture
) -> None:
    parent = _armed("thinker_coder", role="explorer")
    with pytest.raises(SubagentError) as excinfo:
        _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"))
    assert "exceeds the parent's 'read_only'" in str(excinfo.value)
    assert capture.calls == []


def test_read_only_parent_may_delegate_a_read_only_child(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed("thinker_coder", role="explorer")
    sub = _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"), role="explorer")
    assert sub.status == OK


# ---------------------------------------------------------------------------
# (e) unarmed / armed-without-profile are untouched
# ---------------------------------------------------------------------------


def test_unarmed_parent_is_never_validated(tmp_path: Path, capture: _Capture) -> None:
    """Unarmed, a profile is inert and no bound is computed — byte-identical."""
    parent = EngineConfig(model="parent-model")
    setattr(parent, "agents_profile", "worker")
    sub = _spawn(tmp_path, parent, ChildSpec(profile="thinker_coder"))
    assert sub.status == OK


def test_armed_without_profile_is_never_validated(tmp_path: Path, capture: _Capture) -> None:
    parent = _armed("worker")
    sub = _spawn(tmp_path, parent, ChildSpec())
    assert sub.status == OK

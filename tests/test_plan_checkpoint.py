"""Tests for colleague.plan.checkpoint — durable file-based plan-mode gates.

Covers:
  (a) Checkpoint round-trips through save -> load identically.
  (b) load returns None when no checkpoint file exists (clean no-op).
  (c) Recording a resolved gate and reloading reflects the updated state.
  (d) checkpoint.py imports only stdlib (no third-party, no devague).
"""

from importlib import import_module
from pathlib import Path

import pytest

from colleague.plan.checkpoint import (
    Checkpoint,
    checkpoint_path,
    load,
    record_resolved_gate,
    save,
)

# ── (a) Save -> load round-trip ─────────────────────────────────────────────


def test_save_load_roundtrip(tmp_path: Path):
    """Saving a checkpoint and loading it back yields an equal Checkpoint."""
    cp = Checkpoint(
        plan_id="plan-1",
        proposed_item="step-1",
        recommended_move="implement",
        resolved_gates=["gate-0"],
    )
    save(cp, tmp_path)
    loaded = load("plan-1", tmp_path)
    assert loaded is not None
    assert loaded == cp


def test_save_load_empty_fields(tmp_path: Path):
    """A checkpoint with empty proposed_item round-trips correctly."""
    cp = Checkpoint(
        plan_id="plan-2",
        proposed_item="",
        recommended_move="review",
        resolved_gates=[],
    )
    save(cp, tmp_path)
    loaded = load("plan-2", tmp_path)
    assert loaded is not None
    assert loaded == cp


# ── (b) Absent file -> None ─────────────────────────────────────────────────


def test_load_absent_returns_none(tmp_path: Path):
    """Loading a non-existent checkpoint returns None (never raises)."""
    assert load("nonexistent", tmp_path) is None


def test_load_absent_plan_id(tmp_path: Path):
    """Loading a plan_id that was never saved returns None."""
    # Save one checkpoint, load a different id.
    cp = Checkpoint(
        plan_id="plan-a",
        proposed_item="x",
        recommended_move="y",
        resolved_gates=[],
    )
    save(cp, tmp_path)
    assert load("plan-b", tmp_path) is None


# ── (c) Record resolved gate & resume ──────────────────────────────────────


def test_record_resolved_gate(tmp_path: Path):
    """Recording a resolved gate updates the checkpoint on disk."""
    cp = Checkpoint(
        plan_id="plan-3",
        proposed_item="step-1",
        recommended_move="implement",
        resolved_gates=[],
    )
    save(cp, tmp_path)

    updated = record_resolved_gate(
        plan_id="plan-3",
        repo_path=tmp_path,
        gate_id="gate-1",
        next_item="step-2",
        next_move="test",
    )
    assert updated is not None
    assert "gate-1" in updated.resolved_gates
    assert updated.proposed_item == "step-2"
    assert updated.recommended_move == "test"

    # Reload from disk to verify persistence.
    reloaded = load("plan-3", tmp_path)
    assert reloaded is not None
    assert reloaded == updated


def test_record_resolved_gate_creates_file(tmp_path: Path):
    """record_resolved_gate creates the checkpoint file if absent."""
    updated = record_resolved_gate(
        plan_id="plan-new",
        repo_path=tmp_path,
        gate_id="gate-0",
        next_item="step-1",
        next_move="implement",
    )
    assert updated is not None
    assert updated.plan_id == "plan-new"
    assert "gate-0" in updated.resolved_gates
    assert updated.proposed_item == "step-1"

    # Verify it persists.
    reloaded = load("plan-new", tmp_path)
    assert reloaded is not None
    assert reloaded == updated


def test_checkpoint_path(tmp_path: Path):
    """checkpoint_path returns the expected file path."""
    path = checkpoint_path("my-plan", tmp_path)
    assert path == tmp_path / ".colleague" / "plan" / "my-plan.json"


# ── (d) stdlib-only imports ─────────────────────────────────────────────────


def test_checkpoint_imports_stdlib_only():
    """colleague.plan.checkpoint imports only stdlib modules."""
    mod = import_module("colleague.plan.checkpoint")
    _stdlib_allowlist = {
        "dataclasses",
        "json",
        "pathlib",
        "typing",
        "colleague",
        "__future__",
    }
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        mod_name = getattr(obj, "__module__", None)
        if mod_name is None:
            continue
        top = mod_name.split(".")[0]
        if top not in _stdlib_allowlist:
            pytest.fail(
                f"checkpoint.py references non-stdlib module {mod_name!r} " f"(via {name!r})"
            )


def test_no_devague_import():
    """checkpoint.py must not import devague."""
    mod = import_module("colleague.plan.checkpoint")
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        mod_name = getattr(obj, "__module__", None)
        if mod_name and mod_name.startswith("devague"):
            pytest.fail(
                f"checkpoint.py must not import devague " f"(found {name!r} from {mod_name!r})"
            )

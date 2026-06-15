"""Tests for colleague.plan.frame — the native plan-mode frame data model.

Covers:
  (a) PlanFrame round-trips through to_dict / from_dict identically.
  (b) Claims carry kind + state; steps carry a mandatory flag.
  (c) frame.py imports only stdlib (no third-party packages).
"""

import json
import sys
from importlib import import_module

import pytest

from colleague.plan.frame import (
    Claim,
    HonestyCondition,
    PlanFrame,
    Step,
)


# ── (a) Round-trip: save -> load -> equal ──────────────────────────────────

def _sample_frame() -> PlanFrame:
    """A representative PlanFrame exercising every field."""
    return PlanFrame(
        claims=[
            Claim(
                id="c1",
                kind="announcement",
                text="The system shall process requests.",
                state="confirmed",
            ),
            Claim(
                id="c2",
                kind="assumption",
                text="Users have internet access.",
                state="proposed",
            ),
            Claim(
                id="c3",
                kind="requirement",
                text="Latency under 200 ms.",
            ),
        ],
        honesty_conditions=[
            HonestyCondition(
                id="h1",
                claim_id="c1",
                text="Verified by load test.",
                state="confirmed",
            ),
            HonestyCondition(
                id="h2",
                claim_id="c2",
                text="Check ISP coverage data.",
            ),
        ],
        steps=[
            Step(id="s1", kind="setup", mandatory=True),
            Step(id="s2", kind="implement", mandatory=False),
        ],
    )


def test_planframe_roundtrip():
    """A PlanFrame round-trips JSON identically (save -> load -> equal)."""
    original = _sample_frame()
    payload = original.to_dict()
    # Simulate a JSON save + load cycle.
    raw = json.dumps(payload)
    loaded = json.loads(raw)
    restored = PlanFrame.from_dict(loaded)
    assert restored == original


def test_planframe_empty_roundtrip():
    """An empty PlanFrame also round-trips."""
    original = PlanFrame()
    restored = PlanFrame.from_dict(original.to_dict())
    assert restored == original


# ── (b) Claims carry kind + state; steps carry mandatory ───────────────────

def test_claim_defaults():
    """A Claim with only id, kind, text gets default state='proposed'."""
    c = Claim(id="x", kind="decision", text="Go with option A")
    assert c.state == "proposed"


def test_claim_explicit_state():
    """A Claim can carry an explicit state."""
    c = Claim(id="y", kind="boundary", text="No external APIs", state="confirmed")
    assert c.state == "confirmed"


def test_honesty_condition_defaults():
    """An HonestyCondition defaults to state='proposed'."""
    h = HonestyCondition(id="h1", claim_id="c1", text="Check logs")
    assert h.state == "proposed"


def test_step_mandatory_flag():
    """A Step carries a mandatory boolean (True/False)."""
    s1 = Step(id="s1", kind="setup", mandatory=True)
    s2 = Step(id="s2", kind="cleanup", mandatory=False)
    assert s1.mandatory is True
    assert s2.mandatory is False


def test_step_roundtrip():
    """A Step round-trips through to_dict / from_dict."""
    original = Step(id="s3", kind="test", mandatory=True)
    restored = Step.from_dict(original.to_dict())
    assert restored == original


def test_claim_roundtrip():
    """A Claim round-trips through to_dict / from_dict."""
    original = Claim(id="c1", kind="announcement", text="Hello", state="confirmed")
    restored = Claim.from_dict(original.to_dict())
    assert restored == original


def test_honesty_condition_roundtrip():
    """An HonestyCondition round-trips through to_dict / from_dict."""
    original = HonestyCondition(
        id="h1", claim_id="c1", text="Check", state="confirmed"
    )
    restored = HonestyCondition.from_dict(original.to_dict())
    assert restored == original


# ── (c) frame.py imports only stdlib ────────────────────────────────────────

def test_frame_imports_stdlib_only():
    """colleague.plan.frame imports only stdlib modules (no third-party)."""
    mod = import_module("colleague.plan.frame")
    # Walk the module's namespace for any imported objects that live in
    # non-stdlib packages.  We allow the standard-library modules used by the
    # module itself (dataclasses, json, typing) plus the colleague package
    # (which is this repo, not a third-party dep).
    _stdlib_allowlist = {
        "dataclasses",
        "json",
        "typing",
        "colleague",
        "__future__",
    }
    # Check that the module's top-level imports are all stdlib or local.
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        mod_name = getattr(obj, "__module__", None)
        if mod_name is None:
            continue
        top = mod_name.split(".")[0]
        if top not in _stdlib_allowlist:
            pytest.fail(
                f"frame.py references non-stdlib module {mod_name!r} "
                f"(via {name!r})"
            )


def test_no_devague_import():
    """frame.py must not import devague (or any devague sub-package)."""
    mod = import_module("colleague.plan.frame")
    for name, obj in vars(mod).items():
        if name.startswith("_"):
            continue
        mod_name = getattr(obj, "__module__", None)
        if mod_name and mod_name.startswith("devague"):
            pytest.fail(f"frame.py must not import devague (found {name!r} from {mod_name!r})")

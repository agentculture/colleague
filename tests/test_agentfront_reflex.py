"""Tests for the AgentFront surface reflex paragraph in _DEFAULT_SYSTEM.

Verifies the reflex is present in the default system prompt, following the same
pattern as tests/test_destination_loop.py.
"""

from __future__ import annotations

from colleague.loop import _DEFAULT_SYSTEM


def test_default_system_contains_agentfront_reflex() -> None:
    """_DEFAULT_SYSTEM carries the AgentFront surface reflex paragraph."""
    lower = _DEFAULT_SYSTEM.lower()

    assert "agentfront" in lower, "_DEFAULT_SYSTEM must mention 'agentfront'"

    # Probe before first use.
    assert "before" in lower, "_DEFAULT_SYSTEM must mention 'before'"
    assert "first" in lower, "_DEFAULT_SYSTEM must mention 'first'"

    # Affordance tokens.
    assert "learn" in lower, "_DEFAULT_SYSTEM must mention 'learn'"
    assert "explain" in lower, "_DEFAULT_SYSTEM must mention 'explain'"
    assert "--help" in lower, "_DEFAULT_SYSTEM must mention '--help'"
    assert "--json" in lower, "_DEFAULT_SYSTEM must mention '--json'"

    # Advisory framing.
    assert "advisory" in lower, "_DEFAULT_SYSTEM must state the reflex is advisory"
    assert "read-only" in lower, "_DEFAULT_SYSTEM must state the probe is read-only"

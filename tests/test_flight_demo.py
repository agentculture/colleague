"""The flight-piloting demo is reproducible and shows the full sequence.

Runs scripts/demo_flight.py's :func:`run_demo` and asserts the announcement holds
end-to-end: dispatch -> watch -> mid-flight guidance changes course -> cooperative
stop with a preserved partial, using only files under .colleague/.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_DEMO = Path(__file__).resolve().parents[1] / "scripts" / "demo_flight.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_flight", _DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_shows_the_full_piloting_sequence(tmp_path):
    demo = _load_demo()
    outcome = demo.run_demo(tmp_path)

    # The flight first headed the wrong way (wrong.txt), then — after the pilot's
    # mid-flight guidance landed at the NEXT turn boundary (turn 2) — changed course
    # to right.txt.
    assert outcome["wrong_written"] is True
    assert outcome["right_written"] is True
    assert (
        outcome["guidance_seen_turn"] == 2
    ), "guidance must reach the model on the turn AFTER it was sent"

    # The pilot then called it back: a cooperative stop, preserved as a partial.
    assert outcome["stopped_without_finish"] is True
    assert "pilot" in outcome["summary"].lower()
    assert outcome["changed_files"] == ["right.txt", "wrong.txt"]

    # The whole control plane lived under .colleague/ — no socket, no daemon.
    assert outcome["files_only_under_colleague"] is True


def test_demo_is_reproducible(tmp_path):
    # Same inputs -> same outcome (deterministic: no clock, no randomness, no network).
    demo = _load_demo()
    a = demo.run_demo(tmp_path / "a")
    b = demo.run_demo(tmp_path / "b")
    for key in ("wrong_written", "right_written", "guidance_seen_turn", "stopped_without_finish"):
        assert a[key] == b[key]

"""Guard test for the ``tools.tui_sim`` TUI-simulation harness.

The harness records the *real* TUI render seams, so this test pins two
properties that keep the committed recordings trustworthy:

* **Determinism** — building every scenario twice yields byte-identical casts and
  storyboards (the recordings can be regenerated and diffed in CI).
* **Cast validity** — every ``.cast`` is well-formed asciinema **v2** (a JSON
  header with ``version == 2`` followed by ``[t, "o", data]`` output events).

If a render seam changes shape under the harness, this test fails loudly rather
than letting the recordings drift silently.
"""

import json
from pathlib import Path

import pytest

from tools.tui_sim.cast import strip_sgr
from tools.tui_sim.scenarios import build_all

_REPO = Path(__file__).resolve().parents[1]

_EXPECTED = {"first-contact", "drive-cockpit", "skill-suggested", "failed-step", "full-ride"}


def _by_name():
    return {s.name: s for s in build_all(_REPO)}


def test_all_expected_scenarios_present():
    assert set(_by_name()) == _EXPECTED


def test_build_is_deterministic():
    first = _by_name()
    second = _by_name()
    assert set(first) == set(second)
    for name, a in first.items():
        b = second[name]
        assert a.filmstrip.cast() == b.filmstrip.cast(), f"{name}: cast not deterministic"
        assert (
            a.filmstrip.storyboard_txt() == b.filmstrip.storyboard_txt()
        ), f"{name}: storyboard not deterministic"


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_cast_is_valid_v2(name):
    cast = _by_name()[name].filmstrip.cast()
    lines = cast.splitlines()
    assert len(lines) >= 2, "a cast needs a header plus at least one event"

    header = json.loads(lines[0])
    assert header["version"] == 2
    assert isinstance(header["width"], int) and header["width"] > 0
    assert isinstance(header["height"], int) and header["height"] > 0

    last_t = -1.0
    for raw in lines[1:]:
        event = json.loads(raw)
        assert isinstance(event, list) and len(event) == 3
        t, code, data = event
        assert isinstance(t, (int, float)) and t >= last_t  # non-decreasing timeline
        assert code == "o"
        assert isinstance(data, str) and data
        last_t = t


def test_storyboard_is_plain_text():
    """The ``.txt`` storyboard must carry no escape sequences (it is SGR-stripped)."""
    txt = _by_name()["full-ride"].filmstrip.storyboard_txt()
    assert "\x1b" not in txt
    assert strip_sgr(txt) == txt

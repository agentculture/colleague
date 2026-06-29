"""Tests for the live TTY driver — ``colleague.tui.render.driver`` (t12).

All four acceptance criteria:
1. ``key_to_event`` maps quit keys to None, other keys to Key.
2. ``run`` in injected mode (keys=[...]) renders frames and returns CockpitState.
3. No daemon/socket — source-scan confirms driver imports nothing forbidden.
4. ``tui live`` exits with CliError (clean, no hang) when stdin is not a tty.
"""

from __future__ import annotations

import inspect
import io
import sys

import pytest
from agentfront.taui.events import KeyPress
from agentfront.taui.state import TAUIState as CockpitState

from colleague.cli import main
from colleague.cli._errors import CliError
from colleague.tui.render.driver import key_to_event, run

# ---------------------------------------------------------------------------
# Criterion 1: key_to_event mapping
# ---------------------------------------------------------------------------


def test_key_to_event_q_returns_none() -> None:
    """'q' is a quit key — must return None."""
    assert key_to_event("q") is None


def test_key_to_event_esc_returns_none() -> None:
    """ESC (0x1b) is a quit key — must return None."""
    assert key_to_event("\x1b") is None


def test_key_to_event_other_returns_key() -> None:
    """Any non-quit key returns a Key event."""
    result = key_to_event("x")
    assert isinstance(result, KeyPress)
    assert result.key == "x"


def test_key_to_event_arbitrary_token_returns_key() -> None:
    """Arrow keys and multi-char tokens also return Key."""
    result = key_to_event("up")
    assert isinstance(result, KeyPress)
    assert result.key == "up"


def test_key_to_event_enter_returns_key() -> None:
    """Enter key returns a Key event (not a quit)."""
    result = key_to_event("\r")
    assert isinstance(result, KeyPress)


# ---------------------------------------------------------------------------
# Criterion 2: run in injected mode
# ---------------------------------------------------------------------------


def test_run_returns_cockpit_state() -> None:
    """run(..., keys=[...]) must return a CockpitState."""
    buf = io.StringIO()
    result = run(initial=CockpitState(), keys=["x", "q"], out=buf)
    assert isinstance(result, CockpitState)


def test_run_writes_frames_to_out() -> None:
    """run(..., keys=[...]) must write at least one rendered frame to out."""
    buf = io.StringIO()
    run(initial=CockpitState(), keys=["x", "q"], out=buf)
    content = buf.getvalue()
    assert len(content) > 0, "buffer must be non-empty (at least one frame was rendered)"


def test_run_quits_on_q_does_not_block() -> None:
    """run must return promptly when it sees a quit key — never block.

    We verify this by passing a finite key sequence ending with 'q'.  If the
    function returns at all (i.e., the test completes), the promptness criterion
    is satisfied.
    """
    buf = io.StringIO()
    # Several non-quit keys followed by 'q' — must return a CockpitState.
    state = run(initial=CockpitState(), keys=["a", "b", "c", "q"], out=buf)
    assert isinstance(state, CockpitState)


def test_run_quits_on_esc() -> None:
    """ESC triggers quit just like 'q'."""
    buf = io.StringIO()
    state = run(initial=CockpitState(), keys=["x", "\x1b"], out=buf)
    assert isinstance(state, CockpitState)
    assert buf.getvalue()  # at least one frame


def test_run_default_initial_state() -> None:
    """run without explicit initial creates a fresh CockpitState."""
    buf = io.StringIO()
    state = run(keys=["q"], out=buf)
    assert isinstance(state, CockpitState)


def test_run_max_iterations_respected() -> None:
    """max_iterations=2 stops the loop even before a quit key."""
    buf = io.StringIO()
    # Provide an infinite key sequence; max_iterations caps the loop.
    import itertools

    state = run(
        initial=CockpitState(),
        keys=itertools.repeat("a"),
        out=buf,
        max_iterations=2,
    )
    assert isinstance(state, CockpitState)
    assert buf.getvalue()


def test_run_empty_keys_returns_state() -> None:
    """run with an empty key sequence returns the initial state."""
    buf = io.StringIO()
    initial = CockpitState()
    state = run(initial=initial, keys=[], out=buf)
    assert isinstance(state, CockpitState)


# ---------------------------------------------------------------------------
# Criterion 3: no daemon / socket in driver source
# ---------------------------------------------------------------------------


def test_driver_does_not_import_socket() -> None:
    """driver.py must not import 'socket'."""
    import colleague.tui.render.driver as drv_mod

    src = inspect.getsource(drv_mod)
    assert "import socket" not in src, "driver must not import 'socket'"


def test_driver_does_not_import_subprocess() -> None:
    """driver.py must not import 'subprocess'."""
    import colleague.tui.render.driver as drv_mod

    src = inspect.getsource(drv_mod)
    assert "import subprocess" not in src, "driver must not import 'subprocess'"


def test_driver_does_not_import_asyncio() -> None:
    """driver.py must not import 'asyncio'."""
    import colleague.tui.render.driver as drv_mod

    src = inspect.getsource(drv_mod)
    assert "import asyncio" not in src, "driver must not import 'asyncio'"


def test_driver_does_not_use_os_fork() -> None:
    """driver.py must not call os.fork."""
    import colleague.tui.render.driver as drv_mod

    src = inspect.getsource(drv_mod)
    assert "os.fork" not in src, "driver must not call 'os.fork'"


def test_driver_does_not_start_threads() -> None:
    """driver.py must not call Thread(...).start()."""
    import colleague.tui.render.driver as drv_mod

    src = inspect.getsource(drv_mod)
    assert "Thread(" not in src, "driver must not spawn threads"


# ---------------------------------------------------------------------------
# Criterion 4: tui live CLI exits with CliError when stdin is not a tty
# ---------------------------------------------------------------------------


def test_tui_live_raises_cli_error_when_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """tui live must raise CliError (not hang) when stdin is not a tty.

    We call cmd_tui_live directly so we see the raw CliError before main()
    catches and translates it to an exit code.
    """
    import argparse

    from colleague.cli._commands.tui import cmd_tui_live

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(json=False)
    with pytest.raises(CliError) as exc_info:
        cmd_tui_live(args)
    err = exc_info.value
    # The error message must mention the tty requirement.
    assert "tty" in str(err).lower() or "terminal" in str(err).lower()


def test_tui_live_cli_error_has_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CliError from tui live must carry a remediation hint."""
    import argparse

    from colleague.cli._commands.tui import cmd_tui_live

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(json=False)
    with pytest.raises(CliError) as exc_info:
        cmd_tui_live(args)
    err = exc_info.value
    assert err.remediation, "CliError must carry a remediation hint"


def test_tui_live_main_exits_nonzero_when_not_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main(['tui', 'live']) must return non-zero exit code when not a tty."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    rc = main(["tui", "live"])
    assert rc != 0, "tui live must exit non-zero when stdin is not a tty"
    err_output = capsys.readouterr().err
    assert "terminal" in err_output.lower() or "tty" in err_output.lower()


def test_tui_live_registered_in_parser(capsys: pytest.CaptureFixture[str]) -> None:
    """'tui live' must appear in the tui help text."""
    # The rendered CLI returns 0 for a verb's --help rather than raising SystemExit
    # (agentfront run_cli translates argparse's internal exit); content unchanged.
    main(["tui", "--help"])
    out = capsys.readouterr().out
    assert "live" in out

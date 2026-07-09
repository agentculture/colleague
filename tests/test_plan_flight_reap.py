"""Qodo #312 ("plan flight not reaped") — ``run_plan_request`` reaps its flight
plane on every exit path.

``colleague plan run --watch`` arms a flight plane
(``colleague/cli/_commands/plan.py`` ``run_plan_request``) but, before this fix,
never called ``plane.reap()`` -- unlike the bounded tool loop, which reaps via
``ctx.flight.reap()`` (``colleague/loop.py`` ``_reap_flight``). So a finished plan
run left stale ``.colleague/flight/<plan_id>.*`` files behind, and
``colleague flight status/list`` could keep reporting a finished plan as active.

These tests stub ``run_plan_mode`` (success and a ``ValueError`` failure) and
patch just enough of the seams ``run_plan_request`` builds before reaching it
(``registry.load`` for the engine, ``EngineConfig.resolve`` for a deepthink-free
config) so the flight plane genuinely gets armed under ``watch=True`` and we can
assert it is reaped on both the success and the failure path -- and left
untouched (never created) when ``watch=False``.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from colleague import flight
from colleague.cli._commands.plan import run_plan_request
from colleague.cli._errors import CliError
from colleague.config import EngineConfig


class _FakeEngine:
    """A minimal live-shaped engine: ``make_complete`` never raises."""

    name = "fake"

    def make_complete(self, _config):
        return lambda messages: types.SimpleNamespace(content="{}")


def _decide(_item, _critique):
    return "confirm"


def _config() -> EngineConfig:
    # No env vars are set (conftest's autouse _isolate_provider_env scrubs
    # COLLEAGUE_*/OPENAI_* before every test), so this resolves to the built-in
    # defaults -- notably deepthink=None, which keeps run_plan_request's
    # dual-model routing a no-op and lets the fake engine's `complete` stand in
    # unmodified.
    return EngineConfig.resolve()


def _run(tmp_path, *, watch: bool, run_plan_mode_stub):
    with patch("colleague.cli._commands.plan.registry.load", return_value=_FakeEngine()):
        with patch("colleague.cli._commands.plan.run_plan_mode", run_plan_mode_stub):
            return run_plan_request(
                repo=tmp_path,
                request="build a thing",
                engine_name="fake",
                config=_config(),
                decide=_decide,
                quick=True,
                workforce=False,
                plan_id="plan1",
                watch=watch,
            )


def test_watch_success_reaps_the_flight_plane(tmp_path):
    stub = lambda *_args, **_kwargs: types.SimpleNamespace(converged=True)  # noqa: E731

    result = _run(tmp_path, watch=True, run_plan_mode_stub=stub)

    assert result.converged is True
    assert not flight.feed_path(tmp_path, "plan1").exists()
    assert not flight.control_path(tmp_path, "plan1").exists()
    assert not flight.chat_path(tmp_path, "plan1").exists()


def test_watch_failure_still_reaps_the_flight_plane(tmp_path):
    def stub(*_args, **_kwargs):
        raise ValueError("malformed proposal")

    with pytest.raises(CliError) as excinfo:
        _run(tmp_path, watch=True, run_plan_mode_stub=stub)

    # The existing except-ValueError -> CliError behavior is preserved...
    assert "unusable plan proposal" in str(excinfo.value)
    # ...and the finally-block reap still ran despite the raise.
    assert not flight.feed_path(tmp_path, "plan1").exists()
    assert not flight.control_path(tmp_path, "plan1").exists()


def test_no_watch_creates_no_flight_dir(tmp_path):
    stub = lambda *_args, **_kwargs: types.SimpleNamespace(converged=True)  # noqa: E731

    _run(tmp_path, watch=False, run_plan_mode_stub=stub)

    assert not flight.flight_dir(tmp_path).exists()

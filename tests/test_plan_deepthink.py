"""Tests for plan-mode's dual-model deepthink routing (plan task t6).

When the operator configures a dual-model deepthink target (spec claim
c10(b)), plan-mode PROPOSAL completions (claims, honesty, plan items) target
the deepthink model instead of the main model, tools-off — and degrade back
to the main model per-call on any failure (spec c13 / h5), never crashing the
plan run. With no dual config, the call shape stays byte-identical to before
dual-model existed.

The engine is a fake (no network); ``run_plan_request`` is driven directly so
these tests exercise the exact seam in ``colleague/cli/_commands/plan.py``.
"""

from __future__ import annotations

import types

import pytest

from colleague.cli._commands.plan import _route_proposals_through_deepthink, run_plan_request
from colleague.config import DeepthinkConfig, EngineConfig

_PLAN_JSON = (
    '{"items": [{"id": "t1", "summary": "do A", "acceptance": ["A works"], "deps": []},'
    ' {"id": "t2", "summary": "do B", "acceptance": ["B works"], "deps": ["t1"]}]}'
)

# Deliberately unparseable: if a test's "main model" response is ever the one
# that actually reaches the plan-item parser, propose_plan_items exhausts its
# batch retries and run_plan_request raises a CliError — a loud failure signal
# that routing picked the wrong model, not a silent pass.
_BOGUS_JSON = "sorry, I cannot help with that"


def _deepthink_config(**overrides) -> DeepthinkConfig:
    defaults = dict(
        model="deepthink-model",
        base_url="http://localhost:8002/v1",
        api_key="dt-key",
        context_budget=1000,
    )
    defaults.update(overrides)
    return DeepthinkConfig(**defaults)


def _main_config(deepthink: DeepthinkConfig | None) -> EngineConfig:
    return EngineConfig(
        base_url="http://localhost:8001/v1",
        api_key="main-key",
        model="main-model",
        deepthink=deepthink,
    )


def _decide(*_args, **_kwargs) -> str:
    return "confirm"


def _run(repo, config, engine_name="fake"):
    return run_plan_request(
        repo=repo,
        request="build a feature",
        engine_name=engine_name,
        config=config,
        decide=_decide,
        quick=True,
        workforce=False,
    )


class _RecordingEngine:
    """Records ``(config, tools)`` per ``make_complete`` call.

    Each built completion answers with the response keyed by that config's
    ``model`` — so a test can prove whose ANSWER actually reached the proposal
    parser, not merely which config was passed to ``make_complete``.
    """

    name = "fake"

    def __init__(self, responses: dict[str, str]) -> None:
        self.calls: list[tuple[EngineConfig, list | None]] = []
        self._responses = responses

    def make_complete(self, config, tools=None):
        self.calls.append((config, tools))
        content = self._responses[config.model]

        def complete(_messages):
            return types.SimpleNamespace(content=content)

        return complete


class _NoToolsKwargEngine:
    """Mirrors the call shape that predates dual-model: ``make_complete``
    accepts a single positional ``config`` and nothing else. If the plan-mode
    seam ever starts passing ``tools=`` when no dual config is declared, this
    raises ``TypeError`` — pinning today's exact no-dual-config call shape.
    """

    name = "fake"

    def __init__(self, content: str = _PLAN_JSON) -> None:
        self.calls: list[EngineConfig] = []
        self._content = content

    def make_complete(self, config):
        self.calls.append(config)

        def complete(_messages):
            return types.SimpleNamespace(content=self._content)

        return complete


class _FallbackEngine:
    """The deepthink-targeted completion always raises; the main-model
    completion always answers cleanly. Proves per-call fallback: a dual-config
    plan run still converges even though every deepthink call fails.
    """

    name = "fake"

    def __init__(self) -> None:
        self.main_calls = 0
        self.deepthink_calls = 0

    def make_complete(self, config, tools=None):
        if tools == []:

            def dt_complete(_messages):
                self.deepthink_calls += 1
                raise TimeoutError("deepthink endpoint unreachable")

            return dt_complete

        def main_complete(_messages):
            self.main_calls += 1
            return types.SimpleNamespace(content=_PLAN_JSON)

        return main_complete


def test_plan_deepthink_routes_proposals_to_deepthink_model(tmp_path, monkeypatch) -> None:
    dt = _deepthink_config()
    config = _main_config(dt)
    engine = _RecordingEngine({"main-model": _BOGUS_JSON, "deepthink-model": _PLAN_JSON})
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    result = _run(tmp_path, config)

    assert result.converged is True
    assert [i.id for i in result.plan_items] == ["t1", "t2"]

    # Exactly two make_complete BUILDS: the main seam (never invoked for the
    # actual proposal) and the deepthink seam that answers it.
    assert len(engine.calls) == 2
    main_built, dt_built = engine.calls
    assert main_built == (config, None)
    dt_config_used, tools_used = dt_built
    assert dt_config_used.model == dt.model
    assert dt_config_used.base_url == dt.base_url
    assert dt_config_used.context_budget_tokens == dt.context_budget
    assert tools_used == []


def test_plan_no_deepthink_call_shape_byte_identical(tmp_path, monkeypatch) -> None:
    config = _main_config(None)
    engine = _NoToolsKwargEngine()
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    result = _run(tmp_path, config)

    assert result.converged is True
    # Exactly one build, positional-only (no `tools` kwarg was passed — else
    # _NoToolsKwargEngine.make_complete would have raised TypeError).
    assert len(engine.calls) == 1
    assert engine.calls[0] is config


def test_plan_deepthink_fallback_on_raise(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _main_config(_deepthink_config())
    engine = _FallbackEngine()
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    result = _run(tmp_path, config)

    assert result.converged is True
    assert [i.id for i in result.plan_items] == ["t1", "t2"]
    assert engine.deepthink_calls >= 1
    assert engine.main_calls >= 1

    err = capsys.readouterr().err
    assert err.count("plan: deepthink unreachable; falling back to main model") == 1


def test_plan_deepthink_info_line_only_with_dual_config(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dt = _deepthink_config()
    config = _main_config(dt)
    engine = _RecordingEngine({"main-model": _PLAN_JSON, "deepthink-model": _PLAN_JSON})
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    _run(tmp_path, config)

    err = capsys.readouterr().err
    assert f"plan: proposals via deepthink model {dt.model}" in err


def test_plan_no_deepthink_info_line_absent(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _main_config(None)
    engine = _NoToolsKwargEngine()
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    _run(tmp_path, config)

    err = capsys.readouterr().err
    assert "plan: proposals via deepthink model" not in err


def test_plan_dual_config_with_legacy_engine_degrades_never_raises(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Degrade-never-raise covers the BUILD too (spec c13/h5): an out-of-tree
    engine whose ``make_complete(config)`` predates the ``tools`` parameter
    raises ``TypeError`` when the deepthink route is built — the route must
    degrade the whole run to the main model, not crash ``colleague plan``.
    """
    config = _main_config(_deepthink_config())
    engine = _NoToolsKwargEngine()  # legacy 1-arg make_complete + dual config
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    result = _run(tmp_path, config)  # must not raise

    assert result.converged is True
    assert [i.id for i in result.plan_items] == ["t1", "t2"]
    # Only the main-model build landed (the tools-off build raised before
    # recording); the main model answered every proposal.
    assert engine.calls == [config]

    err = capsys.readouterr().err
    assert "plan: deepthink completion unavailable" in err
    assert "plan: proposals via deepthink model" not in err  # route never armed


class _WindowProbeEngine:
    """Captures the messages the deepthink completion actually receives, with
    a 1-token-per-content-char counter so the budget arithmetic is exact.
    """

    name = "fake"

    def __init__(self, fail_deepthink: bool = False) -> None:
        self.deepthink_received: list[list[dict]] = []
        self._fail = fail_deepthink

    def make_complete(self, config, tools=None):
        def complete(messages):
            self.deepthink_received.append(messages)
            if self._fail:
                raise TimeoutError("deepthink endpoint unreachable")
            return types.SimpleNamespace(content=_PLAN_JSON)

        return complete

    def make_count_tokens(self, config):
        return lambda messages: sum(len(str(m.get("content") or "")) for m in messages)


def test_route_windows_oversized_proposals_to_the_deepthink_budget(capsys) -> None:
    """Spec h4 holds for plan-mode too: a proposal prompt bigger than the
    deepthink model's own context budget is windowed BEFORE the request is
    sent — the last user message truncated with the visible note, the other
    turns untouched.
    """
    config = _main_config(_deepthink_config(context_budget=100))  # send budget 75
    engine = _WindowProbeEngine()

    def complete_main(_messages):  # pragma: no cover - deepthink answers
        raise AssertionError("main model must not answer a successful deepthink call")

    route = _route_proposals_through_deepthink(engine, config, complete_main)
    response = route(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 10_000},
        ]
    )

    assert response.content == _PLAN_JSON
    (received,) = engine.deepthink_received
    assert received[0] == {"role": "system", "content": "sys"}
    assert "[deepthink digest truncated to fit budget]" in received[1]["content"]
    counter = engine.make_count_tokens(None)
    assert counter(received) <= 75


def test_route_fallback_hands_main_the_original_unwindowed_messages(capsys) -> None:
    """The fallback targets the MAIN model's wide window — it must receive the
    ORIGINAL messages, never the deepthink-truncated copy.
    """
    config = _main_config(_deepthink_config(context_budget=100))
    engine = _WindowProbeEngine(fail_deepthink=True)
    main_received: list[list[dict]] = []

    def complete_main(messages):
        main_received.append(messages)
        return types.SimpleNamespace(content=_PLAN_JSON)

    route = _route_proposals_through_deepthink(engine, config, complete_main)
    original = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "x" * 10_000},
    ]
    route(original)

    (received,) = main_received
    assert received is original  # untruncated, same object
    assert received[1]["content"] == "x" * 10_000

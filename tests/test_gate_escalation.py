"""#484 t9 — gate-failure escalation + the fill-line spike wiring.

Task t5 shipped the table (:mod:`colleague.effortspikes`); t8 wired its first
point (the pre-mutation barrier). This file covers the remaining two, both
carried by :mod:`colleague.loop_gateescalation`:

AC1 — **gate.repeat_failure.** The FIRST gate repair runs at the seat's
ordinary rung (unchanged behaviour). A REPEATED failure — the deterministic
signal being the fix-turn loop's ITERATION COUNT, never the report's content —
gets ONE ``"medium"`` replan per gate per run, and each firing lands on
``TaskResult.effort_spikes`` as ``{point, rung, seat}``.

AC2 — **fillline.decision.** The fill-line decision point consumes the
EXISTING ``DESIGN_SITE_TABLE['fillline.split']`` contract through the shipped
builder :func:`colleague.fillline.design_seat_config` (so the c32 override /
kill-switch precedence is resolved once, in one place) rather than
duplicating a rung; ``tests/test_design_call_site.py`` names that live
consumer.

Unarmed (``COLLEAGUE_EFFORT_SPIKES`` unset — the default) everything here is a
strict no-op: no escalator is bound, the acting config never gains the
``reasoning_effort_seat`` attribute, and ``effort_spikes`` stays empty.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from colleague import effortspikes
from colleague import loop_gateescalation as _esc
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult
from colleague.loop_types import ContextControls, _Work
from colleague.tools import ToolExecutor

SPIKE_ENV = "COLLEAGUE_EFFORT_SPIKES"
SEAT_ATTR = "reasoning_effort_seat"


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setenv(SPIKE_ENV, "1")
    monkeypatch.delenv("COLLEAGUE_EFFORT_SPIKE_GATE_REPEAT_FAILURE", raising=False)


@pytest.fixture
def unarmed(monkeypatch):
    monkeypatch.delenv(SPIKE_ENV, raising=False)


def _config(**overrides) -> EngineConfig:
    base = dict(model="cortex-model", base_url="http://main:8001/v1", api_key="k")
    base.update(overrides)
    return EngineConfig(**base)


def _ctx(tmp_path: Path, config: EngineConfig | None = None) -> _Work:
    """A minimal ``_Work`` with the escalator bound the way ``run()`` binds it."""
    config = config if config is not None else _config()
    task = Task.new(str(tmp_path), "do a thing")
    return _Work(
        executor=ToolExecutor(task.repo_path),
        hooks=__import__("colleague.hooks", fromlist=["HookConfig"]).HookConfig(),
        telemetry=__import__("colleague.telemetry", fromlist=["Telemetry"]).Telemetry(),
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        gate_escalation=_esc.make_escalator(config),
    )


def _seat(config) -> object:
    return config.__dict__.get(SEAT_ATTR, "<absent>")


# ---------------------------------------------------------------------------
# The escalator itself: push/pop restores the EXACT prior state
# ---------------------------------------------------------------------------


class TestSeatEscalator:
    def test_unarmed_builds_nothing(self, unarmed):
        assert _esc.make_escalator(_config()) is None

    def test_armed_builds_an_escalator(self, armed):
        assert isinstance(_esc.make_escalator(_config()), _esc.SeatEscalator)

    def test_push_sets_and_pop_removes_an_absent_attribute(self, armed):
        config = _config()
        escalator = _esc.SeatEscalator(config)
        assert SEAT_ATTR not in config.__dict__
        escalator.push("medium")
        assert config.__dict__[SEAT_ATTR] == "medium"
        escalator.pop()
        # Absent before -> absent again, never a planted ``None`` row (which
        # ``_effort_for``'s presence-wins rule would read as send-nothing).
        assert SEAT_ATTR not in config.__dict__

    def test_pop_restores_a_pre_existing_value(self, armed):
        config = _config()
        setattr(config, SEAT_ATTR, "low")
        escalator = _esc.SeatEscalator(config)
        escalator.push("medium")
        assert config.__dict__[SEAT_ATTR] == "medium"
        escalator.pop()
        assert config.__dict__[SEAT_ATTR] == "low"

    def test_pop_without_push_is_a_no_op(self, armed):
        config = _config()
        _esc.SeatEscalator(config).pop()
        assert SEAT_ATTR not in config.__dict__

    def test_pushes_nest(self, armed):
        config = _config()
        escalator = _esc.SeatEscalator(config)
        escalator.push("medium")
        escalator.push("xhigh")
        assert config.__dict__[SEAT_ATTR] == "xhigh"
        escalator.pop()
        assert config.__dict__[SEAT_ATTR] == "medium"
        escalator.pop()
        assert SEAT_ATTR not in config.__dict__


# ---------------------------------------------------------------------------
# AC1 — gate.repeat_failure
# ---------------------------------------------------------------------------


class TestGateEscalation:
    def test_first_repair_runs_at_the_ordinary_rung(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        config = ctx.gate_escalation._config
        with _esc.escalated_gate_turn(ctx, "affected_tests", 1) as fired:
            assert fired is False
            assert _seat(config) == "<absent>"
        assert ctx.result.effort_spikes == []

    def test_repeated_repair_escalates_to_the_table_rung(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        config = ctx.gate_escalation._config
        with _esc.escalated_gate_turn(ctx, "affected_tests", 2) as fired:
            assert fired is True
            assert _seat(config) == effortspikes.SPIKE_TABLE["gate.repeat_failure"] == "medium"
        assert _seat(config) == "<absent>"

    def test_the_firing_lands_on_the_artifact(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        with _esc.escalated_gate_turn(ctx, "affected_tests", 2):
            pass
        assert ctx.result.effort_spikes == [
            {"point": "gate.repeat_failure", "rung": "medium", "seat": "cortex"}
        ]

    def test_at_most_one_escalation_per_gate_per_run(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        fired = []
        for attempt in (2, 3, 4):
            with _esc.escalated_gate_turn(ctx, "affected_tests", attempt) as did:
                fired.append(did)
        assert fired == [True, False, False]
        assert len(ctx.result.effort_spikes) == 1

    def test_each_gate_gets_its_own_at_most_once(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        with _esc.escalated_gate_turn(ctx, "affected_tests", 2) as a:
            pass
        with _esc.escalated_gate_turn(ctx, "test_integrity", 2) as b:
            pass
        assert (a, b) == (True, True)
        assert len(ctx.result.effort_spikes) == 2

    def test_the_escalation_is_released_even_when_the_turn_raises(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        config = ctx.gate_escalation._config

        def _blow_up_inside_escalation() -> None:
            with _esc.escalated_gate_turn(ctx, "affected_tests", 2):
                raise RuntimeError("fix turn blew up")

        with pytest.raises(RuntimeError):
            _blow_up_inside_escalation()
        assert _seat(config) == "<absent>"

    def test_unarmed_is_a_strict_no_op(self, tmp_path, unarmed):
        ctx = _ctx(tmp_path)
        assert ctx.gate_escalation is None
        with _esc.escalated_gate_turn(ctx, "affected_tests", 5) as fired:
            assert fired is False
        assert ctx.result.effort_spikes == []

    def test_the_rung_comes_only_from_the_spike_table(self, tmp_path, armed, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_EFFORT_SPIKE_GATE_REPEAT_FAILURE", "xhigh")
        ctx = _ctx(tmp_path)
        config = ctx.gate_escalation._config
        with _esc.escalated_gate_turn(ctx, "affected_tests", 2):
            assert _seat(config) == "xhigh"
        assert ctx.result.effort_spikes[0]["rung"] == "xhigh"


# ---------------------------------------------------------------------------
# AC2 — fillline.decision consumes the design-site contract
# ---------------------------------------------------------------------------


class TestFilllineDecision:
    def test_it_reads_the_design_site_builder_not_the_spike_table(self, armed):
        # The spike table REFUSES to resolve this point (it holds the delegation
        # sentinel); the rung must come from the design-site builder instead.
        assert effortspikes.resolve_spike("fillline.decision") is None
        assert _esc.SeatEscalator(_config()).fillline_rung() == "xhigh"

    def test_arming_pushes_the_design_rung_and_records_it(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        config = ctx.gate_escalation._config
        assert _esc.arm_fillline_decision(ctx) is True
        assert _seat(config) == "xhigh"
        assert ctx.result.effort_spikes == [
            {"point": "fillline.decision", "rung": "xhigh", "seat": "cortex"}
        ]

    def test_disarming_releases_it(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        config = ctx.gate_escalation._config
        _esc.arm_fillline_decision(ctx)
        _esc.disarm_fillline_decision(ctx)
        assert _seat(config) == "<absent>"

    def test_disarm_without_arm_is_a_no_op(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        _esc.disarm_fillline_decision(ctx)
        assert _seat(ctx.gate_escalation._config) == "<absent>"

    def test_at_most_once_per_run(self, tmp_path, armed):
        ctx = _ctx(tmp_path)
        assert _esc.arm_fillline_decision(ctx) is True
        _esc.disarm_fillline_decision(ctx)
        assert _esc.arm_fillline_decision(ctx) is False
        assert len(ctx.result.effort_spikes) == 1

    def test_the_kill_switch_declines(self, tmp_path, armed):
        config = _config(reasoning_effort="default", reasoning_effort_seats={"design": "xhigh"})
        ctx = _ctx(tmp_path, config)
        assert _esc.arm_fillline_decision(ctx) is False
        assert _seat(config) == "<absent>"
        assert ctx.result.effort_spikes == []

    def test_unarmed_is_a_strict_no_op(self, tmp_path, unarmed):
        ctx = _ctx(tmp_path)
        assert ctx.gate_escalation is None
        assert _esc.arm_fillline_decision(ctx) is False
        assert ctx.result.effort_spikes == []


# ---------------------------------------------------------------------------
# The live seams: the two gate fix-turn loops + the fill-line offer/record
# ---------------------------------------------------------------------------


class _Report:
    """A minimal affected-tests report the gate loop is happy to consume."""

    def __init__(self, status="failed"):
        self.status = status
        self.selected = ["tests/test_x.py"]
        self.failed = 1
        self.passed = 0
        self.skipped_reason = None
        self.findings: list[object] = []


def _gate_ctx(tmp_path: Path, armed_config: EngineConfig, **kwargs) -> _Work:
    task = Task.new(str(tmp_path), "fix the tests")
    from colleague.hooks import HookConfig
    from colleague.telemetry import Telemetry

    return _Work(
        executor=ToolExecutor(task.repo_path),
        hooks=HookConfig(),
        telemetry=Telemetry(),
        task=task,
        result=TaskResult(task_id=task.id, status="ok"),
        messages=[],
        gate_escalation=_esc.make_escalator(armed_config),
        **kwargs,
    )


class TestAffectedTestsFixTurnSeam:
    """The affected-tests gate's fix-turn loop actually escalates the 2nd repair."""

    def _drive(self, tmp_path, monkeypatch, config, retries=3):
        from colleague import loop_testgates

        ctx = _gate_ctx(
            tmp_path,
            config,
            affectedtests_enabled=True,
            affectedtests_fix_retries=retries,
        )
        monkeypatch.setattr(loop_testgates, "_gate_changed_set", lambda _ctx: {"colleague/a.py"})
        monkeypatch.setattr(
            loop_testgates._affectedtests,
            "run_affected_tests",
            lambda *_a, **_k: _Report("failed"),
        )
        monkeypatch.setattr(
            loop_testgates._testgates_warnings, "surface_affected_tests", lambda _r: None
        )
        seen: list[object] = []

        def work_loop(_ctx, _complete, _budget):
            seen.append(config.__dict__.get(SEAT_ATTR, "<absent>"))
            return "finished"

        loop_testgates._maybe_run_affected_tests_gate(
            ctx, lambda _m: None, "finished", None, work_loop=work_loop
        )
        return ctx, seen

    def test_first_repair_ordinary_then_one_escalated_repair(self, tmp_path, monkeypatch, armed):
        config = _config()
        ctx, seen = self._drive(tmp_path, monkeypatch, config)
        assert seen == ["<absent>", "medium", "<absent>"]
        assert ctx.result.effort_spikes == [
            {"point": "gate.repeat_failure", "rung": "medium", "seat": "cortex"}
        ]
        assert SEAT_ATTR not in config.__dict__

    def test_unarmed_never_escalates(self, tmp_path, monkeypatch, unarmed):
        config = _config()
        ctx, seen = self._drive(tmp_path, monkeypatch, config)
        assert seen == ["<absent>", "<absent>", "<absent>"]
        assert ctx.result.effort_spikes == []


class TestTestIntegrityFixTurnSeam:
    """The test-integrity gate shares the loop shape, so it is wired identically."""

    def _drive(self, tmp_path, monkeypatch, config, retries=3):
        from colleague import loop_testgates

        class _Finding:
            symbol, kind, test_file, impl_file = "x", "attr", "t.py", "m.py"

        class _MirrorReport:
            findings = [_Finding()]

        ctx = _gate_ctx(
            tmp_path,
            config,
            testintegrity_enabled=True,
            testintegrity_fix_retries=retries,
        )
        monkeypatch.setattr(loop_testgates, "_gate_changed_set", lambda _ctx: {"colleague/a.py"})
        monkeypatch.setattr(
            loop_testgates._testintegrity, "detect_mirror", lambda *_a, **_k: _MirrorReport()
        )
        monkeypatch.setattr(
            loop_testgates._testgates_warnings, "surface_test_integrity", lambda _r: None
        )
        seen: list[object] = []

        def work_loop(_ctx, _complete, _budget):
            seen.append(config.__dict__.get(SEAT_ATTR, "<absent>"))
            return "finished"

        loop_testgates._maybe_run_test_integrity_gate(
            ctx, lambda _m: None, "finished", None, work_loop=work_loop
        )
        return ctx, seen

    def test_first_repair_ordinary_then_one_escalated_repair(self, tmp_path, monkeypatch, armed):
        config = _config()
        ctx, seen = self._drive(tmp_path, monkeypatch, config)
        assert seen == ["<absent>", "medium", "<absent>"]
        assert ctx.result.effort_spikes == [
            {"point": "gate.repeat_failure", "rung": "medium", "seat": "cortex"}
        ]

    def test_unarmed_never_escalates(self, tmp_path, monkeypatch, unarmed):
        config = _config()
        ctx, seen = self._drive(tmp_path, monkeypatch, config)
        assert seen == ["<absent>", "<absent>", "<absent>"]
        assert ctx.result.effort_spikes == []


class TestFilllineLoopSeam:
    """``_offer_fillline`` arms the declaring turn; ``_record_fillline_decision`` releases it."""

    def _ctx(self, tmp_path, config):
        return _gate_ctx(
            tmp_path,
            config,
            context_budget=1000,
            capacity_threshold=0.8,
            autosplit_target=4000,
        )

    def test_the_declaring_turn_carries_the_design_rung(self, tmp_path, armed):
        from colleague import loop_context

        config = _config()
        ctx = self._ctx(tmp_path, config)
        loop_context._offer_fillline(ctx, 900)
        assert config.__dict__.get(SEAT_ATTR) == "xhigh"
        assert ctx.result.effort_spikes == [
            {"point": "fillline.decision", "rung": "xhigh", "seat": "cortex"}
        ]
        loop_context._record_fillline_decision(ctx, "compact")
        # Released before the compaction turn that may follow.
        assert SEAT_ATTR not in config.__dict__

    def test_unarmed_offer_touches_nothing(self, tmp_path, unarmed):
        from colleague import loop_context

        config = _config()
        ctx = self._ctx(tmp_path, config)
        loop_context._offer_fillline(ctx, 900)
        assert SEAT_ATTR not in config.__dict__
        assert ctx.result.effort_spikes == []
        loop_context._record_fillline_decision(ctx, "compact")
        assert SEAT_ATTR not in config.__dict__

    def test_from_config_binds_the_escalator_only_when_armed(self, monkeypatch):
        monkeypatch.delenv(SPIKE_ENV, raising=False)
        assert ContextControls.from_config(_config()).gate_escalation is None
        monkeypatch.setenv(SPIKE_ENV, "1")
        assert ContextControls.from_config(_config()).gate_escalation is not None


# ---------------------------------------------------------------------------
# No model-reachable rung parameter (the boundary sweep)
# ---------------------------------------------------------------------------


def test_no_public_function_accepts_a_rung_parameter() -> None:
    """No public entry point here takes a rung/effort argument — the two values
    come from the two FIXED tables and nowhere else, so nothing a model emits
    can reach the wire as an effort key. ``SeatEscalator.push`` is internal
    (called only by this module's own two firing paths)."""
    offenders = []
    for name, obj in vars(_esc).items():
        if (
            name.startswith("_")
            or not callable(obj)
            or getattr(obj, "__module__", "") != _esc.__name__
        ):
            continue
        target = obj.__wrapped__ if hasattr(obj, "__wrapped__") else obj
        if inspect.isclass(target):
            continue
        params = set(inspect.signature(target).parameters)
        if params & {"rung", "effort", "reasoning_effort", "reasoning_effort_seat"}:
            offenders.append(name)
    assert offenders == [], offenders


def test_the_module_holds_no_effort_string_literal() -> None:
    """The rungs are never written down here — they come from
    ``effortspikes.SPIKE_TABLE`` / ``fillline.design_seat_config``."""
    source = Path(_esc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not literals & {"off", "low", "medium", "high", "xhigh"}

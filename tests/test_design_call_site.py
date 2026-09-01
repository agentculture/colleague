"""Design call-site thinking-effort tests (#416 t6, spec c14/h9).

Covers:

* :data:`colleague.design.DESIGN_CALL_SITES` + :func:`colleague.design.design_effort`
  return the c36 rungs per site, and reject an unknown site.
* :func:`colleague.design.design_seat_config` sets ``reasoning_effort_seat``
  correctly even when the acting seat's OWN effective effort is
  ``"off"``/``"medium"`` (the design site is independent of the acting
  seat), keeps the seat on the SAME model/base_url (unlike deepthink/senses,
  which switch to a declared child endpoint), and honors the c32 precedence
  order (an operator ``reasoning_effort_seats["design"]`` override, or the
  global kill switch, wins over the table).
* One payload test per plan stage (``plan.spec_stage`` / ``plan.plan_stage``)
  proving the completion built for that stage actually carries the design
  effort in the wire payload / the ``make_complete`` build.
* ``autosplit.design_seat_config`` / ``subagents.decomposition_seat_config`` /
  ``plan.workforce.design_seat_config`` are pinned at the BUILDER level (the
  current architecture dispatches those sites as ordinary per-turn messages or
  full child ``Task``s with their own role effort — see each module's own
  docstring for the honest limit).
* ``fillline.design_seat_config`` is pinned at the builder level too AND named
  with its LIVE consumer (#484 t9): ``loop_gateescalation.SeatEscalator``
  reads this builder's resolved rung — table, operator override and kill
  switch alike — and pushes it onto the acting config for exactly the
  fill-line declaring turn.
* A structural guard: every call to :func:`colleague.design.design_seat_config`
  anywhere in :mod:`colleague` (outside ``design.py`` itself) passes a site
  string literal that is a member of :data:`DESIGN_CALL_SITES` — adding a
  call site means editing the constant, never passing an ad-hoc string.
"""

from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

from colleague import autosplit as _autosplit
from colleague import fillline as _fillline
from colleague import loop_gateescalation as _gateescalation
from colleague import subagents as _subagents
from colleague.cli._commands.plan import run_plan_request
from colleague.cli._errors import CliError
from colleague.config import EngineConfig
from colleague.design import DESIGN_CALL_SITES, design_effort, design_seat_config
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.plan import workforce as _plan_workforce

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLEAGUE_DIR = REPO_ROOT / "colleague"

# ---------------------------------------------------------------------------
# DESIGN_CALL_SITES + design_effort per site (c36)
# ---------------------------------------------------------------------------

_EXPECTED_RUNGS = {
    "plan.spec_stage": "xhigh",
    "plan.plan_stage": "high",
    "plan.workforce": "xhigh",
    "autosplit": "xhigh",
    "fillline.split": "xhigh",
    "subagents.decompose": "xhigh",
}


def test_design_call_sites_is_the_closed_set() -> None:
    assert DESIGN_CALL_SITES == frozenset(_EXPECTED_RUNGS)


@pytest.mark.parametrize("site,rung", sorted(_EXPECTED_RUNGS.items()))
def test_design_effort_per_site(site: str, rung: str) -> None:
    assert design_effort(site) == rung


def test_design_effort_unknown_site_raises_cli_error() -> None:
    with pytest.raises(CliError) as excinfo:
        design_effort("not.a.site")
    assert "not.a.site" in str(excinfo.value)
    for site in DESIGN_CALL_SITES:
        assert site in str(excinfo.value)


# ---------------------------------------------------------------------------
# design_seat_config: independent of the acting seat's own effort, same
# model/base_url, c32 precedence honored.
# ---------------------------------------------------------------------------


def _config(**overrides) -> EngineConfig:
    base = dict(model="cortex-model", base_url="http://main:8001/v1", api_key="main-key")
    base.update(overrides)
    return EngineConfig(**base)


def _effort(seat_config: EngineConfig) -> str | None:
    return getattr(seat_config, "reasoning_effort_seat", None)


@pytest.mark.parametrize("site,rung", sorted(_EXPECTED_RUNGS.items()))
def test_design_seat_carries_its_table_rung(site: str, rung: str) -> None:
    seat = design_seat_config(_config(), site)
    assert _effort(seat) == rung


def test_design_seat_independent_of_acting_effort_off() -> None:
    """Even with the ACTING seat's own effective effort at 'off' (senses-like),
    the design seat still carries its OWN table rung — the design site is
    resolved independently of the acting dial."""
    seat = design_seat_config(_config(reasoning_effort="off"), "plan.spec_stage")
    assert _effort(seat) == "xhigh"


def test_design_seat_independent_of_acting_effort_medium() -> None:
    seat = design_seat_config(_config(reasoning_effort="medium"), "plan.plan_stage")
    assert _effort(seat) == "high"


def test_design_seat_operator_override_wins() -> None:
    seat = design_seat_config(_config(reasoning_effort_seats={"design": "low"}), "plan.spec_stage")
    assert _effort(seat) == "low"


def test_design_seat_kill_switch_unsets() -> None:
    seat = design_seat_config(
        _config(reasoning_effort="default", reasoning_effort_seats={"design": "xhigh"}),
        "plan.workforce",
    )
    assert _effort(seat) is None


def test_design_seat_stays_on_the_same_model_and_base_url() -> None:
    """Unlike deepthink/senses (which switch to a declared child endpoint),
    a design seat ALWAYS stays on the cortex/acting seat's own model —
    a design call reasons harder about the same task, it doesn't need a
    different model."""
    cfg = _config(model="cortex-model", base_url="http://main:8001/v1", api_key="main-key")
    seat = design_seat_config(cfg, "autosplit")
    assert seat.model == cfg.model
    assert seat.base_url == cfg.base_url
    assert seat.api_key == cfg.api_key


def test_design_seat_clears_on_delta_and_refresh_seat() -> None:
    cfg = _config(on_delta=lambda _t: None, refresh_seat="main")
    seat = design_seat_config(cfg, "autosplit")
    assert seat.on_delta is None
    assert seat.refresh_seat is None


# ---------------------------------------------------------------------------
# Payload test per plan stage: the completion actually built for that stage
# carries the design effort.
# ---------------------------------------------------------------------------


def test_spec_stage_payload_carries_xhigh_reasoning_effort() -> None:
    seat = design_seat_config(_config(), "plan.spec_stage")
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(
        seat, [{"role": "user", "content": "hi"}], []
    )
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "xhigh"}


def test_plan_stage_payload_carries_high_reasoning_effort() -> None:
    seat = design_seat_config(_config(), "plan.plan_stage")
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(
        seat, [{"role": "user", "content": "hi"}], []
    )
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "high"}


class _RecordingEngine:
    """Records ``(config, tools)`` per ``make_complete`` call and answers with
    valid plan JSON keyed by which design seat built the completion — proves
    ``run_plan_request`` actually wires the design seat into the LIVE build,
    not merely that the builder function works in isolation.
    """

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[EngineConfig, list | None]] = []

    def make_complete(self, config, tools=None):
        self.calls.append((config, tools))

        def complete(_messages):
            return types.SimpleNamespace(
                content='{"items": [{"id": "t1", "summary": "do A", '
                '"acceptance": ["A works"], "deps": []}]}'
            )

        return complete


def _decide(*_args, **_kwargs) -> str:
    return "confirm"


def test_run_plan_request_plan_stage_build_carries_design_effort(tmp_path, monkeypatch) -> None:
    """quick=True: only the plan-stage design seat is built (the spec-stage
    build is skipped, matching the pre-#416 call count exactly) and it
    carries the ``plan.plan_stage`` rung."""
    config = EngineConfig(model="m", base_url="http://main:8001/v1", api_key="k")
    engine = _RecordingEngine()
    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    result = run_plan_request(
        repo=tmp_path,
        request="build a feature",
        engine_name="fake",
        config=config,
        decide=_decide,
        quick=True,
        workforce=False,
    )

    assert result.converged is True
    assert len(engine.calls) == 1
    built_config, tools = engine.calls[0]
    assert tools is None
    assert getattr(built_config, "reasoning_effort_seat", None) == design_effort("plan.plan_stage")


def test_run_plan_request_spec_stage_build_carries_design_effort_when_not_quick(
    tmp_path, monkeypatch
) -> None:
    """quick=False: the spec-stage design seat IS built (first call), then the
    plan-stage seat (second call)."""
    config = EngineConfig(model="m", base_url="http://main:8001/v1", api_key="k")
    engine = _RecordingEngine()

    def fail_complete(_messages):
        raise ValueError("spec-stage call not exercised by this test")

    monkeypatch.setattr("colleague.registry.load", lambda _name: engine)

    # We only assert on the BUILD (not the runtime proposal parsing), so a
    # ValueError from an unusable claims proposal is fine here — catch the
    # CliError it surfaces after recording the build.
    try:
        run_plan_request(
            repo=tmp_path,
            request="build a feature",
            engine_name="fake",
            config=config,
            decide=_decide,
            quick=False,
            workforce=False,
        )
    except CliError:
        pass

    assert len(engine.calls) >= 1
    spec_built, _tools = engine.calls[0]
    assert getattr(spec_built, "reasoning_effort_seat", None) == design_effort("plan.spec_stage")


# ---------------------------------------------------------------------------
# Builder-level pins: autosplit / subagents.decompose / plan.workforce (no live
# call site consumes THOSE THREE today — see each module's own docstring for
# the honest limit).
#
# ``fillline.split`` is the exception as of #484 t9: it HAS a live consumer,
# :meth:`colleague.loop_gateescalation.SeatEscalator.fillline_rung`, which
# reads this builder's rung and pushes it onto the acting config for exactly
# the fill-line declaring turn. Named below.
# ---------------------------------------------------------------------------


def test_autosplit_design_seat_config_pinned_at_builder_level() -> None:
    seat = _autosplit.design_seat_config(_config())
    assert _effort(seat) == "xhigh"
    assert seat.model == "cortex-model"


def test_fillline_design_seat_config_pinned_at_builder_level() -> None:
    seat = _fillline.design_seat_config(_config())
    assert _effort(seat) == "xhigh"
    assert seat.model == "cortex-model"


def test_fillline_design_seat_config_has_a_live_consumer() -> None:
    """The ``fillline.split`` row is no longer consumer-less (#484 t9).

    ``SeatEscalator.fillline_rung`` is the live consumer: it must return
    exactly what ``fillline.design_seat_config`` resolves — the table rung, the
    operator override, and ``None`` under the kill switch — because it reads
    that builder rather than the table (so the two can never drift).
    """
    cfg = _config()
    assert _gateescalation.SeatEscalator(cfg).fillline_rung() == _effort(
        _fillline.design_seat_config(cfg)
    )
    assert _gateescalation.SeatEscalator(cfg).fillline_rung() == design_effort("fillline.split")

    override = _config(reasoning_effort_seats={"design": "low"})
    assert _gateescalation.SeatEscalator(override).fillline_rung() == "low"

    killed = _config(reasoning_effort="default", reasoning_effort_seats={"design": "xhigh"})
    assert _gateescalation.SeatEscalator(killed).fillline_rung() is None


def test_subagents_decomposition_seat_config_pinned_at_builder_level() -> None:
    seat = _subagents.decomposition_seat_config(_config())
    assert _effort(seat) == "xhigh"
    assert seat.model == "cortex-model"


def test_plan_workforce_design_seat_config_pinned_at_builder_level() -> None:
    seat = _plan_workforce.design_seat_config(_config())
    assert _effort(seat) == "xhigh"
    assert seat.model == "cortex-model"


# ---------------------------------------------------------------------------
# Structural guard: every design_seat_config call site passes a literal
# member of DESIGN_CALL_SITES (c14/h9).
# ---------------------------------------------------------------------------


def _colleague_py_files() -> list[Path]:
    return sorted(p for p in COLLEAGUE_DIR.rglob("*.py") if p.is_file())


def _design_seat_config_call_sites(tree: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        if name in ("design_seat_config", "_design_seat_config"):
            calls.append(node)
    return calls


def test_every_design_seat_config_call_passes_a_known_site_literal() -> None:
    """Every module OTHER than ``design.py`` calling ``design_seat_config`` /
    the aliased ``_design_seat_config`` passes a SITE STRING LITERAL that is a
    member of :data:`DESIGN_CALL_SITES` — adding a call site means editing the
    constant, never passing an ad-hoc effort string at the call site."""
    offenders: list[str] = []
    checked_any = False
    for path in _colleague_py_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == "colleague/design.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _design_seat_config_call_sites(tree):
            args = list(call.args)
            # design_seat_config(config, site) OR design_seat_config(config)
            # (a per-module wrapper hard-codes its own site internally, which
            # is itself checked by the wrapper's own dedicated site-value test
            # above — nothing to check here at the call-site level).
            if len(args) < 2:
                continue
            checked_any = True
            site_arg = args[1]
            if not (isinstance(site_arg, ast.Constant) and isinstance(site_arg.value, str)):
                offenders.append(f"{rel}:{call.lineno}: non-literal site argument")
                continue
            if site_arg.value not in DESIGN_CALL_SITES:
                offenders.append(
                    f"{rel}:{call.lineno}: unknown site literal {site_arg.value!r} "
                    "-- add it to colleague.design.DESIGN_CALL_SITES first"
                )
    assert checked_any, "the scanner found no design_seat_config(config, site) call at all"
    assert not offenders, "\n".join(offenders)

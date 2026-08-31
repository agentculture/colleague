"""Per-seat thinking effort on the MAIN seat builders (#416 t4, c3/h3).

Each of the five ``dataclasses.replace`` seat builders carries its own
seat-table rung via the plain ``reasoning_effort_seat`` attribute that
``colleague.engines.vllm_openai._effort_for`` honors ahead of the acting
seat's resolved rung (``EngineConfig.reasoning_effort_effective``):

- ``deepthink_engine_config`` → seat "deepthink" (xhigh default);
- ``senses_engine_config`` → seat "senses" (off default);
- ``tae_loop.seat_engine_config`` → "senses" for the front, "evaluator"
  for the evaluator (low default since v4, #475); the TAE worker needs no attribute
  because with the mode armed the ACTING dial IS the TAE worker;
- ``agents.runtime.agent_engine_config`` → the profile purpose's seat
  (talker→senses, thinker_coder→cortex, worker→worker).

Every test asserts the seat's resolved default rung AND that an operator
per-seat override (``config.reasoning_effort_seats``) wins over it.
"""

from types import SimpleNamespace

from colleague.agents.profile import AgentProfile, resolve_profile
from colleague.agents.runtime import agent_engine_config
from colleague.config import DeepthinkConfig, EngineConfig, SensesConfig
from colleague.deepthink import deepthink_engine_config
from colleague.lobes import RoleInfo
from colleague.senses import senses_engine_config
from colleague.tae_loop import seat_engine_config


def _effort(seat_config: EngineConfig) -> str | None:
    """The rung ``vllm_openai._effort_for`` would send for *seat_config*."""
    return getattr(seat_config, "reasoning_effort_seat", None)


# ---------------------------------------------------------------------------
# deepthink_engine_config → seat "deepthink" (xhigh default)
# ---------------------------------------------------------------------------


def _deepthink_config(**overrides) -> EngineConfig:
    base = dict(
        model="main-model",
        base_url="http://main:8001/v1",
        api_key="main-key",
        deepthink=DeepthinkConfig(
            model="dt-model",
            base_url="http://dt:8002/v1",
            api_key="dt-key",
            context_budget=12345,
        ),
    )
    base.update(overrides)
    return EngineConfig(**base)


def test_deepthink_seat_carries_its_table_rung() -> None:
    seat = deepthink_engine_config(_deepthink_config())
    assert seat is not None
    assert _effort(seat) == "xhigh"


def test_deepthink_seat_operator_override_wins() -> None:
    seat = deepthink_engine_config(_deepthink_config(reasoning_effort_seats={"deepthink": "low"}))
    assert seat is not None
    assert _effort(seat) == "low"


def test_deepthink_seat_kill_switch_unsets() -> None:
    seat = deepthink_engine_config(
        _deepthink_config(reasoning_effort="default", reasoning_effort_seats={"deepthink": "low"})
    )
    assert seat is not None
    assert _effort(seat) is None


# ---------------------------------------------------------------------------
# senses_engine_config → seat "senses" (off default)
# ---------------------------------------------------------------------------


def _senses_config(**overrides) -> EngineConfig:
    base = dict(
        model="main-model",
        base_url="http://main:8001/v1",
        api_key="main-key",
        senses=SensesConfig(
            model="senses-model",
            base_url="http://senses:8003/v1",
            api_key="senses-key",
            context_budget=32768,
        ),
    )
    base.update(overrides)
    return EngineConfig(**base)


def test_senses_seat_carries_its_table_rung() -> None:
    seat = senses_engine_config(_senses_config())
    assert seat is not None
    assert _effort(seat) == "off"


def test_senses_seat_operator_override_wins() -> None:
    seat = senses_engine_config(_senses_config(reasoning_effort_seats={"senses": "medium"}))
    assert seat is not None
    assert _effort(seat) == "medium"


def test_senses_seat_kill_switch_unsets() -> None:
    seat = senses_engine_config(
        _senses_config(reasoning_effort="default", reasoning_effort_seats={"senses": "low"})
    )
    assert seat is not None
    assert _effort(seat) is None


# ---------------------------------------------------------------------------
# tae_loop.seat_engine_config → front "senses", evaluator "evaluator" (low, v4)
# ---------------------------------------------------------------------------


def _tae_seat(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        model=f"{name}-model",
        base_url=f"http://{name}:8004/v1",
        api_key=f"{name}-key",
        context=4096,
    )


def _tae_config(**overrides) -> EngineConfig:
    base = dict(model="main-model", base_url="http://main:8001/v1", api_key="main-key")
    base.update(overrides)
    return EngineConfig(**base)


def test_tae_front_seat_carries_senses_rung() -> None:
    seat = seat_engine_config(_tae_config(), _tae_seat("front"), seat_name="senses")
    assert _effort(seat) == "off"


def test_tae_front_seat_operator_override_wins() -> None:
    seat = seat_engine_config(
        _tae_config(reasoning_effort_seats={"senses": "low"}),
        _tae_seat("front"),
        seat_name="senses",
    )
    assert _effort(seat) == "low"


def test_tae_evaluator_seat_carries_its_table_rung() -> None:
    seat = seat_engine_config(_tae_config(), _tae_seat("evaluator"), seat_name="evaluator")
    assert _effort(seat) == "low"  # v4 table rung (#475)


def test_tae_evaluator_seat_operator_override_wins() -> None:
    seat = seat_engine_config(
        _tae_config(reasoning_effort_seats={"evaluator": "xhigh"}),
        _tae_seat("evaluator"),
        seat_name="evaluator",
    )
    assert _effort(seat) == "xhigh"


def test_tae_seat_without_name_carries_no_seat_attribute() -> None:
    """The TAE worker rides the ACTING dial (config.resolve repoints it), so
    a seat built without a name must not pin a seat-table rung — its effort
    resolves through ``reasoning_effort_effective`` as the acting seat."""
    seat = seat_engine_config(_tae_config(), _tae_seat("worker"))
    assert not hasattr(seat, "reasoning_effort_seat")


# ---------------------------------------------------------------------------
# agents.runtime.agent_engine_config → the profile purpose's seat
# ---------------------------------------------------------------------------


def _role(model: str, ready: bool, context: int, endpoint: str = "") -> RoleInfo:
    return RoleInfo(
        model=model,
        endpoint=endpoint,
        path="/v1",
        context=context,
        ready=ready,
        responsibilities=(),
        forbidden_responsibilities=(),
    )


def _advert_roles() -> SimpleNamespace:
    return SimpleNamespace(
        cortex=_role("cortex-model", True, 1048576),
        senses=_role("senses-model", True, 32768),
        worker=_role("worker-model", False, 65536),
    )


def _parent_config(**overrides) -> EngineConfig:
    base = dict(
        base_url="http://localhost:8001/v1",
        api_key="parent-key",
        model="cortex-model",
        context_budget_tokens=131072,
        lobes_gateway_url="http://localhost:8001",
    )
    base.update(overrides)
    return EngineConfig(**base)


def _profile(purpose: str, roles) -> AgentProfile:
    res = resolve_profile(purpose, roles)
    return AgentProfile(
        agent_id="agent-1",
        purpose=purpose,
        model_role=res.model_role,
        resolved_model=res.resolved_model,
        tool_profile=purpose,
        authority_profile="repo_patch_no_publish",
        parent_agent_id=None,
        task_id="task-1",
        fallback_from_role=res.fallback_from_role,
    )


def test_agent_seat_talker_carries_senses_rung() -> None:
    roles = _advert_roles()
    seat = agent_engine_config(_parent_config(), _profile("talker", roles), roles)
    assert _effort(seat) == "off"


def test_agent_seat_talker_operator_override_wins() -> None:
    roles = _advert_roles()
    seat = agent_engine_config(
        _parent_config(reasoning_effort_seats={"senses": "low"}),
        _profile("talker", roles),
        roles,
    )
    assert _effort(seat) == "low"


def test_agent_seat_thinker_coder_carries_cortex_rung() -> None:
    roles = _advert_roles()
    seat = agent_engine_config(_parent_config(), _profile("thinker_coder", roles), roles)
    assert _effort(seat) == "low"  # v4 cortex rung (#475)


def test_agent_seat_thinker_coder_operator_override_wins() -> None:
    roles = _advert_roles()
    seat = agent_engine_config(
        _parent_config(reasoning_effort_seats={"cortex": "xhigh"}),
        _profile("thinker_coder", roles),
        roles,
    )
    assert _effort(seat) == "xhigh"


def test_agent_seat_worker_carries_worker_rung() -> None:
    """The worker purpose falls back to the cortex role (recorded fallback),
    but its SEAT is still "worker" — the purpose, not the resolved role,
    names the seat-table row."""
    roles = _advert_roles()
    seat = agent_engine_config(_parent_config(), _profile("worker", roles), roles)
    assert _effort(seat) == "low"  # v4 worker rung (#475)


def test_agent_seat_worker_operator_override_wins() -> None:
    roles = _advert_roles()
    seat = agent_engine_config(
        _parent_config(reasoning_effort_seats={"worker": "off"}),
        _profile("worker", roles),
        roles,
    )
    assert _effort(seat) == "off"


def test_agent_seat_kill_switch_unsets() -> None:
    roles = _advert_roles()
    seat = agent_engine_config(
        _parent_config(reasoning_effort="default", reasoning_effort_seats={"cortex": "xhigh"}),
        _profile("thinker_coder", roles),
        roles,
    )
    assert _effort(seat) is None

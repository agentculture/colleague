"""Top-level review/explore reason at ``low`` on the acting seat (2026-08-30).

The operator's rule: the associate seat is the fast reviewer; whenever it is
not taken, cortex above ``low`` is slow — so a top-level ``--role reviewer``
and the read-only ``--mode explore|review`` resolve ``low`` unless an explicit
override (or the kill-switch) says otherwise. Everything else is byte-identical.
"""

from __future__ import annotations

from colleague import effort
from colleague.config import EngineConfig


def _acting(**kw):
    base = dict(worker_armed=False, seats={}, global_value=None, role=None)
    base.update(kw)
    return effort.resolve_acting_effort(**base)


def test_unset_run_keeps_the_cortex_default():
    # v4 (#475): the cortex/worker seat default is "low".
    assert _acting() == "low"
    assert _acting(mode="work") == "low"
    assert _acting(mode=None, role=None) == "low"


def test_top_level_reviewer_and_explorer_reason_low():
    assert _acting(role="reviewer") == "low"
    assert _acting(role="explorer") == "low"
    # other top-level roles keep the seat default ("low" since v4, #475)
    assert _acting(role="writer") == "low"
    assert _acting(role="planner") == "low"


def test_read_only_modes_reason_low_without_a_role():
    assert _acting(mode="review") == "low"
    assert _acting(mode="explore") == "low"


def test_explicit_overrides_and_kill_switch_still_win():
    assert _acting(mode="review", seats={"cortex": "off"}) == "off"
    assert _acting(role="reviewer", seats={"cortex": "xhigh"}) == "xhigh"
    assert _acting(mode="review", global_value="high") == "high"
    assert _acting(mode="review", global_value=effort.DEFAULT_SENTINEL) is None
    # a role WITH its own top-level rung wins over the mode; a role without
    # one leaves the read-only-mode rule to apply (review mode is read-only,
    # so a writer role there is contradictory, never a real dispatch)
    assert _acting(mode="review", role="writer") == "low"
    assert _acting(mode="review", role="reviewer") == "low"


def test_worker_seat_follows_the_same_rule():
    assert _acting(worker_armed=True, mode="review") == "low"
    assert _acting(worker_armed=True) == "low"  # v4 seat default (#475)


def test_engine_config_property_reads_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("COLLEAGUE_REASONING_EFFORT", raising=False)
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.mode is None
    assert cfg.reasoning_effort_effective == "low"  # v4 seat default (#475)
    cfg.mode = "review"
    assert cfg.reasoning_effort_effective == "low"
    cfg.mode = None
    cfg.role = "reviewer"
    assert cfg.reasoning_effort_effective == "low"
    # runtime-only: never serialized
    assert "mode" not in cfg.to_dict()

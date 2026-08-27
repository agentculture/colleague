"""t16 — the per-turn output clamp + microcompaction decisions (colleague/turnbudget.py).

Covers plan claims c4/h2 (``max_tokens`` = the seat-aware window clamp; the
kill-switch omits the key; a ``length`` cut escalates once), c48/h35 (the
design/deepthink seats get the higher ceiling), c11/h9 (blank before the
fill-line offer, count recorded, knob restores today's path) and c42/h31 (the
ledger event + rehydration).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague import config as _config
from colleague import microcompact, outputclamp, turnbudget
from colleague.agents.state.ledger import TaskLedger
from colleague.config import EngineConfig
from colleague.design import design_seat_config


def _cfg(**kw) -> EngineConfig:
    return EngineConfig(base_url="http://127.0.0.1:1/v1", model="m", watch=False, **kw)


class _Est:
    """A stand-in for :class:`colleague.tokenestimate.TokenEstimator`."""

    def __init__(self, window: int | None, estimate: int) -> None:
        self.window = window
        self.window_source = "tokenize_max_model_len" if window else None
        self._estimate = estimate

    def __call__(self, messages: list[dict]) -> int:
        return self._estimate


def _estimator(window: int | None, estimate: int) -> _Est:
    return _Est(window, estimate)


# --- seat + window resolution ---------------------------------------------------


def test_acting_seat_is_cortex_unless_worker_or_stamped() -> None:
    cfg = _cfg()
    assert turnbudget.acting_seat(cfg) == "cortex"
    setattr(cfg, "output_seat", "design")
    assert turnbudget.acting_seat(cfg) == "design"
    setattr(cfg, "output_seat", "not-a-seat")
    assert turnbudget.acting_seat(cfg) == "cortex"
    assert turnbudget.acting_seat(SimpleNamespace(worker=object())) == "worker"


def test_design_seat_config_is_stamped_with_the_high_ceiling_seat() -> None:
    seat = design_seat_config(_cfg(), site="plan")
    assert turnbudget.acting_seat(seat) == "design"
    assert outputclamp.seat_ceiling("design") == outputclamp.DEFAULT_DESIGN_OUTPUT_CEILING
    assert turnbudget.max_tokens_for(seat, []) > outputclamp.OUTPUT_TOKEN_CEILING


def test_deepthink_seat_builder_stamps_output_seat() -> None:
    src = Path("colleague/deepthink.py").read_text(encoding="utf-8")
    assert 'setattr(seat, "output_seat", "deepthink")' in src


def test_window_precedence_probe_then_budget_then_default() -> None:
    cfg = _cfg(context_budget_tokens=50_000)
    assert turnbudget.window_for(cfg) == 50_000
    cfg.token_estimator = _estimator(262_144, 10)
    assert turnbudget.window_for(cfg) == 262_144
    cfg.token_estimator = _estimator(None, 10)
    assert turnbudget.window_for(cfg) == 50_000
    bare = SimpleNamespace()
    assert turnbudget.window_for(bare) == turnbudget.DEFAULT_WINDOW


def test_default_window_mirrors_the_config_default_budget() -> None:
    assert turnbudget.DEFAULT_WINDOW == _config._DEFAULT_CONTEXT_BUDGET


def test_prompt_tokens_prefer_the_estimator_and_fall_back_to_chars() -> None:
    cfg = _cfg()
    msgs = [{"role": "user", "content": "x" * 400}]
    assert turnbudget.prompt_tokens_for(cfg, msgs) == 100
    cfg.token_estimator = _estimator(None, 777)
    assert turnbudget.prompt_tokens_for(cfg, msgs) == 777


# --- the clamp -------------------------------------------------------------------


def test_max_tokens_is_the_window_clamp_for_the_acting_seat() -> None:
    cfg = _cfg()
    cfg.token_estimator = _estimator(262_144, 200_000)
    expected = outputclamp.clamp_output_tokens(64_000, 262_144, 200_000)
    assert turnbudget.max_tokens_for(cfg, []) == expected == 49_037


def test_kill_switch_omits_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")
    assert turnbudget.max_tokens_for(_cfg(), []) is None
    assert turnbudget.escalate_on_length({"max_tokens": 10}, _cfg(), _resp("length", 5)) is False


def _resp(finish_reason: str, prompt_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(finish_reason=finish_reason, prompt_tokens=prompt_tokens)


def test_escalate_on_length_raises_once_toward_the_ceiling_never_past_the_window() -> None:
    cfg = _cfg()
    cfg.token_estimator = _estimator(100_000, 10)
    payload = {"max_tokens": 20_000}
    assert turnbudget.escalate_on_length(payload, cfg, _resp("length", 50_000)) is True
    assert payload["max_tokens"] == min(64_000, 100_000 - 50_000) == 50_000
    # A second cut at the escalated value: nothing higher to try -> no retry.
    assert turnbudget.escalate_on_length(payload, cfg, _resp("length", 50_000)) is False


def test_escalate_is_false_when_not_a_length_cut_or_already_at_the_ceiling() -> None:
    cfg = _cfg()
    cfg.token_estimator = _estimator(1_000_000, 10)
    assert turnbudget.escalate_on_length({"max_tokens": 1}, cfg, _resp("stop", 5)) is False
    assert turnbudget.escalate_on_length({}, cfg, _resp("length", 5)) is False
    at_ceiling = {"max_tokens": 64_000}
    assert turnbudget.escalate_on_length(at_ceiling, cfg, _resp("length", 5)) is False
    assert at_ceiling["max_tokens"] == 64_000


# --- microcompaction -------------------------------------------------------------


def _history(n_tool: int) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i in range(n_tool):
        msgs.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": f"f{i}"}),
                        },
                    }
                ],
            }
        )
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"body {i}"})
    return msgs


def test_blank_old_results_is_due_only_at_the_line_and_names_step_indices() -> None:
    msgs = _history(12)
    original = json.loads(json.dumps(msgs))
    assert turnbudget.blank_old_results(msgs, 84, 100) == (0, [])
    assert msgs == original  # under the line: untouched
    count, indices = turnbudget.blank_old_results(msgs, 85, 100)
    assert (count, indices) == (2, [0, 1])
    assert "cleared" in msgs[3]["content"] and "f0" in msgs[3]["content"]
    assert msgs[-1]["content"] == "body 11"  # the recent window keeps its content


def test_blank_old_results_knob_and_no_budget_are_no_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    msgs = _history(12)
    assert turnbudget.blank_old_results(msgs, 99, None) == (0, [])
    assert turnbudget.blank_old_results(msgs, 99, 0) == (0, [])
    monkeypatch.setenv("COLLEAGUE_MICROCOMPACT", "0")
    assert turnbudget.blank_old_results(msgs, 99, 100) == (0, [])
    assert msgs[3]["content"] == "body 0"


def test_microcompact_turn_records_reestimates_and_accumulates_the_total() -> None:
    msgs = _history(12)
    result = SimpleNamespace(warnings=[])
    got = turnbudget.microcompact_turn(msgs, 90, 100, result, None, lambda m: 42)
    assert got == 42
    assert result.warnings == [
        {
            "kind": "microcompaction",
            "blanked": 2,
            "blanked_total": 2,
            "step_indices": [0, 1],
            "keep_recent": microcompact.DEFAULT_KEEP_RECENT,
        }
    ]
    msgs.extend(_history(2)[2:])  # two more tool results -> two more to blank
    got = turnbudget.microcompact_turn(msgs, 90, 100, result, None, None)
    assert got == 90  # no counter: the caller's figure is returned unchanged
    assert result.warnings[-1]["blanked"] == 2 and result.warnings[-1]["blanked_total"] == 4


def test_microcompact_turn_under_the_line_returns_the_input_unchanged() -> None:
    msgs = _history(12)
    result = SimpleNamespace(warnings=[])
    assert turnbudget.microcompact_turn(msgs, 10, 100, result, None, lambda m: 1) == 10
    assert result.warnings == []


# --- the ledger event + rehydration ----------------------------------------------


def test_ledger_blanking_appends_one_event_and_rehydration_reproduces_the_history(
    tmp_path: Path,
) -> None:
    ledger = TaskLedger(tmp_path / "t.jsonl", task_id="t16")
    agents = SimpleNamespace(ledger=ledger)
    msgs = _history(13)
    original = json.loads(json.dumps(msgs))
    result = SimpleNamespace(warnings=[])
    turnbudget.microcompact_turn(msgs, 90, 100, result, agents, None)
    events = [e for e in ledger.events() if e.data.get("subject") == "microcompaction"]
    assert len(events) == 1 and events[0].kind == "evidence"
    assert events[0].data == {
        "subject": "microcompaction",
        "count": 3,
        "step_indices": [0, 1, 2],
        "keep_recent": 10,
    }
    assert ledger.derive() is not None  # an unknown kind never breaks replay
    assert turnbudget.rehydrate_blanking(original, events[0].data) == msgs
    assert turnbudget.ledger_blanking(None, 1, [0]) is False


def test_ledger_failure_is_a_warning_never_a_lost_turn() -> None:
    class Boom:
        def append(self, *_a, **_k):
            raise RuntimeError("disk full")

    msgs = _history(12)
    result = SimpleNamespace(warnings=[])
    got = turnbudget.microcompact_turn(msgs, 90, 100, result, SimpleNamespace(ledger=Boom()), None)
    assert got == 90
    assert [w["kind"] for w in result.warnings] == [
        "microcompaction",
        "microcompaction-ledger-failed",
    ]

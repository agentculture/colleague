"""Tests for the ``colleague plan`` CLI verb (wiring + gate paths).

The engine + batch_spawn are monkeypatched, so these run with no network.
"""

from __future__ import annotations

import json
import types

import pytest

from colleague.cli import main
from colleague.plan import checkpoint as ckpt

# A claims proposal that covers every mandatory kind with an honesty condition on
# each spec-affecting claim — so auto-confirm (--yes) converges the spec gate.
_CLAIMS_JSON = json.dumps(
    {
        "claims": [
            {"id": "c1", "kind": "announcement", "text": "it ships"},
            {"id": "c2", "kind": "audience", "text": "operators"},
            {"id": "c3", "kind": "after_state", "text": "staged"},
            {"id": "c4", "kind": "boundary", "text": "not a daemon"},
            {"id": "c5", "kind": "success_signal", "text": "tests pass"},
            {"id": "c6", "kind": "why_it_matters", "text": "diversity"},
        ],
        "honesty": [{"id": f"h{i}", "claim_id": f"c{i}", "text": "holds"} for i in range(1, 7)],
    }
)

_PLAN_JSON = json.dumps(
    {
        "items": [
            {"id": "t1", "summary": "do A", "acceptance": ["A works"], "deps": []},
            {"id": "t2", "summary": "do B", "acceptance": ["B works"], "deps": ["t1"]},
        ]
    }
)


class _FakeEngine:
    name = "fake"

    def make_complete(self, _config):
        def complete(messages):
            system = messages[0]["content"]
            content = _PLAN_JSON if "plan items" in system else _CLAIMS_JSON
            return types.SimpleNamespace(content=content)

        return complete


def _patch_live_backend(monkeypatch) -> list[list[dict]]:
    """Make the verb resolve a fake live backend + a no-op batch_spawn.

    Returns a list that records the batch_spawn item-lists it was called with.
    """
    calls: list[list[dict]] = []
    monkeypatch.setattr("colleague.registry.load", lambda _name: _FakeEngine())

    def fake_make_batch_spawn(_repo, _config, _engine, *, counter=None):
        def batch_spawn(items, role=None):
            calls.append(items)
            return []

        return batch_spawn

    monkeypatch.setattr("colleague.cli._commands.plan.make_batch_spawn", fake_make_batch_spawn)
    return calls


def test_plan_overview_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan", "overview"]) == 0
    assert "colleague plan" in capsys.readouterr().out


def test_plan_status_no_checkpoint(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan", "status", "--repo", str(tmp_path)]) == 0
    assert "no plan checkpoint" in capsys.readouterr().out


def test_plan_run_mock_needs_live_backend(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["plan", "run", "do a thing", "--engine", "mock", "--yes", "--repo", str(tmp_path)])
    assert rc != 0
    assert "one-shot completions" in capsys.readouterr().err


def test_plan_run_converges_and_fans_out(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _patch_live_backend(monkeypatch)
    rc = main(["plan", "run", "build a feature", "--yes", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "converged: True" in out
    # Two waves (t1 then t2) → batch_spawn invoked once per wave.
    assert len(calls) == 2
    # The checkpoint was persisted under the repo.
    assert (tmp_path / ".colleague" / "plan" / "plan.json").exists()


def test_plan_run_json(tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_live_backend(monkeypatch)
    rc = main(["plan", "run", "build a feature", "--yes", "--json", "--repo", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["converged"] is True
    assert payload["plan_items"] == ["t1", "t2"]
    assert payload["waves"] == [["t1"], ["t2"]]


class _MalformedEngine:
    """A backend that returns un-parseable proposals (no JSON)."""

    name = "fake"

    def make_complete(self, _config):
        return lambda _messages: types.SimpleNamespace(content="sorry, I cannot help with that")


def test_plan_run_malformed_proposal_is_clean_error(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A model that returns no parseable JSON must surface a clean CliError, never a
    # traceback (the agent-first no-traceback contract).
    monkeypatch.setattr("colleague.registry.load", lambda _name: _MalformedEngine())
    monkeypatch.setattr(
        "colleague.cli._commands.plan.make_batch_spawn",
        lambda _r, _c, _e, **_kw: (lambda _items, role=None: []),
    )
    rc = main(["plan", "run", "build a feature", "--yes", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "unusable plan proposal" in err
    assert "Traceback" not in err


def test_plan_run_quick_flag(tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--quick skips the spec stage and goes straight to plan proposal."""
    calls = _patch_live_backend(monkeypatch)
    rc = main(["plan", "run", "build a feature", "--quick", "--yes", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "converged: True" in out
    # With --quick, propose_claims is not called, so the model only gets
    # called for plan items (one call).  batch_spawn still runs per wave.
    assert len(calls) == 2  # two waves from the plan JSON


def test_plan_run_no_spec_alias(tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--no-spec is accepted as an alias for --quick."""
    calls = _patch_live_backend(monkeypatch)
    rc = main(["plan", "run", "build a feature", "--no-spec", "--yes", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "converged: True" in out
    assert len(calls) == 2


def test_plan_run_writes_request_onto_checkpoint(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `plan run` checkpoint records the originating request (#t17), so a later
    `plan continue` can resume without the caller re-typing it."""
    _patch_live_backend(monkeypatch)
    rc = main(["plan", "run", "build a feature", "--yes", "--repo", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()
    cp = ckpt.load("plan", str(tmp_path))
    assert cp is not None
    assert cp.request == "build a feature"


# --- plan continue (#t17) ---------------------------------------------------


def _patch_live_backend_logged(monkeypatch) -> tuple[list[list[dict]], list[str]]:
    """Like ``_patch_live_backend``, but also records every system prompt used
    in a model completion call -- so a test can assert propose_claims (the
    spec-stage gate machinery) was never invoked."""
    calls: list[list[dict]] = []
    system_prompts: list[str] = []

    class _LoggingEngine:
        name = "fake"

        def make_complete(self, _config):
            def complete(messages):
                system = messages[0]["content"]
                system_prompts.append(system)
                content = _PLAN_JSON if "plan items" in system else _CLAIMS_JSON
                return types.SimpleNamespace(content=content)

            return complete

    monkeypatch.setattr("colleague.registry.load", lambda _name: _LoggingEngine())

    def fake_make_batch_spawn(_repo, _config, _engine, *, counter=None):
        def batch_spawn(items, role=None):
            calls.append(items)
            return []

        return batch_spawn

    monkeypatch.setattr("colleague.cli._commands.plan.make_batch_spawn", fake_make_batch_spawn)
    return calls, system_prompts


def test_plan_continue_no_checkpoint_is_clean_error(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`plan continue` refuses cleanly when there is no checkpoint to resume from
    -- that refusal is exactly what distinguishes it from `run` (never a
    traceback)."""
    rc = main(["plan", "continue", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "error:" in err
    assert "hint:" in err
    assert "no plan checkpoint" in err
    assert "Traceback" not in err


def test_plan_continue_no_stored_request_is_clean_error(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A checkpoint that predates the `request` field (or one written by a
    caller that passed repo_path=None) has nothing to resume from -- refuse
    cleanly rather than driving the orchestrator with an empty request."""
    ckpt.save(
        ckpt.Checkpoint(plan_id="plan", recommended_move="plan", resolved_gates=["c1"]),
        tmp_path,
    )
    rc = main(["plan", "continue", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "hint:" in err
    assert "no stored request" in err
    assert "Traceback" not in err


def test_plan_continue_resumes_without_reasking_resolved_gates(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With a prior checkpoint recording 12 resolved spec gates (the simulated
    kill: the spec stage converged and completed, but the run died before the
    workforce fan-out), `plan continue` resumes -- reporting the resumed count
    and never re-asking those gates (no claims-proposal model call is made;
    only the plan-items call runs)."""
    ckpt.save(
        ckpt.Checkpoint(
            plan_id="plan",
            recommended_move="plan",
            resolved_gates=[f"c{i}" for i in range(1, 7)] + [f"h{i}" for i in range(1, 7)],
            request="build a feature",
        ),
        tmp_path,
    )
    calls, system_prompts = _patch_live_backend_logged(monkeypatch)

    rc = main(["plan", "continue", "--yes", "--repo", str(tmp_path)])
    out = capsys.readouterr()

    assert rc == 0
    assert "converged: True" in out.out
    # The resumed-gate count is reported (never silent).
    assert "12" in out.err
    assert "resuming" in out.err
    # No claims-proposal call was made -- every model call was a plan-items
    # proposal call, proving the spec-stage gates were never re-asked.
    assert system_prompts
    assert all("plan items" in sp for sp in system_prompts)
    # The waves still fan out normally.
    assert len(calls) == 2


def test_plan_continue_json(tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    ckpt.save(
        ckpt.Checkpoint(
            plan_id="plan",
            recommended_move="plan",
            resolved_gates=["c1"],
            request="build a feature",
        ),
        tmp_path,
    )
    _patch_live_backend_logged(monkeypatch)
    rc = main(["plan", "continue", "--yes", "--json", "--repo", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["converged"] is True


def test_plan_continue_frame_flag_targets_named_checkpoint(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--frame selects a non-default checkpoint (multiple concurrently-tracked
    plans)."""
    ckpt.save(
        ckpt.Checkpoint(
            plan_id="my-frame",
            recommended_move="plan",
            resolved_gates=["c1"],
            request="build a feature",
        ),
        tmp_path,
    )
    _patch_live_backend_logged(monkeypatch)
    rc = main(["plan", "continue", "--frame", "my-frame", "--yes", "--repo", str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0
    assert "converged: True" in out.out
    assert "my-frame" in out.err


def test_plan_continue_malformed_proposal_is_clean_error(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A resumed run whose backend returns unparseable plan-item JSON still
    surfaces the clean `unusable plan proposal` error, never a traceback."""
    ckpt.save(
        ckpt.Checkpoint(
            plan_id="plan",
            recommended_move="plan",
            resolved_gates=["c1"],
            request="build a feature",
        ),
        tmp_path,
    )
    monkeypatch.setattr("colleague.registry.load", lambda _name: _MalformedEngine())
    monkeypatch.setattr(
        "colleague.cli._commands.plan.make_batch_spawn",
        lambda _r, _c, _e, **_kw: (lambda _items, role=None: []),
    )
    rc = main(["plan", "continue", "--yes", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "unusable plan proposal" in err
    assert "Traceback" not in err


# --- catalog parity: `continue` must not repeat the #185 omission class ----


def test_plan_continue_has_explain_entry() -> None:
    """`colleague explain plan continue` resolves -- a new verb must ship with
    an explain entry (the #185 class of omission: a real verb missing from a
    self-description catalog)."""
    from colleague.explain import known_paths

    assert ("plan", "continue") in known_paths()


def test_plan_continue_explain_renders(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "plan", "continue"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "continue" in out.lower()


def test_plan_mentioned_in_learn_command_map() -> None:
    """`colleague learn`'s command map names `plan` (and `continue`'s resume
    semantics) -- the #185 class of omission (a shipped verb absent from the
    self-teaching command map) must not repeat for this verb."""
    from colleague.cli._commands.learn import _as_json_payload

    payload = _as_json_payload()
    plan_entries = [c for c in payload["commands"] if c["path"][0] == "plan"]
    assert plan_entries, "learn's command map has no entry naming 'plan'"
    assert any("continue" in c["summary"].lower() for c in plan_entries)


def test_plan_continue_mentioned_in_learn_text() -> None:
    """The human-readable `colleague learn` text also names `plan continue`."""
    from colleague.cli._commands.learn import _TEXT

    assert "plan continue" in _TEXT

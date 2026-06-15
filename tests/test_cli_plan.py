"""Tests for the ``colleague plan`` CLI verb (wiring + gate paths).

The engine + batch_spawn are monkeypatched, so these run with no network.
"""

from __future__ import annotations

import json
import types

import pytest

from colleague.cli import main

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

    def fake_make_batch_spawn(_repo, _config, _engine):
        def batch_spawn(items):
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
        lambda _r, _c, _e: (lambda _items: []),
    )
    rc = main(["plan", "run", "build a feature", "--yes", "--repo", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "unusable plan proposal" in err
    assert "Traceback" not in err

"""Tests for the session ``/model`` action (plan task t3).

``/model`` with no argument lists the gateway's served model roster (one line
per id from ``lobes.fetch_served_model_ids``) plus a ``role → model`` line per
role from ``lobes.resolve_roles``, marking the current acting model; a
``None`` roster degrades to ``roster unavailable`` + the current model; an
unarmed lobes rung degrades to ``lobes not armed`` + the current model; and it
never raises. ``/model <id>`` sets ``s.config.model`` AND re-derives
``s.config.context_budget_tokens`` from the matching role's advertised context
window when known (``min(window, current)`` — never grows the budget past the
current value).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from colleague.cli._commands import _session_actions
from colleague.cli._commands.session import SessionIO, _Session
from colleague.config import EngineConfig
from colleague.lobes import LobesRoles, RoleInfo


def _role(model: str, context: int) -> RoleInfo:
    return RoleInfo(
        model=model,
        endpoint="http://gw",
        path="/v1",
        context=context,
        ready=True,
        responsibilities=("cortex",),
        forbidden_responsibilities=(),
    )


def _make_session(tmp_path: Path, *, model: str = "cur", budget: int = 131072) -> _Session:
    return _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=dataclasses.replace(EngineConfig.resolve(model=model), context_budget_tokens=budget),
        json_mode=False,
        view="markdown",
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=lambda **k: None,
    )


def test_model_no_arg_lists_roster_and_roles(tmp_path: Path, monkeypatch) -> None:
    """AC1: no-arg /model lists every served id + one role→model line per role,
    marking the current acting model."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: "http://gw")
    monkeypatch.setattr(
        _session_actions, "fetch_served_model_ids", lambda gw, api_key="": ["a", "b", "c"]
    )
    monkeypatch.setattr(
        _session_actions,
        "resolve_roles",
        lambda gw, timeout=10.0: LobesRoles(cortex=_role("a", 32768), senses=_role("b", 8192)),
    )
    s = _make_session(tmp_path, model="a")
    out = _session_actions._act_model(s, [])
    # Every served id appears.
    for mid in ("a", "b", "c"):
        assert mid in out
    # One role → model line per role.
    assert "cortex → a" in out
    assert "senses → b" in out
    # The current acting model is marked.
    assert "a *" in out


def test_model_no_arg_none_roster(tmp_path: Path, monkeypatch) -> None:
    """AC1: a None roster degrades to 'roster unavailable' + the current model."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: "http://gw")
    monkeypatch.setattr(_session_actions, "fetch_served_model_ids", lambda gw, api_key="": None)
    monkeypatch.setattr(_session_actions, "resolve_roles", lambda gw, timeout=10.0: None)
    s = _make_session(tmp_path, model="cur")
    out = _session_actions._act_model(s, [])
    assert "roster unavailable" in out
    assert "cur" in out


def test_model_no_arg_unarmed(tmp_path: Path, monkeypatch) -> None:
    """AC1: an unarmed lobes rung degrades to 'lobes not armed' + the current
    model, and never raises."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: None)
    s = _make_session(tmp_path, model="cur")
    out = _session_actions._act_model(s, [])
    assert "lobes not armed" in out
    assert "cur" in out


def test_model_no_arg_never_raises_on_gateway_error(tmp_path: Path, monkeypatch) -> None:
    """AC1: even a raising gateway resolver degrades to the unarmed line."""

    def _boom(repo):
        raise RuntimeError("no gateway")

    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", _boom)
    s = _make_session(tmp_path, model="cur")
    out = _session_actions._act_model(s, [])
    assert "lobes not armed" in out
    assert "cur" in out


def test_model_switch_sets_and_rederives_budget(tmp_path: Path, monkeypatch) -> None:
    """AC2: /model <id> sets s.config.model AND re-derives the budget from the
    matching role's advertised window (min(window, current))."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: "http://gw")
    monkeypatch.setattr(
        _session_actions,
        "resolve_roles",
        lambda gw, timeout=10.0: LobesRoles(cortex=_role("new", 32768), senses=_role("b", 8192)),
    )
    s = _make_session(tmp_path, model="cur", budget=131072)
    out = _session_actions._act_model(s, ["new"])
    assert s.config.model == "new"
    # min(32768, 131072) = 32768.
    assert s.config.context_budget_tokens == 32768
    assert "model → new" in out
    assert "budget 32768" in out


def test_model_switch_budget_never_grows_past_current(tmp_path: Path, monkeypatch) -> None:
    """AC2: a role window LARGER than the current budget keeps the current
    budget (min(window, current) — never grows)."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: "http://gw")
    monkeypatch.setattr(
        _session_actions,
        "resolve_roles",
        lambda gw, timeout=10.0: LobesRoles(cortex=_role("big", 262144), senses=_role("b", 8192)),
    )
    s = _make_session(tmp_path, model="cur", budget=131072)
    out = _session_actions._act_model(s, ["big"])
    assert s.config.model == "big"
    # min(262144, 131072) = 131072 — unchanged.
    assert s.config.context_budget_tokens == 131072
    assert "model → big" in out
    assert "budget 131072" in out


def test_model_switch_unknown_model_keeps_budget(tmp_path: Path, monkeypatch) -> None:
    """AC2: a model matching no role leaves the budget untouched (window unknown)."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: "http://gw")
    monkeypatch.setattr(
        _session_actions,
        "resolve_roles",
        lambda gw, timeout=10.0: LobesRoles(cortex=_role("a", 32768), senses=_role("b", 8192)),
    )
    s = _make_session(tmp_path, model="cur", budget=131072)
    out = _session_actions._act_model(s, ["unknown"])
    assert s.config.model == "unknown"
    assert s.config.context_budget_tokens == 131072
    assert "model → unknown" in out


def test_model_switch_unarmed_keeps_budget(tmp_path: Path, monkeypatch) -> None:
    """AC2: an unarmed lobes rung still sets the model; the budget is untouched
    (no role window to derive from)."""
    monkeypatch.setattr(_session_actions, "resolve_lobes_gateway_url", lambda repo: None)
    s = _make_session(tmp_path, model="cur", budget=131072)
    out = _session_actions._act_model(s, ["new"])
    assert s.config.model == "new"
    assert s.config.context_budget_tokens == 131072
    assert "model → new" in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

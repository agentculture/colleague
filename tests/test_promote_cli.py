"""t8 — the `colleague promote` verb: mint + register + channels + (serve).

Covers spec targets c1 (the promotion command), c2 (an operator can run it), c7
(post-promotion report), h7 (operator runs promote against a checkout). The
prepare path is fully tested; the live `--serve` is delegated to
colleague.resident.connection.serve_live (monkeypatched here, live-tested by hand).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.cli._commands import promote
from colleague.cli._errors import CliError
from colleague.explain.catalog import ENTRIES
from colleague.resident import CultureExtraMissing


def _args(**over) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    promote.register(sub)
    ns = parser.parse_args(["promote"])
    for key, value in over.items():
        setattr(ns, key, value)
    return ns


def _fake_reg(repo, *, suffix, model, **kw):
    return SimpleNamespace(
        nick=suffix,
        signalled=True,
        signal_output="exit=0\n",
        culture_yaml_path=Path("/x/culture.yaml"),
        prompt_path=Path("/x/AGENTS.colleague.md"),
    )


def _fake_sel(repo, **kw):
    return SimpleNamespace(owned="#colleague", chosen=["#colleague", "#general"], degraded=False)


def _patch_steps(monkeypatch):
    # No-op the [culture] gate so the orchestration is testable without the extra
    # installed (the gate itself is covered by test_culture_extra_missing_*).
    monkeypatch.setattr("colleague.resident.require_culture_deps", lambda: None)
    monkeypatch.setattr("colleague.resident.register.register_resident", _fake_reg)
    monkeypatch.setattr("colleague.resident.channels.select_channels", _fake_sel)


def test_verb_registered_and_explained() -> None:
    """`promote` parses to cmd_promote and has an explain-catalog entry (agent-first contract)."""
    ns = _args()
    assert ns.func is promote.cmd_promote
    assert ("promote",) in ENTRIES


def test_prepare_path_reports_json(monkeypatch, capsys) -> None:
    """Default (no --serve): mint+register+channels, report served=False."""
    _patch_steps(monkeypatch)
    rc = promote.cmd_promote(_args(json=True, suffix="colleague"))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["identity"] == "colleague"
    assert out["owned_channel"] == "#colleague"
    assert out["channels"] == ["#colleague", "#general"]
    assert out["registered"] is True
    assert out["served"] is False


def test_culture_extra_missing_raises_clean_clierror(monkeypatch) -> None:
    """Without the [culture] extra, the verb fails cleanly with an install hint (no traceback)."""

    def _missing() -> None:
        raise CultureExtraMissing(
            "the colleague[culture] extra is required ... uv sync --extra culture"
        )

    monkeypatch.setattr("colleague.resident.require_culture_deps", _missing)
    with pytest.raises(CliError) as exc:
        promote.cmd_promote(_args())
    assert "colleague[culture]" in str(exc.value)


def test_serve_delegates_to_serve_live(monkeypatch, capsys) -> None:
    """--serve hands the live wiring to colleague.resident.connection.serve_live."""
    _patch_steps(monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr(
        "colleague.resident.connection.serve_live",
        lambda **kw: calls.append(kw),
    )
    rc = promote.cmd_promote(
        _args(json=True, suffix="colleague", serve=True, irc_host="irc.local", irc_port=6667)
    )
    assert rc == 0
    assert len(calls) == 1
    kw = calls[0]
    assert kw["host"] == "irc.local" and kw["port"] == 6667
    assert kw["nick"] == "colleague"
    # owned channel first, deduped against chosen.
    assert kw["channels"][0] == "#colleague"
    out = json.loads(capsys.readouterr().out)
    assert out["served"] is True

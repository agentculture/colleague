"""qwen-direct (spec c25/c26, plan t6): ``colleague work --model`` / ``--effort``
with NO value print the served options / the per-seat effort table and exit 0
without running; the renderers are pure and shared with the session palette.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from colleague.cli import main
from colleague.cli._commands._listing import (
    LIST_SENTINEL,
    apply_effort,
    effort_table,
    model_arg,
    register_listing_flags,
    served_model_listing,
)
from colleague.cli._errors import CliError
from colleague.config import EngineConfig


def _capture(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = 0
    try:
        main(argv)
    except SystemExit as exc:  # main() may exit
        code = int(exc.code or 0)
    return code, capsys.readouterr().out


def test_served_model_listing_marks_current_and_opt_in_roles() -> None:
    text, payload = served_model_listing(
        current_model="q/cortex",
        roster=["q/cortex", "g/senses"],
        roles={"cortex": "q/cortex", "senses": "g/senses", "muse": "g/muse"},
        lobes_armed=True,
    )
    assert "served: q/cortex  ◀ current" in text
    assert "role senses → g/senses (not consumed — opt-in: COLLEAGUE_SENSES_MODEL=lobes)" in text
    assert "role muse → g/muse (not consumed — opt-in: COLLEAGUE_DEEPTHINK_MODEL=lobes)" in text
    assert payload["served"] == ["q/cortex", "g/senses"]
    assert payload["consumed_roles"] == ["cortex"]


def test_served_model_listing_distinguishes_none_roster_empty_and_unarmed() -> None:
    none_text, none_payload = served_model_listing(
        current_model="m", roster=None, roles=None, lobes_armed=True
    )
    assert "roster unavailable" in none_text
    assert none_payload["served"] is None
    empty_text, _ = served_model_listing(current_model="m", roster=[], roles=None, lobes_armed=True)
    assert "nothing served" in empty_text
    unarmed_text, _ = served_model_listing(
        current_model="m", roster=None, roles=None, lobes_armed=False
    )
    assert "lobes not armed" in unarmed_text


def test_effort_table_reflects_defaults_overrides_and_kill_switch(tmp_path: Path) -> None:
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    text, payload = effort_table(cfg)
    assert payload["seats"]["cortex"] == "medium"
    assert payload["seats"]["deepthink"] == "xhigh"
    assert payload["seats"]["senses"] == "off"
    assert "cortex     medium  (table)" in text
    apply_effort(cfg, "xhigh", "cortex")
    assert effort_table(cfg)[1]["seats"]["cortex"] == "xhigh"
    apply_effort(cfg, "default", "all")
    table = effort_table(cfg)[1]
    assert table["kill_switch"] is True
    assert table["seats"]["deepthink"] is None


def test_apply_effort_rejects_a_bad_rung_before_mutating(tmp_path: Path) -> None:
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    with pytest.raises(CliError):
        apply_effort(cfg, "turbo")
    assert not cfg.reasoning_effort_seats


def test_register_listing_flags_no_value_yields_sentinel() -> None:
    p = argparse.ArgumentParser()
    register_listing_flags(p)
    args = p.parse_args(["--model", "--effort"])
    assert args.model == LIST_SENTINEL
    assert args.effort == LIST_SENTINEL
    assert model_arg(args) is None
    args2 = p.parse_args(["--model", "x/y", "--effort", "low"])
    assert model_arg(args2) == "x/y"
    assert args2.effort == "low"


def test_work_bare_model_and_effort_print_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.setattr("colleague.config._merged_config_json", lambda _repo: {})
    code, out = _capture(
        ["work", "noop", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--model"], capsys
    )
    assert code == 0
    assert "current model:" in out
    assert "lobes not armed" in out
    code, out = _capture(
        [
            "work",
            "noop",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--effort",
            "--json",
        ],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["effort"]["seats"]["cortex"] == "medium"
    assert "models" not in payload

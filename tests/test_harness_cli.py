"""Plan t20 (c43): ``config show`` names the max_tokens ceilings + the window source;
``EngineConfig.lobes_context`` is stamped from the cortex advert (closes d15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import harness_cli
from colleague.cli._commands.config import _config_show
from colleague.config import EngineConfig
from tests.test_associate_config import PAYLOAD_WITH_ASSOCIATE, _serving


def test_config_show_prints_ceilings_and_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.delenv("COLLEAGUE_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("COLLEAGUE_MAX_OUTPUT_TOKENS_DESIGN", raising=False)
    rendered = _config_show(".")
    text = rendered._text
    assert (
        "max_tokens:             cortex=64000 worker=64000 deepthink=131072 design=131072" in text
    )
    assert "window:                 131072 (context_budget)" in text
    data = dict(rendered)
    assert data["max_tokens"] == {
        "cortex": 64000,
        "worker": 64000,
        "deepthink": 131072,
        "design": 131072,
    }
    assert data["window"] == {"tokens": 131072, "source": "context_budget"}


def test_kill_switch_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")
    text = _config_show(".")._text
    assert "max_tokens:             off (COLLEAGUE_MAX_OUTPUT_TOKENS=0 — no clamp)" in text


def test_lobes_context_is_stamped_and_wins_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MODEL", raising=False)
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        cfg = EngineConfig.resolve(repo_path=tmp_path)
        text = _config_show(str(tmp_path))._text
    assert cfg.lobes_context == 131072  # the cortex advert's context, not the proxy's
    assert harness_cli.window_line(cfg) == (131072, "lobes_context")
    assert "window:                 131072 (lobes_context)" in text
    assert "lobes_context" not in cfg.to_dict()  # the JSON snapshot is unchanged


def test_unarmed_config_has_no_lobes_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.lobes_context is None
    assert harness_cli.window_line(cfg) == (cfg.context_budget_tokens, "context_budget")

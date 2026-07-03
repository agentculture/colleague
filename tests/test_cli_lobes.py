"""``colleague lobes`` CLI noun — show + overview for the lobes gateway state.

Cortex/senses arc (spec
docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md,
plan task t10). ``colleague lobes show`` renders the ARMED state, the resolved
cortex/senses roles (when reachable), and the degradation rung actually in
effect. Task t10 depends only on t1 (``colleague/lobes.py``) — the armed
signal here is deliberately just ``COLLEAGUE_LOBES_URL`` env; the fuller
config-resolution precedence chain (explicit flag > env > config.json `lobes`
section > builtin default) is a separate, later task (t4) and is not
consulted by this introspection noun.

Acceptance:
1. ``lobes show`` against a stub/reachable gateway renders all resolved roles
   + ready state; unarmed prints a clean "not configured" message and exits
   0; an armed-but-unreachable gateway shows the degradation honestly with no
   traceback, still exit 0.
2. ``explain lobes`` resolves, and the cross-surface parity test
   (registry == MCP catalog == learn) stays green with the new noun added.
"""

from __future__ import annotations

import json

import pytest

from colleague.cli import main
from colleague.lobes import LobesRoles, RoleInfo

_ENV_VAR = "COLLEAGUE_LOBES_URL"

_CORTEX = RoleInfo(
    model="sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP",
    endpoint="http://localhost:8000",
    path="/v1/chat/completions",
    context=131072,
    ready=True,
    responsibilities=("reasoning", "deciding", "tool_use"),
    forbidden_responsibilities=(),
)

_SENSES = RoleInfo(
    model="coolthor/gemma-4-12B-it-NVFP4A16",
    endpoint="http://localhost:8000",
    path="/v1/chat/completions",
    context=32768,
    ready=True,
    responsibilities=("intake", "normalize_input", "speak_back"),
    forbidden_responsibilities=("final_decision", "repo_action"),
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never let a developer/CI shell leak a real gateway URL into these tests.
    monkeypatch.delenv(_ENV_VAR, raising=False)


# ---------------------------------------------------------------------------
# unarmed
# ---------------------------------------------------------------------------


def test_lobes_show_unarmed_is_clean_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["lobes", "show"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "not configured" in out
    assert _ENV_VAR.lower() in out  # names the env var so an operator knows how to arm it


def test_lobes_show_unarmed_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["lobes", "show", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["armed"] is False
    assert payload["rung"] == "not_configured"
    assert payload["gateway_url"] is None
    assert payload["roles"] is None


# ---------------------------------------------------------------------------
# armed + reachable
# ---------------------------------------------------------------------------


def test_lobes_show_armed_reachable_renders_roles(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_ENV_VAR, "http://127.0.0.1:59999")
    monkeypatch.setattr(
        "colleague.cli._commands.lobes.resolve_roles",
        lambda url, **kwargs: LobesRoles(cortex=_CORTEX, senses=_SENSES),
    )
    rc = main(["lobes", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cortex" in out
    assert "senses" in out
    assert _CORTEX.model in out
    assert _SENSES.model in out
    assert "ready" in out.lower()


def test_lobes_show_armed_reachable_json_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_ENV_VAR, "http://127.0.0.1:59999")
    monkeypatch.setattr(
        "colleague.cli._commands.lobes.resolve_roles",
        lambda url, **kwargs: LobesRoles(cortex=_CORTEX, senses=_SENSES),
    )
    rc = main(["lobes", "show", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["armed"] is True
    assert payload["rung"] == "armed_reachable"
    assert payload["gateway_url"] == "http://127.0.0.1:59999"
    roles = payload["roles"]
    assert roles["cortex"]["model"] == _CORTEX.model
    assert roles["cortex"]["ready"] is True
    assert roles["cortex"]["context"] == 131072
    assert set(roles["cortex"]["responsibilities"]) == set(_CORTEX.responsibilities)
    assert roles["senses"]["model"] == _SENSES.model
    assert roles["senses"]["forbidden_responsibilities"] == list(_SENSES.forbidden_responsibilities)


# ---------------------------------------------------------------------------
# armed + unreachable (a real dead port — exercises the real resolve_roles
# degrade-to-None path, no monkeypatching of the client itself needed)
# ---------------------------------------------------------------------------


def test_lobes_show_armed_unreachable_degrades_honestly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing listens on port 1 — a real connection-refused, exercising the
    # actual colleague.lobes.resolve_roles degrade-to-None path.
    monkeypatch.setenv(_ENV_VAR, "http://127.0.0.1:1")
    rc = main(["lobes", "show"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "unreachable" in out
    assert "http://127.0.0.1:1" in out


def test_lobes_show_armed_unreachable_json_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_ENV_VAR, "http://127.0.0.1:1")
    rc = main(["lobes", "show", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["armed"] is True
    assert payload["rung"] == "armed_unreachable"
    assert payload["gateway_url"] == "http://127.0.0.1:1"
    assert payload["roles"] is None


# ---------------------------------------------------------------------------
# overview / bare / explain
# ---------------------------------------------------------------------------


def test_lobes_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["lobes", "overview"])
    assert rc == 0
    assert "lobes" in capsys.readouterr().out.lower()


def test_lobes_bare_runs_overview(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lobes"]) == 0


def test_explain_lobes(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "lobes"])
    assert rc == 0
    assert "lobes" in capsys.readouterr().out.lower()


def test_explain_lobes_show_and_overview(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "lobes", "show"]) == 0
    capsys.readouterr()
    assert main(["explain", "lobes", "overview"]) == 0

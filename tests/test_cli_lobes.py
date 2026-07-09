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
from pathlib import Path

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

_STT = RoleInfo(
    model="nvidia/parakeet-tdt-0.6b-v2",
    endpoint="http://realtime:8080",
    path="/v1/audio/transcriptions",
    context=0,
    ready=True,
    responsibilities=("transcribe", "audio_input_to_text"),
    forbidden_responsibilities=(),
)

_TTS = RoleInfo(
    model="ResembleAI/chatterbox",
    endpoint="http://realtime:8080",
    path="/v1/audio/speech",
    context=0,
    ready=True,
    responsibilities=("speech_output", "synthesize"),
    forbidden_responsibilities=(),
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    # Never let a developer/CI shell leak a real gateway URL into these tests.
    monkeypatch.delenv(_ENV_VAR, raising=False)
    # Isolate from user-level config: mock Path.home() to use a temp directory.
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


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
# ready semantics (lobes-cli#89, 0.38.0 — colleague#292/291 S1): cortex/senses
# report a CONFIG-PROXY ready; stt/tts (when present) report a LIVE-PROBED
# ready. `lobes show` must distinguish the two, never conflate them.
# ---------------------------------------------------------------------------


def test_lobes_show_labels_cortex_senses_ready_as_config_proxy(
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
    roles = payload["roles"]
    assert roles["cortex"]["ready_kind"] == "config-proxy"
    assert roles["senses"]["ready_kind"] == "config-proxy"
    assert "stt" not in roles
    assert "tts" not in roles


def test_lobes_show_labels_stt_tts_ready_as_live_probed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_ENV_VAR, "http://127.0.0.1:59999")
    monkeypatch.setattr(
        "colleague.cli._commands.lobes.resolve_roles",
        lambda url, **kwargs: LobesRoles(cortex=_CORTEX, senses=_SENSES, stt=_STT, tts=_TTS),
    )
    rc = main(["lobes", "show", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    roles = payload["roles"]
    assert roles["stt"]["ready_kind"] == "live-probed"
    assert roles["tts"]["ready_kind"] == "live-probed"
    assert roles["stt"]["endpoint"] == "http://realtime:8080"
    assert roles["tts"]["model"] == _TTS.model


def test_lobes_show_text_names_ready_kind_when_voice_roles_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_ENV_VAR, "http://127.0.0.1:59999")
    monkeypatch.setattr(
        "colleague.cli._commands.lobes.resolve_roles",
        lambda url, **kwargs: LobesRoles(cortex=_CORTEX, senses=_SENSES, stt=_STT, tts=_TTS),
    )
    rc = main(["lobes", "show"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "live-probed" in out
    assert "config-proxy" in out


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


# ---------------------------------------------------------------------------
# --repo option: config.json lobes section
# ---------------------------------------------------------------------------


def _write_lobes_config(repo: Path, url: str) -> None:
    """Write a .colleague/config.json with a lobes section."""
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps({"lobes": url}), encoding="utf-8")


def test_lobes_show_reads_config_file_lobes_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """lobes show --repo <repo> must read the .colleague/config.json lobes section."""
    _write_lobes_config(tmp_path, "http://test:8000")
    # Call with --repo; env is unset (autouse fixture cleans it).
    rc = main(["lobes", "show", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "armed" in out
    assert "http://test:8000" in out


def test_lobes_show_config_file_json_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """lobes show --json --repo <repo> must reflect config.json lobes section."""
    _write_lobes_config(tmp_path, "http://config-test:9000")
    rc = main(["lobes", "show", "--json", "--repo", str(tmp_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["armed"] is True
    assert payload["gateway_url"] == "http://config-test:9000"


def test_lobes_show_env_beats_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """lobes show must prefer COLLEAGUE_LOBES_URL env over config.json."""
    _write_lobes_config(tmp_path, "http://config:8000")
    env_url = "http://env-wins:9999"
    monkeypatch.setenv(_ENV_VAR, env_url)
    rc = main(["lobes", "show", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert env_url.lower() in out
    assert "config:8000" not in out


# ---------------------------------------------------------------------------
# drift test: lobes show and config show must agree on armed state
# ---------------------------------------------------------------------------


def test_lobes_show_and_config_show_agree_on_armed_unarmed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """lobes show and config show must both report armed/unarmed consistently."""
    from colleague.config import resolve_lobes_gateway_url

    # Both unarmed: no env, no config file.
    # config show should NOT mention lobes
    main(["config", "show", "--repo", str(tmp_path)])
    config_out = capsys.readouterr().out
    assert "lobes" not in config_out.lower()

    # lobes show should report not configured
    main(["lobes", "show", "--repo", str(tmp_path)])
    lobes_out = capsys.readouterr().out
    assert "not configured" in lobes_out.lower()

    # Verify underlying resolution agrees
    assert resolve_lobes_gateway_url(tmp_path) is None


def test_lobes_show_and_config_show_agree_on_armed_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """lobes show and config show must both report armed when config.json sets it."""
    from colleague.config import resolve_lobes_gateway_url

    url = "http://gateway:9000"
    _write_lobes_config(tmp_path, url)

    # config show should mention lobes armed
    main(["config", "show", "--repo", str(tmp_path)])
    config_out = capsys.readouterr().out
    assert "lobes" in config_out.lower()
    assert "armed" in config_out.lower()

    # lobes show should report armed
    main(["lobes", "show", "--repo", str(tmp_path)])
    lobes_out = capsys.readouterr().out
    assert "armed" in lobes_out.lower()

    # Verify underlying resolution agrees
    assert resolve_lobes_gateway_url(tmp_path) == url

"""Voice config resolution (stt/tts roles for the senses live-presence + voice arc).

Mirrors tests/test_config_senses.py field-for-field. Voice is OPTIONAL:
present only when at least one of stt_model / tts_model is resolved.

Precedence: COLLEAGUE_STT_MODEL/COLLEAGUE_TTS_MODEL env >
.colleague/config.json ``voice`` section > lobes discovery > absent (None).
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from colleague.config import EngineConfig, VoiceConfig
from colleague.lobes import LobesRoles, RoleInfo, resolve_roles

# Every env var that can influence a voice resolve — cleared per test.
_ALL_VOICE_ENV = (
    "COLLEAGUE_BASE_URL",
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "COLLEAGUE_API_KEY",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_MODEL",
    "COLLEAGUE_STT_MODEL",
    "COLLEAGUE_TTS_MODEL",
    "COLLEAGUE_VOICE_BASE_URL",
    "COLLEAGUE_VOICE_API_KEY",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_VOICE_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# resolve_roles: stt/tts parsing
# ---------------------------------------------------------------------------


def test_resolve_roles_parses_stt_and_tts_from_fixture() -> None:
    """resolve_roles returns stt/tts RoleInfo when the /capabilities payload has them."""
    import http.server
    import threading

    payload = {
        "cortex": {
            "role": "cortex",
            "model": "test-cortex-model",
            "runtime": "vllm",
            "endpoint": "http://localhost:8000",
            "path": "/v1/chat/completions",
            "context": 131072,
            "quant": "",
            "mtp": False,
            "responsibilities": ["reasoning"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
        "senses": {
            "role": "senses",
            "model": "test-senses-model",
            "runtime": "vllm",
            "endpoint": "http://localhost:8000",
            "path": "/v1/chat/completions",
            "context": 32768,
            "quant": "",
            "mtp": False,
            "responsibilities": ["intake"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
        "stt": {
            "role": "stt",
            "model": "nvidia/parakeet-tdt-0.6b-v2",
            "runtime": "parakeet",
            "endpoint": "http://realtime:8080",
            "path": "/v1/audio/transcriptions",
            "context": 0,
            "quant": "",
            "mtp": False,
            "responsibilities": ["transcribe"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
        "tts": {
            "role": "tts",
            "model": "ResembleAI/chatterbox",
            "runtime": "chatterbox",
            "endpoint": "http://realtime:8080",
            "path": "/v1/audio/speech",
            "context": 0,
            "quant": "",
            "mtp": False,
            "responsibilities": ["speech_output"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
    }

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}"
        result = resolve_roles(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result is not None
    assert result.stt is not None
    assert result.stt.model == "nvidia/parakeet-tdt-0.6b-v2"
    assert result.tts is not None
    assert result.tts.model == "ResembleAI/chatterbox"


def test_resolve_roles_keeps_stt_tts_none_when_fixture_omits_them() -> None:
    """When the /capabilities payload has no stt/tts, resolve_roles still returns
    a valid LobesRoles with stt=None and tts=None (voice roles are OPTIONAL)."""
    import http.server
    import threading

    payload = {
        "cortex": {
            "role": "cortex",
            "model": "test-cortex-model",
            "runtime": "vllm",
            "endpoint": "http://localhost:8000",
            "path": "/v1/chat/completions",
            "context": 131072,
            "quant": "",
            "mtp": False,
            "responsibilities": ["reasoning"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
        "senses": {
            "role": "senses",
            "model": "test-senses-model",
            "runtime": "vllm",
            "endpoint": "http://localhost:8000",
            "path": "/v1/chat/completions",
            "context": 32768,
            "quant": "",
            "mtp": False,
            "responsibilities": ["intake"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
    }

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}"
        result = resolve_roles(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result is not None
    assert isinstance(result, LobesRoles)
    assert result.stt is None
    assert result.tts is None


def test_resolve_roles_stt_malformed_but_tts_ok_still_returns() -> None:
    """A malformed stt role leaves stt=None but does NOT cause resolve_roles
    to return None — voice roles are optional."""
    import http.server
    import threading

    payload = {
        "cortex": {
            "role": "cortex",
            "model": "test-cortex-model",
            "runtime": "vllm",
            "endpoint": "http://localhost:8000",
            "path": "/v1/chat/completions",
            "context": 131072,
            "quant": "",
            "mtp": False,
            "responsibilities": ["reasoning"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
        "senses": {
            "role": "senses",
            "model": "test-senses-model",
            "runtime": "vllm",
            "endpoint": "http://localhost:8000",
            "path": "/v1/chat/completions",
            "context": 32768,
            "quant": "",
            "mtp": False,
            "responsibilities": ["intake"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
        "stt": "not-a-dict",  # malformed
        "tts": {
            "role": "tts",
            "model": "ResembleAI/chatterbox",
            "runtime": "chatterbox",
            "endpoint": "http://realtime:8080",
            "path": "/v1/audio/speech",
            "context": 0,
            "quant": "",
            "mtp": False,
            "responsibilities": ["speech_output"],
            "forbidden_responsibilities": [],
            "ready": True,
            "loaded": True,
        },
    }

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}"
        result = resolve_roles(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result is not None
    assert result.stt is None
    assert result.tts is not None
    assert result.tts.model == "ResembleAI/chatterbox"


# ---------------------------------------------------------------------------
# VoiceConfig shape: a frozen dataclass.
# ---------------------------------------------------------------------------


def test_voice_config_is_frozen_dataclass() -> None:
    vc = VoiceConfig(
        stt_model="stt-model",
        tts_model="tts-model",
        stt_base_url="http://gateway/v1",
        tts_base_url="http://gateway/v1",
        api_key="key-voice",
    )
    assert vc.stt_model == "stt-model"
    assert vc.tts_model == "tts-model"
    assert vc.stt_base_url == "http://gateway/v1"
    assert vc.tts_base_url == "http://gateway/v1"
    assert vc.api_key == "key-voice"
    with pytest.raises(FrozenInstanceError):
        vc.stt_model = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Absent everywhere: voice is None, byte-identical to a pre-feature config.
# ---------------------------------------------------------------------------


def test_absent_everywhere_voice_is_none() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.voice is None


def test_absent_everywhere_to_dict_has_no_voice_key() -> None:
    snapshot = EngineConfig.resolve().to_dict()
    assert "voice" not in snapshot


# ---------------------------------------------------------------------------
# Env-only resolution.
# ---------------------------------------------------------------------------


def test_env_stt_model_activates_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "stt-only-model")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-only-model"
    assert cfg.voice.tts_model is None


def test_env_tts_model_activates_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TTS_MODEL", "tts-only-model")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.tts_model == "tts-only-model"
    assert cfg.voice.stt_model is None


def test_env_both_stt_tts_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "stt-model")
    monkeypatch.setenv("COLLEAGUE_TTS_MODEL", "tts-model")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-model"
    assert cfg.voice.tts_model == "tts-model"


def test_env_all_voice_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "stt-model")
    monkeypatch.setenv("COLLEAGUE_TTS_MODEL", "tts-model")
    monkeypatch.setenv("COLLEAGUE_VOICE_BASE_URL", "http://voice-endpoint/v1")
    monkeypatch.setenv("COLLEAGUE_VOICE_API_KEY", "key-voice")
    cfg = EngineConfig.resolve()
    assert cfg.voice == VoiceConfig(
        stt_model="stt-model",
        tts_model="tts-model",
        stt_base_url="http://voice-endpoint/v1",
        tts_base_url="http://voice-endpoint/v1",
        api_key="key-voice",
    )


def test_env_base_url_defaults_to_main_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "stt-model")
    monkeypatch.setenv("COLLEAGUE_BASE_URL", "http://main-endpoint/v1")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_base_url == "http://main-endpoint/v1"
    assert cfg.voice.tts_base_url == "http://main-endpoint/v1"


def test_env_api_key_defaults_to_main_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TTS_MODEL", "tts-model")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-key")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.api_key == "main-secret-key"


# ---------------------------------------------------------------------------
# Config-file resolution.
# ---------------------------------------------------------------------------


def test_config_file_voice_section(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "voice": {
                "stt_model": "file-stt-model",
                "tts_model": "file-tts-model",
                "base_url": "http://file-voice/v1",
                "api_key": "file-voice-key",
            }
        },
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.voice == VoiceConfig(
        stt_model="file-stt-model",
        tts_model="file-tts-model",
        stt_base_url="http://file-voice/v1",
        tts_base_url="http://file-voice/v1",
        api_key="file-voice-key",
    )


def test_config_file_voice_stt_only(tmp_path: Path) -> None:
    _write_config(tmp_path, {"voice": {"stt_model": "file-stt-only"}})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "file-stt-only"
    assert cfg.voice.tts_model is None


def test_config_file_voice_tts_only(tmp_path: Path) -> None:
    _write_config(tmp_path, {"voice": {"tts_model": "file-tts-only"}})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.voice is not None
    assert cfg.voice.tts_model == "file-tts-only"
    assert cfg.voice.stt_model is None


def test_config_file_voice_without_models_is_absent(tmp_path: Path) -> None:
    """A voice section with no stt_model or tts_model → voice stays None."""
    _write_config(tmp_path, {"voice": {"base_url": "http://endpoint/v1"}})
    assert EngineConfig.resolve(repo_path=tmp_path).voice is None


def test_env_overrides_config_file_stt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, {"voice": {"stt_model": "file-stt"}})
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "env-stt")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "env-stt"


def test_env_overrides_config_file_voice_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {"voice": {"stt_model": "file-stt", "base_url": "http://file-voice/v1"}},
    )
    monkeypatch.setenv("COLLEAGUE_VOICE_BASE_URL", "http://env-voice/v1")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.voice is not None
    assert cfg.voice.stt_base_url == "http://env-voice/v1"
    assert cfg.voice.tts_base_url == "http://env-voice/v1"


# ---------------------------------------------------------------------------
# Empty / whitespace model treated as absent.
# ---------------------------------------------------------------------------


def test_empty_env_stt_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "")
    monkeypatch.setenv("COLLEAGUE_TTS_MODEL", "")
    assert EngineConfig.resolve().voice is None


def test_whitespace_env_stt_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "   ")
    assert EngineConfig.resolve().voice is None


def test_whitespace_config_file_stt_model_is_absent(tmp_path: Path) -> None:
    _write_config(tmp_path, {"voice": {"stt_model": "   "}})
    assert EngineConfig.resolve(repo_path=tmp_path).voice is None


def test_stt_model_is_stripped_of_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "  stt-model  ")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-model"


# ---------------------------------------------------------------------------
# Redaction: the voice api_key never leaks through to_dict().
# ---------------------------------------------------------------------------


def test_to_dict_voice_api_key_not_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "stt-model")
    monkeypatch.setenv("COLLEAGUE_VOICE_API_KEY", "sk-voice-super-secret")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "sk-main-super-secret")
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert "voice" in snapshot
    voice_snapshot = snapshot["voice"]
    assert isinstance(voice_snapshot, dict)
    assert "api_key" not in voice_snapshot
    rendered = json.dumps(snapshot)
    assert "sk-voice-super-secret" not in rendered
    assert "sk-main-super-secret" not in rendered


def test_to_dict_voice_only_present_when_configured() -> None:
    assert "voice" not in EngineConfig.resolve().to_dict()


# ---------------------------------------------------------------------------
# Lobes discovery: VoiceConfig from gateway stt/tts roles.
# ---------------------------------------------------------------------------


def test_voice_from_lobes_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """When lobes returns stt/tts roles, EACH role's VoiceConfig base_url is
    resolved from ITS OWN advertised ``endpoint`` (lobes-cli#87, 0.38.0;
    colleague#292 S1's follow-on / S2 — the gateway-origin-for-all workaround
    is gone), not a blanket gateway-origin value."""

    def _fake_resolve_roles(gateway_url: str, *, timeout: float = 5.0) -> LobesRoles | None:
        return LobesRoles(
            cortex=RoleInfo(
                model="cortex-model",
                endpoint="http://localhost:8000",
                path="/v1/chat/completions",
                context=131072,
                ready=True,
                responsibilities=("reasoning",),
                forbidden_responsibilities=(),
            ),
            senses=RoleInfo(
                model="senses-model",
                endpoint="http://localhost:8000",
                path="/v1/chat/completions",
                context=32768,
                ready=True,
                responsibilities=("intake",),
                forbidden_responsibilities=(),
            ),
            stt=RoleInfo(
                model="stt-from-gateway",
                endpoint="http://realtime:8080",
                path="/v1/audio/transcriptions",
                context=0,
                ready=True,
                responsibilities=("transcribe",),
                forbidden_responsibilities=(),
            ),
            tts=RoleInfo(
                model="tts-from-gateway",
                endpoint="http://realtime:8080",
                path="/v1/audio/speech",
                context=0,
                ready=True,
                responsibilities=("speech_output",),
                forbidden_responsibilities=(),
            ),
        )

    monkeypatch.setattr("colleague.lobes.resolve_roles", _fake_resolve_roles)
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gateway:8001")

    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-from-gateway"
    assert cfg.voice.tts_model == "tts-from-gateway"
    # base_url is derived from EACH role's own reachable ``endpoint`` (with the
    # OpenAI /v1 suffix), NOT the gateway origin (http://gateway:8001).
    assert cfg.voice.stt_base_url == "http://realtime:8080/v1"
    assert cfg.voice.tts_base_url == "http://realtime:8080/v1"


def test_voice_from_lobes_stt_and_tts_dial_distinct_endpoints_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The h1 honesty condition, end-to-end: when stt and tts are served from
    GENUINELY DIFFERENT origins, VoiceConfig resolves each independently — no
    shared field forces one onto the other's endpoint (or the gateway's)."""

    def _fake_resolve_roles(gateway_url: str, *, timeout: float = 5.0) -> LobesRoles | None:
        return LobesRoles(
            cortex=RoleInfo(
                model="cortex-model",
                endpoint="http://cortex-host:9001",
                path="/v1/chat/completions",
                context=131072,
                ready=True,
                responsibilities=("reasoning",),
                forbidden_responsibilities=(),
            ),
            senses=RoleInfo(
                model="senses-model",
                endpoint="http://senses-host:9002",
                path="/v1/chat/completions",
                context=32768,
                ready=True,
                responsibilities=("intake",),
                forbidden_responsibilities=(),
            ),
            stt=RoleInfo(
                model="stt-model",
                endpoint="http://stt-host:9003",
                path="/v1/audio/transcriptions",
                context=0,
                ready=True,
                responsibilities=("transcribe",),
                forbidden_responsibilities=(),
            ),
            tts=RoleInfo(
                model="tts-model",
                endpoint="http://tts-host:9004",
                path="/v1/audio/speech",
                context=0,
                ready=True,
                responsibilities=("speech_output",),
                forbidden_responsibilities=(),
            ),
        )

    monkeypatch.setattr("colleague.lobes.resolve_roles", _fake_resolve_roles)
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gateway:8001")

    cfg = EngineConfig.resolve()

    # Four distinct endpoints in the fixture; four distinct base_urls out —
    # not one, not the gateway origin.
    assert cfg.base_url == "http://cortex-host:9001/v1"
    assert cfg.senses is not None
    assert cfg.senses.base_url == "http://senses-host:9002/v1"
    assert cfg.voice is not None
    assert cfg.voice.stt_base_url == "http://stt-host:9003/v1"
    assert cfg.voice.tts_base_url == "http://tts-host:9004/v1"
    gateway_origin = "http://gateway:8001"
    for resolved in (
        cfg.base_url,
        cfg.senses.base_url,
        cfg.voice.stt_base_url,
        cfg.voice.tts_base_url,
    ):
        assert not resolved.startswith(gateway_origin)


def test_voice_from_lobes_stt_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lobes with only stt (no tts) still produces a VoiceConfig."""

    def _fake_resolve_roles(gateway_url: str, *, timeout: float = 5.0) -> LobesRoles | None:
        return LobesRoles(
            cortex=RoleInfo(
                model="cortex-model",
                endpoint="http://localhost:8000",
                path="/v1/chat/completions",
                context=131072,
                ready=True,
                responsibilities=("reasoning",),
                forbidden_responsibilities=(),
            ),
            senses=RoleInfo(
                model="senses-model",
                endpoint="http://localhost:8000",
                path="/v1/chat/completions",
                context=32768,
                ready=True,
                responsibilities=("intake",),
                forbidden_responsibilities=(),
            ),
            stt=RoleInfo(
                model="stt-only-gateway",
                endpoint="http://realtime:8080",
                path="/v1/audio/transcriptions",
                context=0,
                ready=True,
                responsibilities=("transcribe",),
                forbidden_responsibilities=(),
            ),
            tts=None,
        )

    monkeypatch.setattr("colleague.lobes.resolve_roles", _fake_resolve_roles)
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gateway:8001")

    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-only-gateway"
    assert cfg.voice.tts_model is None


def test_voice_from_lobes_neither_stt_nor_tts_yields_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lobes with no stt and no tts → voice stays None (no second network call)."""

    def _fake_resolve_roles(gateway_url: str, *, timeout: float = 5.0) -> LobesRoles | None:
        return LobesRoles(
            cortex=RoleInfo(
                model="cortex-model",
                endpoint="http://localhost:8000",
                path="/v1/chat/completions",
                context=131072,
                ready=True,
                responsibilities=("reasoning",),
                forbidden_responsibilities=(),
            ),
            senses=RoleInfo(
                model="senses-model",
                endpoint="http://localhost:8000",
                path="/v1/chat/completions",
                context=32768,
                ready=True,
                responsibilities=("intake",),
                forbidden_responsibilities=(),
            ),
            stt=None,
            tts=None,
        )

    monkeypatch.setattr("colleague.lobes.resolve_roles", _fake_resolve_roles)
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gateway:8001")

    cfg = EngineConfig.resolve()
    assert cfg.voice is None


# ---------------------------------------------------------------------------
# Voice and senses coexist independently.
# ---------------------------------------------------------------------------


def test_voice_and_senses_resolve_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "senses-model")
    monkeypatch.setenv("COLLEAGUE_STT_MODEL", "stt-model")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "senses-model"
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-model"


def test_voice_configured_alone_leaves_senses_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_TTS_MODEL", "tts-only-model")
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.senses is None

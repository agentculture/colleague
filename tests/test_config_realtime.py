"""Realtime discovery + config rung (realtime-speech arc, plan task t1).

Spec: docs/specs/2026-07-22-realtime-speech.md (claims c7/h6, c23/h16).
Mirrors tests/test_voice_config.py's structure and hygiene-test shape
field-for-field — ``RealtimeConfig`` is ONE MORE rung on the same resolution
ladder :class:`~colleague.config.VoiceConfig`/:class:`~colleague.config.SensesConfig`/
:class:`~colleague.config.DeepthinkConfig` already climb.

Two independent presence rungs, highest precedence first:

1. an EXPLICIT operator knob (``COLLEAGUE_REALTIME_URL``/``COLLEAGUE_REALTIME_API_KEY``
   env, or a ``realtime`` section in ``.colleague/config.json``) — a trusted,
   operator-declared dial target;
2. the LOBES DISCOVERY fallback: gated on voice already being armed AND the
   gateway's ``stt`` role advertising the ``realtime_vad_session``
   responsibility (:func:`colleague.lobes.stt_supports_realtime` — the ONE
   live availability signal, probed 2026-07-22).

Absent both, :attr:`colleague.config.EngineConfig.realtime` stays ``None`` —
byte-identical to a pre-arc resolve, and the session lane (built in a later
task) makes ZERO WebSocket dial attempts: there is nothing resolved to dial.

api_key hygiene on the DISCOVERY rung follows the #348 same-origin rule
(colleague#347/#348): the main Bearer is inherited only toward the stt role's
OWN origin, never forwarded to a different host a wire payload advertised.
The EXPLICIT knob rung is trusted operator intent (no same-origin check),
mirroring :func:`colleague.config._resolve_voice`'s identical stance for its
own explicit config.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from colleague.config import (
    _DEFAULT_API_KEY,
    EngineConfig,
    RealtimeConfig,
    _realtime_lobes_fallback,
    _resolve_realtime_devices,
)
from colleague.lobes import (
    REALTIME_VAD_RESPONSIBILITY,
    LobesRoles,
    RoleInfo,
    stt_supports_realtime,
)

# Every env var that can influence a realtime resolve — cleared per test
# (conftest.py's autouse fixture already scrubs every COLLEAGUE_*/CONVERTIBLE_*
# var, but the brief's GOTCHA calls out arming explicitly per-test, so this
# module states the full list for readability, matching test_voice_config.py).
_ALL_REALTIME_ENV = (
    "COLLEAGUE_BASE_URL",
    "COLLEAGUE_API_KEY",
    "COLLEAGUE_MODEL",
    "COLLEAGUE_STT_MODEL",
    "COLLEAGUE_TTS_MODEL",
    "COLLEAGUE_VOICE_BASE_URL",
    "COLLEAGUE_VOICE_API_KEY",
    "COLLEAGUE_REALTIME_URL",
    "COLLEAGUE_REALTIME_API_KEY",
    "COLLEAGUE_REALTIME_INPUT_DEVICE",
    "COLLEAGUE_REALTIME_OUTPUT_DEVICE",
    "COLLEAGUE_LOBES_URL",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_REALTIME_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


def _role(
    *,
    model: str,
    endpoint: str,
    path: str = "/v1/chat/completions",
    context: int = 32768,
    responsibilities: tuple[str, ...] = (),
) -> RoleInfo:
    return RoleInfo(
        model=model,
        endpoint=endpoint,
        path=path,
        context=context,
        ready=True,
        responsibilities=responsibilities,
        forbidden_responsibilities=(),
    )


_MAIN_ORIGIN = "http://localhost:8000"
_OTHER_ORIGIN = "http://other-host:9000"


def _roles_with_stt(
    *,
    stt_endpoint: str | None = _MAIN_ORIGIN,
    stt_responsibilities: tuple[str, ...] = ("transcribe", REALTIME_VAD_RESPONSIBILITY),
    stt_present: bool = True,
) -> LobesRoles:
    """A minimal LobesRoles fixture: cortex/senses at _MAIN_ORIGIN, stt
    optionally armed with the given responsibilities/endpoint."""
    stt_role = (
        _role(
            model="stt-hygiene-model",
            endpoint=stt_endpoint or "",
            path="/v1/audio/transcriptions",
            context=0,
            responsibilities=stt_responsibilities,
        )
        if stt_present
        else None
    )
    return LobesRoles(
        cortex=_role(model="cortex-model", endpoint=_MAIN_ORIGIN, context=131072),
        senses=_role(model="senses-model", endpoint=_MAIN_ORIGIN),
        stt=stt_role,
        tts=None,
    )


def _arm_lobes(monkeypatch: pytest.MonkeyPatch, roles: LobesRoles | None) -> None:
    monkeypatch.setattr(
        "colleague.lobes.resolve_roles",
        lambda gateway_url, *, timeout=5.0: roles,
    )
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gateway:8001")


# ---------------------------------------------------------------------------
# colleague.lobes: the realtime_vad_session availability signal.
# ---------------------------------------------------------------------------


def test_realtime_vad_responsibility_constant_is_the_probed_string() -> None:
    """Pins the exact live-probed responsibility string (2026-07-22)."""
    assert REALTIME_VAD_RESPONSIBILITY == "realtime_vad_session"


def test_stt_supports_realtime_true_when_responsibility_present() -> None:
    role = _role(
        model="stt-model",
        endpoint=_MAIN_ORIGIN,
        responsibilities=("transcribe", "realtime_vad_session"),
    )
    assert stt_supports_realtime(role) is True


def test_stt_supports_realtime_false_when_responsibility_absent() -> None:
    role = _role(model="stt-model", endpoint=_MAIN_ORIGIN, responsibilities=("transcribe",))
    assert stt_supports_realtime(role) is False


def test_stt_supports_realtime_false_when_responsibilities_empty() -> None:
    role = _role(model="stt-model", endpoint=_MAIN_ORIGIN, responsibilities=())
    assert stt_supports_realtime(role) is False


def test_stt_supports_realtime_false_when_role_is_none() -> None:
    assert stt_supports_realtime(None) is False


# ---------------------------------------------------------------------------
# RealtimeConfig shape: a frozen dataclass.
# ---------------------------------------------------------------------------


def test_realtime_config_is_frozen_dataclass() -> None:
    rc = RealtimeConfig(
        available=True,
        ws_url="ws://realtime:8080/v1/realtime",
        api_key="key-realtime",
    )
    assert rc.available is True
    assert rc.ws_url == "ws://realtime:8080/v1/realtime"
    assert rc.api_key == "key-realtime"
    with pytest.raises(FrozenInstanceError):
        rc.available = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Absent everywhere: realtime is None, byte-identical to a pre-feature config,
# and the resolve makes no network call at all (no lobes armed => no dial).
# ---------------------------------------------------------------------------


def test_absent_everywhere_realtime_is_none() -> None:
    cfg = EngineConfig.resolve()
    assert cfg.realtime is None


def test_absent_everywhere_to_dict_has_no_realtime_key() -> None:
    snapshot = EngineConfig.resolve().to_dict()
    assert "realtime" not in snapshot


def test_absent_everywhere_makes_zero_network_calls() -> None:
    """No knob, no lobes armed: resolve() must not touch the network at all —
    the strongest available proxy, in this config-only task, for "the session
    lane makes ZERO dial attempts": nothing is resolved for any later caller
    to dial in the first place (colleague/realtime.py itself doesn't exist
    until a later task)."""
    with patch("urllib.request.urlopen") as fake_urlopen:
        cfg = EngineConfig.resolve()
    fake_urlopen.assert_not_called()
    assert cfg.realtime is None


def test_no_advert_and_no_knob_resolves_none_with_lobes_armed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lobes IS armed and stt IS advertised, but WITHOUT the
    realtime_vad_session responsibility, and no explicit knob is set:
    realtime stays None — the "no advert" half of the acceptance criterion."""
    _arm_lobes(monkeypatch, _roles_with_stt(stt_responsibilities=("transcribe",)))
    cfg = EngineConfig.resolve()
    assert cfg.realtime is None
    assert cfg.voice is not None  # voice itself still arms from stt's model


def test_no_stt_role_and_no_knob_resolves_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _arm_lobes(monkeypatch, _roles_with_stt(stt_present=False))
    cfg = EngineConfig.resolve()
    assert cfg.realtime is None


# ---------------------------------------------------------------------------
# Explicit env-knob resolution (no lobes involved).
# ---------------------------------------------------------------------------


def test_env_realtime_url_activates_realtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.available is True
    assert cfg.realtime.ws_url == "ws://realtime-endpoint:9090/v1/realtime"


def test_env_realtime_https_url_upgrades_to_wss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "https://realtime-endpoint:9443")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "wss://realtime-endpoint:9443/v1/realtime"


def test_env_realtime_url_with_extra_path_is_replaced_by_v1_realtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090/some/prefix")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://realtime-endpoint:9090/v1/realtime"


def test_env_realtime_api_key_alone_without_url_stays_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The url IS the presence signal — an api_key with no url does not, on
    its own, declare a realtime target (mirrors the model-is-presence rule
    every sibling rung takes)."""
    monkeypatch.setenv("COLLEAGUE_REALTIME_API_KEY", "some-key")
    assert EngineConfig.resolve().realtime is None


def test_empty_env_realtime_url_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "")
    assert EngineConfig.resolve().realtime is None


def test_whitespace_env_realtime_url_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "   ")
    assert EngineConfig.resolve().realtime is None


def test_env_realtime_url_is_stripped_of_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "  http://realtime-endpoint:9090  ")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://realtime-endpoint:9090/v1/realtime"


def test_env_realtime_api_key_defaults_to_main_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-key")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.api_key == "main-secret-key"


def test_env_realtime_api_key_explicit_wins_over_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-key")
    monkeypatch.setenv("COLLEAGUE_REALTIME_API_KEY", "realtime-own-key")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.api_key == "realtime-own-key"


# ---------------------------------------------------------------------------
# Explicit config-file (.colleague/config.json) knob resolution.
# ---------------------------------------------------------------------------


def test_config_file_realtime_section(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {"realtime": {"url": "http://file-realtime:9090", "api_key": "file-realtime-key"}},
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.realtime == RealtimeConfig(
        available=True,
        ws_url="ws://file-realtime:9090/v1/realtime",
        api_key="file-realtime-key",
    )


def test_config_file_realtime_without_url_is_absent(tmp_path: Path) -> None:
    _write_config(tmp_path, {"realtime": {"api_key": "file-realtime-key"}})
    assert EngineConfig.resolve(repo_path=tmp_path).realtime is None


def test_whitespace_config_file_realtime_url_is_absent(tmp_path: Path) -> None:
    _write_config(tmp_path, {"realtime": {"url": "   "}})
    assert EngineConfig.resolve(repo_path=tmp_path).realtime is None


def test_env_realtime_url_overrides_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"realtime": {"url": "http://file-realtime:9090"}})
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://env-realtime:9091")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://env-realtime:9091/v1/realtime"


# ---------------------------------------------------------------------------
# Lobes discovery: RealtimeConfig from the gateway's stt role.
# ---------------------------------------------------------------------------


def test_lobes_discovery_available_when_stt_advertises_realtime_vad_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="http://realtime:8080",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.available is True
    assert cfg.realtime.ws_url == "ws://realtime:8080/v1/realtime"


def test_lobes_discovery_https_stt_endpoint_uses_wss(monkeypatch: pytest.MonkeyPatch) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="https://realtime:8443",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "wss://realtime:8443/v1/realtime"


def test_lobes_discovery_falls_back_to_gateway_origin_when_stt_endpoint_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(stt_endpoint="", stt_responsibilities=("realtime_vad_session",)),
    )
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://gateway:8001/v1/realtime"


def test_lobes_discovery_absent_when_lobes_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _arm_lobes(monkeypatch, None)
    cfg = EngineConfig.resolve()
    assert cfg.realtime is None


# ---------------------------------------------------------------------------
# Precedence: explicit knob wins over lobes discovery.
# ---------------------------------------------------------------------------


def test_env_realtime_url_wins_over_lobes_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="http://realtime:8080",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://operator-declared:7000")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://operator-declared:7000/v1/realtime"


def test_config_file_realtime_wins_over_lobes_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="http://realtime:8080",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    _write_config(tmp_path, {"realtime": {"url": "http://file-declared:7000"}})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://file-declared:7000/v1/realtime"


# ---------------------------------------------------------------------------
# api_key hygiene (colleague#348 rule) on the LOBES DISCOVERY rung only.
# ---------------------------------------------------------------------------


def test_cross_origin_discovered_realtime_does_not_inherit_main_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint=_OTHER_ORIGIN,
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://other-host:9000/v1/realtime"
    assert cfg.api_key == "main-secret-token"
    assert cfg.realtime.api_key == _DEFAULT_API_KEY
    assert cfg.realtime.api_key != cfg.api_key


def test_same_origin_discovered_realtime_inherits_main_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint=_MAIN_ORIGIN,
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    monkeypatch.setenv("COLLEAGUE_BASE_URL", f"{_MAIN_ORIGIN}/v1")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.api_key == "main-secret-token"


def test_env_realtime_api_key_arms_cross_origin_discovered_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit COLLEAGUE_REALTIME_API_KEY always wins, even cross-origin —
    the same stance the deepthink/senses/voice rungs already take."""
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint=_OTHER_ORIGIN,
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
    monkeypatch.setenv("COLLEAGUE_REALTIME_API_KEY", "realtime-own-token")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.api_key == "realtime-own-token"


def test_config_file_realtime_api_key_without_url_arms_cross_origin_discovered_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config.json realtime section carrying ONLY an api_key (no url — so it
    declares no realtime target of its own) still supplies the key to the
    discovered cross-origin realtime role (mirrors
    test_voice_config.py::test_config_file_voice_api_key_without_model_arms_cross_origin_role)."""
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint=_OTHER_ORIGIN,
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    _write_config(tmp_path, {"realtime": {"api_key": "file-realtime-token"}})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.realtime is not None
    assert cfg.realtime.api_key == "file-realtime-token"


# ---------------------------------------------------------------------------
# The "voice must be armed" gate (requirement text: "realtime arms only when
# voice is armed AND the advertised stt role carries realtime_vad_session").
# Unreachable via the public EngineConfig.resolve() with a validly-parsed stt
# RoleInfo (a valid RoleInfo always carries a non-blank model, which always
# arms VoiceConfig too) — pinned directly at the private-function level,
# mirroring how tests/test_config_lobes_deepthink.py imports
# _deepthink_budget_from_window directly for the same reason.
# ---------------------------------------------------------------------------


def test_realtime_lobes_fallback_returns_none_when_voice_not_armed() -> None:
    roles = _roles_with_stt(
        stt_endpoint="http://realtime:8080",
        stt_responsibilities=("transcribe", "realtime_vad_session"),
    )
    result = _realtime_lobes_fallback(
        roles,
        "http://gateway:8001",
        "http://localhost:8000/v1",
        "main-key",
        {},
        None,  # voice NOT armed
    )
    assert result is None


# ---------------------------------------------------------------------------
# Realtime and voice/senses resolve independently of each other.
# ---------------------------------------------------------------------------


def test_realtime_and_senses_resolve_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "senses-model")
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "senses-model"
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://realtime-endpoint:9090/v1/realtime"


def test_realtime_from_lobes_coexists_with_discovered_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="http://realtime:8080",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    cfg = EngineConfig.resolve()
    assert cfg.voice is not None
    assert cfg.voice.stt_model == "stt-hygiene-model"
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://realtime:8080/v1/realtime"


# ---------------------------------------------------------------------------
# Redaction: the realtime api_key never leaks through to_dict(); presence is
# omit-when-None (byte-identical artifact when unconfigured).
# ---------------------------------------------------------------------------


def test_to_dict_realtime_api_key_not_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    monkeypatch.setenv("COLLEAGUE_REALTIME_API_KEY", "sk-realtime-super-secret")
    monkeypatch.setenv("COLLEAGUE_API_KEY", "sk-main-super-secret")
    cfg = EngineConfig.resolve()
    snapshot = cfg.to_dict()
    assert "realtime" in snapshot
    realtime_snapshot = snapshot["realtime"]
    assert isinstance(realtime_snapshot, dict)
    assert "api_key" not in realtime_snapshot
    rendered = json.dumps(snapshot)
    assert "sk-realtime-super-secret" not in rendered
    assert "sk-main-super-secret" not in rendered


def test_to_dict_realtime_only_present_when_configured() -> None:
    assert "realtime" not in EngineConfig.resolve().to_dict()


def test_to_dict_realtime_includes_available_and_ws_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    snapshot = EngineConfig.resolve().to_dict()
    assert snapshot["realtime"] == {
        "available": True,
        "ws_url": "ws://realtime-endpoint:9090/v1/realtime",
    }


# ---------------------------------------------------------------------------
# Device selection (plan task t4): input_device/output_device are PURE LOCAL
# knobs (a PortAudio device id or name substring on THIS machine), resolved
# identically regardless of which rung (explicit knob or lobes discovery)
# produced the RealtimeConfig — see colleague.config._resolve_realtime_devices.
# ---------------------------------------------------------------------------


def test_realtime_config_devices_default_to_none() -> None:
    rc = RealtimeConfig(
        available=True,
        ws_url="ws://realtime:8080/v1/realtime",
        api_key="key-realtime",
    )
    assert rc.input_device is None
    assert rc.output_device is None


def test_resolve_realtime_devices_absent_everywhere_is_none() -> None:
    assert _resolve_realtime_devices({}) == (None, None)


def test_resolve_realtime_devices_from_file_dict() -> None:
    file_realtime = {"input_device": "Arducam", "output_device": "2"}
    assert _resolve_realtime_devices(file_realtime) == ("Arducam", "2")


def test_resolve_realtime_devices_blank_file_values_are_none() -> None:
    file_realtime = {"input_device": "   ", "output_device": ""}
    assert _resolve_realtime_devices(file_realtime) == (None, None)


def test_resolve_realtime_devices_env_wins_over_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_INPUT_DEVICE", "env-mic")
    monkeypatch.setenv("COLLEAGUE_REALTIME_OUTPUT_DEVICE", "env-speaker")
    file_realtime = {"input_device": "file-mic", "output_device": "file-speaker"}
    assert _resolve_realtime_devices(file_realtime) == ("env-mic", "env-speaker")


def test_env_realtime_input_device_activates_on_explicit_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    monkeypatch.setenv("COLLEAGUE_REALTIME_INPUT_DEVICE", "Reachy Mini")
    monkeypatch.setenv("COLLEAGUE_REALTIME_OUTPUT_DEVICE", "3")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.input_device == "Reachy Mini"
    assert cfg.realtime.output_device == "3"


def test_config_file_realtime_devices_on_explicit_rung(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "realtime": {
                "url": "http://file-realtime:9090",
                "input_device": "Arducam_12MP",
                "output_device": "hdmi",
            }
        },
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.realtime is not None
    assert cfg.realtime.input_device == "Arducam_12MP"
    assert cfg.realtime.output_device == "hdmi"


def test_no_device_knob_leaves_devices_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_REALTIME_URL", "http://realtime-endpoint:9090")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.input_device is None
    assert cfg.realtime.output_device is None


def test_env_realtime_device_resolves_on_lobes_discovery_rung_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Device knobs are a LOCAL-machine concern independent of which rung
    produced the RealtimeConfig — the lobes discovery rung reads the SAME
    env vars as the explicit rung (see _resolve_realtime_devices)."""
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="http://realtime:8080",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    monkeypatch.setenv("COLLEAGUE_REALTIME_INPUT_DEVICE", "Arducam")
    cfg = EngineConfig.resolve()
    assert cfg.realtime is not None
    assert cfg.realtime.ws_url == "ws://realtime:8080/v1/realtime"
    assert cfg.realtime.input_device == "Arducam"
    assert cfg.realtime.output_device is None


def test_config_file_realtime_device_resolves_on_lobes_discovery_rung_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _arm_lobes(
        monkeypatch,
        _roles_with_stt(
            stt_endpoint="http://realtime:8080",
            stt_responsibilities=("transcribe", "realtime_vad_session"),
        ),
    )
    _write_config(tmp_path, {"realtime": {"output_device": "reachymini_audio_sink"}})
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.realtime is not None
    assert cfg.realtime.output_device == "reachymini_audio_sink"
    assert cfg.realtime.input_device is None

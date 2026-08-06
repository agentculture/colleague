"""Same-role stale-pin refresh AT RESOLUTION TIME (plan task t9, spec c10/c11,
honesty h7/h8).

A main-model id pinned via flag/env/config.json that the lobes gateway's
served-model roster (``/v1/models``) no longer carries is STALE CONFIG, not a
reason to die: ``EngineConfig.resolve()`` substitutes cortex's OWN
currently-discovered id (the SAME role the pin was for) and records a
structured :class:`~colleague.lobes.ModelRefreshWarning` — never a fallback,
never a routing decision, never crossing roles.

Mirrors ``tests/test_config_lobes.py``'s real in-process HTTP server fixture
(the t1 pattern) so the real ``urllib`` transport is exercised end to end.
"""

from __future__ import annotations

import contextlib
import http.server
import inspect
import json
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague.config import EngineConfig, _model_pin_source
from colleague.lobes import ModelRefreshWarning

# Sentinel role ids — real SHAPE, test ids (the test_config_lobes.py stance).
_CORTEX_MODEL = "lobes-cortex-sentinel-model"
_SENSES_MODEL = "lobes-senses-sentinel-model"
_STALE_PIN = "stale/pinned-model-id-nobody-serves"

_ROLE_ENDPOINT = "http://localhost:8000"

CAPABILITIES_PAYLOAD: dict[str, object] = {
    "cortex": {
        "role": "cortex",
        "model": _CORTEX_MODEL,
        "runtime": "vllm",
        "endpoint": _ROLE_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": 131072,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": ["reasoning", "tool_use"],
        "forbidden_responsibilities": [],
        "ready": True,
        "loaded": True,
    },
    "senses": {
        "role": "senses",
        "model": _SENSES_MODEL,
        "runtime": "vllm",
        "endpoint": _ROLE_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": 32768,
        "quant": "compressed-tensors",
        "mtp": True,
        "responsibilities": ["intake"],
        "forbidden_responsibilities": ["final_decision", "repo_action"],
        "ready": True,
        "loaded": True,
    },
}

_ALL_ENV = (
    "COLLEAGUE_LOBES_URL",
    "CONVERTIBLE_LOBES_URL",
    "COLLEAGUE_BASE_URL",
    "CONVERTIBLE_BASE_URL",
    "OPENAI_BASE_URL",
    "COLLEAGUE_API_KEY",
    "CONVERTIBLE_API_KEY",
    "OPENAI_API_KEY",
    "COLLEAGUE_MODEL",
    "CONVERTIBLE_MODEL",
    "COLLEAGUE_THREE_TIER",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    # Prevent a real ~/.colleague/config.json leaking into a resolution.
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# A tiny in-process HTTP server serving /capabilities AND /v1/models — the
# same gateway origin the resolution-time rung fetches BOTH from.
# ---------------------------------------------------------------------------


class _GatewayHandler(http.server.BaseHTTPRequestHandler):
    capabilities_body: bytes = b"{}"
    capabilities_status: int = 200
    models_body: bytes = b"{}"
    models_status: int = 200

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path == "/capabilities":
            self.send_response(self.capabilities_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.capabilities_body)
            return
        if self.path == "/v1/models":
            self.send_response(self.models_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.models_body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def _serving(
    capabilities: object,
    models: object | None,
    *,
    capabilities_status: int = 200,
    models_status: int = 200,
) -> Iterator[str]:
    handler_cls = type(
        "_ScopedGatewayHandler",
        (_GatewayHandler,),
        {
            "capabilities_body": json.dumps(capabilities).encode("utf-8"),
            "capabilities_status": capabilities_status,
            "models_body": json.dumps(models if models is not None else {}).encode("utf-8"),
            "models_status": models_status,
        },
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _models_list(*ids: str) -> dict:
    return {"object": "list", "data": [{"id": mid} for mid in ids]}


# ---------------------------------------------------------------------------
# Acceptance 1: a stale pin (absent from /v1/models) refreshes to cortex's
# discovered id, with the warning naming stale id / source / refreshed id.
# ---------------------------------------------------------------------------


def test_stale_pin_via_colleague_model_env_refreshes_to_cortex_discovered_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_MODEL", _STALE_PIN)
        cfg = EngineConfig.resolve()

    assert cfg.model == _CORTEX_MODEL
    assert len(cfg.model_refresh_warnings) == 1
    warning = cfg.model_refresh_warnings[0]
    assert isinstance(warning, ModelRefreshWarning)
    assert warning.role == "cortex"
    assert warning.stale_id == _STALE_PIN
    assert warning.source == "COLLEAGUE_MODEL"
    assert warning.refreshed_id == _CORTEX_MODEL
    assert warning.point == "resolution"

    # Observable on stderr too (h8's "records a warning" — both surfaces).
    err = capsys.readouterr().err
    assert _STALE_PIN in err
    assert "COLLEAGUE_MODEL" in err
    assert _CORTEX_MODEL in err


def test_stale_pin_via_convertible_model_env_names_the_actual_back_compat_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source attribution names the ACTUAL env var that carried the pin —
    the convertible->colleague rename back-compat alias, not a generic
    "env" label."""
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("CONVERTIBLE_MODEL", _STALE_PIN)
        cfg = EngineConfig.resolve()

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model_refresh_warnings[0].source == "CONVERTIBLE_MODEL"


def test_stale_pin_via_config_json_names_config_json_as_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        _write_config(tmp_path, {"model": _STALE_PIN})
        cfg = EngineConfig.resolve(repo_path=tmp_path)

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model_refresh_warnings[0].source == "config.json"


def test_stale_pin_via_explicit_flag_names_flag_as_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve(model=_STALE_PIN)

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model_refresh_warnings[0].source == "flag"


def test_flag_wins_over_env_for_source_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precedence (flag > env) is preserved for the refresh's source too —
    an explicit --model flag pin, not the also-set env var, is what's named."""
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_MODEL", "another-stale-id")
        cfg = EngineConfig.resolve(model=_STALE_PIN)

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model_refresh_warnings[0].stale_id == _STALE_PIN
    assert cfg.model_refresh_warnings[0].source == "flag"


# ---------------------------------------------------------------------------
# Acceptance 2: unarmed lobes / no advertised model / a valid pin — the
# original value surfaces unchanged, byte-identical.
# ---------------------------------------------------------------------------


def test_lobes_unarmed_original_pin_surfaces_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_MODEL", _STALE_PIN)
    cfg = EngineConfig.resolve()

    assert cfg.model == _STALE_PIN
    assert cfg.model_refresh_warnings == ()


def test_valid_pin_resolves_byte_identically(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_MODEL", _CORTEX_MODEL)
        cfg = EngineConfig.resolve()

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model_refresh_warnings == ()


def test_membership_check_unreachable_means_no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """/v1/models unreachable (gateway serves /capabilities but not /v1/models
    at all, e.g. an older lobes-cli) — the check cannot run, so NO refresh:
    the pin proceeds untouched, never a hard failure."""
    with _serving(CAPABILITIES_PAYLOAD, None, models_status=404) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_MODEL", _STALE_PIN)
        cfg = EngineConfig.resolve()

    assert cfg.model == _STALE_PIN
    assert cfg.model_refresh_warnings == ()


def test_membership_check_401_means_no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(CAPABILITIES_PAYLOAD, None, models_status=401) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_MODEL", _STALE_PIN)
        cfg = EngineConfig.resolve()

    assert cfg.model == _STALE_PIN
    assert cfg.model_refresh_warnings == ()


def test_unpinned_model_from_discovery_needs_no_refresh_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No flag/env/config.json pin at all: resolved_model already IS cortex's
    freshly-discovered id — nothing to check, nothing to warn about."""
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_SENSES_MODEL)) as gateway:
        # Note: /v1/models deliberately OMITS the cortex model — proving the
        # membership check never even ran for an unpinned resolution (else
        # this would have "refreshed" a value that was already correct).
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model_refresh_warnings == ()


# ---------------------------------------------------------------------------
# Acceptance 3 / h7: the refresh never crosses roles, and model resolution
# reads exactly {flag, env, config.json, lobes role discovery}.
# ---------------------------------------------------------------------------


def test_refresh_never_crosses_roles_substitutes_cortex_not_senses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """senses advertises a totally different id than cortex; a stale cortex
    pin must refresh to CORTEX's id, never senses'."""
    with _serving(CAPABILITIES_PAYLOAD, _models_list(_CORTEX_MODEL, _SENSES_MODEL)) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_MODEL", _STALE_PIN)
        cfg = EngineConfig.resolve()

    assert cfg.model == _CORTEX_MODEL
    assert cfg.model != _SENSES_MODEL
    assert cfg.model_refresh_warnings[0].refreshed_id == _CORTEX_MODEL


def test_model_pin_source_enumerates_exactly_flag_env_configjson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """h7: model resolution inputs are exactly {flag, env, config.json, lobes
    role discovery} — this directly enumerates :func:`_model_pin_source`'s
    four possible outcomes (the fourth, lobes role discovery, is the ``None``
    "not a pin at all" case)."""
    assert _model_pin_source("explicit-flag-value", None) == "flag"
    monkeypatch.setenv("COLLEAGUE_MODEL", "from-env")
    assert _model_pin_source(None, None) == "COLLEAGUE_MODEL"
    monkeypatch.delenv("COLLEAGUE_MODEL", raising=False)
    monkeypatch.setenv("CONVERTIBLE_MODEL", "from-env-back-compat")
    assert _model_pin_source(None, None) == "CONVERTIBLE_MODEL"
    monkeypatch.delenv("CONVERTIBLE_MODEL", raising=False)
    assert _model_pin_source(None, "from-config-json") == "config.json"
    assert _model_pin_source(None, None) is None  # lobes discovery / builtin default


def test_model_pin_source_reads_no_task_content() -> None:
    """Structural half of h7: neither the source-naming helper nor
    ``EngineConfig.resolve`` itself accepts a task/instruction parameter —
    no code path in this rung CAN read task content to pick a model."""
    pin_source_params = set(inspect.signature(_model_pin_source).parameters)
    assert not (pin_source_params & {"task", "instruction", "prompt", "message"})

    resolve_params = set(inspect.signature(EngineConfig.resolve).parameters)
    assert not (resolve_params & {"task", "instruction", "prompt", "message"})

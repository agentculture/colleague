"""Lobes discovery rung in config resolution (cortex/senses arc, task t4).

Spec: docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md
(claims c6, h1, c3, h10). Plan task t4.

When ARMED — ``COLLEAGUE_LOBES_URL`` env OR a ``lobes`` section in
``.colleague/config.json`` — ``EngineConfig.resolve()`` consumes
``colleague.lobes.resolve_roles(gateway_url)`` as a **defaults source** feeding
BOTH the main model (cortex) and the ``SensesConfig`` (senses). The rung slots
below config.json and above the builtin default::

    explicit flag > COLLEAGUE_*/OPENAI_* env > .colleague/config.json
    > lobes discovery > builtin default

Two load-bearing decisions (LOBES_LIVE_FINDINGS.md):

* **base_url = gateway ORIGIN, not the per-role ``endpoint`` field.** Every role
  reports an internal ``http://localhost:8000`` that is NOT client-reachable;
  the gateway that serves ``/capabilities`` (``COLLEAGUE_LOBES_URL``) is the
  reachable OpenAI endpoint and routes by model id. So both cortex and senses
  dial a base_url derived from the gateway origin (matching the shape of the
  builtin default's ``/v1`` suffix).
* **Degrade, never hard-fail.** Armed-but-unreachable proceeds on the next
  precedence rung with exactly ONE stderr notice for the whole resolve; absent
  entirely is byte-identical to today (no ``resolve_roles`` call, no notice).

The served fixture below is pinned to the REAL live-probed gateway shape (see
LOBES_LIVE_FINDINGS.md / tests/test_lobes.py) but uses SENTINEL model ids so the
precedence assertions are unambiguous (the real cortex id equals the builtin
default ``_DEFAULT_MODEL`` — a sentinel is the only way to prove the lobes rung,
not the builtin, supplied the value).
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague.config import (
    _DEFAULT_MODEL,
    EngineConfig,
    SensesConfig,
    resolve_lobes_gateway_url,
)

# Sentinel role ids — real SHAPE, test ids (see module docstring).
_CORTEX_MODEL = "lobes-cortex-sentinel-model"
_SENSES_MODEL = "lobes-senses-sentinel-model"

# The internal, NON-client-reachable endpoint every role self-reports (decision
# 2). t4 must NEVER dial this — it dials the gateway origin instead.
_ROLE_INTERNAL_ENDPOINT = "http://localhost:8000"

LOBES_PAYLOAD: dict[str, object] = {
    "cortex": {
        "role": "cortex",
        "model": _CORTEX_MODEL,
        "runtime": "vllm",
        "endpoint": _ROLE_INTERNAL_ENDPOINT,
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
        "endpoint": _ROLE_INTERNAL_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": 32768,
        "quant": "compressed-tensors",
        "mtp": True,
        "responsibilities": ["intake", "normalize_input", "classify_intent"],
        "forbidden_responsibilities": [
            "final_decision",
            "repo_action",
            "security_decision",
        ],
        "ready": True,
        "loaded": True,
    },
    # An extra role proves the parser tolerates the superset (ignored, not errored).
    "embedder": {
        "role": "embedder",
        "model": "some/embedder",
        "runtime": "vllm",
        "endpoint": _ROLE_INTERNAL_ENDPOINT,
        "path": "/v1/embeddings",
        "context": 8192,
        "quant": "",
        "mtp": False,
        "responsibilities": ["vectorization"],
        "forbidden_responsibilities": [],
        "ready": True,
        "loaded": True,
    },
}

# A dead port: nothing listens → connection refused → resolve_roles returns None.
_DEAD_GATEWAY = "http://127.0.0.1:1"

# Every env var that can influence a resolve() under test.
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
    "COLLEAGUE_SENSES_MODEL",
    "CONVERTIBLE_SENSES_MODEL",
    "COLLEAGUE_SENSES_BASE_URL",
    "CONVERTIBLE_SENSES_BASE_URL",
    "COLLEAGUE_SENSES_CONTEXT_BUDGET",
    "CONVERTIBLE_SENSES_CONTEXT_BUDGET",
    "COLLEAGUE_SENSES_MULTIMODAL",
    "CONVERTIBLE_SENSES_MULTIMODAL",
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
# A tiny in-process HTTP server serving /capabilities (the t1 pattern), so the
# real urllib transport is exercised, not a monkeypatched stand-in.
# ---------------------------------------------------------------------------


class _CapabilitiesHandler(http.server.BaseHTTPRequestHandler):
    body: bytes = b"{}"
    status: int = 200

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/capabilities":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def _serving(payload: object, *, status: int = 200) -> Iterator[str]:
    handler_cls = type(
        "_ScopedHandler",
        (_CapabilitiesHandler,),
        {"body": json.dumps(payload).encode("utf-8"), "status": status},
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


# ---------------------------------------------------------------------------
# Armed + reachable: cortex → main model/base_url, senses → SensesConfig.
# ---------------------------------------------------------------------------


def test_armed_gateway_resolves_cortex_as_main_and_senses_as_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 1a: ZERO model ids in config + a stub lobes gateway resolves
    cortex as the main model and senses as a SensesConfig."""
    with _serving(LOBES_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()

        # cortex → the MAIN model id (from the gateway, not the builtin).
        assert cfg.model == _CORTEX_MODEL
        assert cfg.model != _DEFAULT_MODEL
        # base_url derived from the GATEWAY ORIGIN + the builtin's /v1 suffix.
        assert cfg.base_url == gateway.rstrip("/") + "/v1"

        # senses → a resolved SensesConfig.
        assert cfg.senses is not None
        assert isinstance(cfg.senses, SensesConfig)
        assert cfg.senses.model == _SENSES_MODEL
        assert cfg.senses.base_url == gateway.rstrip("/") + "/v1"


def test_lobes_base_url_is_gateway_origin_not_role_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 2: the per-role ``endpoint`` (internal :8000) is NEVER dialed —
    both cortex and senses use a base_url derived from the gateway origin."""
    with _serving(LOBES_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()

    assert _ROLE_INTERNAL_ENDPOINT not in cfg.base_url
    assert cfg.senses is not None
    assert _ROLE_INTERNAL_ENDPOINT not in cfg.senses.base_url
    # The reachable base_url is the gateway origin, not the role's :8000.
    assert cfg.base_url.startswith(gateway.rstrip("/"))
    assert cfg.senses.base_url.startswith(gateway.rstrip("/"))


def test_senses_from_lobes_budget_derived_from_role_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The senses context_budget is derived from the senses role's 32K window,
    reproducing the hand-tuned 24000 default (same ~73% headroom ratio)."""
    with _serving(LOBES_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.context_budget == 24000


def test_armed_via_config_json_lobes_section(tmp_path: Path) -> None:
    """The rung arms from a ``lobes`` section in .colleague/config.json too."""
    with _serving(LOBES_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": {"url": gateway}})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.model == _CORTEX_MODEL
    assert cfg.senses is not None
    assert cfg.senses.model == _SENSES_MODEL


def test_armed_via_config_json_lobes_bare_string(tmp_path: Path) -> None:
    """A bare-string ``lobes`` value is accepted as the gateway URL."""
    with _serving(LOBES_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.model == _CORTEX_MODEL


def test_env_lobes_url_beats_config_json_lobes_section(tmp_path: Path) -> None:
    """The gateway URL itself resolves env > config.json (the rung's own arming)."""
    with _serving(LOBES_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": {"url": _DEAD_GATEWAY}})
        # env points at the LIVE stub; config.json points at a dead port.
        import os

        os.environ["COLLEAGUE_LOBES_URL"] = gateway
        try:
            cfg = EngineConfig.resolve(repo_path=tmp_path)
        finally:
            del os.environ["COLLEAGUE_LOBES_URL"]
    assert cfg.model == _CORTEX_MODEL


# ---------------------------------------------------------------------------
# The full precedence ladder INCLUDING the lobes rung (acceptance 1b).
# ---------------------------------------------------------------------------


def test_full_precedence_ladder_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """explicit flag > env > config.json > lobes discovery > builtin default,
    pinned on the MODEL dimension (the clearest single-value ladder)."""
    with _serving(LOBES_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)

        # 5. builtin default: nothing else set, lobes NOT armed → _DEFAULT_MODEL.
        monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
        assert EngineConfig.resolve().model == _DEFAULT_MODEL
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)

        # 4. lobes rung: armed, no config.json model, no env, no flag → cortex.
        assert EngineConfig.resolve().model == _CORTEX_MODEL

        # 3. config.json beats lobes.
        _write_config(tmp_path, {"model": "config-json-model"})
        assert EngineConfig.resolve(repo_path=tmp_path).model == "config-json-model"

        # 2. env beats config.json (and lobes).
        monkeypatch.setenv("COLLEAGUE_MODEL", "env-model")
        assert EngineConfig.resolve(repo_path=tmp_path).model == "env-model"

        # 1. explicit flag beats everything.
        assert (
            EngineConfig.resolve(repo_path=tmp_path, model="explicit-model").model
            == "explicit-model"
        )


def test_config_json_base_url_beats_lobes_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serving(LOBES_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        _write_config(tmp_path, {"base_url": "http://config-json-endpoint/v1"})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.base_url == "http://config-json-endpoint/v1"
    # cortex model still comes from lobes (config.json set only base_url).
    assert cfg.model == _CORTEX_MODEL


def test_declared_senses_beats_lobes_senses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A senses config declared via env wins over the lobes-discovered one."""
    with _serving(LOBES_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "declared-senses-model")
        cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "declared-senses-model"


# ---------------------------------------------------------------------------
# Degradation: armed-but-unreachable proceeds + ONE stderr notice (acceptance 2a).
# ---------------------------------------------------------------------------


def test_armed_unreachable_degrades_to_builtin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", _DEAD_GATEWAY)
    cfg = EngineConfig.resolve()
    # Falls through to the next rung (builtin) — the run still resolves.
    assert cfg.model == _DEFAULT_MODEL
    assert cfg.senses is None


def test_armed_unreachable_emits_exactly_one_stderr_notice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", _DEAD_GATEWAY)
    EngineConfig.resolve()
    err = capsys.readouterr().err
    # Exactly ONE notice for the whole resolve (not one per field).
    assert err.count(_DEAD_GATEWAY) == 1
    assert "lobes" in err.lower()
    assert "unreachable" in err.lower()


def test_armed_unreachable_notice_on_stderr_not_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", _DEAD_GATEWAY)
    EngineConfig.resolve()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert _DEAD_GATEWAY in captured.err


# ---------------------------------------------------------------------------
# Absent entirely: byte-identical to today, NO notice, NO resolve_roles call.
# ---------------------------------------------------------------------------


def test_absent_lobes_is_byte_identical_config() -> None:
    """resolve() with lobes unarmed reproduces the bare dataclass defaults
    field-for-field — the rung changed nothing when absent."""
    assert EngineConfig.resolve() == EngineConfig()


def test_absent_lobes_to_dict_byte_identical() -> None:
    assert EngineConfig.resolve().to_dict() == EngineConfig().to_dict()


def test_absent_lobes_emits_no_notice(capsys: pytest.CaptureFixture[str]) -> None:
    EngineConfig.resolve()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_absent_lobes_makes_no_resolve_roles_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """When not armed, resolve_roles is NEVER called (no network, byte-identical)."""
    import colleague.lobes as lobes_module

    calls: list[str] = []

    def _boom(url: str, **_kwargs: object) -> None:
        calls.append(url)
        raise AssertionError("resolve_roles must not be called when lobes is unarmed")

    monkeypatch.setattr(lobes_module, "resolve_roles", _boom)
    EngineConfig.resolve()
    assert calls == []


# ---------------------------------------------------------------------------
# resolve_lobes_gateway_url — the no-network armed-state helper (visibility).
# ---------------------------------------------------------------------------


def test_gateway_url_helper_none_when_unarmed(tmp_path: Path) -> None:
    assert resolve_lobes_gateway_url() is None
    assert resolve_lobes_gateway_url(tmp_path) is None


def test_gateway_url_helper_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gw:8001")
    assert resolve_lobes_gateway_url() == "http://gw:8001"


def test_gateway_url_helper_reads_config_section(tmp_path: Path) -> None:
    _write_config(tmp_path, {"lobes": {"url": "http://gw:8001"}})
    assert resolve_lobes_gateway_url(tmp_path) == "http://gw:8001"


def test_gateway_url_helper_is_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """The armed-state helper never touches the gateway (no resolve_roles call)."""
    import colleague.lobes as lobes_module

    monkeypatch.setattr(
        lobes_module,
        "resolve_roles",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")),
    )
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gw:8001")
    assert resolve_lobes_gateway_url() == "http://gw:8001"


# ---------------------------------------------------------------------------
# Visibility: provider check-group + config show reflect the armed rung.
# ---------------------------------------------------------------------------


def _stub_roles():
    """Build a LobesRoles from the fixture shape via t1's parser (no network)."""
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(raw: dict) -> RoleInfo:
        return RoleInfo(
            model=raw["model"],
            endpoint=raw["endpoint"],
            path=raw["path"],
            context=raw["context"],
            ready=raw["ready"],
            responsibilities=tuple(raw["responsibilities"]),
            forbidden_responsibilities=tuple(raw["forbidden_responsibilities"]),
        )

    return LobesRoles(
        cortex=_role(LOBES_PAYLOAD["cortex"]),  # type: ignore[arg-type]
        senses=_role(LOBES_PAYLOAD["senses"]),  # type: ignore[arg-type]
    )


def test_provider_group_reports_lobes_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The no-network provider check-group surfaces the armed lobes rung."""
    import colleague.lobes as lobes_module
    from colleague.oilcheck.provider import checks

    monkeypatch.setattr(lobes_module, "resolve_roles", lambda *a, **k: _stub_roles())
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gw:8001")

    results = checks()
    lobes_check = next((c for c in results if c["id"] == "provider_lobes"), None)
    assert lobes_check is not None
    assert "http://gw:8001" in lobes_check["message"]
    assert lobes_check["severity"] == "info"


def test_provider_group_silent_when_lobes_unarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague.oilcheck.provider import checks

    results = checks()
    assert not any(c["id"] == "provider_lobes" for c in results)


def test_reachability_group_reports_lobes_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under --probe, the reachability group does the LIVE lobes consultation."""
    import colleague.lobes as lobes_module
    from colleague.oilcheck.reachability import checks

    monkeypatch.setattr(lobes_module, "resolve_roles", lambda *a, **k: _stub_roles())
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no provider probe here")),
    )
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gw:8001")

    results = checks()
    lobes_check = next((c for c in results if c["id"] == "provider_lobes_reachable"), None)
    assert lobes_check is not None
    assert lobes_check["passed"] is True
    assert _CORTEX_MODEL in lobes_check["message"]
    assert _SENSES_MODEL in lobes_check["message"]


def test_reachability_group_reports_lobes_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import colleague.lobes as lobes_module
    from colleague.oilcheck.reachability import checks

    monkeypatch.setattr(lobes_module, "resolve_roles", lambda *a, **k: None)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no provider probe here")),
    )
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", _DEAD_GATEWAY)

    results = checks()
    lobes_check = next((c for c in results if c["id"] == "provider_lobes_reachable"), None)
    assert lobes_check is not None
    assert lobes_check["passed"] is False
    assert lobes_check["severity"] == "warning"


def test_config_show_reflects_lobes_armed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import colleague.lobes as lobes_module
    from colleague.cli import main

    monkeypatch.setattr(lobes_module, "resolve_roles", lambda *a, **k: _stub_roles())
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gw:8001")

    rc = main(["config", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "lobes" in out.lower()
    assert "http://gw:8001" in out


def test_config_show_json_reflects_lobes_armed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import colleague.lobes as lobes_module
    from colleague.cli import main

    monkeypatch.setattr(lobes_module, "resolve_roles", lambda *a, **k: _stub_roles())
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://gw:8001")

    rc = main(["config", "show", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "lobes" in payload
    assert payload["lobes"]["gateway"] == "http://gw:8001"


def test_config_show_no_lobes_key_when_unarmed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from colleague.cli import main

    rc = main(["config", "show", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "lobes" not in payload

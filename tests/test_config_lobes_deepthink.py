"""Deepthink discovery rung: the lobes ``muse`` role feeds a default DeepthinkConfig.

Spec: docs/specs/2026-07-17-two-machines-two-minds.md (claims c4/h3, c5/h4,
h1). Plan task t5 — the SIXTH sanctioned increment at the router-exclusion
boundary: resolution-only, mirroring how the ``senses`` role feeds a default
``SensesConfig`` (cortex/senses arc t4), one rung below config.json::

    explicit flag > COLLEAGUE_DEEPTHINK_* env > .colleague/config.json
    > lobes discovery (muse) > absent

Load-bearing boundaries (the honest line):

* **Presence keyed solely on a resolved model** — a lobes payload without a
  ``muse`` role, or no lobes at all, leaves ``deepthink`` ``None``:
  byte-identical to a pre-rung resolve (h3).
* **env/config.json always win** — discovery is a DEFAULTS source, never an
  override (the exact stance the senses rung takes).
* **No new decision point** — this file pins resolution only; the four-point
  escalation surface is ``tests/test_deepthink_boundary.py``'s job and is
  untouched by this rung (h4).

The fixture mirrors ``tests/test_config_lobes.py``'s live-probed shape with
SENTINEL model ids, plus the ``muse`` role as probed live 2026-07-17 (context
262144 — thor's serving-side-verified ``max_model_len``).
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
    _DEFAULT_DEEPTHINK_CONTEXT_BUDGET,
    DeepthinkConfig,
    EngineConfig,
    _deepthink_budget_from_window,
)

# Sentinel role ids — real SHAPE, test ids (the test_config_lobes.py stance).
_CORTEX_MODEL = "lobes-cortex-sentinel-model"
_SENSES_MODEL = "lobes-senses-sentinel-model"
_MUSE_MODEL = "lobes-muse-sentinel-model"

# Same-origin rig shape (all roles advertise one endpoint) — deliberately, so
# the discovered deepthink is SAME-endpoint with main and the test-integrity
# reviewer default (spec c10(d), config.py t7) can be proven to arm from a
# discovered muse too.
_ROLE_ENDPOINT = "http://localhost:8000"

# thor's serving-side-verified window (live probe 2026-07-17: vLLM's own
# over-ask rejection names max_model_len=262144) — derives budget 192000 at
# the deepthink default ratio (48000/65536).
_MUSE_WINDOW = 262144
_MUSE_EXPECTED_BUDGET = 192000

MUSE_PAYLOAD: dict[str, object] = {
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
    "muse": {
        "role": "muse",
        "model": _MUSE_MODEL,
        "runtime": "vllm",
        "endpoint": _ROLE_ENDPOINT,
        "path": "/v1/chat/completions",
        "context": _MUSE_WINDOW,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": ["ideation", "divergent_second_opinion"],
        "forbidden_responsibilities": [
            "final_decision",
            "repo_action",
            "security_decision",
        ],
        "ready": True,
        # The live gateway reports loaded=false for proxied roles while the
        # host serves fine (lobes-cli#146) — the rung must not gate on it.
        "loaded": False,
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
    "COLLEAGUE_DEEPTHINK_MODEL",
    "CONVERTIBLE_DEEPTHINK_MODEL",
    "COLLEAGUE_DEEPTHINK_BASE_URL",
    "CONVERTIBLE_DEEPTHINK_BASE_URL",
    "COLLEAGUE_DEEPTHINK_API_KEY",
    "CONVERTIBLE_DEEPTHINK_API_KEY",
    "COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET",
    "CONVERTIBLE_DEEPTHINK_CONTEXT_BUDGET",
    "COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL",
    "CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL",
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


class _CapabilitiesHandler(http.server.BaseHTTPRequestHandler):
    body: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/capabilities":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def _serving(payload: object) -> Iterator[str]:
    handler_cls = type(
        "_ScopedHandler",
        (_CapabilitiesHandler,),
        {"body": json.dumps(payload).encode("utf-8")},
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
# Armed + muse advertised: deepthink discovered, zero model ids in config.
# ---------------------------------------------------------------------------


def test_armed_gateway_with_muse_resolves_deepthink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """c4: with lobes armed and NO deepthink declared anywhere, resolve()
    fills a DeepthinkConfig from the advertised muse role."""
    with _serving(MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()

    assert cfg.deepthink is not None
    assert isinstance(cfg.deepthink, DeepthinkConfig)
    assert cfg.deepthink.model == _MUSE_MODEL
    # muse dials its OWN advertised endpoint (+ the /v1 shape suffix).
    assert cfg.deepthink.base_url == _ROLE_ENDPOINT.rstrip("/") + "/v1"
    # api_key inherits the resolved MAIN endpoint's value.
    assert cfg.deepthink.api_key == cfg.api_key


def test_discovered_deepthink_budget_derived_from_muse_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget derives from the muse role's window at the deepthink default
    ratio (48000/65536) — thor's verified 262144 window yields 192000."""
    with _serving(MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.context_budget == _MUSE_EXPECTED_BUDGET


def test_discovered_deepthink_multimodal_stays_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declaration, never a probe: discovery never arms the media bridge
    (the exact rule the discovered senses follows)."""
    with _serving(MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.multimodal is False


def test_muse_unwired_endpoint_falls_back_to_gateway_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unwired muse (empty ``endpoint``) dials the gateway origin — the
    documented per-role fallback, never a hard failure."""
    payload = json.loads(json.dumps(MUSE_PAYLOAD))
    payload["muse"]["endpoint"] = ""
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == gateway.rstrip("/") + "/v1"


def test_discovered_deepthink_backfills_reviewer_default_when_same_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DISCOVERED deepthink feeds the test-integrity reviewer default too
    (spec c10(d)) when it lands same-endpoint with main — the same-origin rig
    fixture makes muse's dial target equal cortex's."""
    with _serving(MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.base_url == cfg.base_url
    assert cfg.testintegrity_reviewer_model == _MUSE_MODEL


# ---------------------------------------------------------------------------
# Precedence: env and config.json always beat discovery.
# ---------------------------------------------------------------------------


def test_deepthink_env_beats_lobes_muse(monkeypatch: pytest.MonkeyPatch) -> None:
    """COLLEAGUE_DEEPTHINK_MODEL wins over the discovered muse role."""
    with _serving(MUSE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "operator/declared-model")
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "operator/declared-model"
    # The declared deepthink defaults ITS base_url to MAIN's (the t1 rule),
    # never to the muse role's endpoint.
    assert cfg.deepthink.base_url == cfg.base_url
    # And the declared path keeps the hand-tuned default budget.
    assert cfg.deepthink.context_budget == _DEFAULT_DEEPTHINK_CONTEXT_BUDGET


def test_deepthink_config_json_beats_lobes_muse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config.json ``deepthink`` section wins over the discovered muse role."""
    with _serving(MUSE_PAYLOAD) as gateway:
        _write_config(
            tmp_path,
            {"lobes": gateway, "deepthink": {"model": "file/declared-model"}},
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "file/declared-model"


# ---------------------------------------------------------------------------
# Byte-identity: no muse, or no lobes, means no deepthink (h3).
# ---------------------------------------------------------------------------


def test_no_muse_role_leaves_deepthink_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gateway serving cortex/senses but NO muse leaves deepthink None —
    the e2e-shape byte-identity extension (h3)."""
    payload = {k: v for k, v in MUSE_PAYLOAD.items() if k != "muse"}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is None


def test_absent_lobes_leaves_deepthink_none() -> None:
    """No lobes anywhere: deepthink stays None exactly as before the rung."""
    cfg = EngineConfig.resolve()
    assert cfg.deepthink is None


def test_muse_blank_model_leaves_deepthink_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presence is keyed SOLELY on a resolved model — a muse role with a blank
    model id resolves no deepthink (the senses/deepthink presence rule)."""
    payload = json.loads(json.dumps(MUSE_PAYLOAD))
    payload["muse"]["model"] = ""
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.deepthink is None


# ---------------------------------------------------------------------------
# The budget helper (unit).
# ---------------------------------------------------------------------------


def test_deepthink_budget_from_window_ratio() -> None:
    """The helper reproduces the hand-tuned 48000 default at the 64K design
    window and scales any other window at the same ratio; non-positive falls
    back to the default."""
    assert _deepthink_budget_from_window(65536) == _DEFAULT_DEEPTHINK_CONTEXT_BUDGET
    assert _deepthink_budget_from_window(_MUSE_WINDOW) == _MUSE_EXPECTED_BUDGET
    assert _deepthink_budget_from_window(0) == _DEFAULT_DEEPTHINK_CONTEXT_BUDGET
    assert _deepthink_budget_from_window(-1) == _DEFAULT_DEEPTHINK_CONTEXT_BUDGET
    assert _deepthink_budget_from_window(1) == 1

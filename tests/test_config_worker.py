"""Three-tier execution's worker seat: arming, loud refusal, key hygiene.

Plan: docs/plans/2026-08-05-three-tier-execution.md, task t3 (covers c3, h3,
c25, h21). Mirrors ``tests/test_config_lobes_deepthink.py`` /
``tests/test_config_lobes.py``'s fixture + key-hygiene test shape.

Three load-bearing decisions this task adds, distinct from every prior
lobes-fed rung (deepthink/senses/voice/realtime):

* **Default-OFF, explicit arming.** ``three_tier`` (env ``COLLEAGUE_THREE_TIER``
  or a config.json ``three_tier`` block) gates whether the worker role is even
  consulted. Not armed = a strict no-op — an advertised worker role is read
  and discarded exactly like ``reranker`` (acceptance criterion 1/3).
* **Armed makes the worker role MANDATORY, never a silent fallback.** Every
  other lobes-fed rung degrades to ``None`` on any resolution failure; an
  explicitly armed three-tier config instead raises
  :class:`~colleague.cli._errors.CliError` naming exactly what is missing —
  no silent cortex-as-actor (acceptance criterion 2).
* **Role NAMES only, never model-name parsing.** There is no
  ``COLLEAGUE_WORKER_MODEL`` / config.json ``worker.model`` — the worker is
  resolved ONLY by asking the lobes gateway for its ``worker`` role. The only
  recognised ``worker`` config.json key is ``api_key`` (key hygiene,
  acceptance criterion 3, mirroring the deepthink/senses same-origin rule).
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague.cli._errors import CliError
from colleague.config import (
    _DEFAULT_API_KEY,
    EngineConfig,
    WorkerConfig,
)

# Sentinel role ids — real SHAPE, test ids (the test_config_lobes.py stance).
_CORTEX_MODEL = "lobes-cortex-sentinel-model"
_SENSES_MODEL = "lobes-senses-sentinel-model"
_WORKER_MODEL = "lobes-worker-sentinel-model"

# Same-origin rig shape (every role advertises one endpoint) — the reference
# deployment: everything proxied at one gateway.
_ROLE_ENDPOINT = "http://localhost:8000"

_WORKER_WINDOW = 131072

BASE_PAYLOAD: dict[str, object] = {
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


def _worker_role(*, endpoint: str = _ROLE_ENDPOINT, ready: bool = True) -> dict[str, object]:
    return {
        "role": "worker",
        "model": _WORKER_MODEL,
        "runtime": "vllm",
        "endpoint": endpoint,
        "path": "/v1/chat/completions",
        "context": _WORKER_WINDOW,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": ["reasoning", "tool_use", "code_repo_actions"],
        "forbidden_responsibilities": [],
        "ready": ready,
        "loaded": ready,
    }


WORKER_PAYLOAD: dict[str, object] = {**BASE_PAYLOAD, "worker": _worker_role()}

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
    "COLLEAGUE_WORKER_API_KEY",
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
# Acceptance criterion 1 (config-side): worker advert read and discarded when
# three_tier is not armed — byte-identical to a legacy run.
# ---------------------------------------------------------------------------


def test_worker_absent_when_three_tier_not_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lobes gateway advertising a ready worker role never resolves it
    into EngineConfig unless three_tier is explicitly armed."""
    with _serving(WORKER_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.three_tier is False
    assert cfg.worker is None


def test_no_lobes_no_three_tier_is_byte_identical() -> None:
    """No lobes, no three_tier config anywhere: resolve() never even attempts
    a network call and never raises."""
    cfg = EngineConfig.resolve()
    assert cfg.three_tier is False
    assert cfg.worker is None


def test_three_tier_armed_without_lobes_advert_still_reads_discarded_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DECLARED (non-worker) config.json section for three_tier=false with a
    live gateway advertising a worker stays a no-op — arming is what matters,
    not mere advertisement."""
    with _serving(WORKER_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "0")
        cfg = EngineConfig.resolve()
    assert cfg.three_tier is False
    assert cfg.worker is None


# ---------------------------------------------------------------------------
# Arming precedence: env > config.json (bool or object) > default-OFF.
# ---------------------------------------------------------------------------


def test_env_arms_three_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        cfg = EngineConfig.resolve()
    assert cfg.three_tier is True
    assert cfg.worker is not None


def test_config_json_bool_arms_three_tier(tmp_path: Path) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "three_tier": True})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.three_tier is True
    assert cfg.worker is not None


def test_config_json_object_presence_arms_three_tier(tmp_path: Path) -> None:
    """A bare ``{"three_tier": {}}`` object — no explicit ``enabled`` key —
    is itself treated as armed (mirrors the ``lobes`` bare-string-or-object
    tolerance)."""
    with _serving(WORKER_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "three_tier": {}})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.three_tier is True
    assert cfg.worker is not None


def test_config_json_object_enabled_false_does_not_arm(tmp_path: Path) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "three_tier": {"enabled": False}})
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.three_tier is False
    assert cfg.worker is None


def test_env_wins_over_config_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        _write_config(tmp_path, {"lobes": gateway, "three_tier": True})
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "0")
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.three_tier is False
    assert cfg.worker is None


# ---------------------------------------------------------------------------
# Acceptance criterion 2: armed + worker missing/undialable exits with a
# loud, naming refusal — never a silent cortex-as-actor fallback.
# ---------------------------------------------------------------------------


def test_armed_without_lobes_gateway_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    with pytest.raises(CliError) as exc_info:
        EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "three-tier" in message
    assert "lobes" in message


def test_armed_with_unreachable_lobes_gateway_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    # Nothing listens on this port — a real connection-refused.
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://127.0.0.1:1")
    with pytest.raises(CliError) as exc_info:
        EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "three-tier" in message
    assert "unreachable" in message


def test_armed_with_no_worker_role_advertised_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lobes is reachable and advertises cortex/senses but no worker at
    all — the exact gap the refusal must name."""
    with _serving(BASE_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "three-tier" in message
    assert "no ready worker role" in message


def test_armed_with_not_ready_worker_role_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker role is advertised but reports ready=False (undialable) —
    the refusal must fire exactly as if it were missing entirely."""
    payload = {**BASE_PAYLOAD, "worker": _worker_role(ready=False)}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        with pytest.raises(CliError) as exc_info:
            EngineConfig.resolve()
    message = exc_info.value.message.lower()
    assert "no ready worker role" in message


def test_armed_with_malformed_worker_role_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker dict present but missing an expected field degrades to
    absent at the lobes layer — the refusal must still fire."""
    broken_worker = dict(_worker_role())
    del broken_worker["context"]
    payload = {**BASE_PAYLOAD, "worker": broken_worker}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        with pytest.raises(CliError):
            EngineConfig.resolve()


def test_armed_with_ready_worker_resolves_successfully(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        cfg = EngineConfig.resolve()
    assert cfg.three_tier is True
    assert cfg.worker is not None
    assert isinstance(cfg.worker, WorkerConfig)
    assert cfg.worker.model == _WORKER_MODEL
    assert cfg.worker.base_url == _ROLE_ENDPOINT.rstrip("/") + "/v1"
    assert cfg.worker.context == _WORKER_WINDOW


# ---------------------------------------------------------------------------
# Acceptance criterion 2: "tested on both fronts" — cmd_work and run_session
# both surface the refusal identically (both call EngineConfig.resolve()
# before any work/episode dispatch).
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _work_namespace(repo: Path, **overrides) -> argparse.Namespace:
    base = dict(
        instruction=["do", "x"],
        repo=str(repo),
        engine="mock",
        no_pr=True,
        watch=False,
        base="main",
        model=None,
        base_url=None,
        api_key=None,
        max_steps=None,
        json=True,
        command_name=None,
        allow_dirty=True,
        mode=None,
        role=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _session_namespace(repo: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo=str(repo),
        engine="mock",
        no_pr=True,
        base="main",
        base_url=None,
        model=None,
        api_key=None,
        max_steps=None,
        json=False,
        allow_dirty=False,
    )


def test_cmd_work_refuses_loudly_on_broken_three_tier(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """The work front: cmd_work calls EngineConfig.resolve() before building
    any task — the refusal fires before any episode starts."""
    from colleague.cli._commands.work import cmd_work

    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
    with pytest.raises(CliError) as exc_info:
        cmd_work(_work_namespace(git_repo))
    assert "three-tier" in exc_info.value.message.lower()


def test_run_session_refuses_loudly_on_broken_three_tier(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path
) -> None:
    """The session front: run_session calls EngineConfig.resolve() before
    entering its interactive loop — the refusal fires before any input is
    even read."""
    from colleague.cli._commands.session import run_session

    monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")

    def _boom_input() -> Iterator[str]:
        raise AssertionError("the session loop must never start reading input")
        yield  # pragma: no cover - unreachable, satisfies generator shape

    with pytest.raises(CliError) as exc_info:
        run_session(
            _session_namespace(git_repo),
            input_fn=_boom_input(),
            out=lambda *a, **k: None,
            err=lambda *a, **k: None,
            _color=False,
        )
    assert "three-tier" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# Acceptance criterion 3: same-origin key hygiene (mirrors the
# deepthink/senses/voice rungs, colleague#347/#348).
# ---------------------------------------------------------------------------


def test_cross_origin_worker_does_not_inherit_main_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {**BASE_PAYLOAD, "worker": _worker_role(endpoint="http://other-host:9000")}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
        cfg = EngineConfig.resolve()
    assert cfg.worker is not None
    assert cfg.worker.base_url == "http://other-host:9000/v1"
    assert cfg.api_key == "main-secret-token"
    assert cfg.worker.api_key == _DEFAULT_API_KEY
    assert cfg.worker.api_key != cfg.api_key


def test_same_origin_worker_inherits_main_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
        cfg = EngineConfig.resolve()
    assert cfg.worker is not None
    assert cfg.worker.api_key == "main-secret-token"


def test_explicit_worker_api_key_wins_even_cross_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {**BASE_PAYLOAD, "worker": _worker_role(endpoint="http://other-host:9000")}
    with _serving(payload) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret-token")
        monkeypatch.setenv("COLLEAGUE_WORKER_API_KEY", "worker-own-token")
        cfg = EngineConfig.resolve()
    assert cfg.worker is not None
    assert cfg.worker.api_key == "worker-own-token"


def test_config_json_worker_api_key_without_model_arms_cross_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config.json ``worker`` section carrying ONLY an api_key (there is no
    ``model`` key at all — worker has no declared-model rung, role NAMES
    only) still supplies the key to the discovered worker role, even
    cross-origin."""
    payload = {**BASE_PAYLOAD, "worker": _worker_role(endpoint="http://other-host:9000")}
    with _serving(payload) as gateway:
        _write_config(
            tmp_path,
            {
                "lobes": gateway,
                "three_tier": True,
                "worker": {"api_key": "file-worker-token"},
            },
        )
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.worker is not None
    assert cfg.worker.model == _WORKER_MODEL
    assert cfg.worker.api_key == "file-worker-token"


# ---------------------------------------------------------------------------
# to_dict() snapshot shape.
# ---------------------------------------------------------------------------


def test_to_dict_always_carries_three_tier_flag() -> None:
    snapshot = EngineConfig.resolve().to_dict()
    assert snapshot["three_tier"] is False
    assert "worker" not in snapshot


def test_to_dict_carries_worker_when_armed_and_omits_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _serving(WORKER_PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_THREE_TIER", "1")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "sk-worker-secret")
        snapshot = EngineConfig.resolve().to_dict()
    assert snapshot["three_tier"] is True
    assert snapshot["worker"] == {
        "model": _WORKER_MODEL,
        "base_url": _ROLE_ENDPOINT.rstrip("/") + "/v1",
        "context": _WORKER_WINDOW,
    }
    assert "sk-worker-secret" not in str(snapshot)

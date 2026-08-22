"""qwen-direct (spec c14/h10, c21/h18; plan t9): the single-model default.

With lobes armed and NO operator declaration, every seat colleague builds on the
default path resolves to the SAME served model (the ``cortex`` role) and no
second seat is armed; the lobes fallbacks for senses/muse are reachable ONLY
under the ``lobes`` sentinel; the default-path artifact carries no ``senses``
key (byte-identical to the unarmed floor).
"""

from __future__ import annotations

import contextlib
import http.server
import json
import re
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague.config import EngineConfig

_ROLE = {
    "endpoint": "http://localhost:8000",
    "path": "/v1/chat/completions",
    "context": 32768,
    "ready": True,
    "loaded": True,
    "responsibilities": ["reasoning"],
    "forbidden_responsibilities": [],
}
PAYLOAD = {
    "cortex": {**_ROLE, "role": "cortex", "model": "stub/cortex-model", "context": 131072},
    "senses": {**_ROLE, "role": "senses", "model": "stub/gemma-senses"},
    "muse": {**_ROLE, "role": "muse", "model": "stub/gemma-muse", "context": 262144},
    "worker": {**_ROLE, "role": "worker", "model": "stub/worker-model"},
}


class _Handler(http.server.BaseHTTPRequestHandler):
    body = b""

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args: object) -> None:
        return


@contextlib.contextmanager
def _serving(payload: object) -> Iterator[str]:
    handler = type("_H", (_Handler,), {"body": json.dumps(payload).encode("utf-8")})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_default_path_arms_exactly_one_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lobes armed, every role advertised, nothing declared → only cortex."""
    with _serving(PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve()
    assert cfg.model == "stub/cortex-model"
    assert cfg.senses is None
    assert cfg.deepthink is None
    assert getattr(cfg, "worker", None) is None
    assert cfg.three_tier is False
    assert cfg.thought_action_evaluation is False
    # Every model id the resolved config carries is the cortex model.
    models = {
        v for k, v in cfg.to_dict().items() if k.endswith("model") and isinstance(v, str) and v
    }
    assert models == {"stub/cortex-model"}


def test_opt_in_sentinel_is_the_only_way_to_a_second_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    with _serving(PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "lobes")
        monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "lobes")
        cfg = EngineConfig.resolve()
    assert cfg.senses is not None
    assert cfg.senses.model == "stub/gemma-senses"
    assert cfg.deepthink is not None
    assert cfg.deepthink.model == "stub/gemma-muse"


def test_lobes_fallbacks_are_reached_only_under_the_sentinel() -> None:
    """Text guard on config.py: each ``*_lobes_fallback(`` call inside resolve()
    sits under an ``== "lobes"`` sentinel check — no default-path discovery."""
    src = Path("colleague/config.py").read_text(encoding="utf-8").splitlines()
    calls = [
        i
        for i, line in enumerate(src)
        if re.search(r"resolved_(senses|deepthink) = _(senses|deepthink)_lobes_fallback\(", line)
    ]
    assert calls, "expected the two sentinel-guarded fallback calls in resolve()"
    for i in calls:
        window = "\n".join(src[max(0, i - 3) : i])
        assert (
            '== "lobes"' in window
        ), f"config.py:{i + 1} fallback call not under the lobes sentinel"


def test_default_path_mock_artifact_has_no_senses_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c21/h18: a lobes-armed, undeclared run's artifact == the unarmed floor (no senses key)."""
    from colleague.contract import Task
    from colleague.engines.mock import MockEngine

    with _serving(PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    result = MockEngine().work(Task(id="t", repo_path=str(tmp_path), instruction="say hi"), cfg)
    assert "senses" not in result.to_dict()

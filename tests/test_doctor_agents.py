"""#411 t7 — the doctor ``agents`` group: silent when unarmed; role/fallback lines when armed."""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

from colleague.oilcheck import agents, diagnose


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
    handler_cls = type("_H", (_CapabilitiesHandler,), {"body": json.dumps(payload).encode("utf-8")})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _role(model: str, ready: bool, ctx: int) -> dict:
    return {
        "model": model,
        "endpoint": "",
        "path": "/v1/chat/completions",
        "context": ctx,
        "ready": ready,
        "responsibilities": [],
        "forbidden_responsibilities": [],
    }


# Mirrors the live Spark advert of 2026-08-21: worker advertised but NOT ready,
# no associate role at all.
_ADVERT = {
    "cortex": _role("cortex-model", True, 1048576),
    "senses": _role("senses-model", True, 32768),
    "worker": _role("worker-model", False, 65536),
}


def _repo(tmp_path: Path, cfg: dict) -> Path:
    repo = tmp_path / "repo"
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return repo


def test_unarmed_group_is_silent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    repo = _repo(tmp_path, {})
    assert agents.checks(repo_path=repo) == []
    assert agents.probe_checks(repo_path=repo) == []
    report = diagnose(repo_path=repo)
    assert not [c for c in report["checks"] if c["id"].startswith("agents_")]


def test_armed_static_lines_and_probe_fallback_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    with _serving(_ADVERT) as url:
        repo = _repo(tmp_path, {"agents": True, "lobes": url})
        static = {c["id"]: c for c in agents.checks(repo_path=repo)}
        assert static["agents_armed"]["passed"] and static["agents_gateway"]["passed"]
        probe = {c["id"]: c for c in agents.probe_checks(repo_path=repo)}
    assert "ready" in probe["agents_role_cortex"]["message"]
    assert "ready" in probe["agents_role_senses"]["message"]
    assert "not ready → cortex fallback" in probe["agents_role_worker"]["message"]
    assert "absent → cortex fallback" in probe["agents_role_associate"]["message"]
    assert all(c["passed"] for c in probe.values())  # fallback is informational, never a failure


def test_armed_without_gateway_warns_but_does_not_fail_the_rubric(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_AGENTS", "1")
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    repo = _repo(tmp_path, {})
    static = {c["id"]: c for c in agents.checks(repo_path=repo)}
    assert static["agents_gateway"]["passed"] is False
    assert static["agents_gateway"]["severity"] == "warning"
    assert agents.probe_checks(repo_path=repo) == []


def test_unreachable_gateway_is_one_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_AGENTS", raising=False)
    repo = _repo(tmp_path, {"agents": True, "lobes": "http://127.0.0.1:9"})
    probe = agents.probe_checks(repo_path=repo)
    assert [c["id"] for c in probe] == ["agents_gateway_reachable"]
    assert probe[0]["severity"] == "warning"

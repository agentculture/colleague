"""qwen-direct (spec c7/h7): ``config show`` and ``lobes show`` name every
gateway-advertised role colleague does NOT consume by default.

Senses and muse are opt-in since the qwen-direct arc (the ``lobes`` sentinel
or an explicit model id); an operator must be able to SEE the retirement on
the two inspection surfaces rather than infer it from a missing line.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from pathlib import Path
from typing import Iterator

import pytest

from colleague.cli import main

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
}


class _Handler(http.server.BaseHTTPRequestHandler):
    body = b""

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args: object) -> None:  # silence the test log
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


def _run_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> dict:
    with contextlib.suppress(SystemExit):
        main(argv)
    out = capsys.readouterr().out
    return json.loads(out)


def test_config_show_names_senses_and_muse_as_not_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        data = _run_json(["config", "show", "--json", "--repo", str(tmp_path)], capsys)
        capsys.readouterr()
        with contextlib.suppress(SystemExit):
            main(["config", "show", "--repo", str(tmp_path)])
        text = capsys.readouterr().out
    assert data["lobes"]["not_consumed"] == ["senses", "muse"]
    assert "not consumed (opt-in): senses → stub/gemma-senses" in text
    assert "not consumed (opt-in): muse → stub/gemma-muse" in text


def test_config_show_opted_in_senses_drops_from_not_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        monkeypatch.setenv("COLLEAGUE_SENSES_MODEL", "lobes")
        data = _run_json(["config", "show", "--json", "--repo", str(tmp_path)], capsys)
    assert data["lobes"]["not_consumed"] == ["muse"]
    assert data["senses"]["model"] == "stub/gemma-senses"


def test_lobes_show_names_not_consumed_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD) as gateway:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", gateway)
        data = _run_json(["lobes", "show", "--json", "--repo", str(tmp_path)], capsys)
        capsys.readouterr()
        with contextlib.suppress(SystemExit):
            main(["lobes", "show", "--repo", str(tmp_path)])
        text = capsys.readouterr().out
    assert data["armed"] is True
    assert data["not_consumed"] == ["senses", "muse"]
    assert (
        "not consumed (opt-in): senses → stub/gemma-senses — COLLEAGUE_SENSES_MODEL=lobes" in text
    )


def test_unarmed_surfaces_carry_no_not_consumed_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.setattr("colleague.config._merged_config_json", lambda _repo: {})
    data = _run_json(["config", "show", "--json", "--repo", str(tmp_path)], capsys)
    assert "lobes" not in data

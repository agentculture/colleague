"""Tests for the lobes gateway role-resolution client (cortex/senses arc, task t1).

``colleague.lobes.resolve_roles`` is a pure-stdlib ``urllib`` GET client for the
lobes gateway's ``/capabilities`` endpoint. It resolves the ``cortex`` and
``senses`` roles colleague needs (a fast-driving mind + a tools-off front door)
and degrades to ``None`` on any failure — unreachable gateway, timeout,
non-200 status, malformed JSON, or a missing expected role — never raising.

The fixture below is pinned to the REAL live-probed gateway shape (six roles:
cortex, senses, embedder, reranker, stt, tts; each a superset dict of
``role, model, runtime, endpoint, path, context, quant, mtp, responsibilities,
forbidden_responsibilities, ready, loaded``) — see
``docs/specs/`` cortex/senses spec + the live-probe findings this task's brief
was built from. Colleague hardcodes no model id anywhere in ``colleague/lobes.py``
— every model id in these tests comes from the served fixture, and one test
below asserts the module source contains neither fixture model id literally.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from typing import Iterator

import pytest

from colleague.lobes import resolve_roles

# ---------------------------------------------------------------------------
# The real, live-probed /capabilities payload (six roles). Kept in ONE place
# in this test module so a future shape drift is a single-point fixture edit.
# ---------------------------------------------------------------------------

REAL_CAPABILITIES_PAYLOAD: dict[str, object] = {
    "cortex": {
        "role": "cortex",
        "model": "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP",
        "runtime": "vllm",
        "endpoint": "http://localhost:8000",
        "path": "/v1/chat/completions",
        "context": 131072,
        "quant": "modelopt",
        "mtp": True,
        "responsibilities": [
            "reasoning",
            "deciding",
            "planning",
            "tool_use",
            "code_repo_actions",
            "validation",
            "final_authority",
        ],
        "forbidden_responsibilities": [],
        "ready": True,
        "loaded": True,
    },
    "senses": {
        "role": "senses",
        "model": "coolthor/gemma-4-12B-it-NVFP4A16",
        "runtime": "vllm",
        "endpoint": "http://localhost:8000",
        "path": "/v1/chat/completions",
        "context": 32768,
        "quant": "compressed-tensors",
        "mtp": True,
        "responsibilities": [
            "intake",
            "normalize_input",
            "classify_intent",
            "prepare_context_packet",
            "speak_back",
        ],
        "forbidden_responsibilities": [
            "final_decision",
            "repo_action",
            "security_decision",
        ],
        "ready": True,
        "loaded": True,
    },
    "embedder": {
        "role": "embedder",
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "runtime": "vllm",
        "endpoint": "http://localhost:8000",
        "path": "/v1/embeddings",
        "context": 8192,
        "quant": "",
        "mtp": False,
        "responsibilities": ["vectorization", "memory_retrieval_input"],
        "forbidden_responsibilities": [],
        "ready": True,
        "loaded": True,
    },
    "reranker": {
        "role": "reranker",
        "model": "Qwen/Qwen3-Reranker-0.6B",
        "runtime": "vllm",
        "endpoint": "http://localhost:8000",
        "path": "/v1/rerank",
        "context": 8192,
        "quant": "",
        "mtp": False,
        "responsibilities": ["retrieval_ordering", "relevance_refinement"],
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
        "responsibilities": ["transcribe", "audio_input_to_text"],
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
        "responsibilities": ["speech_output", "synthesize"],
        "forbidden_responsibilities": [],
        "ready": True,
        "loaded": True,
    },
}


# ---------------------------------------------------------------------------
# A tiny in-process HTTP server (stdlib http.server) so tests exercise the
# real urllib transport, not a monkeypatched stand-in, for the shape-parsing
# scenarios. Timeout/connection-refused scenarios use a real dead port
# instead (also no monkeypatching needed there).
# ---------------------------------------------------------------------------


class _CapabilitiesHandler(http.server.BaseHTTPRequestHandler):
    """Serves a canned body/status at GET /capabilities; 404 elsewhere."""

    body: bytes = b"{}"
    status: int = 200
    content_type: str = "application/json"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/capabilities":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(self.status)
        self.send_header("Content-Type", self.content_type)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - silence test noise
        pass


@contextlib.contextmanager
def _serving(body: bytes, *, status: int = 200) -> Iterator[str]:
    """Serve *body* at ``/capabilities`` on a background thread; yield the base URL."""
    handler_cls = type(
        "_ScopedCapabilitiesHandler",
        (_CapabilitiesHandler,),
        {"body": body, "status": status},
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _payload_bytes(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_resolve_roles_returns_cortex_and_senses_from_the_real_shape() -> None:
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)

    assert result is not None
    assert result.cortex.model == "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
    assert result.senses.model == "coolthor/gemma-4-12B-it-NVFP4A16"
    assert result.cortex.context == 131072
    assert result.senses.context == 32768
    assert result.cortex.ready is True
    assert result.senses.ready is True
    assert result.cortex.endpoint == "http://localhost:8000"
    assert result.cortex.path == "/v1/chat/completions"
    assert result.senses.forbidden_responsibilities == (
        "final_decision",
        "repo_action",
        "security_decision",
    )
    assert result.cortex.responsibilities == (
        "reasoning",
        "deciding",
        "planning",
        "tool_use",
        "code_repo_actions",
        "validation",
        "final_authority",
    )


def test_resolve_roles_hardcodes_no_model_id() -> None:
    """Every model id in the resolved result must come from the payload, not colleague.

    Belt-and-braces on top of the happy-path equality assertions above:
    scan colleague/lobes.py's own source for the two live fixture model ids —
    neither may appear as a literal in the module.
    """
    import colleague.lobes as lobes_module

    source = __import__("inspect").getsource(lobes_module)
    assert "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP" not in source
    assert "coolthor/gemma-4-12B-it-NVFP4A16" not in source


def test_resolve_roles_tolerates_the_other_four_roles_present() -> None:
    """The six-role payload (embedder/reranker/stt/tts alongside cortex/senses)
    must not break resolution — those four are ignored, not errored on."""
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)

    assert result is not None
    # No attribute for the ignored roles is asserted here on purpose — the
    # public surface is exactly cortex + senses.
    assert not hasattr(result, "embedder")
    assert not hasattr(result, "stt")


# ---------------------------------------------------------------------------
# Degradation — every failure mode returns None, never raises
# ---------------------------------------------------------------------------


def test_resolve_roles_unreachable_gateway_returns_none() -> None:
    # Nothing listens on this port — a real connection-refused.
    result = resolve_roles("http://127.0.0.1:1")
    assert result is None


def test_resolve_roles_connect_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    result = resolve_roles("http://127.0.0.1:9999")
    assert result is None


def test_resolve_roles_malformed_json_returns_none() -> None:
    with _serving(b"not-json-at-all{{{") as url:
        result = resolve_roles(url)
    assert result is None


def test_resolve_roles_non_dict_json_returns_none() -> None:
    with _serving(_payload_bytes([1, 2, 3])) as url:
        result = resolve_roles(url)
    assert result is None


def test_resolve_roles_non_200_status_returns_none() -> None:
    with _serving(b"internal error", status=500) as url:
        result = resolve_roles(url)
    assert result is None


def test_resolve_roles_missing_senses_key_returns_none() -> None:
    partial = {k: v for k, v in REAL_CAPABILITIES_PAYLOAD.items() if k != "senses"}
    with _serving(_payload_bytes(partial)) as url:
        result = resolve_roles(url)
    assert result is None


def test_resolve_roles_missing_cortex_key_returns_none() -> None:
    partial = {k: v for k, v in REAL_CAPABILITIES_PAYLOAD.items() if k != "cortex"}
    with _serving(_payload_bytes(partial)) as url:
        result = resolve_roles(url)
    assert result is None


def test_resolve_roles_role_missing_expected_field_returns_none() -> None:
    """A role dict present but missing one of the fields we capture degrades cleanly."""
    broken = json.loads(json.dumps(REAL_CAPABILITIES_PAYLOAD))
    del broken["senses"]["context"]
    with _serving(_payload_bytes(broken)) as url:
        result = resolve_roles(url)
    assert result is None


def test_resolve_roles_never_raises_on_garbage_url() -> None:
    # Not a valid URL scheme at all — urllib raises ValueError internally.
    result = resolve_roles("not-a-valid-url-at-all")
    assert result is None


def test_resolve_roles_never_raises_on_empty_url() -> None:
    result = resolve_roles("")
    assert result is None

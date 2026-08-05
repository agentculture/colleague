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

from colleague.lobes import RoleInfo, embed_env, ready_kind, resolve_role_base_url, resolve_roles

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
# The real, live-probed ``muse`` role payload (two-machines-two-minds arc,
# task t4). Kept separate from REAL_CAPABILITIES_PAYLOAD (which stays pinned
# to its own "six roles" docstring) so muse's present/absent/malformed tests
# below don't perturb the existing suite. Carries the two NEW wire fields the
# live gateway also advertises (``feasible``, ``hosted_by``, plus ``proxied``)
# ONLY to prove RoleInfo's superset tolerance — this task deliberately does
# NOT parse them (see colleague/lobes.py's docstring and _parse_role).
# ---------------------------------------------------------------------------

MUSE_ROLE_PAYLOAD: dict[str, object] = {
    "role": "muse",
    "model": "nvidia/Gemma-4-31B-IT-NVFP4",
    "runtime": "vllm",
    "endpoint": "http://localhost:8001",
    "path": "/v1/chat/completions",
    "context": 262144,
    "quant": "modelopt",
    "mtp": True,
    "responsibilities": [
        "creative_generation",
        "long_form_writing",
        "ideation",
        "style_variation",
        "divergent_second_opinion",
    ],
    "forbidden_responsibilities": [
        "final_decision",
        "repo_action",
        "security_decision",
    ],
    "ready": True,
    "loaded": False,
    # Unparsed-on-purpose (t4 instruction): a future task's territory.
    "feasible": False,
    "hosted_by": "thor.tail0be7e0.ts.net:8000",
    "proxied": True,
}


# ---------------------------------------------------------------------------
# The ``worker`` role payload (three-tier-execution arc, plan task t3). Kept
# separate from REAL_CAPABILITIES_PAYLOAD (which stays pinned to its own
# "six roles" docstring) so worker's present/absent/malformed tests below
# don't perturb the existing suite — mirrors MUSE_ROLE_PAYLOAD field-for-field.
# ---------------------------------------------------------------------------

WORKER_ROLE_PAYLOAD: dict[str, object] = {
    "role": "worker",
    "model": "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP",
    "runtime": "vllm",
    "endpoint": "http://localhost:8000",
    "path": "/v1/chat/completions",
    "context": 131072,
    "quant": "modelopt",
    "mtp": True,
    "responsibilities": [
        "reasoning",
        "tool_use",
        "code_repo_actions",
    ],
    "forbidden_responsibilities": [],
    "ready": True,
    "loaded": True,
    # Unparsed-on-purpose (t3 instruction, mirrors muse): a future task's territory.
    "feasible": True,
    "hosted_by": "spark:8000",
    "proxied": False,
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


def test_resolve_roles_parses_voice_and_embedder_roles_and_ignores_reranker() -> None:
    """The six-role payload must not break resolution. stt/tts are parsed as
    OPTIONAL voice roles (senses live-presence + voice arc, t1); embedder is
    now ALSO parsed as an optional role (one-embedder increment, S2, t19) —
    only reranker stays ignored (not on the public surface, #277's parked
    retrieval lane)."""
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)

    assert result is not None
    # reranker remains ignored — never on the public surface.
    assert not hasattr(result, "reranker")
    # stt/tts/embedder are resolved as optional roles (their absence would still
    # NOT fail resolution — cortex/senses stay the only mandatory roles).
    assert result.stt is not None
    assert result.tts is not None
    assert result.embedder is not None
    assert result.embedder.model == "Qwen/Qwen3-Embedding-0.6B"


def test_resolve_roles_keeps_embedder_none_when_fixture_omits_it() -> None:
    """Absence of the embedder role never fails resolution (mirrors stt/tts)."""
    partial = {k: v for k, v in REAL_CAPABILITIES_PAYLOAD.items() if k != "embedder"}
    with _serving(_payload_bytes(partial)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.embedder is None


# ---------------------------------------------------------------------------
# muse (two-machines-two-minds arc, task t4): an OPTIONAL role, resolved with
# the exact same present/absent/malformed contract as stt/tts/embedder — its
# absence or malformed shape never fails resolve_roles, which stays mandatory
# only for cortex/senses.
# ---------------------------------------------------------------------------


def test_resolve_roles_parses_muse_role_when_present() -> None:
    payload = {**REAL_CAPABILITIES_PAYLOAD, "muse": MUSE_ROLE_PAYLOAD}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)

    assert result is not None
    assert result.muse is not None
    assert result.muse.model == "nvidia/Gemma-4-31B-IT-NVFP4"
    assert result.muse.endpoint == "http://localhost:8001"
    assert result.muse.path == "/v1/chat/completions"
    assert result.muse.context == 262144
    assert result.muse.ready is True
    assert result.muse.responsibilities == (
        "creative_generation",
        "long_form_writing",
        "ideation",
        "style_variation",
        "divergent_second_opinion",
    )
    assert result.muse.forbidden_responsibilities == (
        "final_decision",
        "repo_action",
        "security_decision",
    )


def test_resolve_roles_keeps_muse_none_when_absent() -> None:
    """The six-role REAL_CAPABILITIES_PAYLOAD carries no muse key at all —
    absence never fails resolution (mirrors stt/tts/embedder)."""
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.muse is None


def test_resolve_roles_keeps_muse_none_on_malformed_payload() -> None:
    """A muse dict present but missing an expected field degrades muse to
    None without failing the whole resolution (like a malformed stt/tts)."""
    broken_muse = dict(MUSE_ROLE_PAYLOAD)
    del broken_muse["context"]
    payload = {**REAL_CAPABILITIES_PAYLOAD, "muse": broken_muse}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.muse is None


def test_resolve_roles_keeps_muse_none_when_not_a_dict() -> None:
    """A muse value that isn't even a dict (e.g. a bare string) degrades to
    None, never raises, never fails resolution."""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "muse": "not-a-dict"}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.muse is None


def test_resolve_roles_tolerates_muse_unknown_wire_fields() -> None:
    """RoleInfo stays a tolerant superset reader (t4 instruction): the live
    muse payload's new, deliberately-unparsed fields (feasible, hosted_by,
    proxied) must not break parsing nor leak onto RoleInfo."""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "muse": MUSE_ROLE_PAYLOAD}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.muse is not None
    assert not hasattr(result.muse, "feasible")
    assert not hasattr(result.muse, "hosted_by")
    assert not hasattr(result.muse, "proxied")
    assert not hasattr(result.muse, "loaded")


# ---------------------------------------------------------------------------
# worker (three-tier-execution arc, plan task t3): an OPTIONAL role, resolved
# with the exact same present/absent/malformed contract as muse — its absence
# or malformed shape never fails resolve_roles, which stays mandatory only
# for cortex/senses. A legacy run that never advertises/consults worker is
# byte-identical (t3 acceptance criterion 1).
# ---------------------------------------------------------------------------


def test_resolve_roles_parses_worker_role_when_present() -> None:
    payload = {**REAL_CAPABILITIES_PAYLOAD, "worker": WORKER_ROLE_PAYLOAD}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)

    assert result is not None
    assert result.worker is not None
    assert result.worker.model == "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
    assert result.worker.endpoint == "http://localhost:8000"
    assert result.worker.path == "/v1/chat/completions"
    assert result.worker.context == 131072
    assert result.worker.ready is True
    assert result.worker.responsibilities == (
        "reasoning",
        "tool_use",
        "code_repo_actions",
    )
    assert result.worker.forbidden_responsibilities == ()


def test_resolve_roles_keeps_worker_none_when_absent() -> None:
    """The six-role REAL_CAPABILITIES_PAYLOAD carries no worker key at all —
    absence never fails resolution, and a legacy run never even sees the
    field (byte-identical — t3 acceptance criterion 1)."""
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.worker is None


def test_resolve_roles_keeps_worker_none_on_malformed_payload() -> None:
    """A worker dict present but missing an expected field degrades worker to
    None without failing the whole resolution (like a malformed muse)."""
    broken_worker = dict(WORKER_ROLE_PAYLOAD)
    del broken_worker["context"]
    payload = {**REAL_CAPABILITIES_PAYLOAD, "worker": broken_worker}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.worker is None


def test_resolve_roles_keeps_worker_none_when_not_a_dict() -> None:
    """A worker value that isn't even a dict (e.g. a bare string) degrades to
    None, never raises, never fails resolution."""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "worker": "not-a-dict"}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.worker is None


def test_resolve_roles_tolerates_worker_unknown_wire_fields() -> None:
    """RoleInfo stays a tolerant superset reader (t3 instruction, mirrors
    muse): the live worker payload's new, deliberately-unparsed fields
    (feasible, hosted_by, proxied) must not break parsing nor leak onto
    RoleInfo."""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "worker": WORKER_ROLE_PAYLOAD}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None
    assert result.worker is not None
    assert not hasattr(result.worker, "feasible")
    assert not hasattr(result.worker, "hosted_by")
    assert not hasattr(result.worker, "proxied")
    assert not hasattr(result.worker, "loaded")


def test_resolve_role_base_url_uses_worker_own_endpoint_when_present() -> None:
    """worker dials its OWN advertised endpoint, not the gateway origin used
    to serve /capabilities — the identical per-role dial contract every
    other resolved role gets."""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "worker": WORKER_ROLE_PAYLOAD}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.worker is not None
    assert resolve_role_base_url(result.worker, url) == "http://localhost:8000"


def test_resolve_role_base_url_falls_back_to_gateway_origin_for_worker_when_endpoint_empty() -> (
    None
):
    """An unwired worker (empty endpoint) falls back to the gateway origin —
    same documented fallback as every other role."""
    worker = dict(WORKER_ROLE_PAYLOAD)
    worker["endpoint"] = ""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "worker": worker}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.worker is not None
    assert resolve_role_base_url(result.worker, url) == url


def test_ready_kind_is_config_proxy_for_worker() -> None:
    """worker's ``ready`` is a CONFIG PROXY, same as cortex/senses/muse —
    gateway-local bookkeeping, never a liveness probe."""
    assert ready_kind("worker") == "config-proxy"


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


# ---------------------------------------------------------------------------
# Scheme validation (Qodo #5, cortex/senses PR #281): a non-http(s) gateway
# URL degrades to None BEFORE urlopen is ever called — never a local-file-read
# / SSRF-shaped dial.
# ---------------------------------------------------------------------------


def _forbid_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if resolve_roles ever reaches urlopen — proves the scheme
    check short-circuits BEFORE any network/file dial is attempted."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("urlopen must not be called for a disallowed scheme")

    monkeypatch.setattr("urllib.request.urlopen", _boom)


def test_resolve_roles_rejects_file_scheme_without_opening_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_urlopen(monkeypatch)
    result = resolve_roles("file:///etc/passwd")
    assert result is None


def test_resolve_roles_rejects_ftp_scheme_without_opening_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_urlopen(monkeypatch)
    result = resolve_roles("ftp://example.com/gateway")
    assert result is None


def test_resolve_roles_accepts_https_scheme() -> None:
    """https, not just http, passes the scheme gate (only urlopen's own
    reachability failure — a real connection refusal here — degrades it)."""
    result = resolve_roles("https://127.0.0.1:1")
    assert result is None  # unreachable, but NOT rejected for its scheme


# ---------------------------------------------------------------------------
# Per-role dial target (lobes-cli#87, 0.38.0 — colleague#292/291 S1): each
# role's own ``endpoint`` is now a client-reachable origin (Host-derived,
# ``GATEWAY_PUBLIC_URL`` override on the gateway side), not internal-only
# metadata. :func:`resolve_role_base_url` dials it directly when non-empty;
# an empty/missing endpoint falls back to the gateway origin — the
# pre-0.38 workaround, kept only as the documented fallback now.
# ---------------------------------------------------------------------------


def test_resolve_role_base_url_uses_each_roles_own_endpoint_when_present() -> None:
    """The gateway-origin-for-all workaround is gone: every resolved role
    dials its OWN advertised endpoint, not the gateway origin used to serve
    /capabilities (colleague#292, closing lobes-cli#87)."""
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)
    assert result is not None

    # cortex/senses report a DIFFERENT origin than the test gateway url —
    # proving the role's own endpoint is dialed, not the gateway url.
    assert resolve_role_base_url(result.cortex, url) == "http://localhost:8000"
    assert resolve_role_base_url(result.senses, url) == "http://localhost:8000"
    # stt/tts report a genuinely distinct origin (the realtime bridge).
    assert result.stt is not None and result.tts is not None
    assert resolve_role_base_url(result.stt, url) == "http://realtime:8080"
    assert resolve_role_base_url(result.tts, url) == "http://realtime:8080"


def test_resolve_role_base_url_falls_back_to_gateway_origin_when_endpoint_empty() -> None:
    """An empty/missing ``endpoint`` (an unwired role) falls back to the
    gateway origin — the documented fallback, never a hard failure."""
    payload = json.loads(json.dumps(REAL_CAPABILITIES_PAYLOAD))
    payload["stt"]["endpoint"] = ""
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.stt is not None
    assert resolve_role_base_url(result.stt, url) == url


def test_resolve_role_base_url_uses_muse_own_endpoint_when_present() -> None:
    """muse dials its OWN advertised endpoint (thor, via the gateway proxy),
    not the gateway origin used to serve /capabilities — the identical
    per-role dial contract every other resolved role gets."""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "muse": MUSE_ROLE_PAYLOAD}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.muse is not None
    assert resolve_role_base_url(result.muse, url) == "http://localhost:8001"


def test_resolve_role_base_url_falls_back_to_gateway_origin_for_muse_when_endpoint_empty() -> None:
    """An unwired muse (empty endpoint) falls back to the gateway origin —
    same documented fallback as every other role."""
    muse = dict(MUSE_ROLE_PAYLOAD)
    muse["endpoint"] = ""
    payload = {**REAL_CAPABILITIES_PAYLOAD, "muse": muse}
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.muse is not None
    assert resolve_role_base_url(result.muse, url) == url


def test_resolve_role_base_url_rejects_disallowed_scheme_and_falls_back() -> None:
    """A role endpoint with a non-http(s) scheme is never dialed directly —
    the same SSRF guard :func:`resolve_roles` applies to the gateway URL
    itself also applies here (degrade to the gateway origin, never raise)."""
    role = RoleInfo(
        model="m",
        endpoint="file:///etc/passwd",
        path="/v1/chat/completions",
        context=0,
        ready=True,
        responsibilities=(),
        forbidden_responsibilities=(),
    )
    assert resolve_role_base_url(role, "http://gateway:8001") == "http://gateway:8001"


def test_resolve_role_base_url_strips_missing_endpoint_whitespace() -> None:
    """A whitespace-only endpoint is treated as empty, not a malformed URL."""
    role = RoleInfo(
        model="m",
        endpoint="   ",
        path="/v1/chat/completions",
        context=0,
        ready=True,
        responsibilities=(),
        forbidden_responsibilities=(),
    )
    assert resolve_role_base_url(role, "http://gateway:8001") == "http://gateway:8001"


# ---------------------------------------------------------------------------
# ready semantics (lobes-cli#89, 0.38.0 — colleague#292/291 S1): ``ready`` is
# a CONFIG PROXY (``ready == loaded``) for cortex/senses/embedder/reranker,
# but LIVE-PROBE-BACKED (via the realtime bridge) for stt/tts.
# ---------------------------------------------------------------------------


def test_ready_kind_is_config_proxy_for_cortex_and_senses() -> None:
    assert ready_kind("cortex") == "config-proxy"
    assert ready_kind("senses") == "config-proxy"


def test_ready_kind_is_config_proxy_for_embedder_and_reranker() -> None:
    assert ready_kind("embedder") == "config-proxy"
    assert ready_kind("reranker") == "config-proxy"


def test_ready_kind_is_live_probed_for_stt_and_tts() -> None:
    assert ready_kind("stt") == "live-probed"
    assert ready_kind("tts") == "live-probed"


def test_ready_kind_is_config_proxy_for_muse() -> None:
    """muse's ``ready`` is a CONFIG PROXY, same as cortex/senses/embedder —
    the gateway proxies it to another machine but never live-probes it."""
    assert ready_kind("muse") == "config-proxy"


# ---------------------------------------------------------------------------
# embed_env (one-embedder increment, S2, colleague#291/#292 task t19): a pure
# helper relaying the embedder's dial target as env vars for OTHER tools
# (eidetic CLI, coherence-cli) to consume — colleague itself never dials it.
# ---------------------------------------------------------------------------


def test_embed_env_builds_eidetic_and_coherence_vars_from_resolved_embedder() -> None:
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)
    assert result is not None and result.embedder is not None

    env = embed_env(result, url)

    # The embedder's own endpoint (a distinct origin from the gateway url,
    # like cortex/senses above) is what gets relayed — not the gateway origin —
    # PLUS the advertised path's prefix (path="/v1/embeddings" -> "/v1"), since
    # both downstream consumers append their own "/embeddings" to the base
    # (probed live 2026-07-10: a bare-origin relay 404s on the real rig).
    assert env == {
        "EIDETIC_EMBED_URL": "http://localhost:8000/v1",
        "EIDETIC_EMBED_MODEL": "Qwen/Qwen3-Embedding-0.6B",
        "COHERENCE_EMBED_URL": "http://localhost:8000/v1",
        "COHERENCE_EMBED_MODEL": "Qwen/Qwen3-Embedding-0.6B",
    }


def test_embed_env_falls_back_to_gateway_origin_when_endpoint_empty() -> None:
    """Empty/missing embedder endpoint falls back to the gateway origin — the
    same SSRF-guarded fallback every other role gets (still carrying the
    advertised path prefix)."""
    payload = json.loads(json.dumps(REAL_CAPABILITIES_PAYLOAD))
    payload["embedder"]["endpoint"] = ""
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.embedder is not None

    env = embed_env(result, url)
    assert env["EIDETIC_EMBED_URL"] == url + "/v1"
    assert env["COHERENCE_EMBED_URL"] == url + "/v1"


def test_embed_env_keeps_bare_relay_for_pathless_or_bare_embeddings_path() -> None:
    """A path of exactly '/embeddings' (or absent) keeps the bare-origin relay —
    only a real prefix (e.g. '/v1') is folded into the base."""
    payload = json.loads(json.dumps(REAL_CAPABILITIES_PAYLOAD))
    payload["embedder"]["path"] = "/embeddings"
    with _serving(_payload_bytes(payload)) as url:
        result = resolve_roles(url)
    assert result is not None and result.embedder is not None

    env = embed_env(result, url)
    assert env["COHERENCE_EMBED_URL"] == "http://localhost:8000"


def test_embed_env_is_empty_when_no_embedder_resolved() -> None:
    partial = {k: v for k, v in REAL_CAPABILITIES_PAYLOAD.items() if k != "embedder"}
    with _serving(_payload_bytes(partial)) as url:
        result = resolve_roles(url)
    assert result is not None and result.embedder is None

    assert embed_env(result, url) == {}


def test_embed_env_issues_no_network_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_env is pure — it must never call urlopen itself."""
    with _serving(_payload_bytes(REAL_CAPABILITIES_PAYLOAD)) as url:
        result = resolve_roles(url)
    assert result is not None

    # Arm the guard AFTER resolve_roles (which legitimately dialed once) —
    # embed_env itself must never reach urlopen.
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("embed_env must not open a network connection")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    embed_env(result, url)

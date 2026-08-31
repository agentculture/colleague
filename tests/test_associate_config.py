"""Associate seat A (adopt-from-qwen-code plan task t18; spec c37/h26, c49/h36, c52).

The ``associate`` lobes role — a fast, tool-capable, NON-coding seat (Nemotron
3.5 Lightning on the Orin, proxied through spark's gateway) — is consumed the
v1.63 opt-in way, exactly like deepthink's muse rung::

    COLLEAGUE_ASSOCIATE_* env > config.json ``associate`` section > (only when
    the declared model is the sentinel ``lobes``) the gateway's advertised
    ``associate`` role > absent (``None``, byte-identical to main)

Live facts this file pins (probed 2026-08-27 against spark's gateway):

* the gateway completes ``{"model": "associate"}`` (the ROLE NAME) through the
  proxy but refuses the raw served id / ``worker`` with ``role_infeasible`` —
  so the seat addresses the wire by role name and records the SERVED model
  from the reply's ``model`` field, never the alias (c49/h36);
* the proxied advert claims ``context: 1048576`` while the origin says 128000
  — the budget derives from the advert with the deepthink headroom ratio, and
  the spec's live window discovery (c38) stays the authority for the clamp;
* the seat streams exactly like cortex (c52): stream + include_usage.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.server
import io
import json
import threading
import urllib.error
from pathlib import Path
from typing import Iterator

import pytest

from colleague import associate as associate_mod
from colleague import effort
from colleague.associate_config import (
    _DEFAULT_ASSOCIATE_CONTEXT_BUDGET,
    ASSOCIATE_WIRE_MODEL,
    AssociateConfig,
    _associate_budget_from_window,
)
from colleague.cli import main
from colleague.cli._commands._listing import OPT_IN_ROLE_ATTRS, not_consumed_roles_from
from colleague.config import _DEFAULT_API_KEY, EngineConfig
from colleague.engines import vllm_openai
from colleague.loop import ModelResponse

_CORTEX_MODEL = "lobes-cortex-sentinel-model"
_SENSES_MODEL = "lobes-senses-sentinel-model"
_ASSOCIATE_MODEL = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
_ROLE_ENDPOINT = "http://localhost:8000"
# The proxied advert's (untrusted, c38) window claim as probed live.
_ASSOCIATE_ADVERT_WINDOW = 1048576

_ROLE = {
    "runtime": "vllm",
    "endpoint": _ROLE_ENDPOINT,
    "path": "/v1/chat/completions",
    "quant": "modelopt",
    "mtp": False,
    "responsibilities": ["reasoning"],
    "forbidden_responsibilities": [],
    "ready": True,
    "loaded": True,
}
PAYLOAD_WITH_ASSOCIATE: dict[str, object] = {
    "cortex": {**_ROLE, "role": "cortex", "model": _CORTEX_MODEL, "context": 131072},
    "senses": {**_ROLE, "role": "senses", "model": _SENSES_MODEL, "context": 32768},
    "associate": {
        **_ROLE,
        "role": "associate",
        "model": _ASSOCIATE_MODEL,
        "context": _ASSOCIATE_ADVERT_WINDOW,
        "tools": True,
        "responsibilities": ["execution", "repo_inspection", "tool_use"],
        "forbidden_responsibilities": [
            "final_decision",
            "security_decision",
            "code_authoring",
            "repo_action",
        ],
        # As probed live: the proxy reports the role not ready/loaded while
        # the Orin serves it fine — the rung must NOT gate on these.
        "ready": False,
        "loaded": False,
    },
}
PAYLOAD_WITHOUT_ASSOCIATE: dict[str, object] = {
    k: v for k, v in PAYLOAD_WITH_ASSOCIATE.items() if k != "associate"
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
    "COLLEAGUE_ASSOCIATE_MODEL",
    "COLLEAGUE_ASSOCIATE_BASE_URL",
    "COLLEAGUE_ASSOCIATE_API_KEY",
    "COLLEAGUE_ASSOCIATE_CONTEXT_BUDGET",
    "COLLEAGUE_ASSOCIATE_REASONING_EFFORT",
    "COLLEAGUE_DEEPTHINK_MODEL",
    "COLLEAGUE_SENSES_MODEL",
    "COLLEAGUE_STREAM",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_home(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path_factory.mktemp("home"))


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
        "_Handler", (_CapabilitiesHandler,), {"body": json.dumps(payload).encode("utf-8")}
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _write_config(repo: Path, payload: dict) -> None:
    cfg_dir = repo / ".colleague"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")


# ── c37/h26: opt-in resolution, byte-identical when unarmed ─────────────────


def test_unarmed_is_byte_identical_with_associate_advertised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lobes armed + associate advertised + no COLLEAGUE_ASSOCIATE_MODEL → the
    resolved config is identical to one resolved against a gateway that never
    advertised the role at all (the qwen-direct 'bare run dials ONE model' line)."""
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        armed_with = EngineConfig.resolve(repo_path=tmp_path)
    with _serving(PAYLOAD_WITHOUT_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        armed_without = EngineConfig.resolve(repo_path=tmp_path)
    assert armed_with.associate is None
    assert armed_without.associate is None
    assert armed_with.model == _CORTEX_MODEL
    assert armed_with.to_dict() == armed_without.to_dict()
    assert "associate" not in armed_with.to_dict()


def test_sentinel_lobes_resolves_from_the_advertised_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assoc = cfg.associate
    assert isinstance(assoc, AssociateConfig)
    assert assoc.model == _ASSOCIATE_MODEL  # the SERVED id, from the advert
    assert assoc.wire_model == ASSOCIATE_WIRE_MODEL == "associate"
    assert assoc.addressed_as_role is True
    assert assoc.base_url == f"{_ROLE_ENDPOINT}/v1"
    # Same-origin as the role endpoint the cortex advert names → main key inherited.
    assert assoc.api_key == cfg.api_key
    assert assoc.context_budget == _associate_budget_from_window(_ASSOCIATE_ADVERT_WINDOW)
    # The main seat is untouched by arming associate.
    assert cfg.model == _CORTEX_MODEL


def test_sentinel_lobes_without_an_advertised_role_stays_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _serving(PAYLOAD_WITHOUT_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.associate is None


def test_explicit_model_id_is_addressed_by_id_not_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "some/explicit-fast-model")
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_BASE_URL", "http://orin:8000/v1")
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_API_KEY", "assoc-key")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assoc = cfg.associate
    assert assoc is not None
    assert assoc.model == assoc.wire_model == "some/explicit-fast-model"
    assert assoc.addressed_as_role is False
    assert assoc.base_url == "http://orin:8000/v1"
    assert assoc.api_key == "assoc-key"
    assert assoc.context_budget == _DEFAULT_ASSOCIATE_CONTEXT_BUDGET


def test_config_json_section_is_honored_and_env_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(
        tmp_path,
        {"associate": {"model": "file/model", "context_budget": "12345"}},
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.associate is not None
    assert cfg.associate.model == "file/model"
    assert cfg.associate.context_budget == 12345
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "env/model")
    assert EngineConfig.resolve(repo_path=tmp_path).associate.model == "env/model"


def test_cross_origin_discovered_associate_never_inherits_the_main_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(json.dumps(PAYLOAD_WITH_ASSOCIATE))
    payload["associate"]["endpoint"] = "http://orin.example:8000"
    with _serving(payload) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        monkeypatch.setenv("COLLEAGUE_API_KEY", "main-secret")
        cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.associate is not None
    assert cfg.associate.base_url == "http://orin.example:8000/v1"
    assert cfg.associate.api_key == _DEFAULT_API_KEY


def test_budget_ratio_mirrors_deepthink_headroom() -> None:
    assert _associate_budget_from_window(0) == _DEFAULT_ASSOCIATE_CONTEXT_BUDGET
    assert _associate_budget_from_window(-1) == _DEFAULT_ASSOCIATE_CONTEXT_BUDGET
    assert 0 < _associate_budget_from_window(1) <= _DEFAULT_ASSOCIATE_CONTEXT_BUDGET
    assert _associate_budget_from_window(131072) == _DEFAULT_ASSOCIATE_CONTEXT_BUDGET


# ── effort table row ────────────────────────────────────────────────────────


def test_effort_table_gains_an_associate_row_defaulting_to_low() -> None:
    # v4 (#475): Nemotron on the armed associate seat needs "low" as its floor.
    assert effort.SEAT_TABLE["associate"] == "low"
    assert effort.resolve_effort(seat="associate") == "low"
    assert effort.to_chat_template_kwargs("low") == {"reasoning_effort": "low"}


def test_associate_seat_effort_override_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_REASONING_EFFORT", "low")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.reasoning_effort_seats["associate"] == "low"


# ── the seat builder: wire addressing, streaming parity, served-model record ─


def _armed_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EngineConfig:
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        return EngineConfig.resolve(repo_path=tmp_path)


def test_seat_builder_returns_none_when_unarmed(tmp_path: Path) -> None:
    assert associate_mod.associate_engine_config(EngineConfig.resolve(repo_path=tmp_path)) is None


def test_seat_sends_the_role_name_on_the_wire_and_streams_like_cortex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _armed_config(tmp_path, monkeypatch)
    seat = associate_mod.associate_engine_config(cfg)
    assert seat is not None
    assert seat.model == "associate"
    assert seat.base_url == cfg.associate.base_url
    assert seat.context_budget_tokens == cfg.associate.context_budget
    assert associate_mod.served_model_expected(seat) == _ASSOCIATE_MODEL
    assert associate_mod.wire_fallback_model(seat) == _ASSOCIATE_MODEL
    engine = vllm_openai.VllmOpenAIEngine()
    messages = [{"role": "user", "content": "hi"}]
    cortex_payload, cortex_streams = engine._build_chat_payload(cfg, messages, [])
    seat_payload, seat_streams = engine._build_chat_payload(seat, messages, [])
    assert cortex_streams is True
    assert seat_streams is True
    assert seat_payload["model"] == "associate"
    # c52: the associate seat streams exactly as cortex does, headless included.
    assert cortex_payload["stream"] is True
    assert seat_payload["stream"] is True
    assert (
        seat_payload["stream_options"]
        == cortex_payload["stream_options"]
        == {"include_usage": True}
    )
    # The seat's own effort rung: thinking OFF (Nemotron spends its first
    # tokens thinking; the scout seat must not).
    # t23: the associate seat sends its PROFILE (depth: thinking on, temperature 0.6,
    # top_p 0.95, no max_tokens) instead of the scout rung / cortex temperature.
    assert seat_payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert seat_payload["temperature"] == 0.6
    assert seat_payload["top_p"] == 0.95
    assert "max_tokens" not in seat_payload
    assert cortex_payload.get("chat_template_kwargs") != {"enable_thinking": False}


def test_seat_effort_override_and_kill_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _armed_config(tmp_path, monkeypatch)
    low = associate_mod.associate_engine_config(
        dataclasses.replace(cfg, reasoning_effort_seats={"associate": "low"})
    )
    assert vllm_openai._effort_for(low) == "low"
    killed = associate_mod.associate_engine_config(
        dataclasses.replace(cfg, reasoning_effort="default")
    )
    assert vllm_openai._effort_for(killed) is None


def test_blocking_and_streaming_replies_carry_the_served_model() -> None:
    blocking = vllm_openai._parse_response(
        {
            "model": _ASSOCIATE_MODEL,
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }
    )
    assert blocking.served_model == _ASSOCIATE_MODEL
    acc = vllm_openai._StreamAccumulator()
    vllm_openai._apply_stream_frame(
        {"model": _ASSOCIATE_MODEL, "choices": [{"delta": {"content": "o"}}]},
        acc,
        lambda _t: None,
    )
    assert acc.served_model == _ASSOCIATE_MODEL
    # Default stays empty — every other engine's ModelResponse is unchanged.
    assert ModelResponse().served_model == ""


def test_role_name_rejection_falls_back_once_to_the_served_id_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _armed_config(tmp_path, monkeypatch)
    seat = associate_mod.associate_engine_config(cfg)
    assert seat is not None
    payload = {"model": "associate", "messages": []}
    calls: list[str] = []

    def dispatch() -> ModelResponse:
        calls.append(payload["model"])
        return ModelResponse(content="ok", served_model=_ASSOCIATE_MODEL)

    exc = urllib.error.HTTPError(
        "http://x/v1/chat/completions",
        400,
        "role_infeasible: The model `associate` is not feasible on this machine",
        {},
        io.BytesIO(b""),
    )
    engine = vllm_openai.VllmOpenAIEngine()
    resp = engine._recover_http_error(exc, payload, "cortex", None, seat, dispatch)
    assert resp.content == "ok"
    assert calls == [_ASSOCIATE_MODEL]
    assert payload["model"] == _ASSOCIATE_MODEL
    assert seat.model == _ASSOCIATE_MODEL
    warning = seat.model_refresh_warnings[-1]
    assert warning.role == "associate"
    assert warning.stale_id == "associate"
    assert warning.refreshed_id == _ASSOCIATE_MODEL
    assert "associate" in capsys.readouterr().err
    # ONCE: a second rejection on the served id propagates unchanged — the
    # consumer (seat B) is what falls to the cortex fallback from here.
    with pytest.raises(urllib.error.HTTPError):
        engine._recover_http_error(exc, payload, "cortex", None, seat, dispatch)
    assert calls == [_ASSOCIATE_MODEL]


def test_role_name_fallback_never_fires_for_the_cortex_seat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _armed_config(tmp_path, monkeypatch)
    payload = {"model": cfg.model, "messages": []}
    exc = urllib.error.HTTPError("http://x", 400, "bad request", {}, io.BytesIO(b""))
    engine = vllm_openai.VllmOpenAIEngine()
    with pytest.raises(urllib.error.HTTPError):
        engine._recover_http_error(exc, payload, "cortex", None, cfg, lambda: None)


def test_stats_model_records_the_served_id_for_the_alias() -> None:
    from colleague.contract import Task, TaskResult
    from colleague.loop import _finalize_stats
    from colleague.tools import ToolExecutor

    result = TaskResult(task_id="t", status="ok", summary="")
    task = Task(id="t", repo_path=".", instruction="x")
    task.engine = "vllm-openai"
    _finalize_stats(
        result,
        task,
        ToolExecutor("."),
        started_at="now",
        duration_seconds=0.0,
        model="associate",
        served_model=_ASSOCIATE_MODEL,
    )
    assert result.stats.model == _ASSOCIATE_MODEL
    # A real model id is never overwritten by a served-model observation.
    _finalize_stats(
        result,
        task,
        ToolExecutor("."),
        started_at="now",
        duration_seconds=0.0,
        model="unsloth/cortex",
        served_model=_ASSOCIATE_MODEL,
    )
    assert result.stats.model == "unsloth/cortex"


# ── the two inspection surfaces ─────────────────────────────────────────────


def test_opt_in_role_table_names_associate() -> None:
    assert ("associate", "associate", "COLLEAGUE_ASSOCIATE_MODEL=lobes") in OPT_IN_ROLE_ATTRS


def test_not_consumed_lists_associate_when_advertised_but_unarmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colleague.lobes import resolve_roles

    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        cfg = EngineConfig.resolve(repo_path=tmp_path)
        roles = resolve_roles(url)
    names = [name for name, _m, _k in not_consumed_roles_from(roles, cfg)]
    assert "associate" in names
    assert "senses" in names


def test_config_show_prints_not_consumed_then_armed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        assert main(["config", "show", "--repo", str(tmp_path)]) == 0
        unarmed = capsys.readouterr().out
        assert f"not consumed (opt-in): associate → {_ASSOCIATE_MODEL}" in unarmed
        assert "COLLEAGUE_ASSOCIATE_MODEL=lobes" in unarmed
        assert "addressed as role name" not in unarmed

        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        assert main(["config", "show", "--repo", str(tmp_path)]) == 0
        armed = capsys.readouterr().out
        assert (
            f"associate → {_ASSOCIATE_MODEL} (addressed as role name via proxy; profile depth:"
            in armed
        )
        assert "not consumed (opt-in): associate" not in armed

        assert main(["config", "show", "--repo", str(tmp_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assoc = data["lobes"]["associate"]
        assert {k: assoc[k] for k in ("served_model", "wire_model", "addressed_as_role")} == {
            "served_model": _ASSOCIATE_MODEL,
            "wire_model": "associate",
            "addressed_as_role": True,
        }
        assert assoc["profile"]["name"] == "depth"  # t23
        assert "associate" not in data["lobes"]["not_consumed"]


def test_config_show_explicit_id_line_names_the_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "some/explicit")
        assert main(["config", "show", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "associate → some/explicit (explicit model id; profile depth:" in out


def test_lobes_show_lists_the_associate_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        assert main(["lobes", "show", "--repo", str(tmp_path)]) == 0
        text = capsys.readouterr().out
        assert f"associate\t{_ASSOCIATE_MODEL}\t[not ready (config-proxy)]" in text
        assert "forbidden: final_decision, security_decision, code_authoring, repo_action" in text
        assert main(["lobes", "show", "--repo", str(tmp_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["roles"]["associate"]["model"] == _ASSOCIATE_MODEL
        assert "associate" in data["not_consumed"]


def test_lobes_show_without_associate_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with _serving(PAYLOAD_WITHOUT_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        assert main(["lobes", "show", "--repo", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "associate" not in data["roles"]


def test_config_show_renders_an_explicit_associate_without_any_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Qodo #441-8: an explicit-model associate needs no lobes gateway to show."""
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "some/explicit")
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_BASE_URL", "http://orin:8000/v1")
    monkeypatch.setenv("COLLEAGUE_ASSOCIATE_API_KEY", "assoc-key")
    assert main(["config", "show", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "associate → some/explicit (explicit model id; profile depth:" in out
    assert "lobes: armed" not in out
    assert main(["config", "show", "--repo", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["associate"]["served_model"] == "some/explicit"
    assert data["associate"]["addressed_as_role"] is False


def test_lobes_show_associate_row_carries_a_canonical_armed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Qodo #441-3: one of not_configured / armed_reachable / armed_unreachable."""
    from colleague import associate_cli

    with _serving(PAYLOAD_WITH_ASSOCIATE) as url:
        monkeypatch.setenv("COLLEAGUE_LOBES_URL", url)
        monkeypatch.delenv("COLLEAGUE_ASSOCIATE_MODEL", raising=False)
        assert main(["lobes", "show", "--repo", str(tmp_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["roles"]["associate"]["armed_state"] == "not_configured"
        monkeypatch.setenv("COLLEAGUE_ASSOCIATE_MODEL", "lobes")
        assert main(["lobes", "show", "--repo", str(tmp_path)]) == 0
        text = capsys.readouterr().out
        assert "  armed_state: armed_unreachable" in text  # the advert says not ready
        assert main(["lobes", "show", "--repo", str(tmp_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["roles"]["associate"]["armed_state"] in associate_cli.ARMED_STATES
        assert data["roles"]["associate"]["armed_state"] == "armed_unreachable"

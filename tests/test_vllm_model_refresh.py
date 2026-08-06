"""Same-role stale-pin refresh AT CALL TIME (plan task t9, spec c10/c11,
honesty h7/h8) — the ``engines/vllm_openai.py`` half.

The resolution-time half lives in ``tests/test_config_model_refresh.py``.
This module covers the ONCE-only 404 ``model_not_found`` catch: the provider's
model roster can still rotate between ``EngineConfig.resolve()`` and the
actual completion request, so a live 404 is unambiguous ground truth a
resolution-time snapshot can't be. A refresh substitutes the SAME role's
freshly (never cached) discovered id and retries EXACTLY ONCE — a second
404 with the refreshed id propagates legibly, never a retry loop.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import urllib.error

import pytest

from colleague.config import EngineConfig, WorkerConfig
from colleague.engines.vllm_openai import (
    VllmOpenAIEngine,
    _is_model_not_found_404,
    _same_role_call_time_refresh,
)
from colleague.lobes import LobesRoles, ModelRefreshWarning, RoleInfo

_STALE_ID = "stale/pinned-model-id-nobody-serves"
_FRESH_ID = "fresh/currently-served-model-id"


def _role(model: str, endpoint: str = "http://role.example:8001") -> RoleInfo:
    return RoleInfo(
        model=model,
        endpoint=endpoint,
        path="/v1/chat/completions",
        context=65536,
        ready=True,
        responsibilities=(),
        forbidden_responsibilities=(),
    )


class _ErrBody:
    """Minimal file-like stand-in an HTTPError reads its body from."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:  # file-like protocol: HTTPError closes its fp on GC
        pass


class _OkResponse:
    """Minimal context-manager stand-in for a successful HTTP response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_OkResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _model_not_found_error(url: str, model_id: str) -> urllib.error.HTTPError:
    body = json.dumps(
        {
            "error": {
                "message": f"The model `{model_id}` does not exist.",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        }
    ).encode("utf-8")
    return urllib.error.HTTPError(url, 404, "Not Found", {}, _ErrBody(body))


def _ok_message(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {}}


# ---------------------------------------------------------------------------
# _is_model_not_found_404 — the exact-shape gate
# ---------------------------------------------------------------------------


def test_is_model_not_found_404_true_for_the_openai_shape() -> None:
    exc = _model_not_found_error("http://x/v1/chat/completions", _STALE_ID)
    from colleague.engines.vllm_openai import _raise_legible_http_error

    with pytest.raises(urllib.error.HTTPError) as folded:
        _raise_legible_http_error("http://x/v1/chat/completions", exc)
    assert _is_model_not_found_404(folded.value)


def test_is_model_not_found_404_false_for_a_plain_404() -> None:
    plain = urllib.error.HTTPError("http://x/wrong-route", 404, "Not Found: nope", {}, None)
    assert not _is_model_not_found_404(plain)


def test_is_model_not_found_404_false_for_a_500() -> None:
    err = urllib.error.HTTPError("http://x", 500, "model_not_found but wrong code", {}, None)
    assert err.code != 404


# ---------------------------------------------------------------------------
# _same_role_call_time_refresh — the gate directly
# ---------------------------------------------------------------------------


def test_same_role_call_time_refresh_none_when_lobes_unarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}
    from colleague import lobes as lobes_mod

    def _spy(*_a: object, **_k: object) -> None:
        called["n"] += 1
        return None

    monkeypatch.setattr(lobes_mod, "resolve_roles", _spy)
    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    assert cfg.lobes_gateway_url is None
    exc = _model_not_found_error("http://x/v1/chat/completions", _STALE_ID)
    from colleague.engines.vllm_openai import _raise_legible_http_error

    with pytest.raises(urllib.error.HTTPError) as folded:
        _raise_legible_http_error("http://x/v1/chat/completions", exc)

    assert _same_role_call_time_refresh(cfg, "cortex", folded.value) is None
    assert called["n"] == 0


def test_same_role_call_time_refresh_none_when_role_advertises_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 2: 'the role advertising no model' leaves the original
    error to surface — here the gateway simply doesn't advertise a worker
    role at all (LobesRoles.worker defaults to None)."""
    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(cortex=_role("cortex/model"), senses=_role("senses/model")),
    )
    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(cfg, lobes_gateway_url="http://gateway.example")
    exc = _model_not_found_error("http://x/v1/chat/completions", _STALE_ID)
    from colleague.engines.vllm_openai import _raise_legible_http_error

    with pytest.raises(urllib.error.HTTPError) as folded:
        _raise_legible_http_error("http://x/v1/chat/completions", exc)

    assert _same_role_call_time_refresh(cfg, "worker", folded.value) is None


def test_same_role_call_time_refresh_never_crosses_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/fresh"),
            senses=_role("senses/fresh"),
            worker=_role("worker/fresh"),
        ),
    )
    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(cfg, lobes_gateway_url="http://gateway.example")
    exc = _model_not_found_error("http://x/v1/chat/completions", _STALE_ID)
    from colleague.engines.vllm_openai import _raise_legible_http_error

    with pytest.raises(urllib.error.HTTPError) as folded:
        _raise_legible_http_error("http://x/v1/chat/completions", exc)

    assert _same_role_call_time_refresh(cfg, "cortex", folded.value) == "cortex/fresh"
    assert _same_role_call_time_refresh(cfg, "worker", folded.value) == "worker/fresh"


def test_same_role_call_time_refresh_reads_no_task_content() -> None:
    params = set(inspect.signature(_same_role_call_time_refresh).parameters)
    assert not (params & {"task", "instruction", "prompt", "messages", "message"})


# ---------------------------------------------------------------------------
# Full complete() dispatch: catches, refreshes, retries ONCE.
# ---------------------------------------------------------------------------


def test_complete_refreshes_once_and_retries_on_404_model_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    call_log: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        call_log.append(payload)
        if payload["model"] == _STALE_ID:
            raise _model_not_found_error(request.full_url, _STALE_ID)
        return _OkResponse(_ok_message("hello from the refreshed model"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(cortex=_role(_FRESH_ID), senses=_role("senses/model")),
    )

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(cfg, lobes_gateway_url="http://gateway.example")

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "hello from the refreshed model"
    assert [c["model"] for c in call_log] == [_STALE_ID, _FRESH_ID]

    assert len(cfg.model_refresh_warnings) == 1
    warning = cfg.model_refresh_warnings[0]
    assert isinstance(warning, ModelRefreshWarning)
    assert warning.role == "cortex"
    assert warning.stale_id == _STALE_ID
    assert warning.refreshed_id == _FRESH_ID
    assert warning.point == "call"

    err = capsys.readouterr().err
    assert _STALE_ID in err
    assert _FRESH_ID in err


def test_complete_second_404_with_refreshed_id_propagates_legibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second 404 — even one carrying the JUST-refreshed id — is never
    caught again: no retry loop, the original (refreshed-id) error surfaces
    legibly."""

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        raise _model_not_found_error(request.full_url, payload["model"])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(cortex=_role(_FRESH_ID), senses=_role("senses/model")),
    )

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(cfg, lobes_gateway_url="http://gateway.example")

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError) as exc:
        complete([{"role": "user", "content": "hi"}])

    assert _FRESH_ID in str(exc.value)
    # Exactly ONE refresh was recorded — the second failure was never caught.
    assert len(cfg.model_refresh_warnings) == 1


def test_complete_non_model_not_found_404_propagates_unchanged_no_lobes_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lobes_called = {"n": 0}

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, _ErrBody(b""))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from colleague import lobes as lobes_mod

    def _spy(*_a: object, **_k: object) -> None:
        lobes_called["n"] += 1
        return None

    monkeypatch.setattr(lobes_mod, "resolve_roles", _spy)

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(cfg, lobes_gateway_url="http://gateway.example")

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError):
        complete([{"role": "user", "content": "hi"}])

    assert lobes_called["n"] == 0
    assert cfg.model_refresh_warnings == ()


def test_complete_lobes_unarmed_original_404_surfaces_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        raise _model_not_found_error(request.full_url, payload["model"])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    assert cfg.lobes_gateway_url is None  # never armed in this test

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError) as exc:
        complete([{"role": "user", "content": "hi"}])

    assert _STALE_ID in str(exc.value)
    assert cfg.model_refresh_warnings == ()


def test_complete_worker_role_refresh_queries_worker_not_cortex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three-tier mode (config.worker set): the acting seat is "worker" —
    a call-time refresh must query the worker role, never cortex."""
    call_log: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        call_log.append(payload)
        if payload["model"] == _STALE_ID:
            raise _model_not_found_error(request.full_url, _STALE_ID)
        return _OkResponse(_ok_message("worker answered"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=_role("cortex/model-never-used-here"),
            senses=_role("senses/model"),
            worker=_role(_FRESH_ID),
        ),
    )

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(
        cfg,
        lobes_gateway_url="http://gateway.example",
        worker=WorkerConfig(
            model=_STALE_ID, base_url="http://x/v1", api_key="EMPTY", context=65536
        ),
    )

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "worker answered"
    assert [c["model"] for c in call_log] == [_STALE_ID, _FRESH_ID]
    assert cfg.model_refresh_warnings[0].role == "worker"
    assert cfg.model_refresh_warnings[0].refreshed_id == _FRESH_ID


def test_drive_survives_a_stale_pin_via_the_full_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """End-to-end: a work item over the mocked HTTP transport whose FIRST
    model turn 404s model_not_found still completes OK — the run proceeds,
    never dies to a rotated model id (Before -> After scenario)."""
    from colleague.contract import OK, Task

    def _finish_payload() -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-finish",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "done via refreshed id"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        if payload["model"] == _STALE_ID:
            raise _model_not_found_error(request.full_url, _STALE_ID)
        return _OkResponse(_finish_payload())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(cortex=_role(_FRESH_ID), senses=_role("senses/model")),
    )

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    cfg = dataclasses.replace(cfg, lobes_gateway_url="http://gateway.example")

    task = Task.new(str(tmp_path), "say hi", engine="vllm-openai")
    result = VllmOpenAIEngine().work(task, cfg)

    assert result.status == OK
    assert result.summary == "done via refreshed id"


# ---------------------------------------------------------------------------
# refresh_seat gating (d5, issue 375) — the refresh acts for the MAIN seat only
# ---------------------------------------------------------------------------


def test_complete_disarmed_seat_404_surfaces_unchanged_no_lobes_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replaced-config seat (refresh_seat=None) never refreshes — the 404
    surfaces into that lane's own degrade path and lobes is never queried."""
    lobes_called = {"n": 0}

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        if request.data is None:  # a GET — would be the lobes lookup
            lobes_called["n"] += 1
            raise AssertionError("lobes must not be queried for a disarmed seat")
        payload = json.loads(request.data.decode("utf-8"))
        raise _model_not_found_error(request.full_url, payload["model"])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = EngineConfig.resolve(base_url="http://x/v1", model=_STALE_ID)
    object.__setattr__(cfg, "lobes_gateway_url", "http://gw")  # armed gateway
    object.__setattr__(cfg, "refresh_seat", None)  # ...but a disarmed seat

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError) as exc:
        complete([{"role": "user", "content": "hi"}])

    assert _STALE_ID in str(exc.value)
    assert lobes_called["n"] == 0
    assert cfg.model_refresh_warnings == ()


def test_deepthink_twin_disarms_the_refresh_seat() -> None:
    from colleague.config import DeepthinkConfig
    from colleague.deepthink import deepthink_engine_config

    cfg = EngineConfig.resolve(base_url="http://x/v1", model="main/model")
    assert cfg.refresh_seat == "main"
    object.__setattr__(
        cfg,
        "deepthink",
        DeepthinkConfig(
            model="muse/model",
            base_url="http://x/v1",
            api_key="",
            context_budget=1000,
        ),
    )
    dt_cfg = deepthink_engine_config(cfg)
    assert dt_cfg is not None
    assert dt_cfg.refresh_seat is None


def test_senses_twin_disarms_the_refresh_seat() -> None:
    from colleague.config import SensesConfig
    from colleague.senses import senses_engine_config

    cfg = EngineConfig.resolve(base_url="http://x/v1", model="main/model")
    object.__setattr__(
        cfg,
        "senses",
        SensesConfig(
            model="senses/model",
            base_url="http://x/v1",
            api_key="",
            context_budget=1000,
        ),
    )
    s_cfg = senses_engine_config(cfg)
    assert s_cfg is not None
    assert s_cfg.refresh_seat is None

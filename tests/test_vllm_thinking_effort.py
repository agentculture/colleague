"""Per-seat thinking effort wired into the vLLM driver (#416 t3, spec
c2/h2/c7/h6/c27/h18/c33/h23/c1/h1/c17/h13).

Two things land here:

- ``_build_chat_payload`` emits ``chat_template_kwargs`` from the ACTING
  seat's resolved rung (``EngineConfig.reasoning_effort_effective``, or the
  optional ``config.reasoning_effort_seat`` plain-attribute override a later
  seat-builder task sets) — absent when nothing should be sent.
- a ladder-400 (the server rejecting the ``reasoning_effort`` rung) drops the
  key and retries EXACTLY ONCE, recording a warning on
  ``config.reasoning_effort_warnings`` — mirroring the call-time stale-pin
  refresh's ``config.model_refresh_warnings`` mechanism exactly (append a new
  tuple, never mutate a shared list) — and is disjoint from that refresh by
  status code (404 vs 400), so a 404->400->200 sequence fires BOTH exactly
  once.

By default (no ``reasoning_effort``/``reasoning_effort_seats`` configured) the
ACTING seat (cortex/worker) resolves to "low" (v4, #475) via ``effort.SEAT_TABLE`` —
NOT ``None`` — so "byte-identical when unset" in this task's title means the
KILL-SWITCH sentinel (``reasoning_effort="default"``), which is what
``reasoning_effort_effective`` returns ``None`` for. The existing
``tests/test_vllm_openai.py``/``tests/test_headless_streaming.py`` pins never
assert full-payload equality (only individual keys like ``stream``), so they
stay green even though their default configs now also carry
``chat_template_kwargs`` — this file locks that behavior in explicitly.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error
from typing import Any

import pytest

from colleague.config import EngineConfig
from colleague.engines.vllm_openai import (
    VllmOpenAIEngine,
    _effort_for,
    _is_ladder_400,
    _LadderRetryWarning,
)


@pytest.fixture(autouse=True)
def _no_output_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """These pins prove the pre-t16 payload shape (#416 / #393 invariants), so the
    t16 window clamp is kill-switched here; the clamp's own presence/absence is
    pinned in tests/test_loop_microcompact.py and tests/test_turnbudget.py."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")


def _cfg(**overrides: Any) -> EngineConfig:
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model="m")
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


class _ErrBody:
    """Minimal file-like stand-in an HTTPError reads its body from (mirrors
    ``tests/test_vllm_model_refresh.py``'s own helper)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:  # file-like protocol: HTTPError closes its fp on GC
        pass


class _OkResponse:
    """Minimal context-manager stand-in answering BOTH transports off the
    SAME scripted payload (blocking ``read()`` and SSE line iteration) —
    mirrors ``tests/test_vllm_model_refresh.py``'s own helper, since headless
    streaming is armed by default (#393)."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_OkResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __iter__(self):
        from tests._vllm_http import sse_lines_for_turn

        return iter(sse_lines_for_turn(self._payload))


def _ok_message(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {}}


def _http_error(url: str, code: int, reason: str, message: str) -> urllib.error.HTTPError:
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError(url, code, reason, {}, _ErrBody(body))


def _ladder_400_error(url: str, rung: str = "bogus") -> urllib.error.HTTPError:
    message = (
        f"Unexpected reasoning effort {rung}. "
        "Supported types are xhigh (default), medium, and low."
    )
    return _http_error(url, 400, "Bad Request", message)


def _non_ladder_400_error(url: str) -> urllib.error.HTTPError:
    return _http_error(url, 400, "Bad Request", "temperature must be between 0 and 2")


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


# ── payload shape: unset / off / each rung, never both keys ────────────────


def test_payload_omits_chat_template_kwargs_when_kill_switched() -> None:
    """The kill-switch sentinel is the concrete "unset" case: with it,
    ``reasoning_effort_effective`` is ``None`` and the payload is
    byte-identical to the pre-#416 shape (no ``chat_template_kwargs`` key at
    all — not even an empty dict)."""
    cfg = _cfg(reasoning_effort="default")
    assert cfg.reasoning_effort_effective is None
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
    assert "chat_template_kwargs" not in payload
    # And it matches the payload built with NOTHING effort-related at all,
    # once the effort machinery is bypassed via the same kill switch.
    assert set(payload) == {"model", "messages", "temperature", "stream", "stream_options"}


def test_payload_off_carries_exactly_enable_thinking_false() -> None:
    cfg = _cfg(reasoning_effort="off")
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("rung", ["low", "medium", "high", "xhigh"])
def test_payload_rung_carries_reasoning_effort_verbatim(rung: str) -> None:
    """'high' rides verbatim — never silently upgraded to 'xhigh' (the
    module docstring's honest limit)."""
    cfg = _cfg(reasoning_effort=rung)
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
    assert payload["chat_template_kwargs"] == {"reasoning_effort": rung}


def test_payload_default_config_sends_the_seat_table_low() -> None:
    """A config with NOTHING explicitly configured is not "unset" for the
    acting cortex/worker seat — ``effort.SEAT_TABLE`` defaults it to
    "low" (c26/h17, t2; "medium" until v4, #475). This is new-since-#416
    behavior; it does not break the existing
    test_vllm_openai.py/test_headless_streaming.py pins because none of them
    assert full-payload equality."""
    cfg = _cfg()
    assert cfg.reasoning_effort_effective == "low"
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "low"}


def test_payload_never_carries_both_keys_or_preserve_thinking() -> None:
    for rung in ("off", "low", "medium", "high", "xhigh"):
        cfg = _cfg(reasoning_effort=rung)
        payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
        fragment = payload["chat_template_kwargs"]
        assert set(fragment) <= {"enable_thinking", "reasoning_effort"}
        assert not ({"enable_thinking", "reasoning_effort"} <= set(fragment))
        assert "preserve_thinking" not in fragment


# ── existing suites' pins stay green (spot-check the claim) ────────────────


def test_existing_pins_do_not_assert_full_payload_equality() -> None:
    """Direct evidence for the acceptance claim: a default-resolved config
    (the shape every existing test_vllm_openai.py/test_headless_streaming.py
    fixture uses) now carries a NEW key, and that is fine because those
    suites only ever assert individual keys (``stream``/``stream_options``),
    never the whole dict."""
    payload, streaming = VllmOpenAIEngine._build_chat_payload(_cfg(), [], [])
    assert streaming is True
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert "chat_template_kwargs" in payload  # new since #416, harmless here


# ── seat-attribute precedence (config.reasoning_effort_seat) ───────────────


def test_effort_for_falls_back_to_acting_seat_when_attribute_absent() -> None:
    cfg = _cfg()
    assert not hasattr(cfg, "reasoning_effort_seat")
    assert _effort_for(cfg) == cfg.reasoning_effort_effective == "low"  # v4 (#475)


def test_reasoning_effort_seat_attribute_wins_over_acting_effective() -> None:
    cfg = _cfg()  # acting-seat effective would be "low" (v4, #475)
    cfg.reasoning_effort_seat = "low"
    assert _effort_for(cfg) == "low"
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "low"}


def test_reasoning_effort_seat_attribute_can_select_off() -> None:
    cfg = _cfg()
    cfg.reasoning_effort_seat = "off"
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, [], [])
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_reasoning_effort_seat_attribute_dropped_by_dataclasses_replace() -> None:
    """A plain attribute (not a dataclass field) never survives
    ``dataclasses.replace`` — the copy re-resolves its own acting-seat rung,
    exactly the degrade the docstring promises."""
    cfg = _cfg()
    cfg.reasoning_effort_seat = "off"
    copy = dataclasses.replace(cfg)
    assert not hasattr(copy, "reasoning_effort_seat")
    assert _effort_for(copy) == "low"  # v4 seat default (#475)


# ── _is_ladder_400 classifier ───────────────────────────────────────────────


def test_is_ladder_400_true_for_the_real_server_shape() -> None:
    from colleague.engines.vllm_openai import _raise_legible_http_error

    exc = _ladder_400_error("http://x/v1/chat/completions")
    with pytest.raises(urllib.error.HTTPError) as folded:
        _raise_legible_http_error("http://x/v1/chat/completions", exc)
    assert _is_ladder_400(folded.value)


def test_is_ladder_400_false_for_a_non_ladder_400() -> None:
    from colleague.engines.vllm_openai import _raise_legible_http_error

    exc = _non_ladder_400_error("http://x/v1/chat/completions")
    with pytest.raises(urllib.error.HTTPError) as folded:
        _raise_legible_http_error("http://x/v1/chat/completions", exc)
    assert not _is_ladder_400(folded.value)


def test_is_ladder_400_false_for_a_404() -> None:
    err = urllib.error.HTTPError("http://x", 404, "reasoning effort not found", {}, None)
    assert not _is_ladder_400(err)


# ── full complete() dispatch: ladder-400 retry-once + warning ──────────────


@pytest.mark.parametrize("stream_env", [None, "0"])
def test_complete_retries_once_and_warns_on_ladder_400(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, stream_env: str | None
) -> None:
    """Exercises BOTH transports: default (streaming, via the SSE reader
    reaching for ``urllib.request.urlopen``) and ``COLLEAGUE_STREAM=0``
    (blocking) — the retry lives in ``complete()``, the single convergence
    point both paths funnel through."""
    if stream_env is not None:
        monkeypatch.setenv("COLLEAGUE_STREAM", stream_env)

    call_log: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        call_log.append(payload)
        if "chat_template_kwargs" in payload:
            raise _ladder_400_error(request.full_url)
        return _OkResponse(_ok_message("answered without the ladder key"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = _cfg(reasoning_effort="xhigh")
    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "answered without the ladder key"
    assert len(call_log) == 2
    assert "chat_template_kwargs" in call_log[0]
    assert "chat_template_kwargs" not in call_log[1]

    assert len(cfg.reasoning_effort_warnings) == 1
    warning = cfg.reasoning_effort_warnings[0]
    assert isinstance(warning, _LadderRetryWarning)
    assert warning.seat == "cortex"
    assert warning.effort == "xhigh"
    assert "supported types" in warning.detail.lower()

    err = capsys.readouterr().err
    assert "cortex" in err
    assert "xhigh" in err
    assert "supported types" in err.lower()


def test_complete_second_ladder_400_propagates_unguarded(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        raise _ladder_400_error(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = _cfg(reasoning_effort="xhigh")
    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError):
        complete([{"role": "user", "content": "hi"}])

    assert len(cfg.reasoning_effort_warnings) == 1  # exactly ONE retry, never a loop


def test_non_ladder_400_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    call_log: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        call_log.append(json.loads(request.data.decode("utf-8")))
        raise _non_ladder_400_error(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = _cfg(reasoning_effort="xhigh")
    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError) as exc:
        complete([{"role": "user", "content": "hi"}])

    assert "temperature" in str(exc.value)
    assert len(call_log) == 1  # never retried
    assert getattr(cfg, "reasoning_effort_warnings", ()) == ()


def test_complete_ladder_400_without_chat_template_kwargs_never_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 naming "reasoning effort" on a request that never carried the
    key at all (kill-switched) is left to propagate — the guard is
    ``"chat_template_kwargs" in payload``, not just the classifier."""

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        raise _ladder_400_error(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = _cfg(reasoning_effort="default")  # kill switch: no chat_template_kwargs sent
    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    with pytest.raises(urllib.error.HTTPError):
        complete([{"role": "user", "content": "hi"}])
    assert getattr(cfg, "reasoning_effort_warnings", ()) == ()


# ── 404 -> 400 -> 200: exactly one refresh + one ladder retry (c33) ────────


def test_complete_404_then_ladder_400_then_200_two_retries_two_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from colleague.config import EngineConfig as _EngineConfig
    from colleague.lobes import LobesRoles, ModelRefreshWarning, RoleInfo

    stale_id = "stale/pinned-model-id"
    fresh_id = "fresh/currently-served-model-id"

    call_log: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        call_log.append(payload)
        if payload["model"] == stale_id:
            raise _model_not_found_error(request.full_url, stale_id)
        if "chat_template_kwargs" in payload:
            raise _ladder_400_error(request.full_url)
        return _OkResponse(_ok_message("refreshed and de-laddered"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from colleague import lobes as lobes_mod

    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(
            cortex=RoleInfo(
                model=fresh_id,
                endpoint="http://role.example:8001",
                path="/v1/chat/completions",
                context=65536,
                ready=True,
                responsibilities=(),
                forbidden_responsibilities=(),
            ),
            senses=None,
        ),
    )

    cfg = _EngineConfig.resolve(base_url="http://x/v1", model=stale_id)
    cfg = dataclasses.replace(
        cfg, lobes_gateway_url="http://gateway.example", reasoning_effort="xhigh"
    )

    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "refreshed and de-laddered"
    assert [c["model"] for c in call_log] == [stale_id, fresh_id, fresh_id]
    assert "chat_template_kwargs" in call_log[1]
    assert "chat_template_kwargs" not in call_log[2]

    # The refreshed id persists (Qodo review precedent, PR #381).
    assert cfg.model == fresh_id

    assert len(cfg.model_refresh_warnings) == 1
    assert isinstance(cfg.model_refresh_warnings[0], ModelRefreshWarning)
    assert cfg.model_refresh_warnings[0].refreshed_id == fresh_id

    assert len(cfg.reasoning_effort_warnings) == 1
    assert cfg.reasoning_effort_warnings[0].seat == "cortex"


# ── a server that silently ignores the key runs identically to today ───────


def test_mock_server_ignoring_chat_template_kwargs_runs_identically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server that just doesn't recognize ``chat_template_kwargs`` (OpenAI
    itself, or a non-vLLM OpenAI-compatible endpoint) answers 200 exactly as
    if the key were never sent — no new error path, no retry, no warning."""

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        assert "chat_template_kwargs" in payload  # the key WAS sent
        return _OkResponse(_ok_message("ignored the key, answered normally"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    cfg = _cfg(reasoning_effort="medium")
    complete = VllmOpenAIEngine()._make_complete(cfg, tools=[])
    resp = complete([{"role": "user", "content": "hi"}])

    assert resp.content == "ignored the key, answered normally"
    assert getattr(cfg, "reasoning_effort_warnings", ()) == ()
    assert cfg.model_refresh_warnings == ()

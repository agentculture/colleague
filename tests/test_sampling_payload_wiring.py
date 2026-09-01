"""#479 t5: the resolved sampling profile reaches the wire — one write site.

This is the task where the arc reaches the wire. ``colleague.sampling`` (t2)
holds the FIXED builtin table + the resolution ladder and
``colleague.samplingfile`` (t3) parses the tracked ``.colleague/models.json``;
neither is wired to anything. Here the adapter's SINGLE payload builder
(``VllmOpenAIEngine._build_chat_payload``, the non-associate branch) consumes
both and merges the resolved keys into the outgoing body.

What this file pins, criterion by criterion:

1. ONE write site — the sampling key names are written into a payload in
   ``colleague/engines/vllm_payload.py`` and nowhere else in ``colleague/``.
2. Only keys a resolved row explicitly sets go on the wire, minus the ones
   whose value already equals the SERVER default: the builtin Qwen thinking
   row puts ``top_k`` 20 on the wire while its ``min_p`` 0.0 and
   ``repetition_penalty`` 1.0 stay off it.
3. ``COLLEAGUE_SAMPLING=0`` is a per-PROCESS env kill switch restoring the
   pre-change payload key for key — two arms in one process differ without
   touching the shared tracked file.
4. No row matched + kill switch unset = a byte-identical outgoing body.
5. The associate branch is untouched (its own suite runs unchanged).
6. A scripted server refusal of the extension keys surfaces exactly as today —
   ONE request, no retry-without-sampling-keys path.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from colleague.config import EngineConfig
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.engines.vllm_payload import _SERVER_DEFAULT_SAMPLING, _sampling_fragment

#: The default served checkpoint — the one the builtin table holds a card for.
_QWEN = "unsloth/Qwen3.8-27B-NVFP4"
_MSGS: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_output_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """These pins assert EXACT payload dicts, so the t16 window clamp (which
    would add ``max_tokens``) is kill-switched here — mirroring
    ``tests/test_vllm_thinking_effort.py``'s own fixture."""
    monkeypatch.setenv("COLLEAGUE_MAX_OUTPUT_TOKENS", "0")


def _cfg(model: str = _QWEN, **overrides: Any) -> EngineConfig:
    cfg = EngineConfig.resolve(base_url="http://host:9999/v1", model=model, discover_lobes=False)
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


def _build(cfg: EngineConfig, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload, _streaming = VllmOpenAIEngine._build_chat_payload(cfg, _MSGS, tools or [])
    return payload


def _write_models_file(root: Path, data: object) -> None:
    (root / ".colleague").mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    (root / ".colleague" / "models.json").write_text(text, encoding="utf-8")


# ── criterion 1: exactly one write site ────────────────────────────────────


def test_sampling_keys_are_written_in_exactly_one_module() -> None:
    """The vLLM extension key names appear as payload keys in ONE module.

    ``min_p``/``repetition_penalty`` are the unambiguous probes (``top_k`` is
    also an eidetic recall argument in ``tools.py``/``tool_schemas.py``, and
    ``top_p`` belongs to the separate associate lane). No seat builder, loop
    module or CLI command may name them.
    """
    owners = set()
    for path in sorted((_REPO_ROOT / "colleague").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if '"min_p"' in text or '"repetition_penalty"' in text:
            owners.add(path.relative_to(_REPO_ROOT).as_posix())
    assert owners == {"colleague/engines/vllm_payload.py"}


def test_the_fragment_has_a_single_call_site_in_the_payload_builder() -> None:
    """``_sampling_fragment`` is called from exactly one place: the adapter's
    payload builder. One definition + one call = one write site."""
    call_sites = []
    for path in sorted((_REPO_ROOT / "colleague").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "_sampling_fragment(" in line and not line.strip().startswith("def "):
                call_sites.append(path.relative_to(_REPO_ROOT).as_posix())
    assert call_sites == ["colleague/engines/vllm_openai.py"]


# ── criterion 2: only what a row sets, minus the server defaults ────────────


def test_builtin_thinking_row_reaches_the_wire_without_the_server_defaults() -> None:
    cfg = _cfg(reasoning_effort="low")
    payload = _build(cfg)
    assert payload["temperature"] == 1.0  # the row REPLACES config.temperature (0.0)
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 20  # the one vLLM extension the table needs
    # Card values that already equal the server default never go on the wire.
    assert "min_p" not in payload
    assert "repetition_penalty" not in payload
    assert "presence_penalty" not in payload  # 0.0 == the server default too
    # The effort fragment still rides beside it, untouched.
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "low"}


def test_builtin_non_thinking_row_rides_the_off_rung() -> None:
    cfg = _cfg(reasoning_effort="off")
    payload = _build(cfg)
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.80
    assert payload["top_k"] == 20
    assert payload["presence_penalty"] == 1.5  # DIFFERS from the server default
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_server_default_table_is_explicit_and_covers_the_two_named_keys() -> None:
    assert _SERVER_DEFAULT_SAMPLING["min_p"] == 0.0
    assert _SERVER_DEFAULT_SAMPLING["repetition_penalty"] == 1.0
    assert "temperature" not in _SERVER_DEFAULT_SAMPLING  # always written; never filtered
    assert "top_k" not in _SERVER_DEFAULT_SAMPLING


def test_kill_switch_sentinel_rung_sends_no_sampling_keys() -> None:
    """No half -> no row -> no keys, on the very model the table claims."""
    cfg = _cfg(reasoning_effort="default")
    assert cfg.reasoning_effort_effective is None
    payload = _build(cfg)
    assert set(payload) == {"model", "messages", "temperature", "stream", "stream_options"}
    assert payload["temperature"] == cfg.temperature


# ── criterion 4: an unmatched model is byte-identical to today ──────────────


def test_unmatched_model_payload_is_byte_identical_key_for_key() -> None:
    cfg = _cfg(model="m", reasoning_effort="low")
    payload = _build(cfg)
    assert payload == {
        "model": "m",
        "messages": _MSGS,
        "temperature": cfg.temperature,
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_unmatched_model_with_tools_is_byte_identical_key_for_key() -> None:
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    cfg = _cfg(model="Qwen/Qwen3.8-4B", reasoning_effort="low")  # NOT the 27B card
    payload = _build(cfg, tools)
    assert payload == {
        "model": "Qwen/Qwen3.8-4B",
        "messages": _MSGS,
        "temperature": cfg.temperature,
        "tools": tools,
        "tool_choice": "auto",
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_unmatched_model_wire_body_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The dumped OUTGOING body (COLLEAGUE_DUMP_REQUEST, the existing capture
    hook) — not just the dict — matches the pre-change shape."""
    monkeypatch.setenv("COLLEAGUE_DUMP_REQUEST", "1")
    cfg = _cfg(model="m", reasoning_effort="low")
    _build(cfg)
    dumped = capsys.readouterr().err.split("outgoing request payload:\n", 1)[1]
    assert json.loads(dumped) == {
        "model": "m",
        "messages": _MSGS,
        "temperature": cfg.temperature,
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


# ── criterion 3: COLLEAGUE_SAMPLING=0, per process, no shared file ──────────


def test_kill_switch_restores_the_pre_change_payload_key_for_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLEAGUE_SAMPLING", "0")
    cfg = _cfg(reasoning_effort="low")  # the MATCHING model
    payload = _build(cfg)
    assert payload == {
        "model": _QWEN,
        "messages": _MSGS,
        "temperature": cfg.temperature,  # 0.0 — the pre-change value
        "chat_template_kwargs": {"reasoning_effort": "low"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_kill_switch_accepts_the_usual_disabling_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("COLLEAGUE_SAMPLING", value)
    assert _sampling_fragment(_cfg(), "low") == {}


def test_two_arms_in_one_process_differ_without_touching_the_shared_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The kill switch is per PROCESS: two arms on ONE checkout differ from
    each other while the tracked ``models.json`` is only ever READ. (A file
    switch could not do this — ``models.json`` is committed and shared.)"""
    _write_models_file(tmp_path, {_QWEN: {"thinking": {"temperature": 0.5}}})
    models = tmp_path / ".colleague" / "models.json"
    before = models.read_bytes(), models.stat().st_mtime_ns
    cfg = _cfg(reasoning_effort="low", memory_root=str(tmp_path))

    monkeypatch.delenv("COLLEAGUE_SAMPLING", raising=False)
    armed = _build(cfg)
    monkeypatch.setenv("COLLEAGUE_SAMPLING", "0")
    disarmed = _build(cfg)

    assert armed["temperature"] == 0.5
    assert disarmed["temperature"] == cfg.temperature
    assert armed != disarmed
    assert (models.read_bytes(), models.stat().st_mtime_ns) == before


# ── operator rows from the tracked .colleague/models.json (claim c56) ───────


def test_operator_row_overrides_the_builtin_row(tmp_path: Path) -> None:
    """Layered AFTER the builtins, so t2's last-wins tie-break makes it win.

    The override is ROW-level, not key-level (``resolve_sampling`` returns one
    row's whole profile): an operator row that names only ``temperature`` and
    ``top_k`` therefore also drops the builtin's ``top_p``.
    """
    _write_models_file(
        tmp_path, {"Qwen/Qwen3.8-27B": {"thinking": {"temperature": 0.4, "top_k": 40}}}
    )
    payload = _build(_cfg(reasoning_effort="low", memory_root=str(tmp_path)))
    assert payload["temperature"] == 0.4
    assert payload["top_k"] == 40
    assert "top_p" not in payload


def test_operator_row_teaches_a_model_the_builtin_table_has_no_card_for(
    tmp_path: Path,
) -> None:
    _write_models_file(tmp_path, {"acme/Foo-9B": {"thinking": {"temperature": 0.3, "top_k": 5}}})
    payload = _build(_cfg(model="acme/Foo-9B", reasoning_effort="low", memory_root=str(tmp_path)))
    assert payload["temperature"] == 0.3
    assert payload["top_k"] == 5


def test_operator_non_thinking_half_rides_the_off_rung(tmp_path: Path) -> None:
    _write_models_file(tmp_path, {_QWEN: {"non_thinking": {"temperature": 0.9}}})
    payload = _build(_cfg(reasoning_effort="off", memory_root=str(tmp_path)))
    assert payload["temperature"] == 0.9
    # ... and the THINKING half still comes from the builtin row.
    thinking = _build(_cfg(reasoning_effort="low", memory_root=str(tmp_path)))
    assert thinking["temperature"] == 1.0


def test_unparseable_operator_value_is_ignored_never_raises(tmp_path: Path) -> None:
    _write_models_file(
        tmp_path, {_QWEN: {"thinking": {"temperature": "hot", "top_k": 40, "bogus": 1}}}
    )
    cfg = _cfg(reasoning_effort="low", memory_root=str(tmp_path))
    payload = _build(cfg)
    assert payload["top_k"] == 40
    assert payload["temperature"] == cfg.temperature  # the row set nothing usable here
    assert "bogus" not in payload


def test_malformed_models_file_falls_back_to_the_builtin_table(tmp_path: Path) -> None:
    _write_models_file(tmp_path, "{not json")
    payload = _build(_cfg(reasoning_effort="low", memory_root=str(tmp_path)))
    assert payload["temperature"] == 1.0
    assert payload["top_k"] == 20


def test_unknown_half_label_is_ignored(tmp_path: Path) -> None:
    _write_models_file(tmp_path, {_QWEN: {"default": {"temperature": 0.1}}})
    payload = _build(_cfg(reasoning_effort="low", memory_root=str(tmp_path)))
    assert payload["temperature"] == 1.0  # builtin, unshadowed


def test_operator_row_may_also_be_filtered_by_the_server_default_table(
    tmp_path: Path,
) -> None:
    _write_models_file(tmp_path, {_QWEN: {"thinking": {"temperature": 0.4, "min_p": 0.0}}})
    payload = _build(_cfg(reasoning_effort="low", memory_root=str(tmp_path)))
    assert "min_p" not in payload


# ── criterion 5: the associate branch is untouched ─────────────────────────


def test_associate_seat_payload_carries_no_sampling_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import associate as associate_mod
    from colleague.associate_config import AssociateConfig

    monkeypatch.setattr(associate_mod, "served_window_budget", lambda a: a.context_budget)
    base = _cfg()
    assoc = AssociateConfig(
        model="nvidia/Nemotron",
        base_url=base.base_url,
        api_key=base.api_key,
        context_budget=100_000,
        wire_model="associate",
    )
    seat = associate_mod.associate_engine_config(dataclasses.replace(base, associate=assoc))
    payload = _build(seat)
    assert payload["temperature"] == 0.6  # the associate profile, not the table
    assert payload["top_p"] == 0.95  # written by _apply_associate_profile
    assert "top_k" not in payload
    assert "min_p" not in payload
    assert payload["chat_template_kwargs"] == {"enable_thinking": True}


# ── criterion 6: a scripted refusal, and no retry-without-sampling path ─────


class _ErrBody:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class _OkResponse:
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


def _sampling_400(url: str) -> urllib.error.HTTPError:
    body = json.dumps({"error": {"message": "top_k is not supported by this server"}}).encode(
        "utf-8"
    )
    return urllib.error.HTTPError(url, 400, "Bad Request", {}, _ErrBody(body))


def test_a_server_that_ignores_the_keys_completes_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        sent.append(json.loads(request.data.decode("utf-8")))
        return _OkResponse({"choices": [{"message": {"content": "done"}}], "usage": {}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = _cfg(reasoning_effort="low")
    resp = VllmOpenAIEngine()._make_complete(cfg, tools=[])(_MSGS)
    assert resp.content == "done"
    assert sent[0]["top_k"] == 20
    assert sent[0]["temperature"] == 1.0


def test_scripted_refusal_surfaces_once_with_no_key_stripping_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400 naming a sampling key surfaces EXACTLY as today (c34): one
    request, the error propagates, and no second body without the keys is
    ever sent. Exposure is already bounded — an unmatched model sends
    nothing — so there is no retry path to add."""
    sent: list[dict] = []

    def fake_urlopen(request: object, timeout: float = 0):  # noqa: ANN001
        sent.append(json.loads(request.data.decode("utf-8")))
        raise _sampling_400(request.full_url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = _cfg(reasoning_effort="low")
    with pytest.raises(urllib.error.HTTPError):
        VllmOpenAIEngine()._make_complete(cfg, tools=[])(_MSGS)

    assert len(sent) == 1
    assert sent[0]["top_k"] == 20
    assert all("top_k" in body for body in sent)  # no key-stripped retry, ever
    assert getattr(cfg, "reasoning_effort_warnings", ()) == ()


def test_no_retry_path_mentions_sampling_in_the_adapter() -> None:
    """Structural companion to the behavioral pin above: the ladder-400 retry
    is the ONLY retry in the driver, and it drops ``chat_template_kwargs``,
    never a sampling key."""
    text = (_REPO_ROOT / "colleague" / "engines" / "vllm_openai.py").read_text(encoding="utf-8")
    assert "_is_ladder_400" in text
    assert 'pop("top_k"' not in text
    assert "_sampling_retry" not in text

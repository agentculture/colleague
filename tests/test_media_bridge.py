"""Media-comprehension bridge (t8, spec c24/h18 — operator decision 2026-07-02).

When the MAIN model is text-only (declared by the operator via the deepthink
section's ``multimodal`` flag on the SECOND model) and the task carries media,
the runtime escalates a media-bearing digest tools-off to the multimodal
second model and folds the returned description back as ONE advisory message —
so attachments are useful on today's rig (27B main + Gemma vision) before the
Gemma-as-main flip. Strict no-op when single-model, when nothing is attached,
or when the second model is not declared multimodal; a bridge failure degrades
(recorded on TaskResult.deepthink), never raises.
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import media
from colleague.config import EngineConfig
from colleague.contract import OK, DeepthinkCall, Task
from colleague.deepthink import DeepthinkResult, run_media_bridge
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_POINT = "media-bridge"


def _png(root: Path, name: str = "shot.png") -> str:
    path = root / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return str(path)


def _task_with_image(tmp_path: Path) -> Task:
    attachment = media.validate_attachment(_png(tmp_path))
    return Task.new(str(tmp_path), "what color is this?", attachments=[attachment])


def _finish_complete(seen: list):
    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    return complete


def _fake_bridge_run(calls: list, *, degraded: bool = False, text: str = "a solid red image"):
    def bound(question: str, context: str = "", *, point: str = "tool", media_parts=None):
        calls.append({"question": question, "point": point, "media_parts": media_parts})
        if degraded:
            return DeepthinkResult(
                text="", call=DeepthinkCall(point=point, degraded=True, duration=0.1)
            )
        return DeepthinkResult(
            text=text,
            call=DeepthinkCall(point=point, tokens=42, duration=0.1, degraded=False),
        )

    return bound


# ---------------------------------------------------------------------------
# Loop behavior
# ---------------------------------------------------------------------------


def test_bridge_fires_once_and_folds_description(tmp_path: Path) -> None:
    calls: list = []
    seen: list = []
    controls = ContextControls(deepthink_run=_fake_bridge_run(calls), media_bridge=True)
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert len(calls) == 1, "exactly one bridge escalation"
    assert calls[0]["point"] == _POINT
    assert calls[0]["media_parts"] and calls[0]["media_parts"][0]["type"] == "image_url"
    advisory = [
        m
        for m in seen[0]
        if m.get("role") == "user"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("[media bridge]")
    ]
    assert len(advisory) == 1, "exactly one advisory message"
    assert "a solid red image" in advisory[0]["content"]
    assert result.deepthink and result.deepthink[0].point == _POINT
    assert result.deepthink[0].degraded is False
    # The main model is DECLARED text-only: its wire must carry NO parts —
    # the initial message is flattened, the real parts travel only on the
    # bridge escalation (h12/h18 extended to the main wire).
    assert all(isinstance(m.get("content"), str) for m in seen[0] if "content" in m)
    assert "[image attachment]" in seen[0][1]["content"]
    # Delivery vocabulary for the bridge case: "bridged", never "delivered".
    assert result.media is not None
    assert result.media["attachments"][0]["status"] == "bridged"


def test_bridge_noop_without_multimodal_declaration(tmp_path: Path) -> None:
    calls: list = []
    seen: list = []
    controls = ContextControls(deepthink_run=_fake_bridge_run(calls), media_bridge=False)
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert not calls
    assert result.deepthink is None
    assert not [m for m in seen[0] if str(m.get("content", "")).startswith("[media bridge]")]


def test_bridge_noop_single_model(tmp_path: Path) -> None:
    seen: list = []
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3)
    assert result.status == OK
    assert result.deepthink is None


def test_bridge_noop_without_attachments(tmp_path: Path) -> None:
    calls: list = []
    seen: list = []
    controls = ContextControls(deepthink_run=_fake_bridge_run(calls), media_bridge=True)
    result = run(
        _finish_complete(seen),
        Task.new(str(tmp_path), "no media"),
        max_steps=3,
        context=controls,
    )
    assert result.status == OK
    assert not calls


def test_bridge_degrades_never_raises(tmp_path: Path) -> None:
    calls: list = []
    seen: list = []
    controls = ContextControls(
        deepthink_run=_fake_bridge_run(calls, degraded=True), media_bridge=True
    )
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert len(calls) == 1
    assert result.deepthink and result.deepthink[0].degraded is True
    assert not [
        m
        for m in seen[0]
        if isinstance(m.get("content"), str) and m["content"].startswith("[media bridge]")
    ], "a degraded bridge folds nothing into the conversation"
    # Even degraded, the declared-text-only main wire carries no parts; the
    # t9 verifier then classifies honestly (unknown here — scripted complete
    # reports no usage; dropped with real usage numbers).
    assert isinstance(seen[0][1]["content"], str)
    assert result.media is not None
    assert result.media["attachments"][0]["status"] == "unknown"


# ---------------------------------------------------------------------------
# run_media_bridge: the parts reach the multimodal wire un-flattened
# ---------------------------------------------------------------------------


class _FakeEngine:
    def __init__(self, sink: list, fail: bool = False):
        self._sink = sink
        self._fail = fail

    def make_count_tokens(self, config):
        from colleague.context import count_tokens_chars

        return count_tokens_chars

    def make_complete(self, config, tools=None):
        assert tools == [], "the bridge is tools-off always"

        def complete(messages: list[dict]) -> ModelResponse:
            if self._fail:
                raise RuntimeError("endpoint unreachable")
            self._sink.append(messages)
            return ModelResponse(content="described")

        return complete


def _dual_config() -> EngineConfig:
    from colleague.config import DeepthinkConfig

    cfg = EngineConfig.resolve()
    cfg.deepthink = DeepthinkConfig(
        model="second/model",
        base_url="http://localhost:9",
        api_key="x",
        context_budget=4000,
        multimodal=True,
    )
    return cfg


def test_run_media_bridge_sends_parts_unflattened() -> None:
    sink: list = []
    parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]
    result = run_media_bridge(
        "describe the media",
        parts,
        config=_dual_config(),
        engine_name="mock",
        engine_loader=lambda name: _FakeEngine(sink),
    )
    assert result.call.degraded is False
    assert result.text == "described"
    sent = sink[0]
    last = sent[-1]
    assert isinstance(last["content"], list)
    assert any(p.get("type") == "image_url" for p in last["content"])


def test_run_media_bridge_unreachable_degrades() -> None:
    parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]
    result = run_media_bridge(
        "describe",
        parts,
        config=_dual_config(),
        engine_name="mock",
        engine_loader=lambda name: _FakeEngine([], fail=True),
    )
    assert result.call.degraded is True
    assert result.text == ""


# ---------------------------------------------------------------------------
# Config resolution: the multimodal declaration
# ---------------------------------------------------------------------------


def test_multimodal_resolves_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "second/model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MULTIMODAL", "1")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.multimodal is True


def test_multimodal_resolves_from_config_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("COLLEAGUE_DEEPTHINK_MODEL", raising=False)
    monkeypatch.delenv("COLLEAGUE_DEEPTHINK_MULTIMODAL", raising=False)
    (tmp_path / ".colleague").mkdir()
    (tmp_path / ".colleague" / "config.json").write_text(
        json.dumps({"deepthink": {"model": "second/model", "multimodal": True}})
    )
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.multimodal is True


def test_multimodal_defaults_false(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "second/model")
    monkeypatch.delenv("COLLEAGUE_DEEPTHINK_MULTIMODAL", raising=False)
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    assert cfg.deepthink is not None
    assert cfg.deepthink.multimodal is False


def test_controls_from_config_arms_media_bridge(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MODEL", "second/model")
    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MULTIMODAL", "true")
    cfg = EngineConfig.resolve(repo_path=tmp_path)
    controls = ContextControls.from_config(cfg)
    assert controls.media_bridge is True

    monkeypatch.setenv("COLLEAGUE_DEEPTHINK_MULTIMODAL", "")
    cfg2 = EngineConfig.resolve(repo_path=tmp_path)
    controls2 = ContextControls.from_config(cfg2)
    assert controls2.media_bridge is False

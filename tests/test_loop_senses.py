"""Cortex/senses loop integration (cortex/senses arc, t6).

Two runtime seams wired into ``colleague/loop.py`` for the cortex/senses split:

* **Context-packet injection** — a task carrying a ``context_packet`` (the
  session/resident ran senses intake) gets the operator's VERBATIM original as
  cortex's first message (never replaced) plus ONE advisory ``[senses]``
  companion message; the packet is recorded on ``TaskResult.senses``.
* **Senses media bridge** — a declared multimodal senses config is PREFERRED
  over the deepthink bridge: the real media parts ride ONE tools-off completion
  to the senses endpoint (the cortex wire is flattened), the record lands on
  ``TaskResult.senses`` (never ``deepthink``), and a degraded bridge records
  honestly with no deepthink fallback.

The deepthink-only path stays byte-identical (``tests/test_media_bridge.py``
passes unmodified); this file pins the NEW senses behavior + the all-engines
mock degrade.
"""

from __future__ import annotations

from pathlib import Path

from colleague import media
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, ContextPacket, DeepthinkCall, SensesRecord, Task
from colleague.deepthink import DeepthinkResult
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_POINT = "media-bridge"

_VERBATIM = "Fix the \tflaky   test in\n\n  parser.py 🐛  \n"


def _png(root: Path, name: str = "shot.png") -> str:
    path = root / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return str(path)


def _packet(original: str = _VERBATIM) -> ContextPacket:
    return ContextPacket(
        original=original,
        interpretation="repair the intermittently-failing parser test",
        confidence=0.8,
        task_type="bugfix",
        omissions=["which test", "expected behavior"],
    )


def _finish_complete(seen: list):
    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    return complete


def _fake_senses_run(calls: list, *, degraded: bool = False, text: str = "a solid red image"):
    def bound(question: str, media_parts):
        calls.append({"question": question, "media_parts": media_parts})
        if degraded:
            return None, SensesRecord(point=_POINT, latency=0.1, tokens=None, degraded=True)
        return text, SensesRecord(point=_POINT, latency=0.1, tokens=42, degraded=False)

    return bound


def _fake_deepthink_run(calls: list, *, text: str = "deepthink saw it"):
    def bound(question: str, context: str = "", *, point: str = "tool", media_parts=None):
        calls.append({"question": question, "point": point, "media_parts": media_parts})
        return DeepthinkResult(
            text=text, call=DeepthinkCall(point=point, tokens=7, duration=0.1, degraded=False)
        )

    return bound


# ---------------------------------------------------------------------------
# Context-packet injection (acceptance 1)
# ---------------------------------------------------------------------------


def test_packet_original_is_verbatim_and_never_replaced(tmp_path: Path) -> None:
    seen: list = []
    task = Task.new(str(tmp_path), _VERBATIM, context_packet=_packet())
    result = run(_finish_complete(seen), task, max_steps=3)
    assert result.status == OK
    first = seen[0]
    # Cortex's first user message IS the operator's verbatim original — the
    # packet's interpretation never replaces it.
    user_msgs = [m for m in first if m.get("role") == "user"]
    assert user_msgs[0]["content"] == _VERBATIM
    # Exactly one advisory [senses] companion message, carrying the interpretation.
    advisory = [
        m
        for m in first
        if m.get("role") == "user"
        and isinstance(m.get("content"), str)
        and m["content"].startswith("[senses]")
    ]
    assert len(advisory) == 1
    assert "repair the intermittently-failing parser test" in advisory[0]["content"]
    # The advisory is a DIFFERENT message from the original — the original stands.
    assert advisory[0]["content"] != _VERBATIM


def test_packet_recorded_on_taskresult_senses(tmp_path: Path) -> None:
    seen: list = []
    task = Task.new(str(tmp_path), _VERBATIM, context_packet=_packet())
    result = run(_finish_complete(seen), task, max_steps=3)
    assert result.senses is not None
    assert result.senses.mode == "split"
    assert result.senses.packet is not None
    # The packet's original round-trips verbatim onto the artifact block.
    assert result.senses.packet.original == _VERBATIM
    assert result.senses.records == []  # no invocation record from injection alone


def test_no_packet_is_byte_identical_senses_none(tmp_path: Path) -> None:
    seen: list = []
    result = run(_finish_complete(seen), Task.new(str(tmp_path), "plain task"), max_steps=3)
    assert result.status == OK
    assert result.senses is None  # key omitted → artifact byte-identical
    assert not [m for m in seen[0] if str(m.get("content", "")).startswith("[senses]")]


# ---------------------------------------------------------------------------
# Senses media bridge — preferred, recorded under TaskResult.senses (acceptance 3)
# ---------------------------------------------------------------------------


def _task_with_image(tmp_path: Path) -> Task:
    attachment = media.validate_attachment(_png(tmp_path))
    return Task.new(str(tmp_path), "what color is this?", attachments=[attachment])


def test_senses_bridge_fires_and_records_under_senses_not_deepthink(tmp_path: Path) -> None:
    scalls: list = []
    seen: list = []
    controls = ContextControls(senses_run=_fake_senses_run(scalls), senses_media_bridge=True)
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert len(scalls) == 1
    assert scalls[0]["media_parts"] and scalls[0]["media_parts"][0]["type"] == "image_url"
    # Recorded under senses, NOT deepthink.
    assert result.deepthink is None
    assert result.senses is not None and len(result.senses.records) == 1
    assert result.senses.records[0].point == _POINT
    assert result.senses.records[0].degraded is False
    # One advisory fold, and the cortex wire is flattened (no parts).
    advisory = [
        m
        for m in seen[0]
        if str(m.get("content", "")).startswith("[media bridge] A multimodal senses model")
    ]
    assert len(advisory) == 1 and "a solid red image" in advisory[0]["content"]
    assert all(isinstance(m.get("content"), str) for m in seen[0] if "content" in m)
    assert result.media is not None and result.media["attachments"][0]["status"] == "bridged"


def test_senses_bridge_preferred_over_deepthink_when_both_armed(tmp_path: Path) -> None:
    scalls: list = []
    dcalls: list = []
    seen: list = []
    controls = ContextControls(
        senses_run=_fake_senses_run(scalls),
        senses_media_bridge=True,
        deepthink_run=_fake_deepthink_run(dcalls),
        media_bridge=True,
    )
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert len(scalls) == 1, "senses ran"
    assert not dcalls, "deepthink bridge never ran — senses is preferred"
    assert result.deepthink is None
    assert result.senses is not None and result.senses.records[0].point == _POINT


def test_senses_bridge_degrades_no_deepthink_fallback(tmp_path: Path) -> None:
    scalls: list = []
    dcalls: list = []
    seen: list = []
    controls = ContextControls(
        senses_run=_fake_senses_run(scalls, degraded=True),
        senses_media_bridge=True,
        deepthink_run=_fake_deepthink_run(dcalls),
        media_bridge=True,
    )
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert len(scalls) == 1
    assert not dcalls, "a degraded senses bridge does NOT fall back to deepthink"
    # Degraded record on senses; nothing folded. The cortex wire was flattened
    # (parts → placeholders), so t9 honestly classifies the attachment as NOT
    # bridged — "unknown" (the mock/fake reports no usage), never "bridged".
    assert result.senses is not None and result.senses.records[0].degraded is True
    assert not [m for m in seen[0] if str(m.get("content", "")).startswith("[media bridge]")]
    assert result.media is not None and result.media["attachments"][0]["status"] != "bridged"


def test_senses_bridge_noop_without_multimodal_declaration(tmp_path: Path) -> None:
    scalls: list = []
    seen: list = []
    controls = ContextControls(senses_run=_fake_senses_run(scalls), senses_media_bridge=False)
    result = run(_finish_complete(seen), _task_with_image(tmp_path), max_steps=3, context=controls)
    assert result.status == OK
    assert not scalls
    assert result.senses is None


def test_senses_bridge_noop_without_attachments(tmp_path: Path) -> None:
    scalls: list = []
    seen: list = []
    controls = ContextControls(senses_run=_fake_senses_run(scalls), senses_media_bridge=True)
    result = run(
        _finish_complete(seen), Task.new(str(tmp_path), "no media"), max_steps=3, context=controls
    )
    assert result.status == OK
    assert not scalls
    assert result.senses is None


def test_packet_and_bridge_compose_on_one_senses_block(tmp_path: Path) -> None:
    scalls: list = []
    seen: list = []
    attachment = media.validate_attachment(_png(tmp_path))
    task = Task.new(str(tmp_path), _VERBATIM, attachments=[attachment], context_packet=_packet())
    controls = ContextControls(senses_run=_fake_senses_run(scalls), senses_media_bridge=True)
    result = run(_finish_complete(seen), task, max_steps=3, context=controls)
    assert result.status == OK
    # One block carrying BOTH the packet (from injection) and the bridge record.
    assert result.senses is not None
    assert result.senses.packet is not None and result.senses.packet.original == _VERBATIM
    assert len(result.senses.records) == 1 and result.senses.records[0].point == _POINT


# ---------------------------------------------------------------------------
# All-engines: the mock records a degraded senses no-op (make_senses_run binding)
# ---------------------------------------------------------------------------


def test_make_senses_run_degrades_on_mock() -> None:
    from colleague.senses import make_senses_run

    config = EngineConfig(
        senses=SensesConfig(
            model="gemma", base_url="http://x", api_key="k", context_budget=24000, multimodal=True
        )
    )
    run_fn = make_senses_run(config, "mock")
    assert run_fn is not None
    text, record = run_fn(
        "describe", [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]
    )
    # Mock make_complete raises → degrade-never-raise → a recorded no-op.
    assert text is None
    assert record.degraded is True and record.point == _POINT and record.tokens is None


def test_make_senses_run_none_without_senses_config() -> None:
    from colleague.senses import make_senses_run

    assert make_senses_run(EngineConfig(), "mock") is None

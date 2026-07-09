"""Cortex/senses session split-mode wiring (cortex/senses arc, t8).

With a senses model resolved, a free-text `colleague session` work line runs
senses INTAKE first (perceives the request → a ContextPacket on the task, so the
loop records mode=split), and the completed work item's DISPLAY summary is shaped
by senses SPEAK-BACK while the artifact keeps the raw cortex summary. Intake +
speak-back timings fold onto ``TaskResult.senses.records``. ``--cortex-only``
bypasses the front door for one run (artifact records mode=cortex-only);
``--debug-senses`` echoes the packet to stderr; a degraded intake falls through
to the raw request and the run never fails. With no senses model resolved the
session is byte-identical.

Driven the established way: a scripted ``run`` over a recording fake ``work_fn``
(mirrors ``tests/test_session_attach.py``), with ``run_senses_intake`` /
``run_senses_speakback`` monkeypatched for determinism (the mock engine cannot
produce a real packet).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import SensesSessionOptions, SessionIO, _Session
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, ContextPacket, SensesBlock, SensesRecord, TaskResult


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _senses_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _session(tmp_path: Path, result: TaskResult, *, config: EngineConfig, **over):
    out, err = _CollectingOut(), _CollectingOut()

    def _fake_work(**kwargs: object):
        # Faithfully stand in for execute_work: the loop's t6 packet injection sets
        # result.senses = SensesBlock(mode=split, packet=task.context_packet) when a
        # packet rides the task. Mirror that here so the session-side finalize folds
        # its records onto the loop-created block (as it does in a real run).
        task = kwargs.get("task")
        packet = getattr(task, "context_packet", None) if task is not None else None
        if packet is not None and result.senses is None:
            result.senses = SensesBlock(mode="split", packet=packet, records=[])
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    senses_options = SensesSessionOptions(
        cortex_only=bool(over.pop("cortex_only", False)),
        debug_senses=bool(over.pop("debug_senses", False)),
    )
    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config,
        json_mode=False,
        view="markdown",
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=senses_options,
        **over,
    )
    return sess, out, err


def _patch_senses(monkeypatch, *, packet, intake_degraded=False, shaped="shaped reply ✨"):
    intake_rec = SensesRecord(
        point="senses-intake",
        latency=0.1,
        tokens=None if intake_degraded else 10,
        degraded=intake_degraded,
    )

    def _intake(text, senses_config, engine, **kw):
        return (None if intake_degraded else packet), intake_rec

    def _speak(summary, senses_config, engine, **kw):
        return shaped, SensesRecord(point="senses-speakback", latency=0.1, tokens=5, degraded=False)

    monkeypatch.setattr(session_mod, "run_senses_intake", _intake)
    monkeypatch.setattr(session_mod, "run_senses_speakback", _speak)
    return intake_rec


# ---------------------------------------------------------------------------
# Acceptance 1 — split: mode + packet + timings; shaped display, raw artifact
# ---------------------------------------------------------------------------


def test_split_run_records_mode_packet_and_timings(tmp_path: Path, monkeypatch) -> None:
    packet = ContextPacket(
        original="fix the flaky parser test",
        interpretation="repair the intermittently failing parser test",
        confidence=0.9,
        task_type="bugfix",
    )
    _patch_senses(monkeypatch, packet=packet)
    result = TaskResult(task_id="t", status=OK, summary="RAW cortex summary")
    sess, out, _err = _session(tmp_path, result, config=_senses_config())
    sess.run(iter(["fix the flaky parser test"]))

    # mode=split + packet recorded on the artifact object the session mutated.
    assert result.senses is not None
    assert result.senses.mode == "split"
    assert result.senses.packet is not None
    assert result.senses.packet.original == "fix the flaky parser test"
    # front-door route decision leads (talking-to-one-teammate, h5), then intake
    # FIRST of the senses-model calls, speak-back LAST.
    points = [r.point for r in result.senses.records]
    assert points == ["senses-frontdoor:cortex", "senses-intake", "senses-speakback"]
    # A visible senses: line was logged.
    assert "senses:" in out.text()


def test_split_display_is_shaped_but_artifact_summary_stays_raw(
    tmp_path: Path, monkeypatch
) -> None:
    packet = ContextPacket(original="q", interpretation="i", task_type="feature")
    _patch_senses(monkeypatch, packet=packet, shaped="Here's what I did, in plain words.")
    result = TaskResult(task_id="t", status=OK, summary="RAW cortex summary")
    sess, out, _err = _session(tmp_path, result, config=_senses_config())
    sess.run(iter(["add a feature"]))

    # The DISPLAY is the shaped speak-back; the artifact summary is the RAW one.
    assert "Here's what I did, in plain words." in out.text()
    assert result.summary == "RAW cortex summary"  # never mutated


# ---------------------------------------------------------------------------
# Acceptance 2 — --cortex-only + byte-identical without senses
# ---------------------------------------------------------------------------


def test_cortex_only_records_mode_and_skips_intake(tmp_path: Path, monkeypatch) -> None:
    called = {"intake": False}

    def _boom(*a, **k):
        called["intake"] = True
        raise AssertionError("intake must not run under --cortex-only")

    monkeypatch.setattr(session_mod, "run_senses_intake", _boom)
    result = TaskResult(task_id="t", status=OK, summary="raw")
    sess, out, _err = _session(tmp_path, result, config=_senses_config(), cortex_only=True)
    sess.run(iter(["do the thing"]))

    assert called["intake"] is False
    assert result.senses is not None and result.senses.mode == "cortex-only"
    assert result.senses.packet is None and result.senses.records == []


def test_no_senses_config_is_byte_identical(tmp_path: Path, monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError("senses must not run without a senses model")

    monkeypatch.setattr(session_mod, "run_senses_intake", _boom)
    result = TaskResult(task_id="t", status=OK, summary="raw")
    plain = EngineConfig.resolve(model="cortex-model")  # no senses
    sess, out, _err = _session(tmp_path, result, config=plain)
    sess.run(iter(["do the thing"]))

    assert result.senses is None  # key omitted → byte-identical artifact
    assert "senses:" not in out.text()


# ---------------------------------------------------------------------------
# Acceptance 3 — --debug-senses + degraded intake never fails the run
# ---------------------------------------------------------------------------


def test_debug_senses_prints_packet_to_stderr(tmp_path: Path, monkeypatch) -> None:
    packet = ContextPacket(original="q", interpretation="i", task_type="docs")
    _patch_senses(monkeypatch, packet=packet)
    result = TaskResult(task_id="t", status=OK, summary="raw")
    sess, _out, err = _session(tmp_path, result, config=_senses_config(), debug_senses=True)
    sess.run(iter(["write the docs"]))

    assert "[debug-senses]" in err.text()
    assert "docs" in err.text()  # the packet's task_type is echoed


def test_degraded_intake_falls_through_to_raw_and_never_fails(tmp_path: Path, monkeypatch) -> None:
    _patch_senses(monkeypatch, packet=None, intake_degraded=True)
    result = TaskResult(task_id="t", status=OK, summary="RAW cortex summary")
    sess, out, _err = _session(tmp_path, result, config=_senses_config())
    sess.run(iter(["fix the bug"]))

    # A degraded intake logs a visible notice and proceeds — no packet attached,
    # the run still completes (mode split, the degraded intake record folded).
    assert "senses: intake degraded" in out.text()
    assert result.senses is not None and result.senses.mode == "split"
    assert result.senses.packet is None
    assert any(r.point == "senses-intake" and r.degraded for r in result.senses.records)


def test_template_selection_does_not_run_intake(tmp_path: Path, monkeypatch) -> None:
    # A non-free-text pick (bare number / template name) is never intake'd (q1).
    def _boom(*a, **k):
        raise AssertionError("intake must not run for a template/number selection")

    monkeypatch.setattr(session_mod, "run_senses_intake", _boom)
    result = TaskResult(task_id="t", status=OK, summary="raw")
    sess, _out, _err = _session(tmp_path, result, config=_senses_config())
    # "42" is a bare number → a palette selection, not free text (no palette here
    # → _resolve_selection surfaces a clean error, but intake must never fire).
    sess.run(iter(["42"]))
    # No assertion needed beyond _boom not firing — reaching here means it didn't.


@pytest.mark.parametrize("cortex_only", [True, False])
def test_run_never_raises_under_either_mode(tmp_path: Path, monkeypatch, cortex_only) -> None:
    packet = ContextPacket(original="q", interpretation="i", task_type="q")
    _patch_senses(monkeypatch, packet=packet)
    result = TaskResult(task_id="t", status=OK, summary="raw")
    sess, _out, _err = _session(tmp_path, result, config=_senses_config(), cortex_only=cortex_only)
    rc = sess.run(iter(["a free text request"]))
    assert rc == 0

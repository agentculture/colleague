"""Cortex/senses measurement livecheck (cortex/senses arc, t13).

Covers, with NO network / live rig required:

- ``classify_cortex_senses_check``: grades from artifact EVIDENCE — PASS on a
  split artifact recording mode=split + the verbatim original; the detail emits
  per-mode wall-clock + senses runtime side by side; NEVER a quality score. A
  missing block or a dropped verbatim original FAILS.
- ``probe_lobes_stack``: (True, None) only when both cortex + senses resolve AND
  report ready; not-configured / unreachable / not-both-ready → (False, reason).
- ``run_cortex_senses_check`` degrades to "skipped" (never raises, never
  fabricates a pass) when the endpoint is unreachable or the rebalanced stack is
  not serving.
"""

from __future__ import annotations

from types import SimpleNamespace

from colleague import livecheck
from colleague.contract import ContextPacket
from colleague.livecheck import (
    ProofResult,
    classify_cortex_senses_check,
    probe_lobes_stack,
    run_cortex_senses_check,
)

_INSTR = "List the Python files at the top level of this repo and say how many there are."


def _split_artifact(*, original=_INSTR, mode="split", duration=4.5, records=None):
    return {
        "stats": {"duration_seconds": duration},
        "senses": {
            "mode": mode,
            "packet": {"original": original},
            "records": (
                records
                if records is not None
                else [
                    {"point": "senses-intake", "latency": 0.20, "tokens": 12, "degraded": False},
                    {"point": "senses-speakback", "latency": 0.10, "tokens": 6, "degraded": False},
                ]
            ),
        },
    }


# ---------------------------------------------------------------------------
# classify — runtime facts only, never a quality score
# ---------------------------------------------------------------------------


class TestClassify:
    def test_pass_emits_both_wall_clocks_and_senses_runtime(self) -> None:
        cortex = {"stats": {"duration_seconds": 3.0}}
        status, detail = classify_cortex_senses_check(cortex, _split_artifact(), _INSTR)
        assert status == "passed"
        # per-mode wall-clock side by side
        assert "3.0" in detail and "4.5" in detail
        # senses runtime (each record's point=latency)
        assert "senses-intake" in detail and "senses-speakback" in detail
        # NO quality score anywhere — the two summaries are never compared.
        assert "better" not in detail.lower() and "quality" not in detail.lower()

    def test_pass_emits_each_senses_record_tokens_alongside_latency(self) -> None:
        """Qodo #3 (cortex/senses PR #281): the measurement story is incomplete
        without token cost alongside latency — the detail must carry both, per
        record, e.g. ``senses-intake=0.2s/12tok``."""
        status, detail = classify_cortex_senses_check(
            {"stats": {"duration_seconds": 3.0}}, _split_artifact(), _INSTR
        )
        assert status == "passed"
        assert "senses-intake=0.2s/12tok" in detail
        assert "senses-speakback=0.1s/6tok" in detail

    def test_degraded_record_tokens_render_as_unknown_not_zero(self) -> None:
        """A degraded record's ``tokens`` is ``None`` (the call never reached the
        wire) — it must render as an honest ``?tok``, never a fabricated
        ``0tok`` (which would misleadingly imply a free call)."""
        art = _split_artifact(
            records=[
                {"point": "senses-intake", "latency": 0.05, "tokens": None, "degraded": True},
            ]
        )
        status, detail = classify_cortex_senses_check({}, art, _INSTR)
        assert status == "passed"
        assert "senses-intake=0.05s/?tok" in detail
        assert "0tok" not in detail

    def test_fail_when_split_missing_senses_block(self) -> None:
        status, detail = classify_cortex_senses_check(
            {}, {"stats": {"duration_seconds": 1.0}}, _INSTR
        )
        assert status == "failed"
        assert "mode=split" in detail

    def test_fail_when_mode_is_not_split(self) -> None:
        art = _split_artifact(mode="cortex-only")
        status, _detail = classify_cortex_senses_check({}, art, _INSTR)
        assert status == "failed"

    def test_fail_when_verbatim_original_not_preserved(self) -> None:
        art = _split_artifact(original="the senses model paraphrased this")
        status, detail = classify_cortex_senses_check({}, art, _INSTR)
        assert status == "failed"
        assert "verbatim" in detail.lower()

    def test_pass_tolerates_missing_stats(self) -> None:
        # A run that reported no stats still grades on the structural facts.
        status, _detail = classify_cortex_senses_check(None, _split_artifact(), _INSTR)
        assert status == "passed"


# ---------------------------------------------------------------------------
# probe_lobes_stack — the honest gate
# ---------------------------------------------------------------------------


def _roles(*, cortex_ready=True, senses_ready=True):
    return SimpleNamespace(
        cortex=SimpleNamespace(ready=cortex_ready),
        senses=SimpleNamespace(ready=senses_ready),
    )


class TestProbeLobesStack:
    def test_not_configured_skips(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck, "resolve_lobes_gateway_url", lambda repo: None)
        serving, reason = probe_lobes_stack(".")
        assert serving is False and "not probed" in reason

    def test_unreachable_gateway_skips(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck, "resolve_lobes_gateway_url", lambda repo: "http://x:8001")
        monkeypatch.setattr(livecheck, "resolve_roles", lambda url: None)
        serving, reason = probe_lobes_stack(".")
        assert serving is False and "not up" in reason

    def test_not_both_ready_skips(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck, "resolve_lobes_gateway_url", lambda repo: "http://x:8001")
        monkeypatch.setattr(livecheck, "resolve_roles", lambda url: _roles(senses_ready=False))
        serving, reason = probe_lobes_stack(".")
        assert serving is False and "ready" in reason

    def test_both_ready_serves(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck, "resolve_lobes_gateway_url", lambda repo: "http://x:8001")
        monkeypatch.setattr(livecheck, "resolve_roles", lambda url: _roles())
        serving, reason = probe_lobes_stack(".")
        assert serving is True and reason is None


# ---------------------------------------------------------------------------
# run — degrade to skipped, never raise / fabricate
# ---------------------------------------------------------------------------


class TestRunDegrades:
    def test_unreachable_endpoint_skips(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck, "_reachable", lambda repo: (False, "connection refused"))
        result = run_cortex_senses_check(".")
        assert isinstance(result, ProofResult)
        assert result.status == "skipped" and "unreachable" in result.detail

    def test_stack_not_serving_skips(self, monkeypatch) -> None:
        monkeypatch.setattr(livecheck, "_reachable", lambda repo: (True, None))
        monkeypatch.setattr(
            livecheck, "probe_lobes_stack", lambda repo: (False, "rebalanced stack not up")
        )
        result = run_cortex_senses_check(".")
        assert result.status == "skipped" and "not up" in result.detail


class _FakeConfig:
    def __init__(self) -> None:
        self.senses = object()

    @classmethod
    def resolve(cls, **kwargs):
        return cls()


def _fake_result(*, senses_dict, summary="cortex summary"):
    """A stand-in TaskResult: ``.to_dict()`` + ``.summary`` + ``.senses``.

    When ``senses_dict`` is set the ``.senses`` object carries a ``.records``
    list (the runner folds session-side records into it before grading)."""
    art = {"stats": {"duration_seconds": 1.0}}
    senses_obj = None
    if senses_dict is not None:
        art["senses"] = senses_dict
        senses_obj = SimpleNamespace(records=list(senses_dict.get("records", [])))
    return SimpleNamespace(to_dict=lambda: art, summary=summary, senses=senses_obj)


class _FakeEngine:
    """Records nothing; returns a fixed fake result from ``work``."""

    result = None

    def work(self, task, config):
        return type(self).result


class TestRunOnServingRig:
    """The serving-rig paths the honest-SKIP / no-fabrication fixes cover
    (review findings #2 + #3) — mocked, no live rig required."""

    def _arm(self, monkeypatch):
        monkeypatch.setattr(livecheck, "_reachable", lambda repo: (True, None))
        monkeypatch.setattr(livecheck, "probe_lobes_stack", lambda repo: (True, None))
        monkeypatch.setattr(livecheck, "EngineConfig", _FakeConfig)
        monkeypatch.setattr(livecheck, "senses_engine_config", lambda c: SimpleNamespace())
        monkeypatch.setattr(livecheck, "VllmOpenAIEngine", _FakeEngine)
        monkeypatch.setattr(
            livecheck, "run_senses_speakback", lambda *a, **k: ("shaped", SimpleNamespace())
        )

    def test_intake_degrade_on_serving_rig_skips_not_fails(self, monkeypatch) -> None:
        # A serving rig whose senses intake gracefully degrades (packet=None) is
        # the designed degrade-to-raw path — SKIP, never a fabricated FAIL (#2).
        self._arm(monkeypatch)
        _FakeEngine.result = _fake_result(senses_dict=None)
        monkeypatch.setattr(
            livecheck, "run_senses_intake", lambda *a, **k: (None, SimpleNamespace(degraded=True))
        )
        result = run_cortex_senses_check(".")
        assert result.status == "skipped"
        assert "degrade" in result.detail.lower()

    def test_loop_recorded_no_block_fails_not_fabricated(self, monkeypatch) -> None:
        # Packet present but the LOOP recorded no senses block → the proof must
        # FAIL (a real regression), NOT fabricate the block and pass (#3).
        self._arm(monkeypatch)
        _FakeEngine.result = _fake_result(senses_dict=None)  # loop recorded nothing
        packet = ContextPacket(original=_INSTR, interpretation="i")
        rec = SimpleNamespace(degraded=False)
        monkeypatch.setattr(livecheck, "run_senses_intake", lambda *a, **k: (packet, rec))
        result = run_cortex_senses_check(".")
        assert result.status == "failed"  # not "passed" — no self-manufactured evidence

    def test_loop_recorded_block_passes(self, monkeypatch) -> None:
        # The healthy path: the loop recorded mode=split + the verbatim original.
        self._arm(monkeypatch)
        _FakeEngine.result = _fake_result(
            senses_dict={"mode": "split", "packet": {"original": _INSTR}, "records": []}
        )
        packet = ContextPacket(original=_INSTR, interpretation="i")
        rec = SimpleNamespace(degraded=False)
        monkeypatch.setattr(livecheck, "run_senses_intake", lambda *a, **k: (packet, rec))
        result = run_cortex_senses_check(".")
        assert result.status == "passed"

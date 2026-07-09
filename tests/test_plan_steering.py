"""#309 — plan mode is steerable mid-run through the flight lane.

Plan mode (`colleague plan run`) drives the model via ``Engine.make_complete``
OUTSIDE the bounded tool loop, so it had no flight plane and could not be steered
at all. This wires a flight plane into ``run_plan_mode`` and cooperative
injection checkpoints at the orchestrator's natural boundaries (before the spec
stage, before plan-item proposal, before each wave): a ``stop`` halts the plan
cooperatively, ``guidance`` is drained/recorded/fed and threaded into the next
stage's request. A run with no flight plane is byte-identical to a pre-#309 run.
"""

import json

from colleague import flight
from colleague.plan.frame import Claim, HonestyCondition
from colleague.plan.orchestrator import PlanRunContext, run_plan_mode
from colleague.plan.plan_stage import PlanItem

_KINDS = ("announcement", "audience", "after_state", "boundary", "success_signal", "before_state")


def _claims():
    return [Claim(id=k, kind=k, text=f"{k} text", state="proposed") for k in _KINDS]


def _honesty():
    return [
        HonestyCondition(id=f"hc-{k}", claim_id=k, text=f"hc for {k}", state="proposed")
        for k in _KINDS
    ]


class _Deps:
    """Minimal stub seams; ``decide`` confirms everything so the spec converges."""

    def __init__(self):
        self.batch_spawn_called = False
        self.propose_plan_items_called = False

    def propose_claims(self, request):
        return _claims(), _honesty()

    def decide(self, item, critique):
        return "confirm"

    def propose_plan_items(self, frame):
        self.propose_plan_items_called = True
        return [PlanItem(id="p1", summary="first", acceptance=["works"])]

    def batch_spawn(self, items):
        self.batch_spawn_called = True
        return []


def _run(deps, *, flight_session=None, repo_path=None):
    return run_plan_mode(
        "build a thing",
        propose_claims=deps.propose_claims,
        decide=deps.decide,
        propose_plan_items=deps.propose_plan_items,
        batch_spawn=deps.batch_spawn,
        engine="mock",
        model="test",
        context=PlanRunContext(repo_path=repo_path, flight=flight_session),
    )


def test_flight_none_is_byte_identical():
    """No flight plane → empty steering, and the full pipeline still runs."""
    deps = _Deps()
    result = _run(deps)
    assert result.steering == []
    assert result.converged is True
    assert deps.batch_spawn_called is True  # the wave ran


def test_flight_none_creates_no_flight_dir(tmp_path):
    """Strict no-op: a plan run with no flight plane never creates .colleague/flight/."""
    _run(_Deps(), flight_session=None, repo_path=str(tmp_path))
    assert not flight.flight_dir(tmp_path).exists()


def test_stop_before_run_halts_cooperatively(tmp_path):
    """A stop written before the run halts at the first boundary — no workforce."""
    plane = flight.arm(tmp_path, "plan1")
    flight.write_stop(tmp_path, "plan1")
    deps = _Deps()
    result = _run(deps, flight_session=plane, repo_path=str(tmp_path))
    assert deps.batch_spawn_called is False  # halted before the workforce fan-out
    assert any("stopped" in s for s in result.steering)


def test_guidance_recorded_and_drained(tmp_path):
    """Guidance written before the run is recorded on result.steering and drained
    (a second read_control returns nothing new — the cursor advanced)."""
    plane = flight.arm(tmp_path, "plan1")
    flight.append_guidance(tmp_path, "plan1", "only plan the CLI surface")
    result = _run(_Deps(), flight_session=plane, repo_path=str(tmp_path))
    assert "only plan the CLI surface" in result.steering
    # drained — no new guidance remains on a fresh read
    assert flight.arm(tmp_path, "plan1") and plane.read_control().guidance == []


def test_guidance_written_to_the_flight_feed(tmp_path):
    """Applied guidance appears on the flight feed as a tool="steering" record,
    visible to a pilot / `flight status`."""
    plane = flight.arm(tmp_path, "plan1")
    flight.append_guidance(tmp_path, "plan1", "drop the telemetry claim")
    _run(_Deps(), flight_session=plane, repo_path=str(tmp_path))
    records = [
        json.loads(line)
        for line in flight.feed_path(tmp_path, "plan1").read_text().splitlines()
        if line.strip()
    ]
    steering_records = [r for r in records if r.get("tool") == "steering"]
    assert steering_records
    assert any("drop the telemetry claim" in r.get("intent", "") for r in steering_records)


def test_guidance_before_spec_augments_the_request(tmp_path):
    """Guidance drained before the spec stage is threaded into the request the spec
    stage proposes from (so the next proposal is actually steered, not just logged)."""
    seen = {}

    class _CapturingDeps(_Deps):
        def propose_claims(self, request):
            seen["request"] = request
            return _claims(), _honesty()

    plane = flight.arm(tmp_path, "plan1")
    flight.append_guidance(tmp_path, "plan1", "narrow to the parser")
    _run(_CapturingDeps(), flight_session=plane, repo_path=str(tmp_path))
    assert "narrow to the parser" in seen["request"]
    assert "operator steering" in seen["request"]


# ── guidance is APPLIED, not just recorded (Qodo #312 "guidance ignored" fix) ─


def test_post_spec_guidance_threads_into_plan_item_proposal(tmp_path):
    """Guidance drained at checkpoint 1 (after the spec stage) is injected into the
    frame as a confirmed claim, so propose_plan_items (which reads confirmed claims)
    is actually steered by it."""
    plane = flight.arm(tmp_path, "plan1")
    seen = {}

    class _D(_Deps):
        def propose_claims(self, request):
            # operator writes guidance DURING the spec stage → checkpoint 1 drains it
            flight.append_guidance(tmp_path, "plan1", "only plan the CLI surface")
            return _claims(), _honesty()

        def propose_plan_items(self, frame):
            seen["confirmed"] = [c.text for c in frame.claims if c.state == "confirmed"]
            return super().propose_plan_items(frame)

    _run(_D(), flight_session=plane, repo_path=str(tmp_path))
    assert any("only plan the CLI surface" in t for t in seen["confirmed"])


def test_pre_wave_guidance_threads_into_workforce_children(tmp_path):
    """Guidance drained at checkpoint 2 (before a wave) is threaded into the wave's
    child instructions (build_workforce_items maps PlanItem.summary → instruction)."""
    plane = flight.arm(tmp_path, "plan1")
    captured = {}

    class _D(_Deps):
        def propose_plan_items(self, frame):
            # operator writes guidance after plan items are proposed → checkpoint 2 drains it
            flight.append_guidance(tmp_path, "plan1", "skip the telemetry item")
            return super().propose_plan_items(frame)

        def batch_spawn(self, items):
            captured["items"] = items
            return super().batch_spawn(items)

    _run(_D(), flight_session=plane, repo_path=str(tmp_path))
    instructions = " ".join(i.get("instruction", "") for i in captured.get("items", []))
    assert "skip the telemetry item" in instructions

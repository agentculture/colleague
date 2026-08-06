"""#308 — the flight feed has a liveness signal during a long completion.

Before #308 the feed only got a line on a WorkStep (a tool call), so during a
long first completion (a reasoning cortex can spend minutes there) the feed was
empty and ``colleague talk`` / senses could only answer "I don't know". This adds
a run-start marker (before the first step) and folds the #206 pre-completion
phase notice into the feed as a distinct ``heartbeat`` record — consumed by the
live lane, filtered out of the step-only ``tui replay``/``snapshot`` (a different
sink), and NEVER advancing ``step_count`` (the #206 invariant).
"""

import json

import pytest

from colleague import flight, registry
from colleague.config import EngineConfig
from colleague.contract import Task


def _records(fp):
    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


# ── flight.py markers ──────────────────────────────────────────────────────


def test_append_run_start_writes_a_typed_run_start_marker(tmp_path):
    sess = flight.arm(tmp_path, "t-rs")
    sess.append_run_start(goal="rename the widget", max_steps=40)
    (rec,) = _records(flight.feed_path(tmp_path, "t-rs"))
    assert rec["type"] == "run-start"
    assert rec["step_index"] == 0
    assert rec["goal"] == "rename the widget"
    assert rec["max_steps"] == 40
    assert "cortex started" in rec["intent"]
    assert "rename the widget" in rec["intent"]


def test_append_run_start_without_goal(tmp_path):
    sess = flight.arm(tmp_path, "t-rs2")
    sess.append_run_start(goal=None, max_steps=10)
    (rec,) = _records(flight.feed_path(tmp_path, "t-rs2"))
    assert rec["type"] == "run-start"
    assert rec["goal"] is None
    assert "cortex started" in rec["intent"]


# ── t2 (change-content-consumption-lane, c9/h9): the run-start line names the
# acting seat — "cortex" (the default, unarmed floor) or "worker" (three-tier
# armed). ──────────────────────────────────────────────────────────────────


def test_append_run_start_default_seat_is_cortex_byte_identical(tmp_path):
    """No ``seat`` argument at all -> the pre-t2 behaviour, unchanged."""
    sess = flight.arm(tmp_path, "t-rs-default")
    sess.append_run_start(goal="rename the widget", max_steps=40)
    (rec,) = _records(flight.feed_path(tmp_path, "t-rs-default"))
    assert rec["intent"].startswith("cortex started")
    assert rec.get("seat") == "cortex"


def test_append_run_start_names_the_worker_seat_when_armed(tmp_path):
    sess = flight.arm(tmp_path, "t-rs-worker")
    sess.append_run_start(goal="rename the widget", max_steps=40, seat="worker")
    (rec,) = _records(flight.feed_path(tmp_path, "t-rs-worker"))
    assert rec["type"] == "run-start"
    assert rec["seat"] == "worker"
    assert rec["intent"].startswith("worker started")
    assert "cortex started" not in rec["intent"]
    assert "rename the widget" in rec["intent"]


def test_append_run_start_explicit_cortex_seat_matches_default(tmp_path):
    """Passing ``seat="cortex"`` explicitly renders identically to omitting it —
    the unarmed floor is a value, not a special code path."""
    sess_default = flight.arm(tmp_path, "t-rs-implicit")
    sess_default.append_run_start(goal="x", max_steps=5)
    sess_explicit = flight.arm(tmp_path, "t-rs-explicit")
    sess_explicit.append_run_start(goal="x", max_steps=5, seat="cortex")
    (rec_default,) = _records(flight.feed_path(tmp_path, "t-rs-implicit"))
    (rec_explicit,) = _records(flight.feed_path(tmp_path, "t-rs-explicit"))
    assert rec_default["intent"] == rec_explicit["intent"]
    assert rec_default["seat"] == rec_explicit["seat"] == "cortex"


def test_append_heartbeat_writes_a_typed_heartbeat_marker(tmp_path):
    sess = flight.arm(tmp_path, "t-hb")
    sess.append_heartbeat(phase="thinking…", elapsed=137.4, step_index=0, max_steps=40)
    (rec,) = _records(flight.feed_path(tmp_path, "t-hb"))
    assert rec["type"] == "heartbeat"
    assert rec["phase"] == "thinking…"
    assert rec["elapsed"] == pytest.approx(137.4, abs=0.01)
    assert rec["step_index"] == 0
    # human-readable liveness the pilot/senses surface directly
    assert "137s elapsed" in rec["intent"]
    assert "step 0/40" in rec["intent"]


def test_step_records_carry_no_type_but_markers_do(tmp_path):
    """The filter mechanism: a step record has no ``type`` key (byte-identical to
    pre-#308), a marker does — so a step counter / step-only replay filters markers
    out by ``record.get("type")``."""
    sess = flight.arm(tmp_path, "t-mix")
    sess.append_run_start(goal="x", max_steps=5)
    sess.append_feed(step_index=0, tool="read_file", intent="read x", stats={})
    sess.append_heartbeat(phase="thinking…", elapsed=1.0, step_index=1, max_steps=5)
    sess.append_feed(step_index=1, tool="edit_file", intent="edit y", stats={})
    records = _records(flight.feed_path(tmp_path, "t-mix"))
    steps = [r for r in records if "type" not in r]
    markers = [r for r in records if r.get("type") in {"run-start", "heartbeat"}]
    assert len(steps) == 2  # only the two real tool steps
    assert len(markers) == 2


# ── loop integration + the #206 invariant ─────────────────────────────────


@pytest.fixture
def keep_feed(monkeypatch):
    """Keep the feed past finish so we can inspect what the loop wrote."""
    monkeypatch.setattr(flight.FlightSession, "reap", lambda self: None)


def test_watched_mock_run_writes_run_start_before_any_step(tmp_path, keep_feed):
    """End-to-end: an armed run puts a run-start marker on the feed before its
    first real step, so senses has something to surface immediately."""
    repo = tmp_path / "op"
    repo.mkdir()
    task = Task.new(str(repo), "do a small thing", engine="mock", watch=True)
    registry.load("mock").work(task, EngineConfig.resolve())
    records = _records(flight.feed_path(repo, task.id))
    assert records, "the feed must not be empty"
    assert records[0].get("type") == "run-start"  # liveness BEFORE the first step
    first_step_idx = next((i for i, r in enumerate(records) if "type" not in r), len(records))
    run_start_idx = next(i for i, r in enumerate(records) if r.get("type") == "run-start")
    assert run_start_idx < first_step_idx


def test_206_invariant_watch_does_not_change_the_step_trace(tmp_path, keep_feed):
    """The #206 no-phantom-step invariant: arming the flight (which writes
    run-start + heartbeat markers to the feed) does NOT perturb the step trace or
    step_count — markers live in the feed only, never in result.steps."""
    cfg = EngineConfig.resolve()
    watched_repo = tmp_path / "watched"
    plain_repo = tmp_path / "plain"
    watched_repo.mkdir()
    plain_repo.mkdir()

    r_watch = registry.load("mock").work(
        Task.new(str(watched_repo), "do work", engine="mock", watch=True), cfg
    )
    r_plain = registry.load("mock").work(
        Task.new(str(plain_repo), "do work", engine="mock", watch=False), cfg
    )

    # identical step trace + step_count despite the markers on the watched feed
    assert r_watch.stats.step_count == r_plain.stats.step_count
    assert [s.tool for s in r_watch.steps] == [s.tool for s in r_plain.steps]

    # ...and the watched run really did write to its own flight plane
    assert flight.flight_dir(watched_repo).exists()


def test_no_watch_writes_no_feed_marker(tmp_path):
    """Strict no-op: an unwatched run creates no flight dir at all."""
    repo = tmp_path / "op"
    repo.mkdir()
    task = Task.new(str(repo), "do work", engine="mock", watch=False)
    registry.load("mock").work(task, EngineConfig.resolve())
    assert not flight.flight_dir(repo).exists()


# ── t2 end-to-end: both arms (armed/unarmed) against the recorded feed JSON,
# through BOTH engines (all-engines rule) ──────────────────────────────────


def _run_start_record(repo, task_id):
    records = _records(flight.feed_path(repo, task_id))
    return next(r for r in records if r.get("type") == "run-start")


def _worker_armed_config():
    """A resolved config with a three-tier worker seat — built directly
    (rather than through ``EngineConfig.resolve()`` against a live lobes
    gateway) since only ``config.worker``'s presence matters to the seat
    label (s16 of the spec: "the front reads config.worker as the armed
    signal")."""
    from dataclasses import replace

    from colleague.config import WorkerConfig

    return replace(
        EngineConfig.resolve(),
        three_tier=True,
        worker=WorkerConfig(
            model="worker/model",
            base_url="http://gateway.example:8001/v1",
            api_key="worker-secret",
            context=131072,
        ),
    )


def test_watched_mock_run_run_start_names_cortex_when_unarmed(tmp_path, keep_feed):
    """Unarmed arm (mock engine): no three-tier worker resolved -> the
    run-start feed line still names cortex, byte-identically to every prior
    release."""
    repo = tmp_path / "op"
    repo.mkdir()
    task = Task.new(str(repo), "do a small thing", engine="mock", watch=True)
    registry.load("mock").work(task, EngineConfig.resolve())
    rec = _run_start_record(repo, task.id)
    assert rec["seat"] == "cortex"
    assert rec["intent"].startswith("cortex started")


def test_watched_mock_run_run_start_names_worker_when_three_tier_armed(tmp_path, keep_feed):
    """Armed arm (mock engine): a resolved ``config.worker`` -> the run-start
    feed line names the worker seat instead of cortex."""
    repo = tmp_path / "op"
    repo.mkdir()
    task = Task.new(str(repo), "do a small thing", engine="mock", watch=True)
    registry.load("mock").work(task, _worker_armed_config())
    rec = _run_start_record(repo, task.id)
    assert rec["seat"] == "worker"
    assert rec["intent"].startswith("worker started")


def test_watched_vllm_run_run_start_names_cortex_when_unarmed(tmp_path, monkeypatch, keep_feed):
    """All-engines rule, unarmed arm: the vLLM backend (mocked HTTP, no live
    rig needed) renders the SAME byte-identical cortex line as the mock
    engine when three-tier is not armed."""
    from colleague.engines import vllm_openai
    from colleague.engines.vllm_openai import VllmOpenAIEngine

    def fake_post(url, payload, *, api_key, timeout):
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
                                    "arguments": json.dumps({"summary": "done"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    repo = tmp_path / "op"
    repo.mkdir()
    task = Task.new(str(repo), "do a small thing", engine="vllm-openai", watch=True)
    VllmOpenAIEngine().work(task, EngineConfig.resolve())
    rec = _run_start_record(repo, task.id)
    assert rec["seat"] == "cortex"
    assert rec["intent"].startswith("cortex started")


def test_watched_vllm_run_run_start_names_worker_when_three_tier_armed(
    tmp_path, monkeypatch, keep_feed
):
    """All-engines rule, armed arm: the vLLM backend names the worker seat
    exactly like the mock engine when ``config.worker`` is resolved."""
    from colleague.engines import vllm_openai
    from colleague.engines.vllm_openai import VllmOpenAIEngine

    def fake_post(url, payload, *, api_key, timeout):
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
                                    "arguments": json.dumps({"summary": "done"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    repo = tmp_path / "op"
    repo.mkdir()
    task = Task.new(str(repo), "do a small thing", engine="vllm-openai", watch=True)
    VllmOpenAIEngine().work(task, _worker_armed_config())
    rec = _run_start_record(repo, task.id)
    assert rec["seat"] == "worker"
    assert rec["intent"].startswith("worker started")

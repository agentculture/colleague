"""Runtime token-delta seam (feels-alive arc, task t3).

An OPTIONAL ``EngineConfig.on_delta`` sink lets an engine feed ordered,
in-progress text deltas of the model's own completion to a consumer (a later
task, t6, arms it from the session cockpit). It bypasses ``colleague/loop.py``
entirely by design (see ``colleague/config.py``'s ``EngineConfig.on_delta``
docstring): each backend's OWN completion-building code (the code that
already receives ``config``, e.g. ``MockEngine.work``, or the vLLM adapter's
``_make_complete``) reads ``config.on_delta`` directly and calls it as the
model's answer streams in, still returning the same ``ModelResponse`` at the
end. The loop never sees deltas, so a delta can never influence a step, a
progress event, the flight feed, or ``TaskResult`` in any way — those are
exactly the invariants this file pins.

The mock engine (task t3) is the reference producer here — it streams each
scripted turn's ``content`` as ordered synthetic word-chunks when armed
(``colleague/engines/mock.py``), so the seam is exercisable with no network,
mirroring how the vLLM engine's real SSE stream will drive it (task t4).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from colleague import flight, registry
from colleague.config import EngineConfig
from colleague.contract import Task

# The mock's deterministic two-turn script (colleague/engines/mock.py
# `_script`): turn 1 writes the marker file with content "writing the marker
# file" (4 words), turn 2 finishes with content "done" (1 word). Pinned here
# because this file specifically tests the streaming behaviour of that exact
# reference script — the mock is the contract reference (h5/h8).
_TURN_1_CONTENT = "writing the marker file"
_TURN_2_CONTENT = "done"
_FIXED_TASK_ID = "fixed-delta-task"


def _records(fp: Path) -> list[dict]:
    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


def _normalize_flight_record(record: dict[str, Any]) -> dict[str, Any]:
    """Drop a heartbeat's wall-clock fields (``at``/``elapsed``) so two separate
    runs' feeds can be compared for content, not timing noise.

    Note: a step record's ``intent`` legitimately embeds the turn's
    ``resp.content`` already (``colleague/loop.py``'s ``_flight_record`` — this
    predates the delta seam entirely). This helper does NOT strip that; the
    point of the flight-feed test below is that arming ``on_delta`` adds
    NOTHING beyond what the loop already, legitimately writes.
    """
    record = dict(record)
    record.pop("at", None)
    if "elapsed" in record:
        record["elapsed"] = None
    return record


def _base_config() -> EngineConfig:
    return EngineConfig.resolve()


def _normalized(data: dict[str, Any]) -> dict[str, Any]:
    """Drop the wall-clock fields that legitimately vary run to run."""
    data = json.loads(json.dumps(data))  # deep copy via round-trip
    data["stats"]["started_at"] = ""
    data["stats"]["duration_seconds"] = 0.0
    return data


def _task(repo: Path, *, watch: bool = False) -> Task:
    return Task(
        id=_FIXED_TASK_ID,
        repo_path=str(repo),
        instruction="do a small thing",
        watch=watch,
    )


# ── EngineConfig.on_delta: shape + defaults ────────────────────────────────


def test_on_delta_defaults_to_none() -> None:
    assert EngineConfig().on_delta is None
    assert EngineConfig.resolve().on_delta is None


def test_on_delta_is_excluded_from_to_dict_and_eq() -> None:
    cfg_a = EngineConfig.resolve()
    cfg_b = dataclasses.replace(cfg_a, on_delta=lambda _chunk: None)
    assert "on_delta" not in cfg_a.to_dict()
    assert "on_delta" not in cfg_b.to_dict()
    # compare=False: two configs differing only by on_delta still compare equal
    # (it is behavior, not serializable/comparable config — the `progress`
    # field precedent).
    assert cfg_a == cfg_b


# ── Unarmed: byte-identical to the current released shape ─────────────────


def test_unarmed_mock_run_is_deterministic_across_two_runs(tmp_path: Path) -> None:
    """The baseline the rest of this file compares an ARMED run against: with
    no on_delta sink, the SAME task produces the SAME TaskResult.to_dict()
    every time (mod wall-clock fields) — i.e. today's released behavior."""
    cfg = _base_config()
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()

    result_a = registry.load("mock").work(_task(repo_a), dataclasses.replace(cfg, on_delta=None))
    result_b = registry.load("mock").work(_task(repo_b), dataclasses.replace(cfg, on_delta=None))

    assert _normalized(result_a.to_dict()) == _normalized(result_b.to_dict())


def test_armed_mock_run_produces_the_same_task_result_as_unarmed(tmp_path: Path) -> None:
    """Streaming is display-only: arming on_delta must not change ANYTHING in
    the TaskResult, down to the byte (mod wall-clock fields)."""
    cfg = _base_config()
    plain_repo = tmp_path / "plain"
    armed_repo = tmp_path / "armed"
    plain_repo.mkdir()
    armed_repo.mkdir()

    plain_result = registry.load("mock").work(
        _task(plain_repo), dataclasses.replace(cfg, on_delta=None)
    )
    deltas: list[str] = []
    armed_result = registry.load("mock").work(
        _task(armed_repo), dataclasses.replace(cfg, on_delta=deltas.append)
    )

    assert len(deltas) > 1  # sanity: the seam really armed
    assert _normalized(plain_result.to_dict()) == _normalized(armed_result.to_dict())
    assert armed_result.stats.step_count == plain_result.stats.step_count


# ── Armed: ordered deltas reconstruct each turn's content exactly ─────────


def test_armed_mock_run_streams_ordered_deltas_reconstructing_each_turn(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    deltas: list[str] = []
    registry.load("mock").work(
        _task(repo), dataclasses.replace(_base_config(), on_delta=deltas.append)
    )

    assert len(deltas) > 1
    # Turn 1 ("writing the marker file") streams as 4 word-chunks, turn 2
    # ("done") as its own single chunk — both reconstruct their source turn
    # exactly, in call order, and the whole stream is ordered start to finish.
    assert "".join(deltas[:4]) == _TURN_1_CONTENT
    assert "".join(deltas[4:]) == _TURN_2_CONTENT
    assert "".join(deltas) == _TURN_1_CONTENT + _TURN_2_CONTENT


def test_unarmed_mock_run_emits_no_deltas(tmp_path: Path) -> None:
    """The only state reachable via a bare resolve(): no sink, no stream."""
    repo = tmp_path / "repo"
    repo.mkdir()
    deltas: list[str] = []
    # on_delta stays at its default (None) — the sink is never wired, so it
    # must never be invoked regardless of what a test harness might append to.
    registry.load("mock").work(_task(repo), _base_config())
    assert deltas == []


# ── Never touches step_count / the progress sink / the flight feed ────────


def test_armed_run_emits_no_extra_progress_events(tmp_path: Path) -> None:
    """A delta rides an out-of-band sink call, never ``ctx.progress`` — the
    progress-event LIST (tool names, in order) must be identical whether or
    not on_delta is armed."""
    cfg = _base_config()
    plain_repo = tmp_path / "plain"
    armed_repo = tmp_path / "armed"
    plain_repo.mkdir()
    armed_repo.mkdir()

    plain_events: list[tuple] = []
    armed_events: list[tuple] = []

    registry.load("mock").work(
        _task(plain_repo),
        dataclasses.replace(cfg, on_delta=None, progress=lambda *a: plain_events.append(a)),
    )
    deltas: list[str] = []
    registry.load("mock").work(
        _task(armed_repo),
        dataclasses.replace(
            cfg, on_delta=deltas.append, progress=lambda *a: armed_events.append(a)
        ),
    )

    assert len(deltas) > 1
    assert armed_events == plain_events


def test_armed_run_never_writes_deltas_to_the_flight_feed(tmp_path: Path, monkeypatch) -> None:
    """Deltas never touch ``colleague/flight.py``: the feed is BYTE-FOR-BYTE
    the same (mod wall-clock noise) whether or not on_delta is armed — arming
    the seam adds nothing to the feed beyond what the loop already,
    legitimately writes there."""
    # Keep the feed past finish so we can inspect what the loop wrote
    # (mirrors tests/test_flight_heartbeat.py's `keep_feed` fixture).
    monkeypatch.setattr(flight.FlightSession, "reap", lambda self: None)

    cfg = _base_config()
    plain_repo = tmp_path / "plain"
    armed_repo = tmp_path / "armed"
    plain_repo.mkdir()
    armed_repo.mkdir()

    registry.load("mock").work(
        _task(plain_repo, watch=True), dataclasses.replace(cfg, on_delta=None)
    )
    deltas: list[str] = []
    registry.load("mock").work(
        _task(armed_repo, watch=True), dataclasses.replace(cfg, on_delta=deltas.append)
    )

    assert len(deltas) > 1
    plain_records = _records(flight.feed_path(plain_repo, _FIXED_TASK_ID))
    armed_records = _records(flight.feed_path(armed_repo, _FIXED_TASK_ID))
    assert armed_records  # sanity: the feed really was written to
    assert [_normalize_flight_record(r) for r in armed_records] == [
        _normalize_flight_record(r) for r in plain_records
    ]

"""``TaskResult.chain`` — chain-of-episodes accounting on the artifact (c20/h19).

A chained run (``--until-done``) stamps a :class:`~colleague.contract.ChainView`
on each episode's artifact: which episode this is, how many episodes exist so
far, and running totals whose tokens/steps are SUMS of per-episode exact usage
— never estimated (the tokens-are-exact rule, h19). An ordinary run's artifact
stays byte-identical (no ``chain`` key at all), mirroring the ``continued_from``
omit-when-None precedent (#167).
"""

from __future__ import annotations

import json
from pathlib import Path

from colleague import artifact
from colleague.contract import OK, ChainView, TaskResult, Usage, WorkStats

# ── ChainView round-trip ─────────────────────────────────────────────────


def test_chain_view_to_dict_shape() -> None:
    view = ChainView(
        episode_index=2,
        episode_count=2,
        total_steps=17,
        total_prompt_tokens=1000,
        total_completion_tokens=250,
        total_tokens=1250,
    )
    assert view.to_dict() == {
        "episode_index": 2,
        "episode_count": 2,
        "total_steps": 17,
        "total_prompt_tokens": 1000,
        "total_completion_tokens": 250,
        "total_tokens": 1250,
    }


def test_chain_view_round_trip() -> None:
    original = ChainView(
        episode_index=3,
        episode_count=3,
        total_steps=42,
        total_prompt_tokens=9,
        total_completion_tokens=8,
        total_tokens=17,
    )
    assert ChainView.from_dict(original.to_dict()) == original


def test_chain_view_from_dict_tolerates_malformed_payloads() -> None:
    # Missing keys and explicit nulls degrade to zeros; a non-dict payload
    # yields an all-zero record — best-effort, never raises (the
    # IncompletionRecord stance on optional structured payloads).
    assert ChainView.from_dict({}) == ChainView(0, 0, 0, 0, 0, 0)
    assert ChainView.from_dict({"episode_index": None}).episode_index == 0
    assert ChainView.from_dict("garbage") == ChainView(0, 0, 0, 0, 0, 0)
    assert ChainView.from_dict(None) == ChainView(0, 0, 0, 0, 0, 0)


# ── TaskResult.chain — omit-when-None, round-trips ───────────────────────


def test_default_is_none_and_key_omitted() -> None:
    result = TaskResult(task_id="abc", status=OK, summary="done")
    assert result.chain is None
    assert "chain" not in result.to_dict()


def test_populated_field_serializes() -> None:
    view = ChainView(1, 1, 5, 100, 20, 120)
    result = TaskResult(task_id="ep1", status=OK, summary="done", chain=view)
    assert result.to_dict()["chain"] == view.to_dict()


def test_round_trip() -> None:
    view = ChainView(2, 2, 9, 300, 60, 360)
    original = TaskResult(task_id="ep2", status=OK, summary="done", chain=view)
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.chain == view


def test_round_trip_absent_key_stays_none() -> None:
    original = TaskResult(task_id="abc", status=OK, summary="done")
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.chain is None


def test_explicit_null_reads_as_none() -> None:
    data = TaskResult(task_id="abc", status=OK, summary="done").to_dict()
    data["chain"] = None
    assert TaskResult.from_dict(data).chain is None


def test_non_dict_chain_reads_as_none() -> None:
    data = TaskResult(task_id="abc", status=OK, summary="done").to_dict()
    data["chain"] = "not-a-mapping"
    assert TaskResult.from_dict(data).chain is None


# ── accumulate: totals are SUMS of per-episode exact usage (h19) ─────────


def _episode(task_id: str, *, prompt: int, completion: int, steps: int) -> TaskResult:
    """One episode's result with exact per-episode usage and step count."""
    usage = Usage()
    usage.add(prompt, completion)
    return TaskResult(
        task_id=task_id,
        status=OK,
        summary=f"episode {task_id}",
        usage=usage,
        stats=WorkStats(step_count=steps),
    )


def test_accumulate_first_episode() -> None:
    ep1 = _episode("e1", prompt=100, completion=30, steps=4)
    view = ChainView.accumulate(None, ep1)
    assert view == ChainView(
        episode_index=1,
        episode_count=1,
        total_steps=4,
        total_prompt_tokens=100,
        total_completion_tokens=30,
        total_tokens=130,
    )


def test_accumulate_sums_exact_per_episode_usage() -> None:
    """Additivity from real per-episode numbers: totals == sums, never estimates."""
    episodes = [
        _episode("e1", prompt=100, completion=30, steps=4),
        _episode("e2", prompt=250, completion=75, steps=7),
        _episode("e3", prompt=40, completion=10, steps=2),
    ]
    view: ChainView | None = None
    for ep in episodes:
        view = ChainView.accumulate(view, ep)
    assert view is not None
    assert view.episode_index == 3
    assert view.episode_count == 3
    # Sums of the per-episode exact values — asserted against the episodes'
    # own usage/stats, not re-derived constants.
    assert view.total_steps == sum(ep.stats.step_count for ep in episodes)
    assert view.total_prompt_tokens == sum(ep.usage.prompt_tokens for ep in episodes)
    assert view.total_completion_tokens == sum(ep.usage.completion_tokens for ep in episodes)
    assert view.total_tokens == sum(ep.usage.total_tokens for ep in episodes)


def test_work_stats_stay_per_episode() -> None:
    """The chain view never merges per-episode stats: each episode's WorkStats
    keeps its own numbers after accumulation (c20 — exact per-episode, never
    merged estimates)."""
    ep1 = _episode("e1", prompt=100, completion=30, steps=4)
    ep2 = _episode("e2", prompt=250, completion=75, steps=7)
    view = ChainView.accumulate(ChainView.accumulate(None, ep1), ep2)
    assert view.total_steps == 11
    # Per-episode records are untouched.
    assert ep1.stats.step_count == 4
    assert ep2.stats.step_count == 7
    assert ep1.usage.total_tokens == 130
    assert ep2.usage.total_tokens == 325


# ── artifact rendering: the final episode's artifact carries the totals ──


def test_final_artifact_renders_chain_totals(tmp_path: Path) -> None:
    episodes = [
        _episode("e1", prompt=100, completion=30, steps=4),
        _episode("e2", prompt=250, completion=75, steps=7),
        _episode("e3", prompt=40, completion=10, steps=2),
    ]
    view: ChainView | None = None
    for ep in episodes:
        view = ChainView.accumulate(view, ep)
    final = episodes[-1]
    final.chain = view

    path = artifact.write(final, tmp_path / ".colleague")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["chain"] == {
        "episode_index": 3,
        "episode_count": 3,
        "total_steps": 13,
        "total_prompt_tokens": 390,
        "total_completion_tokens": 115,
        "total_tokens": 505,
    }
    # Additivity against the real per-episode numbers in the same artifact set.
    assert data["chain"]["total_tokens"] == sum(ep.usage.total_tokens for ep in episodes)
    # The final episode's OWN stats/usage stay per-episode in the artifact.
    assert data["stats"]["step_count"] == 2
    assert data["usage"]["total_tokens"] == 50


def test_ordinary_artifact_has_no_chain_key(tmp_path: Path) -> None:
    result = _episode("solo", prompt=10, completion=5, steps=1)
    path = artifact.write(result, tmp_path / ".colleague")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "chain" not in data


# ── artifact.read_chain_view: best-effort read-back ──────────────────────


def test_read_chain_view_reads_back_written_view(tmp_path: Path) -> None:
    view = ChainView(2, 2, 9, 300, 60, 360)
    result = _episode("ep2", prompt=250, completion=75, steps=7)
    result.chain = view
    artifact.write(result, artifact.artifact_dir(tmp_path))
    assert artifact.read_chain_view(tmp_path, "ep2") == view


def test_read_chain_view_none_without_chain(tmp_path: Path) -> None:
    result = _episode("solo", prompt=10, completion=5, steps=1)
    artifact.write(result, artifact.artifact_dir(tmp_path))
    assert artifact.read_chain_view(tmp_path, "solo") is None


def test_read_chain_view_none_for_missing_artifact(tmp_path: Path) -> None:
    assert artifact.read_chain_view(tmp_path, "no-such-task") is None


# ── deferred_gate_episodes: chain gate-deferral accounting (#341) ─────────


def test_deferred_gate_episodes_default_empty_and_omitted() -> None:
    view = ChainView(1, 1, 5, 100, 20, 120)
    assert view.deferred_gate_episodes == ()
    # Omit-when-empty: an all-gated chain's artifact stays byte-identical.
    assert "deferred_gate_episodes" not in view.to_dict()


def test_deferred_gate_episodes_serializes_and_round_trips() -> None:
    view = ChainView(2, 2, 9, 300, 60, 360, deferred_gate_episodes=("ep1", "ep2"))
    assert view.to_dict()["deferred_gate_episodes"] == ["ep1", "ep2"]
    assert ChainView.from_dict(view.to_dict()) == view


def test_deferred_gate_episodes_from_dict_degrades_to_empty() -> None:
    base = ChainView(1, 1, 1, 1, 1, 2).to_dict()
    for junk in (None, "not-a-list", 7, {"a": 1}):
        data = dict(base)
        data["deferred_gate_episodes"] = junk
        assert ChainView.from_dict(data).deferred_gate_episodes == ()
    # Non-string entries are dropped, string entries kept — never raises.
    data = dict(base)
    data["deferred_gate_episodes"] = ["ep1", 3, None, "ep2"]
    assert ChainView.from_dict(data).deferred_gate_episodes == ("ep1", "ep2")


def test_accumulate_appends_deferring_episode_ids() -> None:
    ep1 = _episode("e1", prompt=100, completion=30, steps=4)
    ep1.gates_deferred = True
    ep2 = _episode("e2", prompt=250, completion=75, steps=7)
    ep3 = _episode("e3", prompt=40, completion=10, steps=2)
    ep3.gates_deferred = True
    view: ChainView | None = None
    for ep in (ep1, ep2, ep3):
        view = ChainView.accumulate(view, ep)
    assert view is not None
    # Only the deferring episodes' ids, in chain order.
    assert view.deferred_gate_episodes == ("e1", "e3")


def test_accumulate_without_deferral_stays_empty() -> None:
    ep1 = _episode("e1", prompt=100, completion=30, steps=4)
    view = ChainView.accumulate(None, ep1)
    assert view.deferred_gate_episodes == ()


# ── TaskResult.gates_deferred: the structured deferral marker (#341) ──────


def test_gates_deferred_default_false_and_omitted() -> None:
    result = TaskResult(task_id="abc", status=OK, summary="done")
    assert result.gates_deferred is False
    assert "gates_deferred" not in result.to_dict()


def test_gates_deferred_true_serializes_and_round_trips() -> None:
    result = TaskResult(task_id="ep1", status=OK, summary="done", gates_deferred=True)
    assert result.to_dict()["gates_deferred"] is True
    assert TaskResult.from_dict(result.to_dict()).gates_deferred is True


def test_gates_deferred_missing_or_null_reads_false() -> None:
    data = TaskResult(task_id="abc", status=OK, summary="done").to_dict()
    assert TaskResult.from_dict(data).gates_deferred is False
    data["gates_deferred"] = None
    assert TaskResult.from_dict(data).gates_deferred is False

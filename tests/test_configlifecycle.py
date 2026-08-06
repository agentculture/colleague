"""Episode-boundary config lifecycle (three-tier-execution plan task t6).

TEST-FIRST for ``colleague/configlifecycle.py`` — the pure, in-memory
:class:`~colleague.configlifecycle.EpisodeConfigLifecycle` that holds one
worker episode's resolved, immutable configuration and applies queued
:class:`~colleague.lattice.ChangeUnit` proposals ONLY at a sanctioned window
(colleague/chain.py's :func:`~colleague.chain.apply_config_window`).

Covers (plan task t6): c8, h8, c26, h22.

Pinned here:

- a queued proposal never changes :meth:`effective_digest` until
  :meth:`apply_window` runs (acceptance 1: the digest is constant across
  every model turn within an episode; a mid-episode proposal applies only at
  the NEXT window);
- :meth:`apply_window` refuses any window string outside the two sanctioned
  ones — "before episode 1" and "between episodes";
- a ``senses.*``-targeted proposal is refused (out of this lifecycle's
  worker-seat scope), never silently dropped;
- :meth:`end_episode` is the T1-regression primitive (loop.py calls it on
  EVERY exit path — the loop-side proof lives in ``test_loop_config_
  lifecycle.py``; here we pin that the counter itself is exit-reason-agnostic
  — nothing about ``end_episode`` cares HOW an episode ended);
- :meth:`child_snapshot` is the risk-r2 inheritance default: a subagent
  spawned mid-episode gets the CURRENT effective snapshot, never a
  queued-but-unapplied proposal;
- :meth:`reset` is "config discarded at top-level task end";
- latency is recorded on every :class:`~colleague.configlifecycle.ConfigApplication`
  (acceptance 3);
- this module imports no ``threading`` / ``concurrent.futures`` (pinned
  structurally by ``tests/test_boundary.py``, unmodified, which parametrizes
  over every ``colleague/*.py`` source and so already covers this new file).
"""

from __future__ import annotations

import pytest

from colleague.configlifecycle import (
    SANCTIONED_WINDOWS,
    WINDOW_BEFORE_EPISODE_1,
    WINDOW_BETWEEN_EPISODES,
    ConfigApplication,
    ConfigLifecycleError,
    EpisodeConfigLifecycle,
    EpisodeConfigSnapshot,
)
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _catalog(tool_ids: list[str]) -> CapabilityCatalog:
    return CapabilityCatalog(tool_ids=tuple(tool_ids))


def _tools_change(tool_ids: list[str], origin: Origin = Origin.CORTEX) -> ChangeUnit:
    return ChangeUnit(target=Target.WORKER_TOOLS, origin=origin, tool_ids=tool_ids)


def _strategist_change(origin: Origin = Origin.CORTEX) -> ChangeUnit:
    return ChangeUnit(target=Target.WORKER_PROMPT_STRATEGIST, origin=origin)


def _knowledge_change(origin: Origin = Origin.CORTEX) -> ChangeUnit:
    return ChangeUnit(
        target=Target.WORKER_KNOWLEDGE,
        origin=origin,
        knowledge_entries=[{"key": "fact1", "origin": origin.value}],
    )


# ===========================================================================
# EpisodeConfigSnapshot — digest determinism
# ===========================================================================


def test_snapshot_digest_deterministic_for_equal_content() -> None:
    a = EpisodeConfigSnapshot(tool_set=("read_file", "write_file"))
    b = EpisodeConfigSnapshot(tool_set=("read_file", "write_file"))
    assert a.digest() == b.digest()


def test_snapshot_digest_changes_with_content() -> None:
    a = EpisodeConfigSnapshot(tool_set=("read_file",))
    b = EpisodeConfigSnapshot(tool_set=("read_file", "write_file"))
    assert a.digest() != b.digest()


def test_default_snapshot_digest_is_stable() -> None:
    # A fresh default snapshot always digests the same — used by reset() /
    # a fresh top-level task's starting point.
    first_digest = EpisodeConfigSnapshot().digest()
    second_digest = EpisodeConfigSnapshot().digest()
    assert first_digest == second_digest


# ===========================================================================
# Acceptance 1 — digest constant until a sanctioned window applies
# ===========================================================================


def test_propose_queues_but_never_changes_effective_digest() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file", "write_file"]))
    before = lifecycle.effective_digest()

    verdict = lifecycle.propose(_tools_change(["read_file"]))

    assert verdict.allowed is True
    assert lifecycle.effective_digest() == before
    assert lifecycle.pending_count() == 1


def test_multiple_mid_episode_proposals_never_move_the_digest() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file", "write_file"]))
    before = lifecycle.effective_digest()

    lifecycle.propose(_tools_change(["read_file"]))
    lifecycle.propose(_strategist_change())
    lifecycle.propose(_knowledge_change())

    assert lifecycle.effective_digest() == before
    assert lifecycle.pending_count() == 3


def test_apply_window_before_episode_1_applies_queue_and_moves_digest() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    before = lifecycle.effective_digest()
    lifecycle.propose(_tools_change(["read_file"]))

    application = lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    assert application.window == WINDOW_BEFORE_EPISODE_1
    assert application.applied_count == 1
    assert application.digest_before == before
    assert application.digest_after == lifecycle.effective_digest()
    assert application.digest_after != before
    assert lifecycle.pending_count() == 0
    assert lifecycle.snapshot.tool_set == ("read_file",)


def test_apply_window_between_episodes_applies_queue_and_moves_digest() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(
        ChangeUnit(
            target=Target.WORKER_PROMPT_STRATEGIST,
            origin=Origin.CORTEX,
            content="Strategy text",
        )
    )
    before = lifecycle.effective_digest()

    application = lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)

    assert application.window == WINDOW_BETWEEN_EPISODES
    assert application.digest_before == before
    assert application.digest_after != before
    assert lifecycle.snapshot.strategist_sections == ("Strategy text",)


def test_apply_window_with_empty_queue_is_a_recorded_noop() -> None:
    lifecycle = EpisodeConfigLifecycle()
    before = lifecycle.effective_digest()

    application = lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)

    assert application.applied_count == 0
    assert application.digest_before == before
    assert application.digest_after == before


@pytest.mark.parametrize("window", ["mid-episode", "", "BEFORE_EPISODE_1", "between_episodes"])
def test_apply_window_refuses_unsanctioned_window(window: str) -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.propose(_strategist_change())

    with pytest.raises(ConfigLifecycleError):
        lifecycle.apply_window(window)

    # A refused window call must not silently drain the queue.
    assert lifecycle.pending_count() == 1


def test_sanctioned_windows_are_exactly_the_two_named_constants() -> None:
    assert SANCTIONED_WINDOWS == {WINDOW_BEFORE_EPISODE_1, WINDOW_BETWEEN_EPISODES}


# ===========================================================================
# senses.* targets are refused, not silently dropped
# ===========================================================================


def test_propose_refuses_senses_targets_out_of_scope() -> None:
    lifecycle = EpisodeConfigLifecycle()
    unit = ChangeUnit(target=Target.SENSES_PROMPT_STRATEGIST, origin=Origin.CORTEX)

    verdict = lifecycle.propose(unit)

    assert verdict.allowed is False
    assert "senses" in verdict.reason.lower()
    assert lifecycle.pending_count() == 0


def test_propose_refuses_unknown_tool_id_via_lattice_catalog() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))

    verdict = lifecycle.propose(_tools_change(["run_command"]))

    assert verdict.allowed is False
    assert lifecycle.pending_count() == 0


def test_propose_refuses_worker_origin_writing_tools() -> None:
    # Authority ceiling (t4): worker may write only senses.knowledge — a
    # worker-origin worker.tools change refuses through the SAME lattice call.
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))

    verdict = lifecycle.propose(_tools_change(["read_file"], origin=Origin.WORKER))

    assert verdict.allowed is False
    assert lifecycle.pending_count() == 0


# ===========================================================================
# Boundary counter (T1 regression primitive)
# ===========================================================================


def test_end_episode_increments_boundary_count() -> None:
    lifecycle = EpisodeConfigLifecycle()
    assert lifecycle.boundary_count == 0

    first = lifecycle.end_episode()
    second = lifecycle.end_episode()

    assert first == 1
    assert second == 2
    assert lifecycle.boundary_count == 2


def test_end_episode_never_touches_the_queue_or_snapshot() -> None:
    # The counter is exit-reason-agnostic BY CONSTRUCTION: nothing about
    # end_episode() applies proposals or moves the digest — only
    # apply_window() (called at a sanctioned window) does that.
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(_tools_change(["read_file"]))
    before = lifecycle.effective_digest()

    lifecycle.end_episode()

    assert lifecycle.effective_digest() == before
    assert lifecycle.pending_count() == 1


# ===========================================================================
# Per-turn observation (the loop-seam primitive)
# ===========================================================================


def test_observe_turn_records_the_pinned_digest_repeatedly() -> None:
    lifecycle = EpisodeConfigLifecycle()
    d1 = lifecycle.observe_turn()
    d2 = lifecycle.observe_turn()
    d3 = lifecycle.observe_turn()

    assert d1 == d2 == d3 == lifecycle.effective_digest()
    assert lifecycle.turn_digests() == [d1, d2, d3]


def test_observe_turn_changes_only_after_a_window_application() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    d1 = lifecycle.observe_turn()
    lifecycle.propose(_tools_change(["read_file"]))
    d2 = lifecycle.observe_turn()
    assert d2 == d1  # a queued proposal never moves an observed digest

    lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)
    d3 = lifecycle.observe_turn()

    assert d3 != d1
    assert lifecycle.turn_digests() == [d1, d2, d3]


# ===========================================================================
# Children inherit the CURRENT effective snapshot by default (risk r2)
# ===========================================================================


def test_child_snapshot_is_the_current_effective_snapshot() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    assert lifecycle.child_snapshot() == lifecycle.snapshot


def test_child_snapshot_ignores_a_queued_unapplied_proposal() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    parent_snapshot_before = lifecycle.snapshot
    lifecycle.propose(_tools_change(["read_file"]))

    child = lifecycle.child_snapshot()

    assert child == parent_snapshot_before
    assert child.tool_set == ()


def test_child_snapshot_reflects_a_post_boundary_application() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(_tools_change(["read_file"]))
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    child = lifecycle.child_snapshot()

    assert child.tool_set == ("read_file",)


# ===========================================================================
# Latency is recorded (acceptance 3)
# ===========================================================================


def test_apply_window_records_latency_on_every_application() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(_tools_change(["read_file"]))

    application = lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    assert isinstance(application, ConfigApplication)
    assert isinstance(application.latency_seconds, float)
    assert application.latency_seconds >= 0.0
    assert lifecycle.applications() == [application]


def test_applications_returns_a_defensive_copy() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    snapshot_list = lifecycle.applications()
    snapshot_list.clear()
    assert len(lifecycle.applications()) == 1


# ===========================================================================
# Config discarded at top-level task end
# ===========================================================================


def test_reset_discards_everything() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(_tools_change(["read_file"]))
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    lifecycle.observe_turn()
    lifecycle.end_episode()
    lifecycle.propose(_strategist_change())  # left queued on purpose

    lifecycle.reset()

    assert lifecycle.effective_digest() == EpisodeConfigSnapshot().digest()
    assert lifecycle.pending_count() == 0
    assert lifecycle.applications() == []
    assert lifecycle.events() == []
    assert lifecycle.turn_digests() == []
    assert lifecycle.boundary_count == 0


# ===========================================================================
# Event log — a clean to-list API for a later durable-serialization task (t7)
# ===========================================================================


def test_events_record_proposed_refused_applied_and_boundary() -> None:
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    lifecycle.propose(_tools_change(["read_file"]))  # proposed
    lifecycle.propose(_tools_change(["nonexistent-tool"]))  # refused
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)  # applied
    lifecycle.end_episode()  # boundary

    kinds = [event.kind for event in lifecycle.events()]

    assert kinds == ["proposed", "refused", "applied", "boundary"]


def test_events_returns_a_defensive_copy() -> None:
    lifecycle = EpisodeConfigLifecycle()
    lifecycle.end_episode()
    events = lifecycle.events()
    events.clear()
    assert len(lifecycle.events()) == 1


# ===========================================================================
# t5 — real-text strategist folding (replaces opaque markers)
# ===========================================================================


def test_strategist_applies_verbatim_stripped_content_not_marker() -> None:
    """Criterion 1: applied strategist unit's verbatim stripped content lands
    in snapshot.strategist_sections — no more origin#N markers."""
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    change = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST,
        origin=Origin.CORTEX,
        content="  Real strategy text here  ",
    )
    lifecycle.propose(change)
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)

    snap = lifecycle.snapshot
    assert snap.strategist_sections == ("Real strategy text here",)
    # No origin#N marker should appear
    for section in snap.strategist_sections:
        assert "#" not in section


def test_strategist_digest_moves_once_per_applied_proposal() -> None:
    """Criterion 1: the digest moves exactly once per applied proposal."""
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    before = lifecycle.effective_digest()

    change = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST,
        origin=Origin.CORTEX,
        content="Strategy content",
    )
    lifecycle.propose(change)
    # Digest unchanged while queued
    assert lifecycle.effective_digest() == before

    lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)
    after = lifecycle.effective_digest()
    assert after != before


def test_second_strategist_application_replaces_leaving_one_note() -> None:
    """Criterion 2: a second strategist application across a later window
    leaves exactly ONE current note (the later one)."""
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))

    # First strategist proposal
    lifecycle.propose(
        ChangeUnit(
            target=Target.WORKER_PROMPT_STRATEGIST,
            origin=Origin.CORTEX,
            content="First strategy",
        )
    )
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    assert lifecycle.snapshot.strategist_sections == ("First strategy",)

    # Second strategist proposal in a later window
    lifecycle.propose(
        ChangeUnit(
            target=Target.WORKER_PROMPT_STRATEGIST,
            origin=Origin.CORTEX,
            content="Second strategy",
        )
    )
    lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)

    # Only the later one remains — replace, not append
    assert lifecycle.snapshot.strategist_sections == ("Second strategy",)
    assert len(lifecycle.snapshot.strategist_sections) == 1


def test_strategist_at_content_cap_applies_without_raising() -> None:
    """Criterion 2: a unit at the content cap applies without raising."""
    from colleague.layers import STRATEGIST_SECTION_MAX_CHARS

    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
    max_content = "x" * STRATEGIST_SECTION_MAX_CHARS
    change = ChangeUnit(
        target=Target.WORKER_PROMPT_STRATEGIST,
        origin=Origin.CORTEX,
        content=max_content,
    )
    verdict = lifecycle.propose(change)
    assert verdict.allowed is True

    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    assert lifecycle.snapshot.strategist_sections == (max_content,)


def test_worker_tools_second_application_replaces_narrowed_set() -> None:
    """Criterion 3: a second worker.tools application REPLACES the narrowed
    set — narrow-then-replace widens back up to (never past) the role-curated
    ceiling in the consuming intersect."""
    lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file", "write_file", "edit_file"]))

    # First narrowing
    lifecycle.propose(_tools_change(["read_file"]))
    lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
    assert lifecycle.snapshot.tool_set == ("read_file",)

    # Second application replaces (widens back)
    lifecycle.propose(_tools_change(["read_file", "write_file"]))
    lifecycle.apply_window(WINDOW_BETWEEN_EPISODES)

    # The second set replaces the first — not appended
    assert lifecycle.snapshot.tool_set == ("read_file", "write_file")


def test_worker_tools_replace_via_narrow_role_by_tool_set() -> None:
    """Criterion 3: narrow-then-replace widens back up to (never past) the
    role-curated ceiling — verified through narrow_role_by_tool_set."""
    from colleague.tools import narrow_role_by_tool_set

    # Start with a full role (None = full surface)
    role = narrow_role_by_tool_set(None, tool_set=("read_file",))
    assert role is not None
    assert "read_file" in role.tool_allowlist
    assert "write_file" not in role.tool_allowlist

    # Replace with a wider tool_set — widens back up
    role_wider = narrow_role_by_tool_set(None, tool_set=("read_file", "write_file"))
    assert role_wider is not None
    assert "read_file" in role_wider.tool_allowlist
    assert "write_file" in role_wider.tool_allowlist

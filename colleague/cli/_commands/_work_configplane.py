"""The config-plane's state, catalog and event fold for ``colleague work``.

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16). Two members of this lane deliberately
stay in ``work.py``: ``_arm_config_plane`` (it carries the ONE assignment to
the engine-consumed lifecycle attribute that ``tests/test_content_lane_e2e.py``
pins to that file — the test sweeps every other ``colleague/**.py`` asserting
none contains that assignment, so this module must not even quote it) and
``_fold_config_plane`` (its ``update_config_events`` call is monkeypatched as
``work_module.update_config_events``, which only bites while the CALL SITE is
textually in ``work.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult

# ---------------------------------------------------------------------------
# Config-plane arming (change-content consumption lane, plan task t9 —
# spec docs/specs/2026-08-06-change-content-consumption-lane.md, c5/h5/c28/h22)
# ---------------------------------------------------------------------------
#
# The three-tier design lets cortex CONFIGURE the worker episode (a narrowed
# tool set, a bounded evaluator note, extra knowledge) via
# colleague/configlifecycle.py + colleague/configurator.py — both complete
# and tested, but nothing in either CLI or session front ever constructed a
# lifecycle or called colleague.chain.run_configurator_window (d3). This
# section is that missing caller: arming lives HERE (execute_work /
# execute_work_chain), never in cmd_work's argv parsing, so both the CLI and
# the session palette (which calls these two functions directly) inherit it
# identically. All imports below are LAZY — a run that never arms three-tier
# (config.worker is None, the default) never pays for the config-plane
# machinery's import graph, mirroring colleague/chain.py's own lazy
# colleague.configurator import.


@dataclass
class _ConfigPlaneState:
    """Bookkeeping for ONE top-level task's config plane.

    Bundles the :class:`~colleague.configlifecycle.EpisodeConfigLifecycle`
    every engine consumes via ``config.config_lifecycle`` (attached at
    construction, so the loop/engines see it from the very first dispatch),
    the configurator's own :class:`~colleague.configevents.ConfigEventStream`
    (a SEPARATE audit trail — see :func:`_combined_config_events`), the
    :class:`~colleague.lattice.CapabilityCatalog` resolved once and reused by
    every window this task runs, and the APPLIED
    :class:`~colleague.lattice.ChangeUnit` objects accumulated across every
    window so far (q5 — the only way an applied evaluator unit's verbatim
    content can ride the folded artifact, since neither the lifecycle's own
    event nor :class:`~colleague.configlifecycle.ConfigApplication` carries
    it).

    Constructed EXACTLY ONCE per top-level task (h22: "one
    ``EpisodeConfigLifecycle`` instance belongs to exactly one TOP-LEVEL
    task") — a standalone (non-chained) :func:`execute_work` call builds its
    own via :func:`_arm_config_plane`; an armed ``--until-done`` chain is
    itself ONE top-level task, so :func:`execute_work_chain` builds ONE and
    threads it to every episode via ``ChainEpisodeOptions.config_plane``
    rather than each episode building its own (which would violate h22 and
    lose the prior episodes' event history).
    """

    lifecycle: "object"
    stream: "object"
    catalog: "object"
    applied_units: list = field(default_factory=list)


def _build_capability_catalog(config: EngineConfig, repo_path: str) -> "object":
    """The run's actually-resolved tool surface, derived the SAME way the
    engines derive it (``colleague/engines/mock.py``/``vllm_openai.py``:
    ``resolve_role(config, task.repo_path)`` then ``curate_schemas(role)``)
    — the :class:`~colleague.lattice.CapabilityCatalog` contract: "built
    ONLY from a caller-supplied resolved tool allow-list", never minted by
    the lattice itself.

    ``deepthink`` stays at :func:`~colleague.tools.curate_schemas`'s default
    ``False``: deepthink is absent in three-tier mode (an architecture
    invariant — three-tier and dual-model deepthink are mutually exclusive
    escalation surfaces), so the offered surface here never includes the
    deepthink tool schema.
    """
    from colleague.lattice import CapabilityCatalog
    from colleague.loop import resolve_role
    from colleague.tools import curate_schemas

    role = resolve_role(config, repo_path)
    schemas = curate_schemas(role)
    tool_ids = tuple(s["function"]["name"] for s in schemas)
    return CapabilityCatalog(tool_ids=tool_ids)


def _accumulate_applied(state: "_ConfigPlaneState", window_result: "object") -> None:
    """Fold ONE window's applied :class:`~colleague.lattice.ChangeUnit`
    objects onto *state* (q5) — the ACCUMULATED list :func:`_combined_config_events`
    later matches positionally against every "applied" event the lifecycle
    ever recorded, across every window this top-level task has run.

    A no-op unless the window actually reviewed AND applied something: an
    unarmed configurator (``reviewed=False``), a degraded review, or a
    healthy ``{"changes": []}`` reply each apply nothing, so there is
    nothing to accumulate — mirrors
    :func:`colleague.configurator.record_applied`'s own precondition
    (``review.verified`` is exactly what *application* drained, for the ONE
    sanctioned review-then-apply call sequence
    :func:`colleague.chain.run_configurator_window` makes).
    """
    if not window_result.reviewed or window_result.application is None:
        return
    if window_result.application.applied_count == 0:
        return
    state.applied_units.extend(window_result.review.verified)


def _run_between_episodes_window(
    state: "_ConfigPlaneState",
    *,
    repo: Path,
    task: Task,
    result: TaskResult,
    config: EngineConfig,
    engine_name: str,
) -> None:
    """Run the config plane's ``WINDOW_BETWEEN_EPISODES`` window (t9) — the
    other of the two sanctioned windows (:data:`colleague.chain.
    WINDOW_BEFORE_EPISODE_1` is the ONE :func:`_arm_config_plane` runs).

    Called from :func:`execute_work_chain`'s go-verdict path — after
    :func:`_chain_should_start_next` decides episode N+1 may dispatch, before
    it actually does — with *task*/*result* the JUST-FINISHED episode's own
    (:func:`colleague.reviewinput.assemble_between_episodes` composes the
    review digest from its terminal facts). A no-op call site guard lives in
    the caller (``if config_plane is not None``); this function itself
    always runs its window once reached, same as :func:`_arm_config_plane`.
    """
    from colleague import chain as chainmod
    from colleague.configurator import configurator_enabled
    from colleague.reviewinput import assemble_between_episodes

    window_result = chainmod.run_configurator_window(
        state.lifecycle,
        chainmod.WINDOW_BETWEEN_EPISODES,
        armed=configurator_enabled(repo_path=repo),
        review_input=assemble_between_episodes(task, result),
        catalog=state.catalog,
        stream=state.stream,
        config=config,
        engine_name=engine_name,
    )
    _accumulate_applied(state, window_result)


def _combined_config_events(state: "_ConfigPlaneState") -> list:
    """Fold the config plane's two append-only records into ONE durable trail
    — never double-counted (spec requirement: "pick ONE source of truth for
    overlapping kinds").

    The CONFIGURATOR STREAM is the source of truth for the whole review
    cycle — proposed / verified / refused / applied / degraded — because it
    is the only record that sees EVERY refusal shape (a malformed reply or
    a change entry that fails to build refuses BEFORE ``lifecycle.propose``
    is ever called, so the lifecycle's own trail is silent about it — Qodo
    #369 review, thread 1) and because it records the cycle in true causal
    order (proposed -> verified -> applied per unit; the previous
    lifecycle-first construction appended every "verified" after every
    "applied" — thread 2). Stream events pass through
    :func:`colleague.contract.map_configlifecycle_events` for the
    class-selective applied-content enrichment (q5, via
    *state.applied_units* — the stream's applied events are 1:1 and
    same-order with the accumulated applied units) and reason preservation.

    The LIFECYCLE contributes ONLY its "boundary" events (mapped onto
    ``EVENT_KIND_BASELINE`` — an episode-boundary marker the stream has no
    equivalent of, recorded once per ``run()`` exit), appended after the
    cycle trail. For a single-episode run this IS chronological (the
    boundary fires at run exit, after the one window); on a chain the
    per-window interleave is approximated — each boundary event carries its
    own boundary index and effective-config digest, which is what anchors
    it to a config state, not its list position (documented approximation,
    deliberate).

    ``seq`` is renumbered across the COMBINED list — a monotonic index into
    what ``TaskResult.config_events`` actually carries, never trusted from
    either source's own internal numbering.
    """
    from dataclasses import replace as _replace

    from colleague.contract import map_configlifecycle_events

    cycle = map_configlifecycle_events(state.stream.replay(), applied_units=state.applied_units)
    boundaries = map_configlifecycle_events(
        [e for e in state.lifecycle.events() if getattr(e, "kind", "") == "boundary"]
    )
    combined = cycle + boundaries
    return [_replace(event, seq=i) for i, event in enumerate(combined)]


def _resolve_config_plane(
    chain: "object | None",
    config: EngineConfig,
    *,
    repo: Path,
    task: Task,
    engine_name: str,
) -> "_ConfigPlaneState | None":
    """Resolve THIS call's config-plane state (change-content consumption
    lane, plan task t9 — h22): a chained episode reuses the state
    :func:`execute_work_chain` already constructed once at arming (one
    lifecycle per top-level task); a standalone (non-chained) call arms its
    OWN state here, before its single dispatch. Both stay ``None`` — a
    strict no-op — unless three-tier is armed (``config.worker is not
    None``). Extracted from :func:`execute_work` to keep its cognitive
    complexity under the S3776 ceiling (the :func:`_moded_config` precedent).
    """
    if chain is not None:
        return chain.config_plane
    if config.worker is not None:
        # `_arm_config_plane` carries the pinned `config.config_lifecycle`
        # assignment and so stays in `work.py`; imported lazily here because a
        # module-level import would be circular.
        from colleague.cli._commands.work import _arm_config_plane

        return _arm_config_plane(config, repo=repo, task=task, engine_name=engine_name)
    return None

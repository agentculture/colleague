"""``colleague work`` — assign a repo task to a coder backend.

The headline verb: select an engine (a discovered wheel), run the bounded
agentic loop against a repo, write the result artifact, and hand the change off
as a branch + PR. The *same* invocation works for every backend — only
``--engine`` changes (honesty conditions h11/h12).

A failed work item still writes a result artifact (``status=error``) before exiting
non-zero, so a crash never leaves an empty run report (h5).

``--command NAME`` (and optional positional args) expands a saved command
template into the Task via :func:`colleague.commands.expand_command` and
records the originating command name on the result (``TaskResult.command``).
Exactly one of a positional instruction or ``--command`` must be supplied.

:func:`execute_work` is the shared helper that performs the work item orchestration
(load engine → run loop → handoff → write artifact) and returns the
``(TaskResult, artifact_path)`` pair.  Both ``cmd_work`` and the ``session``
palette delegate to it so the work path is never duplicated (honesty h11).

Module layout (plan ``hard-1000-line-file-limit`` t16 — the 1000-line hard
limit). The verb's helpers live in ``_work_*.py`` siblings, re-exported below
so every existing import shape (``session.py``'s three, the suite's) resolves
unchanged. What stays HERE is what is PINNED here: ``execute_work`` and every
step of it that calls a name the suite monkeypatches on THIS module
(``load_telemetry``, ``make_spawn``, ``make_batch_spawn``) — a bare-name call
resolves through the ``__globals__`` of the module it is textually defined in,
so moving such a call site would leave the patch green while intercepting
nothing; ``_arm_config_plane`` (the ONE ``config.config_lifecycle`` assignment
``tests/test_content_lane_e2e.py`` pins to this file while sweeping every other
``colleague/**.py``); ``_fold_config_plane`` (its ``update_config_events`` call
is patched as ``work_module.update_config_events``);
``_engine_failure_error`` plus the ``except Exception as exc:  # noqa: BLE001 -
any failure`` body routing into it (``tests/test_timeout_survival.py``
string-splits this file's source on both); ``_arm_interrupt_commit`` (named by
:mod:`colleague.salvage`'s docstring); and ``_handoff_result`` (named by
:mod:`colleague.contract`).
"""

from __future__ import annotations

import argparse
import os
import signal
from contextlib import suppress
from pathlib import Path
from typing import Callable

from colleague import background, registry, rig, worktrees
from colleague.artifact import artifact_dir, failed_result, update_config_events, write
from colleague.cli._banner import emit_banner
from colleague.cli._commands._listing import maybe_list_and_apply, model_arg
from colleague.cli._commands._presence_sink import (
    ack_packet_for_task,
    build_foreground_presence,
    build_watch_presence,
    compose_presence_sink,
    fold_presence_snapshot,
)
from colleague.cli._commands._work_background import (
    _background_child_argv,
    _cmd_work_background,
)
from colleague.cli._commands._work_chain import (
    ChainEpisodeOptions,
    _emit_chain_outcome,
    _resolve_chain_arming,
    _run_chain,
    execute_work_chain,
)
from colleague.cli._commands._work_configplane import (
    _accumulate_applied,
    _build_capability_catalog,
    _combined_config_events,
    _ConfigPlaneState,
    _resolve_config_plane,
)
from colleague.cli._commands._work_parser import _WORK_HELP, _configure_work_parser
from colleague.cli._commands._work_salvage import (
    _baseline_untracked_for,
    _finalize_run_outcome,
    _make_salvage_writer,
    _prepare_run,
    _preserve_isolated_wip,
    _RunSetup,
    _setup_isolation,
    finalize_interrupted,
)
from colleague.cli._commands._work_support import (
    DisplayOptions,
    _announce_flight,
    _apply_affected_tests_optout,
    _apply_coherence_optout,
    _apply_lint_optout,
    _arm_delta_stream,
    _arm_progress_sink,
    _arm_watch,
    _emit_work_outcome,
    _moded_config,
    _render,
    _stamp_run_metadata,
    _step_progress,
)
from colleague.cli._commands._work_task import (
    _build_continued_task,
    _build_task,
    _validated_mode,
)
from colleague.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from colleague.cli._output import emit_diagnostic, emit_result
from colleague.config import EngineConfig, resolve_engine
from colleague.contract import Task, TaskResult
from colleague.feedback import capture_uncaptured_predecessor, set_last_work
from colleague.handoff import HandoffError, branch_name, handoff
from colleague.subagents import (
    default_parent_profile,
    make_batch_spawn,
    make_spawn,
    new_agent_budget,
)
from colleague.telemetry import Telemetry, load_telemetry

#: Names this module re-exports for callers that have always imported them
#: from ``colleague.cli._commands.work`` (``session.py``'s three import
#: shapes, the test suite, and ``colleague.cli``'s registration hook). The
#: implementations moved to the ``_work_*`` siblings in plan t16; the import
#: surface did not.
__all__ = [
    "ChainEpisodeOptions",
    "DisplayOptions",
    "_ConfigPlaneState",
    "_arm_delta_stream",
    "_background_child_argv",
    "_build_continued_task",
    "_build_task",
    "_combined_config_events",
    "_configure_work_parser",
    "_emit_chain_outcome",
    "_make_salvage_writer",
    "_moded_config",
    "_preserve_isolated_wip",
    "_render",
    "_resolve_chain_arming",
    "_setup_isolation",
    "_step_progress",
    "_validated_mode",
    "cmd_work",
    "execute_work",
    "execute_work_chain",
    "finalize_interrupted",
    "register",
    "register_into",
]


def _handoff_result(
    *,
    repo: Path,
    task: Task,
    result: TaskResult,
    baseline_untracked: list[str],
    open_pr: bool,
    base: str,
    telemetry: Telemetry,
    base_sha: str | None = None,
) -> None:
    """Branch/commit (+push/PR) a successful work item; fold the outcome onto *result*.

    A :class:`~colleague.handoff.HandoffError` is non-fatal — the work item still
    succeeded, so it is surfaced as a diagnostic and the result keeps its local
    state. Extracted from :func:`execute_work` to keep that function's control
    flow flat.
    """
    with telemetry.handoff_span() as handoff_span:
        try:
            outcome = handoff(
                repo,
                task.id,
                instruction=task.instruction,
                changed_files=result.changed_files,
                baseline_untracked=baseline_untracked,
                open_pr=open_pr,
                base_branch=base,
                base_sha=base_sha,
            )
        except HandoffError as exc:
            emit_diagnostic(f"handoff skipped: {exc}")
            return
        result.branch = outcome.branch
        result.pr_url = outcome.pr_url
        result.tip_sha = outcome.tip_sha
        if not result.changed_files:
            result.changed_files = outcome.changed_files
        handoff_span.set(
            branch=outcome.branch,
            committed=outcome.committed,
            pushed=outcome.pushed,
            pr_url=outcome.pr_url,
        )
        if outcome.note:
            emit_diagnostic(f"handoff: {outcome.note}")


def _arm_interrupt_commit(
    worktree_path: str | None, *, salvage_write: Callable[[str], None] | None = None
) -> Callable[[], None]:
    """Install SIGTERM+SIGINT handlers that commit the iso worktree's WIP before exit (#222).

    #410: when *salvage_write* is given it runs FIRST — before the WIP commit and
    independent of whatever state the request layer is stuck in — writing the
    partial result artifact (the continuation seed) from the loop's live partial
    (:mod:`colleague.salvage`); a failure there never blocks the WIP commit. A
    ``None`` worktree with a salvage writer still arms the handlers (the artifact
    write is worktree-independent); neither → nothing is installed.

    The isolated work path's success teardown lives in a ``finally`` that a SIGTERM
    (a caller's ``timeout``) bypasses entirely, stranding the model's WIP as
    uncommitted files in an orphan worktree. This arms a handler that, on
    SIGTERM/SIGINT, commits whatever the model wrote onto its ``colleague/<id>``
    branch (best-effort, empty diff = no-op), restores the prior disposition, and
    raises ``SystemExit(128 + signum)`` — which unwinds through the normal ``finally``
    teardown (the branch keeps the WIP commit) and exits the CLI **cleanly** with the
    conventional signal exit code (143 for SIGTERM, 130 for SIGINT) and **no
    traceback**. Raising ``SystemExit`` rather than ``KeyboardInterrupt`` matters: the
    CLI dispatcher catches only ``Exception``, so a bare ``KeyboardInterrupt`` would
    print a Python traceback on a caller's ``timeout`` (review of #228, Qodo).

    A ``None`` worktree (the in-place ``session`` path) installs nothing and returns a
    no-op restore, so only the isolated path is armed. The returned callable restores
    the previous handlers and MUST be invoked on every exit. A non-main-thread /
    unsupported platform degrades gracefully (handlers simply not installed) — never
    breaking a work item. Signals are stdlib: no new dependency, daemon, or thread.
    """
    if worktree_path is None and salvage_write is None:
        return lambda: None

    previous: dict[int, object] = {}

    def _handler(signum: int, _frame: object) -> None:
        reason = signal.Signals(signum).name
        if salvage_write is not None:
            with suppress(Exception):
                salvage_write(reason)
        if worktree_path is not None:
            with suppress(Exception):
                worktrees.commit_iso_worktree_wip(worktree_path, reason=reason)
        # Restore prior handlers before exiting so a second signal can't re-enter this
        # handler mid-commit; SystemExit unwinds through the normal finally blocks
        # (cockpit close, telemetry flush, worktree remove) and exits without a traceback.
        for sig, prev in previous.items():
            with suppress(Exception):
                signal.signal(sig, prev)  # type: ignore[arg-type]
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[sig] = signal.signal(sig, _handler)
        except (ValueError, OSError):  # not the main thread / unsupported — skip
            pass

    def _restore() -> None:
        for sig, prev in previous.items():
            with suppress(Exception):
                signal.signal(sig, prev)  # type: ignore[arg-type]

    return _restore


def _engine_failure_error(
    exc: Exception,
    *,
    task: Task,
    repo: Path,
    engine_name: str,
    command_name: str | None,
    mode: str | None,
    work_span,
    continued_from: str | None = None,
    worktree_path: str | None = None,
    presence: "object | None" = None,
    presence_fold_chat: bool = False,
) -> CliError:
    """Turn an engine raise into the failure artifact + a diagnosable CliError.

    The engine-failure ``except`` body from :func:`execute_work`, extracted to
    keep that function under the S3776 cognitive-complexity threshold. Returns
    (never raises) the :class:`CliError` so the caller can ``raise ... from exc``
    at the original site.

    Prefers the partial result the loop preserved on an engine raise (#37): its
    steps / usage / changed_files + trace reflect the work done up to the
    failure; falls back to a fresh ``failed_result`` for a failure with no
    partial (e.g. an error before the loop starts). Writes the artifact and the
    ``last_work`` pointer (the work item happened even if it failed — a 1/5 is
    exactly the ROI signal), and names the exception class when the payload is
    bare (#269: ``KeyError: 'path'`` instead of ``'path'``). With a
    *worktree_path*, the iso worktree's uncommitted progress is swept onto the
    ``colleague/<id>`` branch and the hint names the surviving branch (#268
    ask 3 — the #222 sweep extended to the exception path). With a *presence*
    (t9 — background presence), any accumulated cost/injection records still
    fold onto the failure artifact before it is written, so an engine crash
    never silently drops the senses cost the run already incurred.
    """
    partial = getattr(exc, "result", None)
    if isinstance(partial, TaskResult):
        result = partial
        original: BaseException = exc.__cause__ or exc
        # A partial run has accumulated steps -> the trace is non-empty.
        artifact_note = "a result artifact (with the partial trace) was still written"
    else:
        # Carry the request into stats so even an early-failure artifact stays
        # discoverable-by-request / sortable in `feedback list` (#132).
        result = failed_result(task.id, f"{type(exc).__name__}: {exc}", request=task.instruction)
        original = exc
        # No partial result -> the trace is empty; don't claim otherwise.
        artifact_note = "a result artifact was still written"
    result.command = command_name
    # Mode (t7 / spec R3 / #256): recorded on the failure path too — a moded run
    # that raises still carries the mode that drove it.
    result.mode = mode
    # Lineage (#167): the failure path keeps it too — a continued run that
    # crashes still names what it was continuing.
    result.continued_from = continued_from
    if presence is not None:
        fold_presence_snapshot(result, presence, fold_chat=presence_fold_chat)
    work_span.set(status=result.status)
    write(result, artifact_dir(repo))
    # Best-effort: never mask the error.
    with suppress(Exception):
        set_last_work(repo, result.task_id)
    # A bare exception payload (e.g. KeyError('path') -> "'path'") tells the
    # operator nothing — name the exception class so the error is diagnosable
    # from the message alone (#269).
    detail = str(original)
    if not detail or not any(ch.isspace() for ch in detail):
        detail = f"{type(original).__name__}: {detail}".rstrip(": ")
    # #268 ask 3: an engine-failure abort must not strand the model's uncommitted
    # progress in the (about-to-be-removed) iso worktree. Commit it onto the
    # colleague/<id> branch — the same #222 sweep the signal and non-OK paths
    # already get — and point the operator at the surviving branch, so an
    # orchestrator can resume from the partial work instead of spelunking for it.
    wip_note = ""
    if _preserve_isolated_wip(worktree_path, f"engine failure: {detail[:80]}"):
        wip_note = f"; partial work preserved on branch {branch_name(task.id, task.instruction)}"
    return CliError(
        EXIT_ENV_ERROR,
        f"engine '{engine_name}' failed: {detail}",
        f"check the engine config / vLLM server; {artifact_note}{wip_note}",
        result=result if isinstance(partial, TaskResult) else None,
    )


def _arm_config_plane(
    config: EngineConfig, *, repo: Path, task: Task, engine_name: str
) -> "_ConfigPlaneState | None":
    """Construct the config plane and run its ``WINDOW_BEFORE_EPISODE_1``
    window — a strict no-op (returns ``None``) unless three-tier is armed
    (``config.worker is not None``: config.py's own resolution already made
    the worker role MANDATORY-if-armed, c25/h21, so this reads arming from
    the RESOLVED config rather than re-deriving it from the lobes gateway).

    The ONE construction site for a top-level task's lifecycle (h22): a
    standalone (non-chained) :func:`execute_work` call reaches this
    directly, before its own single dispatch; an armed ``--until-done``
    chain reaches it exactly once, from :func:`execute_work_chain`, before
    its FIRST episode dispatches — later episodes thread the SAME state via
    ``ChainEpisodeOptions.config_plane`` instead of calling this again.

    The lifecycle is attached to ``config.config_lifecycle`` BEFORE the
    window runs, so it is live (loop/engines will consume it) regardless of
    whether the configurator itself is armed. The configurator's OWN opt-in
    flag (:func:`colleague.configurator.configurator_enabled` — a SEPARATE
    default-off flag from ``three_tier`` itself) is resolved fresh here and
    passed as ``armed=`` to :func:`colleague.chain.run_configurator_window`,
    which is called UNCONDITIONALLY once three-tier is armed but is itself a
    strict no-op (``reviewed=False``, zero completions issued) when the
    configurator is off (acceptance criterion 2) — so the lifecycle is
    always constructed once three-tier is armed, independent of the
    configurator's own arming.

    The catalog is resolved from *repo* (the OPERATOR repo, not a per-episode
    isolated worktree) — deliberately symmetric with
    :func:`execute_work_chain`'s own arming call, which necessarily runs
    BEFORE any per-episode isolation exists. In practice this is the SAME
    tree an isolated episode's worktree checks out (role override files, if
    any, travel with the commit), so the resolved tool surface does not
    differ from what the engine itself later resolves off the isolated
    ``task.repo_path`` — documented here rather than left implicit.
    """
    if config.worker is None:
        return None
    from colleague import chain as chainmod
    from colleague.configevents import ConfigEventStream
    from colleague.configlifecycle import EpisodeConfigLifecycle
    from colleague.configurator import configurator_enabled
    from colleague.reviewinput import assemble_before_episode

    catalog = _build_capability_catalog(config, str(repo))
    lifecycle = EpisodeConfigLifecycle(catalog=catalog)
    stream = ConfigEventStream()
    config.config_lifecycle = lifecycle
    state = _ConfigPlaneState(lifecycle=lifecycle, stream=stream, catalog=catalog)

    window_result = chainmod.run_configurator_window(
        lifecycle,
        chainmod.WINDOW_BEFORE_EPISODE_1,
        armed=configurator_enabled(repo_path=repo),
        review_input=assemble_before_episode(task),
        catalog=catalog,
        stream=stream,
        config=config,
        engine_name=engine_name,
    )
    _accumulate_applied(state, window_result)
    return state


def _fold_config_plane(
    state: "_ConfigPlaneState", *, repo: Path, task_id: str, result: TaskResult
) -> None:
    """The cumulative fold (q2): land the combined config events on *result*
    AND rewrite the ALREADY-PERSISTED artifact — the ONE place both copies
    are kept in sync (acceptance criterion 3), mirroring
    :func:`colleague.artifact.update_config_events`'s own docstring ("the
    loop writes a work item's artifact exactly once, at run end ... the
    config-plane fold happens AFTER that").

    Crash-window honesty (acceptance criterion 3, stated here and pinned by
    a test): by the time this function runs, :func:`colleague.artifact.write`
    has ALREADY durably persisted *result*'s base shape (steps, usage,
    status, branch, everything) — this function only ever ADDS the
    ``config_events``/``config_digest`` keys via a REWRITE
    (:func:`colleague.artifact.update_config_events`). A process killed
    between ``result.config_events = events`` below and that rewrite
    finishing therefore loses AT MOST the events THIS window alone
    contributed — every EARLIER window's fold already landed durably on a
    PRIOR call to this same function (one per episode), so the loss is
    bounded to "the last window", never the whole audit trail.
    """
    from colleague.contract import config_digest_for

    events = _combined_config_events(state)
    result.config_events = events
    # ``config_digest`` is its OWN TaskResult field (not auto-derived by
    # to_dict()) — recomputed here from *events* alone, the same way
    # colleague.artifact.update_config_events recomputes it for the on-disk
    # copy, so the in-memory result and the rewritten artifact never
    # independently drift (both derive it from config_digest_for(events)).
    result.config_digest = config_digest_for(events)
    update_config_events(repo, task_id, events)


def _build_run_presence(
    *, task: Task, config: EngineConfig, engine, external_sink
) -> "tuple[object | None, bool]":
    """Build the run's presence engine, if any — ``(presence, foreground)``.

    The presence-builder half of :func:`execute_work` (extracted for the S3776
    budget, the ``_preserve_isolated_wip`` precedent). Skipped entirely when an
    external ``progress_sink`` was supplied (the interactive ``session`` already
    runs its own middle-manager lane — wiring a second engine would double every
    ack/update). Otherwise the watched builder is tried first, then the
    foreground sibling — the two are gated on ``task.watch`` in opposite
    directions, so at most one returns non-None. ``foreground`` is ``True`` only
    for a one-shot (non-watched) presence, whose chat must be folded from the
    snapshot (no flight plane exists to carry it). Both builds ride
    ``suppress``: narration must never break cortex.
    """
    if external_sink is not None:
        return None, False
    presence = None
    with suppress(Exception):
        presence = build_watch_presence(task=task, config=config, engine=engine)
    if presence is not None:
        return presence, False
    with suppress(Exception):
        presence = build_foreground_presence(
            task=task, config=config, engine=engine, render=emit_diagnostic
        )
        return presence, presence is not None
    return None, False


def _arm_delegation(config: EngineConfig, task: Task) -> None:
    """Build this run's subagent spawn callbacks onto *config* (t6).

    Stays in THIS module deliberately: ``make_spawn``/``make_batch_spawn`` are
    monkeypatched as ``work_mod.make_spawn``/``work_mod.make_batch_spawn``
    (``tests/test_subagent_budget.py``), and a bare-name call only sees those
    patches while the call site is textually here.

    Built once so both ``work`` and ``session``, and every backend (which
    forwards ``config.subagent_spawn``), delegate identically. Depth defaults
    to 1; the launcher binds each child to depth+1, so recursion is bounded by
    ``MAX_SUBAGENT_DEPTH``. ONE shared agent budget is threaded into BOTH
    callbacks so the global ``MAX_SUBAGENT_TOTAL`` cap is actually enforced
    across single + batch + nested delegation (#t4 Q3 wiring fix).
    ``parent_task_id=task.id`` (spec R6 / plan t16 / #259) records THIS work
    item's id on every direct child's ``SubResult.parent``, so a subagent tree
    is walkable from artifacts alone. ``parent_profile`` (#411 t14) — the
    parent's own purpose, recorded on every delegate event — is passed ONLY
    when the ``agents`` mode is armed, so the unarmed calls are
    byte-identical to today.
    """
    # Reasoning sidecar (effort-v4 t6, h20): children tag their sidecars to the
    # OPERATOR repo (the #310 flight-plane precedent — ``task`` here is
    # post-isolation, so ``flight_repo_path`` names the operator repo when the
    # run is worktree-isolated). Attached as a dynamic config attr (the
    # ``agents_ledger_path`` precedent) so ``run_subagent`` can reach it
    # through the spawn closures without a signature change.
    config.reasoning_repo_path = task.flight_repo_path or task.repo_path
    budget = new_agent_budget(config)
    spawn_kwargs: dict = {"counter": budget, "parent_task_id": task.id}
    parent_profile = default_parent_profile(config)
    if parent_profile is not None:
        spawn_kwargs["parent_profile"] = parent_profile
    config.subagent_spawn = make_spawn(task.repo_path, config, task.engine, **spawn_kwargs)
    config.subagent_batch_spawn = make_batch_spawn(
        task.repo_path, config, task.engine, **spawn_kwargs
    )


def _drive_engine(
    *,
    engine,
    setup: _RunSetup,
    repo: Path,
    engine_name: str,
    config: EngineConfig,
    command_name: str | None,
    mode: str | None,
    continued_from: str | None,
    work_span,
    presence: "object | None",
    presence_foreground: bool,
    cockpit_sink: "object | None",
) -> TaskResult:
    """Run the model-driving loop under the rig slot; raise on engine failure.

    Stays in THIS module deliberately: ``tests/test_timeout_survival.py``
    string-splits this file's source on the engine-failure helper's own ``def``
    line and on the broad ``except`` line below, then asserts the except body
    up to the next ``finally:`` routes into that helper with the worktree in
    hand. Quoting either literal here would move the split point, so this
    docstring names them only descriptively.

    Rig-level cooperative concurrency budget (t13 / spec R5 / #258): hold ONE
    slot for the whole model-driving loop, so concurrent TOP-LEVEL work items
    sharing this repo's endpoint serialize to the operator's declared width
    instead of starving each other toward the timeout (#239's interference
    class). Deliberately NOT taken per subagent child: a parent holding a slot
    would starve its own children (deadlock-by-composition) — in-run fan-out is
    already budgeted by width-scaled child budgets (t12) + the backpressure
    throttle (t6). Strict no-op without ``.colleague/rig.json``; degrades OPEN
    after the wait cap (an advisory backstop, never a wedge).
    """
    worktree_path = setup.worktree_path
    try:
        with rig.rig_slot(repo, on_wait=emit_diagnostic):
            return engine.work(setup.task, config)
    except Exception as exc:  # noqa: BLE001 - any failure still writes an artifact (h5)
        raise _engine_failure_error(
            exc,
            task=setup.task,
            repo=repo,
            engine_name=engine_name,
            command_name=command_name,
            continued_from=continued_from,
            mode=mode,
            work_span=work_span,
            worktree_path=worktree_path,
            presence=presence,
            presence_fold_chat=presence_foreground,
        ) from exc
    finally:
        # Close the live cockpit on every exit path (success or engine
        # failure) so the final frame shows the work item as finished. Best-
        # effort: a render glitch must never mask the real outcome.
        if cockpit_sink is not None:
            with suppress(Exception):
                cockpit_sink.close()


def execute_work(
    *,
    repo: Path,
    engine_name: str,
    task: Task,
    open_pr: bool,
    base: str,
    config: EngineConfig,
    allow_dirty: bool = False,
    isolate: bool = False,
    command_name: str | None = None,
    display: "DisplayOptions | None" = None,
    mode: str | None = None,
    continued_from: str | None = None,
    chain: "ChainEpisodeOptions | None" = None,
) -> tuple[TaskResult, Path]:
    """Shared work orchestration: load engine → loop → handoff → write artifact.

    This helper is the single implementation of the work path.  Both
    :func:`cmd_work` and the ``session`` palette call it so the loop, hooks,
    and artifact logic are never duplicated (honesty condition h11).

    Parameters
    ----------
    repo:
        Absolute path to the target repository.
    engine_name:
        Name of the backend plugin to load (e.g. ``"mock"``).
    task:
        A fully constructed :class:`~colleague.contract.Task`.
    open_pr:
        When ``True`` attempt to push and open a PR; ``False`` commits locally only.
    base:
        Base branch for the PR (passed to :func:`~colleague.handoff.handoff`).
    config:
        Resolved :class:`~colleague.config.EngineConfig`.
    allow_dirty:
        When ``False`` (the default) the work path refuses to run against a
        repo with uncommitted tracked changes — the handoff would otherwise
        sweep them onto the work branch (#149). ``True`` opts in to that.
    command_name:
        Originating command-template name (``None`` for a plain instruction).
        Recorded on the result before *every* artifact write — including the
        failure path — so the run report never loses the origin (R5 / c12).
    display:
        The bundled cockpit/TUI display knobs (:class:`DisplayOptions` —
        ``tui`` live-cockpit activation #74 A1, ``tui_events`` WorkStep-JSONL
        path #74 A3, ``sink`` the caller-supplied cockpit sink #74 A2 — the
        interactive ``session`` binds one to its own `CockpitState` +
        frame-writer so a work item renders into the session's one shared
        screen, replacing the auto-constructed cockpit); ``None`` (default)
        means every knob at its ``None`` default, byte-identical to the
        pre-bundle behavior.
    continued_from:
        The prior work item's task id when this run CONTINUES it (#167), else
        ``None``. Recorded on the result before every artifact write — the
        one-way lineage the continue path (``work --continue`` / session
        ``/continue``) stamps; omit-when-None keeps ordinary runs byte-identical.
    mode:
        Constraint-profile mode (t3 / spec R1 / #254). When set, the mode's
        profile (``colleague.profiles`` + operator overlays) fills the
        constraint knobs the operator left untouched, via
        :func:`colleague.config.apply_mode_profile` — the ONE code path shared
        by the ``work --mode`` flag and the session's mode selection. ``None``
        (the default) is a strict no-op (byte-identical config). Also recorded
        on ``result.mode`` before *every* artifact write — including the failure
        path — mirroring ``command_name`` above (t7 / spec R3 / #256); omitted
        from the serialized artifact when ``None``.
        The caller's explicit CLI knobs travel on ``config.explicit_knobs``
        (a runtime-only EngineConfig field, the ``role`` precedent) — those
        are never overwritten by the mode profile (precedence h1).
    chain:
        Set (a :class:`ChainEpisodeOptions`) exactly when this run is ONE
        EPISODE of an armed ``--until-done`` chain (indefinite-run t5):
        ``base_ref`` bases the isolation worktree on the prior episode's
        branch tip (tree carry, c6), and the running :class:`ChainView` is
        accumulated onto ``result.chain`` before the artifact write (c20).
        A chained episode also SKIPS the mode-profile application here — the
        chain loop applied it once at arming, so a mid-chain overlay-file
        change is never re-read (inheritance c28). ``None`` (the default,
        every non-chain caller) is byte-identical to the pre-chain behavior.

    Returns
    -------
    tuple[TaskResult, Path]
        The task result and the path of the written artifact JSON.

    Raises
    ------
    :class:`~colleague.cli._errors.CliError`
        On unknown engine or engine-level failure (artifact is still written
        before the exception is raised — honesty h5).
    """
    display = display or DisplayOptions()
    # Work-start auto-trigger (self-learning t12 AC3, c18/h15): colleague's own
    # action — this work item starting — is a trigger too, not just a grade.
    # Best-effort, read-only-first, and fully swallowed: a detection/capture
    # failure here must never keep THIS work item from starting. Targets the
    # OPERATOR repo (`repo`, not an isolation worktree that gets reaped).
    with suppress(Exception):
        capture_uncaptured_predecessor(repo)
    # Mode-profile layer (t3 / R1 / #254): fill profile defaults for knobs the
    # operator left untouched, BEFORE anything reads the config. One code path
    # for every entry door. A chained episode (indefinite-run c28) arrives with
    # the profile ALREADY applied once by the chain loop; re-applying here would
    # re-read the mode overlay files mid-chain, so an episode could silently run
    # under a config the operator changed after arming — what c28 forbids.
    if chain is None:
        config = _moded_config(config, mode, repo)

    try:
        engine = registry.load(engine_name)
    except registry.UnknownEngine as exc:
        raise CliError(
            EXIT_USER_ERROR, str(exc), "list engines with: colleague backends list"
        ) from exc

    # Config-plane arming (change-content consumption lane, t9): a chained
    # episode's state was already constructed ONCE by execute_work_chain
    # (h22 — one lifecycle per top-level task) and rides `chain.config_plane`;
    # a standalone call arms its OWN state here. Both are a strict no-op
    # (`config_plane` stays None) unless three-tier is armed.
    config_plane = _resolve_config_plane(
        chain, config, repo=repo, task=task, engine_name=engine_name
    )
    setup = _prepare_run(
        repo=repo,
        task=task,
        config=config,
        allow_dirty=allow_dirty,
        isolate=isolate,
        chain=chain,
        command_name=command_name,
        mode=mode,
        continued_from=continued_from,
    )
    task = setup.task

    # Telemetry: the root span wraps engine.work() + handoff() + the artifact write, so
    # the loop's tool spans nest under it. A no-op unless telemetry is enabled.
    # The same shared path serves `work` and `session`, so both are instrumented.
    telemetry = load_telemetry()
    try:
        with telemetry.work_span(
            task_id=task.id,
            engine=engine_name,
            model=config.model,
            max_steps=config.max_steps,
        ) as work_span:
            trace_id = telemetry.trace_id_hex()
            if trace_id:
                emit_diagnostic(f"trace: {trace_id}")

            _announce_flight(task, repo, display.sink)

            # Snapshot untracked files BEFORE the work item so the handoff stages only
            # the files the work item itself produces — never pre-existing operator
            # work-in-progress (#39), with a live --tui-events stream registered as
            # baseline (#74 A3).
            baseline_untracked = _baseline_untracked_for(setup.work_repo, repo, display.tui_events)
            cockpit_sink = _arm_progress_sink(
                config=config, task=task, engine_name=engine_name, display=display
            )
            presence, presence_foreground = _build_run_presence(
                task=task, config=config, engine=engine, external_sink=display.sink
            )
            if presence is not None:
                with suppress(Exception):
                    presence.acknowledge(ack_packet_for_task(task))
                config.progress = compose_presence_sink(config.progress, presence)
            _arm_delegation(config, task)
            result = _drive_engine(
                engine=engine,
                setup=setup,
                repo=repo,
                engine_name=engine_name,
                config=config,
                command_name=command_name,
                mode=mode,
                continued_from=continued_from,
                work_span=work_span,
                presence=presence,
                presence_foreground=presence_foreground,
                cockpit_sink=cockpit_sink,
            )

            # Fold the presence engine's cost/injection records onto the artifact
            # (t9) — every non-raising exit (OK/INCOMPLETE/ERROR), so an
            # unattended watched run still records what it cost regardless of
            # whether an operator ever attaches via `colleague talk`.
            if presence is not None:
                fold_presence_snapshot(result, presence, fold_chat=presence_foreground)

            _finalize_run_outcome(
                result=result,
                read_only_role=setup.read_only_role,
                work_repo=setup.work_repo,
                task=task,
                baseline_untracked=baseline_untracked,
                open_pr=open_pr,
                base=base,
                telemetry=telemetry,
                base_sha=setup.base_sha,
                worktree_path=setup.worktree_path,
                chain=chain,
            )

            work_span.set(
                status=result.status,
                step_count=len(result.steps),
                pr_url=result.pr_url,
            )
            _stamp_run_metadata(
                result,
                config=config,
                command_name=command_name,
                mode=mode,
                continued_from=continued_from,
                chain=chain,
            )
            artifact_path = write(result, artifact_dir(repo))
            # The cumulative config-plane fold (t9, acceptance criterion 3):
            # AFTER the base artifact is durably written, land the combined
            # config events on `result` AND rewrite the just-written artifact
            # so the two copies never drift (see _fold_config_plane's own
            # docstring for the crash-window honesty this ordering buys).
            # A strict no-op (config_plane is None) unless three-tier armed.
            if config_plane is not None:
                _fold_config_plane(config_plane, repo=repo, task_id=result.task_id, result=result)
            # Record this as the repo's most recent work item so `colleague feedback
            # last` resolves to it. Best-effort: a pointer write must never break
            # a successful work item.
            with suppress(Exception):
                set_last_work(repo, result.task_id)
            return result, artifact_path
    finally:
        # Restore the operator's prior signal disposition (#222) before teardown, so
        # the interrupt-commit handler is never left armed past this work item.
        setup.restore_signals()
        telemetry.flush()
        # A staged continuation warning belongs to THIS run only. On the happy
        # path _stamp_run_metadata already drained it; if _drive_engine raised,
        # clear it here so a long-lived session config never stamps a stale
        # warning onto an unrelated later run (review-2 finding, c32/h19).
        if getattr(config, "continuation_warnings", None):
            with suppress(Exception):
                config.continuation_warnings = []
        # Tear down the isolation worktree on every exit path (success, engine
        # failure, handoff error), KEEPING its colleague/<id> branch — the branch
        # is the deliverable the operator merges; only the working dir is disposable.
        # On an interrupt the WIP is already committed to that branch (the handler /
        # the cooperative-stop path above), so removing the working dir loses nothing.
        if setup.worktree_path is not None:
            with suppress(Exception):
                worktrees.isolation_worktree_remove(str(repo), setup.worktree_path)


def cmd_work(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))

    # Decorative startup banner — interactive TTY only, suppressed in --json so
    # neither stdout (the result stream) nor agent-parsed stderr is polluted (issue #15).
    emit_banner(emit_diagnostic, json_mode=json_mode)

    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        raise CliError(
            EXIT_USER_ERROR,
            f"repo path is not a directory: {args.repo}",
            "pass --repo pointing at an existing repository",
        )

    # Resolve the engine: explicit --engine > COLLEAGUE_ENGINE > vllm-openai.
    # A bare work item never silently falls through to the no-op mock (#53).
    engine = resolve_engine(args.engine)

    config = EngineConfig.resolve(
        base_url=args.base_url,
        model=model_arg(args),
        api_key=args.api_key,
        max_steps=args.max_steps,
        repo_path=repo,
    )
    rc = maybe_list_and_apply(args, config, repo, json_mode=json_mode)  # qwen-direct t6
    if rc is not None:
        return rc

    config.role = getattr(args, "role", None)

    # --cortex-only (t8): null the senses seat for this run; no-op when unresolved.
    if getattr(args, "cortex_only", False):
        config.senses = None

    # Mode validation (t3): fail loudly + early on a typo (the --algo idiom);
    # explicit CLI knobs ride config.explicit_knobs so the profile never wins.
    mode = _validated_mode(getattr(args, "mode", None))
    if args.max_steps is not None:
        config.explicit_knobs = frozenset({"max_steps"})

    _apply_lint_optout(args, config)
    _apply_coherence_optout(args, config)
    _apply_affected_tests_optout(args, config)

    command_name: str | None = getattr(args, "command_name", None)
    task = _build_task(args, repo, engine, config)

    # Background one-shot child (t12, spec R4 / h10): when this process IS the
    # detached child, COLLEAGUE_BACKGROUND_ID carries the handle id the parent
    # pre-minted, so the child's artifact/flight/logs are all findable from the
    # SAME id the parent printed in its start payload. A strict no-op for every
    # ordinary invocation — the env var is only ever set by
    # background.spawn_background, and only in the child's own environment.
    bg_id = os.environ.get(background.BACKGROUND_ID_ENV)
    if bg_id:
        task.id = bg_id

    if getattr(args, "background", False):
        # Detach and return immediately — never runs the loop in this process.
        return _cmd_work_background(args, repo, json_mode)

    _arm_watch(args, task, config)

    # Episode chaining (indefinite-run t5): an armed run (--until-done, or
    # until_done via COLLEAGUE_UNTIL_DONE / config.json — c21) dispatches
    # through the chain loop, which owns handoff-once (c26) and verbatim
    # inheritance (c28). An unarmed run takes the single-episode path below,
    # byte-identical to today.
    _, chain_armed = _resolve_chain_arming(args, config)
    if chain_armed:
        return _run_chain(
            args, repo, engine, config, task, command_name=command_name or None, mode=mode
        )

    # Delegate the full work orchestration to the shared helper, which records
    # the originating command on the result before every artifact write.
    try:
        result, artifact_path = execute_work(
            repo=repo,
            engine_name=engine,
            task=task,
            open_pr=not args.no_pr,
            allow_dirty=getattr(args, "allow_dirty", False),
            # `colleague work`/`drive` (and `ask-colleague write --apply`) ALWAYS
            # run worktree-isolated, so the result lands on colleague/<id> and the
            # operator's tree/branch are never touched (#196/#201). `session` keeps
            # its in-place interactive path (it calls execute_work without isolate).
            isolate=True,
            base=args.base,
            config=config,
            command_name=command_name or None,
            display=DisplayOptions(
                tui=getattr(args, "tui", None),
                tui_events=getattr(args, "tui_events", None),
            ),
            mode=mode,
            continued_from=getattr(args, "_continued_from_resolved", None),
        )
    except CliError as exc:
        # On a partial-bearing failure, surface the preserved partial TaskResult to
        # stdout (--json only) so machine consumers (e.g. ask-colleague.sh) can parse it.
        # The diagnostic stays on stderr and the exit code stays non-zero — both are
        # handled by the _dispatch layer that catches this re-raise.
        if json_mode and exc.result is not None:
            emit_result(exc.result.to_dict(), json_mode=True)
        raise

    return _emit_work_outcome(result, engine, artifact_path, json_mode)


def _add_work_parser(sub: argparse._SubParsersAction, name: str, *, help_text: str) -> None:
    p = sub.add_parser(name, help=help_text)
    _configure_work_parser(p)
    p.set_defaults(func=cmd_work)


def register(sub: argparse._SubParsersAction) -> None:
    _add_work_parser(sub, "work", help_text=_WORK_HELP)
    # Deprecated alias of `work` (the old car-themed verb), kept for
    # back-compatibility. Labelled in --help so the surface nudges toward `work`.
    _add_work_parser(sub, "drive", help_text="Deprecated alias of 'colleague work'.")


def register_into(app) -> None:
    """Register ``work`` (deprecated alias ``drive``) as an agentfront host command.

    ``work`` is deliberately NOT a rendered registry tool. It owns CLI-specific
    semantics the agentfront tool dispatch (return-value → ``emit_result``, exit
    always 0; raise → structured error) cannot express:

    * **custom exit codes with the result still on stdout** — ``0`` on ``OK``,
      ``2`` on ``INCOMPLETE`` (#192, a load-bearing contract a caller branches
      on), ``1`` on a soft error — none of which a "return a value, exit 0" tool
      can produce;
    * a streamed per-step progress feed + an interactive banner;
    * its own ``--json`` ``TaskResult`` emission (a tool func never receives
      ``json_mode``).

    So it is registered as a **host command**, reusing :func:`cmd_work`'s
    ``(args) -> int`` handler verbatim (agentfront's ``_dispatch`` still gives it
    the ``AgentfrontError`` → structured-stderr + no-traceback wrapper, and a
    :class:`~colleague.cli._errors.CliError` is an ``AgentfrontError`` subclass).
    The ``drive`` alias rides along on the same handler + configure.
    """
    app.add_command(
        "work",
        cmd_work,
        help=_WORK_HELP,
        configure=_configure_work_parser,
        aliases=("drive",),
    )

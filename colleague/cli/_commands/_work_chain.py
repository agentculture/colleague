"""The ``--until-done`` episode-chain lane for ``colleague work``.

Split out of ``colleague/cli/_commands/work.py`` (the 1000-line hard limit,
plan ``hard-1000-line-file-limit`` t16). ``work.py`` re-exports
``execute_work_chain`` / ``_resolve_chain_arming`` / ``ChainEpisodeOptions``,
so ``session.py``'s three import shapes resolve unchanged.

**Why the two call-backs into ``work`` are LAZY module-attribute lookups.**
``execute_work_chain`` dispatches each episode through ``execute_work`` and
arms the config plane through ``_arm_config_plane`` — both of which live in
``work.py`` (``execute_work`` because ``load_telemetry``/``make_spawn``/
``make_batch_spawn`` are monkeypatched on that module and a bare-name call
resolves through the ``__globals__`` of the module it is textually defined in;
``_arm_config_plane`` because it holds the pinned ``config.config_lifecycle``
assignment). A ``from ... import execute_work`` here would (a) be a circular
import and (b) silently defeat ``monkeypatch.setattr(work_mod,
"execute_work", ...)`` — the patch would stay green while intercepting
nothing. Looking the names up as attributes of the ``work`` MODULE at call
time keeps both patches effective; ``tests/test_chain_e2e.py`` (which spies on
``work_mod.execute_work`` and asserts it saw both episodes) is the proof.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path

from colleague import flight
from colleague.artifact import artifact_dir, find_artifact, read_chain_view, write
from colleague.cli._commands._tui_sink import CockpitProgressSink
from colleague.cli._commands._work_configplane import (
    _ConfigPlaneState,
    _run_between_episodes_window,
)
from colleague.cli._commands._work_support import (
    _READ_ONLY_MODES,
    DisplayOptions,
    Lineage,
    _emit_work_outcome,
    _moded_config,
)
from colleague.cli._errors import CliError
from colleague.cli._output import emit_diagnostic, emit_result
from colleague.config import EngineConfig
from colleague.contract import ChainView, Task, TaskResult
from colleague.handoff import (
    branch_name,
    chain_handoff_finalize,
    commits_ahead,
    head_sha,
    reap_chain_intermediates,
)
from colleague.roles import is_read_only


@dataclass(frozen=True)
class ChainEpisodeOptions:
    """Per-episode chain-dispatch knobs (indefinite-run t5) — the S107-safe
    bundle (the :class:`DisplayOptions` precedent). Non-``None`` exactly when
    :func:`execute_work` is dispatched by the ``--until-done`` chain loop
    (:func:`_run_chain`); ``None`` (every other caller) is byte-identical to
    the pre-chain behavior."""

    #: The prior episode's ``colleague/<id>`` branch — episode N+1's worktree
    #: base (tree carry, c6/h6). ``None`` on the chain's first episode.
    base_ref: str | None = None
    #: The chain view stamped on the PRIOR episode's artifact (``None`` on the
    #: first episode); this episode's ``result.chain`` accumulates onto it
    #: (sums of per-episode exact usage, c20/h19).
    prior_view: ChainView | None = None
    #: The UNION of every prior episode's ``result.changed_files`` so far
    #: (sorted, deduped) — ``()`` on the chain's first episode. Accumulated by
    #: :func:`execute_work_chain`'s loop and threaded by :func:`execute_work`
    #: into :class:`~colleague.loop.ContextControls.chain_prior_changed`
    #: (indefinite-run follow-up, issue #335, decision c22). Read by the NEXT
    #: task's gate-skip guard — dormant plumbing here.
    prior_changed: tuple[str, ...] = ()
    #: The whole top-level task's shared config-plane state (change-content
    #: consumption lane, plan task t9 — h22). Constructed ONCE by
    #: :func:`execute_work_chain` when three-tier is armed and threaded to
    #: EVERY episode, so each episode's fold sees the SAME
    #: lifecycle/stream/accumulated-applied-units. ``None`` for an unarmed
    #: chain (byte-identical) — a standalone (non-chained) call to
    #: :func:`execute_work` never reads this field; it arms its OWN state via
    #: :func:`_arm_config_plane` instead.
    config_plane: "_ConfigPlaneState | None" = None


def _arm_chain_dispatch(config: EngineConfig, chain: "ChainEpisodeOptions | None") -> str | None:
    """Stamp the chain-episode dispatch marker; return the episode base_ref (#335, c22).

    Keyed on ``chain``'s PRESENCE for THIS call, never on ``config.until_done``
    — set unconditionally (including the ``False``/``()`` branch) so a config
    object reused across dispatches (the session's one long-lived
    ``EngineConfig``) never leaks a prior chained call's marker onto a later
    unchained one. A subagent child never sees a ``True`` value regardless:
    ``run_subagent`` resets both fields on the child config it builds via
    ``dataclasses.replace``. Returns ``chain.base_ref`` (the prior episode's
    ``colleague/<id>`` tip, c6) for :func:`_setup_isolation`, ``None`` for an
    unchained dispatch or the chain's first episode. Extracted from
    :func:`execute_work` to keep its cognitive complexity under the S3776
    ceiling (the :func:`_moded_config` precedent; PR #338 Sonar catch).
    """
    config.chain_episode = chain is not None
    if chain is None:
        config.chain_prior_changed = ()
        return None
    config.chain_prior_changed = chain.prior_changed
    return chain.base_ref


def _resolve_chain_arming(args: argparse.Namespace, config: EngineConfig) -> tuple[int, bool]:
    """Resolve the ``(cap, armed)`` chain pair — the standard knob precedence (c21).

    Explicit flag > env > config.json > default: the env/config.json legs were
    already folded into ``EngineConfig.resolve`` by t3
    (``COLLEAGUE_UNTIL_DONE`` / ``COLLEAGUE_MAX_EPISODES`` →
    ``config.until_done`` / ``config.max_episodes``), so this only lets the
    explicit CLI flags win last — the ``max_steps`` idiom. ``--until-done``
    is arm-only (a bare switch, no ``--no-until-done``), so a config-armed
    chain stays armed. Cap ``0`` (or negative) means unlimited.
    """
    armed = bool(getattr(args, "until_done", False)) or bool(getattr(config, "until_done", False))
    explicit_cap = getattr(args, "max_episodes", None)
    cap = explicit_cap if explicit_cap is not None else int(getattr(config, "max_episodes", 5))
    return cap, armed


def _chain_should_start_next(
    repo: Path,
    result: TaskResult,
    state,
    *,
    progressed: bool | None,
    watch: bool,
    agents_armed: bool = False,
) -> tuple[tuple[str, str] | None, "object"]:
    """Decide the chain's move at ONE episode boundary — the t6 extension seam.

    Everything that happens BETWEEN two episodes funnels through here, in
    order: (1) the pure verdict — ok-guard, continuable allow-list,
    no-progress guard, episode cap (:func:`colleague.chain.should_continue`);
    (2) the between-episode pilot stop (t6): on a WATCHED chain, read the
    JUST-FINISHED episode's flight control — the pilot's live handle — and
    halt (reason :data:`~colleague.chain.HALT_PILOT_STOP`) when a cooperative
    ``stop`` landed in the boundary window, so a stop never dispatches another
    episode (an unwatched chain ignores it, matching the in-episode unwatched
    semantics; :func:`colleague.flight.read_stop` is a pure peek — absent
    control file = no stop); (3) the continuation seed resolution (the
    ok-guard and wrong-run guard live inside
    :func:`~colleague.continuation.resolve_continuation`, wrapped by
    :func:`~colleague.chain.resolve_chain_seed` so a ``ContinuationError`` is
    a clean halt, never a crash).

    Returns ``(seed, verdict)``: ``seed`` is ``(prior_task_id, seed_text)``
    when episode N+1 may dispatch, else ``None``; ``verdict`` is the
    :class:`~colleague.chain.ChainVerdict` that decided it (the halt reason,
    or the continuable exit reason on a go).
    """
    # Lazy import: the chain path is opt-in; keep work's import graph flat.
    from colleague import chain as chainmod

    verdict = chainmod.should_continue(
        result, state.episode_count, state.cap, progressed=progressed
    )
    if not verdict.should_continue:
        return None, verdict
    if watch and flight.read_stop(repo, result.task_id):
        return None, chainmod.ChainVerdict(
            should_continue=False,
            reason=chainmod.HALT_PILOT_STOP,
            detail=(
                f"pilot stop on {result.task_id}'s flight control — episode "
                f"{state.episode_count + 1} was never dispatched"
            ),
        )
    warnings: list[dict] = []
    seed, halt = chainmod.resolve_chain_seed(
        repo, result.task_id, agents_armed=agents_armed, warnings=warnings
    )
    for warning in warnings:
        emit_diagnostic(f"continuation: {warning['detail']}")
    if halt is not None:
        return None, halt
    return seed, verdict


def _chain_finalize(
    repo: Path,
    result: TaskResult,
    episode_branches: list[str],
    *,
    instruction: str,
    open_pr: bool,
    base: str,
    pr_body: str | None = None,
) -> Path:
    """The chain's ONE handoff + intermediate reap, on a COMPLETED chain (c26).

    Every episode ran with push/PR suppressed, so this performs the arming
    invocation's handoff choice exactly once: push the FINAL episode's branch
    — which carries the cumulative diff, because each episode based its
    worktree on the prior tip — and open the single PR
    (:func:`~colleague.handoff.chain_handoff_finalize`, gated by the same h7
    predicate as any handoff; ``--no-pr``/no remote/no ``gh`` stays local).
    The final artifact is re-written so it records the REAL ``pr_url``/push
    outcome — never a synthesized one (the #167-arc rule); the rewrite hits
    the same path (same task id + request slug).

    Then the intermediate ``colleague/<id>`` branches are reaped
    (:func:`~colleague.handoff.reap_chain_intermediates` — ancestors of the
    kept final branch only, so a degraded-base episode's unique work is never
    destroyed; artifacts keep the evidence). A HALTED chain never reaches
    this function — every branch is left for the operator (the WIP rule).
    """
    final_branch = episode_branches[-1]
    # ``pr_body`` (#340 b3): the gate-deferral warning rides the PR body so the
    # human reviewer at gate 3 sees it; None keeps the --fill body byte-identical.
    outcome = chain_handoff_finalize(
        repo,
        result.task_id,
        final_branch,
        instruction=instruction,
        open_pr=open_pr,
        base_branch=base,
        body=pr_body,
    )
    result.branch = outcome.branch
    if outcome.pr_url:
        result.pr_url = outcome.pr_url
    if outcome.tip_sha:
        result.tip_sha = outcome.tip_sha
    if outcome.note:
        emit_diagnostic(f"chain handoff: {outcome.note}")
    artifact_path = write(result, artifact_dir(repo))
    reaped = reap_chain_intermediates(repo, episode_branches[:-1], keep=final_branch)
    reaped_refs = [r["ref"] for r in reaped if r["action"] == "reaped"]
    if reaped_refs:
        emit_diagnostic(
            f"chain: reaped {len(reaped_refs)} intermediate branch(es): " + ", ".join(reaped_refs)
        )
    return artifact_path


def _chain_progress(
    repo: Path,
    result: TaskResult,
    state,
    *,
    read_only: bool,
    prior_ref: str,
    episode_branch: str,
) -> bool | None:
    """The no-progress guard's evidence for one episode (c22) — deterministic.

    Feeds :func:`colleague.chain.episode_progressed` exactly two signals:

    - ``new_commits`` — ``git rev-list --count <prior_ref>..<episode_branch>``
      (:func:`~colleague.handoff.commits_ahead`), where ``prior_ref`` is the
      prior episode's branch (or the chain-start HEAD sha for episode 1); a
      budget-exhausted episode's WIP commit (#222) counts here.
    - ``new_evidence`` — :meth:`~colleague.chain.ChainState.record_episode`'s
      verdict: a changed-file path from this episode's artifact that no prior
      episode reported.

    ``record_episode`` is called for EVERY episode (it also keeps the chain's
    episode ledger). A read-only role returns ``None`` — commits and changed
    files are structurally impossible for it, so the c22 evidence inputs
    cannot apply; the episode cap bounds a read-only chain instead.
    """
    new_evidence = state.record_episode(result.task_id, result.changed_files)
    if read_only:
        return None
    new_commits = commits_ahead(repo, prior_ref, episode_branch)
    # Lazy import mirrors _chain_should_start_next (opt-in chain path).
    from colleague import chain as chainmod

    return chainmod.episode_progressed(new_commits=new_commits, new_evidence=new_evidence)


def _announce_episode_transition(
    repo: Path, prior_id: str, next_id: str, state, watch: bool
) -> None:
    """Announce one chain hop (t6) — sink line + the flight transition marker.

    Extracted from :func:`execute_work_chain` for the S3776 budget. The
    announcement rides the #38 progress channel; the marker lands on the PRIOR
    episode's flight feed (type="episode-transition", best-effort, watch-gated
    like every flight write) so a pilot following episode 1 can locate every
    later episode. Announcement text and marker intent are the same string.
    """
    announcement = flight.transition_announcement(prior_id, state.episode_count + 1, state.cap)
    emit_diagnostic(f"chain: {announcement}")
    if watch:
        flight.append_episode_transition(
            repo,
            prior_id,
            next_task_id=next_id,
            episode_index=state.episode_count + 1,
            cap=state.cap,
        )


def _resolve_deferred_branch(repo: Path | None, task_id: str) -> str | None:
    """A deferred episode's WIP branch, read from its own artifact (best-effort).

    An INHERITED deferred id — a chain resumed via ``--continue`` carries the
    cut run's ``deferred_gate_episodes`` forward (``ChainView.accumulate``) —
    has no entry in the resumed invocation's id→branch map; its branch lives
    only on the episode's persisted artifact (``branch``, recorded when the
    #222 WIP sweep preserved a chained episode's work — see
    :func:`_preserve_non_ok_wip`). Any failure — no repo threaded, artifact
    gone, corrupt JSON, a null field (a pre-fix or no-WIP episode) — returns
    ``None``; the caller renders the explicit unresolved marker instead, never
    a silently shorter branch list (Qodo, PR #345).
    """
    if repo is None:
        return None
    path = find_artifact(repo, task_id)
    if path is None:
        return None
    try:
        branch = json.loads(path.read_text(encoding="utf-8")).get("branch")
    except (OSError, json.JSONDecodeError):
        return None
    return branch if isinstance(branch, str) and branch else None


def _emit_chain_outcome(
    verdict,
    state,
    *,
    completed: bool,
    branches: list[str],
    deferred: tuple[str, ...] = (),
    repo: Path | None = None,
) -> None:
    """The chain's terminal diagnostics (extracted for the S3776 budget).

    ``deferred`` is the chain's accumulated deferred-gate episode ids
    (``ChainView.deferred_gate_episodes``, the #341 typed record — never
    parsed out of ``capacity_warning``). A HALTED chain names the deferring
    episodes and their kept WIP branches (#341: the per-episode note alone
    left ungated WIP silent at the outcome level); a deferred id the current
    invocation didn't run (a ``--continue`` resumed chain inherits the cut
    run's deferrals) resolves its branch from the episode's own artifact via
    *repo* (optional — absent keeps other callers working), and an id still
    unresolved is marked ``(branch not resolved)`` explicitly — the line never
    silently claims the branch list is complete when it is not (Qodo,
    PR #345). A COMPLETED chain warns only when the FINAL episode deferred —
    the one ok-finish + declared fill-line handoff shape whose handoff fires
    ungated (#340 b1); every other completed chain re-gated the union on its
    final episode, so it renders byte-identically to today.
    """
    detail = f": {verdict.detail}" if verdict.detail else ""
    emit_diagnostic(
        f"chain: {'completed' if completed else 'halted'} after "
        f"{state.episode_count} episode(s) — {verdict.reason}{detail}"
    )
    if not completed and branches:
        emit_diagnostic("chain: episode branches kept (WIP): " + ", ".join(branches))
    if not deferred:
        return
    if completed:
        final_id = state.episode_ids[-1] if state.episode_ids else ""
        if final_id and final_id in deferred:
            emit_diagnostic(
                "chain: WARNING — chain completed and handed off with the final "
                f"episode's pre-finish gates deferred ({final_id}; ok-finish + "
                "declared fill-line handoff, #340)"
            )
        return
    id_to_branch = dict(zip(state.episode_ids, branches))
    named_branches = [
        id_to_branch.get(tid)
        or _resolve_deferred_branch(repo, tid)
        or f"{tid} (branch not resolved)"
        for tid in deferred
    ]
    emit_diagnostic(
        "chain: gates deferred on episode(s) "
        + ", ".join(deferred)
        + " — halted chain keeps ungated WIP on branch(es): "
        + ", ".join(named_branches)
    )


def _maybe_finalize_chain(
    repo: Path,
    result: TaskResult,
    branches: list[str],
    *,
    completed: bool,
    read_only: bool,
    chain_base: str,
    instruction: str,
    open_pr: bool,
    base: str,
    artifact_path: Path,
    pr_body: str | None = None,
) -> Path:
    """Finalize a COMPLETED chain once — or honestly decline to (extracted, S3776).

    Three declines, each deliberate: a HALTED chain never pushes (the operator
    may want the WIP); a read-only chain stays handoff-free (h21); and a
    completed chain that landed NO commits mirrors ``handoff()``'s "no changes
    to hand off" semantics — no push, no PR, no reap, one explicit diagnostic
    (Qodo, PR #333; ``commits_ahead`` degrades to 0 on any git error, which
    conservatively declines too). Returns the (possibly re-written) artifact
    path — unchanged on every decline.
    """
    if not completed or read_only or not branches:
        return artifact_path
    if commits_ahead(repo, chain_base, branches[-1]) <= 0:
        emit_diagnostic("chain: completed with no changes; no handoff performed")
        return artifact_path
    return _chain_finalize(
        repo,
        result,
        branches,
        instruction=instruction,
        open_pr=open_pr,
        base=base,
        pr_body=pr_body,
    )


def _chain_deferral_surfacing(
    result: TaskResult, completed: bool
) -> tuple[tuple[str, ...], str | None]:
    """The chain's gate-deferral surfacing inputs (#341/#340; extracted, S3776).

    ``deferred`` is the typed chain record — accumulated per episode by
    ``ChainView.accumulate`` off ``result.gates_deferred`` — that feeds the
    outcome line. ``pr_body`` is non-None only on the #340 corner (a COMPLETED
    chain whose FINAL episode deferred: ok-finish + declared fill-line
    handoff), so the warning rides the handoff PR body and the human reviewer
    at gate 3 sees the diff went ungated.
    """
    deferred = tuple(result.chain.deferred_gate_episodes) if result.chain else ()
    pr_body: str | None = None
    if completed and getattr(result, "gates_deferred", False):
        pr_body = (
            "WARNING: this chain completed via a declared fill-line "
            "finish-with-handoff, so the pre-finish gates (lint / coherence / "
            "test-integrity / affected-tests) were deferred on its final episode "
            "and this diff was handed off ungated (#340). Deferring episode(s): "
            + ", ".join(deferred)
            + "."
        )
    return deferred, pr_body


def execute_work_chain(
    *,
    repo: Path,
    engine_name: str,
    task: Task,
    open_pr: bool,
    base: str,
    config: EngineConfig,
    cap: int,
    allow_dirty: bool = False,
    command_name: str | None = None,
    display: "DisplayOptions | None" = None,
    progress_sink: "CockpitProgressSink | None" = None,
    mode: str | None = None,
    lineage: "Lineage | None" = None,
) -> tuple[TaskResult, Path]:
    """The ``--until-done`` episode chain loop (indefinite-run t5/t9).

    The single implementation of episode chaining, shared by BOTH fronts (the
    h11 ``execute_work`` precedent): :func:`_run_chain` adapts ``cmd_work``'s
    parsed argv onto it, and the interactive ``session``'s armed dispatch
    calls it directly (``_dispatch_work`` — same kwargs shape as its
    single-episode ``work_fn`` call, plus *cap*), so the session front can
    never fork the chain semantics. Returns the FINAL episode's
    ``(result, artifact_path)`` pair — the caller owns outcome emission
    (exit-code mapping for the CLI, the feed line for the session).

    Wraps :func:`execute_work`: each episode is an ordinary bounded work item
    with its own artifact; the chain decisions are pure ``colleague.chain``
    verdicts over the episode's persisted terminal facts. The loop owns:

    - **handoff-once** (c26): every episode dispatches with ``open_pr=False``
      (finality is unknowable before an episode runs), and a COMPLETED chain
      (ok-finish) performs the arming invocation's push/PR choice exactly once
      via :func:`_chain_finalize`, then reaps the intermediate branches. A
      HALTED chain (non-continuable exit, no progress, cap, continuation
      error) leaves every episode branch alone — the operator may want the
      WIP — and never pushes.
    - **verbatim inheritance** (c28/h23): every episode re-dispatches with the
      SAME resolved locals — ``engine``, ``config`` (resolved once in
      :func:`cmd_work`; mode profile applied once below), ``open_pr``,
      ``allow_dirty``, display knobs, attachments — never re-reading env or
      ``config.json`` mid-chain (the ``_CHILD_FLAG_TABLE`` background-child
      precedent, held as locals).
    - **tree carry** (c6): episode N+1's isolation worktree bases on episode
      N's ``colleague/<id>`` branch tip (``ChainEpisodeOptions.base_ref``);
      a missing/reaped tip degrades to HEAD with a recorded warning (h6).
    - **lineage + accounting** (c20): ``continued_from`` stamps episode-to-
      episode, and each episode's artifact carries the running
      :class:`~colleague.contract.ChainView` (sums of exact usage, h19).
      ``--continue`` combines: episode 1 is the continued task (dispatched at
      HEAD, exactly like an unchained ``--continue``), and a cut CHAINED
      run's accounting resumes via :func:`~colleague.artifact.read_chain_view`.
      Every episode also re-resolves :func:`colleague.continuation.prior_task_text`
      for its OWN ``continued_from`` (c22/h15/h3) so the ORIGINAL brief — never
      a synthesized seed — rides every episode's artifact ``task_text``.

    A halted chain returns its last episode's honest result (#313 stays
    intact) — the CLI adapter maps it to the exit code (0 ok / 2 incomplete /
    1 error).
    """

    continued_from = lineage.continued_from if lineage else None
    continuation_task_text = lineage.task_text if lineage else None
    display = display or DisplayOptions()
    if progress_sink is not None and display.sink is None:
        # The session front still passes its sink positionally-adjacent; fold it
        # into the bundle execute_work reads (S107 — sink rides DisplayOptions).
        display = replace(display, sink=progress_sink)
    # c28: apply the mode profile ONCE at arming; every episode reuses this
    # resolved config verbatim (execute_work skips re-application when chained,
    # so a mid-chain overlay change is never re-read).
    config = _moded_config(config, mode, repo)
    attachments = task.attachments
    arming_instruction = task.instruction
    # Read-only chain semantics arm on the read-only ROLE or a read-only MODE
    # (explore/review): both produce commits structurally never, so the c22
    # commit-evidence guard cannot apply (progressed=None; the episode cap
    # bounds the chain) and the chain stays handoff-free (h21). Live-dogfood
    # catch (t12): a `--mode review --until-done` chain otherwise halts
    # 'no-progress' after episode 1 — the arc's own review chain proved it.
    read_only_chain = is_read_only(getattr(config, "role", None)) or mode in _READ_ONLY_MODES
    # Lazy import: the chain path is opt-in; keep work's import graph flat.
    from colleague import chain as chainmod
    from colleague import continuation

    # Config-plane arming (change-content consumption lane, t9): ONE
    # lifecycle for the WHOLE chain (h22 — an armed --until-done chain is
    # itself one top-level task), constructed + its WINDOW_BEFORE_EPISODE_1
    # run BEFORE episode 1 ever dispatches, then threaded to every episode
    # via ChainEpisodeOptions.config_plane below (never re-armed mid-chain).
    # A strict no-op (config_plane stays None) unless three-tier is armed
    # (config.worker is not None) — byte-identical to today either way.
    # Lazy MODULE-attribute lookup (see this module's docstring): both
    # `_arm_config_plane` and `execute_work` stay pinned to `work.py`, and the
    # suite patches `execute_work` on that module object.
    from colleague.cli._commands import work as _work

    config_plane = _work._arm_config_plane(config, repo=repo, task=task, engine_name=engine_name)

    # --continue + --until-done: resume the cut run's chain accounting when it
    # carried a view (an ordinary cut run yields None → fresh accounting).
    prior_view = read_chain_view(repo, continued_from) if continued_from else None
    chain_base = head_sha(repo) or "HEAD"
    state = chainmod.ChainState(cap=cap)
    episode_task = task
    prior_branch: str | None = None
    episode_branches: list[str] = []
    # Cumulative changed-files union across episodes (#335, c22): each episode
    # sees every PRIOR episode's touched files, sorted+deduped, on
    # ``ChainEpisodeOptions.prior_changed`` — ``()`` on the first episode.
    changed_so_far: set[str] = set()

    while True:
        result, artifact_path = _work.execute_work(
            repo=repo,
            engine_name=engine_name,
            task=episode_task,
            open_pr=False,  # c26: per-episode push/PR suppressed; see _chain_finalize
            allow_dirty=allow_dirty,
            isolate=True,
            base=base,
            config=config,
            command_name=command_name,
            display=display,
            mode=mode,
            lineage=Lineage(continued_from=continued_from, task_text=continuation_task_text),
            chain=ChainEpisodeOptions(
                base_ref=prior_branch,
                prior_view=prior_view,
                prior_changed=tuple(sorted(changed_so_far)),
                config_plane=config_plane,
            ),
        )
        prior_view = result.chain
        changed_so_far |= set(result.changed_files)
        episode_branch = result.branch or branch_name(episode_task.id, episode_task.instruction)
        episode_branches.append(episode_branch)

        progressed = _chain_progress(
            repo,
            result,
            state,
            read_only=read_only_chain,
            prior_ref=prior_branch or chain_base,
            episode_branch=episode_branch,
        )
        seed, verdict = _chain_should_start_next(
            repo,
            result,
            state,
            progressed=progressed,
            watch=task.watch,
            agents_armed=bool(getattr(config, "agents", False)),
        )
        if seed is None:
            break
        # Config-plane between-episode window (t9): the go-verdict path —
        # decided to continue, not yet dispatched episode N+1. Reviews the
        # JUST-FINISHED episode's terminal facts (episode_task/result, still
        # unreassigned at this point in the loop). A no-op unless three-tier
        # is armed (config_plane is None).
        if config_plane is not None:
            _run_between_episodes_window(
                config_plane,
                repo=repo,
                task=episode_task,
                result=result,
                config=config,
                engine_name=engine_name,
            )
        emit_diagnostic(
            f"chain: episode {state.episode_count} ({result.task_id}) exit "
            f"{verdict.reason!r} — continuing (episode {state.episode_count + 1})"
        )
        continued_from, seed_text = seed
        # c22/h15/h3: re-resolve for THIS episode's own prior artifact so the
        # original brief — never the seed just built — rides every episode.
        continuation_task_text = continuation.prior_task_text(repo, continued_from)
        prior_branch = episode_branch
        episode_task = Task.new(
            str(repo),
            seed_text,
            engine=engine_name,
            attachments=list(attachments) if attachments else None,
        )
        # The flight arming resolved once for the arming invocation (c28).
        episode_task.watch = task.watch
        _announce_episode_transition(repo, result.task_id, episode_task.id, state, task.watch)

    completed = verdict.reason == chainmod.HALT_OK_FINISH
    deferred, pr_body = _chain_deferral_surfacing(result, completed)
    artifact_path = _maybe_finalize_chain(
        repo,
        result,
        episode_branches,
        completed=completed,
        read_only=read_only_chain,
        chain_base=chain_base,
        instruction=arming_instruction,
        open_pr=open_pr,
        base=base,
        artifact_path=artifact_path,
        pr_body=pr_body,
    )
    _emit_chain_outcome(
        verdict,
        state,
        completed=completed,
        branches=episode_branches,
        deferred=deferred,
        repo=repo,
    )
    return result, artifact_path


def _run_chain(
    args: argparse.Namespace,
    repo: Path,
    engine: str,
    config: EngineConfig,
    task: Task,
    *,
    command_name: str | None,
    mode: str | None,
) -> int:
    """``cmd_work``'s thin adapter onto :func:`execute_work_chain` (t5/t9).

    Unpacks the parsed argv (open-pr choice, display knobs, the resolved
    ``--continue`` lineage) onto the shared chain loop and maps the FINAL
    episode's result to the exit code via :func:`_emit_work_outcome`
    (0 ok / 2 incomplete / 1 error — a halted chain reports its last episode
    honestly, #313). The session front calls ``execute_work_chain`` directly,
    so the chain semantics live in exactly one place.
    """
    json_mode = bool(getattr(args, "json", False))
    cap, _ = _resolve_chain_arming(args, config)
    try:
        result, artifact_path = execute_work_chain(
            repo=repo,
            engine_name=engine,
            task=task,
            open_pr=not args.no_pr,
            base=args.base,
            config=config,
            cap=cap,
            allow_dirty=bool(getattr(args, "allow_dirty", False)),
            command_name=command_name,
            display=DisplayOptions(
                tui=getattr(args, "tui", None), tui_events=getattr(args, "tui_events", None)
            ),
            mode=mode,
            lineage=Lineage(
                continued_from=getattr(args, "_continued_from_resolved", None),
                task_text=getattr(args, "_continuation_task_text_resolved", None),
            ),
        )
    except CliError as exc:
        # An episode crash halts the chain like a single run's failure —
        # branches stay (the operator may want the WIP); same --json
        # partial surface as cmd_work's unchained path.
        if json_mode and exc.result is not None:
            emit_result(exc.result.to_dict(), json_mode=True)
        raise
    return _emit_work_outcome(result, engine, artifact_path, json_mode)

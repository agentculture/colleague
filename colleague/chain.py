"""Chain driver core: the pure decision layer for chained episodes (indefinite-run t3).

An ARMED run (``--until-done``, plan t5) chains bounded episodes: each episode
is an ordinary work item with its own ``max_steps`` budget, artifact, and
``_EXIT_BUDGET`` exit — chaining lives OUTSIDE the bounded loop, at the work
dispatch layer, and this module is where that layer's decisions live. Nothing
here runs git, spawns a process, or imports loop internals: every function is
a pure mapping from a :class:`~colleague.contract.TaskResult`'s persisted
terminal facts (plus caller-supplied evidence) to an explicit verdict.

The three decisions (spec 2026-07-15-indefinite-run):

- **Continuable-exit allow-list** (decision c24/h20): the chain re-dispatches
  ONLY an episode whose exit reason is in :data:`CONTINUABLE_REASONS` — an
  explicit enumeration, exactly ``{"budget-exhausted"}``, never a
  ``status != ok`` catch-all (a catch-all would re-dispatch pilot-stopped and
  protocol-broken runs, each of which is a deliberate halt with its own
  meaning).
- **No-progress guard** (decision c22): an episode that lands no new commits
  on its branch AND adds no new artifact evidence halts the chain — chaining
  must never become an infinite no-progress loop or a way to launder
  incompletion (#313 stays intact).
- **Episode cap** (decision c21): default 5 when armed, 0 = unlimited; the
  knobs ride :meth:`colleague.config.EngineConfig.resolve`
  (``COLLEAGUE_UNTIL_DONE`` / ``COLLEAGUE_MAX_EPISODES``).

Consumes artifacts (via the ``TaskResult`` shape) and
:func:`colleague.continuation.resolve_continuation` only — the ok-guard and
wrong-run guard stay where they are, and a :class:`ContinuationError` is a
CLEAN halt verdict here, never a crash (h5). Pure stdlib; no subprocess,
thread, or socket (the ``test_boundary.py`` sanctioned lists are unchanged).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from colleague import configlifecycle as _configlifecycle
from colleague.continuation import ContinuationError, resolve_continuation
from colleague.contract import ERROR, OK, TaskResult

# The continuable-exit ALLOW-LIST (decision c24): incompletion reasons —
# exact literals from colleague/incompletion.py — whose episode the chain may
# re-dispatch. An explicit enumeration, deliberately NOT "status != ok":
# pilot-stop, tool-protocol-broken, no-progress-zero-steps, write-no-changes,
# empty-deliverable, and error are each a deliberate halt with its own meaning.
CONTINUABLE_REASONS: frozenset[str] = frozenset({"budget-exhausted"})

# Canonical exit-reason strings :func:`exit_reason` derives for results that
# carry no incompletion record (whose ``reason`` is otherwise used verbatim).
EXIT_OK = "ok"
EXIT_ERROR = "error"
EXIT_BUDGET_EXHAUSTED = "budget-exhausted"
EXIT_STOPPED_WITHOUT_FINISH = "stopped-without-finish"
EXIT_UNCLASSIFIED = "unclassified"

# Halt-verdict reasons — one honest string per way a chain ends (h2/h7).
HALT_OK_FINISH = "ok-finish"
HALT_NON_CONTINUABLE = "non-continuable-reason"
HALT_CAP_REACHED = "cap-reached"
HALT_NO_PROGRESS = "no-progress"
HALT_CONTINUATION_ERROR = "continuation-error"
# A pilot's cooperative stop landing in the between-episode window (t6). The
# check itself lives at the work-dispatch seam (_chain_should_start_next) —
# flight-control I/O stays out of this pure module; only the reason is named
# here so the halt vocabulary has one home.
HALT_PILOT_STOP = "pilot-stop"

#: The go-verdict reason for a declared fill-line handoff (deviation d1): the
#: episode took the #156 FINISH-WITH-HANDOFF move, so the chain restarts from
#: its continuation seed (decision c23) instead of halting on the episode's
#: incompletion classification.
CONTINUE_CAPACITY_HANDOFF = "capacity-handoff"

# The armed-default episode cap (decision c21). The resolved knob lives in
# colleague/config.py (``EngineConfig.max_episodes``); this mirror keeps the
# decision layer usable without a config object (e.g. ``ChainState(cap=...)``).
DEFAULT_MAX_EPISODES = 5


@dataclass(frozen=True)
class ChainVerdict:
    """The chain driver's decision for one episode boundary.

    ``should_continue`` says whether episode N+1 may be dispatched; ``reason``
    is one of the module's reason constants (a continuable exit reason on a
    go-verdict, a ``HALT_*`` string on a halt); ``detail`` carries the honest
    specifics (e.g. WHICH non-continuable exit reason halted the chain).
    """

    should_continue: bool
    reason: str
    detail: str = ""


def exit_reason(result: TaskResult) -> str:
    """Map a result's persisted terminal facts to a canonical exit-reason string.

    Precedence mirrors how the loop records an exit:

    1. ``status == OK`` → ``"ok"`` (a clean finish has no exit *problem*);
    2. ``status == ERROR`` → ``"error"`` (the aborted path sets no
       incompletion record — never continuable);
    3. an :class:`~colleague.contract.IncompletionRecord` → its ``reason``
       verbatim (the exact colleague/incompletion.py literals, e.g.
       ``"budget-exhausted"``, ``"tool-protocol-broken"``);
    4. ``not_finished`` → ``"budget-exhausted"``: the #313 soft rule
       SUPPRESSES the record when a budget exit already changed files
       (delivered-so-far is not absence), but the budget exit itself persists
       on this flag — the headline chaining case;
    5. ``stopped_without_finish`` → ``"stopped-without-finish"`` (a record-less
       pilot stop or no-finish stall — outcome flags are disjoint, so a budget
       exit never lands here);
    6. anything else → ``"unclassified"`` (defensively non-continuable).
    """
    if result.status == OK:
        return EXIT_OK
    if result.status == ERROR:
        return EXIT_ERROR
    if result.incompletion is not None and result.incompletion.reason:
        return result.incompletion.reason
    if result.not_finished:
        return EXIT_BUDGET_EXHAUSTED
    if result.stopped_without_finish:
        return EXIT_STOPPED_WITHOUT_FINISH
    return EXIT_UNCLASSIFIED


def declared_capacity_handoff(result: TaskResult) -> bool:
    """True when *result* recorded the fill-line FINISH-WITH-HANDOFF move (#156).

    The precise, deterministic signal (deviation d1): ``capacity_decision`` is
    stamped by the loop only when the model declared a move at the fill line;
    ``kind == "finish-with-handoff"`` is the continuation-shaped finish the
    c23 decision exists to restart from.
    """
    decision = getattr(result, "capacity_decision", None)
    return getattr(decision, "kind", None) == "finish-with-handoff"


def should_continue(
    result: TaskResult,
    episode_index: int,
    cap: int,
    *,
    progressed: Optional[bool] = None,
) -> ChainVerdict:
    """Decide whether the chain may dispatch another episode after *result*.

    Parameters
    ----------
    result:
        The episode that just finished (its persisted terminal facts).
    episode_index:
        The 1-based count of episodes already run — the one *result* belongs to.
    cap:
        The episode cap (decision c21): ``0`` (or negative) = unlimited.
    progressed:
        The no-progress guard's evidence verdict (decision c22), computed by
        the caller via :func:`episode_progressed` — ``False`` halts the chain;
        ``None`` (no evidence supplied, e.g. the first episode) never
        triggers the guard.

    Returns a :class:`ChainVerdict` whose ``reason`` names every halt honestly:
    ``ok-finish`` (the ok-guard — an ok episode is never re-dispatched),
    ``non-continuable-reason`` (allow-list miss, the exit reason in
    ``detail``), ``no-progress``, or ``cap-reached``; a go-verdict carries the
    continuable exit reason itself.
    """
    reason = exit_reason(result)
    if reason == EXIT_OK:
        return ChainVerdict(
            should_continue=False,
            reason=HALT_OK_FINISH,
            detail=f"{result.task_id} finished ok — the chain is done",
        )
    # Deviation d1 (2026-07-15, live-dogfood catch): a non-ok episode that
    # DECLARED the fill-line finish-with-handoff (#156 — recorded verbatim on
    # ``result.capacity_decision``) is continuable regardless of its
    # incompletion classification: the handoff exists so the chain restarts
    # from its seed (decision c23). The ok-guard above still wins (done is
    # done), the cap below still bounds, and every deliberate halt in the
    # allow-list contract (c24: pilot-stop, tool-protocol, plain no-progress)
    # is unaffected — this recognizes exactly the one declared-handoff shape.
    if declared_capacity_handoff(result):
        if cap > 0 and episode_index >= cap:
            return ChainVerdict(
                should_continue=False,
                reason=HALT_CAP_REACHED,
                detail=f"episode {episode_index} reached the {cap}-episode cap",
            )
        return ChainVerdict(
            should_continue=True,
            reason=CONTINUE_CAPACITY_HANDOFF,
            detail="the episode declared finish-with-handoff at the fill line (#156)",
        )
    if reason not in CONTINUABLE_REASONS:
        return ChainVerdict(
            should_continue=False,
            reason=HALT_NON_CONTINUABLE,
            detail=f"exit reason {reason!r} is not in the continuable allow-list",
        )
    if progressed is False:
        return ChainVerdict(
            should_continue=False,
            reason=HALT_NO_PROGRESS,
            detail=(
                f"episode {episode_index} landed no new commits and added no new "
                "artifact evidence (decision c22)"
            ),
        )
    if cap > 0 and episode_index >= cap:
        return ChainVerdict(
            should_continue=False,
            reason=HALT_CAP_REACHED,
            detail=f"episode {episode_index} reached the {cap}-episode cap",
        )
    return ChainVerdict(
        should_continue=True,
        reason=reason,
        detail=f"episode {episode_index} exit {reason!r} is continuable",
    )


def episode_progressed(*, new_commits: int, new_evidence: bool) -> bool:
    """The no-progress predicate (decision c22), on explicit caller evidence.

    ``new_commits`` is the number of commits the episode landed on its branch
    (the caller counts them — this module never runs git); ``new_evidence`` is
    whether the episode's artifact added evidence the chain had not seen (e.g.
    :meth:`ChainState.record_episode`'s return). Progress = either.
    """
    return new_commits > 0 or new_evidence


@dataclass
class ChainState:
    """Bookkeeping record for one armed chain, across episodes.

    The dispatch loop (t5) owns dispatching; this record owns what the chain
    has SEEN: the ordered episode ids, the artifact evidence baseline the
    no-progress guard compares against, the cap, and the final halt verdict.
    Pure in-memory state — nothing here touches disk or git.
    """

    cap: int = DEFAULT_MAX_EPISODES
    episode_ids: list[str] = field(default_factory=list)
    seen_changed_files: set[str] = field(default_factory=set)
    halt: Optional[ChainVerdict] = None

    @property
    def episode_count(self) -> int:
        """The 1-based count of episodes recorded so far."""
        return len(self.episode_ids)

    def record_episode(self, task_id: str, changed_files: Iterable[str] = ()) -> bool:
        """Record a finished episode; return True when it added NEW artifact evidence.

        New evidence = a changed-file path (from the episode's artifact) the
        chain has not seen in any prior episode — one of the two
        :func:`episode_progressed` inputs (decision c22). The baseline is
        updated in place so the next episode compares against everything seen.
        """
        self.episode_ids.append(task_id)
        incoming = set(changed_files)
        fresh = incoming - self.seen_changed_files
        self.seen_changed_files |= incoming
        return bool(fresh)


def resolve_chain_seed(
    repo: str | Path, task_id: str
) -> tuple[Optional[tuple[str, str]], Optional[ChainVerdict]]:
    """Resolve the next episode's continuation seed — a clean halt on failure.

    Wraps :func:`colleague.continuation.resolve_continuation` verbatim (the
    ok-guard and artifact guards stay where they are) and converts
    :class:`ContinuationError` into a halt :class:`ChainVerdict` instead of a
    crash (h5): an ok artifact ("nothing to continue"), a missing artifact, or
    a corrupt one each end the chain cleanly with the error text as
    ``detail``.

    Returns ``((resolved_task_id, seed_text), None)`` on success, or
    ``(None, halt_verdict)`` when continuation cannot be honored — exactly one
    of the pair is ``None``.
    """
    try:
        resolved = resolve_continuation(repo, task_id)
    except ContinuationError as exc:
        return None, ChainVerdict(
            should_continue=False,
            reason=HALT_CONTINUATION_ERROR,
            detail=str(exc),
        )
    return resolved, None


# ---------------------------------------------------------------------------
# Episode-boundary config lifecycle window (plan task t6, decisions c8/c26)
# ---------------------------------------------------------------------------
#
# The three-tier-execution design (#364/#363) lets cortex propose task-local
# config changes (colleague/lattice.py ChangeUnits, applied through
# colleague/configlifecycle.py's EpisodeConfigLifecycle). This module already
# treats the episode as the unit (CONTINUABLE_REASONS, the between-episode
# halt/continue verdict above) — the configuration boundary maps onto the
# SAME seam: a proposal queued mid-episode may only take effect in the
# window BETWEEN two dispatched episodes, or before the very first one.
# ``apply_config_window`` is the ONE function that may call
# ``EpisodeConfigLifecycle.apply_window`` — the sanctioned call site colleague/
# configlifecycle.py's docstring names. Synchronous on the calling thread; this
# module imports no threading primitive and no bounded-pool executor.

#: Re-exported here so a chain driver names its own windows without importing
#: colleague.configlifecycle directly — this module is the documented home of
#: "the between-episode window" the plan task names.
WINDOW_BEFORE_EPISODE_1 = _configlifecycle.WINDOW_BEFORE_EPISODE_1
WINDOW_BETWEEN_EPISODES = _configlifecycle.WINDOW_BETWEEN_EPISODES


def apply_config_window(
    lifecycle: _configlifecycle.EpisodeConfigLifecycle,
    window: str,
) -> _configlifecycle.ConfigApplication:
    """Apply *lifecycle*'s queued config proposals at a sanctioned window.

    The ONLY two sanctioned call sites (decision c8/c26): BEFORE episode 1
    ever dispatches (``window=WINDOW_BEFORE_EPISODE_1``), and in the chain
    driver's between-episode window, after :func:`should_continue` verdicts a
    go and before episode N+1 dispatches (``window=WINDOW_BETWEEN_EPISODES``).
    A mid-episode call is never made — nothing in ``colleague/loop.py``'s
    turn loop calls this function or ``EpisodeConfigLifecycle.apply_window``
    directly. Delegates the actual queue-drain + digest work to
    :meth:`~colleague.configlifecycle.EpisodeConfigLifecycle.apply_window`
    (which independently refuses any *window* outside the sanctioned set) —
    this wrapper exists so "chain.py's between-episode window" has one named
    home a caller imports from, matching the plan instruction verbatim.
    """
    return lifecycle.apply_window(window)

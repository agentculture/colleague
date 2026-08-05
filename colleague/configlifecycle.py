"""Episode-boundary config lifecycle (three-tier-execution plan task t6).

An opt-in three-tier run (design brief #364/#363) lets cortex *configure* what
the worker's episode runs under — a narrowed tool set, a bounded task-local
strategist prompt section, extra knowledge entries — as typed
:class:`~colleague.lattice.ChangeUnit` proposals. This module owns the ONE
question those proposals raise once they exist: *when* does a proposal ever
take effect?

The answer (spec decision, covered here: c8/h8/c26/h22) is: **never mid-
episode**. :class:`EpisodeConfigLifecycle` holds one worker episode's
resolved, immutable configuration as an opaque, digestible
:class:`EpisodeConfigSnapshot`; proposals arriving during an episode are
queued, never applied, so the effective-config digest is provably constant
across every model turn within that episode (the loop seam in
``colleague/loop.py`` observes it, never mutates it). The queue is only ever
drained at the two sanctioned windows colleague/chain.py names: **before
episode 1**, and in the chain driver's **between-episode window**
(:func:`colleague.chain.apply_config_window`). Both windows run synchronously
on the calling thread — this module imports no ``threading`` /
``concurrent.futures`` (mirroring the ``test_boundary.py`` rule 6 sanctioned
list, which stays exactly ``{subagents.py, _input_line.py}``; v1 cortex
review is synchronous, never concurrent-with-episode).

Scope: this lifecycle tracks the WORKER seat's three configurable surfaces —
``worker.tools`` / ``worker.prompt.strategist`` / ``worker.knowledge`` (the
lattice's ``Target`` enum also carries two ``senses.*`` targets, which are a
different consumer's concern and are refused here, not silently dropped).
The snapshot is deliberately OPAQUE: this module does not compose real prompt
text or resolve a real tool schema — that stays layers.py's (t5) and
roles.py/tools.py's job. A queued unit's effect on the snapshot is a
canonical, deterministic marker sufficient to prove the timing contract
(digest changes ONLY at a sanctioned window) — a later task (t11, the actual
cortex configurator) is what will make those markers carry real prompt/tool
content end to end.

What lands durably is deliberately NOT this module's job either: t7
(contract.py/artifact.py) owns serializing a config event stream onto
``TaskResult``. Until it lands, every record here — proposals, refusals,
applications, episode boundaries, per-turn digest observations — lives on
this in-memory object with a clean to-list API (:meth:`events`,
:meth:`applications`, :meth:`turn_digests`) a later task can read and persist
without this module changing shape.

Lifecycle scope (task t6, honesty h22): one :class:`EpisodeConfigLifecycle`
instance belongs to exactly one TOP-LEVEL task. A chain's episodes share the
same instance (so ``end_episode()`` accumulates a running boundary count
across the whole chain and queued-but-unapplied proposals survive an
episode's exit into the next between-episode window); :meth:`reset` is the
explicit "config discarded at top-level task end" operation — a fresh task
must construct (or reset) a fresh lifecycle, never reuse a finished one's
queue/history.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace
from typing import Optional

from colleague.lattice import CapabilityCatalog, ChangeUnit, Target, Verdict, validate_change

# The three WORKER-seat targets this lifecycle applies. The lattice's other two
# targets (``senses.prompt.strategist`` / ``senses.knowledge``) belong to a
# different consumer — :meth:`EpisodeConfigLifecycle.propose` refuses them by
# name rather than silently ignoring them (the lattice's own "refuse whole,
# never strip-and-retain" discipline).
WORKER_TARGETS: frozenset[Target] = frozenset(
    {Target.WORKER_TOOLS, Target.WORKER_PROMPT_STRATEGIST, Target.WORKER_KNOWLEDGE}
)

# The two sanctioned application windows (colleague/chain.py names the second
# one; "before episode 1" has no chain-driver counterpart because it runs
# before any episode — hence it is named here, the shared home for both).
WINDOW_BEFORE_EPISODE_1 = "before-episode-1"
WINDOW_BETWEEN_EPISODES = "between-episodes"
SANCTIONED_WINDOWS: frozenset[str] = frozenset({WINDOW_BEFORE_EPISODE_1, WINDOW_BETWEEN_EPISODES})


class ConfigLifecycleError(Exception):
    """Programmatic misuse of the lifecycle API (e.g. an unsanctioned window).

    Mirrors :class:`colleague.lattice.LatticeError` — reserved for internal
    invariants, never for an ordinary proposal refusal (those return a
    :class:`~colleague.lattice.Verdict`, exactly like :func:`validate_change`).
    """


@dataclass(frozen=True)
class EpisodeConfigSnapshot:
    """One episode's resolved, immutable configuration — opaque and digestible.

    Three tuples mirror the three worker-seat lattice targets:
    ``strategist_sections`` (opaque per-application markers — the composed
    prompt TEXT is layers.py's concern, out of scope here), ``tool_set`` (the
    narrowed tool id set), and ``knowledge_entries`` (canonical JSON strings,
    one per applied knowledge entry). Frozen: a proposal never mutates a
    snapshot in place, it produces a NEW one (see :func:`_apply_change`).
    """

    strategist_sections: tuple[str, ...] = ()
    tool_set: tuple[str, ...] = ()
    knowledge_entries: tuple[str, ...] = ()

    def canonical(self) -> str:
        """A deterministic, order-preserving JSON serialization for digesting."""
        payload = {
            "strategist_sections": list(self.strategist_sections),
            "tool_set": list(self.tool_set),
            "knowledge_entries": list(self.knowledge_entries),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """The sha256 hex digest over :meth:`canonical` — the effective-config digest."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConfigEvent:
    """One append-only record on the lifecycle's in-memory event log.

    ``kind`` is one of ``"proposed"`` / ``"refused"`` / ``"applied"`` /
    ``"boundary"`` — a deliberate subset of the full proposed/refused/
    verified/applied/reverted vocabulary the spec assigns to t7's durable
    event stream (``"verified"``/``"reverted"`` belong to the not-yet-built
    cortex configurator, t11); this module records only what it itself does.
    ``digest`` is the effective-config digest at the moment of the event —
    always populated on ``"applied"``/``"boundary"`` events (the two that can
    change or observe it), empty otherwise.
    """

    kind: str
    target: str = ""
    origin: str = ""
    detail: str = ""
    digest: str = ""


@dataclass(frozen=True)
class ConfigApplication:
    """One record of the queue being drained at a sanctioned window.

    ``latency_seconds`` times the synchronous, in-memory application itself
    (queue drain + snapshot rebuild) — bounded by construction, since v1
    review is synchronous on the calling thread and every operation here is
    pure Python over small in-memory structures (no I/O, no subprocess, no
    network): there is no unbounded wait to cap.
    """

    window: str
    applied_count: int
    digest_before: str
    digest_after: str
    latency_seconds: float


def _apply_change(snapshot: EpisodeConfigSnapshot, change: ChangeUnit) -> EpisodeConfigSnapshot:
    """Fold one validated, worker-scoped :class:`ChangeUnit` into a NEW snapshot.

    Only called from :meth:`EpisodeConfigLifecycle.apply_window`, itself only
    ever reached at a sanctioned window — never mid-episode. Targets outside
    :data:`WORKER_TARGETS` never reach this function: :meth:`propose` refuses
    them before they are ever queued.
    """
    if change.target is Target.WORKER_TOOLS:
        return replace(snapshot, tool_set=tuple(change.tool_ids))
    if change.target is Target.WORKER_KNOWLEDGE:
        added = tuple(
            json.dumps(entry, sort_keys=True, separators=(",", ":"))
            for entry in change.knowledge_entries
        )
        return replace(snapshot, knowledge_entries=snapshot.knowledge_entries + added)
    if change.target is Target.WORKER_PROMPT_STRATEGIST:
        # Opaque marker (see the module docstring): a real strategist SECTION's
        # composed text is layers.py's (t5) concern; what this module must prove
        # is only that the digest moves exactly once per applied proposal, and
        # only at a sanctioned window.
        marker = f"{change.origin.value}#{len(snapshot.strategist_sections) + 1}"
        return replace(snapshot, strategist_sections=snapshot.strategist_sections + (marker,))
    # Unreachable: propose() refuses every non-worker target before queuing.
    raise ConfigLifecycleError(f"cannot apply out-of-scope target {change.target!r}")


class EpisodeConfigLifecycle:
    """Owns one top-level task's worker-episode configuration across episodes.

    Holds the CURRENT episode's frozen :class:`EpisodeConfigSnapshot`, a queue
    of proposals validated against the lattice (:func:`colleague.lattice.
    validate_change`) that arrived mid-episode, and applies the queue ONLY at
    :data:`WINDOW_BEFORE_EPISODE_1` / :data:`WINDOW_BETWEEN_EPISODES`
    (:meth:`apply_window`, called from ``colleague/chain.py``'s
    :func:`~colleague.chain.apply_config_window` — the sole sanctioned call
    site). Application is synchronous on the calling thread: nothing here
    imports ``threading`` or ``concurrent.futures``.

    The loop (``colleague/loop.py``) consults this object read-only during an
    episode: it reads :meth:`effective_digest` (via :meth:`observe_turn`,
    the loop's per-turn pin-proof) and never calls :meth:`apply_window`
    itself — only :meth:`end_episode`, once per ``run()`` call, on every exit
    path (the T1 regression fix: a no-tool episode end counts as a boundary
    exactly like a tool-driven one).
    """

    def __init__(
        self,
        initial: Optional[EpisodeConfigSnapshot] = None,
        *,
        catalog: Optional[CapabilityCatalog] = None,
    ) -> None:
        self._snapshot = initial if initial is not None else EpisodeConfigSnapshot()
        # An empty catalog is a safe, restrictive default — worker.tools
        # proposals refuse until a caller supplies the task's actually-resolved
        # tool allow-list (the t4 CapabilityCatalog contract: constructed ONLY
        # from a caller-supplied resolved list, never minted here).
        self._catalog = catalog if catalog is not None else CapabilityCatalog(tool_ids=())
        self._queue: list[ChangeUnit] = []
        self._applications: list[ConfigApplication] = []
        self._events: list[ConfigEvent] = []
        self._turn_digests: list[str] = []
        self._boundary_count = 0

    # -- read-only snapshot / digest -------------------------------------

    @property
    def snapshot(self) -> EpisodeConfigSnapshot:
        """The CURRENT, effective (already-applied) snapshot."""
        return self._snapshot

    def effective_digest(self) -> str:
        """The sha256 digest of the current effective snapshot."""
        return self._snapshot.digest()

    @property
    def boundary_count(self) -> int:
        """The number of episode boundaries :meth:`end_episode` has recorded."""
        return self._boundary_count

    def pending_count(self) -> int:
        """How many validated proposals are queued, not yet applied."""
        return len(self._queue)

    # -- children (risk r2: the default is INHERIT) -----------------------

    def child_snapshot(self) -> EpisodeConfigSnapshot:
        """The snapshot a subagent spawned INSIDE this episode inherits by default.

        Risk r2 (plan park, default proposal: inherit): a child spawned
        mid-episode gets the episode's CURRENT frozen snapshot — never a
        queued-but-unapplied proposal, since a proposal is not "resolved
        config" until the next sanctioned window applies it. This is the
        documented default a subagent-spawn integration (out of this task's
        file ownership) is expected to read; nothing in ``colleague/
        subagents.py`` is touched by task t6.
        """
        return self._snapshot

    # -- proposals ----------------------------------------------------------

    def propose(self, change: ChangeUnit) -> Verdict:
        """Validate and queue *change*; returns the :class:`Verdict` (never raises).

        A change targeting a ``senses.*`` surface is refused here (out of this
        lifecycle's worker-seat scope) with the same never-raise discipline as
        every other lattice refusal. An accepted change is queued — it has NO
        effect on :meth:`effective_digest` until the next :meth:`apply_window`.
        """
        if change.target not in WORKER_TARGETS:
            verdict = Verdict(
                False,
                f"refused: {change.target!r} is out of scope for the worker "
                "episode config lifecycle (only "
                f"{sorted(t.value for t in WORKER_TARGETS)!r} apply here; "
                "senses.* targets belong to a different lifecycle)",
            )
            self._events.append(
                ConfigEvent(
                    kind="refused",
                    target=getattr(change.target, "value", str(change.target)),
                    detail=verdict.reason,
                )
            )
            return verdict
        verdict = validate_change(change, self._catalog)
        if verdict.allowed:
            self._queue.append(change)
            self._events.append(
                ConfigEvent(kind="proposed", target=change.target.value, origin=change.origin.value)
            )
        else:
            self._events.append(
                ConfigEvent(
                    kind="refused",
                    target=change.target.value,
                    origin=change.origin.value,
                    detail=verdict.reason,
                )
            )
        return verdict

    # -- application (the ONLY two sanctioned windows) -----------------------

    def apply_window(self, window: str) -> ConfigApplication:
        """Drain the queue into a NEW snapshot — ONLY at a sanctioned window.

        Called from :func:`colleague.chain.apply_config_window`, never
        directly by the loop. Synchronous on the calling thread; raises
        :class:`ConfigLifecycleError` on any window string outside
        :data:`SANCTIONED_WINDOWS` (programmer misuse, not a proposal
        refusal).
        """
        if window not in SANCTIONED_WINDOWS:
            raise ConfigLifecycleError(
                f"apply_window: unsanctioned window {window!r} "
                f"(only {sorted(SANCTIONED_WINDOWS)!r} may apply queued config)"
            )
        start = time.monotonic()
        digest_before = self.effective_digest()
        queued, self._queue = self._queue, []
        for change in queued:
            self._snapshot = _apply_change(self._snapshot, change)
            self._events.append(
                ConfigEvent(
                    kind="applied",
                    target=change.target.value,
                    origin=change.origin.value,
                    detail=window,
                    digest=self.effective_digest(),
                )
            )
        digest_after = self.effective_digest()
        latency = time.monotonic() - start
        record = ConfigApplication(
            window=window,
            applied_count=len(queued),
            digest_before=digest_before,
            digest_after=digest_after,
            latency_seconds=latency,
        )
        self._applications.append(record)
        return record

    def applications(self) -> list[ConfigApplication]:
        """A copy of every recorded window application, in order."""
        return list(self._applications)

    # -- the loop seam: episode boundaries + per-turn pin-proof --------------

    def observe_turn(self) -> str:
        """Record the pinned digest at one model turn; return it.

        Called by ``colleague/loop.py``'s ``_work_loop`` once per completed
        model turn (never by a proposal path) — proves the loop consults a
        FROZEN snapshot: nothing between here and the next call mutates
        ``self._snapshot`` (only :meth:`apply_window` does, and it is never
        called from inside a running episode).
        """
        digest = self.effective_digest()
        self._turn_digests.append(digest)
        return digest

    def turn_digests(self) -> list[str]:
        """A copy of every digest :meth:`observe_turn` recorded, in order."""
        return list(self._turn_digests)

    def end_episode(self) -> int:
        """Mark ONE episode boundary; returns the new boundary count.

        Called exactly once per ``run()`` call (loop.py), on EVERY exit path
        — a model-signalled finish, a no-tool stop (the T1 regression this
        method exists to fix), budget exhaustion, a pilot stop, a tool-
        protocol break, or an aborted engine raise. Never gated on which
        ``_EXIT_*`` reason ended the episode.
        """
        self._boundary_count += 1
        self._events.append(
            ConfigEvent(
                kind="boundary", detail=str(self._boundary_count), digest=self.effective_digest()
            )
        )
        return self._boundary_count

    def events(self) -> list[ConfigEvent]:
        """A copy of the full append-only event log, in order.

        The clean to-list API a later task (t7, contract.py/artifact.py) can
        read and persist onto ``TaskResult`` without this module changing
        shape.
        """
        return list(self._events)

    # -- top-level task end ---------------------------------------------

    def reset(self) -> None:
        """Discard ALL state — the "config is discarded at top-level task end" rule.

        A fresh top-level task must never reuse a finished lifecycle's queue,
        applications, events, or boundary count; this is the explicit
        operation that enforces it (a caller resets, or simply constructs a
        new :class:`EpisodeConfigLifecycle`, per top-level task).
        """
        self._snapshot = EpisodeConfigSnapshot()
        self._queue = []
        self._applications = []
        self._events = []
        self._turn_digests = []
        self._boundary_count = 0

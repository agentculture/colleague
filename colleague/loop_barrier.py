"""The pre-mutation decision barrier — one bounded tools-off planning turn (#484, t8).

Spec ``docs/specs/2026-09-01-small-fixes-then-effort-balance.md`` (c18/h7),
consuming the table task t5 built (:mod:`colleague.effortspikes`). The rung
comes from :func:`colleague.effortspikes.resolve_spike` under the ONE point
name :data:`BARRIER_POINT` and from nowhere else — no other input, and
certainly not turn content, can choose it.

What it does
------------

The FIRST time a model turn's tool calls include a MUTATING tool, after a
phase in which the run has only done read-only work, the loop interposes ONE
bounded, tools-off completion: same history, no tools offered, plus a system
nudge to name the files, invariants and seams the change will touch before
touching them. The completion's text lands in the running history as an
assistant planning message, so the model's NEXT turn re-issues its tool calls
with the plan in context.

What happens to the intercepted turn
------------------------------------

**Its tool calls are NOT executed, and its assistant message is NOT appended.**
The barrier REPLACES that turn's execution: nothing from the stale turn is
carried forward except the fact that the model wanted to act. The clean shape
is deliberate — a deferred-then-replayed tool call would act on a plan the
model had not yet written, and an appended assistant tool-call message with no
matching ``tool`` results is not a valid OpenAI history. The model re-issues
whatever it still wants to do on its next turn.

Accounting (decision c23 — honest, never hidden)
------------------------------------------------

The barrier turn is a NORMAL step:

* :func:`colleague.loop_accounting._account_turn` folds its usage, reasoning
  and answer sizes into ``WorkStats`` and advances ``model_turns`` — the
  declared ``max_steps`` bound, so the barrier costs a turn like any other;
* it appends ONE :class:`~colleague.contract.Step` named
  :data:`BARRIER_POINT`, so ``stats.step_count`` advances by exactly one and
  the trace shows where the barrier ran. It is never attributed to a real
  tool, and it never mutates anything.

Bounds
------

Its own output ceiling and timeout, both derived from existing config knobs at
the seat (never from the acting turn's budget):

* **output ceiling** — one EIGHTH of the run's ``max_output_chars``
  (:data:`PLAN_CHARS_DIVISOR`; 8500 chars on the 68000 default). A longer plan
  is cut with the same discoverable marker shape ``colleague/tasktext.py``
  uses, never silently;
* **timeout** — the STANDARD turn timeout: ``base_timeout`` when a bounded
  timeout escalation has raised ``timeout`` in place, else ``timeout``. A
  planning turn never inherits an escalated window.

Firing
------

At most ONCE per run (v0: a single barrier, matching the drift test that pins
three POINTS, not multiple firings). The firing is recorded on the artifact as
``TaskResult.effort_spikes`` — one
:meth:`colleague.effortspikes.SpikeRecord.to_dict` entry ``(point, rung,
seat)``; the presence of a record for :data:`BARRIER_POINT` is also the
already-fired marker, so no extra state cell is needed.

Unarmed (``COLLEAGUE_EFFORT_SPIKES`` unset — the default) every function here
is a strict no-op: :func:`make_barrier_complete` returns ``None`` before it
builds anything, :func:`intercept` returns ``False`` before it looks at a
tool name, no payload changes and the ``effort_spikes`` key never appears.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Callable, List, Optional, cast

from colleague import effortspikes
from colleague.contract import Step
from colleague.loop_accounting import _account_turn
from colleague.loop_progress import _emit_phase
from colleague.roles import is_read_only_tool

if TYPE_CHECKING:  # pragma: no cover - typing only
    from colleague.loop_types import _Work

#: The ONE spike point this module consumes. The rung is resolved from
#: :func:`colleague.effortspikes.resolve_spike` under this name and nowhere
#: else — there is no parameter, env fall-through or content inspection by
#: which any other value could reach the wire.
BARRIER_POINT = "barrier.pre_mutation"

#: The barrier's output ceiling as a divisor of the run's ``max_output_chars``
#: (68000 default -> 8500 chars). A plan is a short list of files, invariants
#: and seams; anything longer is the model writing the change instead.
PLAN_CHARS_DIVISOR = 8

#: The phase notice emitted before the (possibly slow) tools-off completion
#: (#206). A phase notice never advances ``step_count`` — the barrier's own
#: :class:`Step` does that, separately and once.
PHASE_BARRIER = "planning the change before the first edit — one bounded planning turn…"

#: The system nudge appended to the request (never to ``ctx.messages``): the
#: barrier turn asks for a decision, not for prose about one.
BARRIER_PROMPT = (
    "[decision barrier] You are about to change the repository for the first "
    "time in this run. Before acting, and WITHOUT calling any tool (none are "
    "available on this turn), write the plan you will act on:\n"
    "1. the exact files you will create or edit, and what changes in each;\n"
    "2. the invariants and conventions those files already carry that your "
    "change must not break;\n"
    "3. the seams you will touch (callers, tests, docs) and how you will "
    "verify the change.\n"
    "Be concise and concrete. Your next turn re-issues the tool calls you "
    "intended, with this plan in context."
)

#: ``messages -> ModelResponse`` (the loop's ``CompleteFn`` shape, left
#: untyped here so this module never imports the loop).
CompleteFn = Callable[[List[dict]], Any]
#: ``(engine_name, warn) -> CompleteFn | None`` — see
#: :func:`make_barrier_complete`.
BarrierCompleteFactory = Callable[..., Optional[CompleteFn]]


# ---------------------------------------------------------------------------
# The seat: a tools-off completion at the table's rung
# ---------------------------------------------------------------------------


def plan_char_ceiling(config: object) -> int:
    """The barrier's own output ceiling in characters (see the module docstring)."""
    chars = getattr(config, "max_output_chars", 0)
    if not isinstance(chars, int) or isinstance(chars, bool) or chars <= 0:
        return 0
    return max(1, chars // PLAN_CHARS_DIVISOR)


def clamp_plan(text: str, ceiling: int) -> str:
    """*text* cut to *ceiling* chars with a discoverable marker, never silently.

    Mirrors :func:`colleague.tasktext.prepare_task_text`'s marker shape. A
    non-positive *ceiling* (a config without ``max_output_chars``) is
    pass-through.
    """
    if ceiling <= 0 or len(text) <= ceiling:
        return text
    return f"{text[:ceiling]}\n[truncated: original {len(text)} chars]"


def barrier_seat_config(config: Any, rung: str) -> Any:
    """The :class:`~colleague.config.EngineConfig` the barrier turn runs against.

    A ``dataclasses.replace`` of the ACTING config — same model, same endpoint
    (the barrier is the acting mind thinking, not a second mind) — with the
    per-call knobs cleared exactly like every other one-shot seat builder
    (:func:`colleague.associate.associate_engine_config`), the standard
    (un-escalated) turn timeout, and ``reasoning_effort_seat`` set to *rung*.

    That plain attribute is the whole of "how the rung reaches the wire":
    ``vllm_openai._effort_for`` reads it and renders
    ``chat_template_kwargs`` for THIS completion only — the same mechanism a
    subagent spawn's explicit effort override already uses. No engine change.
    """
    seat = cast(Any, dataclasses.replace(config, on_delta=None, refresh_seat=None))
    base = getattr(config, "base_timeout", None)
    timeout = getattr(config, "timeout", None)
    if isinstance(base, (int, float)) and isinstance(timeout, (int, float)):
        seat.timeout = min(float(base), float(timeout))
    setattr(seat, "reasoning_effort_seat", rung)
    return seat


def make_barrier_complete(
    config: Any, *, engine_loader: Optional[Callable[[str], Any]] = None
) -> Optional[BarrierCompleteFactory]:
    """Bind the barrier's seat-completion factory, or ``None`` when it can never fire.

    ``None`` — the strict no-op — whenever
    :func:`colleague.effortspikes.resolve_spike` declines the point (the
    ``COLLEAGUE_EFFORT_SPIKES`` opt-in unset, the default). Nothing is built,
    no engine is loaded, and the loop keeps the pre-#484 path byte for byte.

    Armed, the returned ``factory(engine_name, warn)`` loads that engine and
    returns a TOOLS-OFF completion (``make_complete(seat, tools=[])`` — the
    honest tools-off invariant the deepthink seam relies on) whose replies are
    clamped to :func:`plan_char_ceiling`. It returns ``None`` — after one
    ``warn`` — for an engine with no one-shot completion seam (``mock``) or any
    setup failure, and the caller then simply does not interpose a barrier:
    the all-engines rule holds because an armed ``mock`` run never crashes, it
    records why.
    """
    if effortspikes.resolve_spike(BARRIER_POINT) is None:
        return None
    from colleague import registry

    loader = engine_loader if engine_loader is not None else registry.load

    def factory(engine_name: str, warn: Callable[[str], None]) -> Optional[CompleteFn]:
        rung = effortspikes.resolve_spike(BARRIER_POINT)
        if rung is None:  # re-checked at fire time: the opt-in is process state
            return None
        try:
            engine = loader(engine_name)
            seat = barrier_seat_config(config, rung)
            primary = engine.make_complete(seat, tools=[])
        except Exception as exc:  # noqa: BLE001 - a missing seam is never a crash
            warn(f"pre-mutation barrier unavailable (engine '{engine_name}': {exc})")
            return None
        ceiling = plan_char_ceiling(config)

        def complete(messages: List[dict]) -> Any:
            resp = primary(messages)
            resp.content = clamp_plan(resp.content or "", ceiling)
            return resp

        return complete

    return factory


# ---------------------------------------------------------------------------
# The trigger: tool NAMES only, never content
# ---------------------------------------------------------------------------


def is_mutating_tool(name: str) -> bool:
    """Whether *name* is a mutating tool — the EXISTING read-only classification.

    Membership in :data:`colleague.roles._READONLY_TOOLS` (via
    :func:`colleague.roles.is_read_only_tool`) — the same tool-NAME set that
    makes a read-only role provably unable to mutate the tree. Nothing here
    reads arguments or content: the trigger is a name lookup, so it can never
    become the excluded router (spec s14/c18).
    """
    return not is_read_only_tool(name)


def barrier_fired(result: Any) -> bool:
    """Whether this run already fired the barrier (the artifact record IS the marker)."""
    return any(
        isinstance(entry, dict) and entry.get("point") == BARRIER_POINT
        for entry in getattr(result, "effort_spikes", None) or ()
    )


def should_fire(ctx: "_Work", calls: Any) -> bool:
    """Whether THIS turn is the pre-mutation moment (tool names only).

    All four must hold:

    * the spike surface is armed for this point (rung resolves) AND a barrier
      seat factory was bound;
    * the barrier has not already fired this run (v0: at most once);
    * the run has completed at least one step and EVERY step so far named a
      read-only tool — i.e. the run is still in its read-only phase;
    * this turn asks for at least one mutating tool.
    """
    if ctx.barrier_complete is None or effortspikes.resolve_spike(BARRIER_POINT) is None:
        return False
    if barrier_fired(ctx.result):
        return False
    steps = ctx.result.steps
    if not steps or any(is_mutating_tool(step.tool) for step in steps):
        return False
    return any(is_mutating_tool(getattr(call, "name", "")) for call in calls or ())


# ---------------------------------------------------------------------------
# The firing
# ---------------------------------------------------------------------------


def _warn(ctx: "_Work", detail: str) -> None:
    ctx.result.warnings.append({"kind": "effort-spike-barrier", "detail": detail})


def intercept(ctx: "_Work", calls: Any) -> bool:
    """Interpose the barrier before this turn's tool calls; ``True`` if it consumed the turn.

    ``True`` means the caller must NOT append the turn's assistant message and
    must NOT run its tool calls (see the module docstring: the barrier
    replaces that turn's execution). ``False`` means nothing was interposed and
    the turn proceeds exactly as it does today — the state every unarmed run,
    and every armed run whose seat could not be built or whose planning turn
    produced no text, is in.
    """
    if not should_fire(ctx, calls):
        return False
    rung = cast(str, effortspikes.resolve_spike(BARRIER_POINT))
    complete = ctx.barrier_complete(ctx.task.engine, lambda text: _warn(ctx, text))
    if complete is None:
        return False
    request = list(ctx.messages) + [{"role": "user", "content": BARRIER_PROMPT}]
    _emit_phase(ctx, PHASE_BARRIER)
    try:
        resp = complete(request)
    except Exception as exc:  # noqa: BLE001 - a planning turn never aborts the run
        _warn(ctx, f"pre-mutation barrier turn failed ({type(exc).__name__}: {exc})")
        return False
    # Honest accounting first: the completion HAPPENED, so its usage and its
    # turn count land on WorkStats whether or not it produced a usable plan.
    _account_turn(ctx, resp)
    ctx.result.effort_spikes.append(
        effortspikes.SpikeRecord(point=BARRIER_POINT, rung=rung, seat=ctx.seat).to_dict()
    )
    plan = (resp.content or "").strip()
    if not plan:
        # No plan to inject: do not swallow the turn the model actually wanted.
        # The spike is still recorded (it fired) and the turn is still counted.
        return False
    ctx.result.steps.append(
        Step(len(ctx.result.steps), BARRIER_POINT, {"rung": rung}, plan, ok=True)
    )
    ctx.messages.append({"role": "assistant", "content": plan})
    return True

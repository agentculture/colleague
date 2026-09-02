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
import inspect
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

#: The stall decision point (effort-floor-and-decay arc): the SAME tools-off
#: seat as the barrier, a different trigger — a COUNT of acting turns with no
#: file-writing call (:data:`colleague.effortspikes.STALL_TURNS`), never
#: content. Rows 74-75 showed an ``off``-floor run surveying its whole budget
#: away without ever requesting a write, so the pre-mutation barrier — which
#: waits for that request — could never help it; this point can.
STALL_POINT = "stall.no_write"

PHASE_STALL = "no file changed for many turns — one bounded decision turn…"

STALL_PROMPT = (
    "[decision barrier] You have taken many tool turns in this run without "
    "changing any file. Surveying further will not finish the task. WITHOUT "
    "calling any tool (none are available on this turn), decide now:\n"
    "1. the exact files you will create or edit next, and what changes in "
    "each — commit to a concrete first edit;\n"
    "2. what you already know that makes that edit safe (the invariants and "
    "callers you have seen);\n"
    "3. what you will verify afterwards.\n"
    "Be concise and concrete. Your next turn should issue the first "
    "write_file or edit_file call."
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
    marker = f"\n[truncated: original {len(text)} chars]"
    # The marker counts AGAINST the ceiling, so the retained plan never
    # exceeds the configured bound; a ceiling too small to hold even the
    # marker degrades to the marker alone, still discoverable.
    keep = max(0, ceiling - len(marker))
    return f"{text[:keep]}{marker}"


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
    :func:`colleague.effortspikes.resolve_spike` declines BOTH decision
    points (the barrier and the stall turn; ``COLLEAGUE_EFFORT_SPIKES=0``).
    Nothing is built, no engine is loaded, and the loop keeps the pre-#484
    path byte for byte. A partially-armed run (one point overridden to
    ``off``) still binds the factory, and each point resolves its own rung
    at fire time.

    Armed, the returned ``factory(engine_name, warn)`` loads that engine and
    returns a TOOLS-OFF completion (``make_complete(seat, tools=[])`` — the
    honest tools-off invariant the deepthink seam relies on) whose replies are
    clamped to :func:`plan_char_ceiling`. It returns ``None`` — after one
    ``warn`` — for an engine with no one-shot completion seam (``mock``) or any
    setup failure, and the caller then simply does not interpose a barrier:
    the all-engines rule holds because an armed ``mock`` run never crashes, it
    records why.
    """
    if all(effortspikes.resolve_spike(p) is None for p in (BARRIER_POINT, STALL_POINT)):
        return None
    from colleague import registry

    loader = engine_loader if engine_loader is not None else registry.load

    def factory(
        engine_name: str, warn: Callable[[str], None], *, point: str = BARRIER_POINT
    ) -> Optional[CompleteFn]:
        rung = effortspikes.resolve_spike(point)
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


#: The tool NAMES whose first appearance in a turn is the barrier's trigger,
#: and whose earlier appearance in the run cancels it (#487). Narrower than
#: :func:`is_mutating_tool` on purpose: ``run_command`` stays a mutating tool
#: for roles and policy, but a survey that opens with ``git status`` or
#: ``wc -l`` is still a survey — the v0 precondition ("every prior step
#: read-only") latched shut on that first shell command and could never fire
#: on 3 of 5 measured dispatches (rows 72-73). Still a name lookup, never
#: content: a ``sed -i`` inside ``run_command`` slips past, and that is
#: documented rather than inspected.
FILE_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


def is_file_write_tool(name: str) -> bool:
    """Whether *name* is one of :data:`FILE_WRITE_TOOLS` (a name lookup only)."""
    return name in FILE_WRITE_TOOLS


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
    * the run has completed at least one step and NO step so far named a
      file-writing tool (:data:`FILE_WRITE_TOOLS`, #487) — i.e. the tree is
      still untouched, whatever shell commands the survey ran;
    * this turn asks for at least one file-writing tool.
    """
    if ctx.barrier_complete is None or effortspikes.resolve_spike(BARRIER_POINT) is None:
        return False
    if barrier_fired(ctx.result):
        return False
    steps = ctx.result.steps
    if not steps or any(is_file_write_tool(step.tool) for step in steps):
        return False
    return any(is_file_write_tool(getattr(call, "name", "")) for call in calls or ())


# ---------------------------------------------------------------------------
# The firing
# ---------------------------------------------------------------------------


def _note_decay_reset(ctx: "_Work") -> None:
    """The barrier is a reset point for effort decay (a no-op when decay is unarmed)."""
    from colleague import loop_gateescalation as _gateescalation

    _gateescalation.note_reset(ctx)


def _warn(ctx: "_Work", detail: str) -> None:
    ctx.result.warnings.append({"kind": "effort-spike-barrier", "detail": detail})


# ---------------------------------------------------------------------------
# stall.no_write — the count-keyed decision turn
# ---------------------------------------------------------------------------


def stall_fires(result: Any) -> int:
    """How many times ``stall.no_write`` already fired this run (the artifact IS the state)."""
    return sum(
        1
        for entry in getattr(result, "effort_spikes", None) or ()
        if isinstance(entry, dict) and entry.get("point") == STALL_POINT
    )


def turns_since_last_mark(ctx: "_Work") -> int:
    """Acting turns since the latest mark: run start, any spike firing, any file write.

    Marks are model-turn counts recorded on ``ctx._stall_marks`` — by
    :func:`note_stall_mark` when a spike fires and by :func:`note_file_write`
    when a file-writing tool call executes (stamped at the turn it happened,
    never reconstructed from step positions: one response can carry several
    calls, Qodo #491 t5). The count is ``stats.model_turns`` minus the latest
    mark. Nothing here reads tool arguments or model text.
    """
    turns = int(getattr(ctx.result.stats, "model_turns", 0))
    marks = getattr(ctx, "_stall_marks", None) or ()
    last = max(marks) if marks else 0
    return max(0, turns - last)


def note_file_write(ctx: "_Work", tool_name: str) -> None:
    """A file-writing tool call executed now: a stall mark at the current turn (name lookup)."""
    if not is_file_write_tool(tool_name):
        return
    marks = getattr(ctx, "_stall_marks", None)
    if marks is not None:
        marks.append(int(getattr(ctx.result.stats, "model_turns", 0)))


def note_stall_mark(ctx: "_Work") -> None:
    """Record 'a spike fired now' as a stall mark (any spike restarts the count)."""
    marks = getattr(ctx, "_stall_marks", None)
    if marks is not None:
        marks.append(int(getattr(ctx.result.stats, "model_turns", 0)))


def should_fire_stall(ctx: "_Work", calls: Any) -> bool:
    """Whether THIS turn is a stall decision moment (a count over tool names).

    All must hold: the point is armed and a seat factory bound; this turn
    requests no file-writing tool (a turn that finally writes is not a stall);
    fewer than :data:`colleague.effortspikes.STALL_MAX_FIRES` firings so far;
    and at least :data:`colleague.effortspikes.STALL_TURNS` acting turns since
    the last mark.
    """
    if ctx.barrier_complete is None or effortspikes.resolve_spike(STALL_POINT) is None:
        return False
    if any(is_file_write_tool(getattr(call, "name", "")) for call in calls or ()):
        return False
    if stall_fires(ctx.result) >= effortspikes.STALL_MAX_FIRES:
        return False
    return turns_since_last_mark(ctx) >= effortspikes.STALL_TURNS


def intercept_stall(ctx: "_Work", calls: Any) -> bool:
    """Interpose the stall decision turn; ``True`` if it consumed the turn."""
    if not should_fire_stall(ctx, calls):
        return False
    return _interpose(ctx, STALL_POINT, STALL_PROMPT, PHASE_STALL)


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
    return _interpose(ctx, BARRIER_POINT, BARRIER_PROMPT, PHASE_BARRIER)


def _call_factory(factory: Any, engine_name: str, warn: Any, point: str) -> Optional[CompleteFn]:
    """Invoke a seat factory under the documented ``(engine_name, warn)`` contract.

    The production factory (:func:`make_barrier_complete`) also accepts an
    optional ``point`` keyword so a non-barrier decision point resolves ITS
    rung; an injected two-argument factory (the ``ContextControls``
    contract, every test double) is called exactly as before and serves the
    barrier's rung for every point — a compatibility rule, never a
    ``TypeError`` escaping the loop (Qodo #491 t8).
    """
    if point != BARRIER_POINT:
        try:
            params = inspect.signature(factory).parameters
        except (TypeError, ValueError):  # a callable without an inspectable signature
            params = {}
        if "point" in params:
            return factory(engine_name, warn, point=point)
    return factory(engine_name, warn)


def _interpose(ctx: "_Work", point: str, prompt: str, phase: str) -> bool:
    """Run one tools-off decision turn for *point* (the barrier's mechanism, shared)."""
    rung = cast(str, effortspikes.resolve_spike(point))

    def warn(text: str) -> None:
        _warn(ctx, text)

    complete = _call_factory(ctx.barrier_complete, ctx.task.engine, warn, point)
    if complete is None:
        return False
    request = list(ctx.messages) + [{"role": "user", "content": prompt}]
    _emit_phase(ctx, phase)
    try:
        resp = complete(request)
    except Exception as exc:  # noqa: BLE001 - a planning turn never aborts the run
        _warn(ctx, f"{point} decision turn failed ({type(exc).__name__}: {exc})")
        return False
    # Honest accounting first: the completion HAPPENED, so its usage and its
    # turn count land on WorkStats whether or not it produced a usable plan.
    _account_turn(ctx, resp)
    ctx.result.effort_spikes.append(
        effortspikes.SpikeRecord(point=point, rung=rung, seat=ctx.seat).to_dict()
    )
    note_stall_mark(ctx)
    _note_decay_reset(ctx)
    plan = (resp.content or "").strip()
    if not plan:
        # No plan to inject: do not swallow the turn the model actually wanted.
        # The spike is still recorded (it fired) and the turn is still counted.
        return False
    ctx.result.steps.append(Step(len(ctx.result.steps), point, {"rung": rung}, plan, ok=True))
    ctx.messages.append({"role": "assistant", "content": plan})
    return True

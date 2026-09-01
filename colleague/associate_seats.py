"""The enumerated associate seats — where the fast NON-coding mind is consumed (t19).

adopt-from-qwen-code arc (spec docs/specs/2026-08-27-adopt-from-qwen-code.md,
claims c33/h22, decision c32; plan task t19). Task t18 built the seat
(:mod:`colleague.associate`: the ``EngineConfig`` an associate call runs
against, addressed on the wire by ROLE NAME); this module is the ONE place
that says WHICH work goes there. :data:`ASSOCIATE_SEATS` is a fixed,
enumerated tuple — never a routing policy: the runtime never picks a model
per turn, each seat below is a named call site that always resolves the same
way.

The five seats (c33):

* ``scout`` — the read-only scout subagent role (:mod:`colleague.roles`
  ``scout``): a child that reads, greps and reports, on the associate model;
* ``compact`` — the fill-line compaction summary author
  (``loop._compact_history``);
* ``synthesis`` — forced final synthesis (#191/#202/#248,
  ``loop._maybe_force_synthesis``);
* ``digest`` — the lint / affected-tests digest. ENUMERATED, NOT CONSUMED:
  neither gate makes a model completion today (``colleague/lint.py`` and
  ``colleague/affectedtests.py`` are shell-outs), so there is no call site to
  swap — the row exists so the tuple is the complete list the spec names;
* ``distill`` — the rung-2 lesson-distillation author rung
  (:func:`distill_author`, consumed by ``colleague.distill``'s resolvers
  AFTER deepthink/muse and BEFORE the cortex floor).

Resolution precedence per seat: deepthink/muse (where a seat has that rung)
> associate > cortex. The two branches the operator decision c32 names:

* **UNARMED** (``COLLEAGUE_ASSOCIATE_MODEL`` unset → ``config.associate`` is
  ``None``): every seat runs EXACTLY as today — the acting completion, the
  acting effort, nothing added. This is the arc's byte-identical pin
  (h1/c44): an unset knob changes nothing. (The plan's "unarmed → cortex@low"
  wording is realised for the one NEW surface, the ``scout`` role, via its
  ``ROLE_TABLE`` row — a new role has no pre-arc behaviour to keep.)
* **ARMED but UNREACHABLE** (the adapter's one role-alias retry exhausted, a
  network/HTTP failure, an engine without one-shot completions): the seat
  falls to **cortex@off** (v4 #475, :data:`FALLBACK_EFFORT`) and records ONE
  warning naming the seat, failure and fallback on ``TaskResult.warnings``.
  Never silent, never a refusal.

Code-authoring seats (the acting loop, ``writer`` children, the design and
evaluator seats) never reference the associate config — pinned by the AST
guard in ``tests/test_associate_seats.py``.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Optional, cast

from colleague import effort as _effort
from colleague import efforttables as _efforttables
from colleague.associate import associate_engine_config
from colleague.config import EngineConfig
from colleague.context import window_messages

__all__ = [
    "ASSOCIATE_SEATS",
    "FALLBACK_EFFORT",
    "SCOUT_ROLE",
    "SeatCompleteFactory",
    "distill_author",
    "fallback_seat_config",
    "fallback_warning",
    "make_associate_complete",
    "resolve_associate_seat_config",
    "scout_child_config",
    "window_to_seat",
]

#: The FIXED, ENUMERATED set of associate-eligible seats (c33/h22). Adding a
#: seat here is a spec change; nothing else in the runtime may route to the
#: associate config.
ASSOCIATE_SEATS: tuple[str, ...] = ("scout", "compact", "synthesis", "digest", "distill")

#: The typed subagent role that runs on the associate seat.
SCOUT_ROLE = "scout"

#: The unreachable-seat fallback rung — v4 (#475), two models, one seat:
#: cortex occupying the associate seat over-thinks a shallow lane above "off".
FALLBACK_EFFORT = "off"

#: ``messages -> ModelResponse`` (the loop's own ``CompleteFn`` shape, left
#: untyped here to avoid importing the loop).
CompleteFn = Callable[[list[dict[str, Any]]], Any]
#: ``(seat, warn, *, count_tokens=None, lane_budget=None) -> CompleteFn | None``
#: — see :func:`make_associate_complete` (the two keyword-only knobs feed
#: :func:`window_to_seat`; ``Callable`` cannot spell keyword-only parameters).
SeatCompleteFactory = Callable[..., Optional[CompleteFn]]


def _check_seat(seat: str) -> None:
    if seat not in ASSOCIATE_SEATS:
        raise ValueError(
            f"unknown associate seat {seat!r}; the enumerated seats are {ASSOCIATE_SEATS}"
        )


def resolve_associate_seat_config(config: EngineConfig, seat: str) -> EngineConfig:
    """The :class:`EngineConfig` *seat* completes against.

    ARMED → the associate seat config (:func:`associate_engine_config` — wire
    model = the role name, the seat's own endpoint/key/budget, the
    ``associate`` effort row). UNARMED → *config* itself, the very same
    object, so the caller's path is byte-identical to main.
    """
    _check_seat(seat)
    seat_config = associate_engine_config(config, sub_seat=seat)
    return seat_config if seat_config is not None else config


def fallback_seat_config(config: EngineConfig, seat: str) -> EngineConfig:
    """cortex@off — the acting config at the :data:`FALLBACK_EFFORT` rung.

    The unreachable-associate branch of c32: a replace of *config* (per-call
    knobs cleared like the other one-shot seat builders) with an explicit
    ``off`` ``reasoning_effort_seat`` (v4 #475) — ``default`` still wins.
    """
    _check_seat(seat)
    low = cast(EngineConfig, dataclasses.replace(config, on_delta=None, refresh_seat=None))
    setattr(
        low,
        "reasoning_effort_seat",
        _effort.resolve_effort(
            kill_switch=(config.reasoning_effort == "default"),
            seat_override=FALLBACK_EFFORT,
            seat="cortex",
        ),
    )
    return low


def fallback_warning(seat: str, reason: str) -> str:
    """The ONE recorded warning an unreachable associate seat leaves behind."""
    return (
        f"associate seat '{seat}' unreachable ({reason}) — "
        f"fell back to cortex at thinking effort '{FALLBACK_EFFORT}'"
    )


def window_to_seat(
    messages: list[dict[str, Any]],
    seat_config: object,
    *,
    count_tokens: Optional[Callable[[list[dict[str, Any]]], int]] = None,
    lane_budget: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Window *messages* to the SEAT's ``context_budget_tokens`` before dispatch.

    The compact / synthesis lanes build their message lists against the
    parent's ``ContextControls`` budget (the MAIN window); the associate seat's
    own budget is clamped to its SERVED window (#460, ``served_window_budget``)
    and can be smaller — e.g. 128,000 on the reference rig under a 200,000+
    cortex budget. Rather than letting an overlong request fail on the wire
    and land on the cortex@off fallback, this trims it with the loop's own
    primitive (:func:`colleague.context.window_messages` — head + most recent
    turns, one elision placeholder, the same *count_tokens* the lane already
    windowed with; the chars/4 estimate when ``None``). Pass-through (the same
    list object, byte-identical) when the seat carries no positive budget,
    when *lane_budget* is known and the seat's budget is NOT smaller than it,
    or when the request already fits.
    """
    seat_budget = getattr(seat_config, "context_budget_tokens", None)
    if not isinstance(seat_budget, int) or isinstance(seat_budget, bool) or seat_budget <= 0:
        return messages
    if isinstance(lane_budget, int) and lane_budget > 0 and seat_budget >= lane_budget:
        return messages
    return window_messages(messages, seat_budget, count_tokens)


def make_associate_complete(
    config: EngineConfig,
    engine_name: str,
    *,
    engine_loader: Optional[Callable[[str], Any]] = None,
) -> Optional[SeatCompleteFactory]:
    """Bind the seat-completion factory the loop consults for its seats.

    ``None`` when unarmed (``config.associate`` is ``None``) — the loop then
    keeps its acting ``complete`` for every seat, byte-identical to main.
    Armed: ``factory(seat, warn, *, count_tokens=None, lane_budget=None)``
    returns a tools-off completion on the associate seat that, on ANY
    exception, calls ``warn(text)`` once and completes the ORIGINAL messages
    on cortex@off instead; it returns ``None`` (after ``warn``) when the
    engine has no one-shot completion seam (the ``mock`` engine), so the
    caller keeps its acting completion — the all-engines rule holds: an armed
    mock run never crashes, it records why.

    Seat windowing (Qodo #464 / #460): the loop windows a lane's request to
    the MAIN budget, which can exceed the associate's served window. Before
    the associate dispatch the request is therefore trimmed to the SEAT's
    ``context_budget_tokens`` via :func:`window_to_seat` — the caller's
    *count_tokens* and *lane_budget* decide whether anything is cut; the seat
    budget not smaller than the lane's, or a request that already fits, is a
    pass-through of the very same list. Honest limit that remains: the count
    is the lane's estimator (calibrated on the cortex tokenizer, or chars/4),
    not the associate model's own tokenizer, so a request the estimate calls
    fitting can still fail on the wire — that case still lands on the fallback
    branch above (defence in depth), never a crash.
    """
    if config.associate is None:
        return None
    from colleague import registry

    loader = engine_loader if engine_loader is not None else registry.load

    def factory(
        seat: str,
        warn: Callable[[str], None],
        *,
        count_tokens: Optional[Callable[[list[dict[str, Any]]], int]] = None,
        lane_budget: Optional[int] = None,
    ) -> Optional[CompleteFn]:
        _check_seat(seat)
        try:
            engine = loader(engine_name)
            seat_config = resolve_associate_seat_config(config, seat)
            primary = engine.make_complete(seat_config, tools=[])
        except NotImplementedError as exc:
            warn(fallback_warning(seat, f"engine '{engine_name}': {exc}"))
            return None
        except Exception as exc:  # noqa: BLE001 — Qodo #441-7: setup failures fall back too
            warn(fallback_warning(seat, f"setup {type(exc).__name__}: {exc}"))
            return engine.make_complete(fallback_seat_config(config, seat), tools=[])

        def complete(messages: list[dict[str, Any]]) -> Any:
            try:
                request = window_to_seat(
                    messages, seat_config, count_tokens=count_tokens, lane_budget=lane_budget
                )
                return primary(request)
            # every failure shape falls back, recorded
            except Exception as exc:  # noqa: BLE001
                warn(fallback_warning(seat, f"{type(exc).__name__}: {exc}"))
                low = engine.make_complete(fallback_seat_config(config, seat), tools=[])
                return low(messages)

        return complete

    return factory


def scout_child_config(
    parent_config: EngineConfig,
    child: EngineConfig,
    role: Optional[str],
    *,
    effort_override: Optional[str],
) -> EngineConfig:
    """Swap a ``scout`` child onto the associate seat (c33/h22).

    Called by :func:`colleague.subagents._build_child_config` after the bare
    child config is built. Not a scout, or UNARMED → *child* unchanged (the
    same object: an unarmed scout runs on cortex at its ``ROLE_TABLE`` rung).
    ARMED → the child's config replaced onto the associate seat (wire model =
    the role name, the seat's endpoint/key), its context budget the SMALLER
    of the child's share and the seat's own, and its rung resolved on the
    ``associate`` seat row with the spawn's explicit *effort_override* (the
    highest-precedence input) winning above it — never the parent's own rung.
    The child's ``role`` stays ``scout``, so the executor's allow-list (the
    refusal half) and the curated schema (the offered half) both stay the
    strict read-only subset.
    """
    if role != SCOUT_ROLE:
        return child
    seat = associate_engine_config(child, sub_seat=SCOUT_ROLE)
    if seat is None:
        return child
    seat.context_budget_tokens = min(child.context_budget_tokens, seat.context_budget_tokens)
    setattr(
        seat,
        "reasoning_effort_seat",
        _efforttables.resolve_associate_sub_seat_effort(
            kill_switch=(parent_config.reasoning_effort == "default"),
            parent_override=effort_override,
            seat_override=parent_config.reasoning_effort_seats.get(f"associate.{SCOUT_ROLE}"),
            row_override=parent_config.reasoning_effort_seats.get("associate"),
            seat=SCOUT_ROLE,
        ),
    )
    return seat


def distill_author(config: object) -> Optional[Any]:
    """The rung-2 distillation author rung on the associate seat, or ``None``.

    Consumed by both :mod:`colleague.distill` resolvers AFTER the deepthink/
    muse rung and BEFORE the lobes-cortex floor (c33: precedence deepthink/
    muse > associate > cortex). Names the WIRE model (the role name for a
    proxied seat — the distill child dispatches through the same gateway that
    completed ``{"model": "associate"}``) with the seat's own endpoint and key.
    """
    assoc = getattr(config, "associate", None)
    if assoc is None:
        return None
    from colleague.distill import DistillAuthor

    seats = getattr(config, "reasoning_effort_seats", None) or {}
    return DistillAuthor(
        model=assoc.wire_model,
        base_url=assoc.base_url,
        api_key=assoc.api_key,
        effort=_efforttables.resolve_associate_sub_seat_effort(
            kill_switch=(getattr(config, "reasoning_effort", None) == "default"),
            seat_override=seats.get("associate.distill"),
            row_override=seats.get("associate"),
            seat="distill",
        ),
    )

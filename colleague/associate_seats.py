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
  ``ROLE_TABLE`` row ``low`` — a new role has no pre-arc behaviour to keep.)
* **ARMED but UNREACHABLE** (the adapter's one role-alias retry exhausted, a
  network/HTTP failure, an engine without one-shot completions): the seat
  falls to **cortex@low** — the acting config with the ``low`` rung — and
  records ONE warning naming the seat, the failure and the fallback on
  ``TaskResult.warnings``. Never silent, never a refusal.

Code-authoring seats (the acting loop, ``writer`` children, the design and
evaluator seats) never reference the associate config — pinned by the AST
guard in ``tests/test_associate_seats.py``.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Optional, cast

from colleague import effort as _effort
from colleague.associate import associate_engine_config
from colleague.config import EngineConfig

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
]

#: The FIXED, ENUMERATED set of associate-eligible seats (c33/h22). Adding a
#: seat here is a spec change; nothing else in the runtime may route to the
#: associate config.
ASSOCIATE_SEATS: tuple[str, ...] = ("scout", "compact", "synthesis", "digest", "distill")

#: The typed subagent role that runs on the associate seat.
SCOUT_ROLE = "scout"

#: The rung the cortex fallback runs at when an ARMED seat is unreachable.
FALLBACK_EFFORT = "low"

#: ``messages -> ModelResponse`` (the loop's own ``CompleteFn`` shape, left
#: untyped here to avoid importing the loop).
CompleteFn = Callable[[list[dict[str, Any]]], Any]
#: ``(seat, warn) -> CompleteFn | None`` — see :func:`make_associate_complete`.
SeatCompleteFactory = Callable[[str, Callable[[str], None]], Optional[CompleteFn]]


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
    seat_config = associate_engine_config(config)
    return seat_config if seat_config is not None else config


def fallback_seat_config(config: EngineConfig, seat: str) -> EngineConfig:
    """cortex@low — the acting config at the :data:`FALLBACK_EFFORT` rung.

    The unreachable-associate branch of c32: a replace of *config* (per-call
    knobs cleared exactly like the other one-shot seat builders) with the
    seat's ``reasoning_effort_seat`` resolved as an explicit ``low`` override
    on the cortex seat — the global ``default`` kill switch still wins.
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


def make_associate_complete(
    config: EngineConfig,
    engine_name: str,
    *,
    engine_loader: Optional[Callable[[str], Any]] = None,
) -> Optional[SeatCompleteFactory]:
    """Bind the seat-completion factory the loop consults for its seats.

    ``None`` when unarmed (``config.associate`` is ``None``) — the loop then
    keeps its acting ``complete`` for every seat, byte-identical to main.
    Armed: ``factory(seat, warn)`` returns a tools-off completion on the
    associate seat that, on ANY exception, calls ``warn(text)`` once and
    completes the same messages on cortex@low instead; it returns ``None``
    (after ``warn``) when the engine has no one-shot completion seam (the
    ``mock`` engine), so the caller keeps its acting completion — the
    all-engines rule holds: an armed mock run never crashes, it records why.

    Honest limit: the loop windows a seat's request to the MAIN budget; a
    request larger than the associate's own window fails on the wire and
    lands on the fallback branch above.
    """
    if config.associate is None:
        return None
    from colleague import registry

    loader = engine_loader if engine_loader is not None else registry.load

    def factory(seat: str, warn: Callable[[str], None]) -> Optional[CompleteFn]:
        _check_seat(seat)
        try:
            engine = loader(engine_name)
            primary = engine.make_complete(resolve_associate_seat_config(config, seat), tools=[])
        except NotImplementedError as exc:
            warn(fallback_warning(seat, f"engine '{engine_name}': {exc}"))
            return None
        except Exception as exc:  # noqa: BLE001 — Qodo #441-7: setup failures fall back too
            warn(fallback_warning(seat, f"setup {type(exc).__name__}: {exc}"))
            return engine.make_complete(fallback_seat_config(config, seat), tools=[])

        def complete(messages: list[dict[str, Any]]) -> Any:
            try:
                return primary(messages)
            except Exception as exc:  # noqa: BLE001 — every failure shape falls back, recorded
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
    seat = associate_engine_config(child)
    if seat is None:
        return child
    seat.context_budget_tokens = min(child.context_budget_tokens, seat.context_budget_tokens)
    setattr(
        seat,
        "reasoning_effort_seat",
        _effort.resolve_effort(
            kill_switch=(parent_config.reasoning_effort == "default"),
            parent_override=effort_override,
            seat_override=parent_config.reasoning_effort_seats.get("associate"),
            seat="associate",
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

    return DistillAuthor(model=assoc.wire_model, base_url=assoc.base_url, api_key=assoc.api_key)

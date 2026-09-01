"""The named steps :meth:`colleague.config.EngineConfig.resolve` walks.

``resolve`` used to be one 680-line function that called essentially every
helper in ``config.py``. It is now a short sequence of named steps, and this
module holds the ones that do not need to live beside the class: the execution
modes, the main-model rung (+ the stale-pin refresh and the context budget),
the acting-dial repoint, the thinking-effort ladder, and the ~190-line block
of scalar env/config.json knobs.

Split out of ``config.py`` (hard 1000-line file limit, plan
``hard-1000-line-file-limit`` t14). Every step is a PURE move of the code that
already sat inline: same order, same precedence, same comments. The one step
NOT here is the seat-dial step — it stays in ``config.py`` beside the class
because ``tests/test_single_model_default.py`` reads that file for the
``== "lobes"`` sentinel guarding each ``*_lobes_fallback(`` call, and keeping
that pin honest is worth more than a tidier split.
"""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from colleague import effort, efforttables
from colleague.config_defaults import (
    _DEFAULT_AFFECTED_TESTS_DEPTH,
    _DEFAULT_AFFECTED_TESTS_FIX_RETRIES,
    _DEFAULT_AFFECTED_TESTS_MAX_FILES,
    _DEFAULT_AUTOSPLIT_TARGET_TOKENS,
    _DEFAULT_CONTEXT_BUDGET,
    _DEFAULT_FANOUT_FILES,
    _DEFAULT_FILLLINE_THRESHOLD,
    _DEFAULT_LINT_FIX_RETRIES,
    _DEFAULT_MAX_CONTINUE_NUDGES,
    _DEFAULT_MAX_EPISODES,
    _DEFAULT_MAX_OUTPUT_CHARS,
    _DEFAULT_MAX_STEPS,
    _DEFAULT_MODEL,
    _DEFAULT_PLAN_OFFER_TOKENS,
    _DEFAULT_SUBAGENT_CONCURRENCY,
    _DEFAULT_SUBAGENT_DEPTH,
    _DEFAULT_SUBAGENT_TOTAL,
    _DEFAULT_SYNTHESIS_RESERVE,
    _DEFAULT_TEMPERATURE,
    _DEFAULT_TESTINTEGRITY_FIX_RETRIES,
    _DEFAULT_TIMEOUT,
    _DEFAULT_TOO_LONG_MIN,
)
from colleague.config_files import (
    FileOverrides,
    _file_or_default,
    _pick,
    _str,
    _try_float,
    _try_int,
    _try_int_or_none,
)
from colleague.config_flags import (
    _resolve_acting_add_tools,
    _resolve_affected_tests_enabled,
    _resolve_agents_enabled,
    _resolve_coherence_enabled,
    _resolve_distiller_checkpoint,
    _resolve_hire_enabled,
    _resolve_lint_enabled,
    _resolve_memory_distill,
    _resolve_memory_enabled,
    _resolve_testintegrity_enabled,
    _resolve_thought_action_evaluation_enabled,
    _resolve_three_tier_enabled,
    _resolve_until_done_enabled,
    _resolve_watch_enabled,
)
from colleague.config_lobes import _defaults_source, resolve_lobes_gateway_url
from colleague.config_modelpin import _resolution_time_refresh
from colleague.config_seats import (
    _refuse_conflicting_execution_modes,
    _resolve_acting_dial,
    _resolve_evaluation_seats,
    _resolve_worker,
)
from colleague.fillline import DEFAULT_COMPACTION_CAP

if TYPE_CHECKING:
    from colleague.config_types import DeepthinkConfig, EvaluationSeats, WorkerConfig
    from colleague.lobes import ModelRefreshWarning


@dataclass(frozen=True)
class ExecutionModes:
    """The three mutually-exclusive execution modes and the seats they resolve.

    One value object instead of the nine ``resolved_*`` locals ``resolve`` used
    to thread by hand — the same nine values, in the same resolution order.
    """

    three_tier: bool
    worker: "Optional[WorkerConfig]"
    thought_action_evaluation: bool
    agents: bool
    hire: bool
    acting_add_tools: "tuple[str, ...]"
    seats: "Optional[EvaluationSeats]"
    evaluator_checkpoint: "Optional[str]"
    distiller_checkpoint: "Optional[str]"


def resolve_execution_modes(
    files: FileOverrides,
    repo_path: "str | Path | None",
    lobes_roles: object,
    lobes_gateway_url: "str | None",
    base_url: str,
    api_key: str,
) -> ExecutionModes:
    """Arm (or leave dormant) the three execution modes and resolve their seats.

    A verbatim lift of the block that sat inline in ``resolve``: three-tier
    arming + the mandatory worker seat, thought-action-evaluation arming + its
    three seats, model-bound agents, hire, the acting add-set, the
    mutual-exclusion refusal, and the two authority checkpoints.
    """
    # Three-tier execution arming + worker seat resolution
    # (three-tier-execution arc, plan task t3; covers c3/h3/c25/h21).
    # ``resolved_three_tier`` gates whether the worker role is even
    # consulted — NOT armed is a strict no-op (an advertised worker role
    # is read and discarded exactly like reranker, byte-identical to
    # today). ARMED makes the worker role MANDATORY: :func:`_resolve_worker`
    # raises a loud, naming refusal (never falls back to cortex silently
    # acting) rather than ever returning with three_tier True and worker
    # None — the refusal fires HERE, at resolution time, before any
    # episode starts.
    resolved_three_tier = _resolve_three_tier_enabled(files.three_tier)
    # The RAW, no-network operator declaration, hoisted so both execution
    # modes' seat resolution names the same gap the same way (it was
    # already evaluated unconditionally as an argument below).
    declared_lobes_url = resolve_lobes_gateway_url(repo_path)
    resolved_worker = _resolve_worker(
        resolved_three_tier,
        lobes_roles,
        lobes_gateway_url,
        declared_lobes_url,
        base_url,
        api_key,
        files.worker,
    )
    # Thought→action→evaluation seat resolution (post-#387 program, plan
    # task t12; issue #397, spec c17/c26 + h10/h19). An INDEPENDENT opt-in
    # from the block above: not armed is a strict no-op (every seat advert
    # read and discarded, byte-identical), ARMED makes the front/worker/
    # evaluator roles MANDATORY and resolves each BY ROLE NAME. Both modes
    # armed at once refuses first — neither mode silently wins.
    resolved_tae = _resolve_thought_action_evaluation_enabled(files.tae)
    # Model-bound agents (#411 t7): the THIRD independent opt-in; any two
    # armed modes refuse together, naming both.
    resolved_agents = _resolve_agents_enabled(files.agents)
    # hire_colleague arming (t4): independent of every execution mode.
    resolved_hire = _resolve_hire_enabled(files.hire)
    resolved_acting_add = _resolve_acting_add_tools()
    _refuse_conflicting_execution_modes(resolved_three_tier, resolved_tae, resolved_agents)
    resolved_seats = _resolve_evaluation_seats(
        resolved_tae,
        lobes_roles,
        lobes_gateway_url,
        declared_lobes_url,
        base_url,
        api_key,
        files.seats,
    )
    # The authority-separation seam (spec c38/h30): the evaluator's own
    # checkpoint id, flat on the config, is what distill.py's
    # ``_refuses_evaluator_as_distiller`` guard reads to refuse handing the
    # evaluator seat lesson-authoring authority — and the declared
    # distiller checkpoint is what lifts that refusal. Unarmed leaves the
    # former ``None``, so the guard stays exactly as inert as today.
    resolved_evaluator_checkpoint = (
        resolved_seats.evaluator.model if resolved_seats is not None else None
    )
    resolved_distiller_checkpoint = _resolve_distiller_checkpoint(files.distiller)
    return ExecutionModes(
        three_tier=resolved_three_tier,
        worker=resolved_worker,
        thought_action_evaluation=resolved_tae,
        agents=resolved_agents,
        hire=resolved_hire,
        acting_add_tools=resolved_acting_add,
        seats=resolved_seats,
        evaluator_checkpoint=resolved_evaluator_checkpoint,
        distiller_checkpoint=resolved_distiller_checkpoint,
    )


def suppress_deepthink_in_mode(
    deepthink: "Optional[DeepthinkConfig]", three_tier: bool, thought_action_evaluation: bool
) -> "Optional[DeepthinkConfig]":
    """Return *deepthink*, or ``None`` once an execution mode is armed.

    Deepthink absent in three-tier mode (plan task t8; covers c12/h12).
    Once three_tier is armed, no DeepthinkConfig is EVER constructed —
    neither a DECLARED (env/config.json) deepthink nor one discovered
    from the lobes muse role above (``resolved_deepthink`` may already
    hold either) survives. Three-tier's own strong-reasoning seat is
    the worker itself (arc summary: "evaluator absent, deepthink
    absent") — forcing this HERE, before the reviewer-default backfill
    just below reads ``resolved_deepthink``, means that backfill (t7)
    also sees no deepthink to borrow a reviewer model from, staying
    consistent with deepthink's total absence. Legacy (three_tier
    False) is completely untouched: resolved_deepthink keeps whatever
    _resolve_deepthink/_deepthink_lobes_fallback already computed above.

    The thought→action→evaluation mode (t12) takes the IDENTICAL stance
    for the identical reason: its evaluator seat is the mode's judgment
    surface, so a second, differently-resolved judgment escalation would
    be exactly the ambiguity the fixed authority boundary exists to
    remove (acceptance criterion 3 — "deepthink stays absent in this mode
    as in three-tier"). Unarmed keeps every legacy deepthink path
    untouched.
    """
    if three_tier or thought_action_evaluation:
        return None
    return deepthink


def resolve_main_model(
    model: "str | None",
    files: FileOverrides,
    lobes_model: "str | None",
    lobes_gateway_url: "str | None",
    lobes_roles: object,
    api_key: str,
    ov: object,
    *,
    worker_armed: bool,
) -> "tuple[str, Optional[ModelRefreshWarning], int]":
    """The main model id (+ any stale-pin refresh) and the context budget.

    Precedence unchanged: explicit arg > env > config.json > the lobes cortex
    advert > the builtin default; the resolution-time same-role refresh then
    gets its one look at the result.
    """
    # Lobes rung (t4): the gateway's cortex model is the default only for the
    # main model id, below config.json and above the builtin. A plain if/else
    # (not a nested ternary, SonarCloud S3358), mirroring base_url_default above.
    model_default = _defaults_source(files.cfg_model, lobes_model, _DEFAULT_MODEL)

    resolved_model = _pick(
        model,
        "COLLEAGUE_MODEL",
        "CONVERTIBLE_MODEL",
        default=model_default,
    )
    resolved_model, model_refresh_warning = _resolution_time_refresh(
        resolved_model,
        model,
        files.cfg_model,
        lobes_gateway_url,
        lobes_roles,
        api_key,
        three_tier_armed=worker_armed,
    )
    resolved_context_budget_tokens = int(
        _pick(
            _str(ov.context_budget_tokens),
            "COLLEAGUE_CONTEXT_BUDGET",
            "CONVERTIBLE_CONTEXT_BUDGET",
            default=str(_DEFAULT_CONTEXT_BUDGET),
        )
    )
    # Worker-as-actor wiring (three-tier-execution arc, plan task t8;
    # covers c12/h12). Once three_tier is ARMED and the worker seat
    # resolved above, the ACTING dial — model/base_url/api_key/
    return resolved_model, model_refresh_warning, resolved_context_budget_tokens


def resolve_acting_dial_step(
    worker: "Optional[WorkerConfig]",
    seats: "Optional[EvaluationSeats]",
    main: "tuple[str, str, str, int]",
) -> "tuple[str, str, str, int]":
    """Repoint the ACTING dial onto the worker seat when a mode armed one.

    Worker-as-actor wiring (three-tier-execution arc, plan task t8;
    covers c12/h12). Once three_tier is ARMED and the worker seat
    resolved above, the ACTING dial — model/base_url/api_key/
    context_budget_tokens, exactly what the vllm-openai engine drives
    the bounded tool loop with — becomes the WORKER's own resolution,
    never cortex's ("the worker drives the tool loop and cortex does
    not act"). cortex's own resolved base_url/api_key/model (the
    ``resolved_*`` locals above) still feed the senses/voice/deepthink
    default-to-main rungs UNCHANGED — this override happens only here,
    at the very end of resolution, so it can never leak backwards into
    another rung's "defaults to the main endpoint" precedent.
    ``resolved_worker`` is guaranteed non-None whenever
    ``resolved_three_tier`` is True (a broken worker already raised a
    loud refusal above, via :func:`_resolve_worker`), so this is a
    plain presence check, never a second refusal path. The loop itself
    (colleague/loop.py) is UNTOUCHED by this task — it simply drives
    whatever ``EngineConfig`` hands back, exactly as it always has.

    The thought→action→evaluation mode (plan task t13) MIRRORS this
    mechanism rather than inventing a second one: with the mode armed, the
    acting dial becomes ``evaluation_seats.worker``'s own resolution, for
    the identical reason ("the worker acts; the evaluator judges and does
    not act"). t12 deliberately left the dial alone and said so; this is
    that repoint. The two modes are mutually exclusive by refusal
    (:func:`_refuse_conflicting_execution_modes`), so the two branches can
    never both fire. The evaluator's own checkpoint stays on
    ``evaluator_checkpoint`` — which is exactly what keeps
    ``distill.py``'s authority-separation guard (spec c38/h30) able to
    refuse the evaluator seat lesson-authoring authority: the guard reads
    ``evaluator_checkpoint``, never ``config.model``, so repointing the
    acting dial cannot weaken it.
    """
    return _resolve_acting_dial(worker, seats, main=main)


def resolve_effort_knobs(files: FileOverrides) -> "tuple[Optional[str], dict, dict, int]":
    """The per-seat thinking-effort ladder: global rung, seat + purpose tables."""
    # Per-seat thinking-effort ladder (#416 t2, validated via
    # effort.validate_effort/c37; parsing lives in colleague.effort,
    # SonarCloud S3776 extraction) + t1's associate/purpose overrides
    # (colleague.efforttables, a ratchet-safe sibling).
    (
        resolved_reasoning_effort,
        resolved_reasoning_effort_seats,
        resolved_too_long_min,
    ) = effort.resolve_reasoning_effort_overrides(
        _pick,
        files.reasoning_effort,
        files.reasoning_effort_seats,
        files.too_long_min,
        _DEFAULT_TOO_LONG_MIN,
    )
    resolved_reasoning_effort_seats.update(
        efforttables.resolve_associate_seat_overrides(_pick, files.reasoning_effort_seats)
    )
    resolved_reasoning_effort_purposes = efforttables.resolve_purpose_overrides(
        _pick, files.reasoning_effort_purposes
    )
    return (
        resolved_reasoning_effort,
        resolved_reasoning_effort_seats,
        resolved_reasoning_effort_purposes,
        resolved_too_long_min,
    )


# ---------------------------------------------------------------------------
# Temperature knob deprecation (reasoning-aware-sampling-defaults arc, plan
# task t7, spec c9/h11 + c42/h32).
#
# The flat scalar temperature knob is being replaced by the per-half table in
# ``colleague.sampling`` (t2) / the tracked ``.colleague/models.json`` file
# (t3). ``CONVERTIBLE_TEMPERATURE`` — the legacy rename alias — is removed
# NOW: the scalar block below no longer reads it at all, and a run that still
# sets it gets a loud warning rather than a silent no-op.
# ``COLLEAGUE_TEMPERATURE`` itself is DEPRECATED over one release: it still
# applies THIS release and still means exactly what it means today (a single
# scalar `EngineConfig.temperature`), but warns — naming
# ``.colleague/models.json`` as the replacement, and naming explicitly that
# a single value collapses BOTH the thinking and non-thinking sampling
# halves to itself (the honesty requirement behind spec acceptance 6: a
# split-by-half world with one flat pin needs a reader to be able to tell
# the two halves collapsed, not just that a number was applied).
#
# Mirrors ``colleague.lobes.ModelRefreshWarning`` / ``vllm_payload.
# _LadderRetryWarning``'s shape and stderr-notice convention exactly: a
# frozen record, a ``message()`` line printed ONCE at resolution time (never
# per-turn — this is a resolution-time env read, not a call-time one), and a
# ``to_dict()`` a downstream fold (``colleague/cli/_commands/_work_support.py``)
# lands on ``TaskResult.warnings`` verbatim.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemperatureDeprecationWarning:
    """One temperature-knob deprecation/removal record (spec c9/h11).

    ``variable`` is the env var name that was set (``CONVERTIBLE_TEMPERATURE``
    or ``COLLEAGUE_TEMPERATURE``); ``kind`` is ``"removed"`` (the value is
    IGNORED — the legacy alias never rejoins the scalar lane) or
    ``"deprecated"`` (the value still APPLIES this release).
    """

    variable: str
    kind: str

    def message(self) -> str:
        if self.kind == "removed":
            return (
                "colleague: CONVERTIBLE_TEMPERATURE is removed and no longer read — "
                "its value is IGNORED. Set COLLEAGUE_TEMPERATURE instead if you need "
                "the single-value scalar (it too is deprecated, see below), or move "
                "to the per-half sampling rows in .colleague/models.json."
            )
        return (
            "colleague: COLLEAGUE_TEMPERATURE is deprecated — it still applies this "
            "release exactly as it does today, but because it is a SINGLE value it "
            "collapses BOTH the thinking and non-thinking sampling halves to this "
            "one temperature. Migrate to the per-half rows in "
            ".colleague/models.json; COLLEAGUE_TEMPERATURE is removed in a later "
            "release."
        )

    def to_dict(self) -> "dict[str, str]":
        return {"variable": self.variable, "kind": self.kind, "message": self.message()}


def _emit_temperature_deprecation_warning(warning: TemperatureDeprecationWarning) -> None:
    """Print *warning*'s message to stderr — mirrors
    :func:`colleague.lobes.emit_model_refresh_warning`'s convention. Never
    raises: a closed/broken stderr must never break the resolution it is
    merely announcing.
    """
    with suppress(OSError):
        print(warning.message(), file=sys.stderr)


def _resolve_temperature_deprecation() -> "tuple[TemperatureDeprecationWarning, ...]":
    """Detect + emit the temperature-knob deprecation/removal warnings.

    Reads the environment directly (not via :func:`_pick`, which already
    hides whether a variable was actually set) — a truthy/non-empty value
    counts as "set", matching ``_pick``'s own truthiness check. Called
    exactly ONCE per :meth:`~colleague.config.EngineConfig.resolve` — a plain
    run with neither variable set returns ``()`` and prints nothing (h21's
    "a run without it is silent").
    """
    warnings: "list[TemperatureDeprecationWarning]" = []
    if os.environ.get("CONVERTIBLE_TEMPERATURE"):
        warnings.append(TemperatureDeprecationWarning("CONVERTIBLE_TEMPERATURE", "removed"))
    if os.environ.get("COLLEAGUE_TEMPERATURE"):
        warnings.append(TemperatureDeprecationWarning("COLLEAGUE_TEMPERATURE", "deprecated"))
    for warning in warnings:
        _emit_temperature_deprecation_warning(warning)
    return tuple(warnings)


def resolve_scalar_knobs(
    ov: object,
    max_steps: "int | None",
    files: FileOverrides,
    testintegrity_reviewer_model: str,
) -> "dict[str, object]":
    """Every scalar ``env > config.json > builtin`` knob, as ``cls(**kwargs)`` input.

    The block that used to sit inside ``resolve``'s ``return cls(...)`` call,
    moved wholesale: same knobs, same env names, same defaults, same comments.
    Excluded (they come from other steps): ``base_url`` / ``api_key`` /
    ``model`` / ``context_budget_tokens`` / ``lobes_context`` and every seat,
    mode and effort field.

    ``temperature`` is the one exception to "same env names": the
    ``CONVERTIBLE_TEMPERATURE`` alias is REMOVED (spec c9/h11, plan t7) —
    ``COLLEAGUE_TEMPERATURE`` alone resolves it, and
    :func:`_resolve_temperature_deprecation` fires the deprecation/removal
    warnings this knob's env source now carries.
    """
    temperature_deprecation_warnings = _resolve_temperature_deprecation()
    return {
        "max_steps": int(
            _pick(
                _str(max_steps),
                "COLLEAGUE_MAX_STEPS",
                "CONVERTIBLE_MAX_STEPS",
                default=str(_DEFAULT_MAX_STEPS),
            )
        ),
        "temperature": float(
            _pick(
                None,
                "COLLEAGUE_TEMPERATURE",
                default=str(_DEFAULT_TEMPERATURE),
            )
        ),
        "temperature_deprecation_warnings": temperature_deprecation_warnings,
        "timeout": float(
            _pick(
                None,
                "COLLEAGUE_TIMEOUT",
                "CONVERTIBLE_TIMEOUT",
                default=str(_DEFAULT_TIMEOUT),
            )
        ),
        "max_output_chars": int(
            _pick(
                _str(ov.max_output_chars),
                "COLLEAGUE_MAX_OUTPUT_CHARS",
                "CONVERTIBLE_MAX_OUTPUT_CHARS",
                default=str(_DEFAULT_MAX_OUTPUT_CHARS),
            )
        ),
        "subagent_concurrency": _try_int(
            _pick(
                _str(ov.subagent_concurrency),
                "COLLEAGUE_SUBAGENT_CONCURRENCY",
                "CONVERTIBLE_SUBAGENT_CONCURRENCY",
                default=str(_DEFAULT_SUBAGENT_CONCURRENCY),
            ),
            default=_DEFAULT_SUBAGENT_CONCURRENCY,
        ),
        "subagent_depth": _try_int(
            _pick(
                None,
                "COLLEAGUE_SUBAGENT_DEPTH",
                "CONVERTIBLE_SUBAGENT_DEPTH",
                default=str(_DEFAULT_SUBAGENT_DEPTH),
            ),
            default=_DEFAULT_SUBAGENT_DEPTH,
        ),
        "subagent_total": _try_int(
            _pick(
                None,
                "COLLEAGUE_SUBAGENT_TOTAL",
                "CONVERTIBLE_SUBAGENT_TOTAL",
                default=str(_DEFAULT_SUBAGENT_TOTAL),
            ),
            default=_DEFAULT_SUBAGENT_TOTAL,
        ),
        "autosplit_target_tokens": int(
            _pick(
                _str(ov.autosplit_target_tokens),
                "COLLEAGUE_AUTOSPLIT_TARGET",
                "CONVERTIBLE_AUTOSPLIT_TARGET",
                default=str(_DEFAULT_AUTOSPLIT_TARGET_TOKENS),
            )
        ),
        "fillline_threshold": _try_float(
            _pick(
                _str(ov.fillline_threshold),
                "COLLEAGUE_FILLLINE_THRESHOLD",
                "CONVERTIBLE_FILLLINE_THRESHOLD",
                default=str(_DEFAULT_FILLLINE_THRESHOLD),
            ),
            default=_DEFAULT_FILLLINE_THRESHOLD,
        ),
        "fanout_files": _try_int(
            _pick(
                _str(ov.fanout_files),
                "COLLEAGUE_FANOUT_FILES",
                "CONVERTIBLE_FANOUT_FILES",
                default=str(_DEFAULT_FANOUT_FILES),
            ),
            default=_DEFAULT_FANOUT_FILES,
        ),
        "review_fanout_folders": _try_int_or_none(
            _pick(
                None,
                "COLLEAGUE_REVIEW_FANOUT_FOLDERS",
                "CONVERTIBLE_REVIEW_FANOUT_FOLDERS",
                default="",
            )
        ),
        "plan_offer_tokens": _try_int(
            _pick(
                _str(ov.plan_offer_tokens),
                "COLLEAGUE_PLAN_OFFER_TOKENS",
                "CONVERTIBLE_PLAN_OFFER_TOKENS",
                default=str(_DEFAULT_PLAN_OFFER_TOKENS),
            ),
            default=_DEFAULT_PLAN_OFFER_TOKENS,
        ),
        "max_continue_nudges": _try_int(
            _pick(
                _str(ov.max_continue_nudges),
                "COLLEAGUE_MAX_CONTINUE_NUDGES",
                "CONVERTIBLE_MAX_CONTINUE_NUDGES",
                default=str(_DEFAULT_MAX_CONTINUE_NUDGES),
            ),
            default=_DEFAULT_MAX_CONTINUE_NUDGES,
        ),
        # Env-only (no CLI flag / explicit override) — keeping it off the
        # parameter list holds resolve() at 13 params (Sonar S107, PR #207).
        "synthesis_reserve_steps": _try_int(
            _pick(
                None,
                "COLLEAGUE_SYNTHESIS_RESERVE_STEPS",
                "CONVERTIBLE_SYNTHESIS_RESERVE_STEPS",
                default=str(_DEFAULT_SYNTHESIS_RESERVE),
            ),
            default=_DEFAULT_SYNTHESIS_RESERVE,
        ),
        # Lint gate (#200) — env > config.json > default-on. Kept off the
        # signature (the --no-lint flag overrides post-resolve) to hold the
        # S107 parameter ceiling, mirroring synthesis_reserve_steps above.
        "lint": _resolve_lint_enabled(files.lint),
        "watch": _resolve_watch_enabled(files.watch),
        "coherence": _resolve_coherence_enabled(files.coherence),
        "memory": _resolve_memory_enabled(files.memory),
        "memory_distill": _resolve_memory_distill(files.memory_distill),
        "lint_fix_retries": _try_int(
            _pick(
                None,
                "COLLEAGUE_LINT_FIX_RETRIES",
                "CONVERTIBLE_LINT_FIX_RETRIES",
                default=_file_or_default(files.lint_retries, str(_DEFAULT_LINT_FIX_RETRIES)),
            ),
            default=_DEFAULT_LINT_FIX_RETRIES,
        ),
        # Test-integrity gate (#203) — env > config.json > default-on, mirroring
        # lint. Kept off the signature (no CLI flag in v0) for the S107 ceiling.
        "testintegrity": _resolve_testintegrity_enabled(files.ti),
        "testintegrity_fix_retries": _try_int(
            _pick(
                None,
                "COLLEAGUE_TESTINTEGRITY_FIX_RETRIES",
                "CONVERTIBLE_TESTINTEGRITY_FIX_RETRIES",
                default=_file_or_default(files.ti_retries, str(_DEFAULT_TESTINTEGRITY_FIX_RETRIES)),
            ),
            default=_DEFAULT_TESTINTEGRITY_FIX_RETRIES,
        ),
        "testintegrity_reviewer_model": testintegrity_reviewer_model,
        # Affected-tests gate (#213) — env > config.json > default-on, mirroring
        # lint. Kept off the signature (no CLI flag in v0) for the S107 ceiling.
        "affected_tests": _resolve_affected_tests_enabled(files.at),
        "affected_tests_fix_retries": _try_int(
            _pick(
                None,
                "COLLEAGUE_AFFECTED_TESTS_FIX_RETRIES",
                default=_file_or_default(
                    files.at_retries, str(_DEFAULT_AFFECTED_TESTS_FIX_RETRIES)
                ),
            ),
            default=_DEFAULT_AFFECTED_TESTS_FIX_RETRIES,
        ),
        "affected_tests_depth": _try_int(
            _pick(
                None,
                "COLLEAGUE_AFFECTED_TESTS_DEPTH",
                default=_file_or_default(files.at_depth, str(_DEFAULT_AFFECTED_TESTS_DEPTH)),
            ),
            default=_DEFAULT_AFFECTED_TESTS_DEPTH,
        ),
        "affected_tests_max_files": _try_int(
            _pick(
                None,
                "COLLEAGUE_AFFECTED_TESTS_MAX_FILES",
                default=_file_or_default(
                    files.at_max_files, str(_DEFAULT_AFFECTED_TESTS_MAX_FILES)
                ),
            ),
            default=_DEFAULT_AFFECTED_TESTS_MAX_FILES,
        ),
        # affected_tests_override has no env var (set later from a CLI flag).
        "affected_tests_override": None,
        # Episode chaining (indefinite-run, decision c21) — env > config.json
        # > default (dormant OFF / cap 5, 0 = unlimited). The --until-done /
        # --max-episodes CLI flags are applied post-resolve by the work path
        # (t5), keeping both off the signature (the S107 ceiling, the lint
        # precedent).
        "until_done": _resolve_until_done_enabled(files.until_done),
        "max_episodes": _try_int(
            _pick(
                None,
                "COLLEAGUE_MAX_EPISODES",
                "CONVERTIBLE_MAX_EPISODES",
                default=_file_or_default(files.max_episodes, str(_DEFAULT_MAX_EPISODES)),
            ),
            default=_DEFAULT_MAX_EPISODES,
        ),
        # Per-run compaction-turn cap (issue #334) — env > config.json >
        # the fillline default (4), 0 = unlimited (the max_episodes
        # convention above). Malformed input falls back to the default.
        "compaction_cap": _try_int(
            _pick(
                None,
                "COLLEAGUE_COMPACTION_CAP",
                "CONVERTIBLE_COMPACTION_CAP",
                default=_file_or_default(files.compaction_cap, str(DEFAULT_COMPACTION_CAP)),
            ),
            default=DEFAULT_COMPACTION_CAP,
        ),
    }

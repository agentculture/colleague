"""Engine configuration: where the model lives and how hard the loop drives it.

Resolution precedence, highest first:

1. an explicit value passed in code / from a CLI flag,
2. a ``COLLEAGUE_*`` environment variable (the legacy ``CONVERTIBLE_*`` name is
   still honored as a deprecated fallback during the rename),
3. an OpenAI-style ``OPENAI_*`` environment variable (so an existing OpenAI
   client setup is reused),
4. a persistent ``.colleague/config.json`` file (repo-level, falling back to
   user-level ``~/.colleague/config.json``) — the ``base_url``/``api_key``/
   ``model`` endpoint keys only, and only when ``resolve`` is given a
   ``repo_path``. This is the durable way to point colleague at another
   OpenAI-compatible provider without re-passing flags or env vars each run,
5. the built-in default.

Defaults point at the vLLM reference rig (decision D3): an OpenAI-compatible
server on ``localhost:8001``. Because the driver only speaks the OpenAI surface,
pointing ``base_url`` elsewhere is a config change, never a code change (h2) —
whether via env var, CLI flag, or ``.colleague/config.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Collection, Optional

from colleague import config_resolve, config_snapshot, effort
from colleague.associate_config import ASSOCIATE_WIRE_MODEL  # noqa: F401 - re-export
from colleague.associate_config import AssociateConfig, resolve_associate_seat

# ---------------------------------------------------------------------------
# The config siblings (plan ``hard-1000-line-file-limit`` t14). ``config.py``
# was 4442 lines; the helper groups below now live in their own modules and are
# re-exported HERE so every existing ``from colleague.config import X`` — 422
# importers, private names included (``_DEFAULT_MAX_OUTPUT_CHARS`` in tools.py,
# ``MAX_SUBAGENT_FANOUT`` in loop.py) — resolves exactly as before.
#
# ``_merged_config_json`` is re-exported deliberately, not incidentally: it is
# a landed monkeypatch seam, and ``config_files._merged_for`` dispatches back
# through THIS module attribute so the two patches of
# ``colleague.config._merged_config_json`` stay effective.
# ---------------------------------------------------------------------------
from colleague.config_defaults import (  # noqa: F401
    _CONFIG_FILENAME,
    _CONFIG_KEYS,
    _DEEPTHINK_CONFIG_KEYS,
    _DEEPTHINK_DEFAULT_WINDOW,
    _DEFAULT_AFFECTED_TESTS_DEPTH,
    _DEFAULT_AFFECTED_TESTS_ENABLED,
    _DEFAULT_AFFECTED_TESTS_FIX_RETRIES,
    _DEFAULT_AFFECTED_TESTS_MAX_FILES,
    _DEFAULT_AGENTS_ENABLED,
    _DEFAULT_API_KEY,
    _DEFAULT_AUTOSPLIT_TARGET_TOKENS,
    _DEFAULT_BASE_URL,
    _DEFAULT_COHERENCE_ENABLED,
    _DEFAULT_CONTEXT_BUDGET,
    _DEFAULT_DEEPTHINK_CONTEXT_BUDGET,
    _DEFAULT_ENGINE,
    _DEFAULT_FANOUT_FILES,
    _DEFAULT_FILLLINE_THRESHOLD,
    _DEFAULT_LINT_ENABLED,
    _DEFAULT_LINT_FIX_RETRIES,
    _DEFAULT_MAX_CONTINUE_NUDGES,
    _DEFAULT_MAX_EPISODES,
    _DEFAULT_MAX_OUTPUT_CHARS,
    _DEFAULT_MAX_STEPS,
    _DEFAULT_MEMORY_DISTILL,
    _DEFAULT_MEMORY_ENABLED,
    _DEFAULT_MODEL,
    _DEFAULT_PLAN_OFFER_TOKENS,
    _DEFAULT_SENSES_CONTEXT_BUDGET,
    _DEFAULT_SUBAGENT_CONCURRENCY,
    _DEFAULT_SUBAGENT_DEPTH,
    _DEFAULT_SUBAGENT_TOTAL,
    _DEFAULT_SYNTHESIS_RESERVE,
    _DEFAULT_TEMPERATURE,
    _DEFAULT_TESTINTEGRITY_ENABLED,
    _DEFAULT_TESTINTEGRITY_FIX_RETRIES,
    _DEFAULT_TESTINTEGRITY_REVIEWER_MODEL,
    _DEFAULT_THOUGHT_ACTION_EVALUATION,
    _DEFAULT_THREE_TIER_ENABLED,
    _DEFAULT_TIMEOUT,
    _DEFAULT_TOO_LONG_MIN,
    _DEFAULT_UNTIL_DONE,
    _DEFAULT_WATCH_ENABLED,
    _DISTILLER_CONFIG_KEYS,
    _EVALUATION_SEAT_ROLES,
    _LOBES_CONFIG_KEYS,
    _REALTIME_CONFIG_KEYS,
    _SEAT_CONFIG_KEYS,
    _SENSES_CONFIG_KEYS,
    _SENSES_DEFAULT_WINDOW,
    _VOICE_CONFIG_KEYS,
    _WORKER_CONFIG_KEYS,
    MAX_AGENT_MESSAGES,
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENT_FANOUT,
    MAX_SUBAGENT_TOTAL,
)
from colleague.config_files import (  # noqa: F401
    FileOverrides,
    _file_or_default,
    _load_affected_tests_overrides,
    _load_agents_override,
    _load_chain_overrides,
    _load_coherence_override,
    _load_deepthink_overrides,
    _load_distiller_override,
    _load_hire_override,
    _load_lint_overrides,
    _load_lobes_override,
    _load_memory_distill_override,
    _load_memory_override,
    _load_presence_override,
    _load_realtime_overrides,
    _load_reasoning_effort_overrides,
    _load_seat_overrides,
    _load_senses_overrides,
    _load_testintegrity_overrides,
    _load_thought_action_evaluation_override,
    _load_three_tier_override,
    _load_voice_overrides,
    _load_watch_override,
    _load_worker_overrides,
    _merged_config_json,
    _pick,
    _read_json_object,
    _str,
    _str_dict,
    _try_float,
    _try_int,
    _try_int_or_none,
    autosplit_children,
    config_provenance,
    effective_concurrency,
    load_config_file,
    load_file_overrides,
)
from colleague.config_flags import (  # noqa: F401
    _DEFAULT_HIRE_ENABLED,
    _PRESENCE_OFF_VALUES,
    PRESENCE_RUNGS,
    _normalize_presence_value,
    _parse_bool,
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
    _resolve_testintegrity_reviewer_model,
    _resolve_thought_action_evaluation_enabled,
    _resolve_three_tier_enabled,
    _resolve_until_done_enabled,
    _resolve_watch_enabled,
    resolve_engine,
    resolve_presence_rung,
    resolve_session_engine,
)
from colleague.config_lobes import (  # noqa: F401
    _WS_SCHEME_MAP,
    _deepthink_budget_from_window,
    _deepthink_from_lobes_role,
    _deepthink_lobes_fallback,
    _defaults_source,
    _emit_lobes_unreachable_notice,
    _lobes_base_url,
    _realtime_ws_url,
    _resolve_lobes_rung,
    _role_dial_base_url,
    _same_origin,
    _seat_refusal,
    _senses_budget_from_window,
    _senses_from_lobes_role,
    _senses_lobes_fallback,
    _voice_from_lobes_roles,
    _voice_lobes_fallback,
    _worker_refusal,
    resolve_lobes_gateway_url,
)
from colleague.config_modelpin import (  # noqa: F401
    _model_pin_source,
    _refresh_stale_model_pin,
    _resolution_time_refresh,
)
from colleague.config_profiles import (  # noqa: F401
    _PROFILE_ENV_KEYS,
    _PROFILES_FILENAME,
    _coerce_profile_int,
    _coerce_profile_seconds,
    _coerce_unit_fraction,
    _env_present,
    _field_from_source,
    _load_profile_overlays,
    _profile_as_source,
    _profile_updates,
    _read_profiles_file,
    _resolve_builtin_profile,
    apply_mode_profile,
)
from colleague.config_seats import (  # noqa: F401
    _realtime_lobes_fallback,
    _refuse_conflicting_execution_modes,
    _refuse_unusable_evaluation_gateway,
    _resolve_acting_dial,
    _resolve_deepthink,
    _resolve_evaluation_seats,
    _resolve_realtime,
    _resolve_realtime_devices,
    _resolve_senses,
    _resolve_voice,
    _resolve_worker,
    _seat_api_key,
)
from colleague.config_types import (  # noqa: F401
    DeepthinkConfig,
    EvaluationSeats,
    RealtimeConfig,
    ResolveOverrides,
    SeatConfig,
    SensesConfig,
    VoiceConfig,
    WorkerConfig,
)
from colleague.fillline import DEFAULT_COMPACTION_CAP

if TYPE_CHECKING:
    # Annotation-only (change-content consumption lane, plan task t3): types
    # ``config_lifecycle`` below. No runtime import — the attachment is read
    # defensively via getattr (colleague/loop.py:2934 already does this
    # forward-compatibly), and any object exposing the same read surface
    # (a frozen child view, a future adapter) is accepted, never just this
    # concrete class.
    # Annotation-only (temperature-knob deprecation, reasoning-aware-sampling
    # arc, plan task t7): types ``temperature_deprecation_warnings`` below.
    # No runtime import needed — ``config_resolve`` is already imported
    # eagerly at module scope above, this is purely to keep the annotation
    # string resolvable under a type checker.
    from colleague.config_resolve import TemperatureDeprecationWarning
    from colleague.configlifecycle import EpisodeConfigLifecycle

    # Annotation-only (same-role stale-pin refresh, plan task t9): types
    # ``model_refresh_warnings`` below. The real import stays LAZY inside
    # :func:`colleague.config_modelpin._refresh_stale_model_pin` (the same
    # ``colleague.lobes`` lazy-import precedent as every other lobes-fed rung).
    from colleague.lobes import ModelRefreshWarning


@dataclass(frozen=True)
class SeatDials:
    """The five opt-in dial targets resolved from env / config.json / lobes."""

    deepthink: Optional[DeepthinkConfig]
    senses: Optional[SensesConfig]
    associate: Optional[AssociateConfig]
    voice: Optional[VoiceConfig]
    realtime: Optional[RealtimeConfig]


def _resolve_seat_dials(
    files: FileOverrides,
    repo_path: "str | Path | None",
    base_url: str,
    api_key: str,
    lobes_roles: object,
    lobes_gateway_url: "str | None",
) -> SeatDials:
    """The deepthink / senses / associate / voice / realtime dials, in order.

    Deliberately kept in ``config.py`` rather than moved to
    :mod:`colleague.config_resolve` with the other ``resolve`` steps:
    ``tests/test_single_model_default.py`` reads THIS file and asserts each
    ``resolved_* = _*_lobes_fallback(`` call sits within three lines of its
    ``== "lobes"`` sentinel. Splitting the two apart would leave that guard
    passing on a file that no longer contains the code it guards — so the
    block stays whole, and stays here.
    """
    # Dual-model deepthink (t1) — a local so the reviewer default backfill (t7)
    # can inspect it. Muse discovery is OPT-IN ONLY (qwen-direct c4): the
    # sentinel ``lobes`` asks for it; see :func:`_deepthink_lobes_fallback`.
    resolved_deepthink = _resolve_deepthink(files.deepthink, base_url, api_key)
    if resolved_deepthink is not None and resolved_deepthink.model == "lobes":
        resolved_deepthink = _deepthink_lobes_fallback(
            lobes_roles, lobes_gateway_url, base_url, api_key, files.deepthink
        )
    # Senses front-door target — OPT-IN ONLY (qwen-direct c2): the sentinel
    # ``lobes`` asks for it; see :func:`_senses_lobes_fallback` (#292/#348).
    resolved_senses = _resolve_senses(files.senses, base_url, api_key)
    if resolved_senses is not None and resolved_senses.model == "lobes":
        resolved_senses = _senses_lobes_fallback(
            lobes_roles, lobes_gateway_url, base_url, api_key, files.senses
        )
    # Associate seat (t18) — OPT-IN like senses/muse; :mod:`colleague.associate_config`.
    resolved_associate = resolve_associate_seat(
        repo_path, base_url, api_key, lobes_roles, lobes_gateway_url
    )
    # Voice (stt/tts) escalation target (senses live-presence + voice arc) —
    # resolved once as a local, mirroring senses. Precedence: env >
    # config.json > lobes discovery > absent. When voice is NOT declared via
    # env/config.json but the lobes rung resolved, the gateway's stt/tts roles
    # supply the VoiceConfig — EACH role's own resolved dial target
    # (colleague#292, S1's follow-on: closes lobes-cli#87 end-to-end), and
    # the main api_key ONLY toward roles whose dial target shares the main
    # endpoint's own origin (see :func:`_voice_lobes_fallback` for the
    # key-hygiene rule, colleague#348 t2 — the same conservative stance
    # :func:`_senses_lobes_fallback`/:func:`_deepthink_lobes_fallback`
    # take, extended to voice's two-role, single-key shape).
    resolved_voice = _resolve_voice(files.voice, base_url, api_key)
    if resolved_voice is None:
        resolved_voice = _voice_lobes_fallback(
            lobes_roles, lobes_gateway_url, base_url, api_key, files.voice
        )
    # Realtime (server-VAD live speech session) dial target
    # (realtime-speech arc, plan task t1) — resolved once as a local,
    # mirroring senses/voice. Precedence: env > config.json > lobes
    # discovery (the stt role's realtime_vad_session responsibility,
    # gated on voice already being armed) > absent. Resolved AFTER voice
    # since the discovery fallback consults the just-resolved
    # ``resolved_voice`` (see :func:`_realtime_lobes_fallback`).
    resolved_realtime = _resolve_realtime(files.realtime, api_key)
    if resolved_realtime is None:
        resolved_realtime = _realtime_lobes_fallback(
            lobes_roles,
            lobes_gateway_url,
            base_url,
            api_key,
            files.realtime,
            resolved_voice,
        )
    return SeatDials(
        deepthink=resolved_deepthink,
        senses=resolved_senses,
        associate=resolved_associate,
        voice=resolved_voice,
        realtime=resolved_realtime,
    )


@dataclass
class EngineConfig:
    """Settings for an OpenAI-compatible engine driver."""

    base_url: str = _DEFAULT_BASE_URL
    api_key: str = _DEFAULT_API_KEY
    model: str = _DEFAULT_MODEL
    max_steps: int = _DEFAULT_MAX_STEPS
    temperature: float = _DEFAULT_TEMPERATURE
    timeout: float = _DEFAULT_TIMEOUT
    # Runtime-only (#268 escalation bookkeeping, Qodo PR #271): the OPERATOR's
    # configured timeout, recorded the moment a work item's bounded x2
    # escalation raises `timeout` in place. Presence means `timeout` may carry
    # escalated state — `loop._make_timeout_escalator` restores `timeout` from
    # it at every work-item start, so an escalation can never leak into a
    # subagent child config (derived via dataclasses.replace, which copies both
    # fields) or a session-reused config and compound past 2x the operator's
    # value. Never resolved from env/file, never serialized (absent from
    # to_dict), None on every fresh resolve().
    base_timeout: float | None = None
    context_budget_tokens: int = _DEFAULT_CONTEXT_BUDGET
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS
    subagent_concurrency: int = _DEFAULT_SUBAGENT_CONCURRENCY
    subagent_depth: int = _DEFAULT_SUBAGENT_DEPTH
    subagent_total: int = _DEFAULT_SUBAGENT_TOTAL
    autosplit_target_tokens: int = _DEFAULT_AUTOSPLIT_TARGET_TOKENS
    fillline_threshold: float = _DEFAULT_FILLLINE_THRESHOLD
    fanout_files: int = _DEFAULT_FANOUT_FILES
    # Review fan-out advisory (#220b): the distinct-folders-read count at which a
    # review run is nudged ONCE to fan out per-folder read-only `reviewer` subagents.
    # ``None`` = dormant (the default) — a strict no-op, so a normal run is
    # byte-identical. Enabled per-run via ``COLLEAGUE_REVIEW_FANOUT_FOLDERS`` (the
    # ask-colleague ``review`` wrapper sets it).
    review_fanout_folders: int | None = None
    plan_offer_tokens: int = _DEFAULT_PLAN_OFFER_TOKENS
    max_continue_nudges: int = _DEFAULT_MAX_CONTINUE_NUDGES
    synthesis_reserve_steps: int = _DEFAULT_SYNTHESIS_RESERVE
    lint: bool = _DEFAULT_LINT_ENABLED
    coherence: bool = _DEFAULT_COHERENCE_ENABLED
    memory: bool = _DEFAULT_MEMORY_ENABLED
    memory_distill: bool = _DEFAULT_MEMORY_DISTILL
    # Flight plane armed by default (#307): work/drive/session default watch ON.
    # The work path resolves the effective value against the --watch/--no-watch
    # flags post-resolve; session default-arms from this. env COLLEAGUE_WATCH >
    # config.json {watch} > default-on.
    watch: bool = _DEFAULT_WATCH_ENABLED
    lint_fix_retries: int = _DEFAULT_LINT_FIX_RETRIES
    testintegrity: bool = _DEFAULT_TESTINTEGRITY_ENABLED
    testintegrity_fix_retries: int = _DEFAULT_TESTINTEGRITY_FIX_RETRIES
    testintegrity_reviewer_model: str = _DEFAULT_TESTINTEGRITY_REVIEWER_MODEL
    affected_tests: bool = _DEFAULT_AFFECTED_TESTS_ENABLED
    affected_tests_fix_retries: int = _DEFAULT_AFFECTED_TESTS_FIX_RETRIES
    affected_tests_depth: int = _DEFAULT_AFFECTED_TESTS_DEPTH
    affected_tests_max_files: int = _DEFAULT_AFFECTED_TESTS_MAX_FILES
    affected_tests_override: Optional[str] = None
    # Episode chaining (indefinite-run, decision c21): ``until_done`` arms the
    # chain driver (colleague/chain.py); default OFF = today's single-episode
    # behavior byte-identical. ``max_episodes`` caps an armed chain: default 5,
    # 0 = unlimited. Deliberately NOT in :meth:`to_dict` (the ``watch``
    # precedent) so a dormant run's artifact config snapshot stays
    # byte-identical (h1).
    until_done: bool = _DEFAULT_UNTIL_DONE
    max_episodes: int = _DEFAULT_MAX_EPISODES
    # Per-run compaction-turn cap (indefinite-run follow-up, issue #334):
    # bounds how many fill-line ``compact`` moves a single run may spend
    # before further compaction offers are suppressed (the anti-thrash floor
    # documented on :data:`colleague.fillline.DEFAULT_COMPACTION_CAP`).
    # Default 4, 0 = unlimited (the ``max_episodes`` convention). Precedence:
    # COLLEAGUE_COMPACTION_CAP env > .colleague/config.json {"compaction_cap":
    # ...} > the fillline default. Unlike ``max_episodes``/``until_done`` this
    # DOES appear in :meth:`to_dict` — the artifact snapshot is meant to
    # surface the effective cap (h4/h7), not stay byte-identical.
    compaction_cap: int = DEFAULT_COMPACTION_CAP
    # Per-seat thinking-effort ladder (#416 t2, see colleague.effort):
    # ``reasoning_effort`` = GLOBAL override ("default" = kill-switch);
    # ``reasoning_effort_seats`` = per-seat override (incl. ``associate.<seat>``,
    # t1: colleague.efforttables). All default unset, byte-identical to today.
    reasoning_effort: Optional[str] = None
    reasoning_effort_seats: dict = field(default_factory=dict)
    reasoning_effort_purposes: dict = field(default_factory=dict)  # t1: colleague.efforttables
    # t8's "too long" advisory threshold, in minutes (#416 t2).
    too_long_min: int = _DEFAULT_TOO_LONG_MIN
    # Dual-model deepthink escalation target (t1); ``None`` = single-model,
    # byte-identical (:class:`DeepthinkConfig`, :func:`_resolve_deepthink`).
    deepthink: Optional[DeepthinkConfig] = None
    # Senses (multimodal front-door) escalation target (task t3); ``None`` =
    # no senses declared, byte-identical (:class:`SensesConfig`).
    senses: Optional[SensesConfig] = None
    associate: Optional[AssociateConfig] = None  # t18: colleague/associate_config.py
    lobes_context: Optional[int] = None  # t20: cortex's advertised window (closes d15)
    # Voice (stt/tts) escalation target; ``None`` = no voice declared,
    # byte-identical (:class:`VoiceConfig`, :func:`_resolve_voice`).
    voice: Optional[VoiceConfig] = None
    # Realtime (server-VAD live speech) dial target; ``None`` = not
    # declared/discovered, byte-identical (:class:`RealtimeConfig`).
    realtime: Optional[RealtimeConfig] = None
    # Three-tier execution arming (plan task t3); ``False`` = byte-identical
    # (a worker advert is read+discarded, never resolved) — see
    # :func:`_resolve_three_tier_enabled`.
    three_tier: bool = False
    # Worker (three-tier actor) dial target; ``None`` = three-tier not armed,
    # byte-identical. RESOLUTION ONLY when present: an armed run with an
    # unresolvable worker raises a loud refusal (no silent cortex-as-actor).
    # See :class:`WorkerConfig`/:func:`_resolve_worker`.
    worker: Optional[WorkerConfig] = None
    # Thought→action→evaluation execution arming (plan task t12; #397).
    # ``False`` = byte-identical (every seat advert read+discarded, key
    # omitted from ``to_dict()``). An INDEPENDENT opt-in: distinct from
    # ``three_tier`` in every direction (arming both refuses). See
    # :func:`_resolve_thought_action_evaluation_enabled`.
    thought_action_evaluation: bool = False
    # Model-bound agents arming (#411, eleventh sanctioned increment; plan
    # task t7). ``False`` = byte-identical, key omitted from ``to_dict()``.
    # A THIRD independent opt-in: arming it with either sibling mode refuses.
    # See :func:`_resolve_agents_enabled`.
    agents: bool = False
    # hire_colleague arming (delegation-follow-ups t4, spec c17/D5): env
    # ``COLLEAGUE_HIRE`` > config.json ``hire`` > OFF. ``False`` = key omitted
    # from ``to_dict()`` (byte-identical). Resolution only — the tools land
    # in later tasks and read this flag.
    hire: bool = False
    # The acting seat's ADD-set (t4 attestation of t1's knob): the tool names
    # ``COLLEAGUE_ACTING_ADD_TOOLS`` adds at depth 0; ``()`` = key omitted.
    acting_add_tools: tuple[str, ...] = ()
    # The mode's three resolved seats (front/worker/evaluator), each resolved
    # BY ROLE NAME from the lobes /capabilities contract. ``None`` = the mode
    # is not armed, byte-identical to today. RESOLUTION ONLY when present: an
    # armed run with any unresolvable seat raises a loud refusal instead of
    # ever leaving this ``None`` with the flag True (no silent fallback). See
    # :class:`EvaluationSeats` and :func:`_resolve_evaluation_seats`.
    evaluation_seats: Optional[EvaluationSeats] = None
    # The checkpoint id serving the EVALUATOR seat (spec c38/h30). Set ONLY
    # when the mode is armed — it is ``evaluation_seats.evaluator.model``,
    # surfaced as a flat field because ``colleague/distill.py``'s
    # ``_refuses_evaluator_as_distiller`` guard reads exactly this attribute
    # (via ``getattr``) to refuse handing the evaluator seat lesson-authoring
    # authority. ``None`` = unarmed, which leaves that guard as inert as it is
    # today. See :func:`_resolve_evaluation_seats`.
    evaluator_checkpoint: Optional[str] = None
    # An operator-DECLARED distinct distillation authority (spec c38/h30).
    # Lifts the evaluator-as-distiller refusal above by naming a checkpoint
    # that is genuinely not the evaluator's. Resolved independently of the
    # mode's arming (an authority declaration stands on its own); ``None`` =
    # nothing declared, byte-identical to today. See
    # :func:`_resolve_distiller_checkpoint`.
    distiller_checkpoint: Optional[str] = None
    # The episode config-lifecycle attachment (change-content consumption
    # lane, plan task t3). ``None`` (the default) = no config plane armed,
    # byte-identical to today — the pre-existing state, since nothing has
    # ever set this field before this task. A runtime-only object set
    # imperatively by the work front once three-tier is armed (a later
    # task), never resolved from env/file — excluded from eq/repr/to_dict
    # like ``role``/``memory_root`` above. Typed here only to make a seam
    # ``colleague/loop.py`` already reads via
    # ``getattr(config, "config_lifecycle", None)`` (line 2934,
    # forward-compatible before this field existed) explicit; both engines'
    # ``work()`` read it the same way at episode-schema-resolution time.
    config_lifecycle: "Optional[EpisodeConfigLifecycle]" = field(
        default=None, compare=False, repr=False
    )

    # A runtime-only per-step progress sink ``(step_index, tool, target, ok)``
    # the loop fires per tool call (#38). Set by the CLI work path, not by
    # ``resolve()``; excluded from eq/repr and from ``to_dict`` (it is behavior,
    # not serializable config).
    progress: Optional[Callable[[int, str, str, bool], None]] = field(
        default=None, compare=False, repr=False
    )

    # Token-delta seam (feels-alive arc, task t3): an OPTIONAL per-completion
    # sink an engine MAY call with each ordered text delta of the model's
    # in-progress completion, before it returns the full ``ModelResponse``.
    # Mirrors ``progress`` immediately above: a runtime-only field set
    # imperatively by the caller (CLI/session/cockpit), never resolved from
    # env/file/``resolve()`` — excluded from eq/repr/``to_dict`` (behavior,
    # not serializable config). ``None`` (the default, and the ONLY state
    # reachable through ``resolve()``) is a strict no-op: an engine that never
    # checks ``on_delta``, or checks it and finds it ``None``, streams
    # nothing — an unarmed run is byte-identical to the pre-seam loop.
    #
    # Deliberately NOT threaded through ``ContextControls``/``colleague.loop``:
    # the loop only ever sees a completed ``ModelResponse`` (what ``complete``
    # returns), never the raw stream a live backend receives it from — so
    # there is nothing for the loop to forward. Each backend's OWN
    # completion-building code already receives this ``config`` object
    # directly (e.g. ``MockEngine.work(self, task, config)``, or the vLLM
    # adapter's ``_make_complete(self, config, tools)``), so it reads
    # ``config.on_delta`` itself and invokes it as the answer streams in,
    # still returning the same ``ModelResponse`` at the end exactly as today.
    #
    # Intended producer (task t4): the vLLM engine's SSE stream calls this
    # once per received content chunk as it arrives from the server.
    # Intended producer (this task, t3): the mock engine emits synthetic
    # word-chunk deltas of each scripted turn's ``content`` when armed (see
    # ``colleague/engines/mock.py``), so the seam is exercisable end to end
    # with no network.
    # Intended consumer (task t6): the session's live cockpit sinks arm this
    # to render tokens as they stream instead of only after a turn completes.
    on_delta: Optional[Callable[[str], None]] = field(default=None, compare=False, repr=False)

    # Runtime-only spawn callback for subagent delegation; set by the work item
    # path, not by ``resolve()``; excluded from eq/repr/to_dict (it is behavior,
    # not serializable config).
    subagent_spawn: Optional[Callable] = field(default=None, compare=False, repr=False)

    # Runtime-only batch-spawn callback for parallel subagent delegation; set by
    # the work path, not by ``resolve()``; excluded from eq/repr/to_dict (it is
    # behavior, not serializable config).
    subagent_batch_spawn: Optional[Callable] = field(default=None, compare=False, repr=False)

    # Typed-subagent role NAME this work item runs as (#t4). ``None`` = today's
    # full-surface behavior (byte-identical to pre-role). Set on a *child's* config
    # by the subagent launcher; the engine builds the child's curated tool schema +
    # role-composed prompt from it (t8). A runtime field, not env-resolved, so it is
    # excluded from eq/repr/to_dict like the spawn callbacks above.
    role: Optional[str] = field(default=None, compare=False, repr=False)
    # The run's ``--mode`` (explore/review/work/…), stamped by the CLI front
    # beside ``role`` so the acting seat's effort can apply the read-only-mode
    # rung (:data:`colleague.effort.TOP_LEVEL_MODE_TABLE`). Runtime-only, like
    # ``role``: excluded from eq/repr/to_dict.
    mode: Optional[str] = field(default=None, compare=False, repr=False)

    # Memory root (spec R1 / plan t2): the OPERATOR repo the memory store lives
    # in. An isolated run works in a throwaway worktree, so a lesson written to
    # task.repo_path would die with it — execute_work sets this to the real repo
    # root so recall/remember target the durable store. A runtime field set by
    # the CLI layer (the ``role`` precedent); excluded from eq/repr/to_dict.
    memory_root: Optional[str] = field(default=None, compare=False, repr=False)

    # Mode-profile explicit-knob mask (t3 / spec R1): the EngineConfig field names
    # the caller set from explicit CLI flags (e.g. ``{"max_steps"}`` when
    # ``--max-steps`` was given), so ``apply_mode_profile`` never overwrites them.
    # A runtime field set by the CLI layer — the ``role`` precedent (keeps
    # ``execute_work`` under the S107 parameter ceiling); excluded from
    # eq/repr/to_dict.
    explicit_knobs: Collection[str] = field(default=(), compare=False, repr=False)

    # Embedder env overrides (one-embedder increment, S2, colleague#291/#292
    # task t19): built by :func:`_resolve_lobes_rung` from the gateway's
    # OPTIONAL ``embedder`` role via :func:`colleague.lobes.embed_env` — ``{}``
    # (the default) when lobes is unarmed/unreachable or the gateway doesn't
    # advertise an embedder (never fails resolution, mirroring stt/tts).
    # Threaded to the eidetic-CLI subprocess env in ``colleague/memory.py``
    # (never overwriting an operator-set env var — operator wins). A
    # runtime-derived plumbing value, not a declared override — excluded from
    # eq/repr/to_dict like ``memory_root``/``role`` above.
    embed_env: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    # The ARMED lobes gateway origin this config resolved against (self-knowledge
    # arc, t9): set by :meth:`resolve` from :func:`_resolve_lobes_rung`'s
    # ``lobes_gateway_url`` — ``None`` when the rung is unarmed OR degraded
    # (unreachable), so it reflects the state the run ACTUALLY resolved with,
    # never a dead URL presented as live. Read by the loop's self-knowledge
    # advisory (via ``ContextControls.from_config``) to render the honest
    # ``lobes:`` self-fact. A runtime-derived plumbing value like ``embed_env``
    # above — excluded from eq/repr/to_dict.
    lobes_gateway_url: Optional[str] = field(default=None, compare=False, repr=False)

    # Same-role stale-pin refresh records (plan task t9, spec c11/h8): every
    # :class:`~colleague.lobes.ModelRefreshWarning` this config's resolution
    # emitted (``()`` — the default — when the pin was valid, or lobes was
    # unarmed/unreachable/couldn't run the membership check, byte-identical
    # to today), PLUS any the vLLM engine's call-time 404 catch appends
    # in-place during ``work()`` (``colleague/engines/vllm_openai.py``
    # reassigns this to a NEW tuple — ``self.model_refresh_warnings +
    # (warning,)`` — rather than mutating a shared list, so a subagent child
    # sharing this field's value via ``dataclasses.replace`` never sees a
    # parent's later call-time append, and vice versa). A runtime-derived
    # plumbing value like ``lobes_gateway_url``/``embed_env`` above —
    # excluded from eq/repr/to_dict; a downstream task (t11) is the one that
    # folds this onto ``TaskResult``/the run artifact.
    model_refresh_warnings: "tuple[ModelRefreshWarning, ...]" = field(
        default=(), compare=False, repr=False
    )

    # Temperature-knob deprecation/removal records (reasoning-aware-sampling
    # arc, plan task t7, spec c9/h11): set by
    # :func:`colleague.config_resolve._resolve_temperature_deprecation`
    # inside :func:`colleague.config_resolve.resolve_scalar_knobs` — ``()``
    # (the default) when neither ``CONVERTIBLE_TEMPERATURE`` (removed) nor
    # ``COLLEAGUE_TEMPERATURE`` (deprecated, still applied) is set, matching
    # today byte-for-byte. Runtime-derived plumbing like
    # ``model_refresh_warnings`` above — excluded from eq/repr/to_dict; the
    # CLI work front folds this onto ``TaskResult.warnings`` the same way.
    temperature_deprecation_warnings: "tuple[TemperatureDeprecationWarning, ...]" = field(
        default=(), compare=False, repr=False
    )

    # Which seat the call-time stale-pin refresh may act for (d5, issue 375):
    # ``"main"`` — the default — arms the vLLM engine's 404 catch for the
    # acting MAIN seat only (the c8/c11 scoping). The replaced-config twins
    # (``deepthink_engine_config`` / ``senses_engine_config``) set ``None``
    # so a deepthink/senses 404 surfaces unchanged into that lane's own
    # degrade path instead of being silently retried on the main seat's
    # model (the muse->cortex cross-role event this field exists to stop).
    # Runtime-only plumbing like the fields above — excluded from
    # eq/repr/to_dict.
    refresh_seat: Optional[str] = field(default="main", compare=False, repr=False)

    # Chain-episode dispatch marker (indefinite-run follow-up, issue #335 /
    # decision c22): ``True`` exactly when THIS dispatch is one episode of an
    # armed ``--until-done`` chain (``execute_work`` sets it per-call from the
    # PRESENCE of its ``chain: ChainEpisodeOptions | None`` parameter — never
    # from ``config.until_done``, so a plain run with ``until_done=True`` but
    # no chain dispatch leaves it ``False``). ``chain_prior_changed`` carries
    # the UNION of every prior episode's ``result.changed_files`` (sorted,
    # deduped), ``()`` on the chain's first episode / any non-chained run. A
    # runtime field set imperatively by the CLI layer — the ``role``/
    # ``memory_root`` precedent — excluded from eq/repr/to_dict. c22 requires
    # a subagent child NOT inherit the marker even though ``dataclasses.
    # replace`` would otherwise copy it from the parent config object
    # ``execute_work`` mutated in place: :func:`colleague.subagents.
    # run_subagent` resets both fields to their dormant defaults in its
    # ``replace_kwargs`` (see that module), so every subagent child is
    # byte-identical to an unchained dispatch regardless of its parent.
    chain_episode: bool = field(default=False, compare=False, repr=False)
    chain_prior_changed: tuple[str, ...] = field(default=(), compare=False, repr=False)

    @property
    def reasoning_effort_effective(self) -> Optional[str]:
        """The ACTING seat's resolved thinking-effort rung — see
        :func:`colleague.effort.resolve_acting_effort` (c26/h17). A property,
        not a ``resolve()``-time field: :attr:`role` is set by the CLI AFTER
        ``resolve()`` returns (``colleague/cli/_commands/work.py``'s
        ``config.role = ...``), so only a lazy read reflects it correctly.
        """
        return effort.resolve_acting_effort(
            worker_armed=self.worker is not None,
            seats=self.reasoning_effort_seats,
            global_value=self.reasoning_effort,
            role=self.role,
            mode=self.mode,
        )

    @classmethod
    def resolve(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_steps: int | None = None,
        repo_path: str | Path | None = None,
        discover_lobes: bool = True,
        overrides: "ResolveOverrides | None" = None,
    ) -> "EngineConfig":
        """Build a config from explicit args, env vars, config file, then defaults.

        When *repo_path* is provided, values from ``.colleague/config.json``
        are loaded and used as the ``default=`` for the ``base_url``, ``api_key``
        and ``model`` fields. The resulting precedence is:

        explicit argument > COLLEAGUE_/OPENAI_ env var > .colleague/config.json > built-in default.

        When *repo_path* is ``None`` or no config file exists, behaviour is
        byte-identical to the prior (no config-file) implementation.

        ``temperature``, ``timeout``, ``subagent_depth`` and ``subagent_total``
        have no explicit-override keyword (and no CLI flag): no production caller
        passes them, so their precedence is simply ``COLLEAGUE_*`` env var >
        built-in default. Keeping them off the signature holds ``resolve`` under
        the parameter ceiling (SonarCloud S107); the dataclass still carries the
        fields, and the ``COLLEAGUE_TIMEOUT`` / ``COLLEAGUE_SUBAGENT_DEPTH`` /
        ``COLLEAGUE_SUBAGENT_TOTAL`` env vars (with ``CONVERTIBLE_*`` fallbacks)
        override them as before. ``temperature`` is the one exception
        (reasoning-aware-sampling arc, plan task t7, spec c9/h11):
        ``CONVERTIBLE_TEMPERATURE`` is REMOVED — its value is ignored and a run
        that sets it gets a loud warning — and ``COLLEAGUE_TEMPERATURE`` alone
        resolves the scalar, itself DEPRECATED for one release (still applied,
        still warns, names ``.colleague/models.json`` as the per-half
        replacement). See :func:`colleague.config_resolve.resolve_scalar_knobs`.

        *overrides* bundles eight secondary numeric-knob explicit-override slots
        (``context_budget_tokens``, ``max_output_chars``, ``subagent_concurrency``,
        ``autosplit_target_tokens``, ``fillline_threshold``, ``fanout_files``,
        ``plan_offer_tokens``, ``max_continue_nudges`` — see
        :class:`ResolveOverrides`) that used to be individual keyword params here;
        each still resolves ``COLLEAGUE_*`` env > ``.colleague/config.json`` >
        built-in default exactly as before when omitted from *overrides* (or when
        *overrides* itself is ``None``) — this bundling changed nothing about
        resolution, only how an explicit override is expressed.
        """
        ov = overrides if overrides is not None else ResolveOverrides()
        # Every .colleague/config.json section this resolution consults, read
        # once (t14): an absent repo_path yields the all-defaults instance, the
        # byte-identical "no config file" case.
        files = load_file_overrides(repo_path)

        # Lobes discovery rung (task t4): see :func:`_resolve_lobes_rung` for the
        # full rationale (extracted to hold this method's cognitive complexity
        # under the SonarCloud S3776 ceiling — pure extraction, no behavior
        # change). It slots BELOW config.json and ABOVE the builtin default.
        # ``lobes_gateway_url`` (S1/S2 follow-on) lets the senses/voice rungs
        # below resolve EACH role's own dial target independently of cortex's.
        lobes_base_url, lobes_model, lobes_roles, lobes_gateway_url, lobes_embed_env = (
            _resolve_lobes_rung(repo_path, discover_lobes)
        )

        # Resolved once as locals (not just inline in the ``cls(...)`` call
        # below) so the deepthink resolution can default ITS base_url/api_key
        # to the MAIN endpoint's already-resolved values (spec requirement).
        # The default is a plain if/else (not a nested ternary, SonarCloud
        # S3358) over the two DEFAULTS-SOURCE rungs below the explicit
        # arg/env precedence: config.json, then the lobes discovery rung.
        base_url_default = _defaults_source(files.cfg_base_url, lobes_base_url, _DEFAULT_BASE_URL)
        resolved_base_url = _pick(
            base_url,
            "COLLEAGUE_BASE_URL",
            "CONVERTIBLE_BASE_URL",
            "OPENAI_BASE_URL",
            default=base_url_default,
        )
        resolved_api_key = _pick(
            api_key,
            "COLLEAGUE_API_KEY",
            "CONVERTIBLE_API_KEY",
            "OPENAI_API_KEY",
            default=_file_or_default(files.cfg_api_key, _DEFAULT_API_KEY),
        )

        # The five opt-in seat dials (the sentinel-guarded lobes fallbacks).
        dials = _resolve_seat_dials(
            files, repo_path, resolved_base_url, resolved_api_key, lobes_roles, lobes_gateway_url
        )
        # The three mutually-exclusive execution modes and their seats.
        modes = config_resolve.resolve_execution_modes(
            files, repo_path, lobes_roles, lobes_gateway_url, resolved_base_url, resolved_api_key
        )
        resolved_deepthink = config_resolve.suppress_deepthink_in_mode(
            dials.deepthink, modes.three_tier, modes.thought_action_evaluation
        )
        # Test-integrity reviewer model (#203) — env > CONVERTIBLE fallback >
        # default (empty), then backfilled from the deepthink model when
        # unconfigured and same-endpoint (t7, spec c10(d)).
        resolved_testintegrity_reviewer_model = _resolve_testintegrity_reviewer_model(
            _pick(
                None,
                "COLLEAGUE_TESTINTEGRITY_REVIEWER_MODEL",
                "CONVERTIBLE_TESTINTEGRITY_REVIEWER_MODEL",
                default=_DEFAULT_TESTINTEGRITY_REVIEWER_MODEL,
            ),
            resolved_deepthink,
            resolved_base_url,
        )
        resolved_model, model_refresh_warning, resolved_context_budget_tokens = (
            config_resolve.resolve_main_model(
                model,
                files,
                lobes_model,
                lobes_gateway_url,
                lobes_roles,
                resolved_api_key,
                ov,
                worker_armed=modes.worker is not None,
            )
        )
        (
            acting_model,
            acting_base_url,
            acting_api_key,
            acting_context_budget_tokens,
        ) = config_resolve.resolve_acting_dial_step(
            modes.worker,
            modes.seats,
            main=(
                resolved_model,
                resolved_base_url,
                resolved_api_key,
                resolved_context_budget_tokens,
            ),
        )
        (
            resolved_reasoning_effort,
            resolved_reasoning_effort_seats,
            resolved_reasoning_effort_purposes,
            resolved_too_long_min,
        ) = config_resolve.resolve_effort_knobs(files)

        return cls(
            base_url=acting_base_url,
            api_key=acting_api_key,
            model=acting_model,
            context_budget_tokens=acting_context_budget_tokens,
            lobes_context=getattr(getattr(lobes_roles, "cortex", None), "context", None) or None,
            **config_resolve.resolve_scalar_knobs(
                ov, max_steps, files, resolved_testintegrity_reviewer_model
            ),
            # Dual-model deepthink (t1) — env > config.json `deepthink` > absent.
            deepthink=resolved_deepthink,
            # Senses (multimodal front-door, cortex/senses arc task t3) —
            # env > config.json `senses` section > absent (None). Scope: no
            # lobes discovery rung yet (t4); base_url/api_key default to the
            # resolved MAIN endpoint values computed above.
            senses=dials.senses,
            associate=dials.associate,  # t18: see colleague/associate_config.py
            voice=dials.voice,
            # Realtime dial target (realtime-speech arc, task t1) — env >
            # config.json `realtime` section > lobes discovery (stt's
            # realtime_vad_session responsibility) > absent (None).
            realtime=dials.realtime,
            # Three-tier execution arming (three-tier-execution arc, plan task
            # t3) — env `COLLEAGUE_THREE_TIER` > config.json `three_tier` >
            # default-OFF.
            three_tier=modes.three_tier,
            # Worker (three-tier bounded-tool-loop actor) dial target — None
            # when three_tier is not armed (byte-identical to today); when
            # armed, resolution above already raised a loud refusal on any
            # gap, so a returned config never carries three_tier True with
            # worker None.
            worker=modes.worker,
            # Thought→action→evaluation arming (post-#387 program, plan task
            # t12) — env `COLLEAGUE_THOUGHT_ACTION_EVALUATION` > config.json
            # `thought_action_evaluation` > default-OFF; independent of
            # `three_tier` in both directions.
            thought_action_evaluation=modes.thought_action_evaluation,
            # Model-bound agents arming (#411, plan task t7) — env
            # `COLLEAGUE_AGENTS` > config.json `agents` > default-OFF; a third
            # independent opt-in; omitted from to_dict() when unarmed.
            agents=modes.agents,
            hire=modes.hire,
            acting_add_tools=modes.acting_add_tools,
            # The mode's three seats (front/worker/evaluator), each resolved BY
            # ROLE NAME from lobes /capabilities — None when the mode is not
            # armed (byte-identical); when armed, resolution above already
            # raised a naming refusal on any missing/not-ready role, so a
            # returned config never carries the flag True with seats None.
            evaluation_seats=modes.seats,
            # The evaluator seat's checkpoint id + any declared distinct
            # distillation authority (spec c38/h30) — the two attributes
            # distill.py's authority-separation guard reads.
            evaluator_checkpoint=modes.evaluator_checkpoint,
            distiller_checkpoint=modes.distiller_checkpoint,
            # Embedder env overrides (S2, task t19) — {} when lobes is
            # unarmed/unreachable or the gateway doesn't advertise an embedder
            # (see :func:`_resolve_lobes_rung` / :func:`colleague.lobes.embed_env`).
            embed_env=lobes_embed_env,
            # Armed lobes gateway origin (t9 self-knowledge) — None when the rung
            # is unarmed or degraded, so the self-facts ``lobes:`` line reflects
            # the state this run actually resolved with.
            lobes_gateway_url=lobes_gateway_url,
            # Same-role stale-pin refresh records (plan task t9) — the
            # resolution-time rung's own finding (if any); the vLLM engine's
            # call-time 404 catch appends to this same field in place during
            # ``work()``.
            model_refresh_warnings=(
                (model_refresh_warning,) if model_refresh_warning is not None else ()
            ),
            reasoning_effort=resolved_reasoning_effort,
            reasoning_effort_seats=resolved_reasoning_effort_seats,
            reasoning_effort_purposes=resolved_reasoning_effort_purposes,
            too_long_min=resolved_too_long_min,
        )

    def to_dict(self) -> dict[str, object]:
        """Config snapshot for the result artifact, with the api_key redacted.

        The body lives in :func:`colleague.config_snapshot.config_to_dict`
        (t14) — the same key set, emitted from a sibling module.
        """
        return config_snapshot.config_to_dict(self)

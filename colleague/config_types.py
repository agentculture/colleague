"""The sub-config dataclasses :class:`colleague.config.EngineConfig` composes.

The nine frozen value objects a resolved config carries — the deepthink /
senses / worker / seat dials, the evaluation-seat triple, voice, realtime and
the :class:`ResolveOverrides` bundle. Split out of ``config.py`` (hard
1000-line file limit, plan ``hard-1000-line-file-limit`` t14) as the LEAF that
breaks the import cycles between the other config siblings — a pure move, no
field, default or docstring changed. Every name is re-exported from
:mod:`colleague.config`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeepthinkConfig:
    """A resolved dual-model deepthink escalation target.

    Optional: present on :attr:`EngineConfig.deepthink` only when the
    operator has declared a deepthink model (env var or a ``deepthink``
    section in .colleague/config.json) — see :func:`_resolve_deepthink`. The
    deepthink endpoint speaks the same OpenAI surface as the main endpoint
    through the same ``vllm-openai`` adapter, so retargeting stays a config
    change, never a code change (h2 precedent). Nothing here hard-codes a
    specific pair of models (h1) — any two OpenAI-compatible endpoints can
    play main and deepthink.
    """

    model: str
    base_url: str
    api_key: str
    context_budget: int
    multimodal: bool = False
    """Operator declaration that THIS (second) model accepts media content
    parts while the main model is text-only (task t8, decision c24) — arming
    the runtime's media-comprehension bridge. Never probed or inferred from a
    model name; default ``False`` keeps a dual-model config byte-identical."""


@dataclass(frozen=True)
class SensesConfig:
    """A resolved senses (multimodal front-door) escalation target.

    Cortex/senses arc (spec
    docs/specs/2026-07-03-colleague-drives-with-a-cortex-and-senses-it-resol.md,
    plan task t3). Optional: present on :attr:`EngineConfig.senses` only when
    the operator has declared a senses model (env var or a ``senses`` section
    in .colleague/config.json) — see :func:`_resolve_senses`. Mirrors
    :class:`DeepthinkConfig` field-for-field: the senses endpoint speaks the
    same OpenAI surface as the main endpoint through the same
    ``vllm-openai`` adapter, so retargeting stays a config change, never a
    code change (h2 precedent). This task (t3) resolves ONLY
    env > config.json > absent — the lobes discovery rung is a separate,
    later task (t4).
    """

    model: str
    base_url: str
    api_key: str
    context_budget: int
    multimodal: bool = False
    """Operator declaration that the senses model accepts media content
    parts — senses is the natural multimodal front door (intake / speak-back
    on the operator-facing surfaces). Never probed or inferred from a model
    name; default ``False`` keeps a senses config byte-identical."""


@dataclass(frozen=True)
class WorkerConfig:
    """A resolved worker (three-tier bounded-tool-loop actor) dial target.

    Three-tier-execution arc (plan task t3). Present on
    :attr:`EngineConfig.worker` ONLY when three-tier execution is EXPLICITLY
    armed (the ``three_tier`` config/env block — see
    :func:`_resolve_three_tier_enabled`) AND the lobes gateway advertises a
    ready ``worker`` role — resolution REQUIRES the role; unlike
    :class:`DeepthinkConfig`/:class:`SensesConfig` there is NO
    env/config.json-declared worker *model* (role NAMES only, never
    model-name parsing — the t3 design boundary, see :func:`_resolve_worker`).
    An armed-but-unresolvable worker raises a loud refusal instead of ever
    degrading to ``None`` and falling back to cortex silently acting as the
    worker (c25/h21) — the opposite stance every other lobes-fed rung takes.

    ``base_url``/``api_key`` mirror the dial-target shape of every sibling
    config (:func:`_role_dial_base_url` / the #347/#348 same-origin key
    hygiene rule). ``context`` is the role's OWN advertised window, read
    verbatim off the wire (never scaled/derived — unlike
    deepthink/senses' ``context_budget``, since this task performs
    RESOLUTION ONLY; nothing yet consumes this field to window a prompt).

    RESOLUTION ONLY in this task — nothing in the loop consumes this field
    yet; a later task (t8) wires the worker into the bounded tool loop as the
    acting seat.
    """

    model: str
    base_url: str
    api_key: str
    context: int


@dataclass(frozen=True)
class SeatConfig:
    """One resolved thought→action→evaluation seat's dial target (plan task t12).

    Field-for-field :class:`WorkerConfig`'s shape — model id, dial target,
    api_key (same-origin hygiene, #347/#348), and the role's OWN advertised
    context window read verbatim off the wire — because a seat *is* the same
    kind of thing: a lobes role colleague may dial. It is a separate type only
    so the three-tier worker seat and this mode's seats can never be confused
    for one another by a reader or a consumer.

    Which lobes role fills which seat is :data:`_EVALUATION_SEAT_ROLES` and
    nothing else: there is no declared seat model anywhere, and no model-name
    parsing anywhere (spec c40).
    """

    model: str
    base_url: str
    api_key: str
    context: int


@dataclass(frozen=True)
class EvaluationSeats:
    """The three seats of the thought→action→evaluation mode (plan task t12).

    Present on :attr:`EngineConfig.evaluation_seats` ONLY when the mode is
    EXPLICITLY armed (``COLLEAGUE_THOUGHT_ACTION_EVALUATION`` /
    config.json ``thought_action_evaluation``) AND the lobes gateway advertises
    a ready role for every seat. All three are MANDATORY: an armed-but-
    unresolvable seat raises a loud refusal naming the seat and the role
    (:func:`_resolve_evaluation_seats`) instead of ever degrading to a silent
    fallback — a silently missing evaluator would remove the mode's entire
    safety property.

    - :attr:`front` (lobes ``senses``) — commits typed Thoughts; no repo tools.
    - :attr:`worker` (lobes ``worker``) — realizes a Thought through tools.
    - :attr:`evaluator` (lobes ``cortex``) — tools-off thought↔action fidelity
      judgment; CANNOT write durable memory (spec c38/h30 — see
      :attr:`EngineConfig.evaluator_checkpoint`).

    RESOLUTION ONLY: nothing consumes these seats yet (the control loop is plan
    task t13). Deepthink is unconditionally absent whenever this is present,
    exactly as in three-tier mode.
    """

    front: SeatConfig
    worker: SeatConfig
    evaluator: SeatConfig


@dataclass(frozen=True)
class VoiceConfig:
    """A resolved voice (stt/tts) escalation target.

    Senses live-presence + voice arc. Optional: present on
    :attr:`EngineConfig.voice` only when at least one of ``stt_model`` or
    ``tts_model`` is resolved. Mirrors :class:`SensesConfig` field-for-field
    (base_url/api_key default to the main endpoint). Precedence:
    ``COLLEAGUE_STT_MODEL``/``COLLEAGUE_TTS_MODEL`` env > ``voice`` section of
    .colleague/config.json > lobes discovery > absent (None).

    ``stt_base_url``/``tts_base_url`` are SEPARATE fields (colleague#292, S1's
    follow-on / S2): pre-0.38 both stt and tts were forced to dial a single
    blanket gateway-origin value (there was no other reachable target), but
    since lobes-cli 0.38.0 each role can report its OWN genuinely dialable
    endpoint (lobes-cli#87) — a rig serving stt/tts from different origins
    needs two independently-resolved dial targets, not one shared field. The
    non-lobes env/config.json path (:func:`_resolve_voice`) still sets both to
    the SAME value (there is only one declared voice base_url there), so this
    split is byte-identical for every caller that isn't the lobes rung.
    """

    stt_model: str | None
    tts_model: str | None
    stt_base_url: str
    tts_base_url: str
    api_key: str


@dataclass(frozen=True)
class RealtimeConfig:
    """A resolved realtime (server-VAD live speech session) dial target.

    Realtime-speech arc (spec docs/specs/2026-07-22-realtime-speech.md, plan
    task t1). Optional: present on :attr:`EngineConfig.realtime` only when
    realtime is genuinely AVAILABLE — either an EXPLICIT operator knob
    (``COLLEAGUE_REALTIME_URL``/``COLLEAGUE_REALTIME_API_KEY`` env, or a
    ``realtime`` section in .colleague/config.json — see
    :func:`_resolve_realtime`) declares a dial target, or the lobes discovery
    rung (:func:`_realtime_lobes_fallback`) finds the gateway's ``stt`` role
    advertising the ``realtime_vad_session`` responsibility AND voice is
    already armed. Absence (``None``) means the session lane (a later task)
    must make ZERO WebSocket dial attempts — nothing is resolved to dial.

    ``available`` is always ``True`` when this object exists — there is no
    "declared but unavailable" state; unavailability is represented entirely
    by ``EngineConfig.realtime is None``. The field exists so a downstream
    consumer (a later task's session front) can render an honest state
    without re-deriving presence from "is not None" wherever it reads this
    config, and so the resolved shape is self-documenting in the artifact
    snapshot (:meth:`EngineConfig.to_dict`).

    ``ws_url`` is the ws(s) ``/v1/realtime`` dial target (see
    :func:`_realtime_ws_url`) — never an http(s) URL, so a caller never has to
    re-derive the scheme swap. ``api_key`` follows the #348 same-origin
    hygiene rule on the discovery rung; the explicit rung inherits the main
    key unconditionally (trusted operator intent) unless it declares its own.

    ``input_device``/``output_device`` (plan task t4) are PURE LOCAL knobs —
    a PortAudio device id (e.g. ``"2"``) or a name substring (e.g.
    ``"Reachy Mini"``) naming which mic/speaker on THIS machine the session
    lane's capture/playback functions (``colleague/realtime.py``) should open.
    Unlike every other field on this class, they resolve IDENTICALLY
    regardless of which rung produced this object — a discovered dial target
    says nothing about which physical device this box should use, so both
    :func:`_resolve_realtime` and :func:`_realtime_lobes_fallback` read the
    SAME env/config.json knobs via :func:`_resolve_realtime_devices`.
    ``None`` (the default) means "let the audio library pick its own
    default device" — never a forced index.
    """

    available: bool
    ws_url: str
    api_key: str
    input_device: str | None = None
    output_device: str | None = None


@dataclass(frozen=True)
class ResolveOverrides:
    """Bundle of secondary numeric-knob explicit overrides for :meth:`EngineConfig.resolve`.

    Every knob here still resolves through the SAME ``COLLEAGUE_*`` env var >
    ``.colleague/config.json`` > built-in-default precedence as before when
    left ``None`` — nothing about resolution itself changed. The only thing
    that moved is WHERE an explicit override is expressed: no production CLI
    flow ever sets more than the six identity/sizing knobs that stayed
    top-level params on ``resolve()`` (``base_url``, ``api_key``, ``model``,
    ``max_steps``, ``repo_path``, ``discover_lobes``); these eight are
    exercised ONLY by tests that pin one knob's own precedence in isolation
    (e.g. "an explicit ``context_budget_tokens`` beats the env var"). Bundling
    them here holds ``resolve()``'s parameter list under the SonarCloud S107
    ceiling (13) without dropping that per-knob override capability. Pure
    extraction — no behavior change.
    """

    context_budget_tokens: int | None = None
    max_output_chars: int | None = None
    subagent_concurrency: int | None = None
    autosplit_target_tokens: int | None = None
    fillline_threshold: float | None = None
    fanout_files: int | None = None
    plan_offer_tokens: int | None = None
    max_continue_nudges: int | None = None

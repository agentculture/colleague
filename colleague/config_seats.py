"""Seat resolution: the acting dial, the worker/evaluation seats, voice, realtime.

The rungs that turn resolved endpoints plus lobes role adverts into the
concrete seats a run drives — :func:`_resolve_acting_dial` (who the tool loop
actually dials), the three-tier worker, the thought→action→evaluation seat
triple, the mutual-exclusion refusal, and the deepthink / senses / voice /
realtime dial resolvers. Split out of ``config.py`` (hard 1000-line file
limit, plan ``hard-1000-line-file-limit`` t14) — a pure move, no precedence
changed. Every name is re-exported from :mod:`colleague.config`.
"""

from __future__ import annotations

from colleague.config_defaults import (
    _DEFAULT_API_KEY,
    _DEFAULT_DEEPTHINK_CONTEXT_BUDGET,
    _DEFAULT_SENSES_CONTEXT_BUDGET,
    _EVALUATION_SEAT_ROLES,
)
from colleague.config_files import _pick, _try_int
from colleague.config_lobes import (
    _realtime_ws_url,
    _role_dial_base_url,
    _same_origin,
    _seat_refusal,
    _worker_refusal,
)
from colleague.config_types import (
    DeepthinkConfig,
    EvaluationSeats,
    RealtimeConfig,
    SeatConfig,
    SensesConfig,
    VoiceConfig,
    WorkerConfig,
)


def _resolve_acting_dial(
    resolved_worker: "WorkerConfig | None",
    resolved_seats: "EvaluationSeats | None",
    *,
    main: tuple[str, str, str, int],
) -> tuple[str, str, str, int]:
    """Return ``(model, base_url, api_key, context)`` for the seat that ACTS.

    Exactly one seat acts. Unarmed, that is the main dial. Under three-tier
    (t8) it is ``resolved_worker``; under thought→action→evaluation (t13) it is
    ``resolved_seats.worker`` — the evaluator never acts. The two modes are
    mutually exclusive (``_refuse_conflicting_execution_modes``), so the
    branches below can never both apply.

    Note this repoints the ACTING dial only. ``distill.py``'s
    authority-separation guard reads ``evaluator_checkpoint``, never
    ``config.model``, so moving this dial cannot weaken it (spec c38/h30).
    """
    if resolved_worker is not None:
        return (
            resolved_worker.model,
            resolved_worker.base_url,
            resolved_worker.api_key,
            resolved_worker.context,
        )
    if resolved_seats is not None:
        return (
            resolved_seats.worker.model,
            resolved_seats.worker.base_url,
            resolved_seats.worker.api_key,
            resolved_seats.worker.context,
        )
    return main


def _resolve_worker(
    three_tier: bool,
    lobes_roles: object,
    lobes_gateway_url: str | None,
    declared_lobes_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_worker: dict[str, str],
) -> "WorkerConfig | None":
    """Resolve the three-tier worker seat — REQUIRED when three-tier is armed
    (three-tier-execution arc, plan task t3; covers c3/h3/c25/h21).

    **Not armed (default): a strict no-op.** Returns ``None`` immediately
    without even inspecting ``lobes_roles.worker`` — an advertised worker
    role is read and discarded exactly like ``reranker``, byte-identical to
    today (acceptance criterion 3 of task t3).

    **Armed: the worker role is MANDATORY, never a silent fallback.** Unlike
    every other lobes-fed rung, which degrades to ``None`` on any resolution
    failure, an EXPLICITLY armed three-tier config raises
    :class:`~colleague.cli._errors.CliError` (via :func:`_worker_refusal`)
    naming exactly what is missing — no lobes gateway configured, an
    unreachable gateway, or the gateway advertising no READY worker role —
    rather than ever falling back to cortex silently acting as the worker.
    The refusal fires HERE, at resolution time (``EngineConfig.resolve()``),
    before any episode starts — both ``work`` and ``session`` call
    ``resolve()`` before dispatching any work, so the refusal is uniform
    across both CLI fronts.

    There is deliberately NO declared-worker-model rung (unlike
    deepthink/senses/voice): the worker seat is resolved ONLY by ROLE NAME
    from the lobes gateway — colleague never parses a model name to decide
    who the worker is (the t3 design boundary, "role NAMES only, never
    model-name parsing").

    *declared_lobes_url* is the RAW, no-network operator declaration
    (:func:`resolve_lobes_gateway_url`) — distinct from *lobes_gateway_url*,
    which :func:`_resolve_lobes_rung` already collapses to ``None`` on EITHER
    "nothing declared" OR "declared but unreachable/malformed" (every other
    lobes-fed rung treats those two states identically — they both just fall
    through to the next precedence rung). The refusal here tells them apart
    so the message names the real gap: "no gateway configured" vs "gateway
    `<url>` unreachable".

    **api_key hygiene** mirrors :func:`_senses_lobes_fallback` /
    :func:`_deepthink_lobes_fallback` (colleague#347/#348): an explicit
    ``COLLEAGUE_WORKER_API_KEY`` env or config.json ``worker.api_key`` —
    usable even though there is no declared worker model, since presence is
    keyed on the ARMED three-tier block instead — always wins. Otherwise the
    MAIN key is inherited only when the worker's resolved dial target shares
    the main endpoint's origin (:func:`_same_origin`); a cross-origin worker
    gets the withheld :data:`_DEFAULT_API_KEY` default instead, so the main
    Bearer token is never forwarded to a host a wire payload advertised — the
    SAME withheld-default mechanism the deepthink/senses/voice rungs already
    use (there is no separate notice function; the withheld default IS the
    mechanism, exactly as documented in ``docs/features/cortex-senses.md``'s
    api_key hygiene section). A wrong/absent key degrades visibly at the
    worker dial site (a later task), never fails resolution here.
    """
    if not three_tier:
        return None
    if declared_lobes_url is None:
        raise _worker_refusal(
            "three-tier execution is armed (three_tier) but no lobes gateway is "
            "configured — the worker role can only be discovered from a lobes "
            "gateway",
            "set COLLEAGUE_LOBES_URL or a 'lobes' section in .colleague/config.json "
            "to a gateway advertising a ready worker role, or unset three_tier",
        )
    if lobes_gateway_url is None or lobes_roles is None:
        raise _worker_refusal(
            f"three-tier execution is armed (three_tier) but the lobes gateway "
            f"{declared_lobes_url!r} is unreachable — the worker role could not be "
            "resolved",
            "check the lobes gateway is running and reachable, or unset three_tier",
        )
    worker_role = getattr(lobes_roles, "worker", None)
    if worker_role is None or not getattr(worker_role, "ready", False):
        raise _worker_refusal(
            f"three-tier execution is armed (three_tier) but the lobes gateway "
            f"{lobes_gateway_url!r} advertises no ready worker role",
            "arm a ready worker role on the lobes gateway, or unset three_tier",
        )
    worker_base_url = _role_dial_base_url(worker_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_WORKER_API_KEY",
        default=file_worker.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(worker_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    return WorkerConfig(
        model=worker_role.model,
        base_url=worker_base_url,
        api_key=api_key,
        context=int(getattr(worker_role, "context", 0) or 0),
    )


# ---------------------------------------------------------------------------
# Thought→action→evaluation mode arming (post-#387 program, plan task t12;
# issue #397; spec c17/c26, honesty h10/h19).
# ---------------------------------------------------------------------------


def _refuse_conflicting_execution_modes(
    three_tier: bool, thought_action_evaluation: bool, agents: bool = False
) -> None:
    """Refuse when more than ONE execution mode is armed at once (plan task t12; #411 t7).

    Execution modes cannot share the acting seat, and silently letting one
    win by precedence is exactly the class of quiet degradation this arc
    exists to prevent — an operator who armed two must be told, not guessed
    at. A strict no-op unless at least two are armed. The refusal NAMES both
    modes and both switches.
    """
    armed = [
        (name, switch)
        for name, switch, on in (
            ("three_tier", "COLLEAGUE_THREE_TIER", three_tier),
            (
                "thought_action_evaluation",
                "COLLEAGUE_THOUGHT_ACTION_EVALUATION",
                thought_action_evaluation,
            ),
            ("agents", "COLLEAGUE_AGENTS", agents),
        )
        if on
    ]
    if len(armed) < 2:
        return
    names = " and ".join(name for name, _ in armed)
    switches = " / ".join(switch for _, switch in armed)
    raise _seat_refusal(
        f"{names} are both armed — they are independent execution modes and "
        "cannot both own the acting seat",
        f"unset one of {switches} (or the matching .colleague/config.json key)",
    )


def _refuse_unusable_evaluation_gateway(
    declared_lobes_url: str | None,
    lobes_gateway_url: str | None,
    lobes_roles: object,
) -> None:
    """Raise the two GATEWAY-level arming refusals for the mode (plan task t12).

    Mirrors :func:`_resolve_worker`'s first two refusal branches, including the
    *declared* vs *resolved* URL distinction: ``declared_lobes_url`` is the
    RAW, no-network operator declaration, while ``lobes_gateway_url`` is
    already collapsed to ``None`` on EITHER "nothing declared" OR "declared but
    unreachable/malformed" — telling them apart is what lets the message name
    the real gap.
    """
    if declared_lobes_url is None:
        raise _seat_refusal(
            "thought→action→evaluation mode is armed (thought_action_evaluation) "
            "but no lobes gateway is configured — the front, worker, and evaluator "
            "seats can only be discovered from a lobes gateway",
            "set COLLEAGUE_LOBES_URL or a 'lobes' section in .colleague/config.json "
            "to a gateway advertising ready senses/worker/cortex roles, or unset "
            "thought_action_evaluation",
        )
    if lobes_gateway_url is None or lobes_roles is None:
        raise _seat_refusal(
            "thought→action→evaluation mode is armed (thought_action_evaluation) "
            f"but the lobes gateway {declared_lobes_url!r} is unreachable — the "
            "front, worker, and evaluator seats could not be resolved",
            "check the lobes gateway is running and reachable, or unset "
            "thought_action_evaluation",
        )


def _seat_api_key(
    seat: str,
    file_seat: dict[str, str],
    seat_base_url: str,
    main_base_url: str,
    main_api_key: str,
) -> str:
    """Resolve one seat's api_key under the #347/#348 same-origin hygiene rule.

    An explicit ``COLLEAGUE_<SEAT>_API_KEY`` env or a ``<seat>.api_key`` in
    config.json always wins (trusted operator intent). Otherwise the MAIN key
    is inherited only when the seat's resolved dial target shares the main
    endpoint's origin; a cross-origin seat gets the withheld
    :data:`_DEFAULT_API_KEY` instead, so the main Bearer token is never
    forwarded to a host a wire payload advertised. Identical in mechanism to
    :func:`_resolve_worker`'s own key hygiene.
    """
    explicit = _pick(
        None,
        f"COLLEAGUE_{seat.upper()}_API_KEY",
        default=file_seat.get("api_key", ""),
    )
    if explicit:
        return explicit
    if _same_origin(seat_base_url, main_base_url):
        return main_api_key
    return _DEFAULT_API_KEY


def _resolve_evaluation_seats(
    armed: bool,
    lobes_roles: object,
    lobes_gateway_url: str | None,
    declared_lobes_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_seats: dict[str, dict[str, str]],
) -> "EvaluationSeats | None":
    """Resolve the thought→action→evaluation mode's three seats (plan task t12).

    **Not armed (default): a strict no-op.** Returns ``None`` without
    inspecting a single role — every advertised role is read and discarded
    exactly as it is today, so an unarmed resolution is byte-identical
    (acceptance criterion 1, honesty h19/h10).

    **Armed: every seat is MANDATORY and resolved BY ROLE NAME.**
    :data:`_EVALUATION_SEAT_ROLES` is the whole mapping — ``front`` ←
    ``senses``, ``worker`` ← ``worker``, ``evaluator`` ← ``cortex`` — read off
    the gateway's ``/capabilities`` contract. There is deliberately NO
    declared-seat-model rung anywhere: colleague never parses a model name to
    decide who fills a seat (spec c40 — the reference rig's specific model ids
    are a CANDIDATE, never an architectural requirement). A missing or not-``ready``
    role raises :class:`~colleague.cli._errors.CliError` naming BOTH the seat
    and the role it resolves from, rather than falling back to another seat's
    model: a silent fallback would leave the operator believing they have an
    evaluator seat when they do not, which removes the mode's entire safety
    property (acceptance criterion 2).

    The refusal fires HERE, at resolution time (``EngineConfig.resolve()``),
    before any episode starts — uniform across the ``work`` and ``session``
    fronts, exactly like three-tier's worker refusal.

    RESOLUTION ONLY in this task: nothing consumes these seats yet. The
    control loop (which seat acts when, and the evaluator's invocation
    boundaries) is plan task t13's territory — this task arms the seats, not
    their payloads. Consequently the ACTING dial (``model``/``base_url``/
    ``api_key``) is deliberately left UNCHANGED by arming, unlike three-tier's
    t8 worker-as-actor override.
    """
    if not armed:
        return None
    _refuse_unusable_evaluation_gateway(declared_lobes_url, lobes_gateway_url, lobes_roles)
    seats: dict[str, SeatConfig] = {}
    for seat, role_name in _EVALUATION_SEAT_ROLES:
        role = getattr(lobes_roles, role_name, None)
        if role is None or not getattr(role, "ready", False):
            raise _seat_refusal(
                "thought→action→evaluation mode is armed (thought_action_evaluation) "
                f"but the lobes gateway {lobes_gateway_url!r} advertises no ready "
                f"{role_name} role — the {seat} seat resolves BY ROLE NAME from "
                "/capabilities and has no fallback",
                f"arm a ready {role_name} role on the lobes gateway, or unset "
                "thought_action_evaluation",
            )
        seat_base_url = _role_dial_base_url(role, lobes_gateway_url)
        seats[seat] = SeatConfig(
            model=role.model,
            base_url=seat_base_url,
            api_key=_seat_api_key(
                seat,
                file_seats.get(seat, {}),
                seat_base_url,
                main_base_url,
                main_api_key,
            ),
            context=int(getattr(role, "context", 0) or 0),
        )
    return EvaluationSeats(**seats)


def _resolve_realtime_devices(file_realtime: dict[str, str]) -> tuple[str | None, str | None]:
    """Resolve the LOCAL-MACHINE input/output device knobs (plan task t4).

    Precedence per key: ``COLLEAGUE_REALTIME_INPUT_DEVICE``/
    ``COLLEAGUE_REALTIME_OUTPUT_DEVICE`` env > the ``realtime`` section of
    .colleague/config.json > absent (``None`` — the audio library's own
    default device). These are PURE LOCAL knobs — an id (e.g. ``"2"``) or a
    name substring (e.g. ``"Reachy Mini"``) naming a PortAudio device on THIS
    machine — so, unlike every other RealtimeConfig field, they are resolved
    IDENTICALLY on BOTH the explicit rung (:func:`_resolve_realtime`) and the
    lobes discovery fallback (:func:`_realtime_lobes_fallback`): a discovered
    dial target says nothing about which physical mic/speaker this box
    should use, so both rungs call this ONE helper with the same
    *file_realtime* dict. A blank/whitespace-only value resolves to ``None``,
    same stance as every other blank-string field in this module.
    """
    input_device = _pick(
        None,
        "COLLEAGUE_REALTIME_INPUT_DEVICE",
        default=file_realtime.get("input_device", ""),
    ).strip()
    output_device = _pick(
        None,
        "COLLEAGUE_REALTIME_OUTPUT_DEVICE",
        default=file_realtime.get("output_device", ""),
    ).strip()
    return (input_device or None, output_device or None)


def _resolve_realtime(
    file_realtime: dict[str, str],
    main_api_key: str,
) -> "RealtimeConfig | None":
    """Resolve the EXPLICIT operator-declared realtime dial-target knob
    (realtime-speech arc, plan task t1).

    Precedence per key: ``COLLEAGUE_REALTIME_URL``/``COLLEAGUE_REALTIME_API_KEY``
    env > the ``realtime`` section of .colleague/config.json > absent
    (``None``). No ``CONVERTIBLE_*`` fallback — realtime postdates the
    CONVERTIBLE->COLLEAGUE rename, the same stance
    ``COLLEAGUE_VOICE_API_KEY`` already takes (see :func:`_resolve_voice`).

    Realtime is PRESENT iff the resolved ``url`` is a non-empty,
    non-whitespace string — the "the url IS the presence signal" stance every
    sibling rung takes with its own model field (deepthink/senses/voice); an
    operator-set ``api_key`` with no ``url`` is not a realtime declaration on
    its own (mirrors :func:`_resolve_voice`'s ``stt_model``/``tts_model``
    gate) — it can still arm a DISCOVERED cross-origin role's key, see
    :func:`_realtime_lobes_fallback`.

    This is the OPERATOR-DECLARED rung ONLY — it never consults lobes; the
    discovery fallback (:func:`_realtime_lobes_fallback`) is a SEPARATE,
    lower-precedence rung consulted only when this resolves ``None``.
    ``api_key`` defaults to *main_api_key* with NO same-origin check — an
    explicit operator declaration is trusted intent (the same stance
    :func:`_resolve_voice`/:func:`_resolve_senses`/:func:`_resolve_deepthink`
    take for their own explicit config); same-origin hygiene (#348) applies
    ONLY to the lobes-derived fallback below, whose dial target comes from an
    untrusted wire payload.
    """
    url = _pick(None, "COLLEAGUE_REALTIME_URL", default=file_realtime.get("url", ""))
    if not url.strip():
        return None
    api_key = _pick(
        None,
        "COLLEAGUE_REALTIME_API_KEY",
        default=file_realtime.get("api_key") or main_api_key,
    )
    input_device, output_device = _resolve_realtime_devices(file_realtime)
    return RealtimeConfig(
        available=True,
        ws_url=_realtime_ws_url(url.strip()),
        api_key=api_key,
        input_device=input_device,
        output_device=output_device,
    )


def _realtime_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_realtime: dict[str, str],
    voice: "VoiceConfig | None",
) -> "RealtimeConfig | None":
    """The stt ``realtime_vad_session`` -> RealtimeConfig discovery fallback
    (realtime-speech arc, plan task t1).

    Mirrors :func:`_voice_lobes_fallback`'s extraction shape and api_key
    hygiene. Returns ``None`` unless ALL of: lobes resolved (*lobes_roles*/
    *lobes_gateway_url* both non-``None``), voice is ALREADY armed (*voice* is
    not ``None`` — the spec requirement's "realtime arms only when voice is
    armed"), the gateway advertises an ``stt`` role, and that role carries
    :data:`colleague.lobes.REALTIME_VAD_RESPONSIBILITY` in its
    ``responsibilities`` (:func:`colleague.lobes.stt_supports_realtime` — the
    ONE live availability signal, probed 2026-07-22). In practice a
    successfully-parsed stt :class:`~colleague.lobes.RoleInfo` always carries
    a non-blank model, which already arms ``voice`` via
    :func:`_voice_lobes_fallback` — the *voice* check here is a stated,
    defensive gate matching the requirement text verbatim, not a
    reachable-in-practice branch through the public resolution path.

    **api_key hygiene (the #348 rule, extended to realtime).** An explicitly
    declared realtime key (``COLLEAGUE_REALTIME_API_KEY`` env or config.json
    ``realtime.api_key`` — usable even without a declared ``url``) always
    wins. Otherwise the MAIN key is inherited only when the stt role's OWN
    resolved dial origin (:func:`colleague.lobes.resolve_role_base_url`)
    shares the main endpoint's origin (:func:`_same_origin`); a cross-origin
    stt role gets :data:`_DEFAULT_API_KEY` instead, so the main Bearer token
    is never forwarded to a host a wire payload advertised — the identical
    Qodo finding on colleague#347/#348 the deepthink/senses/voice rungs
    already close. A wrong/absent key degrades visibly at the realtime dial
    site (a later task), never fails resolution here.
    """
    if voice is None or lobes_roles is None or lobes_gateway_url is None:
        return None
    stt_role = getattr(lobes_roles, "stt", None)
    # Lazy import mirrors every other lobes-consulting helper in this module
    # (keeps config's module import graph unchanged; lets tests monkeypatch it).
    from colleague import lobes as _lobes

    if not _lobes.stt_supports_realtime(stt_role):
        return None
    origin = _lobes.resolve_role_base_url(stt_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_REALTIME_API_KEY",
        default=file_realtime.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(origin, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    input_device, output_device = _resolve_realtime_devices(file_realtime)
    return RealtimeConfig(
        available=True,
        ws_url=_realtime_ws_url(origin),
        api_key=api_key,
        input_device=input_device,
        output_device=output_device,
    )


def _resolve_deepthink(
    file_deepthink: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "DeepthinkConfig | None":
    """Resolve the optional dual-model deepthink escalation target.

    Precedence per key: ``COLLEAGUE_DEEPTHINK_*`` env (``CONVERTIBLE_DEEPTHINK_*``
    honored as a deprecated fallback, matching every other knob in this module)
    > the ``deepthink`` section of .colleague/config.json > a default.

    Dual-model is PRESENT iff the resolved model is a non-empty, non-whitespace
    string; otherwise this returns ``None`` regardless of the other keys — an
    operator-set base_url/api_key/context_budget with no model is not a
    dual-model declaration (the model IS the presence signal, spec h1).

    ``base_url``/``api_key`` default to *main_base_url*/*main_api_key* — the
    ALREADY-resolved main endpoint values — so declaring dual-model needs only
    a model id unless deepthink truly lives at a different endpoint. An empty
    file value for ``base_url``/``api_key`` is treated as absent (falls
    through to the main endpoint), matching the env-var "empty is absent"
    convention used throughout this module.

    ``context_budget`` parses as an int; a malformed or absent value falls
    back to :data:`_DEFAULT_DEEPTHINK_CONTEXT_BUDGET` and never raises,
    mirroring every other numeric knob resolved via :func:`_try_int`.
    """
    model = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_MODEL",
        "CONVERTIBLE_DEEPTHINK_MODEL",
        default=file_deepthink.get("model", ""),
    )
    if not model.strip():
        return None
    base_url = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_BASE_URL",
        "CONVERTIBLE_DEEPTHINK_BASE_URL",
        default=file_deepthink.get("base_url") or main_base_url,
    )
    api_key = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_API_KEY",
        "CONVERTIBLE_DEEPTHINK_API_KEY",
        default=file_deepthink.get("api_key") or main_api_key,
    )
    context_budget = _try_int(
        _pick(
            None,
            "COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET",
            "CONVERTIBLE_DEEPTHINK_CONTEXT_BUDGET",
            default=file_deepthink.get("context_budget", ""),
        ),
        default=_DEFAULT_DEEPTHINK_CONTEXT_BUDGET,
    )
    # The media-bridge declaration (t8): truthy strings arm it, anything else
    # (absent, empty, junk) resolves False — a declaration, never a probe.
    multimodal = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_MULTIMODAL",
        "CONVERTIBLE_DEEPTHINK_MULTIMODAL",
        default=file_deepthink.get("multimodal", ""),
    ).strip().lower() in ("1", "true", "yes")
    return DeepthinkConfig(
        model=model.strip(),
        base_url=base_url,
        api_key=api_key,
        context_budget=context_budget,
        multimodal=multimodal,
    )


def _resolve_senses(
    file_senses: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "SensesConfig | None":
    """Resolve the optional senses (multimodal front-door) escalation target.

    Mirrors :func:`_resolve_deepthink` field-for-field (cortex/senses arc,
    task t3). Precedence per key: ``COLLEAGUE_SENSES_*`` env
    (``CONVERTIBLE_SENSES_*`` honored as a deprecated fallback, matching
    every other knob in this module) > the ``senses`` section of
    .colleague/config.json > a default.

    Senses is PRESENT iff the resolved model is a non-empty, non-whitespace
    string; otherwise this returns ``None`` regardless of the other keys —
    an operator-set base_url/api_key/context_budget with no model is not a
    senses declaration (the model IS the presence signal, same as deepthink).

    ``base_url``/``api_key`` default to *main_base_url*/*main_api_key* — the
    ALREADY-resolved main endpoint values — so declaring senses needs only a
    model id unless senses truly lives at a different endpoint. An empty
    file value for ``base_url``/``api_key`` is treated as absent (falls
    through to the main endpoint), matching the env-var "empty is absent"
    convention used throughout this module.

    ``context_budget`` parses as an int; a malformed or absent value falls
    back to :data:`_DEFAULT_SENSES_CONTEXT_BUDGET` and never raises,
    mirroring every other numeric knob resolved via :func:`_try_int`.

    Scope note (task t3): this resolves ONLY env > config.json > absent — the
    lobes discovery rung (t4) is a separate, later task and is not consulted
    here.
    """
    model = _pick(
        None,
        "COLLEAGUE_SENSES_MODEL",
        "CONVERTIBLE_SENSES_MODEL",
        default=file_senses.get("model", ""),
    )
    if not model.strip():
        return None
    # INTENTIONAL (Qodo #2, cortex/senses PR #281): the ``or`` below treats an
    # explicitly-empty config.json ``senses.base_url``/``api_key`` string the
    # SAME as an absent key — both fall through to the main endpoint's already-
    # resolved value. This is not a lost override: a JSON string field cannot
    # distinguish "explicitly blank" from "omitted" any more usefully than
    # "absent" does here, and this is the field-for-field mirror of
    # ``_resolve_deepthink``'s identical ``file_x or main_x`` pattern a few
    # functions above — changing it here without changing deepthink would
    # split the two resolvers' behavior. See
    # ``tests/test_config_senses.py::test_config_file_empty_base_url_and_api_key_fall_through_to_main``
    # for the pinned regression test.
    base_url = _pick(
        None,
        "COLLEAGUE_SENSES_BASE_URL",
        "CONVERTIBLE_SENSES_BASE_URL",
        default=file_senses.get("base_url") or main_base_url,
    )
    api_key = _pick(
        None,
        "COLLEAGUE_SENSES_API_KEY",
        "CONVERTIBLE_SENSES_API_KEY",
        default=file_senses.get("api_key") or main_api_key,
    )
    context_budget = _try_int(
        _pick(
            None,
            "COLLEAGUE_SENSES_CONTEXT_BUDGET",
            "CONVERTIBLE_SENSES_CONTEXT_BUDGET",
            default=file_senses.get("context_budget", ""),
        ),
        default=_DEFAULT_SENSES_CONTEXT_BUDGET,
    )
    # A declaration, never a probe — truthy strings arm it, anything else
    # (absent, empty, junk) resolves False, mirroring deepthink.multimodal.
    multimodal = _pick(
        None,
        "COLLEAGUE_SENSES_MULTIMODAL",
        "CONVERTIBLE_SENSES_MULTIMODAL",
        default=file_senses.get("multimodal", ""),
    ).strip().lower() in ("1", "true", "yes")
    return SensesConfig(
        model=model.strip(),
        base_url=base_url,
        api_key=api_key,
        context_budget=context_budget,
        multimodal=multimodal,
    )


def _resolve_voice(
    file_voice: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "VoiceConfig | None":
    """Resolve the optional voice (stt/tts) escalation target.

    Mirrors :func:`_resolve_senses` field-for-field. Precedence per key:
    ``COLLEAGUE_STT_MODEL``/``COLLEAGUE_TTS_MODEL``/``COLLEAGUE_VOICE_*`` env
    > the ``voice`` section of .colleague/config.json > a default.

    Voice is PRESENT iff at least one of ``stt_model`` or ``tts_model`` is a
    non-empty, non-whitespace string; otherwise this returns ``None``.

    ``base_url``/``api_key`` default to *main_base_url*/*main_api_key* — the
    ALREADY-resolved main endpoint values. An empty file value for
    ``base_url``/``api_key`` is treated as absent (falls through to the main
    endpoint).
    """
    stt_model = _pick(
        None,
        "COLLEAGUE_STT_MODEL",
        default=file_voice.get("stt_model", ""),
    )
    tts_model = _pick(
        None,
        "COLLEAGUE_TTS_MODEL",
        default=file_voice.get("tts_model", ""),
    )
    stt_model = stt_model.strip() if stt_model else ""
    tts_model = tts_model.strip() if tts_model else ""
    if not stt_model and not tts_model:
        return None
    base_url = _pick(
        None,
        "COLLEAGUE_VOICE_BASE_URL",
        default=file_voice.get("base_url") or main_base_url,
    )
    api_key = _pick(
        None,
        "COLLEAGUE_VOICE_API_KEY",
        default=file_voice.get("api_key") or main_api_key,
    )
    return VoiceConfig(
        stt_model=stt_model or None,
        tts_model=tts_model or None,
        stt_base_url=base_url,
        tts_base_url=base_url,
        api_key=api_key,
    )

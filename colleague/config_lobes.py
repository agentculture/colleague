"""Lobes gateway discovery: URLs, role adverts, and the discovery rung.

Everything that turns an operator-declared ``lobes`` gateway into resolved
dial targets BY ROLE NAME — the gateway URL resolution, per-role base-url
derivation, the senses / muse / voice role→config fallbacks (each reached ONLY
under its opt-in sentinel, qwen-direct c2/c4), the refusal helpers and
:func:`_resolve_lobes_rung` itself. Split out of ``config.py`` (hard 1000-line
file limit, plan ``hard-1000-line-file-limit`` t14) — a pure move, no
resolution order changed. Every name is re-exported from
:mod:`colleague.config`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from colleague.config_defaults import (
    _DEEPTHINK_DEFAULT_WINDOW,
    _DEFAULT_API_KEY,
    _DEFAULT_BASE_URL,
    _DEFAULT_DEEPTHINK_CONTEXT_BUDGET,
    _DEFAULT_SENSES_CONTEXT_BUDGET,
    _SENSES_DEFAULT_WINDOW,
)
from colleague.config_files import _load_lobes_override, _pick
from colleague.config_types import DeepthinkConfig, SensesConfig, VoiceConfig

if TYPE_CHECKING:
    from colleague.cli._errors import CliError


def resolve_lobes_gateway_url(repo_path: str | Path | None = None) -> str | None:
    """The armed lobes gateway URL, or ``None`` when the rung is unarmed. NO network.

    Precedence: ``COLLEAGUE_LOBES_URL`` env (``CONVERTIBLE_LOBES_URL`` honored as
    a deprecated fallback) > a ``lobes`` section in .colleague/config.json (only
    when *repo_path* is given) > ``None``. Public so the doctor / ``config show``
    surfaces can report the ARMED state without consulting the gateway.

    ``None`` means the lobes discovery rung is not armed — resolution stays
    byte-identical to a pre-feature run (no ``resolve_roles`` call, no notice).
    """
    for key in ("COLLEAGUE_LOBES_URL", "CONVERTIBLE_LOBES_URL"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    if repo_path is not None:
        return _load_lobes_override(repo_path)
    return None


def _lobes_base_url(origin_url: str) -> str:
    """Append the builtin default's OpenAI path suffix (``/v1``) to *origin_url*.

    A pure shape helper: match whatever :data:`_DEFAULT_BASE_URL` carries as a
    path suffix so every lobes-derived base_url (gateway origin OR a per-role
    dial target — see :func:`_role_dial_base_url`) has the same shape as the
    builtin default. Historically this was applied to the gateway origin ONLY
    (LOBES_LIVE_FINDINGS decision 2, pre-0.38: every role's own ``endpoint``
    reported an internal, non-client-reachable host, e.g. ``http://localhost:8000``,
    so both cortex and senses were forced to dial the gateway origin instead).
    Since lobes-cli 0.38.0 closed lobes-cli#87, a role's own ``endpoint`` is
    genuinely client-reachable, so :func:`_role_dial_base_url` now feeds this
    helper the role's OWN resolved origin — the gateway origin is only the
    documented fallback (see ``colleague/lobes.py``'s ``resolve_role_base_url``).
    """
    suffix = urlsplit(_DEFAULT_BASE_URL).path.rstrip("/")
    return origin_url.rstrip("/") + suffix


#: Scheme swap applied by :func:`_realtime_ws_url` — any scheme not in this
#: map (e.g. an operator who already supplied ``ws://``/``wss://``) passes
#: through unchanged.
_WS_SCHEME_MAP = {"http": "ws", "https": "wss"}


def _realtime_ws_url(origin: str) -> str:
    """Derive the ws(s) ``/v1/realtime`` dial target from an http(s) *origin*
    (realtime-speech arc, plan task t1).

    The one shape rule: scheme swaps http->ws / https->wss via
    :data:`_WS_SCHEME_MAP` (any other scheme passes through unchanged, so an
    operator who already declares a ``ws://``/``wss://`` knob is idempotent),
    the netloc (host[:port]) is preserved exactly, and the path is ALWAYS the
    literal ``/v1/realtime`` — the OpenAI-compatible realtime session path the
    lobes gateway tunnels (probed live 2026-07-22, docs/specs/2026-07-22-
    realtime-speech.md decision c23: ``/v1/realtime`` answers 401 bare and
    101-upgrades with a Bearer key). Any query/fragment on *origin* is
    dropped — this derives a DIAL TARGET, not a general URL rewrite. Never
    raises; a malformed *origin* degrades to whatever :func:`urlsplit`
    tolerates, matching this module's degrade-never-raise stance elsewhere.
    """
    parts = urlsplit(origin)
    scheme = _WS_SCHEME_MAP.get(parts.scheme.lower(), parts.scheme.lower())
    return urlunsplit((scheme, parts.netloc, "/v1/realtime", "", ""))


def _role_dial_base_url(role: object, gateway_url: str) -> str:
    """Resolve *role*'s own dial target and apply the ``/v1``-shape suffix (lobes-cli#87).

    Delegates to :func:`colleague.lobes.resolve_role_base_url` for the
    SSRF-guarded per-role origin — the role's own ``endpoint`` when it is a
    non-empty, allowed-scheme URL, else *gateway_url* itself (an unwired role
    or a disallowed scheme) — then applies :func:`_lobes_base_url`'s suffix so
    every lobes-derived base_url shares one shape. This is the consumer switch
    (colleague#292, S1's follow-on) closing lobes-cli#87 end-to-end: cortex,
    senses, and voice (stt/tts) each dial THEIR OWN advertised endpoint instead
    of the pre-0.38 gateway-origin-for-all workaround.
    """
    # Lazy import mirrors _resolve_lobes_rung's own lazy `colleague.lobes` import
    # (keeps config's module import graph unchanged; lets tests monkeypatch it).
    from colleague import lobes as _lobes

    origin = _lobes.resolve_role_base_url(role, gateway_url)
    return _lobes_base_url(origin)


def _senses_budget_from_window(window: int) -> int:
    """A senses context_budget derived from a role's reported window.

    Applies the same headroom ratio the built-in default encodes
    (:data:`_DEFAULT_SENSES_CONTEXT_BUDGET` / :data:`_SENSES_DEFAULT_WINDOW`), so
    the live 32K senses role reproduces the hand-tuned 24000 default and any
    other window scales proportionally. Floored at 1; a non-positive window
    falls back to the default (never zero — that would disable the budget path).
    """
    if window <= 0:
        return _DEFAULT_SENSES_CONTEXT_BUDGET
    ratio = _DEFAULT_SENSES_CONTEXT_BUDGET / _SENSES_DEFAULT_WINDOW
    return max(1, int(window * ratio))


def _senses_from_lobes_role(role: object, base_url: str, api_key: str) -> "SensesConfig | None":
    """Build a :class:`SensesConfig` from the gateway's senses role (t4).

    Used only when senses is NOT otherwise declared (env/config.json win).
    *base_url* is the senses role's OWN resolved dial target (colleague#292,
    S1's follow-on: :func:`_role_dial_base_url` closes lobes-cli#87 — the
    role's own ``endpoint`` when reachable, the gateway origin only as the
    documented fallback; NOT a blanket gateway-origin-for-all as before);
    api_key inherits the resolved MAIN endpoint's value. ``multimodal`` stays
    ``False`` — the t1 :class:`~colleague.lobes.RoleInfo` carries no ``mtp``
    field, so an operator arms the media bridge by declaring senses explicitly
    (env/config, which take precedence). Returns ``None`` on a blank model.
    """
    model = str(getattr(role, "model", "") or "").strip()
    if not model:
        return None
    return SensesConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget=_senses_budget_from_window(int(getattr(role, "context", 0) or 0)),
        multimodal=False,
    )


def _deepthink_budget_from_window(window: int) -> int:
    """A deepthink context_budget derived from a role's reported window.

    Applies the same headroom ratio the built-in default encodes
    (:data:`_DEFAULT_DEEPTHINK_CONTEXT_BUDGET` / :data:`_DEEPTHINK_DEFAULT_WINDOW`),
    so a 64K role reproduces the hand-tuned 48000 default and any other window
    scales proportionally (thor's verified 262144 window → 192000). Floored at
    1; a non-positive window falls back to the default (never zero — that
    would disable the budget path). Mirrors :func:`_senses_budget_from_window`.
    """
    if window <= 0:
        return _DEFAULT_DEEPTHINK_CONTEXT_BUDGET
    ratio = _DEFAULT_DEEPTHINK_CONTEXT_BUDGET / _DEEPTHINK_DEFAULT_WINDOW
    return max(1, int(window * ratio))


def _deepthink_from_lobes_role(
    role: object, base_url: str, api_key: str
) -> "DeepthinkConfig | None":
    """Build a :class:`DeepthinkConfig` from the gateway's muse role (t5).

    The two-machines-two-minds arc's discovery rung — the sixth sanctioned
    increment at the router-exclusion boundary: resolution only, feeding the
    ALREADY-enumerated four-point escalation surface; no new decision point.
    Used only when deepthink is NOT otherwise declared (env/config.json win —
    the exact stance :func:`_senses_from_lobes_role` takes). *base_url* is the
    muse role's OWN resolved dial target (:func:`_role_dial_base_url`);
    api_key inherits the resolved MAIN endpoint's value. ``multimodal`` stays
    ``False`` — declaration, never a probe (the discovered-senses rule).
    Returns ``None`` on a blank model (presence is keyed solely on a resolved
    model, the t1 deepthink rule). The gateway's ``loaded``/``feasible`` flags
    are deliberately NOT consulted — for proxied roles they describe the
    gateway host, not the serving host (lobes-cli#146).
    """
    model = str(getattr(role, "model", "") or "").strip()
    if not model:
        return None
    return DeepthinkConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget=_deepthink_budget_from_window(int(getattr(role, "context", 0) or 0)),
        multimodal=False,
    )


def _same_origin(a: str, b: str) -> bool:
    """True when *a* and *b* share scheme + host + port (case-insensitive netloc).

    The credential-hygiene predicate for the deepthink discovery rung: the
    MAIN api_key is inherited by a DISCOVERED deepthink only toward the same
    origin the main endpoint already talks to — never forwarded to a
    different host a wire payload advertised (Qodo finding on colleague#347).
    """
    sa, sb = urlsplit(a), urlsplit(b)
    return (sa.scheme.lower(), sa.netloc.lower()) == (sb.scheme.lower(), sb.netloc.lower())


def _deepthink_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_deepthink: dict[str, str],
) -> "DeepthinkConfig | None":
    """The muse→deepthink discovery fallback, extracted from ``resolve()`` (t5).

    OPT-IN ONLY (qwen-direct): reached solely when the declared deepthink model
    is the sentinel ``lobes``; an advertised muse role alone arms nothing.

    Extraction keeps ``resolve()`` under the SonarCloud S3776 cognitive-
    complexity ceiling — the same move :func:`_resolve_lobes_rung` made.
    Returns ``None`` when lobes did not resolve, no muse role is advertised,
    or the role carries a blank model.

    **api_key hygiene.** An explicitly declared deepthink key
    (``COLLEAGUE_DEEPTHINK_API_KEY`` env or config.json ``deepthink.api_key``
    — usable even without a declared model) always wins. Otherwise the MAIN
    key is inherited only when muse's dial target shares the main endpoint's
    origin (:func:`_same_origin`); a cross-origin muse gets
    :data:`_DEFAULT_API_KEY` instead, so the main Bearer token is never
    forwarded to a host a wire payload advertised. A wrong/absent key
    degrades visibly at the escalation point (the c13 ladder), never fails
    the run.
    """
    muse_role = getattr(lobes_roles, "muse", None) if lobes_roles is not None else None
    if muse_role is None or lobes_gateway_url is None:
        return None
    deepthink_base_url = _role_dial_base_url(muse_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_DEEPTHINK_API_KEY",
        "CONVERTIBLE_DEEPTHINK_API_KEY",
        default=file_deepthink.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(deepthink_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    return _deepthink_from_lobes_role(muse_role, deepthink_base_url, api_key)


def _senses_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_senses: dict[str, str],
) -> "SensesConfig | None":
    """The senses discovery fallback, extracted from ``resolve()`` (colleague#348).

    OPT-IN ONLY (qwen-direct): reached solely when the declared senses model is
    the sentinel ``lobes``; an advertised senses role alone arms nothing.

    Mirrors :func:`_deepthink_lobes_fallback` field-for-field — the same
    extraction keeps ``resolve()`` under the SonarCloud S3776 cognitive-
    complexity ceiling. Returns ``None`` when lobes did not resolve, no
    senses role is advertised, or the role carries a blank model.

    **api_key hygiene.** An explicitly declared senses key
    (``COLLEAGUE_SENSES_API_KEY`` env or config.json ``senses.api_key`` —
    usable even without a declared model) always wins. Otherwise the MAIN
    key is inherited only when senses's dial target shares the main
    endpoint's origin (:func:`_same_origin`); a cross-origin senses gets
    :data:`_DEFAULT_API_KEY` instead, so the main Bearer token is never
    forwarded to a host a wire payload advertised (the same Qodo finding on
    colleague#347 the deepthink rung already closed — colleague#348 extends
    it to senses). A wrong/absent key degrades visibly at the senses
    call site, never fails the run.
    """
    senses_role = getattr(lobes_roles, "senses", None) if lobes_roles is not None else None
    if senses_role is None or lobes_gateway_url is None:
        return None
    senses_base_url = _role_dial_base_url(senses_role, lobes_gateway_url)
    explicit_key = _pick(
        None,
        "COLLEAGUE_SENSES_API_KEY",
        "CONVERTIBLE_SENSES_API_KEY",
        default=file_senses.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _same_origin(senses_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _DEFAULT_API_KEY
    return _senses_from_lobes_role(senses_role, senses_base_url, api_key)


def _voice_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_voice: dict[str, str],
) -> "VoiceConfig | None":
    """The stt/tts discovery fallback, extracted from ``resolve()`` (colleague#348 t2).

    Same extraction shape as :func:`_senses_lobes_fallback` — keeps
    ``resolve()`` under the SonarCloud S3776 cognitive-complexity ceiling.
    Wraps the untouched :func:`_voice_from_lobes_roles` (which stays exactly
    as-is for its existing callers/tests), computing only the api_key it is
    fed. Returns ``None`` when lobes did not resolve, or neither stt nor tts
    carries a non-blank model (no role is "armed").

    **api_key hygiene — the conservative single-field rule.**
    :class:`VoiceConfig` keeps its single ``api_key`` field — there is no
    per-role ``stt_api_key``/``tts_api_key`` split. That split is a named,
    unbuilt follow-up (decision c15, colleague#348): it would need its own
    re-spec, so it stays parked here. Because one key must cover every armed
    role, the hygiene rule is deliberately conservative rather than
    per-role: an explicitly declared voice key (``COLLEAGUE_VOICE_API_KEY``
    env or config.json ``voice.api_key`` — usable even without a declared
    model; NO ``CONVERTIBLE_VOICE_API_KEY`` fallback, since voice postdates
    the CONVERTIBLE→COLLEAGUE rename) always wins. Otherwise the MAIN key is
    inherited only when EVERY armed role's dial target (armed = a non-blank
    model; an unarmed role's gateway-fallback base_url is excluded from the
    check) shares the main endpoint's origin (:func:`_same_origin`) — stt
    and tts both same-origin inherits, but a SINGLE cross-origin role sinks
    the whole VoiceConfig to :data:`_DEFAULT_API_KEY` instead, never a
    half-armed mix of the main key on one field and the default on the
    other (there is nowhere to put a per-role result with one shared field).
    This is the same Qodo finding on colleague#347 the deepthink and senses
    rungs already closed, extended here to voice's two-role shape. A
    wrong/absent key degrades visibly at the voice call site, never fails
    the run.
    """
    if lobes_roles is None or lobes_gateway_url is None:
        return None
    stt_role = getattr(lobes_roles, "stt", None)
    tts_role = getattr(lobes_roles, "tts", None)
    armed_roles = [
        role
        for role in (stt_role, tts_role)
        if role is not None and str(getattr(role, "model", "") or "").strip()
    ]
    if not armed_roles:
        return None
    explicit_key = _pick(
        None,
        "COLLEAGUE_VOICE_API_KEY",
        default=file_voice.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    else:
        dial_targets = (_role_dial_base_url(role, lobes_gateway_url) for role in armed_roles)
        if all(_same_origin(target, main_base_url) for target in dial_targets):
            api_key = main_api_key
        else:
            api_key = _DEFAULT_API_KEY
    return _voice_from_lobes_roles(lobes_roles, lobes_gateway_url, api_key)


def _voice_from_lobes_roles(roles: object, gateway_url: str, api_key: str) -> "VoiceConfig | None":
    """Build a :class:`VoiceConfig` from the gateway's stt/tts roles (t1).

    ``roles`` is the resolved :class:`~colleague.lobes.LobesRoles` (typed
    ``object`` here to avoid a module-level ``lobes`` import — the same lazy
    stance :func:`_resolve_lobes_rung` takes). Used only when voice is NOT
    otherwise declared (env/config.json win). ``stt_base_url``/``tts_base_url``
    are EACH resolved independently via :func:`_role_dial_base_url` (colleague#292,
    S1's follow-on: closes lobes-cli#87 — a role's own ``endpoint`` when
    reachable, *gateway_url* only as the documented fallback) — no longer a
    single blanket gateway-origin-for-all value, so a rig where stt/tts are
    served from genuinely different origins dials each correctly. api_key
    inherits the resolved MAIN endpoint's value. Returns ``None`` when neither
    stt nor tts is armed on the gateway.
    """
    stt_role = getattr(roles, "stt", None)
    tts_role = getattr(roles, "tts", None)
    stt_model = (str(getattr(stt_role, "model", "") or "").strip()) or None
    tts_model = (str(getattr(tts_role, "model", "") or "").strip()) or None

    if stt_model is None and tts_model is None:
        return None

    stt_base_url = (
        _role_dial_base_url(stt_role, gateway_url)
        if stt_role is not None
        else _lobes_base_url(gateway_url)
    )
    tts_base_url = (
        _role_dial_base_url(tts_role, gateway_url)
        if tts_role is not None
        else _lobes_base_url(gateway_url)
    )

    return VoiceConfig(
        stt_model=stt_model,
        tts_model=tts_model,
        stt_base_url=stt_base_url,
        tts_base_url=tts_base_url,
        api_key=api_key,
    )


def _seat_refusal(message: str, remediation: str) -> "CliError":
    """Build a loud seat-resolution refusal, lazily importing
    :class:`~colleague.cli._errors.CliError` (the same lazy-import stance
    :func:`_resolve_lobes_rung` takes for ``colleague.lobes`` — keeps
    ``config``'s module-level import graph unchanged).

    Every other lobes-fed rung (deepthink/senses/voice/realtime) degrades to
    ``None`` on any resolution failure. These are the exceptions: an
    EXPLICITLY armed execution mode makes its seats MANDATORY — three-tier's
    worker (:func:`_resolve_worker`, c25/h21) and the thought→action→evaluation
    mode's front/worker/evaluator (:func:`_resolve_evaluation_seats`, h19).
    """
    from colleague.cli._errors import EXIT_USER_ERROR, CliError

    return CliError(EXIT_USER_ERROR, message, remediation)


def _worker_refusal(message: str, remediation: str) -> "CliError":
    """The three-tier worker refusal (c25/h21) — see :func:`_seat_refusal`."""
    return _seat_refusal(message, remediation)


def _defaults_source(file_value: str | None, lobes_value: str | None, builtin: str) -> str:
    """First non-None of the two DEFAULTS-SOURCE rungs, else *builtin*.

    config.json outranks the lobes discovery rung; both sit BELOW the explicit
    flag/env precedence :func:`_pick` applies on top. Written as statements
    rather than a nested ternary (SonarCloud S3358) and shared by the base_url
    and model resolutions so the two rungs cannot drift apart.
    """
    if file_value is not None:
        return file_value
    if lobes_value is not None:
        return lobes_value
    return builtin


def _emit_lobes_unreachable_notice(gateway_url: str) -> None:
    """Emit ONE stderr notice that an armed lobes gateway was unreachable.

    Fires at most once per :meth:`EngineConfig.resolve` call (not once per field)
    — resolution proceeds on the next precedence rung, never hard-fails (h7).
    """
    print(
        f"colleague: lobes gateway {gateway_url!r} unreachable — proceeding on "
        "the next config precedence rung (config.json / builtin default)",
        file=sys.stderr,
    )


def _resolve_lobes_rung(
    repo_path: str | Path | None,
    discover_lobes: bool,
) -> "tuple[str | None, str | None, object | None, str | None, dict[str, str]]":
    """Consult the lobes gateway (task t4) and return its DEFAULTS-SOURCE bundle.

    Extracted from :meth:`EngineConfig.resolve` to hold its cognitive
    complexity under the SonarCloud S3776 ceiling (15) — pure extraction, no
    behavior change.

    When armed (``COLLEAGUE_LOBES_URL`` env or a ``lobes`` section in
    config.json), the gateway is consulted ONCE as a DEFAULTS SOURCE feeding
    cortex → the main model id + base_url, senses → a SensesConfig, voice →
    a VoiceConfig, and the embedder → ``embed_env`` overrides (S2, task t19).
    Unreachable degrades to the next precedence rung with ONE stderr notice
    (never a hard-fail, h7); unarmed (``discover_lobes=False``, or no gateway
    URL resolved) makes NO network call and returns an all-``None``/``{}``
    bundle — byte-identical to a pre-lobes resolve. ``discover_lobes=False`` is
    the OFFLINE seam the contractually no-network ``doctor`` provider group
    needs so an armed lobes gateway doesn't leak a network call into a plain
    ``colleague doctor``; the default (``True``) still discovers live per run.

    **Per-role dialing (colleague#292, S1's follow-on — closes lobes-cli#87
    end-to-end).** ``lobes_base_url`` is CORTEX's own resolved dial target
    (:func:`_role_dial_base_url`), not a blanket gateway-origin value — senses
    and voice each resolve their OWN dial target independently from the
    returned ``lobes_gateway_url``, below. The pre-0.38 "every role dials the
    gateway origin" workaround is gone; the gateway origin survives only as
    :func:`~colleague.lobes.resolve_role_base_url`'s documented per-role
    fallback for an unwired role or a disallowed scheme.

    Returns
    -------
    (lobes_base_url, lobes_model, lobes_roles, lobes_gateway_url, lobes_embed_env)
        ``lobes_base_url``/``lobes_model`` are the two values ``resolve()``
        folds into its own base_url/model defaults; ``lobes_roles`` is the
        raw resolved :class:`~colleague.lobes.LobesRoles` (or ``None``) the
        senses/voice rungs also consult; ``lobes_gateway_url`` is the armed
        gateway origin itself (needed by the senses/voice per-role resolution
        below, and as the documented fallback); ``lobes_embed_env`` is the
        embedder's env-var overrides (``{}`` when unarmed/unreachable/no
        embedder — see :func:`colleague.lobes.embed_env`).
    """
    if not discover_lobes:
        return None, None, None, None, {}
    lobes_gateway_url = resolve_lobes_gateway_url(repo_path)
    if lobes_gateway_url is None:
        return None, None, None, None, {}
    # Lazy import keeps config's module import graph unchanged (the
    # sanitize_model idiom) and lets tests monkeypatch resolve_roles.
    from colleague import lobes as _lobes

    lobes_roles = _lobes.resolve_roles(lobes_gateway_url)
    if lobes_roles is None:
        _emit_lobes_unreachable_notice(lobes_gateway_url)
        return None, None, None, None, {}
    # Per-role dialing (S1's follow-on, S2): cortex dials ITS OWN endpoint,
    # falling back to the gateway origin only when unwired/disallowed.
    lobes_base_url = _role_dial_base_url(lobes_roles.cortex, lobes_gateway_url)
    lobes_model = (lobes_roles.cortex.model or "").strip() or None
    lobes_embed_env = _lobes.embed_env(lobes_roles, lobes_gateway_url)
    return lobes_base_url, lobes_model, lobes_roles, lobes_gateway_url, lobes_embed_env

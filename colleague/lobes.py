"""Role-resolution client for the lobes gateway (cortex/senses arc, task t1;
re-synced to the lobes-cli 0.38.0 contract by colleague#292/291 S1).

Colleague drives with two minds served behind one gateway: a **cortex** (the
fast, wide-window reasoner that drives the tool loop) and **senses** (a
tools-off front door — intake, normalization, intent classification). The
gateway also serves four more roles today (``embedder``, ``reranker``,
``stt``, ``tts``); colleague resolves ``cortex`` + ``senses`` (mandatory) and
``stt``/``tts`` (optional, voice-arc consumers) and ignores ``embedder``/
``reranker`` (future follow-up territory, #276/#277).

:func:`resolve_roles` is a plain ``urllib`` GET of ``{gateway_url}/capabilities``.
The ``lobes`` CLI itself shipped ``lobes capabilities`` / ``lobes endpoint
<role>`` verbs in 0.36.0 (colleague never shells out to lobes-cli — no
subprocess dependency added here; this module hand-rolls its own stdlib GET
against the same live HTTP surface those verbs also read). It degrades to
``None`` on ANY failure — unreachable gateway, connect/read timeout, a
non-200 status, malformed/invalid JSON, or a missing expected role/field —
and **never raises**. There is no disk cache: every call re-resolves against
the live gateway (v1 decision — the gateway is cheap to ask and roles can
flip ``ready``/``loaded`` between calls).

Drift resilience: the served ``/capabilities`` shape is a superset of what
colleague needs (``role, model, runtime, endpoint, path, context, quant, mtp,
responsibilities, forbidden_responsibilities, ready, loaded`` per role — see
the live-probe findings this module was built from). All parsing lives in
:func:`_parse_role`, the one place a future shape drift gets fixed. Colleague
hardcodes no model id here — every id comes from the gateway's response.

**Per-role dial target (lobes-cli#87, closed in 0.38.0).** Before 0.38, a
role's own ``endpoint`` field reported an internal, non-client-reachable host
(the arc's original "gateway-origin-for-all" workaround, still applied by
``colleague/config.py``'s ``EngineConfig`` resolution — see that module's
docstrings). Since 0.38.0 each role's ``endpoint`` is a client-reachable
origin (Host-derived, overridable via the gateway's ``GATEWAY_PUBLIC_URL``),
so :func:`resolve_role_base_url` now dials it directly when non-empty,
falling back to the gateway origin only when ``endpoint`` is empty/missing
(an unwired role) or carries a scheme outside the same ``http``/``https``
guard :func:`resolve_roles` applies to the gateway URL itself. **Scope note:**
this module provides the resolution primitive; whether
``colleague/config.py``'s ``EngineConfig`` resolution consumes it for the
actual cortex/senses/stt/tts dial (replacing its own gateway-origin default)
is a separate, later integration step — not part of this change.

**``ready`` semantics differ by role (lobes-cli#89, closed in 0.38.0).** For
``cortex``/``senses``/``embedder``/``reranker``, the gateway's ``ready`` is a
CONFIG PROXY: ``ready == loaded`` (the model is loaded into the serving
process), never an actual per-request liveness probe. For ``stt``/``tts``,
0.38.0 made ``ready`` LIVE-PROBE-BACKED via the realtime bridge's own health
check — a warming audio backend now answers HTTP 503 with a ``Retry-After``
header instead of a bare 502 (see ``colleague/voice.py``'s bounded warming
retry). :func:`ready_kind` classifies which is which so a caller never
conflates a config proxy with real liveness.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

#: The one endpoint this module ever calls.
_CAPABILITIES_PATH = "/capabilities"

#: Bound a stalled gateway so a caller never hangs indefinitely on a dead rig.
_DEFAULT_TIMEOUT = 5.0

#: The only gateway URL schemes :func:`resolve_roles` will dial. Rejects
#: ``file://`` / ``ftp://`` / any other scheme BEFORE ``urlopen`` is ever
#: reached (Qodo #5, cortex/senses PR #281) — an operator-declared
#: ``COLLEAGUE_LOBES_URL`` / config.json ``lobes`` value with an unexpected
#: scheme degrades to ``None`` (the same degrade-to-None contract as an
#: unreachable gateway) rather than risking a local-file-read / SSRF-shaped
#: request.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

#: The roles colleague resolves. The gateway may serve more (embedder,
#: reranker, stt, tts as of the 2026-07-03 live probe) — those are read and
#: discarded, never an error.
_RESOLVED_ROLES = ("cortex", "senses")

#: Roles whose ``ready`` is LIVE-PROBE-BACKED (lobes-cli#89, 0.38.0) — the
#: gateway's realtime bridge health-checks the audio backend itself. Every
#: other role's ``ready`` is a CONFIG PROXY (``ready == loaded``): see
#: :func:`ready_kind`.
_LIVE_PROBED_READY_ROLES = frozenset({"stt", "tts"})


@dataclass(frozen=True)
class RoleInfo:
    """One resolved lobes role's served metadata.

    A superset of the wire payload's per-role dict is served (``role``,
    ``runtime``, ``quant``, ``mtp``, ``loaded`` are on the wire too); this
    captures the fields colleague's cortex/senses arc actually needs. Add a
    field here (and to :func:`_parse_role`) if a later task needs more of the
    wire shape — this is the single point a future drift gets fixed.
    """

    model: str
    endpoint: str
    path: str
    context: int
    ready: bool
    responsibilities: tuple[str, ...]
    forbidden_responsibilities: tuple[str, ...]


@dataclass(frozen=True)
class LobesRoles:
    """The cortex + senses metadata resolved from one gateway ``/capabilities`` call.

    ``stt`` and ``tts`` are OPTIONAL voice roles: their absence or malformed
    shape leaves them ``None`` but does NOT cause :func:`resolve_roles` to
    return ``None`` (unlike cortex/senses which are mandatory).
    """

    cortex: RoleInfo
    senses: RoleInfo
    stt: RoleInfo | None = None
    tts: RoleInfo | None = None


def _parse_role(raw: object) -> RoleInfo | None:
    """Parse one role's wire dict into a :class:`RoleInfo`, or ``None`` on any mismatch.

    Tolerant of extra keys (the wire shape is a superset); strict about the
    keys/types colleague actually reads. Never raises — any KeyError/TypeError
    from a malformed role dict is caught and turned into ``None``.
    """
    if not isinstance(raw, dict):
        return None
    try:
        model = raw["model"]
        endpoint = raw["endpoint"]
        path = raw["path"]
        context = raw["context"]
        ready = raw["ready"]
        responsibilities = raw["responsibilities"]
        forbidden = raw["forbidden_responsibilities"]

        if not isinstance(model, str) or not model:
            return None
        if not isinstance(endpoint, str) or not isinstance(path, str):
            return None
        if not isinstance(context, int) or isinstance(context, bool):
            return None
        if not isinstance(ready, bool):
            return None
        if not isinstance(responsibilities, list) or not all(
            isinstance(item, str) for item in responsibilities
        ):
            return None
        if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
            return None

        return RoleInfo(
            model=model,
            endpoint=endpoint,
            path=path,
            context=context,
            ready=ready,
            responsibilities=tuple(responsibilities),
            forbidden_responsibilities=tuple(forbidden),
        )
    except (KeyError, TypeError):
        return None


def resolve_roles(gateway_url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> LobesRoles | None:
    """Resolve cortex + senses metadata from the lobes gateway.

    Validates *gateway_url*'s scheme is ``http``/``https`` BEFORE ever calling
    ``urlopen`` (Qodo #5, cortex/senses PR #281) — a ``file://``/``ftp://``/
    other-scheme URL degrades to ``None`` immediately, never dialed.

    GETs ``{gateway_url}/capabilities`` (stdlib ``urllib``) and parses the
    JSON body. Degrades to ``None`` on ANY failure: an unsupported scheme, an
    unreachable gateway, connect/read timeout, a non-200 status,
    malformed/invalid JSON, a non-dict top-level body, or either the
    ``cortex`` or ``senses`` role being absent/malformed. **Never raises.**

    Re-resolves on every call — there is no disk cache (v1 decision: roles
    can flip ``ready``/``loaded`` between calls, and the gateway is cheap to
    ask).
    """
    if urlsplit(gateway_url).scheme not in _ALLOWED_SCHEMES:
        return None
    try:
        url = gateway_url.rstrip("/") + _CAPABILITIES_PATH
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(  # nosec B310 - scheme validated above
            request, timeout=timeout
        ) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                return None
            raw_body = response.read()
        payload = json.loads(raw_body.decode("utf-8"))
    # Degrade-to-None is the whole contract of this function: any failure
    # (network, JSON, shape) here folds into the caller's None-check.
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(payload, dict):
        return None

    resolved: dict[str, RoleInfo] = {}
    for name in _RESOLVED_ROLES:
        role = _parse_role(payload.get(name))
        if role is None:
            return None
        resolved[name] = role

    # Voice roles (stt/tts) are OPTIONAL: parse them but never fail resolution.
    stt_role = _parse_role(payload.get("stt"))
    tts_role = _parse_role(payload.get("tts"))

    return LobesRoles(
        cortex=resolved["cortex"],
        senses=resolved["senses"],
        stt=stt_role,
        tts=tts_role,
    )


def resolve_role_base_url(role: RoleInfo, gateway_url: str) -> str:
    """Resolve the client-reachable dial target for *role* (lobes-cli#87, 0.38.0).

    Dials *role*'s own ``endpoint`` directly when it is a non-empty
    ``http``/``https`` URL — the fixed pre-0.38 gap (an internal,
    non-reachable host) that 0.38.0 closed by making ``endpoint``
    Host-derived and genuinely dialable. Falls back to *gateway_url* (the
    gateway origin used to serve ``/capabilities``) when ``endpoint`` is
    empty/missing (an unwired role) or carries a scheme outside
    :data:`_ALLOWED_SCHEMES` — the same SSRF guard :func:`resolve_roles`
    applies to the gateway URL itself. Never raises; a malformed/disallowed
    endpoint degrades to the documented fallback, not an exception.
    """
    endpoint = (role.endpoint or "").strip()
    if endpoint and urlsplit(endpoint).scheme in _ALLOWED_SCHEMES:
        return endpoint
    return gateway_url


def ready_kind(role_name: str) -> str:
    """Classify *role_name*'s ``ready`` semantics (lobes-cli#89, 0.38.0).

    Returns ``"live-probed"`` for ``stt``/``tts`` — the gateway's realtime
    bridge health-checks the audio backend itself, so ``ready`` reflects
    actual reachability (a warming backend answers 503 + ``Retry-After``
    instead, see ``colleague/voice.py``). Returns ``"config-proxy"`` for every
    other role (``cortex``, ``senses``, ``embedder``, ``reranker``, or any
    future/unknown name): ``ready == loaded``, true once the model is loaded
    into the serving process — never an actual per-request liveness probe.
    Never conflate the two when surfacing ``ready`` to an operator.
    """
    return "live-probed" if role_name in _LIVE_PROBED_READY_ROLES else "config-proxy"

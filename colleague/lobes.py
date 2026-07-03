"""Role-resolution client for the lobes gateway (cortex/senses arc, task t1).

Colleague drives with two minds served behind one gateway: a **cortex** (the
fast, wide-window reasoner that drives the tool loop) and **senses** (a
tools-off front door — intake, normalization, intent classification). The
gateway also serves four more roles today (``embedder``, ``reranker``,
``stt``, ``tts``) that are future follow-up territory (#276/#277); colleague
resolves only ``cortex`` + ``senses`` and ignores the rest.

:func:`resolve_roles` is a plain ``urllib`` GET of ``{gateway_url}/capabilities``
— the gateway's one live surface today (the ``lobes`` CLI ships no
``capabilities`` verb yet, lobes-cli#81). It degrades to ``None`` on ANY
failure — unreachable gateway, connect/read timeout, a non-200 status,
malformed/invalid JSON, or a missing expected role/field — and **never
raises**. There is no disk cache: every call re-resolves against the live
gateway (v1 decision — the gateway is cheap to ask and roles can flip
``ready``/``loaded`` between calls).

Drift resilience: the served ``/capabilities`` shape is a superset of what
colleague needs (``role, model, runtime, endpoint, path, context, quant, mtp,
responsibilities, forbidden_responsibilities, ready, loaded`` per role — see
the live-probe findings this module was built from). All parsing lives in
:func:`_parse_role`, the one place a future shape drift gets fixed. Colleague
hardcodes no model id here — every id comes from the gateway's response.

Honest limit (decision, see the cortex/senses spec): each role's own
``endpoint``/``path`` fields are reported here **faithfully**, exactly as
served, but are informational metadata only — a later task (config
resolution) decides the actual dial-string (the gateway origin routes by
model id; a role's self-reported ``endpoint`` is not reachable directly).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

#: The one endpoint this module ever calls.
_CAPABILITIES_PATH = "/capabilities"

#: Bound a stalled gateway so a caller never hangs indefinitely on a dead rig.
_DEFAULT_TIMEOUT = 5.0

#: The roles colleague resolves. The gateway may serve more (embedder,
#: reranker, stt, tts as of the 2026-07-03 live probe) — those are read and
#: discarded, never an error.
_RESOLVED_ROLES = ("cortex", "senses")


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
    """The cortex + senses metadata resolved from one gateway ``/capabilities`` call."""

    cortex: RoleInfo
    senses: RoleInfo


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

    GETs ``{gateway_url}/capabilities`` (stdlib ``urllib``) and parses the
    JSON body. Degrades to ``None`` on ANY failure: unreachable gateway,
    connect/read timeout, a non-200 status, malformed/invalid JSON, a
    non-dict top-level body, or either the ``cortex`` or ``senses`` role
    being absent/malformed. **Never raises.**

    Re-resolves on every call — there is no disk cache (v1 decision: roles
    can flip ``ready``/``loaded`` between calls, and the gateway is cheap to
    ask).
    """
    try:
        url = gateway_url.rstrip("/") + _CAPABILITIES_PATH
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            status = getattr(response, "status", 200)
            if status != 200:
                return None
            raw_body = response.read()
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:  # noqa: BLE001 - degrade-to-None is the whole contract, never raise
        return None

    if not isinstance(payload, dict):
        return None

    resolved: dict[str, RoleInfo] = {}
    for name in _RESOLVED_ROLES:
        role = _parse_role(payload.get(name))
        if role is None:
            return None
        resolved[name] = role

    return LobesRoles(cortex=resolved["cortex"], senses=resolved["senses"])

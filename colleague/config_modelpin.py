"""Resolution-time stale-model-pin refresh (same-role lookup against lobes).

A pinned model id that the armed gateway no longer serves is refreshed ONCE,
at resolution time, to the model the same lobes ROLE now advertises — and the
substitution is recorded as a loud warning, never applied silently. Split out
of ``config.py`` (hard 1000-line file limit, plan ``hard-1000-line-file-limit``
t14) — a pure move. Every name is re-exported from :mod:`colleague.config`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from colleague.config_defaults import _DEFAULT_API_KEY

if TYPE_CHECKING:
    from colleague.lobes import ModelRefreshWarning


def _model_pin_source(model_arg: str | None, file_model: str | None) -> str | None:
    """Name which layer PINNED the main model id, or ``None`` when it came from
    lobes role discovery / the builtin default — i.e. it was never a pin at all
    (same-role stale-pin refresh, plan task t9, honesty h7).

    Mirrors ``_pick(model, "COLLEAGUE_MODEL", "CONVERTIBLE_MODEL",
    default=model_default)``'s OWN precedence exactly — flag > COLLEAGUE_MODEL
    env > CONVERTIBLE_MODEL env (the convertible->colleague rename back-compat
    fallback) > config.json — so a refresh warning's ``source`` is never wrong
    about which layer actually won. Reads NOTHING beyond these four inputs:
    no ``Task``/instruction parameter exists on this function or on
    :meth:`EngineConfig.resolve` at all, which is the structural half of h7's
    "model resolution inputs are exactly {flag, env, config.json, lobes role
    discovery} — no code path reads task content to pick a model."
    """
    if model_arg is not None:
        return "flag"
    if os.environ.get("COLLEAGUE_MODEL"):
        return "COLLEAGUE_MODEL"
    if os.environ.get("CONVERTIBLE_MODEL"):
        return "CONVERTIBLE_MODEL"
    if file_model is not None:
        return "config.json"
    return None


def _resolution_time_refresh(
    resolved_model: str,
    model_arg: str | None,
    file_model: str | None,
    lobes_gateway_url: str | None,
    lobes_roles: object,
    resolved_api_key: str,
    *,
    three_tier_armed: bool,
) -> "tuple[str, ModelRefreshWarning | None]":
    """The resolution-time stale-pin refresh rung, gate included (S3776
    extraction from ``resolve()``; plan task t9, spec c10/c11, h7/h8).

    Skipped entirely when three-tier is armed: the worker, not cortex, is
    the ACTING seat there, so a cortex pin refresh would be inert work
    against a role that never drives — never a network call this rung has
    no use for. The wire-format placeholder key is NOT a credential:
    sending "Bearer EMPTY" can turn an otherwise-OK anonymous /v1/models
    fetch into a 401 on a strict gateway and silently skip this rung
    (Qodo review, PR #381) — the placeholder translates to no header.
    """
    if three_tier_armed:
        return resolved_model, None
    return _refresh_stale_model_pin(
        resolved_model,
        model_arg,
        file_model,
        lobes_gateway_url,
        lobes_roles,
        api_key=("" if resolved_api_key == _DEFAULT_API_KEY else resolved_api_key),
    )


def _refresh_stale_model_pin(
    resolved_model: str,
    model_arg: str | None,
    file_model: str | None,
    lobes_gateway_url: str | None,
    lobes_roles: object,
    api_key: str = "",
) -> "tuple[str, ModelRefreshWarning | None]":
    """Same-role stale-pin refresh AT RESOLUTION TIME (plan task t9, spec
    c10/c11, honesty h7/h8): a main-model id pinned via flag/env/config.json
    that the lobes gateway's successfully-fetched ``/v1/models`` roster no
    longer carries is STALE CONFIG, not a reason to die — substitute
    CORTEX's own currently-discovered id (cortex is the role the MAIN model
    resolves from in the legacy/two-tier path this rung covers — see
    :class:`WorkerConfig`'s docstring: the three-tier worker seat has
    deliberately NO declared-pin rung of its own, so it can never go stale
    this way; a stale WORKER id is a ``/capabilities``-vs-actually-served
    advert mismatch instead, ``colleague/oilcheck/three_tier.py``'s
    territory, not a pin refresh) and record a warning naming the stale id,
    its source layer, and the refreshed id. This is a REFRESH, never a
    fallback/routing decision: the target role never changes, only its
    served id.

    Fires ONLY when ALL of:

    - the pin has a NAMEABLE source (:func:`_model_pin_source` returns
      non-``None``) — a value that already came from lobes discovery itself,
      or the builtin default with no pin at all, is already the freshest
      available id and needs no check (acceptance 2: unpinned resolves
      byte-identically, there is nothing to warn about);
    - lobes is armed AND reachable (*lobes_gateway_url*/*lobes_roles* both
      non-``None``) — unarmed/unreachable leaves the pin untouched (h8);
    - the gateway's ``/v1/models`` membership check actually RUNS
      (:func:`colleague.lobes.fetch_served_model_ids` returns non-``None`` —
      a fetch failure, including a bare 401, means NO refresh, per the
      spec's explicit "a membership check that cannot run means no refresh"
      rule — distinct from a successfully-fetched EMPTY list, which is a
      valid "nothing served" membership result);
    - the pinned id is absent from that fetched list (acceptance 2: a VALID
      pin — present in the list — resolves byte-identically, untouched);
    - cortex's OWN discovered id (from the SAME ``/capabilities`` call
      *lobes_roles* already carries — never a second network round trip) is
      present/non-blank (acceptance 2: "the role advertising no model" also
      leaves the original value in place).

    Returns ``(resolved_model, warning)`` — *resolved_model* is the
    refreshed id when a refresh fired, else *resolved_model* unchanged;
    *warning* is the structured :class:`~colleague.lobes.ModelRefreshWarning`
    (already emitted to stderr via
    :func:`colleague.lobes.emit_model_refresh_warning`), or ``None``.
    """
    pin_source = _model_pin_source(model_arg, file_model)
    if pin_source is None or lobes_gateway_url is None or lobes_roles is None:
        return resolved_model, None
    # Lazy import mirrors every other lobes-consulting helper in this module
    # (keeps config's module-level import graph unchanged; lets tests
    # monkeypatch it).
    from colleague import lobes as _lobes

    served_ids = _lobes.fetch_served_model_ids(lobes_gateway_url, api_key=api_key)
    if served_ids is None or resolved_model in served_ids:
        return resolved_model, None
    cortex_model = (getattr(lobes_roles.cortex, "model", "") or "").strip()
    if not cortex_model:
        return resolved_model, None
    warning = _lobes.ModelRefreshWarning(
        role="cortex",
        stale_id=resolved_model,
        source=pin_source,
        refreshed_id=cortex_model,
        point="resolution",
    )
    _lobes.emit_model_refresh_warning(warning)
    return cortex_model, warning

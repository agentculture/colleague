"""Associate-seat configuration — the fast, tool-capable NON-coding mind (t18).

adopt-from-qwen-code arc (spec docs/specs/2026-08-27-adopt-from-qwen-code.md,
claims c37/h26, c49/h36; plan task t18). Split out of :mod:`colleague.config`
so that module stays under its file-length ratchet: the dataclass, the
defaults, the config.json section loader, the env/config resolver and the
lobes discovery fallback all live here; ``config.py`` only wires them into
``EngineConfig.resolve`` (the way deepthink/senses are wired inline there).

The seat builder that turns an :class:`AssociateConfig` into an
:class:`~colleague.config.EngineConfig` is :mod:`colleague.associate`.

Import direction: ``config`` imports THIS module at load time (for the
dataclass type and the wiring functions); this module imports ``config``
LAZILY inside functions for the shared helpers (``_pick``, ``_try_int``,
``_merged_config_json``, ``_role_dial_base_url``, ``_same_origin``,
``_DEFAULT_API_KEY``) — never at module load.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ASSOCIATE_WIRE_MODEL",
    "AssociateConfig",
    "associate_from_lobes_role",
    "associate_lobes_fallback",
    "load_associate_overrides",
    "resolve_associate",
]

# Associate seat defaults (adopt-from-qwen-code t18, spec c37/c49). The role's
# advertised window on the Orin is 128000 (the proxied advert over-claims
# 1048576 — c38: the LIVE window discovery is the clamp's authority, this
# budget is only the seat's windowing headroom, at the deepthink ratio).
_DEFAULT_ASSOCIATE_CONTEXT_BUDGET = 96000
_ASSOCIATE_DEFAULT_WINDOW = 131072
#: The ROLE NAME the associate seat sends as ``model`` on the wire. Probed
#: 2026-08-27: spark's gateway completes ``{"model": "associate"}`` through the
#: Orin proxy but refuses the raw served id (it maps to the hardware-infeasible
#: local ``worker`` backend, ``role_infeasible``) — so the seat is addressed by
#: role name and the SERVED model is read back from the reply (c49/h36).
ASSOCIATE_WIRE_MODEL = "associate"

# Recognised keys inside the NESTED "associate" section of .colleague/config.json (t18).
_ASSOCIATE_CONFIG_KEYS = frozenset({"model", "base_url", "api_key", "context_budget"})


@dataclass(frozen=True)
class AssociateConfig:
    """A resolved associate seat — the fast, tool-capable NON-coding mind (t18).

    Optional: present on :attr:`EngineConfig.associate` only when the operator
    declared one (``COLLEAGUE_ASSOCIATE_MODEL`` / config.json ``associate``
    section — the sentinel ``lobes`` asks for the gateway's advertised
    ``associate`` role). Same OpenAI surface, same ``vllm-openai`` adapter, so
    retargeting stays a config change.

    ``model`` is the SERVED model id (the advert's, or the declared id);
    ``wire_model`` is what the seat sends as ``model`` — the role name
    (:data:`ASSOCIATE_WIRE_MODEL`) for a lobes-discovered seat, since the
    gateway routes the proxied role by name and refuses the raw id; the id
    itself for an explicitly declared model.
    """

    model: str
    base_url: str
    api_key: str
    context_budget: int
    wire_model: str = ASSOCIATE_WIRE_MODEL

    @property
    def addressed_as_role(self) -> bool:
        """True when the seat dials the gateway by role name (proxied)."""
        return self.wire_model != self.model


def _associate_budget_from_window(window: int) -> int:
    """An associate context_budget derived from a role's reported window (t18).

    The deepthink/senses headroom ratio (:data:`_DEFAULT_ASSOCIATE_CONTEXT_BUDGET`
    / :data:`_ASSOCIATE_DEFAULT_WINDOW`), floored at 1; a non-positive window
    falls back to the default. The proxied advert may over-claim the window
    (probed: 1048576 vs the Orin's own 128000) — this is only the seat's
    windowing headroom; the live window discovery (spec c38) owns the clamp.
    """
    if window <= 0:
        return _DEFAULT_ASSOCIATE_CONTEXT_BUDGET
    ratio = _DEFAULT_ASSOCIATE_CONTEXT_BUDGET / _ASSOCIATE_DEFAULT_WINDOW
    return max(1, int(window * ratio))


def associate_from_lobes_role(
    role: object, base_url: str, api_key: str
) -> "AssociateConfig | None":
    """Build an :class:`AssociateConfig` from the gateway's ``associate`` role (t18).

    Resolution only — the qwen-direct opt-in rung (reached solely via the
    ``lobes`` sentinel). The advertised model id is recorded as the SERVED
    model; the wire model is the ROLE NAME (:data:`ASSOCIATE_WIRE_MODEL`),
    because the gateway routes the proxied role by name and refuses the raw
    id (``role_infeasible``, probed 2026-08-27). ``ready``/``loaded`` are NOT
    consulted — for a proxied role they describe the gateway host, not the
    serving host (lobes-cli#146; the muse rung's stance). ``None`` on a blank
    model.
    """
    model = str(getattr(role, "model", "") or "").strip()
    if not model:
        return None
    return AssociateConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget=_associate_budget_from_window(int(getattr(role, "context", 0) or 0)),
        wire_model=ASSOCIATE_WIRE_MODEL,
    )


def associate_lobes_fallback(
    lobes_roles: object,
    lobes_gateway_url: str | None,
    main_base_url: str,
    main_api_key: str,
    file_associate: dict[str, str],
) -> "AssociateConfig | None":
    """The associate discovery fallback (t18) — OPT-IN ONLY, like muse/senses.

    Reached solely when the declared associate model is the sentinel
    ``lobes``; an advertised role alone arms nothing (the v1.63 line: a bare
    run dials ONE model). Mirrors :func:`colleague.config._deepthink_lobes_fallback`
    field-for-field, including the api_key hygiene: an explicit
    ``COLLEAGUE_ASSOCIATE_API_KEY`` / config.json key wins; otherwise the
    MAIN key is inherited only when the role's dial target shares the main
    endpoint's origin, else :data:`colleague.config._DEFAULT_API_KEY`.
    """
    from colleague import config as _cfg  # lazy: config imports this module

    role = getattr(lobes_roles, "associate", None) if lobes_roles is not None else None
    if role is None or lobes_gateway_url is None:
        return None
    associate_base_url = _cfg._role_dial_base_url(role, lobes_gateway_url)
    explicit_key = _cfg._pick(
        None,
        "COLLEAGUE_ASSOCIATE_API_KEY",
        default=file_associate.get("api_key", ""),
    )
    if explicit_key:
        api_key = explicit_key
    elif _cfg._same_origin(associate_base_url, main_base_url):
        api_key = main_api_key
    else:
        api_key = _cfg._DEFAULT_API_KEY
    return associate_from_lobes_role(role, associate_base_url, api_key)


def resolve_associate(
    file_associate: dict[str, str],
    main_base_url: str,
    main_api_key: str,
) -> "AssociateConfig | None":
    """Resolve the optional associate (fast non-coding) seat declaration (t18).

    Precedence per key: ``COLLEAGUE_ASSOCIATE_*`` env > the ``associate``
    section of .colleague/config.json > a default (base_url/api_key default to
    the resolved MAIN endpoint values, like deepthink). Present iff the
    resolved model is non-blank; the sentinel ``lobes`` is carried through
    for :func:`associate_lobes_fallback` to replace. An explicit model id is
    addressed on the wire BY THAT ID (``wire_model == model``); only the
    lobes-discovered seat is addressed by role name.
    """
    from colleague import config as _cfg  # lazy: config imports this module

    model = _cfg._pick(
        None,
        "COLLEAGUE_ASSOCIATE_MODEL",
        default=file_associate.get("model", ""),
    )
    if not model.strip():
        return None
    base_url = _cfg._pick(
        None,
        "COLLEAGUE_ASSOCIATE_BASE_URL",
        default=file_associate.get("base_url") or main_base_url,
    )
    api_key = _cfg._pick(
        None,
        "COLLEAGUE_ASSOCIATE_API_KEY",
        default=file_associate.get("api_key") or main_api_key,
    )
    context_budget = _cfg._try_int(
        _cfg._pick(
            None,
            "COLLEAGUE_ASSOCIATE_CONTEXT_BUDGET",
            default=file_associate.get("context_budget", ""),
        ),
        default=_DEFAULT_ASSOCIATE_CONTEXT_BUDGET,
    )
    model = model.strip()
    return AssociateConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        context_budget=context_budget,
        wire_model=model,
    )


def load_associate_overrides(repo_path: str | Path) -> dict[str, str]:
    """Read the NESTED ``associate`` section of .colleague/config.json (t18).

    Mirrors :func:`colleague.config._load_senses_overrides` key-for-key (minus ``multimodal`` —
    the associate seat is a text-only scout): returns stringified values for
    :data:`_ASSOCIATE_CONFIG_KEYS`; an absent/non-dict section yields ``{}``
    and never raises. Merge granularity is the top-level ``associate`` key.
    """
    from colleague import config as _cfg  # lazy: config imports this module

    data = _cfg._merged_config_json(repo_path)
    section = data.get("associate")
    if not isinstance(section, dict):
        return {}
    return {
        key: str(value)
        for key, value in section.items()
        if key in _ASSOCIATE_CONFIG_KEYS and value is not None
    }

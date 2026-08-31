"""The mode-profile default layer (spec R1 / issue #254).

Each mode carries its own compute/context profile; :func:`apply_mode_profile`
fills ONLY the knobs the operator did not already decide (env var present, or
an explicit flag recorded in ``explicit_knobs``). Split out of ``config.py``
(hard 1000-line file limit, plan ``hard-1000-line-file-limit`` t14) — a pure
move. Every name is re-exported from :mod:`colleague.config`.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Collection

from colleague import configdir

if TYPE_CHECKING:
    from colleague.config import EngineConfig

# presence means the operator already decided the knob (env > profile).
_PROFILE_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "max_steps": ("COLLEAGUE_MAX_STEPS", "CONVERTIBLE_MAX_STEPS"),
    "timeout": ("COLLEAGUE_TIMEOUT", "CONVERTIBLE_TIMEOUT"),
    "context_budget_tokens": (
        "COLLEAGUE_CONTEXT_BUDGET",
        "CONVERTIBLE_CONTEXT_BUDGET",
    ),
    "fillline_threshold": (
        "COLLEAGUE_FILLLINE_THRESHOLD",
        "CONVERTIBLE_FILLLINE_THRESHOLD",
    ),
    "synthesis_reserve_steps": (
        "COLLEAGUE_SYNTHESIS_RESERVE_STEPS",
        "CONVERTIBLE_SYNTHESIS_RESERVE_STEPS",
    ),
}

# Operator overlay file: .colleague/profiles.json (repo/user via configdir) and
# .colleague/<sanitize_model(model)>/profiles.json (exact-path, per-model-first
# — the hooks/approvals overlay convention).
_PROFILES_FILENAME = "profiles.json"


def _env_present(env_keys: tuple[str, ...]) -> bool:
    """True when any of the env vars is set non-empty (mirrors ``_pick``)."""
    return any(os.environ.get(key) for key in env_keys)


def _read_profiles_file(path: Path | None) -> dict[str, dict]:
    """Parse a profiles overlay file into ``{mode: {knob: value}}``.

    Missing file, malformed JSON, or a non-dict payload is a strict no-op
    (empty dict) — the malformed-config convention shared with hooks,
    approvals, and config.json. Non-dict mode entries are dropped.
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def _load_profile_overlays(
    repo_path: str | Path | None, model: str | None
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load ``(per_model_overlay, repo_overlay)`` profiles files.

    The per-model path is built by exact construction through
    :func:`colleague.layers.sanitize_model` — sibling ``.colleague/*/``
    directories are never globbed, so model X can never load model Y's
    overlay (honesty condition h7).
    """
    if repo_path is None:
        return {}, {}
    repo_overlay = _read_profiles_file(configdir.resolve_file(repo_path, _PROFILES_FILENAME))
    per_model: dict[str, dict] = {}
    if model:
        # Lazy: keeps config's module import graph unchanged (layers is the
        # sanctioned per-model sanitizer, same idiom as the hooks overlay).
        from colleague.layers import sanitize_model

        per_model = _read_profiles_file(
            configdir.resolve_file(repo_path, f"{sanitize_model(model)}/{_PROFILES_FILENAME}")
        )
    return per_model, repo_overlay


def _coerce_profile_int(value: object, *, minimum: int) -> int | None:
    """An int >= minimum, or None; bool is explicitly not an int here."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= minimum else None


def _coerce_profile_seconds(value: object) -> float | None:
    """A positive number of seconds as float, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    return seconds if seconds > 0 else None


def _coerce_unit_fraction(value: object) -> float | None:
    """A fraction in (0, 1], or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    fraction = float(value)
    return fraction if 0 < fraction <= 1 else None


def _profile_as_source(profile: object) -> dict[str, object]:
    """Adapt a ModeProfile-shaped object to the overlay-dict field interface."""
    return {
        "max_steps": getattr(profile, "max_steps", None),
        "context_budget_fraction": getattr(profile, "context_budget_fraction", None),
        "synthesis_reserve_steps": getattr(profile, "synthesis_reserve_steps", None),
        "timeout": getattr(profile, "timeout", None),
        "fillline_threshold": getattr(profile, "fillline_threshold", None),
    }


def _field_from_source(
    field_name: str, source: dict[str, object], base_budget_tokens: int
) -> object | None:
    """Extract + validate one knob from one source; None when absent/invalid.

    ``context_budget_tokens`` accepts either an absolute
    ``context_budget_tokens`` int or a ``context_budget_fraction`` in (0, 1]
    applied to the *resolved default* budget — the fraction composes with the
    per-model/default budget rather than competing with an operator override
    (an env/flag-set budget never reaches this code path at all).
    """
    if field_name == "context_budget_tokens":
        absolute = _coerce_profile_int(source.get("context_budget_tokens"), minimum=1)
        if absolute is not None:
            return absolute
        fraction = _coerce_unit_fraction(source.get("context_budget_fraction"))
        if fraction is not None:
            # Floor at 1: a tiny base budget must TIGHTEN, never truncate to 0
            # — a non-positive budget would disable the context-budget path
            # entirely, the opposite of what a profile fraction means (Qodo
            # PR #260 review).
            return max(1, int(base_budget_tokens * fraction))
        return None
    raw = source.get(field_name)
    if field_name == "max_steps":
        return _coerce_profile_int(raw, minimum=1)
    if field_name == "synthesis_reserve_steps":
        return _coerce_profile_int(raw, minimum=0)
    if field_name == "timeout":
        return _coerce_profile_seconds(raw)
    if field_name == "fillline_threshold":
        return _coerce_unit_fraction(raw)
    return None


def _resolve_builtin_profile(mode: str, resolve: Callable | None) -> object | None:
    """Look up the built-in catalog profile (the t1 module), or None."""
    if resolve is None:
        try:
            # Lazy: profiles.py is a leaf catalog module; importing it here
            # keeps config importable during partial checkouts/transitions.
            from colleague.profiles import resolve_profile as resolve
        except ImportError:  # pragma: no cover - transition guard
            return None
    return resolve(mode)


def _profile_updates(
    config: "EngineConfig",
    sources: list[dict[str, object]],
    explicit_fields: set[str],
) -> dict[str, object]:
    """The knob updates the profile sources yield for *config* (S3776 extract).

    Per knob: an explicit CLI flag or a set env var means the operator already
    decided it (skipped); otherwise the FIRST source (per-model overlay > repo
    overlay > built-in profile) that yields a valid value wins, and a value
    equal to the resolved one is dropped (no-op replace avoidance).
    """
    updates: dict[str, object] = {}
    for field_name, env_keys in _PROFILE_ENV_KEYS.items():
        if field_name in explicit_fields or _env_present(env_keys):
            continue
        for source in sources:
            value = _field_from_source(field_name, source, config.context_budget_tokens)
            if value is not None:
                if value != getattr(config, field_name):
                    updates[field_name] = value
                break
    return updates


def apply_mode_profile(
    config: "EngineConfig",
    mode: str | None,
    *,
    explicit: Collection[str] = (),
    repo_path: str | Path | None = None,
    resolve: Callable | None = None,
) -> "EngineConfig":
    """Fill mode-profile defaults for constraint knobs the operator left untouched.

    The R1 (#254) profile layer, applied AFTER :meth:`EngineConfig.resolve` so
    the full precedence per knob is::

        explicit flag > COLLEAGUE_*/CONVERTIBLE_* env > per-model overlay
        > repo overlay > built-in mode profile > resolved value untouched

    *explicit* names the EngineConfig fields the caller set from CLI flags
    (e.g. ``{"max_steps"}`` when ``--max-steps`` was given); a set env var is
    detected here directly (mirroring ``_pick``'s non-empty semantics). The
    knobs a profile may fill are exactly ``_PROFILE_ENV_KEYS``.

    Strict no-op guarantees (h1): returns *config* itself for a falsy or
    unknown mode, when no profile/overlay defines the mode, or when every
    knob is already operator-decided — so a run with no mode selected is
    byte-identical to today.
    """
    if not mode:
        return config
    profile = _resolve_builtin_profile(mode, resolve)
    per_model_overlay, repo_overlay = _load_profile_overlays(repo_path, config.model)
    sources: list[dict[str, object]] = [
        source
        for source in (per_model_overlay.get(mode), repo_overlay.get(mode))
        if isinstance(source, dict)
    ]
    if profile is not None:
        sources.append(_profile_as_source(profile))
    if not sources:
        return config
    updates = _profile_updates(config, sources, set(explicit))
    if not updates:
        return config
    return replace(config, **updates)

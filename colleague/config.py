"""Engine configuration: where the model lives and how hard the loop drives it.

Resolution precedence, highest first:

1. an explicit value passed in code / from a CLI flag,
2. a ``COLLEAGUE_*`` environment variable (the legacy ``CONVERTIBLE_*`` name is
   still honored as a deprecated fallback during the rename),
3. an OpenAI-style ``OPENAI_*`` environment variable (so an existing OpenAI
   client setup is reused),
4. the built-in default.

Defaults point at the vLLM reference rig (decision D3): an OpenAI-compatible
server on ``localhost:8001``. Because the driver only speaks the OpenAI surface,
pointing ``base_url`` elsewhere is a config change, never a code change (h2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

# vLLM ignores the key, but the OpenAI wire format wants a non-empty string.
_DEFAULT_API_KEY = "EMPTY"
_DEFAULT_BASE_URL = "http://localhost:8001/v1"
# Built-in fallback model id. Points at the model the reference rig actually
# serves at _DEFAULT_BASE_URL so a bare work item (no COLLEAGUE_MODEL / --model)
# reaches a live model instead of a 404 "model does not exist". Override per
# environment with COLLEAGUE_MODEL or --model.
_DEFAULT_MODEL = "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
_DEFAULT_MAX_STEPS = 40
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 120.0
# Proactive context budget in tokens. Counted exactly via the served model's
# /tokenize endpoint when reachable; char-based fallback otherwise (best-effort
# exact, char-approximate fallback, never token-exact-guaranteed — no tokenizer
# library is bundled). Sized for the 256k (262144-token) reference rig, leaving
# headroom for the completion + system/tools prompt. Override per environment
# with COLLEAGUE_CONTEXT_BUDGET (e.g. lower it for a small-context model).
_DEFAULT_CONTEXT_BUDGET = 192000
# Cap on each tool result (read_file / run_command / list_dir / subagent) fed
# back to the model, in characters. Raised from the old hardcoded 20000 to suit
# the 256k window so a large file read isn't truncated. Tunable per environment
# with COLLEAGUE_MAX_OUTPUT_CHARS.
_DEFAULT_MAX_OUTPUT_CHARS = 100000

# Opt-in concurrency width for subagent delegation (how many may run in
# parallel). Clamped to [1, MAX_SUBAGENT_FANOUT - 1] by effective_concurrency().
# Tunable per environment with COLLEAGUE_SUBAGENT_CONCURRENCY.
_DEFAULT_SUBAGENT_CONCURRENCY = 1

# Auto-split capacity target in tokens (issue #151). The operator-tunable
# "~1M effective capacity" knob: colleague recommends splitting a too-large
# assignment into children whose count is derived from this target divided by
# the per-child context budget, then structurally clamped to the subagent
# fan-out cap. Override with COLLEAGUE_AUTOSPLIT_TARGET.
_DEFAULT_AUTOSPLIT_TARGET_TOKENS = 1_000_000

# Fill-line decision threshold (issue #156): the fraction of the context budget at
# which the runtime offers the proactive capacity decision (compact | split |
# finish-with-handoff). 0.8 leaves headroom for the decision prompt + the model's
# declaring turn before a hard overflow. Override with COLLEAGUE_FILLLINE_THRESHOLD;
# 0 (or out of (0, 1]) leaves the proactive decision dormant — degradation + the
# reactive auto-split still apply.
_DEFAULT_FILLLINE_THRESHOLD = 0.8

# Engine SELECTION default (distinct from the provider config below — mock
# ignores provider config entirely). The default is the real bundled engine,
# never the no-op ``mock`` contract reference: a bare ``drive``/``session`` must
# not silently fake work (issue #53, "Mock shouldn't be default"). ``mock`` is
# reachable only by an explicit ``--engine mock`` / ``COLLEAGUE_ENGINE=mock``.
_DEFAULT_ENGINE = "vllm-openai"

# Subagent delegation bounds.
MAX_SUBAGENT_DEPTH = 2
MAX_SUBAGENT_FANOUT = 4


def _pick(explicit: str | None, *env_keys: str, default: str) -> str:
    if explicit is not None:
        return explicit
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def resolve_engine(explicit: str | None) -> str:
    """Resolve the backend plugin name to drive.

    Precedence, highest first: an explicit value (the ``--engine`` flag), the
    ``COLLEAGUE_ENGINE`` environment variable (legacy ``CONVERTIBLE_ENGINE`` is
    honored as a deprecated fallback), then the built-in default
    (:data:`_DEFAULT_ENGINE`). Engine selection is config too, so it mirrors the
    provider-field precedence — but it is a separate concern (the ``mock`` engine
    never reads provider config).

    An empty or whitespace-only candidate is treated as *absent*, not as a valid
    override: ``--engine ''`` (or ``--engine "$VAR"`` with ``VAR`` unset, or a
    blank ``COLLEAGUE_ENGINE``) falls through to the next source rather than
    resolving to an invalid engine name that would later raise ``UnknownEngine``.
    A non-blank value is returned stripped of surrounding whitespace.
    """
    for candidate in (
        explicit,
        os.environ.get("COLLEAGUE_ENGINE"),
        os.environ.get("CONVERTIBLE_ENGINE"),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return _DEFAULT_ENGINE


@dataclass
class EngineConfig:
    """Settings for an OpenAI-compatible engine driver."""

    base_url: str = _DEFAULT_BASE_URL
    api_key: str = _DEFAULT_API_KEY
    model: str = _DEFAULT_MODEL
    max_steps: int = _DEFAULT_MAX_STEPS
    temperature: float = _DEFAULT_TEMPERATURE
    timeout: float = _DEFAULT_TIMEOUT
    context_budget_tokens: int = _DEFAULT_CONTEXT_BUDGET
    max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS
    subagent_concurrency: int = _DEFAULT_SUBAGENT_CONCURRENCY
    autosplit_target_tokens: int = _DEFAULT_AUTOSPLIT_TARGET_TOKENS
    fillline_threshold: float = _DEFAULT_FILLLINE_THRESHOLD

    # A runtime-only per-step progress sink ``(step_index, tool, target, ok)``
    # the loop fires per tool call (#38). Set by the CLI work path, not by
    # ``resolve()``; excluded from eq/repr and from ``to_dict`` (it is behavior,
    # not serializable config).
    progress: Optional[Callable[[int, str, str, bool], None]] = field(
        default=None, compare=False, repr=False
    )

    # Runtime-only spawn callback for subagent delegation; set by the work item
    # path, not by ``resolve()``; excluded from eq/repr/to_dict (it is behavior,
    # not serializable config).
    subagent_spawn: Optional[Callable] = field(default=None, compare=False, repr=False)

    # Runtime-only batch-spawn callback for parallel subagent delegation; set by
    # the work path, not by ``resolve()``; excluded from eq/repr/to_dict (it is
    # behavior, not serializable config).
    subagent_batch_spawn: Optional[Callable] = field(default=None, compare=False, repr=False)

    @classmethod
    def resolve(
        cls,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_steps: int | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
        context_budget_tokens: int | None = None,
        max_output_chars: int | None = None,
        subagent_concurrency: int | None = None,
        autosplit_target_tokens: int | None = None,
        fillline_threshold: float | None = None,
    ) -> "EngineConfig":
        """Build a config from explicit args, env vars, then defaults."""
        return cls(
            base_url=_pick(
                base_url,
                "COLLEAGUE_BASE_URL",
                "CONVERTIBLE_BASE_URL",
                "OPENAI_BASE_URL",
                default=_DEFAULT_BASE_URL,
            ),
            api_key=_pick(
                api_key,
                "COLLEAGUE_API_KEY",
                "CONVERTIBLE_API_KEY",
                "OPENAI_API_KEY",
                default=_DEFAULT_API_KEY,
            ),
            model=_pick(model, "COLLEAGUE_MODEL", "CONVERTIBLE_MODEL", default=_DEFAULT_MODEL),
            max_steps=int(
                _pick(
                    _str(max_steps),
                    "COLLEAGUE_MAX_STEPS",
                    "CONVERTIBLE_MAX_STEPS",
                    default=str(_DEFAULT_MAX_STEPS),
                )
            ),
            temperature=float(
                _pick(
                    _str(temperature),
                    "COLLEAGUE_TEMPERATURE",
                    "CONVERTIBLE_TEMPERATURE",
                    default=str(_DEFAULT_TEMPERATURE),
                )
            ),
            timeout=float(
                _pick(
                    _str(timeout),
                    "COLLEAGUE_TIMEOUT",
                    "CONVERTIBLE_TIMEOUT",
                    default=str(_DEFAULT_TIMEOUT),
                )
            ),
            context_budget_tokens=int(
                _pick(
                    _str(context_budget_tokens),
                    "COLLEAGUE_CONTEXT_BUDGET",
                    "CONVERTIBLE_CONTEXT_BUDGET",
                    default=str(_DEFAULT_CONTEXT_BUDGET),
                )
            ),
            max_output_chars=int(
                _pick(
                    _str(max_output_chars),
                    "COLLEAGUE_MAX_OUTPUT_CHARS",
                    "CONVERTIBLE_MAX_OUTPUT_CHARS",
                    default=str(_DEFAULT_MAX_OUTPUT_CHARS),
                )
            ),
            subagent_concurrency=_try_int(
                _pick(
                    _str(subagent_concurrency),
                    "COLLEAGUE_SUBAGENT_CONCURRENCY",
                    "CONVERTIBLE_SUBAGENT_CONCURRENCY",
                    default=str(_DEFAULT_SUBAGENT_CONCURRENCY),
                ),
                default=_DEFAULT_SUBAGENT_CONCURRENCY,
            ),
            autosplit_target_tokens=int(
                _pick(
                    _str(autosplit_target_tokens),
                    "COLLEAGUE_AUTOSPLIT_TARGET",
                    "CONVERTIBLE_AUTOSPLIT_TARGET",
                    default=str(_DEFAULT_AUTOSPLIT_TARGET_TOKENS),
                )
            ),
            fillline_threshold=_try_float(
                _pick(
                    _str(fillline_threshold),
                    "COLLEAGUE_FILLLINE_THRESHOLD",
                    "CONVERTIBLE_FILLLINE_THRESHOLD",
                    default=str(_DEFAULT_FILLLINE_THRESHOLD),
                ),
                default=_DEFAULT_FILLLINE_THRESHOLD,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Config snapshot for the result artifact, with the api_key redacted."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "max_steps": self.max_steps,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "context_budget_tokens": self.context_budget_tokens,
            "autosplit_target_tokens": self.autosplit_target_tokens,
            "fillline_threshold": self.fillline_threshold,
            "max_output_chars": self.max_output_chars,
        }


def _str(value: object | None) -> str | None:
    """None-preserving str() so an unset numeric arg falls through to env/default."""
    return None if value is None else str(value)


def _try_int(value: str | None, default: int) -> int:
    """Try to parse an int from a string; return default if None, empty, or non-numeric."""
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _try_float(value: str | None, default: float) -> float:
    """Try to parse a float from a string; return default if None, empty, or non-numeric."""
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def effective_concurrency(requested: int) -> int:
    """Clamp a requested concurrency width to the valid range [1, MAX_SUBAGENT_FANOUT - 1].

    Args:
        requested: The requested concurrency level (may be 0, negative, or > max).

    Returns:
        The clamped concurrency: min(max(1, requested), MAX_SUBAGENT_FANOUT - 1).
    """
    return min(max(1, requested), MAX_SUBAGENT_FANOUT - 1)


def autosplit_children(target_tokens: int, per_child_budget_tokens: int) -> int:
    """Derive the number of child hand-over assignments for a split.

    children = ceil(target_tokens / per_child_budget_tokens), then structurally
    clamped to [1, MAX_SUBAGENT_FANOUT - 1] (the batch reserves one fan-out slot
    for the sequential merge child). Guards a non-positive per-child budget by
    returning the max usable children.

    The ceiling uses INTEGER arithmetic (``-(-a // b)``), not ``math.ceil(a / b)``:
    true division forces a float, and an absurd operator-provided ``target_tokens``
    (beyond float range) would raise ``OverflowError`` before the clamp — integer
    division stays exact for arbitrarily large ints (#151 review).
    """
    if per_child_budget_tokens <= 0:
        return MAX_SUBAGENT_FANOUT - 1
    raw = -(-target_tokens // per_child_budget_tokens)  # integer ceiling division
    return min(max(1, raw), MAX_SUBAGENT_FANOUT - 1)

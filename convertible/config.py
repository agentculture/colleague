"""Engine configuration: where the model lives and how hard the loop drives it.

Resolution precedence, highest first:

1. an explicit value passed in code / from a CLI flag,
2. a ``CONVERTIBLE_*`` environment variable,
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
_DEFAULT_MODEL = "Qwen/Qwen3-32B"
_DEFAULT_MAX_STEPS = 25
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 120.0


def _pick(explicit: str | None, *env_keys: str, default: str) -> str:
    if explicit is not None:
        return explicit
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


@dataclass
class EngineConfig:
    """Settings for an OpenAI-compatible engine driver."""

    base_url: str = _DEFAULT_BASE_URL
    api_key: str = _DEFAULT_API_KEY
    model: str = _DEFAULT_MODEL
    max_steps: int = _DEFAULT_MAX_STEPS
    temperature: float = _DEFAULT_TEMPERATURE
    timeout: float = _DEFAULT_TIMEOUT

    # A runtime-only per-step progress sink ``(step_index, tool, target, ok)``
    # the loop fires per tool call (#38). Set by the CLI drive path, not by
    # ``resolve()``; excluded from eq/repr and from ``to_dict`` (it is behavior,
    # not serializable config).
    progress: Optional[Callable[[int, str, str, bool], None]] = field(
        default=None, compare=False, repr=False
    )

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
    ) -> "EngineConfig":
        """Build a config from explicit args, env vars, then defaults."""
        return cls(
            base_url=_pick(
                base_url, "CONVERTIBLE_BASE_URL", "OPENAI_BASE_URL", default=_DEFAULT_BASE_URL
            ),
            api_key=_pick(
                api_key, "CONVERTIBLE_API_KEY", "OPENAI_API_KEY", default=_DEFAULT_API_KEY
            ),
            model=_pick(model, "CONVERTIBLE_MODEL", default=_DEFAULT_MODEL),
            max_steps=int(
                _pick(_str(max_steps), "CONVERTIBLE_MAX_STEPS", default=str(_DEFAULT_MAX_STEPS))
            ),
            temperature=float(
                _pick(
                    _str(temperature), "CONVERTIBLE_TEMPERATURE", default=str(_DEFAULT_TEMPERATURE)
                )
            ),
            timeout=float(
                _pick(_str(timeout), "CONVERTIBLE_TIMEOUT", default=str(_DEFAULT_TIMEOUT))
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
        }


def _str(value: object | None) -> str | None:
    """None-preserving str() so an unset numeric arg falls through to env/default."""
    return None if value is None else str(value)

"""Provider check-group — STUB.

Spec for the sibling agent who fills this in. This group reports on the
**provider config** the engine drivers resolve through
:class:`convertible.config.EngineConfig`. It must:

* Resolve an ``EngineConfig`` (via ``EngineConfig.resolve()``) and report the
  effective ``base_url`` and ``model`` as ``info`` checks (``passed=True``;
  these are observations, not gates). The ``api_key`` MUST be **redacted** —
  never put a secret in a message; mirror ``EngineConfig.to_dict()``, which
  deliberately omits ``api_key``.
* Emit a ``warning`` when a third-party provider credential looks unset — i.e.
  ``base_url`` points at a non-local OpenAI-compatible host but the resolved
  ``api_key`` is still the placeholder default (``"EMPTY"``) and no
  ``OPENAI_API_KEY`` / ``CONVERTIBLE_API_KEY`` is set. (A local vLLM rig needs
  no key, so a local ``base_url`` must NOT warn.)
* Emit an advisory ``provider_budget`` ``warning`` (info-level guidance about
  cost/usage budget) per the doctor spec — never an ``error`` (it is advisory).

All checks here are ``info`` or ``warning``; this group has **no** ``error``
checks (a missing provider key is advisory, not fatal — the drive will surface
the real failure). Read-only: resolves config from env + defaults only; opens no
connection to the provider. Catch any unexpected error and return it as a single
failed ``warning`` check rather than raising.

Until implemented, returns ``[]``.
"""

from __future__ import annotations


def checks() -> list[dict]:
    """STUB — returns no checks yet. See module docstring for the spec."""
    return []

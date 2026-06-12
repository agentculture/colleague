"""Shared pytest fixtures for the colleague suite.

Provider-env isolation. colleague resolves its engine config from a family of
``COLLEAGUE_*`` / ``CONVERTIBLE_*`` (legacy) / ``OPENAI_*`` environment variables
(see :meth:`colleague.config.EngineConfig.resolve`). On a developer box that
exports those for a live rig — e.g. ``COLLEAGUE_API_KEY``, ``CONVERTIBLE_BASE_URL``,
``CONVERTIBLE_MODEL`` pointed at a local vLLM — config/oilcheck tests that assert
the *built-in defaults* would otherwise flip on that ambient state and fail,
while passing in CI (where the vars are absent).

The ``_isolate_provider_env`` autouse fixture strips them before every test so the
suite is hermetic — it sees exactly what CI sees. A test that needs a var present
sets it via ``monkeypatch.setenv`` in its own body, which runs *after* this
fixture, so explicit per-test setup still wins. Clearing by prefix (not a hand-kept
list) is deliberate: it was a stale ``CONVERTIBLE_*``-only allow-list that let the
canonical ``COLLEAGUE_*`` vars leak through after the convertible→colleague rename.
"""

from __future__ import annotations

import os

import pytest

#: The ``OPENAI_*`` variables colleague actually reads (it does not consume the
#: wider OPENAI_* namespace, so only these are cleared).
_OPENAI_PROVIDER_KEYS = ("OPENAI_BASE_URL", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every colleague/convertible + provider-OpenAI env var before each test."""
    for key in list(os.environ):
        if key.startswith(("COLLEAGUE_", "CONVERTIBLE_")):
            monkeypatch.delenv(key, raising=False)
    for key in _OPENAI_PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)

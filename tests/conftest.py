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

**Hermeticity guard for the user-level config home (task t1 addendum).**
Beyond env vars, colleague's config-file loaders also resolve a *user-level*
``~/.colleague/``/``~/.convertible/`` directory via ``Path.home()`` by default
(``colleague.configdir.config_roots``). A developer machine with a real
``~/.colleague/config.json`` (stray keys, an old ``lobes``/``model`` override,
...) would otherwise leak into any test that doesn't explicitly monkeypatch
``Path.home()`` itself — CI stayed green only because CI's home happens to be
empty. This fixture additionally points ``COLLEAGUE_HOME`` at an empty
per-test directory (honored by ``configdir.config_roots`` ahead of
``Path.home()``, see ``colleague/configdir.py``'s ``_default_user_home``), so
every test is hermetic against the real home by default. A test that needs to
plant its OWN fake user-level config still wins by setting ``COLLEAGUE_HOME``
itself (via ``monkeypatch.setenv``, in its own body, which runs after this
fixture) or by passing an explicit ``user_home=`` argument to a ``configdir``
function directly — either always overrides this default.
"""

from __future__ import annotations

import os

import pytest

#: The ``OPENAI_*`` variables colleague actually reads (it does not consume the
#: wider OPENAI_* namespace, so only these are cleared).
_OPENAI_PROVIDER_KEYS = ("OPENAI_BASE_URL", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Clear every colleague/convertible + provider-OpenAI env var before each test,
    then point ``COLLEAGUE_HOME`` at an empty per-test directory (see module
    docstring) so no test can ever see the developer's real ``~/.colleague``.
    """
    for key in list(os.environ):
        if key.startswith(("COLLEAGUE_", "CONVERTIBLE_")):
            monkeypatch.delenv(key, raising=False)
    for key in _OPENAI_PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COLLEAGUE_HOME", str(tmp_path / "isolated-home"))

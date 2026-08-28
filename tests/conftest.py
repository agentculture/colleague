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

**SSE bridge over blocking stubs (#393).** Headless SSE streaming is armed by
default from #393 on, so the vLLM driver reaches for ``urllib.request.urlopen``
+ the SSE reader on every turn — not the ``vllm_openai._post_json`` blocking
function that a dozen suites monkeypatch to script their turns. Those suites
pin *transport-independent* behavior (the loop, the offered tool schema, policy
parity, degradation, the artifact shape), so the
``_sse_bridge_over_blocking_stubs`` autouse fixture keeps them running on the
DEFAULT (streaming) path instead of demoting them to the opt-out: whenever a
test has installed its own ``_post_json`` stub, a chat-completions stream is
answered from THAT stub, re-framed as SSE (:mod:`tests._vllm_http`). The bridge
is inert for every test that has not patched ``_post_json`` (the real
``urlopen`` is called), and a test that patches ``urlopen`` itself — the
streaming suites — overrides it from its own body. A suite that genuinely pins
the BLOCKING transport sets ``COLLEAGUE_STREAM=0``; that, not this bridge, is
the honest opt-out.

**PATH-independent ``web`` tool surface (deviation d16).** ``colleague/
web_schemas.py`` hides the ``web`` tool whenever ``shutil.which("webglass")``
is ``None`` — a rule that is CORRECT and must not change. But it makes the
offered tool surface depend on whether the running machine happens to have
``webglass`` installed: CI (no webglass) fails the full-surface pins that pass
on a dev box (webglass present). The ``_webglass_on_path`` autouse fixture
makes the check deterministic for the whole suite: it patches ``shutil.which``
with a delegating fake that reports ``webglass`` present (``/fake/webglass``)
and forwards every other name to the REAL ``shutil.which`` — so the
PATH-dependent behavior of the other tools (git, gh, rg, eidetic, ...) is
untouched. ``web`` is therefore OFFERED in every test unless a test explicitly
hides it. Tests that deliberately pin the hidden state (``test_web_schemas``,
``test_e2e_mock``, ``test_web``, ``test_webbudget``, ``test_livecheck``,
``test_resident_web_trust``) patch ``shutil.which`` in their own body, which
runs *after* this fixture, so their explicit setup wins.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request

import pytest

from colleague.engines import vllm_openai
from tests._vllm_http import FakeStreamResponse, sse_lines_for_turn

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


#: The pristine ``shutil.which`` — the real PATH lookup a delegating fake
#: forwards non-webglass names to, captured once at import time (before any
#: monkeypatching).
_REAL_WHICH = shutil.which


@pytest.fixture(autouse=True)
def _webglass_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the ``web`` tool's PATH check deterministic for the whole suite (d16).

    ``colleague.web_schemas`` hides ``web`` when ``shutil.which("webglass")``
    is ``None``; that rule is correct and stays. This fixture patches
    ``shutil.which`` with a delegating fake that reports ``webglass`` present
    (``/fake/webglass``) and forwards every other name to the REAL
    ``shutil.which`` — so ``web`` is offered in every test unless a test
    explicitly hides it, and the PATH-dependent behavior of the other tools
    (git, gh, rg, eidetic, ...) is untouched. A test that patches
    ``shutil.which`` in its own body (the hidden-state pins) runs after this
    fixture and wins.
    """

    def _which(name: str, *args, **kwargs):
        if name == "webglass":
            return "/fake/webglass"
        return _REAL_WHICH(name, *args, **kwargs)

    monkeypatch.setattr("shutil.which", _which)


#: The pristine blocking transport — the identity a patched ``_post_json`` is
#: compared against, captured once at import time (before any monkeypatching).
_REAL_POST_JSON = vllm_openai._post_json


@pytest.fixture(autouse=True)
def _sse_bridge_over_blocking_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer a streamed chat turn from the test's own ``_post_json`` stub (#393).

    See the module docstring. Everything is decided at CALL time, so this
    fixture never cares whether it ran before or after the test installed its
    stub, and it is a strict no-op for any test that installed none.
    """
    real_urlopen = urllib.request.urlopen

    def dispatching_urlopen(request, timeout=None):  # type: ignore[no-untyped-def]
        url = str(getattr(request, "full_url", ""))
        if vllm_openai._post_json is _REAL_POST_JSON or not url.endswith("/chat/completions"):
            return real_urlopen(request, timeout=timeout)
        payload = vllm_openai._blocking_payload(json.loads(request.data.decode("utf-8")))
        auth = request.headers.get("Authorization", "")
        turn = vllm_openai._post_json(
            url,
            payload,
            api_key=auth[len("Bearer ") :] if auth.startswith("Bearer ") else "",
            timeout=timeout if timeout is not None else 0.0,
        )
        return FakeStreamResponse(sse_lines_for_turn(turn))

    monkeypatch.setattr("urllib.request.urlopen", dispatching_urlopen)

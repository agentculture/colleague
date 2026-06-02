"""Tests for the engines check-group (oilcheck).

Uses monkeypatching of the ``colleague.registry._engine_entry_points`` seam
(the same seam ``tests/test_registry.py`` uses) to simulate various engine
discovery scenarios without needing a real installed wheel.

Scenarios covered:
* Healthy: both bundled engines present + loadable — no error checks fail.
* Missing bundled engine (only ``mock`` present) — ``bundled_engines_present``
  fails with severity "error" and a non-empty remediation.
* Zero engines discovered — ``engines_discovered`` fails (error).
* Broken/unloadable engine (load raises) — per-engine check fails (error)
  AND ``checks()`` itself does NOT raise.
* Extra out-of-tree engine — probed uniformly; no change to engines.py needed.
"""

from __future__ import annotations

from typing import Any

import pytest

from colleague import registry
from colleague.engine import Engine
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.oilcheck import diagnose
from colleague.oilcheck import engines as engines_group

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

_BUNDLED = ("mock", "vllm-openai")


class _FakeEP:
    """Duck-typed entry point matching the shape registy uses (.name/.value/.load())."""

    def __init__(self, name: str, engine_cls: type[Engine]) -> None:
        self.name = name
        self.value = f"fake.module:{engine_cls.__name__}"
        self._cls = engine_cls

    def load(self) -> type[Engine]:
        return self._cls


class _BrokenEP:
    """An entry point whose .load() raises ImportError."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.value = "broken.module:BrokenEngine"

    def load(self) -> Any:
        raise ImportError(f"no module named 'broken_module' (engine: {self.name})")


class _ThirdPartyEngine(Engine):
    name = "third-party"

    def drive(self, task, config):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _ep(*eps):
    """Return a patcher callable that fixes _engine_entry_points to ``eps``."""
    return lambda: list(eps)


# ---------------------------------------------------------------------------
# Helpers to inspect the checks returned
# ---------------------------------------------------------------------------


def _by_id(checks: list[dict], id_: str) -> dict | None:
    return next((c for c in checks if c["id"] == id_), None)


def _error_checks(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["severity"] == "error" and not c["passed"]]


# ---------------------------------------------------------------------------
# Scenario: healthy — both bundled engines present and loadable
# ---------------------------------------------------------------------------


def test_healthy_no_error_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both bundled engines present + loadable → all error-severity checks pass."""
    eps = [_FakeEP("mock", MockEngine), _FakeEP("vllm-openai", VllmOpenAIEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    assert isinstance(checks, list)
    assert _error_checks(checks) == [], _error_checks(checks)


def test_healthy_engines_discovered_check_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [_FakeEP("mock", MockEngine), _FakeEP("vllm-openai", VllmOpenAIEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    disc = _by_id(checks, "engines_discovered")
    assert disc is not None, "engines_discovered check missing"
    assert disc["passed"] is True
    assert disc["severity"] == "error"
    assert "mock" in disc["message"]
    assert "vllm-openai" in disc["message"]
    assert disc["remediation"] == ""


def test_healthy_bundled_engines_present_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [_FakeEP("mock", MockEngine), _FakeEP("vllm-openai", VllmOpenAIEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    bep = _by_id(checks, "bundled_engines_present")
    assert bep is not None, "bundled_engines_present check missing"
    assert bep["passed"] is True
    assert bep["severity"] == "error"
    assert bep["remediation"] == ""


def test_healthy_passing_checks_have_empty_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [_FakeEP("mock", MockEngine), _FakeEP("vllm-openai", VllmOpenAIEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    for check in engines_group.checks():
        if check["passed"]:
            assert (
                check["remediation"] == ""
            ), f"passed check {check['id']} has non-empty remediation"


# ---------------------------------------------------------------------------
# Scenario: missing bundled engine (only mock present)
# ---------------------------------------------------------------------------


def test_missing_vllm_openai_fails_bundled_engines_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only mock registered → bundled_engines_present fails (error)."""
    eps = [_FakeEP("mock", MockEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    bep = _by_id(checks, "bundled_engines_present")
    assert bep is not None
    assert bep["passed"] is False
    assert bep["severity"] == "error"
    assert bep["remediation"] != "", "failing bundled_engines_present must carry a remediation hint"


def test_missing_vllm_openai_remediation_mentions_pyproject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remediation hint points toward pyproject entry-points config."""
    eps = [_FakeEP("mock", MockEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    bep = _by_id(checks, "bundled_engines_present")
    assert bep is not None
    rem = bep["remediation"].lower()
    assert (
        "pyproject" in rem or "entry" in rem
    ), f"remediation should mention pyproject/entry-points, got: {bep['remediation']!r}"


def test_missing_engine_makes_diagnose_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed error in the engines group propagates to diagnose() → healthy=False."""
    eps = [_FakeEP("mock", MockEngine)]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    report = diagnose()
    assert report["healthy"] is False


# ---------------------------------------------------------------------------
# Scenario: zero engines discovered
# ---------------------------------------------------------------------------


def test_zero_engines_fails_engines_discovered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_engine_entry_points", _ep())

    checks = engines_group.checks()
    disc = _by_id(checks, "engines_discovered")
    assert disc is not None
    assert disc["passed"] is False
    assert disc["severity"] == "error"
    assert disc["remediation"] != ""


def test_zero_engines_also_fails_bundled_engines_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When zero engines, bundled engines are also missing → that check also fails."""
    monkeypatch.setattr(registry, "_engine_entry_points", _ep())

    checks = engines_group.checks()
    bep = _by_id(checks, "bundled_engines_present")
    assert bep is not None
    assert bep["passed"] is False


def test_zero_engines_makes_diagnose_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_engine_entry_points", _ep())

    report = diagnose()
    assert report["healthy"] is False


# ---------------------------------------------------------------------------
# Scenario: broken / unloadable engine
# ---------------------------------------------------------------------------


def test_broken_engine_load_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """An engine whose .load() raises → a per-engine error check is emitted."""
    eps = [
        _FakeEP("mock", MockEngine),
        _FakeEP("vllm-openai", VllmOpenAIEngine),
        _BrokenEP("broken-engine"),
    ]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    # There should be at least one failed error check mentioning the broken engine
    failed = [
        c
        for c in checks
        if not c["passed"] and c["severity"] == "error" and "broken" in c["message"].lower()
    ]
    assert failed, f"Expected a failed error check for broken-engine; got: {checks}"


def test_broken_engine_check_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """checks() MUST NOT raise even when an engine fails to load."""
    eps = [_BrokenEP("broken-engine")]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    # Must not raise:
    result = engines_group.checks()
    assert isinstance(result, list)


def test_broken_engine_failed_check_has_nonempty_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eps = [
        _FakeEP("mock", MockEngine),
        _FakeEP("vllm-openai", VllmOpenAIEngine),
        _BrokenEP("broken-engine"),
    ]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    failed = [c for c in checks if not c["passed"] and "broken" in c["message"].lower()]
    for c in failed:
        assert c["remediation"] != "", f"Failed check {c['id']} missing remediation"


def test_broken_engine_does_not_raise_and_makes_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken engine propagates to diagnose() unhealthy without raising."""
    eps = [
        _FakeEP("mock", MockEngine),
        _FakeEP("vllm-openai", VllmOpenAIEngine),
        _BrokenEP("broken-engine"),
    ]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    report = diagnose()
    assert report["healthy"] is False


# ---------------------------------------------------------------------------
# Scenario: extra out-of-tree engine (all-engines uniformity)
# ---------------------------------------------------------------------------


def test_extra_engine_is_probed_uniformly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A third-party engine present alongside bundled ones is probed too."""
    eps = [
        _FakeEP("mock", MockEngine),
        _FakeEP("vllm-openai", VllmOpenAIEngine),
        _FakeEP("third-party", _ThirdPartyEngine),
    ]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    # The engines_discovered message should mention the third-party engine
    disc = _by_id(checks, "engines_discovered")
    assert disc is not None
    assert "third-party" in disc["message"]


def test_extra_engine_no_code_change_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """engines.py code is unchanged when a 3rd-party engine appears; it just works."""
    eps = [
        _FakeEP("mock", MockEngine),
        _FakeEP("vllm-openai", VllmOpenAIEngine),
        _FakeEP("third-party", _ThirdPartyEngine),
    ]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    # No errors from any of the three (all loadable)
    assert _error_checks(checks) == [], _error_checks(checks)


def test_extra_broken_engine_probed_uniformly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a broken 3rd-party engine is probed uniformly and surfaces as a check."""
    eps = [
        _FakeEP("mock", MockEngine),
        _FakeEP("vllm-openai", VllmOpenAIEngine),
        _BrokenEP("third-party-broken"),
    ]
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    failed = [c for c in checks if not c["passed"] and "third-party-broken" in c["message"]]
    assert failed, "broken 3rd-party engine not surfaced as a check"


# ---------------------------------------------------------------------------
# Contract invariants across all returned checks
# ---------------------------------------------------------------------------


_VALID_SEVERITIES = {"error", "warning", "info"}
_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}


@pytest.mark.parametrize(
    "eps",
    [
        [],
        [_FakeEP("mock", MockEngine)],
        [_FakeEP("mock", MockEngine), _FakeEP("vllm-openai", VllmOpenAIEngine)],
        [
            _FakeEP("mock", MockEngine),
            _FakeEP("vllm-openai", VllmOpenAIEngine),
            _FakeEP("third-party", _ThirdPartyEngine),
        ],
        [_BrokenEP("broken-engine")],
    ],
    ids=["zero", "mock-only", "both-bundled", "with-third-party", "broken-only"],
)
def test_check_shape_invariants(monkeypatch: pytest.MonkeyPatch, eps: list) -> None:
    """Every returned check must satisfy the five-key contract shape."""
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    assert isinstance(checks, list)
    for check in checks:
        assert set(check) == _CHECK_KEYS, f"wrong keys: {check}"
        assert isinstance(check["id"], str) and check["id"]
        assert isinstance(check["passed"], bool)
        assert check["severity"] in _VALID_SEVERITIES
        assert isinstance(check["message"], str)
        assert isinstance(check["remediation"], str)
        if check["passed"]:
            assert (
                check["remediation"] == ""
            ), f"passed check {check['id']} has non-empty remediation"


@pytest.mark.parametrize(
    "eps",
    [
        [],
        [_FakeEP("mock", MockEngine)],
        [_FakeEP("mock", MockEngine), _FakeEP("vllm-openai", VllmOpenAIEngine)],
        [_BrokenEP("broken-engine")],
    ],
    ids=["zero", "mock-only", "both-bundled", "broken-only"],
)
def test_check_ids_are_unique(monkeypatch: pytest.MonkeyPatch, eps: list) -> None:
    """No two checks from the engines group may share an id."""
    monkeypatch.setattr(registry, "_engine_entry_points", _ep(*eps))

    checks = engines_group.checks()
    ids = [c["id"] for c in checks]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"

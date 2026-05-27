"""Wheel discovery: bundled + out-of-tree engines, selection, errors (R4, h4)."""

from __future__ import annotations

import pytest

from convertible import registry
from convertible.engine import Engine
from convertible.engines.mock import MockEngine
from convertible.engines.vllm_openai import VllmOpenAIEngine


class ThirdPartyEngine(Engine):
    """Stand-in for an engine shipped by an out-of-tree wheel."""

    name = "third-party"

    def drive(self, task, config):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class _FakeEntryPoint:
    """Duck-typed entry point: registry only reads .name/.value and calls .load()."""

    def __init__(self, name: str, value: str, engine_cls: type[Engine]) -> None:
        self.name = name
        self.value = value
        self._engine_cls = engine_cls

    def load(self) -> type[Engine]:
        return self._engine_cls


def test_bundled_engines_are_discovered() -> None:
    found = registry.names()
    assert "mock" in found
    assert "vllm-openai" in found


def test_load_returns_engine_instances() -> None:
    assert isinstance(registry.load("mock"), MockEngine)
    assert isinstance(registry.load("vllm-openai"), VllmOpenAIEngine)


def test_unknown_engine_raises_with_available_names() -> None:
    with pytest.raises(registry.UnknownEngine) as exc:
        registry.load("does-not-exist")
    assert "mock" in str(exc.value)


def test_catalog_exposes_entry_point_targets() -> None:
    targets = {w.name: w.target for w in registry.catalog()}
    assert targets["mock"].endswith("mock:MockEngine")


def test_out_of_tree_wheel_discovered_via_same_mechanism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An external wheel registering in the same group is discovered + loadable."""
    # A fake entry point alongside the real bundled ones — exactly the shape an
    # installed out-of-tree wheel produces in importlib.metadata.
    fake = _FakeEntryPoint(
        "third-party", "third_party_pkg.engine:ThirdPartyEngine", ThirdPartyEngine
    )
    real = registry._engine_entry_points()
    monkeypatch.setattr(registry, "_engine_entry_points", lambda: [*real, fake])

    assert "third-party" in registry.names()
    assert isinstance(registry.load("third-party"), ThirdPartyEngine)
    # bundled engines still discovered alongside the external one
    assert "mock" in registry.names()

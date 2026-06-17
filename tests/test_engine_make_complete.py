"""Regression test: pin the Engine.make_complete public seam (issue #204).

The base class defines make_complete(config) -> CompleteFn; the default raises
NotImplementedError mentioning a live backend. The mock engine inherits the
default. The vllm-openai engine overrides it to return a working CompleteFn.
This test pins that contract so it can't silently regress.
"""

from __future__ import annotations

import inspect

import pytest

from colleague.config import EngineConfig
from colleague.engine import Engine
from colleague.registry import load


class TestEngineMakeComplete:
    """Tests for the Engine.make_complete one-shot completion seam."""

    def test_base_class_make_complete_exists_and_is_callable(self) -> None:
        """Engine.make_complete exists on the base class and is callable."""
        assert hasattr(Engine, "make_complete")
        assert callable(getattr(Engine, "make_complete"))
        # It's a regular method (not a property or data descriptor).
        assert inspect.isfunction(Engine.make_complete)

    def test_mock_engine_raises_not_implemented(self) -> None:
        """The mock engine inherits the default make_complete, which raises
        NotImplementedError mentioning a live backend / plan mode."""
        engine = load("mock")
        config = EngineConfig()

        with pytest.raises(NotImplementedError, match="live backend"):
            engine.make_complete(config)

    def test_vllm_openai_make_complete_returns_callable(self) -> None:
        """The vllm-openai engine's make_complete(config) returns a callable
        (CompleteFn) without raising. We do NOT make any network call — we
        just confirm a callable is returned."""
        engine = load("vllm-openai")
        config = EngineConfig()

        complete_fn = engine.make_complete(config)
        assert callable(complete_fn)

"""Opt-in cortex configurator through the lattice (plan task t11) — TEST-FIRST.

Covers:

- arming resolution (:func:`colleague.configurator.configurator_enabled`) —
  env > config.json ``three_tier.configurator`` > default OFF, independent
  of ``three_tier.enabled``;
- cortex-dial resolution (:func:`colleague.configurator.resolve_cortex_dial`)
  — degrades to ``None`` absent a gateway, resolves the CORTEX role (never
  the acting/worker dial) when one is armed;
- the review (:func:`colleague.configurator.review_and_queue`) — one
  tools-off completion, strict-JSON parsing, malformed replies refused
  whole, per-entry lattice validation, event-stream recording, and
  degrade-never-raise;
- ``colleague/chain.py``'s :func:`~colleague.chain.run_configurator_window`
  — armed/unarmed, review + apply + applied-event wiring.

Acceptance criteria (plan task t11):

1. cortex proposes typed change units only; zero cortex-authored advisory
   prose in the worker's conversation; the acting completion seam is never
   wrapped — see ``tests/test_configurator_boundary.py`` for the structural
   half of this pin.
2. proposals verify then apply only at sanctioned windows; refusals recorded
   on the event stream; the configurator is opt-in and off by default.
"""

from __future__ import annotations

import json

import pytest

from colleague import chain
from colleague.config import EngineConfig
from colleague.configevents import (
    EVENT_KIND_APPLIED,
    EVENT_KIND_DEGRADED,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    EVENT_KIND_VERIFIED,
    ConfigEventStream,
)
from colleague.configlifecycle import EpisodeConfigLifecycle
from colleague.configurator import (
    ConfiguratorReviewInput,
    ConfiguratorReviewResult,
    ConfiguratorWindowResult,
    record_applied,
    review_and_queue,
)
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target
from colleague.loop import ModelResponse


def _engine_config(**overrides) -> EngineConfig:
    defaults = dict(api_key="k", model="worker-model", base_url="http://localhost:8001/v1")
    defaults.update(overrides)
    return EngineConfig.resolve(**defaults)


# ---------------------------------------------------------------------------
# A no-network fake engine, mirroring tests/test_deepthink.py's _FakeEngine
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Records make_complete()/complete() calls; no network, fully scripted."""

    name = "fake"

    def __init__(self, content: str = '{"changes": []}', raise_on_complete=None) -> None:
        self.make_complete_calls: "list[list | None]" = []
        self.complete_call_count = 0
        self.captured_messages: "list[dict] | None" = None
        self._content = content
        self._raise_on_complete = raise_on_complete

    def make_count_tokens(self, config: EngineConfig):
        def counter(messages):
            return sum(len(m.get("content") or "") for m in messages)

        return counter

    def make_complete(self, config: EngineConfig, tools=None):
        self.make_complete_calls.append(tools)

        def complete(messages):
            self.complete_call_count += 1
            self.captured_messages = messages
            if self._raise_on_complete is not None:
                raise self._raise_on_complete
            return ModelResponse(content=self._content, prompt_tokens=3, completion_tokens=5)

        return complete


def _catalog(*tool_ids: str) -> CapabilityCatalog:
    return CapabilityCatalog(tool_ids=tuple(tool_ids))


# ===========================================================================
# Change-content field (change-content-consumption-lane spec, acceptance
# criterion 2): a changes entry may carry "content" (a string) for a
# evaluator target.
# ===========================================================================


class TestContentField:
    def test_evaluator_content_is_carried_through(self) -> None:
        fake = _FakeEngine(
            content=json.dumps(
                {
                    "changes": [
                        {
                            "target": "worker.prompt.evaluator",
                            "content": "focus on the honest-README timer inversion",
                        }
                    ]
                }
            )
        )
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert len(result.refused) == 0
        assert len(result.verified) == 1
        unit = result.verified[0]
        assert unit.target is Target.WORKER_PROMPT_EVALUATOR
        assert unit.content == "focus on the honest-README timer inversion"
        assert [e.kind for e in stream.replay()] == [EVENT_KIND_PROPOSED, EVENT_KIND_VERIFIED]

    def test_content_is_not_treated_as_an_extra_key(self) -> None:
        """content joined _RECOGNIZED_CHANGE_KEYS -- it must never itself
        trigger the generic extra-keys lattice refusal on an evaluator
        target."""
        fake = _FakeEngine(
            content=json.dumps(
                {"changes": [{"target": "worker.prompt.evaluator", "content": "a note"}]}
            )
        )
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert len(result.verified) == 1

    def test_wrongly_typed_content_is_refused_whole(self) -> None:
        fake = _FakeEngine(
            content=json.dumps(
                {"changes": [{"target": "worker.prompt.evaluator", "content": 12345}]}
            )
        )
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert result.verified == []
        assert len(result.refused) == 1
        # never even reached lifecycle.propose() -- no PROPOSED event either
        assert [e.kind for e in stream.replay()] == [EVENT_KIND_REFUSED]

    def test_content_on_a_non_evaluator_target_refuses_whole_via_the_lattice(self) -> None:
        """content is only valid on a *.prompt.evaluator target -- on any
        other target the lattice's own field/target-shape check refuses the
        whole unit (this module never special-cases it)."""
        fake = _FakeEngine(
            content=json.dumps(
                {"changes": [{"target": "worker.tools", "tool_ids": ["read_file"], "content": "x"}]}
            )
        )
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert result.verified == []
        assert len(result.refused) == 1
        assert "content" in result.refused[0][1]

    def test_content_less_evaluator_unit_stays_valid(self) -> None:
        """A content-less evaluator unit (existing proposals, pre-lane)
        stays valid -- content defaults to "" and never trips the
        field/target-shape check."""
        fake = _FakeEngine(content=json.dumps({"changes": [{"target": "worker.prompt.evaluator"}]}))
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert len(result.verified) == 1
        assert result.verified[0].content == ""


# ===========================================================================
# _SYSTEM_PROMPT documents the content field (acceptance criterion 2) and
# drops the stale "carries no extra fields today" line.
# ===========================================================================


class TestSystemPromptDocumentsContent:
    def test_system_prompt_documents_content_field(self) -> None:
        from colleague.configurator import _SYSTEM_PROMPT

        assert "content" in _SYSTEM_PROMPT
        assert "carries no extra fields today" not in _SYSTEM_PROMPT


# ===========================================================================
# Degraded review visibility (change-content-consumption-lane spec,
# acceptance criterion 3): both degraded early-returns append a visible
# degraded record; a healthy empty-changes reply appends nothing and is NOT
# degraded.
# ===========================================================================


class TestDegradedVisibility:
    def test_no_dial_and_healthy_empty_changes_are_distinguishable_on_the_stream(self) -> None:
        # Path 1: no cortex dial resolvable at all -- degraded, visible.
        degraded_stream = ConfigEventStream()
        lifecycle_a = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        degraded_result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle_a,
            stream=degraded_stream,
            cortex_config=None,
            engine_name="fake",
        )

        # Path 2: cortex answered "nothing to change" -- healthy, not degraded.
        healthy_stream = ConfigEventStream()
        lifecycle_b = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        fake = _FakeEngine(content='{"changes": []}')
        healthy_result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle_b,
            stream=healthy_stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert degraded_result.degraded is True
        assert [e.kind for e in degraded_stream.replay()] == [EVENT_KIND_DEGRADED]

        assert healthy_result.degraded is False
        assert healthy_stream.replay() == []

    def test_completion_exception_degraded_path_is_also_visible(self) -> None:
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        fake = _FakeEngine(raise_on_complete=RuntimeError("dead port"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert result.degraded is True
        assert [e.kind for e in stream.replay()] == [EVENT_KIND_DEGRADED]
        assert "dead port" in stream.replay()[0].reason
        # zero proposed/verified/applied events alongside the degraded one
        assert result.proposed == []
        assert result.verified == []


# ===========================================================================
# record_applied
# ===========================================================================


class TestRecordApplied:
    def test_no_op_when_review_is_none(self) -> None:
        stream = ConfigEventStream()
        record_applied(stream, None, None)
        assert len(stream) == 0

    def test_appends_applied_per_verified_unit(self) -> None:
        stream = ConfigEventStream()
        unit = ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
        review = ConfiguratorReviewResult(verified=[unit])
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        lifecycle.propose(unit)
        application = lifecycle.apply_window(chain.WINDOW_BETWEEN_EPISODES)

        record_applied(stream, review, application)

        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_APPLIED]
        assert stream.replay()[0].target == "worker.tools"

    def test_no_op_when_nothing_applied(self) -> None:
        stream = ConfigEventStream()
        unit = ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.CORTEX, tool_ids=["read_file"])
        review = ConfiguratorReviewResult(verified=[unit])
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        # nothing proposed -> applied_count is 0
        application = lifecycle.apply_window(chain.WINDOW_BETWEEN_EPISODES)

        record_applied(stream, review, application)

        assert len(stream) == 0


# ===========================================================================
# colleague/chain.py's run_configurator_window
# ===========================================================================


class TestRunConfiguratorWindow:
    def test_unarmed_is_a_strict_no_op(self) -> None:
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        lifecycle.propose(
            ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.HOST, tool_ids=["read_file"])
        )

        result = chain.run_configurator_window(
            lifecycle,
            chain.WINDOW_BETWEEN_EPISODES,
            armed=False,
            review_input=ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            stream=stream,
            config=_engine_config(),
            engine_name="fake",
        )

        assert isinstance(result, ConfiguratorWindowResult)
        assert result.reviewed is False
        assert result.review is None
        assert result.application is None
        # a pre-existing (host-queued) proposal is untouched by the unarmed call
        assert lifecycle.pending_count() == 1
        assert len(stream) == 0

    def test_armed_reviews_applies_and_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from colleague import lobes as _lobes

        cortex_role = _lobes.RoleInfo(
            model="cortex-model",
            endpoint="",
            path="",
            context=0,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )
        senses_role = _lobes.RoleInfo(
            model="senses-model",
            endpoint="",
            path="",
            context=0,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )
        roles = _lobes.LobesRoles(cortex=cortex_role, senses=senses_role)
        monkeypatch.setattr(_lobes, "resolve_roles", lambda url, **kw: roles)

        fake = _FakeEngine(
            content=json.dumps({"changes": [{"target": "worker.tools", "tool_ids": ["read_file"]}]})
        )
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        config = _engine_config()
        config.lobes_gateway_url = "http://gateway:8000"

        result = chain.run_configurator_window(
            lifecycle,
            chain.WINDOW_BETWEEN_EPISODES,
            armed=True,
            review_input=ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            stream=stream,
            config=config,
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert result.reviewed is True
        assert len(result.review.verified) == 1
        assert result.application.applied_count == 1
        assert lifecycle.snapshot.tool_set == ("read_file",)
        assert lifecycle.pending_count() == 0
        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_PROPOSED, EVENT_KIND_VERIFIED, EVENT_KIND_APPLIED]

    def test_armed_but_no_cortex_dial_still_applies_whatever_was_already_queued(self) -> None:
        """A dormant/unreachable cortex must never block a HOST-queued
        proposal from applying at its sanctioned window."""
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        lifecycle.propose(
            ChangeUnit(target=Target.WORKER_TOOLS, origin=Origin.HOST, tool_ids=["read_file"])
        )

        result = chain.run_configurator_window(
            lifecycle,
            chain.WINDOW_BETWEEN_EPISODES,
            armed=True,
            review_input=ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            stream=stream,
            config=_engine_config(),  # no lobes_gateway_url -> cortex dial is None
            engine_name="fake",
        )

        assert result.reviewed is True
        assert result.review.degraded is True
        assert result.application.applied_count == 1
        assert lifecycle.snapshot.tool_set == ("read_file",)

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

from colleague.config import EngineConfig
from colleague.configevents import (
    EVENT_KIND_DEGRADED,
    EVENT_KIND_PROPOSED,
    EVENT_KIND_REFUSED,
    EVENT_KIND_VERIFIED,
    ConfigEventStream,
)
from colleague.configlifecycle import EpisodeConfigLifecycle
from colleague.configurator import (
    ConfiguratorReviewInput,
    configurator_enabled,
    resolve_cortex_dial,
    review_and_queue,
)
from colleague.lattice import CapabilityCatalog, Origin, Target
from colleague.loop import ModelResponse
from colleague.registry import load as registry_load


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
# Arming: opt-in, off by default (acceptance 2)
# ===========================================================================


class TestConfiguratorEnabled:
    def test_off_by_default_with_no_env_and_no_repo(self) -> None:
        assert configurator_enabled(env={}) is False

    def test_off_by_default_even_under_an_armed_three_tier_config_json(self, tmp_path) -> None:
        """The whole point of the SEPARATE opt-in flag: an armed three_tier
        block does NOT arm the configurator on its own."""
        colleague_dir = tmp_path / ".colleague"
        colleague_dir.mkdir()
        (colleague_dir / "config.json").write_text(
            json.dumps({"three_tier": {"enabled": True}}), encoding="utf-8"
        )
        assert configurator_enabled(repo_path=tmp_path, env={}) is False

    def test_env_var_arms_it(self) -> None:
        assert configurator_enabled(env={"COLLEAGUE_CONFIGURATOR": "1"}) is True

    def test_env_var_false_disarms_it(self) -> None:
        assert configurator_enabled(env={"COLLEAGUE_CONFIGURATOR": "0"}) is False

    def test_config_json_nested_configurator_key_arms_it(self, tmp_path) -> None:
        colleague_dir = tmp_path / ".colleague"
        colleague_dir.mkdir()
        (colleague_dir / "config.json").write_text(
            json.dumps({"three_tier": {"enabled": True, "configurator": True}}),
            encoding="utf-8",
        )
        assert configurator_enabled(repo_path=tmp_path, env={}) is True

    def test_env_wins_over_config_json(self, tmp_path) -> None:
        colleague_dir = tmp_path / ".colleague"
        colleague_dir.mkdir()
        (colleague_dir / "config.json").write_text(
            json.dumps({"three_tier": {"configurator": True}}), encoding="utf-8"
        )
        assert (
            configurator_enabled(repo_path=tmp_path, env={"COLLEAGUE_CONFIGURATOR": "0"}) is False
        )

    def test_bare_three_tier_boolean_carries_no_configurator_subkey(self, tmp_path) -> None:
        """A bare ``{"three_tier": true}`` has no sub-key to read — absent,
        not an error, and the default stays OFF."""
        colleague_dir = tmp_path / ".colleague"
        colleague_dir.mkdir()
        (colleague_dir / "config.json").write_text(
            json.dumps({"three_tier": True}), encoding="utf-8"
        )
        assert configurator_enabled(repo_path=tmp_path, env={}) is False


# ===========================================================================
# Cortex-dial resolution
# ===========================================================================


class TestResolveCortexDial:
    def test_no_gateway_url_degrades_to_none(self) -> None:
        config = _engine_config()
        assert resolve_cortex_dial(config) is None

    def test_unreachable_gateway_degrades_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from colleague import lobes as _lobes

        monkeypatch.setattr(_lobes, "resolve_roles", lambda url, **kw: None)
        config = _engine_config()
        assert resolve_cortex_dial(config, gateway_url="http://localhost:8000") is None

    def test_resolves_cortex_role_never_the_acting_worker_dial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In three-tier mode config.model/base_url/api_key already carry the
        WORKER's acting dial (t8) — this must resolve the CORTEX role
        instead, completely independent of those fields."""
        from colleague import lobes as _lobes

        cortex_role = _lobes.RoleInfo(
            model="cortex-model",
            endpoint="http://cortex-host:9000",
            path="",
            context=32000,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )
        senses_role = _lobes.RoleInfo(
            model="senses-model",
            endpoint="",
            path="",
            context=8000,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )
        roles = _lobes.LobesRoles(cortex=cortex_role, senses=senses_role)
        monkeypatch.setattr(_lobes, "resolve_roles", lambda url, **kw: roles)

        # config carries the WORKER's own dial (as t8 leaves it in three-tier mode)
        config = _engine_config(
            model="worker-actor-model", base_url="http://worker-host:7000/v1", api_key="worker-key"
        )

        dial = resolve_cortex_dial(config, gateway_url="http://gateway:8000")

        assert dial is not None
        assert dial.model == "cortex-model"
        assert "cortex-host:9000" in dial.base_url
        assert dial.context_budget_tokens == 32000
        # every OTHER knob is inherited unchanged from config (the
        # deepthink_engine_config precedent)
        assert dial.max_steps == config.max_steps

    def test_no_model_on_cortex_role_degrades_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from colleague import lobes as _lobes

        cortex_role = _lobes.RoleInfo(
            model="",
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
            context=8000,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )
        roles = _lobes.LobesRoles(cortex=cortex_role, senses=senses_role)
        monkeypatch.setattr(_lobes, "resolve_roles", lambda url, **kw: roles)
        config = _engine_config()
        assert resolve_cortex_dial(config, gateway_url="http://gateway:8000") is None


# ===========================================================================
# review_and_queue — degrade-never-raise
# ===========================================================================


class TestReviewDegradation:
    def test_no_cortex_config_degrades_immediately(self) -> None:
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        result = review_and_queue(
            ConfiguratorReviewInput(digest="episode facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=None,
            engine_name="fake",
        )
        assert result.degraded is True
        # a total inability to reach cortex is VISIBLE on the stream, never
        # silent (the #363 armed-is-not-alive lesson) — distinct from a
        # healthy {"changes": []} reply, which appends nothing at all.
        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_DEGRADED]
        assert stream.replay()[0].reason == "no cortex dial resolvable"

    def test_engine_loader_raising_degrades(self) -> None:
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))

        def bad_loader(name):
            raise RuntimeError("no such engine")

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="dead",
            engine_loader=bad_loader,
        )
        assert result.degraded is True
        # the completion-exception degraded path is equally visible on the
        # stream, carrying the exception text as the reason.
        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_DEGRADED]
        assert "no such engine" in stream.replay()[0].reason

    def test_mock_engine_not_implemented_degrades_never_raises(self) -> None:
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="mock",
            engine_loader=registry_load,
        )
        assert result.degraded is True
        assert [e.kind for e in stream.replay()] == [EVENT_KIND_DEGRADED]

    def test_completion_call_uses_tools_off(self) -> None:
        fake = _FakeEngine()
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file"))
        review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )
        assert fake.make_complete_calls == [[]]
        assert fake.complete_call_count == 1


# ===========================================================================
# review_and_queue — malformed replies refused whole
# ===========================================================================


class TestMalformedReplyRefusedWhole:
    def test_unparseable_json_is_refused_whole(self) -> None:
        fake = _FakeEngine(content="not json at all, just prose")
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

        assert result.degraded is False
        assert len(result.refused) == 1
        assert result.proposed == []
        assert result.verified == []
        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_REFUSED]

    def test_changes_not_a_list_is_refused_whole(self) -> None:
        fake = _FakeEngine(content=json.dumps({"changes": "not-a-list"}))
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

        assert len(result.refused) == 1
        assert [e.kind for e in stream.replay()] == [EVENT_KIND_REFUSED]

    def test_empty_changes_list_is_a_legitimate_no_op(self) -> None:
        """{"changes": []} is the common case — nothing malformed about it."""
        fake = _FakeEngine(content='{"changes": []}')
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

        assert result.degraded is False
        assert result.refused == []
        assert result.proposed == []
        assert len(stream) == 0


# ===========================================================================
# review_and_queue — per-entry parsing + validation + event recording
# ===========================================================================


class TestPerEntryProcessing:
    def test_valid_worker_tools_change_is_verified_and_queued(self) -> None:
        fake = _FakeEngine(
            content=json.dumps({"changes": [{"target": "worker.tools", "tool_ids": ["read_file"]}]})
        )
        stream = ConfigEventStream()
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog("read_file", "grep"))

        result = review_and_queue(
            ConfiguratorReviewInput(digest="facts"),
            catalog=_catalog("read_file", "grep"),
            lifecycle=lifecycle,
            stream=stream,
            cortex_config=_engine_config(),
            engine_name="fake",
            engine_loader=lambda n: fake,
        )

        assert len(result.verified) == 1
        unit = result.verified[0]
        assert unit.target is Target.WORKER_TOOLS
        assert unit.origin is Origin.CORTEX  # ALWAYS stamped, never model-declared
        assert unit.tool_ids == ["read_file"]
        # queued on the lifecycle, not yet applied
        assert lifecycle.pending_count() == 1
        assert lifecycle.snapshot.tool_set == ()

        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_PROPOSED, EVENT_KIND_VERIFIED]
        assert stream.replay()[0].target == "worker.tools"
        assert stream.replay()[0].origin == "cortex"

    def test_out_of_catalog_tool_id_is_refused_and_recorded(self) -> None:
        fake = _FakeEngine(
            content=json.dumps({"changes": [{"target": "worker.tools", "tool_ids": ["nope"]}]})
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
        assert lifecycle.pending_count() == 0
        kinds = [e.kind for e in stream.replay()]
        assert kinds == [EVENT_KIND_PROPOSED, EVENT_KIND_REFUSED]
        assert "nope" in stream.replay()[1].reason

    def test_unknown_target_string_is_refused(self) -> None:
        fake = _FakeEngine(content=json.dumps({"changes": [{"target": "operator.secrets"}]}))
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

    def test_operator_owned_surface_target_is_refused(self) -> None:
        """hooks/approvals/etc. are never valid lattice targets — the
        configurator inherits the lattice's own refusal, never a bespoke one."""
        fake = _FakeEngine(content=json.dumps({"changes": [{"target": "hooks"}]}))
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
        assert "hooks" in result.refused[0][1]
        assert "scope" in result.refused[0][1]

    def test_senses_target_is_out_of_this_lifecycle_scope_and_refused(self) -> None:
        """senses.* is a VALID lattice target for cortex authority-wise, but
        this worker-episode lifecycle refuses it (a different consumer's
        scope) — the configurator records that refusal too."""
        fake = _FakeEngine(content=json.dumps({"changes": [{"target": "senses.knowledge"}]}))
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

    def test_missing_target_key_is_refused_whole_without_aborting_the_batch(self) -> None:
        fake = _FakeEngine(
            content=json.dumps(
                {
                    "changes": [
                        {"tool_ids": ["read_file"]},  # missing "target" -> refused
                        {"target": "worker.prompt.evaluator"},  # valid -> verified
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

        assert len(result.refused) == 1
        assert len(result.verified) == 1
        assert result.verified[0].target is Target.WORKER_PROMPT_EVALUATOR

    def test_wrongly_typed_tool_ids_is_refused_whole(self) -> None:
        fake = _FakeEngine(
            content=json.dumps({"changes": [{"target": "worker.tools", "tool_ids": "read_file"}]})
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

    def test_non_object_entry_is_refused_whole(self) -> None:
        fake = _FakeEngine(content=json.dumps({"changes": ["worker.tools"]}))
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

    def test_valid_worker_knowledge_change_stamps_and_queues(self) -> None:
        fake = _FakeEngine(
            content=json.dumps(
                {
                    "changes": [
                        {
                            "target": "worker.knowledge",
                            "knowledge_entries": [{"origin": "cortex", "text": "a fact"}],
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

        assert len(result.verified) == 1
        assert result.verified[0].knowledge_entries == [{"origin": "cortex", "text": "a fact"}]

    def test_model_declared_origin_is_ignored_never_trusted(self) -> None:
        """A model claiming origin="host" (to try to escalate its own
        authority) is silently overridden to Origin.CORTEX -- never trusted,
        and its presence does not itself trigger an extra-keys refusal."""
        fake = _FakeEngine(
            content=json.dumps(
                {"changes": [{"target": "worker.prompt.evaluator", "origin": "host"}]}
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
        assert result.verified[0].origin is Origin.CORTEX

    def test_genuinely_unknown_extra_key_refuses_whole_via_the_lattice(self) -> None:
        fake = _FakeEngine(
            content=json.dumps(
                {"changes": [{"target": "worker.prompt.evaluator", "policy": "escalate"}]}
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
        assert "forbidden" in result.refused[0][1] or "policy" in result.refused[0][1]


# ===========================================================================
# Entry-level knowledge origin auto-stamping (change-content-consumption-lane
# spec, acceptance criterion 1): a cortex knowledge entry lacking origin
# validates post-stamp with origin=cortex; a model-supplied origin (entry-
# level or unit-level) is still discarded — authority is never self-declared.
# ===========================================================================


class TestKnowledgeEntryOriginStamping:
    def test_entry_lacking_origin_validates_post_stamp(self) -> None:
        """Before this stamp, a knowledge entry with no 'origin' key refuses
        at the lattice (missing/empty origin) — this is the exact experiment
        C refusal. Auto-stamping fixes it: the entry validates with
        origin=cortex, host-known, never requested of the model."""
        fake = _FakeEngine(
            content=json.dumps(
                {
                    "changes": [
                        {
                            "target": "worker.knowledge",
                            "knowledge_entries": [{"text": "a fact, no origin supplied"}],
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
        assert result.verified[0].knowledge_entries == [
            {"text": "a fact, no origin supplied", "origin": "cortex"}
        ]
        assert [e.kind for e in stream.replay()] == [EVENT_KIND_PROPOSED, EVENT_KIND_VERIFIED]

    def test_entry_level_model_supplied_origin_is_discarded_and_restamped(self) -> None:
        """A model claiming a knowledge entry's origin="host" (an attempt to
        escalate an individual entry's authority, distinct from the
        unit-level origin) is discarded then re-stamped cortex — never
        conditionally left alone because "already present"."""
        fake = _FakeEngine(
            content=json.dumps(
                {
                    "changes": [
                        {
                            "target": "worker.knowledge",
                            "knowledge_entries": [{"origin": "host", "text": "trying to escalate"}],
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

        assert len(result.verified) == 1
        entry = result.verified[0].knowledge_entries[0]
        assert entry["origin"] == "cortex"
        assert entry["text"] == "trying to escalate"

    def test_unit_level_and_entry_level_origin_both_discarded_together(self) -> None:
        """A single reply that claims escalated authority at BOTH the
        unit-level 'origin' key AND inside a knowledge entry is fully
        neutralised: the resulting ChangeUnit.origin is CORTEX and every
        knowledge entry's origin is 'cortex', regardless of what the model
        claimed at either level."""
        fake = _FakeEngine(
            content=json.dumps(
                {
                    "changes": [
                        {
                            "target": "worker.knowledge",
                            "origin": "host",
                            "knowledge_entries": [{"origin": "host", "text": "a fact"}],
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

        assert len(result.verified) == 1
        unit = result.verified[0]
        assert unit.origin is Origin.CORTEX
        assert unit.knowledge_entries[0]["origin"] == "cortex"

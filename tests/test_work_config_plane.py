"""TEST-FIRST for the work front arming the config plane (plan task t9).

Spec: docs/specs/2026-08-06-change-content-consumption-lane.md — covers c5,
h5, c28, h22.

Acceptance criteria under test:

1. three-tier armed (``config.worker`` resolved): lifecycle + stream
   constructed, catalog built from the run's actually-resolved tool surface,
   ``run_configurator_window`` at ``WINDOW_BEFORE_EPISODE_1`` before the
   first dispatch (plain work AND chains) and ``WINDOW_BETWEEN_EPISODES`` in
   ``execute_work_chain``'s go-verdict path; the lifecycle is attached to
   ``config`` so the loop + engines consume it.
2. no three-tier: byte-identical (no lifecycle, no windows, no events,
   artifact shape unchanged). three-tier armed + configurator OFF: the
   lifecycle IS constructed, windows run as strict no-ops
   (``reviewed=False``), ZERO completions issued.
3. the cumulative fold updates BOTH the in-memory ``TaskResult`` and the
   on-disk artifact after each window; a run killed between the fold and the
   artifact-update loses at most the last window's events.

Arming happens INSIDE ``execute_work``/``execute_work_chain`` (never in
``cmd_work``'s argv parsing) so both the CLI and the ``session`` palette
(which call these two functions directly) inherit it identically — these
tests call the two functions directly, mirroring
``tests/test_work_mode_wiring.py``'s and ``tests/test_flight_heartbeat.py``'s
own direct-call conventions, rather than going through the full CLI/lobes
resolution just to populate ``config.worker``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from colleague import chain as chainmod
from colleague.cli._commands.work import execute_work, execute_work_chain
from colleague.config import EngineConfig, WorkerConfig
from colleague.configevents import EVENT_KIND_BASELINE
from colleague.contract import OK, Task, TaskResult
from colleague.loop import ModelResponse, ToolCall

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A git-initialised repo with an initial commit (cwd-scoped identity)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "init")
    return repo


def _worker_armed_config(**overrides) -> EngineConfig:
    """A resolved config with a three-tier worker seat — built DIRECTLY
    (rather than through ``EngineConfig.resolve()`` against a live lobes
    gateway), mirroring ``tests/test_flight_heartbeat.py``'s
    ``_worker_armed_config`` helper: only ``config.worker``'s presence
    matters to the front's arming decision (config.py's own resolution rung
    already makes the worker role MANDATORY-if-armed, so a hand-built
    ``WorkerConfig`` is a faithful stand-in for what ``resolve()`` would have
    produced against a real gateway)."""
    config = EngineConfig.resolve()
    config.three_tier = True
    config.worker = WorkerConfig(
        model="worker-model", base_url="http://worker.example:8000/v1", api_key="k", context=32000
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _task(repo: Path, instruction: str = "map the loop") -> Task:
    return Task.new(str(repo), instruction, engine="mock")


class _DualEngine:
    """A fake engine serving BOTH call sites arming can reach:

    - ``.work()`` — the acting (worker) dispatch every ``execute_work`` call
      makes. Records the config it received (so a test can inspect
      ``config.config_lifecycle`` post-dispatch) and, when a lifecycle is
      attached, calls ``end_episode()`` on it — the ONE piece of
      ``colleague/loop.py``'s real behavior this fake mimics, so a fold test
      sees a realistic lifecycle event trail (an episode boundary marker)
      without standing up the whole bounded loop.
    - ``.make_complete()`` — the cortex review's own completion,
      reached via ``colleague.chain.run_configurator_window`` ->
      ``colleague.configurator.review_and_queue``'s default
      ``engine_loader=registry.load`` (the SAME patched ``registry.load``
      resolves both call sites in these tests, so one fake covers both).
    """

    name = "fake"

    def __init__(
        self,
        seen: list,
        *,
        content: str = '{"changes": []}',
        results: "list[TaskResult] | None" = None,
        mimic_end_episode: bool = True,
    ) -> None:
        self.seen = seen
        self._content = content
        self._results = results or []
        self._call = 0
        self.mimic_end_episode = mimic_end_episode
        self.complete_calls = 0

    def work(self, task: Task, config: EngineConfig) -> TaskResult:
        self.seen.append(config)
        lifecycle = getattr(config, "config_lifecycle", None)
        if self.mimic_end_episode and lifecycle is not None:
            lifecycle.end_episode()
        if self._results:
            result = self._results[min(self._call, len(self._results) - 1)]
            self._call += 1
            return replace(result, task_id=task.id)
        return TaskResult(task_id=task.id, status=OK, summary="done")

    def make_complete(self, config: EngineConfig, tools=None):
        def complete(messages):
            self.complete_calls += 1
            return ModelResponse(content=self._content, prompt_tokens=3, completion_tokens=5)

        return complete


# ===========================================================================
# Criterion 2 (first half) — no three-tier: byte-identical
# ===========================================================================


class TestUnarmedByteIdentical:
    def test_no_worker_no_lifecycle_no_events_no_artifact_keys(self, git_repo, monkeypatch):
        seen: list = []
        monkeypatch.setattr("colleague.registry.load", lambda name: _DualEngine(seen))
        config = EngineConfig.resolve(repo_path=git_repo)
        assert config.worker is None  # sanity: genuinely unarmed

        result, artifact_path = execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        assert seen[0].config_lifecycle is None
        assert result.config_events == []
        assert result.config_digest is None
        data = json.loads(artifact_path.read_text())
        assert "config_events" not in data
        assert "config_digest" not in data

    def test_unarmed_chain_never_arms_the_config_plane(self, git_repo, monkeypatch):
        calls: list = []
        real = chainmod.run_configurator_window

        def spy(lifecycle, window, **kwargs):
            calls.append(window)
            return real(lifecycle, window, **kwargs)

        monkeypatch.setattr(chainmod, "run_configurator_window", spy)
        seen: list = []
        monkeypatch.setattr("colleague.registry.load", lambda name: _DualEngine(seen))
        config = EngineConfig.resolve(repo_path=git_repo)

        result, _artifact_path = execute_work_chain(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo, "chain unarmed"),
            open_pr=False,
            base="main",
            config=config,
            cap=5,
            allow_dirty=True,
        )

        assert calls == []  # run_configurator_window never even called
        assert result.config_events == []


# ===========================================================================
# Criteria 1 + 2 (second half) — armed, configurator OFF: lifecycle
# constructed + attached, windows are strict no-ops, zero completions
# ===========================================================================


class TestArmedConfiguratorOff:
    def test_lifecycle_constructed_attached_zero_completions(self, git_repo, monkeypatch):
        seen: list = []
        engine = _DualEngine(seen)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)
        config = _worker_armed_config()
        # configurator stays OFF (default): no COLLEAGUE_CONFIGURATOR env, no
        # .colleague/config.json three_tier.configurator key.

        result, artifact_path = execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        # Lifecycle constructed + attached before the (only) dispatch —
        # acceptance criterion 1's "lifecycle attached to config so loop +
        # engines consume it".
        assert seen[0].config_lifecycle is not None
        # The configurator's own opt-in flag stayed off -> zero completions
        # issued anywhere (acceptance criterion 2).
        assert engine.complete_calls == 0
        # The window ran as a strict no-op (reviewed=False): the ONLY event
        # on the combined trail is the lifecycle's own end_episode boundary
        # marker (mimicked by the fake engine above) — no
        # proposed/verified/refused/applied/degraded anywhere.
        assert [e.kind for e in result.config_events] == [EVENT_KIND_BASELINE]
        data = json.loads(artifact_path.read_text())
        assert [e["kind"] for e in data["config_events"]] == [EVENT_KIND_BASELINE]
        assert data["config_digest"] == result.config_digest

    def test_run_configurator_window_reports_unreviewed(self, git_repo, monkeypatch):
        seen_results: list = []
        real = chainmod.run_configurator_window

        def spy(lifecycle, window, **kwargs):
            result = real(lifecycle, window, **kwargs)
            seen_results.append(result)
            return result

        monkeypatch.setattr(chainmod, "run_configurator_window", spy)
        seen: list = []
        monkeypatch.setattr("colleague.registry.load", lambda name: _DualEngine(seen))
        config = _worker_armed_config()

        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        assert len(seen_results) == 1
        assert seen_results[0].reviewed is False
        assert seen_results[0].review is None
        assert seen_results[0].application is None


# ===========================================================================
# Criterion 1 — catalog built from the run's actually-resolved tool surface
# ===========================================================================


class TestCapabilityCatalog:
    def test_catalog_matches_curate_schemas_for_the_resolved_role(self, git_repo, monkeypatch):
        from colleague.loop import resolve_role
        from colleague.tools import curate_schemas

        captured: dict = {}
        real = chainmod.run_configurator_window

        def spy(lifecycle, window, **kwargs):
            captured["catalog"] = kwargs["catalog"]
            return real(lifecycle, window, **kwargs)

        monkeypatch.setattr(chainmod, "run_configurator_window", spy)
        seen: list = []
        monkeypatch.setattr("colleague.registry.load", lambda name: _DualEngine(seen))
        config = _worker_armed_config()
        config.role = "explorer"

        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        expected_role = resolve_role(config, str(git_repo))
        expected_ids = tuple(s["function"]["name"] for s in curate_schemas(expected_role))
        assert captured["catalog"].tool_ids == expected_ids
        assert expected_ids  # sanity: the explorer role isn't the empty set


# ===========================================================================
# Criterion 1 — WINDOW_BEFORE_EPISODE_1 runs before the (only) dispatch, for
# plain (non-chained) work
# ===========================================================================


class TestPlainWorkWindowTiming:
    def test_before_episode_1_runs_once_before_dispatch(self, git_repo, monkeypatch):
        order: list = []
        real = chainmod.run_configurator_window

        def spy(lifecycle, window, **kwargs):
            order.append(("window", window))
            return real(lifecycle, window, **kwargs)

        monkeypatch.setattr(chainmod, "run_configurator_window", spy)

        seen: list = []

        class _OrderedEngine(_DualEngine):
            def work(self, task, config):
                order.append(("dispatch", task.id))
                return super().work(task, config)

        engine = _OrderedEngine(seen)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)
        config = _worker_armed_config()

        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        assert [w for kind, w in order if kind == "window"] == [chainmod.WINDOW_BEFORE_EPISODE_1]
        assert order[0][0] == "window"
        assert order[1][0] == "dispatch"


# ===========================================================================
# Criterion 1 (chain half) + h22 — a chain shares ONE lifecycle across
# episodes; WINDOW_BEFORE_EPISODE_1 fires once, WINDOW_BETWEEN_EPISODES fires
# in the go-verdict path
# ===========================================================================


def _budget_turn(episode: int) -> ModelResponse:
    return ModelResponse(
        content=f"episode {episode} still working",
        tool_calls=[
            ToolCall(
                f"e{episode}",
                "write_file",
                {"path": f"episode-{episode}.txt", "content": f"episode {episode} work\n"},
            )
        ],
        prompt_tokens=1,
        completion_tokens=1,
    )


def _finish_turn() -> ModelResponse:
    return ModelResponse(
        content="done",
        tool_calls=[ToolCall("fin", "finish", {"summary": "chain complete"})],
        prompt_tokens=1,
        completion_tokens=1,
    )


def _script_two_episodes(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Episode 1 writes a file and never finishes (budget-exhausted, the
    continuable exit reason); episode 2 finishes ok. Mirrors
    ``tests/test_work_chain.py``'s own ``_script_episodes`` harness, trimmed
    to the two-episode shape these tests need."""
    counter = {"n": 0}

    def fake_script(task):
        counter["n"] += 1
        n = counter["n"]

        def complete(messages):
            return _budget_turn(n) if n == 1 else _finish_turn()

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", fake_script)
    return counter


class TestChainWindowTiming:
    def test_two_episode_chain_windows_before_and_between(self, git_repo, monkeypatch):
        _script_two_episodes(monkeypatch)

        calls: list = []
        lifecycles_seen: list = []
        real = chainmod.run_configurator_window

        def spy(lifecycle, window, **kwargs):
            calls.append(window)
            lifecycles_seen.append(lifecycle)
            return real(lifecycle, window, **kwargs)

        monkeypatch.setattr(chainmod, "run_configurator_window", spy)

        config = _worker_armed_config()
        config.max_steps = 1  # episode 1's single write-only turn exits budget-exhausted
        task = _task(git_repo, "chain the work")

        result, _artifact_path = execute_work_chain(
            repo=git_repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            cap=5,
            allow_dirty=True,
        )

        assert calls == [chainmod.WINDOW_BEFORE_EPISODE_1, chainmod.WINDOW_BETWEEN_EPISODES]
        # h22: "a chain's episodes share the same instance" — never rebuilt
        # mid-chain.
        assert lifecycles_seen[0] is lifecycles_seen[1]
        assert result.status == OK

    def test_config_lifecycle_is_the_same_object_across_episodes(self, git_repo, monkeypatch):
        _script_two_episodes(monkeypatch)
        seen_lifecycles: list = []

        from colleague.engines import mock as mock_engine

        original_work = mock_engine.MockEngine.work

        def recording_work(self, task, config):
            seen_lifecycles.append(getattr(config, "config_lifecycle", None))
            return original_work(self, task, config)

        monkeypatch.setattr(mock_engine.MockEngine, "work", recording_work)

        config = _worker_armed_config()
        config.max_steps = 1
        task = _task(git_repo, "chain the work again")

        execute_work_chain(
            repo=git_repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            cap=5,
            allow_dirty=True,
        )

        assert len(seen_lifecycles) == 2
        assert seen_lifecycles[0] is not None
        assert seen_lifecycles[0] is seen_lifecycles[1]


# ===========================================================================
# Criterion 3 — the cumulative fold: real applied content lands on BOTH the
# in-memory TaskResult and the on-disk artifact
# ===========================================================================


class TestCumulativeFold:
    def test_applied_strategist_content_lands_on_result_and_artifact(self, git_repo, monkeypatch):
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
        monkeypatch.setenv("COLLEAGUE_CONFIGURATOR", "1")

        content = json.dumps(
            {"changes": [{"target": "worker.prompt.strategist", "content": "focus on X"}]}
        )
        seen: list = []
        engine = _DualEngine(seen, content=content)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)

        config = _worker_armed_config()
        config.lobes_gateway_url = "http://gateway.example:8000"

        result, artifact_path = execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        applied = [e for e in result.config_events if e.kind == "applied"]
        assert len(applied) == 1
        assert applied[0].content == "focus on X"
        assert result.config_digest is not None

        data = json.loads(artifact_path.read_text())
        applied_dict = [e for e in data["config_events"] if e["kind"] == "applied"]
        assert len(applied_dict) == 1
        assert applied_dict[0]["content"] == "focus on X"
        assert data["config_digest"] == result.config_digest

    def test_crash_window_honesty_write_precedes_the_fold_update(self, git_repo, monkeypatch):
        """Acceptance criterion 3, crash-window honesty: the base artifact
        (steps/usage/status/etc.) is durably written by
        ``colleague.artifact.write`` BEFORE the config-plane fold ever calls
        ``update_config_events`` — so a process killed between the two loses
        AT MOST this window's events; the base result (and every EARLIER
        window's already-folded events, on a chain) are already safe on
        disk. This test proves the ordering directly: by the time
        ``update_config_events`` runs, the on-disk artifact already exists
        and already lacks ``config_events`` (the base write happened first,
        without them)."""
        from colleague.artifact import find_artifact

        observed: dict = {}

        import colleague.cli._commands.work as work_module

        real_update = work_module.update_config_events

        def spy_update(repo_path, task_id, config_events):
            path = find_artifact(repo_path, task_id)
            observed["existed_before_update"] = path is not None
            if path is not None:
                on_disk = json.loads(path.read_text())
                observed["had_config_events_before_update"] = "config_events" in on_disk
            return real_update(repo_path, task_id, config_events)

        monkeypatch.setattr(work_module, "update_config_events", spy_update)

        seen: list = []
        monkeypatch.setattr("colleague.registry.load", lambda name: _DualEngine(seen))
        config = _worker_armed_config()

        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        assert observed["existed_before_update"] is True
        assert observed["had_config_events_before_update"] is False


class TestCombinedTrailSourcesTheStream:
    """Regression pins for the Qodo #369 review findings on the fold.

    Thread 1: a refusal that happens BEFORE ``lifecycle.propose()`` (a
    malformed reply / a change entry that fails to build) exists ONLY on the
    configurator stream — the previous lifecycle-first fold dropped it from
    ``TaskResult.config_events`` entirely.

    Thread 2: the previous fold appended the stream's "verified" events
    after ALL mapped lifecycle events, so a verified record could land after
    its own applied record — breaking the cycle's causal order
    (proposed -> verified -> applied).
    """

    def _state(self):
        from colleague.cli._commands.work import _ConfigPlaneState
        from colleague.configevents import ConfigEventStream
        from colleague.configlifecycle import EpisodeConfigLifecycle
        from colleague.lattice import CapabilityCatalog

        catalog = CapabilityCatalog(tool_ids=("read_file", "finish"))
        return _ConfigPlaneState(
            lifecycle=EpisodeConfigLifecycle(catalog=catalog),
            stream=ConfigEventStream(),
            catalog=catalog,
        )

    def test_pre_propose_refusal_is_visible_on_the_folded_trail(self):
        """A stream-only refusal (never proposed onto the lifecycle) survives
        the fold — pre-change this list was empty of it (Qodo thread 1)."""
        from colleague.cli._commands.work import _combined_config_events
        from colleague.configevents import EVENT_KIND_REFUSED

        state = self._state()
        state.stream.append(
            EVENT_KIND_REFUSED,
            origin="cortex",
            reason="malformed configurator reply: no JSON object found",
        )
        folded = _combined_config_events(state)
        refused = [e for e in folded if e.kind == EVENT_KIND_REFUSED]
        assert len(refused) == 1
        assert "malformed configurator reply" in refused[0].reason

    def test_verified_precedes_applied_in_the_folded_trail(self):
        """The cycle's causal order (proposed -> verified -> applied) is
        preserved verbatim from the stream — pre-change every verified event
        trailed every applied event (Qodo thread 2)."""
        from colleague.cli._commands.work import _combined_config_events
        from colleague.configevents import (
            EVENT_KIND_APPLIED,
            EVENT_KIND_PROPOSED,
            EVENT_KIND_VERIFIED,
        )
        from colleague.lattice import ChangeUnit, Origin, Target

        state = self._state()
        unit = ChangeUnit(
            target=Target.WORKER_PROMPT_STRATEGIST,
            origin=Origin.CORTEX,
            content="Verify before editing.",
        )
        target = Target.WORKER_PROMPT_STRATEGIST.value
        state.stream.append(EVENT_KIND_PROPOSED, target=target, origin="cortex")
        state.stream.append(EVENT_KIND_VERIFIED, target=target, origin="cortex")
        state.stream.append(EVENT_KIND_APPLIED, target=target, origin="cortex")
        state.applied_units.append(unit)
        assert state.lifecycle.propose(unit).allowed
        state.lifecycle.apply_window("before-episode-1")
        state.lifecycle.end_episode()

        folded = _combined_config_events(state)
        kinds = [e.kind for e in folded]
        assert kinds.index(EVENT_KIND_VERIFIED) < kinds.index(EVENT_KIND_APPLIED)
        # the applied record still carries the verbatim content (q5)
        applied = [e for e in folded if e.kind == EVENT_KIND_APPLIED]
        assert getattr(applied[0], "content", "") == "Verify before editing."
        # the boundary marker survives as the trailing baseline record
        assert kinds[-1] == "baseline"
        # seq is monotonic across the combined trail
        assert [e.seq for e in folded] == list(range(len(folded)))

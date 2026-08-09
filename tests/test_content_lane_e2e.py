"""Announcement-level (c1/h1) hermetic end-to-end proofs for the
change-content consumption lane (plan task t11 — spec docs/specs/
2026-08-06-change-content-consumption-lane.md).

Every OTHER task's own test file (t1 tests/test_lattice.py, t2 tests/
test_flight_heartbeat.py, t3 tests/test_tool_narrowing.py, t5 tests/
test_configlifecycle.py, t6 tests/test_configurator.py, t7 tests/
test_engine_evaluator_seam.py, t8 tests/test_contract_configevents.py, t9
tests/test_work_config_plane.py, t10 tests/test_subagent_config_snapshot.py)
already proves its OWN mechanism in isolation. This module's job is
different: it is the ONE place that drives a SINGLE scripted cortex
conversation all the way through the REAL front (``colleague.cli._commands.
work.execute_work``, exactly what ``colleague work``/``session`` call) and
proves the six lanes the announcement names hold TOGETHER, end to end, with
no rig and no network:

  (a) an evaluator note lands in the NEXT episode's composed system prompt
  (b) a tool narrowing lands on the offered schema AND the executor
  (c) the front's armed windows fold config_events onto the artifact
  (d) cortex knowledge-entry origins are auto-stamped (a model-supplied
      origin, at either level, is discarded)
  (e) the flight run-start line names the seat that actually acts
  (f) the applied content on the artifact is byte-verbatim

...plus the containment claims (acceptance criterion 3): an over-cap
evaluator proposal refuses whole, the section renders under its ONE named
heading on every engine's composed prompt, and an unarmed run has no code
path by which cortex text could ever reach a prompt.

Hermetic, by construction (h "no rig, no network" — the spec's own end-to-end
honesty condition):

- the cortex review's own completion is SCRIPTED — a fake/wrapper engine's
  ``make_complete()`` returns a fixed :class:`~colleague.loop.ModelResponse`
  directly (the "engine_loader for a fake engine" shape
  ``colleague.configurator.review_and_queue`` documents), never touching a
  socket;
- the WORKER side is driven either by the real ``MockEngine`` with its
  module-level ``_script`` monkeypatched (so prompt composition, tool
  narrowing, and the executor all run for real), or by the real
  ``VllmOpenAIEngine`` with ``vllm_openai._post_json`` monkeypatched (so the
  actual wire ``tools=``/``messages=`` payload can be inspected) —
  the SAME "mock HTTP" convention every other engine test in this repo uses.

Failing-first (h17), honestly: most lanes below depend on the FULL t1-t10
chain landing together (the front's own arming, t9, is the LAST piece — see
each class's own pre-arc note for the exact commit/gap). A literal single
revert of this whole tree to reproduce one true "pre-arc" RED run is
impractical (work.py/chain.py/configurator.py/configlifecycle.py/
lattice.py/contract.py/artifact.py/engine.py/tools.py/mock.py/vllm_openai.py
all changed across the ten tasks) — per the task instruction's own stated
fallback, each class names the SPECIFIC pre-arc commit and the SPECIFIC
assertion that fails there instead, and two of them (the two closest to a
single-file swap) are verified directly the same way
tests/test_configurator_boundary.py's and tests/test_loop_config_lifecycle.py's
own t11 additions are: temporarily checking out one file at its pre-arc SHA,
observing the red, and restoring it (see each docstring's "Verified
directly" note).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from colleague import flight
from colleague import lobes as _lobes
from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig, WorkerConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.layers import EVALUATOR_SECTION_HEADING, EVALUATOR_SECTION_MAX_CHARS
from colleague.loop import ModelResponse, ToolCall

# ---------------------------------------------------------------------------
# Harness — mirrors tests/test_work_config_plane.py's own fixtures exactly,
# the established pattern for driving execute_work() hermetically.
# ---------------------------------------------------------------------------


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "init")
    return repo


def _task(repo: Path, instruction: str = "map the auth flow", *, watch: bool = False) -> Task:
    return Task.new(str(repo), instruction, engine="mock", watch=watch)


def _worker_armed_config(**overrides: Any) -> EngineConfig:
    config = EngineConfig.resolve()
    config.three_tier = True
    config.worker = WorkerConfig(
        model="worker-model", base_url="http://worker.example:8000/v1", api_key="k", context=32000
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _arm_configurator_cortex_dial(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arm the configurator's own opt-in flag + a resolvable (mocked) cortex
    dial — mirrors tests/test_work_config_plane.py's ``TestCumulativeFold``
    fixture setup exactly. The cortex dial only needs to RESOLVE (so
    ``resolve_cortex_dial`` returns non-``None`` and ``review_and_queue``
    actually issues its one completion); the completion itself is scripted
    directly below, so nothing here ever opens a socket.
    """
    monkeypatch.setenv("COLLEAGUE_CONFIGURATOR", "1")
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


class _ScriptedCortexMockEngine(MockEngine):
    """The REAL ``MockEngine`` (prompt composition, tool-narrowing, the
    executor all run for real via the inherited ``.work()``) with
    ``.make_complete()`` overridden to return a SCRIPTED cortex JSON reply
    directly — no network, no rig. This is the "engine_loader for a fake
    engine whose make_complete returns a scripted JSON reply" shape
    ``colleague.configurator.review_and_queue`` documents, applied via the
    SAME ``colleague.registry.load`` monkeypatch
    tests/test_work_config_plane.py's own ``_DualEngine`` harness uses (the
    established hermetic-engine pattern in this repo) — the ONE difference
    is this subclasses the real engine instead of faking ``.work()`` too, so
    the worker's OWN dispatch is 100% production code.
    """

    def __init__(self, cortex_content: str) -> None:
        self._cortex_content = cortex_content
        self.complete_calls = 0

    def make_complete(self, config: EngineConfig, tools: Any = None):
        def complete(messages: list[dict]) -> ModelResponse:
            self.complete_calls += 1
            return ModelResponse(content=self._cortex_content, prompt_tokens=3, completion_tokens=5)

        return complete


def _fake_worker_script(captured_prompts: list, attempt: tuple[str, dict]):
    """A ``colleague.engines.mock._script`` replacement: turn 1 captures the
    FULL composed system prompt and attempts *attempt* (a ``(tool, args)``
    pair); turn 2 always finishes cleanly. Mirrors
    tests/test_work_config_plane.py's own ``_script_two_episodes`` /
    ``fake_script`` monkeypatch convention.
    """

    def build(task: Task):
        state = {"n": 0}

        def complete(messages: list[dict]) -> ModelResponse:
            state["n"] += 1
            if state["n"] == 1:
                captured_prompts.append(messages[0]["content"])
                name, args = attempt
                return ModelResponse(
                    content="attempting",
                    tool_calls=[ToolCall("1", name, args)],
                    prompt_tokens=1,
                    completion_tokens=1,
                )
            return ModelResponse(
                content="done",
                tool_calls=[ToolCall("2", "finish", {"summary": "done"})],
                prompt_tokens=1,
                completion_tokens=1,
            )

        return complete

    return build


def _read_artifact(path: Path) -> dict:
    return json.loads(path.read_text())


# ===========================================================================
# Lanes (a) + (b, executor half) + (c) + (f) — ONE hermetic mock run:
# a scripted cortex reply carrying BOTH evaluator content AND a tool
# narrowing in the SAME window -> the next (only) episode's composed prompt
# carries the text, the narrowed-away tool refuses at the executor, the
# folded config_events (incl. verbatim applied content) ride BOTH the
# in-memory TaskResult and the on-disk artifact.
#
# Pre-arc gap (h17): before plan task t9 landed (commit 273cdde, "merge t8"
# — the tree immediately before t9's front-arming), no front ever
# constructed an EpisodeConfigLifecycle or called
# colleague.chain.run_configurator_window at all (the "d3" gap the spec
# names): grep confirms zero occurrences of "config_lifecycle" or
# "run_configurator_window" in colleague/cli/_commands/work.py at that
# commit. So on that tree, execute_work(config=<armed config>, ...) would
# leave config.config_lifecycle unset regardless of config.worker, and
# EVERY assertion below (composed-prompt heading, executor refusal via
# narrowing, config_events, artifact content) fails at the very first one
# reached. Not re-verified empirically here (a multi-file revert spanning
# t1/t4/t5/t6/t7/t8/t9 together is impractical within this task's tests-only
# scope) — see the two extended files (tests/test_configurator_boundary.py,
# tests/test_loop_config_lifecycle.py) for this module's empirically
# verified single-file pre-arc reverts.
# ===========================================================================


class TestEvaluatorAndToolNarrowingHermeticEndToEnd:
    def test_scripted_cortex_reply_drives_prompt_narrowing_and_artifact(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _arm_configurator_cortex_dial(monkeypatch)
        note = "focus on the auth module before anything else"
        cortex_content = json.dumps(
            {
                "changes": [
                    {"target": "worker.prompt.evaluator", "content": note},
                    {"target": "worker.tools", "tool_ids": ["list_dir", "read_file", "finish"]},
                ]
            }
        )
        engine = _ScriptedCortexMockEngine(cortex_content)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)

        captured_prompts: list = []
        monkeypatch.setattr(
            "colleague.engines.mock._script",
            _fake_worker_script(
                captured_prompts, attempt=("write_file", {"path": "x.txt", "content": "y"})
            ),
        )

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

        # -- lane (a): the evaluator note rides the NEXT (here: only)
        # episode's composed system prompt, under its named heading.
        assert captured_prompts, "the scripted worker completion must have been called"
        system_content = captured_prompts[0]
        assert EVALUATOR_SECTION_HEADING in system_content
        assert note in system_content

        # -- lane (b), executor half: write_file was narrowed away
        # (tool_ids excludes it) -> refused at the ONE allowlist mechanism,
        # never executed.
        assert result.changed_files == []
        write_steps = [s for s in result.steps if s.tool == "write_file"]
        assert write_steps
        assert write_steps[0].ok is False
        assert "not allowed for this role" in write_steps[0].result
        assert config.config_lifecycle is not None
        assert config.config_lifecycle.snapshot.tool_set == ("list_dir", "read_file", "finish")

        # -- lane (c): the front's armed windows folded config_events onto
        # BOTH the in-memory result and the on-disk artifact.
        kinds = [e.kind for e in result.config_events]
        assert "proposed" in kinds
        assert "verified" in kinds
        assert "applied" in kinds
        applied = [e for e in result.config_events if e.kind == "applied"]
        assert len(applied) == 2  # the evaluator unit + the tools unit
        assert result.config_digest is not None

        data = _read_artifact(artifact_path)
        assert [e["kind"] for e in data["config_events"]] == kinds
        assert data["config_digest"] == result.config_digest

        # -- lane (f): the applied evaluator unit's content is byte-verbatim
        # on BOTH the in-memory result and the on-disk artifact; the
        # sibling applied tools unit carries no content (only evaluator
        # targets ever do).
        applied_evaluator = [e for e in applied if e.target == "worker.prompt.evaluator"]
        assert len(applied_evaluator) == 1
        assert applied_evaluator[0].content == note

        applied_dicts = [e for e in data["config_events"] if e["kind"] == "applied"]
        applied_evaluator_dict = [
            e for e in applied_dicts if e["target"] == "worker.prompt.evaluator"
        ]
        assert len(applied_evaluator_dict) == 1
        assert applied_evaluator_dict[0]["content"] == note

        applied_tools_dict = [e for e in applied_dicts if e["target"] == "worker.tools"]
        assert len(applied_tools_dict) == 1
        assert "content" not in applied_tools_dict[0]


# ===========================================================================
# Lane (b), schema half — the offered wire schema is narrowed on
# vllm-openai (all-engines rule), proven directly on the actual HTTP
# payload; lane (a) re-proven on the second engine too (the composed system
# prompt rides the SAME messages[0] the worker's real request carries).
#
# Pre-arc gap (h17): same t9 boundary as above (no front ever armed
# anything) PLUS, independently, before plan task t3 landed (commit
# 5df5950, "merge t1" — the tree immediately before t3's narrowing
# consumption), colleague/engines/vllm_openai.py never read
# config.config_lifecycle at all: grep at that commit shows zero
# occurrences of "config_lifecycle" in that file, so ``offered_tools`` was
# always the FULL role-curated surface regardless of any narrowing — the
# "sent_tool_names == narrowed set" assertion below fails on that tree too.
# ===========================================================================


class _RealWorkFakeCortex:
    """Delegates ``.work()`` to a REAL :class:`VllmOpenAIEngine` (so system
    prompt composition + offered-schema narrowing + the executor all run for
    real, over mocked HTTP) while ``.make_complete()`` — the cortex review's
    OWN completion — returns a scripted JSON reply directly, bypassing the
    wire entirely for that one call. Reached via the SAME
    ``colleague.registry.load`` monkeypatch every other hermetic engine test
    in this repo uses.
    """

    def __init__(self, real_engine: VllmOpenAIEngine, cortex_content: str) -> None:
        self.name = real_engine.name
        self._real = real_engine
        self._cortex_content = cortex_content
        self.complete_calls = 0

    def work(self, task: Task, config: EngineConfig):
        return self._real.work(task, config)

    def make_complete(self, config: EngineConfig, tools: Any = None):
        def complete(messages: list[dict]) -> ModelResponse:
            self.complete_calls += 1
            return ModelResponse(content=self._cortex_content, prompt_tokens=3, completion_tokens=5)

        return complete


def _openai_finish_turn() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "v1",
                            "function": {
                                "name": "finish",
                                "arguments": json.dumps({"summary": "done"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


class TestOfferedSchemaNarrowedOnTheWire:
    def test_vllm_offered_schema_narrowed_and_prompt_carries_the_note(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _arm_configurator_cortex_dial(monkeypatch)
        note = "prioritise reading the auth module first"
        cortex_content = json.dumps(
            {
                "changes": [
                    {"target": "worker.prompt.evaluator", "content": note},
                    {"target": "worker.tools", "tool_ids": ["list_dir", "read_file", "finish"]},
                ]
            }
        )
        engine = _RealWorkFakeCortex(VllmOpenAIEngine(), cortex_content)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)

        captured_payloads: list = []

        def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
            captured_payloads.append(payload)
            return _openai_finish_turn()

        monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

        config = _worker_armed_config()
        config.lobes_gateway_url = "http://gateway.example:8000"

        result, artifact_path = execute_work(
            repo=git_repo,
            engine_name="vllm-openai",
            task=Task.new(str(git_repo), "map the auth flow", engine="vllm-openai"),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        assert result.status == OK
        assert captured_payloads, "the worker's real HTTP-mocked completion must have posted"
        worker_payload = captured_payloads[0]

        # lane (b): the OFFERED wire schema is exactly the narrowed set.
        sent_tool_names = {t["function"]["name"] for t in worker_payload["tools"]}
        assert sent_tool_names == {"list_dir", "read_file", "finish"}

        # lane (a), all-engines parity: the SAME composed system prompt rides
        # the actual request the worker sent.
        system_content = worker_payload["messages"][0]["content"]
        assert EVALUATOR_SECTION_HEADING in system_content
        assert note in system_content

        data = _read_artifact(artifact_path)
        assert data["config_digest"] == result.config_digest


# ===========================================================================
# Lane (d) — cortex knowledge-entry origins are auto-stamped; a
# model-supplied origin, at EITHER level (the unit's own "origin" key, or an
# individual knowledge entry's own "origin" key), is discarded and
# re-stamped "cortex" — never trusted.
#
# Pre-arc gap (h17, VERIFIED DIRECTLY below): before plan task t6 landed
# (commit 09fdf23, "merge t3" — the tree immediately before t6's
# origin-stamping fix), colleague/configurator.py's ``_build_change_unit``
# built ``knowledge_entries=list(knowledge_raw)`` — entries passed through
# COMPLETELY UNSTAMPED (the exact experiment C refusal the spec names). The
# unit-level origin was already stamped at that commit (not the bug); only
# the ENTRY-level stamp is new at t6.
# ===========================================================================


class TestAutoStampedKnowledgeOrigins:
    def test_model_supplied_origin_discarded_and_restamped_cortex(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _arm_configurator_cortex_dial(monkeypatch)
        cortex_content = json.dumps(
            {
                "changes": [
                    {
                        "target": "worker.knowledge",
                        "origin": "operator",  # unit-level: must be discarded
                        "knowledge_entries": [
                            {"origin": "operator-declared", "fact": "auth flow uses JWT"}
                        ],
                    }
                ]
            }
        )
        engine = _ScriptedCortexMockEngine(cortex_content)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)
        monkeypatch.setattr(
            "colleague.engines.mock._script",
            _fake_worker_script([], attempt=("finish", {"summary": "done"})),
        )

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

        assert config.config_lifecycle is not None
        entries = config.config_lifecycle.snapshot.knowledge_entries
        assert len(entries) == 1
        parsed = json.loads(entries[0])
        # Entry-level: the model-supplied "operator-declared" is discarded,
        # re-stamped "cortex".
        assert parsed["origin"] == "cortex"
        assert parsed["fact"] == "auth flow uses JWT"

        # Unit-level: the applied event's own origin is ALSO "cortex", never
        # the model-supplied "operator" the change entry itself carried.
        applied = [e for e in result.config_events if e.kind == "applied"]
        assert len(applied) == 1
        assert applied[0].origin == "cortex"

        data = _read_artifact(artifact_path)
        # The trail's LAST record is the run-exit boundary marker (baseline,
        # no origin) — the applied record is what carries the stamped origin.
        artifact_applied = [e for e in data["config_events"] if e["kind"] == "applied"]
        assert artifact_applied[-1]["origin"] == "cortex"


# ===========================================================================
# Lane (e) — the flight run-start line names the seat that actually acts,
# THROUGH THE FRONT (execute_work), not just via a direct engine.work() call
# (tests/test_flight_heartbeat.py already covers that half at the t2 unit
# level).
#
# Pre-arc gap (h17): before plan task t2 landed (commit d274f85, the plan
# commit itself — the tree before ANY task in this arc), grep confirms zero
# occurrences of "seat" in colleague/engines/mock.py: there was no seat
# parameter at all threaded from an engine into colleague.loop.run(), so the
# flight run-start line always said "cortex started" regardless of whether
# config.worker was resolved. The armed-arm assertion below
# (``rec["seat"] == "worker"``) fails unconditionally on that tree.
# ===========================================================================


class TestSeatNamedFlightLineThroughTheFront:
    @pytest.fixture(autouse=True)
    def _keep_feed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep the feed past finish so this test can inspect what the loop
        wrote — mirrors tests/test_flight_heartbeat.py's own ``keep_feed``
        fixture."""
        monkeypatch.setattr(flight.FlightSession, "reap", lambda self: None)

    def _run_start_record(self, repo: Path, task_id: str) -> dict:
        lines = flight.feed_path(repo, task_id).read_text().splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return next(r for r in records if r.get("type") == "run-start")

    def test_armed_run_names_the_worker_seat(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("colleague.registry.load", lambda name: MockEngine())
        config = _worker_armed_config()
        task = _task(git_repo, watch=True)

        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        rec = self._run_start_record(git_repo, task.id)
        assert rec["seat"] == "worker"
        assert rec["intent"].startswith("worker started")

    def test_unarmed_run_names_cortex_byte_identically(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("colleague.registry.load", lambda name: MockEngine())
        config = EngineConfig.resolve()
        assert config.worker is None  # sanity: genuinely unarmed
        task = _task(git_repo, watch=True)

        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        rec = self._run_start_record(git_repo, task.id)
        assert rec["seat"] == "cortex"
        assert rec["intent"].startswith("cortex started")


# ===========================================================================
# Containment (acceptance criterion 3): over-cap refuses whole, the section
# renders only under its ONE named heading on every engine, and an unarmed
# run has no code path by which cortex text reaches any prompt.
# ===========================================================================


class TestContainment:
    def test_over_cap_evaluator_content_refuses_whole_through_the_front(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-arc gap (h17): before plan task t1 landed (commit 8571cb4's
        parent, i.e. the pre-arc HEAD c5436c7), ``ChangeUnit`` carried no
        ``content`` field at all and ``_check_field_target_shape`` had no
        length check — an over-cap proposal could not even be EXPRESSED, let
        alone refused. On the current tree it is refused whole at the
        lattice, before ever reaching the snapshot or any prompt.
        """
        _arm_configurator_cortex_dial(monkeypatch)
        over_cap = "x" * (EVALUATOR_SECTION_MAX_CHARS + 1)
        cortex_content = json.dumps(
            {"changes": [{"target": "worker.prompt.evaluator", "content": over_cap}]}
        )
        engine = _ScriptedCortexMockEngine(cortex_content)
        monkeypatch.setattr("colleague.registry.load", lambda name: engine)

        captured_prompts: list = []
        monkeypatch.setattr(
            "colleague.engines.mock._script",
            _fake_worker_script(captured_prompts, attempt=("finish", {"summary": "done"})),
        )

        config = _worker_armed_config()
        config.lobes_gateway_url = "http://gateway.example:8000"

        result, _artifact_path = execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo),
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )

        assert config.config_lifecycle is not None
        # Refused whole — never folded onto the effective snapshot.
        assert config.config_lifecycle.snapshot.evaluator_sections == ()
        refused = [e for e in result.config_events if e.kind == "refused"]
        assert refused
        assert refused[0].target == "worker.prompt.evaluator"
        applied = [e for e in result.config_events if e.kind == "applied"]
        assert applied == []
        # And it never reached the composed prompt.
        assert captured_prompts
        assert EVALUATOR_SECTION_HEADING not in captured_prompts[0]

    def test_evaluator_section_renders_under_its_one_heading_on_both_engines(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both engines compose the SAME heading exactly once — never
        interleaved as raw instructions, never doubled (the #363 T3 trap
        t7's own docstring names). Reuses this module's two harnesses
        (mock + vllm) rather than re-deriving a third."""
        note = "keep changes small and reviewable"

        # -- mock half
        _arm_configurator_cortex_dial(monkeypatch)
        cortex_content = json.dumps(
            {"changes": [{"target": "worker.prompt.evaluator", "content": note}]}
        )
        mock_engine = _ScriptedCortexMockEngine(cortex_content)
        monkeypatch.setattr("colleague.registry.load", lambda name: mock_engine)
        captured_prompts: list = []
        monkeypatch.setattr(
            "colleague.engines.mock._script",
            _fake_worker_script(captured_prompts, attempt=("finish", {"summary": "done"})),
        )
        mock_config = _worker_armed_config()
        mock_config.lobes_gateway_url = "http://gateway.example:8000"
        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=_task(git_repo, "task one"),
            open_pr=False,
            base="main",
            config=mock_config,
            allow_dirty=True,
        )
        assert captured_prompts[0].count(EVALUATOR_SECTION_HEADING) == 1

        # -- vllm half
        vllm_engine = _RealWorkFakeCortex(VllmOpenAIEngine(), cortex_content)
        monkeypatch.setattr("colleague.registry.load", lambda name: vllm_engine)
        captured_payloads: list = []

        def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
            captured_payloads.append(payload)
            return _openai_finish_turn()

        monkeypatch.setattr(vllm_openai, "_post_json", fake_post)
        vllm_config = _worker_armed_config()
        vllm_config.lobes_gateway_url = "http://gateway.example:8000"
        execute_work(
            repo=git_repo,
            engine_name="vllm-openai",
            task=Task.new(str(git_repo), "task two", engine="vllm-openai"),
            open_pr=False,
            base="main",
            config=vllm_config,
            allow_dirty=True,
        )
        vllm_system = captured_payloads[0]["messages"][0]["content"]
        assert vllm_system.count(EVALUATOR_SECTION_HEADING) == 1
        # And the engine's own default system text still carries through
        # (the #363 T3 trap: an evaluator-only composition must not silently
        # drop the engine base) — both composed prompts are longer than the
        # heading + note alone.
        assert len(vllm_system) > len(EVALUATOR_SECTION_HEADING) + len(note) + 50
        assert len(captured_prompts[0]) > len(EVALUATOR_SECTION_HEADING) + len(note) + 50

    def test_unarmed_run_has_no_code_path_for_cortex_text(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Grep-level + behavioral, combined.

        Grep-level: ``colleague/cli/_commands/work.py`` is the ONLY
        production module that ever assigns ``config.config_lifecycle =``
        (an attribute ASSIGNMENT, not a comparison) anywhere in
        ``colleague/`` — and that one assignment is gated behind
        ``if config.worker is None: return None`` (``_arm_config_plane``,
        i.e. arming is impossible without a resolved three-tier worker).
        ``colleague/engine.py`` is the ONLY module that ever passes
        ``evaluator_section=`` to the composition layer
        (``colleague/layers.py``), and it reads that value from
        ``config.config_lifecycle`` alone — never a literal, never
        ``task.instruction``/``task.goal``. So an unarmed config
        (``config_lifecycle`` absent/``None``, the default) has no reachable
        path to inject cortex text into any composed prompt.

        Behavioral: an unarmed ``execute_work`` run's composed prompt never
        contains the heading regardless of what the task's OWN
        instruction/goal happen to contain (proving the heading is never a
        pass-through of untrusted user text either).
        """
        import colleague.cli._commands.work as work_module
        import colleague.engine as engine_module

        work_source = Path(work_module.__file__).read_text(encoding="utf-8")
        assignment_sites = [
            line
            for line in work_source.splitlines()
            if "config_lifecycle" in line
            and "=" in line
            and "==" not in line
            and "config.config_lifecycle =" in line
        ]
        assert len(assignment_sites) == 1
        assert "config.config_lifecycle = lifecycle" in assignment_sites[0]

        # No OTHER production module assigns config.config_lifecycle.
        import colleague

        pkg_dir = Path(colleague.__file__).parent
        offenders = []
        for path in pkg_dir.rglob("*.py"):
            if path == Path(work_module.__file__):
                continue
            text = path.read_text(encoding="utf-8")
            if "config.config_lifecycle = " in text or "config.config_lifecycle=" in text:
                offenders.append(str(path))
        assert offenders == []

        engine_source = Path(engine_module.__file__).read_text(encoding="utf-8")
        assert engine_source.count("evaluator_section=evaluator_section") >= 1

        # Behavioral: an unarmed run, even with the heading text SITTING in
        # the task's own instruction, never composes it into the prompt via
        # the evaluator seam (task.instruction rides the USER message, not
        # the system message's evaluator section — a separate, pre-existing
        # boundary this reconfirms rather than assumes).
        monkeypatch.setattr("colleague.registry.load", lambda name: MockEngine())
        captured_prompts: list = []
        monkeypatch.setattr(
            "colleague.engines.mock._script",
            _fake_worker_script(captured_prompts, attempt=("finish", {"summary": "done"})),
        )
        config = EngineConfig.resolve()
        assert config.worker is None
        task = Task.new(
            str(git_repo), f"do the thing; also mention {EVALUATOR_SECTION_HEADING}", engine="mock"
        )
        execute_work(
            repo=git_repo,
            engine_name="mock",
            task=task,
            open_pr=False,
            base="main",
            config=config,
            allow_dirty=True,
        )
        assert getattr(config, "config_lifecycle", None) is None
        assert EVALUATOR_SECTION_HEADING not in captured_prompts[0]

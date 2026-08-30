"""``TaskResult.prompt_digest`` — the instrument that makes a prose arm
attributable (plan task t7, ``docs/plans/2026-08-29-purpose-tools-get-chosen.md``,
covers c49/h36).

A live-testing row that claims "this run used prompt arm B" is only worth
anything if the claim can be checked against the run itself. Before this
field the only evidence was the overlay file the operator *believed* was in
place at dispatch time. ``prompt_digest`` is a sha256 of the system prompt the
backend ACTUALLY handed ``colleague.loop.run`` — operator overlay included —
so t16's acceptance ("every run's prompt digest read off its artifact matches
the arm the row claims; a mismatch voids that run") has something real to read.

Shape follows ``config_digest`` EXACTLY (see
``tests/test_contract_configevents.py``): omit-when-``None``, round-tripped by
``from_dict``, produced from ONE pure helper.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from colleague import salvage
from colleague.config import EngineConfig
from colleague.contract import Task, TaskResult, prompt_digest_for
from colleague.engines import mock as mock_engine_mod
from colleague.engines import vllm_openai
from colleague.engines.mock import MockEngine
from colleague.engines.vllm_openai import VllmOpenAIEngine
from colleague.loop import ModelResponse, WorkAborted
from tests._batch_fixture import (
    BATCH_TASK_INSTRUCTION,
    make_batch_repo,
    vllm_batch_turns,
)

_MODEL = "Qwen/Qwen3-32B"
_OVERLAY_MARKER = "PROMPT-ARM-B-MARKER"


def _task(repo: Path) -> Task:
    return Task(id="t7", instruction="do a thing", repo_path=str(repo))


def _write_writer_overlay(repo: Path, body: str) -> None:
    """An operator prompt overlay — the very thing a prose arm changes."""
    agents = repo / ".colleague" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "writer.md").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# The pure helper: a sha256 of the composed prompt, omit-when-None.
# ---------------------------------------------------------------------------


def test_prompt_digest_for_is_the_sha256_of_the_prompt() -> None:
    prompt = "You are a colleague.\nRule: land the change."
    assert prompt_digest_for(prompt) == hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def test_prompt_digest_for_is_none_for_no_composed_prompt() -> None:
    assert prompt_digest_for(None) is None


def test_prompt_digest_for_digests_an_empty_prompt() -> None:
    """``""`` IS a composed prompt (the backend composed something, it was
    empty); only ``None`` — no prompt at all — is omitted."""
    assert prompt_digest_for("") == hashlib.sha256(b"").hexdigest()


def test_prompt_digest_for_is_deterministic_and_collision_free_on_a_one_char_edit() -> None:
    """Determinism is asserted against an INDEPENDENTLY computed digest, not
    against a second call to the same function — comparing an expression with
    itself can never fail, so it would prove nothing (SonarCloud python:S5863).
    Pinning the literal sha256 also catches a change of hash algorithm."""
    expected_a = hashlib.sha256(b"arm A").hexdigest()
    assert prompt_digest_for("arm A") == expected_a
    assert prompt_digest_for("arm B") != expected_a


# ---------------------------------------------------------------------------
# Artifact shape: beside config_digest, omitted when None, round-tripped.
# ---------------------------------------------------------------------------


def test_prompt_digest_defaults_to_none() -> None:
    assert TaskResult(task_id="x", status="ok").prompt_digest is None


def test_prompt_digest_is_omitted_when_none() -> None:
    """A run with no composed prompt serializes byte-identically to the
    pre-``prompt_digest`` artifact — no extra key."""
    assert "prompt_digest" not in TaskResult(task_id="x", status="ok").to_dict()


def test_prompt_digest_sits_beside_config_digest() -> None:
    result = TaskResult(
        task_id="x",
        status="ok",
        config_digest="deadbeef",
        prompt_digest="cafebabe",
    )
    keys = list(result.to_dict())
    assert keys.index("prompt_digest") == keys.index("config_digest") + 1


def test_prompt_digest_round_trips_through_from_dict() -> None:
    digest = prompt_digest_for("some composed prompt")
    original = TaskResult(task_id="x", status="ok", prompt_digest=digest)
    restored = TaskResult.from_dict(original.to_dict())
    assert restored.prompt_digest == digest


def test_prompt_digest_absent_from_dict_reads_back_as_none() -> None:
    restored = TaskResult.from_dict({"task_id": "x", "status": "ok"})
    assert restored.prompt_digest is None


# ---------------------------------------------------------------------------
# Acceptance 1 — different composed prompts -> different digests on the
#                artifact; identical prompts -> identical digests.
# ---------------------------------------------------------------------------


def _run_mock(repo: Path) -> TaskResult:
    return MockEngine().work(
        Task.new(str(repo), "write the output file", engine="mock"),
        EngineConfig(model=_MODEL),
    )


def test_two_prose_arms_show_different_prompt_digests(tmp_path: Path) -> None:
    """Arm A (no operator overlay) and arm B (an overlay under
    ``.colleague/agents/writer.md``) compose DIFFERENT system prompts — and
    the difference is visible on each run's artifact without trusting the
    filesystem the run happened to see."""
    arm_a = tmp_path / "arm_a"
    arm_b = tmp_path / "arm_b"
    arm_a.mkdir()
    arm_b.mkdir()
    _write_writer_overlay(arm_b, _OVERLAY_MARKER)

    result_a = _run_mock(arm_a)
    result_b = _run_mock(arm_b)

    assert result_a.prompt_digest is not None
    assert result_b.prompt_digest is not None
    assert result_a.prompt_digest != result_b.prompt_digest
    # And the difference survives the artifact serialization the row reads.
    assert result_a.to_dict()["prompt_digest"] != result_b.to_dict()["prompt_digest"]


def test_two_runs_with_identical_prompts_show_identical_prompt_digests(tmp_path: Path) -> None:
    arm_b1 = tmp_path / "b1"
    arm_b2 = tmp_path / "b2"
    arm_b1.mkdir()
    arm_b2.mkdir()
    _write_writer_overlay(arm_b1, _OVERLAY_MARKER)
    _write_writer_overlay(arm_b2, _OVERLAY_MARKER)

    result_1 = _run_mock(arm_b1)
    result_2 = _run_mock(arm_b2)

    assert result_1.prompt_digest == result_2.prompt_digest
    assert result_1.prompt_digest is not None


def test_prompt_digest_is_the_digest_of_the_prompt_that_actually_ran(tmp_path: Path) -> None:
    """Not a re-derivation: the digest equals sha256 of exactly what
    ``Engine.system_prompt`` composed for that repo, overlay included."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_writer_overlay(repo, _OVERLAY_MARKER)

    engine = MockEngine()
    composed = engine.system_prompt(_task(repo), EngineConfig(model=_MODEL))
    assert composed is not None
    assert _OVERLAY_MARKER in composed

    result = _run_mock(repo)
    assert result.prompt_digest == hashlib.sha256(composed.encode("utf-8")).hexdigest()


def test_prompt_digest_is_omitted_when_the_backend_composed_no_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The byte-identical floor: a backend whose ``system_prompt`` returns
    ``None`` leaves the key OFF the artifact entirely."""
    monkeypatch.setattr(MockEngine, "system_prompt", lambda self, task, config: None)
    result = _run_mock(tmp_path)
    assert result.prompt_digest is None
    assert "prompt_digest" not in result.to_dict()


# ---------------------------------------------------------------------------
# All-engines rule — vllm-openai records the field the same way mock does.
# ---------------------------------------------------------------------------


def test_vllm_records_the_same_prompt_digest_as_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns = vllm_batch_turns()
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)

    cfg = EngineConfig.resolve()
    mock_repo = make_batch_repo(tmp_path / "mock")
    vllm_repo = make_batch_repo(tmp_path / "vllm")

    mock_result = MockEngine().work(
        Task.new(str(mock_repo), BATCH_TASK_INSTRUCTION, engine="mock"), cfg
    )
    vllm_result = VllmOpenAIEngine().work(
        Task.new(str(vllm_repo), "identical batch task", engine="vllm-openai"), cfg
    )

    assert mock_result.prompt_digest is not None
    assert vllm_result.prompt_digest is not None
    # Same model, same (empty) overlay state -> the SAME composed prompt on
    # both backends, hence the same digest: the all-engines rule, measured.
    assert mock_result.prompt_digest == vllm_result.prompt_digest


# ---------------------------------------------------------------------------
# The failure paths — an aborted / signal-salvaged run is EXACTLY the run whose
# arm attribution matters most (Qodo 3888125917).
#
# Both engines stamped ``prompt_digest`` only AFTER ``loop.run()`` returned, so
# a ``WorkAborted`` (which carries the loop's partial result out past that line)
# and the interrupt-salvage handler (which writes the live result object while
# the loop is still inside ``run()``) both produced an artifact with the key
# missing — even though the composed prompt had already gone to the model. The
# digest is now stamped the moment the loop's ``TaskResult`` exists.
# ---------------------------------------------------------------------------


def _exploding_complete(_messages: list) -> "ModelResponse":
    raise RuntimeError("engine exploded mid-drive")


def test_aborted_mock_run_still_carries_the_prompt_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``WorkAborted`` partial carries the digest of the prompt that ran."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_writer_overlay(repo, _OVERLAY_MARKER)

    task = Task.new(str(repo), "write the output file", engine="mock")
    cfg = EngineConfig(model=_MODEL)
    engine = MockEngine()
    composed = engine.system_prompt(task, cfg)
    assert composed is not None

    monkeypatch.setattr(mock_engine_mod, "_script", lambda _task: _exploding_complete)

    with pytest.raises(WorkAborted) as excinfo:
        engine.work(task, cfg)

    partial = excinfo.value.result
    assert partial.prompt_digest == hashlib.sha256(composed.encode("utf-8")).hexdigest()
    assert partial.to_dict()["prompt_digest"] == partial.prompt_digest


def test_aborted_vllm_run_still_carries_the_prompt_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All-engines rule: the live backend's aborted partial behaves identically."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_writer_overlay(repo, _OVERLAY_MARKER)

    task = Task.new(str(repo), "write the output file", engine="vllm-openai")
    cfg = EngineConfig(model=_MODEL)
    engine = VllmOpenAIEngine()
    composed = engine.system_prompt(task, cfg)
    assert composed is not None

    def _boom(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        raise RuntimeError("engine exploded mid-drive")

    monkeypatch.setattr(vllm_openai, "_post_json", _boom)

    with pytest.raises(WorkAborted) as excinfo:
        engine.work(task, cfg)

    partial = excinfo.value.result
    assert partial.prompt_digest == hashlib.sha256(composed.encode("utf-8")).hexdigest()
    assert partial.to_dict()["prompt_digest"] == partial.prompt_digest


def test_the_live_salvage_object_carries_the_prompt_digest_mid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interrupt-salvage path (#410) reads the LIVE result through
    ``salvage.peek`` while the loop is still running — so the digest must be
    on that object before the engine's post-return line ever executes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_writer_overlay(repo, _OVERLAY_MARKER)

    task = Task.new(str(repo), "write the output file", engine="mock")
    cfg = EngineConfig(model=_MODEL)
    engine = MockEngine()
    composed = engine.system_prompt(task, cfg)
    assert composed is not None

    seen: list = []

    def _peeking_script(inner_task: Task):
        def _complete(_messages: list) -> ModelResponse:
            live = salvage.peek(inner_task.id)
            seen.append(None if live is None else live.prompt_digest)
            raise RuntimeError("interrupted mid-drive")

        return _complete

    monkeypatch.setattr(mock_engine_mod, "_script", _peeking_script)

    with pytest.raises(WorkAborted):
        engine.work(task, cfg)

    assert seen == [hashlib.sha256(composed.encode("utf-8")).hexdigest()]


def test_an_aborted_run_with_no_composed_prompt_still_omits_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The byte-identical floor holds on the failure path too."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(MockEngine, "system_prompt", lambda self, task, config: None)
    monkeypatch.setattr(mock_engine_mod, "_script", lambda _task: _exploding_complete)

    engine = MockEngine()
    task = Task.new(str(repo), "x", engine="mock")
    cfg = EngineConfig(model=_MODEL)

    # Only the call under test sits inside `raises` — constructing the task or
    # config must not be able to satisfy the assertion (SonarCloud S5915).
    with pytest.raises(WorkAborted) as excinfo:
        engine.work(task, cfg)

    partial = excinfo.value.result
    assert partial.prompt_digest is None
    assert "prompt_digest" not in partial.to_dict()

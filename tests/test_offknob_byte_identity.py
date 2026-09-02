"""#484/#481/#482/#483 t11 — the all-off-knobs byte-identity sweep.

The small-fixes-then-effort-balance arc (``docs/specs/2026-09-01-small-fixes-
then-effort-balance.md``) landed four new surfaces, each with its own off-knob
(or, for the delta heartbeat, a documented claim that it needs none):

* ``COLLEAGUE_RECORD_TASK_TEXT=0`` — no ``task_text`` key (:mod:`colleague.tasktext`).
* ``COLLEAGUE_IMPORT_CHECK=0`` — no ``importcheck_report`` key, no import-check
  warning (:mod:`colleague.importcheck`).
* ``COLLEAGUE_EFFORT_SPIKES`` unset/``0`` — no ``effort_spikes`` key, no
  barrier/escalation behavior, no extra completion calls
  (:mod:`colleague.effortspikes`, :mod:`colleague.loop_barrier`).
* the delta heartbeat (:mod:`colleague.loop_deltaheartbeat`) — NO dedicated
  off-knob by design: it only ever writes to the flight-feed / progress sink,
  never the artifact or the wire. This module verifies that claim directly
  against the ``_emit_phase`` implementation rather than trusting the
  docstring.

Each existing per-surface test module (``test_contract_task_text.py``,
``test_importcheck.py``, ``test_barrier_pre_mutation.py``) already proves its
OWN knob is a no-op in isolation. What none of them prove is what this module
is for: that turning every knob off AT THE SAME TIME still reproduces the
exact pre-arc artifact/wire shape — and that no knob's suppression is
accidentally conditioned on another knob's state.

Baseline provenance (read this before touching the pinned literals below)
---------------------------------------------------------------------------
``BASELINE_KEYS`` is derived by running a real ``mock`` work item through
``registry.load("mock").work(...)`` with every off-knob set and taking
``sorted(result.to_dict().keys())`` — verified by hand against
``tests/test_e2e_mock.py::test_no_destination_drive_omits_destination_keys_byte_identical``'s
pinned key set (the pre-#481 "no destination" byte-identity guard) MINUS
``"task_text"`` (which that guard's baseline includes because task-text
recording is ON by default per decision c15 — turning the knob off is exactly
what removes it) and cross-checked against
``tests/test_result_fidelity.py::test_task_result_public_fields_unchanged``'s
pinned *dataclass field* list (a superset — that list names every field the
type can ever carry, including ones omitted-when-empty/None such as
``sub_results``, ``hires``, ``effort_spikes``, ``importcheck_report``,
``task_text`` itself). This literal is the pre-arc *serialized* contract for a
plain, unconfigured mock drive with nothing set up to trigger any optional
gate.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from colleague import registry
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.loop import ModelResponse, ToolCall, run
from colleague.loop_progress import delta_heartbeat
from colleague.loop_types import ContextControls, _Work
from colleague.tools import ToolExecutor

RECORD_TASK_TEXT_ENV = "COLLEAGUE_RECORD_TASK_TEXT"
IMPORT_CHECK_ENV = "COLLEAGUE_IMPORT_CHECK"
EFFORT_SPIKES_ENV = "COLLEAGUE_EFFORT_SPIKES"

#: The pinned pre-arc serialized key set for a plain, unconfigured mock drive.
#: See the module docstring's "Baseline provenance" section for how this was
#: derived and cross-checked. Change this ONLY alongside a re-derivation from
#: both sibling pins named above.
BASELINE_KEYS = {
    "task_id",
    "status",
    "summary",
    "changed_files",
    "steps",
    "usage",
    "stats",
    "finish_states",
    "artifacts_path",
    "error",
    "branch",
    "pr_url",
    "hook_firings",
    "command",
    "not_finished",
    "stopped_without_finish",
    "prompt_digest",
    "offered_tools",
    "effort",
    "sampling",
}


def _all_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RECORD_TASK_TEXT_ENV, "0")
    monkeypatch.setenv(IMPORT_CHECK_ENV, "0")
    monkeypatch.setenv(EFFORT_SPIKES_ENV, "0")


# ---------------------------------------------------------------------------
# 1. ARTIFACT byte-identity — a real mock work item, all off-knobs together.
# ---------------------------------------------------------------------------


class TestArtifactByteIdentity:
    def test_plain_drive_matches_the_pinned_pre_arc_key_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _all_off(monkeypatch)
        cfg = EngineConfig.resolve()

        result = registry.load("mock").work(Task.new(str(tmp_path), "do work"), cfg)

        assert result.status == OK
        serialized = result.to_dict()
        assert set(serialized.keys()) == BASELINE_KEYS
        # None of the arc's three new keys leaked through.
        assert "task_text" not in serialized
        assert "importcheck_report" not in serialized
        assert "effort_spikes" not in serialized
        # No new warning kind appeared either — a clean run carries none.
        assert serialized.get("warnings", []) in ([], None)

    def test_a_python_file_change_plus_a_mutation_still_matches_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stress case: a scripted run that reads, then writes a *clean,
        importable* ``.py`` file, then finishes. With every knob off this must
        STILL omit all three new keys — proving the omission isn't merely
        "nothing happened to trigger the gates" but "the gates were consulted
        and declined to record anything" (import-check would otherwise record
        a ``"passed"`` report even on success; the barrier would otherwise
        have interposed on the mutating write).
        """
        _all_off(monkeypatch)

        def script(_messages: list[dict]) -> ModelResponse:
            calls = script.calls
            script.calls += 1
            if calls == 0:
                return ModelResponse(
                    content="reading", tool_calls=[ToolCall("r1", "list_dir", {"path": "."})]
                )
            if calls == 1:
                return ModelResponse(
                    content="writing",
                    tool_calls=[
                        ToolCall(
                            "w1",
                            "write_file",
                            {"path": "mod.py", "content": "value = 42\n"},
                        )
                    ],
                )
            return ModelResponse(tool_calls=[ToolCall("f1", "finish", {"summary": "done"})])

        script.calls = 0

        task = Task.new(str(tmp_path), "add a module")
        result = run(script, task, max_steps=8)

        assert result.status == OK
        serialized = result.to_dict()
        assert "task_text" not in serialized
        assert "importcheck_report" not in serialized
        assert "effort_spikes" not in serialized
        # No barrier step was interposed — the tool sequence is exactly what
        # the script issued, nothing inserted.
        assert [s.tool for s in result.steps] == ["list_dir", "write_file", "finish"]


# ---------------------------------------------------------------------------
# 2. WIRE byte-identity — the all-knobs-together sweep over captured requests.
# ---------------------------------------------------------------------------


class _Script:
    """A scripted acting completion that records every request it was handed."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[list[dict]] = []

    def __call__(self, messages):
        self.requests.append(copy.deepcopy(messages))
        if not self.responses:
            return ModelResponse(content="(script exhausted)")
        return self.responses.pop(0)


def _turns():
    return [
        ModelResponse(content="reading", tool_calls=[ToolCall("r1", "list_dir", {"path": "."})]),
        ModelResponse(
            content="writing",
            tool_calls=[
                ToolCall("w1", "write_file", {"path": "mod.py", "content": "value = 42\n"})
            ],
        ),
        ModelResponse(tool_calls=[ToolCall("f1", "finish", {"summary": "done"})]),
    ]


def _scrub(requests: list[list[dict]], *repos: Path) -> list[list[dict]]:
    """Normalize away the one expected difference between two throwaway repos:
    their absolute paths appearing inside tool-call text."""
    out = requests
    for repo in repos:
        out = [
            [{k: str(v).replace(str(repo), "R") for k, v in m.items()} for m in req] for req in out
        ]
    return out


class TestWireByteIdentity:
    def test_all_off_knobs_produce_the_same_request_sequence_as_no_barrier_wiring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ALL-knobs-together sweep: ``test_barrier_pre_mutation.py``'s
        unarmed test already proves the spike knob alone is byte-identical;
        this test proves the same holds with the task-text and import-check
        knobs ALSO turned off in the same run — knobs can interact (a shared
        gate-dispatch seam, a shared env-read helper), so this is the
        combination the single-knob tests cannot catch.
        """
        _all_off(monkeypatch)
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()

        task_a = Task.new(str(repo_a), "add a module")
        controls_a = ContextControls(barrier_complete=lambda engine, warn: None)
        script_a = _Script(_turns())
        result_a = run(script_a, task_a, max_steps=8, context=controls_a)

        task_b = Task.new(str(repo_b), "add a module")
        script_b = _Script(_turns())
        result_b = run(script_b, task_b, max_steps=8)

        assert result_a.status == OK
        assert result_b.status == OK
        assert _scrub(script_a.requests, repo_a) == _scrub(script_b.requests, repo_b)
        # No extra completion call was made in either run (3 turns == 3 calls).
        assert len(script_a.requests) == len(script_b.requests) == 3


# ---------------------------------------------------------------------------
# 3. Knob independence — singly-off vs all-off, to catch a knob that only
#    suppresses its own key when it's the ONLY one turned off.
# ---------------------------------------------------------------------------


class TestKnobIndependence:
    @pytest.mark.parametrize(
        "task_text_off,import_check_off",
        [
            (True, False),
            (False, True),
            (True, True),
        ],
        ids=["task_text_only", "import_check_only", "both_off"],
    )
    def test_each_off_knob_suppresses_only_its_own_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        task_text_off: bool,
        import_check_off: bool,
    ) -> None:
        monkeypatch.setenv(RECORD_TASK_TEXT_ENV, "0" if task_text_off else "1")
        monkeypatch.setenv(IMPORT_CHECK_ENV, "0" if import_check_off else "1")
        monkeypatch.setenv(EFFORT_SPIKES_ENV, "0")

        def script(_messages: list[dict]) -> ModelResponse:
            calls = script.calls
            script.calls += 1
            if calls == 0:
                return ModelResponse(
                    content="writing",
                    tool_calls=[
                        ToolCall("w1", "write_file", {"path": "mod.py", "content": "value = 42\n"})
                    ],
                )
            return ModelResponse(tool_calls=[ToolCall("f1", "finish", {"summary": "done"})])

        script.calls = 0
        task = Task.new(str(tmp_path), "add a module")
        result = run(script, task, max_steps=8)

        serialized = result.to_dict()
        assert ("task_text" in serialized) is (not task_text_off)
        assert ("importcheck_report" in serialized) is (not import_check_off)
        # effort_spikes never appears regardless — the spike opt-in was never armed.
        assert "effort_spikes" not in serialized


# ---------------------------------------------------------------------------
# 4. Delta heartbeat (#483) — verify the "no artifact/wire effect" claim
#    directly against the implementation rather than trusting the docstring.
# ---------------------------------------------------------------------------


class TestDeltaHeartbeatNeverTouchesArtifactOrWire:
    def _bare_ctx(self, tmp_path: Path, progress=None) -> _Work:
        task = Task.new(str(tmp_path), "x")
        result = TaskResult(task_id=task.id, status="ok")
        return _Work(
            executor=ToolExecutor(str(tmp_path)),
            hooks=None,
            telemetry=None,
            task=task,
            result=result,
            messages=[{"role": "user", "content": "hi"}],
            max_steps=4,
            progress=progress,
        )

    def test_repeated_delta_arrival_never_mutates_result_or_messages(self, tmp_path: Path) -> None:
        ctx = self._bare_ctx(tmp_path)
        before_result = copy.deepcopy(ctx.result.to_dict())
        before_messages = copy.deepcopy(ctx.messages)
        before_step_count = ctx.result.stats.step_count

        beat = delta_heartbeat(ctx)
        for chunk in ("hello", " world", "", "more text", "even more"):
            beat(chunk)

        # ctx.flight is None here (no watchable flight) and ctx.progress is
        # None too — both legs of _emit_phase are strict no-ops, so nothing
        # about the artifact or the running history changed at all.
        assert ctx.result.to_dict() == before_result
        assert ctx.messages == before_messages
        assert ctx.result.stats.step_count == before_step_count
        assert "task_text" not in ctx.result.to_dict()
        assert "importcheck_report" not in ctx.result.to_dict()
        assert "effort_spikes" not in ctx.result.to_dict()

    def test_a_raising_progress_sink_is_suppressed_and_still_touches_nothing(
        self, tmp_path: Path
    ) -> None:
        def boom(*_a, **_k):
            raise RuntimeError("a raising sink must never propagate")

        ctx = self._bare_ctx(tmp_path, progress=boom)
        before_result = copy.deepcopy(ctx.result.to_dict())

        beat = delta_heartbeat(ctx)
        beat("a chunk")  # must not raise

        assert ctx.result.to_dict() == before_result

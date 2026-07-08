"""Drift test for docs/contract.md (S7, colleague#296): the doc is the source
of truth for the published artifact/feedback contract; a shape change in the
code that isn't mirrored in the doc must fail this test (and vice versa).

Builds a MAXIMAL ``TaskResult`` — every optional field set, every nested
dataclass populated — and asserts its ``to_dict()`` key sets (top-level and
every documented nested shape) match the ``<!-- contract:keys:NAME -->``
fenced blocks parsed out of ``docs/contract.md``. Also exercises the
``feedback`` record shape and the ``feedback export`` line shape the same way.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from colleague import feedback as fb
from colleague.affectedtests import AffectedTestsReport
from colleague.contract import (
    OK,
    SENSES_CHAT_KINDS,
    SENSES_LOOP_POINT_PREFIX,
    CapacityDecision,
    CoherenceReport,
    ContextPacket,
    DeepthinkCall,
    HookFiring,
    LintReport,
    SensesBlock,
    SensesRecord,
    Step,
    SubResult,
    TaskResult,
    Usage,
    WorkStats,
)
from colleague.testintegrity import MirrorFinding, TestIntegrityReport

CONTRACT_DOC = Path(__file__).resolve().parent.parent / "docs" / "contract.md"

_BLOCK_RE = re.compile(
    r"<!--\s*contract:keys:([a-zA-Z0-9_-]+)\s*-->\s*```text\n(.*?)```",
    re.DOTALL,
)


def _parse_key_blocks(doc_text: str) -> dict[str, set[str]]:
    """Every ``<!-- contract:keys:NAME -->`` fenced ``text`` block -> its key set."""
    blocks: dict[str, set[str]] = {}
    for name, body in _BLOCK_RE.findall(doc_text):
        keys = {line.strip() for line in body.splitlines() if line.strip()}
        assert name not in blocks, f"duplicate contract:keys block: {name}"
        blocks[name] = keys
    return blocks


@pytest.fixture(scope="module")
def doc_blocks() -> dict[str, set[str]]:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    blocks = _parse_key_blocks(text)
    # Sanity: the doc really contains fenced key blocks (a parsing regression
    # would otherwise make every assertion below vacuously pass on empty sets).
    assert len(blocks) >= 20, f"expected >=20 contract:keys blocks, found {sorted(blocks)}"
    return blocks


def _maximal_task_result() -> TaskResult:
    """A TaskResult with EVERY optional field set and every nested shape populated."""
    return TaskResult(
        task_id="max1",
        status=OK,
        summary="did everything",
        changed_files=["a.py"],
        steps=[Step(index=0, tool="write_file", arguments={"path": "a.py"}, result="wrote")],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        stats=WorkStats(
            request="do the thing",
            engine="mock",
            model="m1",
            started_at="2026-01-01T00:00:00+00:00",
            duration_seconds=1.5,
            model_turns=2,
            step_count=1,
            tool_counts={"write_file": 1},
            files_changed=1,
            bytes_written=100,
            reasoning_chars=10,
            reasoning_bytes=10,
            answer_chars=20,
            answer_bytes=20,
        ),
        artifacts_path=".colleague/max1.json",
        error=None,
        branch="colleague/max1",
        pr_url="https://github.com/x/y/pull/1",
        hook_firings=[
            HookFiring(
                event="pre_tool",
                tool="write_file",
                command="x",
                decision="allow",
                exit_code=0,
                reason="",
            )
        ],
        sub_results=[
            SubResult(
                task_id="sub1",
                engine="mock",
                model="m1",
                status=OK,
                summary="did sub",
                changed_files=["b.py"],
                usage=Usage(1, 1, 2),
                role="writer",
                parent="max1",
            )
        ],
        command="scaffold",
        destination="goal-frame",
        announcement="arrived",
        capacity_decision=CapacityDecision(kind="compact", reason="full"),
        capacity_warning="too big",
        lint_report=LintReport(fixed=["black"], residual=["flake8 x"], skipped=["ruff: missing"]),
        coherence_report=CoherenceReport(
            status="scored",
            reason="n/a",
            embed_url="http://localhost:8001/v1",
            embed_model="Qwen/Qwen3-Embedding-0.6B",
            files=[{"path": "docs/x.md", "meaning_score": 0.5}],
        ),
        test_integrity_report=TestIntegrityReport(
            findings=[
                MirrorFinding(symbol="x", kind="attribute", test_file="t.py", impl_file="i.py")
            ]
        ),
        affected_tests_report=AffectedTestsReport(
            status="passed", selected=["t.py"], total=1, capped=False, passed=1, failed=0
        ),
        not_finished=False,
        stopped_without_finish=False,
        role="writer",
        mode="work",
        acceptance_outcomes=[{"criterion": "c1", "met": True, "evidence": "e1"}],
        deepthink=[DeepthinkCall(point="tool", tokens=100, duration=1.2, degraded=False)],
        finish_recovered="literal-markup",
        memory={"query": "q", "recalled": 1, "injected_chars": 10, "lesson_recorded": True},
        media={"attachments": [{"path": "img.png", "status": "delivered"}]},
        senses=SensesBlock(
            mode="split",
            packet=ContextPacket(
                original="hi",
                interpretation="hello",
                confidence=0.9,
                task_type="bugfix",
                omissions=["x"],
            ),
            records=[SensesRecord(point="interpret", latency=0.5, tokens=50, degraded=False)],
            injections=[{"text": "go", "at": 1.0, "source": "operator"}],
            chat=[
                {
                    "message": "m",
                    "answer": "a",
                    "relay": True,
                    "relay_text": "r",
                    "latency": 0.1,
                    "degraded": False,
                    "at": 1.0,
                }
            ],
        ),
    )


def test_maximal_task_result_round_trips() -> None:
    """Sanity: the maximal fixture itself is a valid, lossless TaskResult."""
    result = _maximal_task_result()
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert reloaded == result


def test_top_level_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict().keys()) == doc_blocks["top-level"]


def test_stats_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["stats"].keys()) == doc_blocks["stats"]


def test_usage_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    d = result.to_dict()
    assert set(d["usage"].keys()) == doc_blocks["usage"]
    # Usage is the SAME shape nested inside a SubResult (cost is nested-only).
    assert set(d["sub_results"][0]["usage"].keys()) == doc_blocks["usage"]


def test_step_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["steps"][0].keys()) == doc_blocks["step"]


def test_hook_firing_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["hook_firings"][0].keys()) == doc_blocks["hook_firing"]


def test_sub_result_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["sub_results"][0].keys()) == doc_blocks["sub_result"]


def test_capacity_decision_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["capacity_decision"].keys()) == doc_blocks["capacity_decision"]


def test_lint_report_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["lint_report"].keys()) == doc_blocks["lint_report"]


def test_coherence_report_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["coherence_report"].keys()) == doc_blocks["coherence_report"]


def test_test_integrity_report_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    d = result.to_dict()
    assert set(d["test_integrity_report"].keys()) == doc_blocks["test_integrity_report"]
    assert set(d["test_integrity_report"]["findings"][0].keys()) == doc_blocks["mirror_finding"]


def test_affected_tests_report_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert (
        set(result.to_dict()["affected_tests_report"].keys()) == doc_blocks["affected_tests_report"]
    )


def test_acceptance_outcome_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert (
        set(result.to_dict()["acceptance_outcomes"][0].keys()) == doc_blocks["acceptance_outcome"]
    )


def test_deepthink_call_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["deepthink"][0].keys()) == doc_blocks["deepthink_call"]


def test_memory_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    assert set(result.to_dict()["memory"].keys()) == doc_blocks["memory"]


def test_media_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    d = result.to_dict()
    assert set(d["media"].keys()) == doc_blocks["media"]
    assert set(d["media"]["attachments"][0].keys()) == doc_blocks["media_attachment"]


def test_senses_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    result = _maximal_task_result()
    d = result.to_dict()
    assert set(d["senses"].keys()) == doc_blocks["senses"]
    assert set(d["senses"]["packet"].keys()) == doc_blocks["context_packet"]
    assert set(d["senses"]["records"][0].keys()) == doc_blocks["senses_record"]


def test_senses_chat_kind_vocabulary_matches_doc(doc_blocks: dict[str, set[str]]) -> None:
    """The documented ``chat[].kind`` vocabulary (presence-default-everywhere
    arc, task t3) matches the code's own closed set exactly — the SAME
    vocabulary every front (session, talk attach, background, resident, the
    senses coordination loop) must reuse, never a front-specific kind."""
    assert set(SENSES_CHAT_KINDS) == doc_blocks["senses_chat_kind"]


def test_senses_loop_point_prefix_is_documented(doc_blocks: dict[str, set[str]]) -> None:
    """``docs/contract.md`` names the exact ``SENSES_LOOP_POINT_PREFIX`` string
    (not just the constant's existence) so a reader of the published contract
    can recognise a senses-loop turn's ``records[].point`` without reading the
    source."""
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    assert SENSES_LOOP_POINT_PREFIX in text


def test_feedback_record_keys_match_doc(doc_blocks: dict[str, set[str]]) -> None:
    record = fb.Feedback(task_id="t1", rating=4, notes="n", by="ori", at="2026-01-01T00:00:00Z")
    assert set(record.to_dict().keys()) == doc_blocks["feedback"]


def test_export_line_keys_match_doc(tmp_path: Path, doc_blocks: dict[str, set[str]]) -> None:
    """The ACTUAL export-line dict (not a hand-built one) matches the doc."""
    repo = tmp_path / "repo"
    repo.mkdir()
    adir = repo / ".colleague"
    adir.mkdir()
    (adir / "w1.json").write_text(
        json.dumps(
            {
                "task_id": "w1",
                "status": OK,
                "summary": "did it",
                "changed_files": [],
                "steps": [],
                "usage": {},
                "stats": {
                    "request": "do x",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "step_count": 3,
                    "files_changed": 1,
                    "bytes_written": 42,
                },
            }
        ),
        encoding="utf-8",
    )
    fb.write_feedback(repo, "w1", rating=4, notes="solid", by="ori")

    rows = fb.export_work_items(repo)
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == doc_blocks["export_line"]
    assert set(row["stats"].keys()) == doc_blocks["export_line_stats"]

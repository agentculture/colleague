"""#411 t21 — continuity regression for the agents mode (c44 / h31).

Three pins, each on a REAL armed loop (``.colleague/config.json {"agents":
true}`` → ``EngineConfig.resolve`` → ``loop.run(..., context=...)``):

1. **SIGTERM-resume equality.** An armed run parked in a never-yielding
   completion (a real ``os.pipe`` read — never a fake stream that returns, see
   the repo's fake-streams gotcha) receives SIGTERM → the #410 salvage writes
   the artifact AND the task ledger survives on disk; ``work --continue``'s
   lane (``resolve_continuation(..., agents_armed=True)`` + t17's
   ``rehydrate_snapshot``) rehydrates a snapshot EQUAL to the pre-cut snapshot
   on ``changed_paths`` / ``open_loops`` / ``acceptance`` /
   ``authority_digest`` — 0 lost — and the seed names every item.
2. **Compaction drops 0 ledger state.** A fill-line ``compact`` during an armed
   run rewrites only the transcript: every ``plan_node`` and ``changed_path``
   event recorded before the compaction is still on the ledger afterwards,
   byte-for-byte, as a prefix of the final event sequence (append-only), and
   the run completes.
3. **Manifest audit.** The tests-side helper :mod:`tests._agents_audit`
   (NOT a CLI verb) reports ``max(token_estimate) / advertised_context`` over
   a run; the scripted armed run sits well under the 0.5 line against the
   budget it ran with. t23 (the live proof) imports the same helper.
"""

from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path

import pytest

from colleague import loop, salvage
from colleague.agents.runtime import InvocationRecord, make_agents_run
from colleague.agents.state import TaskLedger, ledger_path, read_ledger
from colleague.artifact import artifact_dir
from colleague.cli._commands.work import _arm_interrupt_commit, _make_salvage_writer
from colleague.config import EngineConfig
from colleague.continuation import rehydrate_snapshot, resolve_continuation
from colleague.contract import ERROR, OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall
from tests._agents_audit import (
    audit_report,
    invocations_of,
    manifest_ratio,
    max_token_estimate,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _arm_repo(tmp_path: Path) -> tuple[Path, EngineConfig]:
    repo = tmp_path / "repo"
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / "config.json").write_text(json.dumps({"agents": True}), encoding="utf-8")
    cfg = EngineConfig.resolve(repo_path=repo, discover_lobes=False)
    assert cfg.agents is True
    return repo, cfg


@pytest.fixture()
def armed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    return _arm_repo(tmp_path)


def _has(messages, needle: str) -> bool:
    return any(needle in (m.get("content") or "") for m in messages)


def _finish(summary: str = "done", **usage) -> ModelResponse:
    return ModelResponse(
        content=summary, tool_calls=[ToolCall("f", "finish", {"summary": summary})], **usage
    )


def _list_dir(**usage) -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("l", "list_dir", {"path": "."})], **usage)


def _write(path: str, **usage) -> ModelResponse:
    return ModelResponse(
        tool_calls=[ToolCall("w", "write_file", {"path": path, "content": "seeded\n"})],
        **usage,
    )


def _artifact_json(repo: Path, task_id: str) -> dict:
    files = [
        p
        for p in artifact_dir(repo).glob(f"{task_id}*.json")
        if not p.name.endswith(".trace.jsonl")
    ]
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _continuity_view(snapshot) -> dict:
    """The four continuity fields the t21 acceptance compares (0 lost)."""
    return {
        "changed_paths": tuple(snapshot.changed_paths),
        "open_loops": tuple(
            tuple(sorted(loop_.items())) for loop_ in snapshot.open_loops
        ),  # hashable, order-preserving
        "acceptance": tuple(tuple(sorted(a.items())) for a in snapshot.acceptance),
        "authority_digest": snapshot.authority_digest,
    }


# ---------------------------------------------------------------------------
# 1. SIGTERM-resume equality (real os.pipe)
# ---------------------------------------------------------------------------


def test_sigterm_resume_rehydrates_the_pre_cut_snapshot_with_zero_loss(armed) -> None:
    repo, cfg = armed
    task = Task.new(
        str(repo),
        "hang forever on the wire (armed)",
        constraints=["stdlib only"],
        acceptance=["tests pass", "docs updated"],
    )
    controls = ContextControls.from_config(cfg)
    run = controls.agents_run
    assert run is not None
    rfd, wfd = os.pipe()
    calls = {"n": 0}
    pre_cut: dict = {}
    seeded_events: list = []

    def complete(_messages):
        calls["n"] += 1
        if calls["n"] == 1:
            # The run has begun (ledger open, request/constraints/acceptance
            # seeded). Lay down the state a cut must never lose: a plan node,
            # an open loop and a changed path — then the PRE-CUT snapshot.
            ledger = run.ledger
            assert isinstance(ledger, TaskLedger)  # appended via TaskLedger, as the brief asks
            seeded_events.append(
                ledger.append("plan_node", {"id": "p1", "text": "wire the continuity test"})
            )
            seeded_events.append(
                ledger.append("open_loop", {"id": "l1", "text": "verify the SIGTERM lane"})
            )
            seeded_events.append(ledger.append("changed_path", {"path": "colleague/loop.py"}))
            pre_cut["snapshot"] = read_ledger(ledger_path(repo, task.id)).snapshot
            return _list_dir()
        os.read(rfd, 1)  # parks the main thread in a real blocking read
        raise AssertionError("unreachable: the signal must unwind the read")

    restore = _arm_interrupt_commit(
        None,
        salvage_write=_make_salvage_writer(
            task, repo, command_name=None, mode=None, continued_from=None
        ),
    )
    timer = threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.daemon = True
    try:
        timer.start()
        with pytest.raises(SystemExit) as excinfo:
            loop.run(complete, task, max_steps=4, context=controls)
        assert excinfo.value.code == 128 + signal.SIGTERM
    finally:
        restore()
        timer.cancel()
        os.close(rfd)
        os.close(wfd)

    assert calls["n"] == 2  # the seeding turn, then the blocked turn
    # (t5) the salvaged artifact exists and says what happened
    data = _artifact_json(repo, task.id)
    assert data["status"] == ERROR
    assert data["incompletion"]["reason"] == "interrupted"
    assert salvage.peek(task.id) is None
    # AND the task ledger exists at the operator repo
    path = ledger_path(repo, task.id)
    assert path.is_file()

    # work --continue's lane: armed + readable ledger → the ledger seed, no warning
    warnings: list[dict] = []
    task_id, seed = resolve_continuation(repo, task.id, agents_armed=True, warnings=warnings)
    assert task_id == task.id and warnings == []
    assert seed.startswith(f"You are CONTINUING work item {task.id}")
    assert "hang forever on the wire (armed)" in seed  # the request, verbatim

    # rehydrated snapshot == pre-cut snapshot on the four continuity fields
    before = pre_cut["snapshot"]
    after = rehydrate_snapshot(repo, task.id)
    assert after is not None
    assert _continuity_view(after) == _continuity_view(before)
    lost = (
        (set(before.changed_paths) - set(after.changed_paths))
        | (
            {loop_["id"] for loop_ in before.open_loops}
            - {loop_["id"] for loop_ in after.open_loops}
        )
        | ({a["text"] for a in before.acceptance} - {a["text"] for a in after.acceptance})
    )
    assert lost == set(), lost
    assert before.changed_paths == ("colleague/loop.py",)
    assert [loop_["id"] for loop_ in before.open_loops] == ["l1"]
    assert [a["text"] for a in before.acceptance] == ["tests pass", "docs updated"]
    assert before.authority_digest and after.authority_digest == before.authority_digest
    # the plan node rode along too (the same replay, the same ledger)
    assert [p["id"] for p in after.plan] == ["p1"]
    # the seeded events are byte-identical on the surviving ledger
    survivors = {e.seq: e for e in read_ledger(path).events}
    for event in seeded_events:
        assert survivors[event.seq].canonical() == event.canonical()

    # ...and the seed names every one of them
    assert "`colleague/loop.py`" in seed
    assert "[l1] verify the SIGTERM lane" in seed
    assert "tests pass" in seed and "docs updated" in seed
    assert "stdlib only" in seed
    assert f"authority_digest: `{after.authority_digest}`" in seed


# ---------------------------------------------------------------------------
# 2. A fill-line compaction drops 0 plan nodes / changed paths
# ---------------------------------------------------------------------------


def test_fillline_compaction_leaves_every_plan_node_and_changed_path(armed) -> None:
    repo, cfg = armed
    task = Task.new(str(repo), "do a long armed thing")
    run = make_agents_run(cfg)
    assert run is not None
    # A tiny budget + the 0.8 line: the first working turn (prompt_tokens 90)
    # crosses, the fill-line offers, the model declares COMPACT.
    controls = ContextControls(
        budget=100, fillline_threshold=0.8, agents_run=run, autosplit_target=100
    )
    calls: list[list] = []
    before_compaction: dict = {}

    def complete(messages):
        calls.append(list(messages))
        if _has(messages, "Summarize everything done"):
            # The compaction turn: the transcript is about to be rewritten —
            # capture the ledger as it stands RIGHT NOW.
            before_compaction["events"] = read_ledger(run.ledger_path).events
            return ModelResponse(
                content="COMPACT SUMMARY: wrote notes.txt; plan p1/p2 in flight; remains finish",
                prompt_tokens=5,
                completion_tokens=5,
            )
        if _has(messages, "declare ONE move"):
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            ledger = run.ledger
            assert ledger is not None
            ledger.append("plan_node", {"id": "p1", "text": "write the note"})
            ledger.append("plan_node", {"id": "p2", "text": "finish cleanly"})
            ledger.append("changed_path", {"path": "docs/seeded.md"})
            # Crosses the fill line (90 >= 0.8 * 100) while writing a real file.
            return _write("notes.txt", prompt_tokens=90, completion_tokens=1)
        return _finish(prompt_tokens=5, completion_tokens=1)

    result = loop.run(complete, task, max_steps=10, context=controls)
    assert result.status == OK
    assert result.capacity_decision is not None and result.capacity_decision.kind == "compact"
    # the transcript WAS compacted (the final turn ran on head + the summary)
    final = calls[-1]
    assert any((m.get("content") or "").startswith("[Compacted summary") for m in final)
    assert not any(m.get("role") == "tool" for m in final)
    assert (repo / "notes.txt").is_file()

    # ...but the ledger lost nothing: every pre-compaction event is still there,
    # byte-identical, as a PREFIX of the final sequence (append-only).
    pre = before_compaction["events"]
    assert pre, "the compaction turn must have seen a populated ledger"
    post = read_ledger(run.ledger_path).events
    assert len(post) >= len(pre)
    assert [e.canonical() for e in post[: len(pre)]] == [e.canonical() for e in pre]
    pre_plan = [e for e in pre if e.kind == "plan_node"]
    pre_changed = [e for e in pre if e.kind == "changed_path"]
    assert [e.data["id"] for e in pre_plan] == ["p1", "p2"]
    assert [e.data["path"] for e in pre_changed] == ["docs/seeded.md"]
    dropped_plan = {e.canonical() for e in pre_plan} - {
        e.canonical() for e in post if e.kind == "plan_node"
    }
    dropped_changed = {e.canonical() for e in pre_changed} - {
        e.canonical() for e in post if e.kind == "changed_path"
    }
    assert dropped_plan == set() and dropped_changed == set()
    # the replayed snapshot agrees: both plan nodes, the seeded path AND the
    # real write (folded at end) — the compaction touched only the transcript
    snapshot = rehydrate_snapshot(repo, task.id)
    assert snapshot is not None
    assert [p["id"] for p in snapshot.plan] == ["p1", "p2"]
    assert set(snapshot.changed_paths) == {"docs/seeded.md", "notes.txt"}
    assert result.agents is not None and result.agents["ledger_digest"] == snapshot.state_digest


# ---------------------------------------------------------------------------
# 3. The manifest audit helper (tests-side, imported by t23)
# ---------------------------------------------------------------------------


def test_scripted_armed_run_manifest_ratio_is_under_half(armed) -> None:
    repo, cfg = armed
    task = Task.new(str(repo), "audit the manifest of a scripted armed run")
    controls = ContextControls.from_config(cfg)
    advertised = controls.budget or cfg.context_budget_tokens
    assert advertised and advertised > 0
    script = iter([_list_dir(), _finish()])
    result = loop.run(lambda _m: next(script), task, max_steps=4, context=controls)
    assert result.status == OK
    invocations = result.agents["invocations"]
    assert len(invocations) == 2 and all(i["token_estimate"] > 0 for i in invocations)

    ratio = manifest_ratio(result, advertised)
    assert 0.0 < ratio < 0.5, (ratio, advertised)
    assert manifest_ratio(result.agents, advertised) == ratio  # block or result: same
    assert manifest_ratio(invocations, advertised) == ratio  # or the raw list
    report = audit_report(result, advertised)
    assert report["count"] == 2 and report["ratio"] == ratio
    assert report["max_token_estimate"] == max(i["token_estimate"] for i in invocations)
    assert report["advertised_context"] == advertised
    assert report["truncated"] == 0 and report["sources"] == ["chars"]
    assert report["over_half"] is False and report["over"] is False
    # the estimate never reaches Usage (exact tokens only)
    assert result.usage.total_tokens == 0


def _record(estimate: int, source: str, *, truncated: bool = False) -> InvocationRecord:
    return InvocationRecord(
        agent_id="a",
        purpose="thinker_coder",
        model_role="cortex",
        resolved_model="m",
        fallback_from_role=None,
        tool_surface_digest="d",
        ledger_digest="",
        token_estimate=estimate,
        token_estimate_source=source,
        truncated=truncated,
    )


def test_audit_helper_accepts_records_blocks_and_empties() -> None:
    records = [_record(300, "chars"), _record(700, "tokenize", truncated=True)]
    assert max_token_estimate(records) == 700
    assert manifest_ratio(records, 1000) == 0.7
    assert manifest_ratio({"invocations": [r.to_dict() for r in records]}, 1400) == 0.5
    assert len(invocations_of([r.to_dict() for r in records])) == 2
    report = audit_report(records, 1000)
    assert report["count"] == 2 and report["truncated"] == 1
    assert report["sources"] == ["chars", "tokenize"]
    assert report["over_half"] is True and report["over"] is False
    assert audit_report(records, 500)["over"] is True
    # empties: no invocations = ratio 0, never a crash
    assert manifest_ratio(None, 100) == 0.0
    assert manifest_ratio([], 100) == 0.0
    assert manifest_ratio({"invocations": []}, 100) == 0.0
    assert audit_report(None, 100)["count"] == 0
    # a non-positive window is a caller error, never a silent inf
    with pytest.raises(ValueError):
        manifest_ratio(records, 0)

"""Proactive fill-line capacity decision (#156): pure helpers + loop integration.

Covers plan targets c4/h2/h11 (the trigger records exactly one declared move,
byte-identical no-op otherwise), c10/h3 (self-compaction: a model-authored summary
replaces the elided turns, head preserved, lossy-windowing fallback on overflow),
c11 (a split declaration routes through the existing subagents path), and c12 (a
finish-with-handoff declaration preserves a continuation summary).

Indefinite-run t1 (c3/h3) supersedes the v1 once-per-work-item limit: the decision
is offered per CROSSING (a resolved offer re-arms once the run drops back under the
line), bounded by the per-run compaction cap
(``fillline.DEFAULT_COMPACTION_CAP``) — the cap reached = no further offers,
recorded on the trace (``capacity_warning``).

Indefinite-run t2 (c4/h4) adds deterministic compaction validation: the MAIN
model's summary is cross-checked against the run's own evidence (goal/original
request + changed-file paths) and repaired deterministically
(``fillline.validate_compaction`` — no second-model call, non-goal c12); an
empty/whitespace summary is REJECTED and never replaces history — armed
(``ContextControls.chain_armed``) the loop takes FINISH-WITH-HANDOFF (decision
c23), unarmed it keeps today's lossy-windowing floor.
"""

from __future__ import annotations

from pathlib import Path

from colleague import fillline
from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_SYS = "You are a test coding agent."
_OVERFLOW = "This model's maximum context length is 4096 tokens"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_armed_requires_budget_and_threshold() -> None:
    assert fillline.armed(100, 0.8) is True
    assert fillline.armed(None, 0.8) is False
    assert fillline.armed(0, 0.8) is False
    assert fillline.armed(100, 0) is False
    assert fillline.armed(100, 1.5) is False


def test_crossed() -> None:
    assert fillline.crossed(80, 100, 0.8) is True
    assert fillline.crossed(79, 100, 0.8) is False


def test_classify_declaration() -> None:
    assert fillline.classify_declaration(["subagents"]) == fillline.MOVE_SPLIT
    assert fillline.classify_declaration(["subagent"]) == fillline.MOVE_SPLIT
    assert fillline.classify_declaration(["finish"]) == fillline.MOVE_HANDOFF
    assert fillline.classify_declaration([]) == fillline.MOVE_COMPACT
    assert fillline.classify_declaration(["read_file"]) == fillline.MOVE_COMPACT


def test_build_decision_prompt_names_all_three_moves() -> None:
    body = fillline.build_decision_prompt(
        used_tokens=200, budget_tokens=250, per_child_budget_tokens=250, max_children=3
    )
    assert "COMPACT" in body
    assert "SPLIT" in body
    assert "FINISH-WITH-HANDOFF" in body
    assert "subagents" in body
    assert "200" in body and "250" in body and "3" in body


def test_default_compaction_cap_and_cap_reached() -> None:
    """The per-run compaction cap is a module constant (t3 owns the config knob) and
    ``cap_reached`` follows the 0-is-unlimited convention (indefinite-run t1)."""
    assert fillline.DEFAULT_COMPACTION_CAP == 4
    assert fillline.cap_reached(0, 4) is False
    assert fillline.cap_reached(3, 4) is False
    assert fillline.cap_reached(4, 4) is True
    assert fillline.cap_reached(5, 4) is True
    # cap <= 0 = no cap (the 0-is-unlimited chain-knob convention) — never reached.
    assert fillline.cap_reached(100, 0) is False
    assert fillline.cap_reached(100, -1) is False


def test_apply_compaction_preserves_head_and_replaces_tail() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "original assignment"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "tool result", "tool_call_id": "1"},
    ]
    out = fillline.apply_compaction(messages, "did A and B; remains C")
    assert out[0] == messages[0]  # system preserved
    assert out[1] == messages[1]  # original assignment preserved
    assert len(out) == 3
    assert out[2]["content"].startswith("[Compacted summary")
    assert "did A and B" in out[2]["content"]
    # The elided working turns (assistant tool_calls + tool reply) are gone.
    assert not any(m.get("role") == "tool" for m in out)


# ---------------------------------------------------------------------------
# Loop integration
# ---------------------------------------------------------------------------


def _task(tmp_path: Path) -> Task:
    return Task.new(str(tmp_path), "do a long thing", engine="mock")


def _run(complete, task, **kwargs):
    cc = ContextControls(
        budget=kwargs.pop("budget", 100),
        count_tokens=kwargs.pop("count_tokens", None),
        autosplit_target=kwargs.pop("autosplit_target", 100),
        fillline_threshold=kwargs.pop("fillline_threshold", 0.8),
        chain_armed=kwargs.pop("chain_armed", False),
    )
    kwargs.setdefault("system_prompt", _SYS)
    kwargs.setdefault("max_steps", 10)
    return run(complete, task, context=cc, **kwargs)


def _has(messages, needle: str) -> bool:
    return any(needle in (m.get("content") or "") for m in messages)


def _offers_seen(calls: list[list]) -> int:
    """Count the completions whose LAST message is the fill-line decision prompt.

    The offer is always appended immediately before the declaring completion (and a
    compaction then elides it from later histories), so this counts distinct offers
    the model actually saw.
    """
    return sum(1 for msgs in calls if "declare ONE move" in (msgs[-1].get("content") or ""))


def test_no_fillline_event_is_byte_identical_noop(tmp_path) -> None:
    """A work item whose context never crosses the line records no decision (#156, h2)."""

    def complete(messages):
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=10,  # well under 0.8 * 100
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is None
    assert "capacity_decision" not in result.to_dict()
    assert "capacity_warning" not in result.to_dict()


def test_compact_branch_summarizes_and_preserves_head(tmp_path) -> None:
    """A COMPACT declaration records the move and replaces elided turns with a
    model-authored summary; messages[:2] survive (#156, c10/h3)."""
    calls: list[list] = []

    def complete(messages):
        calls.append(list(messages))
        if _has(messages, "Summarize everything done"):
            return ModelResponse(
                content="COMPACT SUMMARY: read foo.py; remains bar",
                prompt_tokens=5,
                completion_tokens=5,
            )
        if _has(messages, "declare ONE move"):
            # Declare COMPACT: reply without a tool call.
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            # First working turn crosses the fill line (prompt_tokens 90 >= 0.8*100).
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        # After compaction: finish.
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("2", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    assert "fill line" in result.capacity_decision.reason
    # The final (finish) turn ran against head + the model-authored summary only.
    final = calls[-1]
    assert final[0]["role"] == "system"  # messages[:2] preserved (head)
    assert any(
        (m.get("content") or "").startswith("[Compacted summary") for m in final
    ), "compacted summary must replace the elided turns"
    assert _has(final, "COMPACT SUMMARY: read foo.py")  # model-authored content present
    assert not any(m.get("role") == "tool" for m in final)  # working history elided


def test_compact_overflow_falls_back_to_windowing(tmp_path) -> None:
    """If the summarization turn itself overflows, compaction falls back to lossy
    windowing rather than aborting — degradation is the documented floor (#156, h3)."""
    calls: list[int] = []

    def complete(messages):
        calls.append(1)
        if _has(messages, "Summarize everything done"):
            raise RuntimeError(_OVERFLOW)  # the summary turn cannot fit
        if _has(messages, "declare ONE move"):
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("2", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(
        complete,
        _task(tmp_path),
        count_tokens=lambda msgs: sum(len(m.get("content") or "") for m in msgs),
    )
    # The run completed (no abort) and the decision was still recorded as compact.
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"


def test_compact_with_tool_calls_does_not_discard_them(tmp_path) -> None:
    """A compact declaration that ALSO makes a working tool call still runs it —
    the tool call is not silently discarded (Qodo bug 1)."""
    calls: list[int] = []

    def complete(messages):
        calls.append(1)
        if _has(messages, "Summarize everything done"):
            return ModelResponse(content="SUMMARY of work", prompt_tokens=5, completion_tokens=5)
        if _has(messages, "declare ONE move"):
            # Declare compact, but the same turn also writes a file (keeps working).
            return ModelResponse(
                content="compacting and writing",
                tool_calls=[ToolCall("w", "write_file", {"path": "marker.txt", "content": "hi"})],
                prompt_tokens=85,
                completion_tokens=1,
            )
        if len(calls) == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    # The declaring turn's write_file actually ran — the file exists and is tracked.
    assert (tmp_path / "marker.txt").exists()
    assert "marker.txt" in result.changed_files


def test_split_declaration_records_split(tmp_path) -> None:
    """A SPLIT declaration (subagents call) is recorded as kind 'split' (#156, c11)."""

    def complete(messages):
        if _has(messages, "declare ONE move"):
            return ModelResponse(
                content="splitting",
                tool_calls=[ToolCall("s", "subagents", {"tasks": []})],
                prompt_tokens=85,
                completion_tokens=1,
            )
        if not _has(messages, "list_dir-done-marker"):
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "split"


def test_finish_with_handoff_declaration_preserves_continuation(tmp_path) -> None:
    """A FINISH-WITH-HANDOFF declaration records the move and the continuation
    summary is preserved on the result (#156, c12)."""

    def complete(messages):
        if _has(messages, "declare ONE move"):
            return ModelResponse(
                content="handing off",
                tool_calls=[ToolCall("f", "finish", {"summary": "DONE: A,B  REMAINS: C,D"})],
                prompt_tokens=85,
                completion_tokens=1,
            )
        return ModelResponse(
            content="",
            tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
            prompt_tokens=90,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "finish-with-handoff"
    assert result.summary == "DONE: A,B  REMAINS: C,D"


# ---------------------------------------------------------------------------
# Per-crossing re-arm + compaction cap (indefinite-run t1, c3/h3)
# ---------------------------------------------------------------------------


def test_second_crossing_after_resolved_compact_offers_again(tmp_path) -> None:
    """After a resolved compact, a SECOND threshold crossing offers the fill-line
    decision again — per-crossing re-arm, superseding the v1 once-per-work-item
    limit (indefinite-run t1, c3)."""
    calls: list[list] = []
    work = {"n": 0}
    summaries = {"n": 0}

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            summaries["n"] += 1
            return ModelResponse(
                content=f"SUMMARY {'ONE' if summaries['n'] == 1 else 'TWO'}",
                prompt_tokens=5,
                completion_tokens=5,
            )
        if "declare ONE move" in last:
            # Declare COMPACT: reply without a tool call.
            return ModelResponse(content="compacting", prompt_tokens=90, completion_tokens=1)
        work["n"] += 1
        if work["n"] == 1:  # first crossing (>= 0.8 * 100)
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        if work["n"] == 2:  # post-compaction turn drops BACK UNDER the line → re-arm
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("2", "list_dir", {"path": "."})],
                prompt_tokens=20,
                completion_tokens=1,
            )
        if work["n"] == 3:  # second crossing
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("3", "list_dir", {"path": "."})],
                prompt_tokens=95,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path), max_steps=20)
    assert result.status == OK
    assert _offers_seen(calls) == 2  # the second crossing offered the decision again
    # The recorded (singular) decision reflects the LATEST crossing's own numbers —
    # the used-tokens cell was reset with the re-arm.
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    assert "95" in result.capacity_decision.reason
    # The second compaction's summary replaced the history; the first is elided.
    final = calls[-1]
    assert _has(final, "SUMMARY TWO")
    assert not _has(final, "SUMMARY ONE")


def test_no_reoffer_while_still_over_the_line(tmp_path) -> None:
    """A resolved compact whose follow-up turns STAY over the line never immediately
    re-offers: the re-arm requires the run to drop back under the line first — one
    offer per crossing, not one per over-the-line turn (indefinite-run t1, h3)."""
    calls: list[list] = []
    work = {"n": 0}

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            return ModelResponse(content="SUMMARY", prompt_tokens=5, completion_tokens=5)
        if "declare ONE move" in last:
            return ModelResponse(content="compacting", prompt_tokens=90, completion_tokens=1)
        work["n"] += 1
        if work["n"] <= 3:  # first crossing, then two post-compact turns STILL over
            return ModelResponse(
                content="",
                tool_calls=[ToolCall(str(work["n"]), "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=90,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path), max_steps=20)
    assert result.status == OK
    assert _offers_seen(calls) == 1  # never re-offered without a dip under the line


def test_split_declaration_rearms_without_consuming_compaction_cap(tmp_path) -> None:
    """The re-arm applies to ANY resolved declaration, and only compaction turns
    count against the cap: a resolved SPLIT followed by a dip under the line lets a
    second crossing offer again, which can still declare COMPACT (t1, c3/h3)."""
    calls: list[list] = []
    work = {"n": 0}

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            return ModelResponse(content="SUMMARY", prompt_tokens=5, completion_tokens=5)
        if "declare ONE move" in last:
            if _offers_seen(calls) == 1:  # first offer: declare SPLIT
                return ModelResponse(
                    content="splitting",
                    tool_calls=[ToolCall("s", "subagents", {"tasks": []})],
                    prompt_tokens=90,
                    completion_tokens=1,
                )
            # Second offer: declare COMPACT.
            return ModelResponse(content="compacting", prompt_tokens=90, completion_tokens=1)
        work["n"] += 1
        if work["n"] == 1:  # first crossing
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        if work["n"] == 2:  # dip back under the line → re-arm
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("2", "list_dir", {"path": "."})],
                prompt_tokens=20,
                completion_tokens=1,
            )
        if work["n"] == 3:  # second crossing
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("3", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path), max_steps=20)
    assert result.status == OK
    assert _offers_seen(calls) == 2
    # The latest declaration wins the singular field; the split never counted
    # against the compaction cap (the compact still ran).
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    assert result.capacity_warning is None  # cap never reached — nothing recorded


def test_compaction_cap_suppresses_further_offers_and_is_recorded(tmp_path) -> None:
    """The per-run compaction cap bounds total compaction turns: the crossing after
    the cap-th compaction gets NO offer, and the suppression is recorded ONCE on
    ``capacity_warning`` (the trace) — never silent (indefinite-run t1, h3)."""
    calls: list[list] = []
    work = {"n": 0}
    # 4 full compact cycles (cross → offer → compact → dip re-arms), then TWO more
    # over-the-line turns: the 5th crossing must get no offer (cap = 4 reached) and
    # the 6th proves the cap note records once, not per crossing.
    tokens = iter([90, 20, 90, 20, 90, 20, 90, 20, 90, 90])

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            return ModelResponse(content="S", prompt_tokens=5, completion_tokens=5)
        if "declare ONE move" in last:
            return ModelResponse(content="compacting", prompt_tokens=90, completion_tokens=1)
        tok = next(tokens, None)
        if tok is None:
            return ModelResponse(
                content="done",
                tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
                prompt_tokens=5,
                completion_tokens=1,
            )
        work["n"] += 1
        return ModelResponse(
            content="",
            tool_calls=[ToolCall(str(work["n"]), "list_dir", {"path": "."})],
            prompt_tokens=tok,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path), max_steps=30)
    assert result.status == OK
    # Exactly the cap's worth of offers — the 5th crossing was suppressed.
    assert _offers_seen(calls) == fillline.DEFAULT_COMPACTION_CAP
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    # The suppression is on the trace, once (not re-recorded by the 6th crossing).
    assert result.capacity_warning is not None
    assert "compaction cap" in result.capacity_warning
    assert result.capacity_warning.count("compaction cap") == 1


# ---------------------------------------------------------------------------
# Deterministic compaction validation (indefinite-run t2, c4) — pure validator
# ---------------------------------------------------------------------------


def test_validate_compaction_rejects_only_empty_or_whitespace() -> None:
    """Rejection is reserved for the uncoverable case — an empty/whitespace note
    (c4/h4). Any non-empty summary is repairable, so it is repaired, never rejected."""
    assert fillline.validate_compaction("", "some goal", ["a.py"]) == ("", False)
    assert fillline.validate_compaction("   \n\t ", "some goal", ["a.py"]) == ("", False)
    assert fillline.validate_compaction(None, "some goal", ["a.py"]) == ("", False)
    # A bare non-empty token is never rejected — it gets the evidence appended.
    text, ok = fillline.validate_compaction("x", "some goal", ["a.py"])
    assert ok is True
    assert "some goal" in text and "a.py" in text


def test_validate_compaction_passes_complete_summary_unchanged() -> None:
    """A summary already carrying the goal and every changed-file path passes
    through byte-identical — no evidence block, no rewriting (c4)."""
    summary = "Did the long thing; edited a.py and b.py; remains: the docs."
    text, ok = fillline.validate_compaction(summary, "the long thing", ["a.py", "b.py"])
    assert ok is True
    assert text == summary


def test_validate_compaction_appends_only_missing_facts() -> None:
    """Repair is additive and deterministic: the original text is preserved verbatim
    and ONLY the missing facts (goal + absent changed paths) are appended (c4)."""
    summary = "Edited a.py; more to do."
    text, ok = fillline.validate_compaction(summary, "refactor the parser", ["a.py", "b.py"])
    assert ok is True
    assert text.startswith(summary)
    assert "refactor the parser" in text
    assert "b.py" in text
    # The already-present path is not re-listed in the appended evidence block.
    appended = text[len(summary) :]
    assert "a.py" not in appended
    # Deterministic: same inputs, same output.
    assert fillline.validate_compaction(summary, "refactor the parser", ["a.py", "b.py"]) == (
        text,
        True,
    )


def test_validate_compaction_goal_heuristic_first_line_case_insensitive() -> None:
    """The goal-presence check is a containment heuristic on the goal's FIRST line,
    case-insensitive — a summary restating the request in different case passes."""
    text, ok = fillline.validate_compaction(
        "I did REFACTOR THE PARSER as asked.", "refactor the parser\nmore detail below", []
    )
    assert ok is True
    assert text == "I did REFACTOR THE PARSER as asked."


def test_validate_compaction_repair_is_idempotent() -> None:
    """Validating a repaired text appends nothing further — the evidence block itself
    satisfies the checks, so repeated validation is a fixed point (c4)."""
    repaired, ok = fillline.validate_compaction("a thin note", "the goal text", ["src/mod.py"])
    assert ok is True
    again, ok2 = fillline.validate_compaction(repaired, "the goal text", ["src/mod.py"])
    assert ok2 is True
    assert again == repaired


def test_build_handoff_instruction_names_finish_and_continuation() -> None:
    """The unrepairable-note handoff instruction (decision c23) is deterministic and
    mirrors the decision prompt's FINISH-WITH-HANDOFF wording: call `finish` with a
    continuation summary."""
    body = fillline.build_handoff_instruction()
    assert body == fillline.build_handoff_instruction()  # deterministic
    assert "FINISH-WITH-HANDOFF" in body
    assert "finish" in body
    assert "continuation summary" in body


# ---------------------------------------------------------------------------
# Unrepairable-note policy in the loop (indefinite-run t2, c4/h4, decision c23)
# ---------------------------------------------------------------------------


def test_empty_summary_rejected_unarmed_keeps_windowing_floor(tmp_path) -> None:
    """An empty compaction summary NEVER replaces history: unarmed (chain_armed
    False, the default), the loop keeps today's lossy-windowing floor — and the old
    '(no summary produced)' silent-amnesia placeholder is gone (c4/h4)."""
    calls: list[list] = []

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            return ModelResponse(content="   \n ", prompt_tokens=5, completion_tokens=1)
        if "declare ONE move" in last:
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    assert result.capacity_decision is not None
    assert result.capacity_decision.kind == "compact"
    # The empty note never replaced history: no compacted-summary message and no
    # silent-amnesia placeholder appear in ANY completion's history.
    for msgs in calls:
        assert not _has(msgs, "[Compacted summary")
        assert not _has(msgs, "(no summary produced)")
    # The lossy-windowing floor preserved the head — the original assignment is
    # still present on the final (finish) turn.
    assert _has(calls[-1], "do a long thing")
    # And no handoff instruction was injected — that path is armed-only.
    assert not any(_has(msgs, "FINISH-WITH-HANDOFF now") for msgs in calls)


def test_empty_summary_rejected_armed_takes_finish_with_handoff(tmp_path) -> None:
    """With continuation chaining armed (ContextControls.chain_armed=True), an
    unrepairable (empty) compaction note routes the run to FINISH-WITH-HANDOFF
    (decision c23): the loop injects the deterministic handoff instruction and the
    model finishes with a continuation summary — preserved on the result."""
    calls: list[list] = []

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            return ModelResponse(content="", prompt_tokens=5, completion_tokens=1)
        if "FINISH-WITH-HANDOFF now" in last:
            return ModelResponse(
                content="handing off",
                tool_calls=[ToolCall("f", "finish", {"summary": "DONE: A  REMAINS: B"})],
                prompt_tokens=5,
                completion_tokens=1,
            )
        if "declare ONE move" in last:
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("1", "list_dir", {"path": "."})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        # Without the injected instruction the model would keep working — the
        # summary assertion below would then fail.
        return ModelResponse(
            content="",
            tool_calls=[ToolCall("2", "list_dir", {"path": "."})],
            prompt_tokens=20,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path), chain_armed=True)
    assert result.status == OK
    # The handoff instruction reached the model and the continuation summary landed.
    assert any(_has(msgs, "FINISH-WITH-HANDOFF now") for msgs in calls)
    assert result.summary == "DONE: A  REMAINS: B"
    # The empty note still never replaced history.
    for msgs in calls:
        assert not _has(msgs, "[Compacted summary")
        assert not _has(msgs, "(no summary produced)")


def test_compaction_summary_repaired_with_run_evidence(tmp_path) -> None:
    """A non-empty summary that omits the goal and a changed-file path is repaired
    deterministically before it replaces history: the compacted note carries the
    run's own evidence (c4) — and validation is pure, no extra model call (c12)."""
    calls: list[list] = []

    def complete(messages):
        calls.append(list(messages))
        last = messages[-1].get("content") or ""
        if "Summarize everything done" in last:
            # Omits the goal AND the changed file — must be repaired, not trusted.
            return ModelResponse(content="made some progress", prompt_tokens=5, completion_tokens=1)
        if "declare ONE move" in last:
            return ModelResponse(content="compacting", prompt_tokens=85, completion_tokens=1)
        if len(calls) == 1:
            return ModelResponse(
                content="",
                tool_calls=[ToolCall("w", "write_file", {"path": "marker.txt", "content": "hi"})],
                prompt_tokens=90,
                completion_tokens=1,
            )
        return ModelResponse(
            content="done",
            tool_calls=[ToolCall("f", "finish", {"summary": "done"})],
            prompt_tokens=5,
            completion_tokens=1,
        )

    result = _run(complete, _task(tmp_path))
    assert result.status == OK
    final = calls[-1]
    note = next(
        (m.get("content") or "")
        for m in final
        if (m.get("content") or "").startswith("[Compacted summary")
    )
    assert "made some progress" in note  # the model's own text, preserved verbatim
    assert "do a long thing" in note  # the goal/original request, repaired in
    assert "marker.txt" in note  # the changed-file evidence, repaired in
    # No second-model / extra completion was introduced by validation (c12):
    # work turn, declaring turn, summary turn, finish turn — exactly four.
    assert len(calls) == 4


def test_from_config_threads_chain_armed() -> None:
    """The from_config mapping threads ``until_done`` into ``chain_armed`` (c23).

    t10's integration catch: nothing set ``chain_armed`` from a real dispatch,
    leaving the armed unrepairable-note branch unreachable — this pins the
    single-source mapping both engines share (the all-engines rule).
    """
    from colleague.config import EngineConfig
    from colleague.loop import ContextControls

    armed = EngineConfig.resolve()
    armed.until_done = True
    assert ContextControls.from_config(armed).chain_armed is True

    bare = EngineConfig.resolve()
    assert ContextControls.from_config(bare).chain_armed is False

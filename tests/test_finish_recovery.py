"""#248 report survival (plan t5): a work item's findings always reach the caller.

Two reproduced failure modes from the issue evidence, fixed in the loop:

- **Mode B — literal finish markup.** The served model emitted its full report as
  literal tool-call text in message *content* (``<tool_call> function=finish>
  <parameter=summary> …``) instead of a structured call. Before the fix the loop
  treated that as a bare no-tool turn (nudge → stop) and the report was lost from
  the artifact; the run read INCOMPLETE with a thin/absent summary. The loop now
  re-parses that shape and treats it as the finish payload, recorded honestly on
  ``TaskResult.finish_recovered = "literal-markup"``.

- **Mode A — thin finish after a heavy read.** A 130k-token, 13-read run finished
  with a single headline sentence (the completion budget went to tool args).
  ``_maybe_force_synthesis`` (#191/#202) only fired on an *empty* summary, so a
  one-liner slipped the net. The loop now also fires it on a THIN finish after a
  read-heavy, zero-write run, recorded as
  ``TaskResult.finish_recovered = "thin-finish-synthesis"``.

A finish that carries a real summary — or any run that wrote files — stays
byte-identical (the marker key is omitted from the artifact).
"""

from __future__ import annotations

from pathlib import Path

from colleague.contract import INCOMPLETE, OK, Task, TaskResult
from colleague.loop import CompleteFn, ModelResponse, ToolCall, run

# The exact shape from issue #248 run 9c0e49d64c9d: note the mangled opening tag
# (``function=finish>`` with no ``<``) — the recovery must tolerate it.
_LITERAL_MARKUP = """<tool_call>
function=finish>
<parameter=summary>
## Design Review: Relaxing _require_tty

Section 1: the guard is too strict for piped callers.
Section 2: the fix is a capability probe, not a hard refusal.
</parameter>
</function>
</tool_call>"""

_WELLFORMED_MARKUP = (
    "<tool_call>\n<function=finish>\n<parameter=summary>\nThe answer is 42, "
    "derived from both config files.\n</parameter>\n</function>\n</tool_call>"
)


def _counting(responses: list[ModelResponse]) -> tuple[CompleteFn, dict]:
    """A scripted complete() that also counts calls (then repeats the last)."""
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete, state


def test_literal_finish_markup_recovered_as_finish(tmp_path: Path) -> None:
    """Mode B: the report emitted as literal markup becomes the real finish."""
    complete, _ = _counting([ModelResponse(content=_LITERAL_MARKUP)])
    result = run(complete, Task.new(str(tmp_path), "review the design"), max_steps=10)

    assert result.status == OK
    assert result.summary.startswith("## Design Review: Relaxing _require_tty")
    assert "Section 2" in result.summary
    assert result.finish_recovered == "literal-markup"
    assert result.stopped_without_finish is False
    assert result.to_dict()["finish_recovered"] == "literal-markup"


def test_wellformed_literal_markup_variant_recovered(tmp_path: Path) -> None:
    complete, _ = _counting([ModelResponse(content=_WELLFORMED_MARKUP)])
    result = run(complete, Task.new(str(tmp_path), "answer"), max_steps=10)

    assert result.status == OK
    assert result.summary == "The answer is 42, derived from both config files."
    assert result.finish_recovered == "literal-markup"


def test_plain_prose_turn_is_not_misparsed(tmp_path: Path) -> None:
    """A bare prose turn (no markup) keeps today's nudge-then-stop behavior."""
    complete, _ = _counting([ModelResponse(content="Let me check the files:")])
    result = run(complete, Task.new(str(tmp_path), "explore"), max_steps=10)

    assert result.status == INCOMPLETE
    assert result.stopped_without_finish is True
    assert result.finish_recovered is None
    assert "finish_recovered" not in result.to_dict()


def _read_turns(n: int) -> list[ModelResponse]:
    return [
        # Alternate the path: five identical calls in a row trip the t16 loop guard.
        ModelResponse(tool_calls=[ToolCall(str(i), "list_dir", {"path": "." if i % 2 else "./"})])
        for i in range(n)
    ]


def test_thin_finish_after_heavy_read_triggers_synthesis(tmp_path: Path) -> None:
    """Mode A: a headline-only finish after many zero-write steps synthesizes."""
    report = "FULL FINDINGS: module A does X; module B does Y; the bug is in C."
    responses = _read_turns(8) + [
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "Read the files."})]),
        ModelResponse(content=report),
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "survey"), max_steps=20)

    assert result.status == OK
    assert result.summary == report
    assert result.finish_recovered == "thin-finish-synthesis"
    assert state["i"] == 10  # 8 read turns + finish turn + ONE synthesis turn


def test_substantive_finish_is_byte_identical(tmp_path: Path) -> None:
    """A real summary after heavy reading is untouched: no synthesis turn runs."""
    real = (
        "The survey found three call sites: alpha.py wires the adapter, beta.py "
        "owns the retry loop, and gamma.py holds the config seam; the fix belongs "
        "in beta.py because the retry loop swallows the timeout classification."
    )
    responses = _read_turns(8) + [
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": real})])
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "survey"), max_steps=20)

    assert result.status == OK
    assert result.summary == real
    assert result.finish_recovered is None
    assert "finish_recovered" not in result.to_dict()
    assert state["i"] == 9  # no extra synthesis turn


def test_thin_finish_with_writes_is_untouched(tmp_path: Path) -> None:
    """A short summary on a run that WROTE files is legitimate ('wrote out.txt')."""
    responses = _read_turns(7) + [
        ModelResponse(
            tool_calls=[ToolCall("w", "write_file", {"path": "out.txt", "content": "x"})]
        ),
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "wrote out.txt"})]),
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "write"), max_steps=20)

    assert result.status == OK
    assert result.summary == "wrote out.txt"
    assert result.finish_recovered is None
    assert state["i"] == 9  # 7 reads + write + finish; no synthesis turn


def test_thin_finish_synthesis_failure_keeps_original(tmp_path: Path) -> None:
    """If the synthesis turn yields nothing, the original thin summary survives."""
    responses = _read_turns(8) + [
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "Read the files."})]),
        ModelResponse(content=""),
    ]
    complete, _ = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "survey"), max_steps=20)

    assert result.status == OK
    assert result.summary == "Read the files."
    assert result.finish_recovered is None


def test_finish_recovered_round_trips_from_dict() -> None:
    r = TaskResult(task_id="x", status=OK, summary="s", finish_recovered="literal-markup")
    assert TaskResult.from_dict(r.to_dict()).finish_recovered == "literal-markup"
    bare = TaskResult(task_id="x", status=OK, summary="s")
    assert TaskResult.from_dict(bare.to_dict()).finish_recovered is None


# The exact meta-description finish observed in issue #231 run d0c20c8c2e54: a
# one-sentence summary that DESCRIBES a report ("covers ... with file:line
# references ...") that is nowhere in the return value. Too long for the thin
# guard (~300 chars > 160), so t6 adds a pattern-based meta-claim detector.
_META_SUMMARY_231 = (
    "Read-only architecture reconnaissance complete. Report covers all three "
    "planned features (Migration Importer, Freshness/Temporal Model, "
    "No-Hard-Delete Lifecycle) with file:line references, schema changes, "
    "computation points, and conflict analysis."
)


def test_meta_description_finish_triggers_synthesis(tmp_path: Path) -> None:
    """#231: a finish that DESCRIBES the report (instead of being it) synthesizes."""
    report = (
        "FINDINGS: record.py holds the schema (add decay fields); scoring.py is "
        "where reinforcement lands; the mongo backend conflicts with shadowing."
    )
    responses = _read_turns(16) + [
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": _META_SUMMARY_231})]),
        ModelResponse(content=report),
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "architecture recon"), max_steps=30)

    assert result.status == OK
    assert result.summary == report
    assert result.finish_recovered == "meta-finish-synthesis"
    assert state["i"] == 18  # 16 reads + finish + ONE synthesis turn


def test_real_report_containing_meta_phrase_is_untouched(tmp_path: Path) -> None:
    """A long real report may legitimately SAY 'analysis complete' — never re-opened."""
    real = (
        "The analysis is complete. FINDINGS ON ALL THREE FEATURES:\n"
        "1) Migration importer: touch eidetic/memory/record.py:41 (schema) and "
        "backends/files.py:88 (reader); add a `migrated_from` field.\n"
        "2) Freshness/temporal: decay computed in scoring.py:120; reinforcement on "
        "recall lands in cli/_commands/recall.py:63.\n"
        "3) No-hard-delete: shadowing conflicts with mongo backend TTL indexes "
        "(backends/mongo.py:204) — needs a tombstone collection instead.\n"
        "Risks: the files backend has no transaction; concurrent shadow writes race."
    )
    responses = _read_turns(16) + [
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": real})])
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "architecture recon"), max_steps=30)

    assert result.status == OK
    assert result.summary == real
    assert result.finish_recovered is None
    assert state["i"] == 17  # no synthesis turn


def test_meta_phrase_on_write_run_is_untouched(tmp_path: Path) -> None:
    """A write-run finish naming its coverage is legitimate — writes disarm t6."""
    summary = "Refactor complete. The change covers all three call sites with tests."
    responses = _read_turns(7) + [
        ModelResponse(
            tool_calls=[ToolCall("w", "write_file", {"path": "out.txt", "content": "x"})]
        ),
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": summary})]),
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "refactor"), max_steps=30)

    assert result.status == OK
    assert result.summary == summary
    assert result.finish_recovered is None
    assert state["i"] == 9


def test_meta_phrase_on_short_run_is_untouched(tmp_path: Path) -> None:
    """A short run (little read context) is never re-opened — nothing to synthesize."""
    responses = _read_turns(3) + [
        ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": _META_SUMMARY_231})])
    ]
    complete, state = _counting(responses)
    result = run(complete, Task.new(str(tmp_path), "quick look"), max_steps=30)

    assert result.status == OK
    assert result.summary == _META_SUMMARY_231
    assert result.finish_recovered is None
    assert state["i"] == 4

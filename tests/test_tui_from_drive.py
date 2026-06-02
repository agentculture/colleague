"""The drive→DriveStep bridge: live and post-hoc summaries must agree.

`convertible/tui/from_drive.py` is the single source of the step→summary mapping,
so a step reads identically whether it came from the live progress callback or
was reconstructed from a `<id>.trace.jsonl` line. These guard that contract plus
the trace-conversion edge cases.
"""

from __future__ import annotations

from convertible.tui.events import DriveStep
from convertible.tui.from_drive import drive_step, progress_target, trace_to_drive_steps


def test_progress_target_prefers_path_then_command_then_name() -> None:
    assert progress_target({"path": "src/x.py"}) == "src/x.py"
    assert progress_target({"command": "pytest -q"}) == "pytest -q"
    assert progress_target({"name": "boost"}) == "boost"
    # path wins over later keys when several are present.
    assert progress_target({"command": "c", "path": "p"}) == "p"


def test_progress_target_first_line_and_truncation() -> None:
    assert progress_target({"command": "echo hi\nrm -rf /"}) == "echo hi"
    long = "a" * 60
    out = progress_target({"path": long})
    assert len(out) == 48 and out.endswith("...")


def test_progress_target_empty_for_non_dict_or_unknown_keys() -> None:
    assert progress_target(None) == ""
    assert progress_target("nope") == ""
    assert progress_target({"unrelated": "value"}) == ""


def test_drive_step_constructs_event() -> None:
    evt = drive_step("write_file", "x.py", ok=False)
    assert evt == DriveStep(tool="write_file", summary="x.py", ok=False)


def test_trace_summary_matches_live_target_for_same_step() -> None:
    """The whole reason this module exists: a trace line's summary equals the
    `target` the live callback would have shown for the same arguments."""
    arguments = {"path": "main.py", "content": "..."}
    live_target = progress_target(arguments)  # what the loop passes live
    (post_hoc,) = trace_to_drive_steps(
        [{"index": 0, "tool": "write_file", "arguments": arguments, "result": "wrote", "ok": True}]
    )
    assert post_hoc == DriveStep(tool="write_file", summary=live_target, ok=True)


def test_trace_falls_back_to_result_when_no_subject_key() -> None:
    (step,) = trace_to_drive_steps(
        [{"index": 0, "tool": "finish", "arguments": {}, "result": "all done\nextra", "ok": True}]
    )
    assert step.tool == "finish"
    assert step.summary == "all done"  # first line of result, args carry no hint


def test_trace_preserves_ok_and_skips_malformed_lines() -> None:
    steps = trace_to_drive_steps(
        [
            {
                "tool": "run_command",
                "arguments": {"command": "false"},
                "result": "boom",
                "ok": False,
            },
            "not a dict",
            {"index": 9, "arguments": {"path": "x"}},  # no tool -> skipped
            {"tool": "read_file", "arguments": {"path": "y.py"}},  # ok defaults True
        ]
    )
    assert [(s.tool, s.ok) for s in steps] == [("run_command", False), ("read_file", True)]

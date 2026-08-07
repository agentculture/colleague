"""t3: the feedback verb-group rendered from the agentfront App registry.

Exercises the migrated `feedback` group through agentfront's run_cli (the rendered
path), proving the reference migration pattern: named-param tool funcs that return
``rendered(structured, text)`` produce colleague's exact dual output (pretty text
vs --json structured), errors raise CliError (rendered natively), the nested group
dispatches, bare-noun falls through to the framework overview, explain reads the
op's doc, and the tools land in the registry (so MCP/learn see them too).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

from agentfront.cli_surface import run_cli

from colleague.cli._app import build_app


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = run_cli(build_app(), argv)
    except SystemExit as exc:  # KeyboardInterrupt path
        code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_record_then_show_dual_rendered(tmp_path):
    code, out, _ = _run(
        ["feedback", "record", "d1", "--rating", "4", "--by", "ori", "--repo", str(tmp_path)]
    )
    assert code == 0
    assert "rating: 4/5" in out  # pretty text in text mode

    code, out, _ = _run(["feedback", "show", "d1", "--repo", str(tmp_path), "--json"])
    assert code == 0
    rec = json.loads(out)  # structured dict under --json
    assert rec["task_id"] == "d1" and rec["rating"] == 4 and rec["by"] == "ori"


def test_show_ungraded_is_clean_dual(tmp_path):
    code, out, _ = _run(["feedback", "show", "never", "--repo", str(tmp_path)])
    assert code == 0 and "no feedback yet" in out

    code, out, _ = _run(["feedback", "show", "never", "--repo", str(tmp_path), "--json"])
    assert code == 0
    assert json.loads(out) == {"task_id": "never", "feedback": None}


def test_record_missing_rating_errors_cleanly(tmp_path):
    code, out, err = _run(["feedback", "record", "d2", "--repo", str(tmp_path)])
    assert code != 0  # rating 0 is out of the 1-5 range
    assert out.strip() == ""  # clean stdout on failure
    assert "error:" in err and "Traceback" not in err


def test_bare_feedback_falls_through_to_group_overview(tmp_path):
    code, out, _ = _run(["feedback"])
    assert code == 0
    for verb in ("record", "show", "list"):
        assert verb in out  # the framework bare-noun overview lists the child verbs


def test_explain_feedback_record_reads_doc(tmp_path):
    code, out, _ = _run(["explain", "feedback", "record"])
    assert code == 0 and "record" in out.lower()


def test_feedback_list_rendered(tmp_path):
    # `list` enumerates work-item artifacts (not feedback records); an empty repo
    # yields an empty JSON list (text mode: a clean "no work items" message).
    code, out, _ = _run(["feedback", "list", "--repo", str(tmp_path), "--json"])
    assert code == 0
    assert json.loads(out) == []  # a real JSON array, dual-rendered from rendered()

    code, out, _ = _run(["feedback", "list", "--repo", str(tmp_path)])
    assert code == 0 and "no work items" in out


def test_record_author_cortex_dual_rendered(tmp_path):
    """t3: the `--author` flag derives cleanly from the registry tool signature
    (no explicit Flag() entry needed, same as `--by`)."""
    code, out, _ = _run(
        [
            "feedback",
            "record",
            "d1",
            "--rating",
            "5",
            "--author",
            "cortex",
            "--repo",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert "author: cortex" in out

    code, out, _ = _run(
        ["feedback", "show", "d1", "--author", "cortex", "--repo", str(tmp_path), "--json"]
    )
    assert code == 0
    rec = json.loads(out)
    assert rec["author"] == "cortex"
    assert rec["rating"] == 5


def test_feedback_tools_land_in_registry():
    """The group's verbs are real registry tools (so MCP/learn enumerate them too)."""
    app = build_app()
    paths = {tuple(t.group) + (t.name,) for t in app.list_tools()}
    for verb in ("record", "show", "list", "overview"):
        assert ("feedback", verb) in paths

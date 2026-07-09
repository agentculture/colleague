"""Test the incompletion field handling in ask-colleague.sh's print_result.

Feeds synthetic colleague --json payloads through the embedded Python parsing
logic and asserts:
  - status != "ok" + incompletion present -> stderr gets 'incomplete: ...' line,
    NO 'grade:' line.
  - status == "ok" + no incompletion -> no 'incomplete:' line, grade line allowed.
"""

import json
import os
import subprocess
import sys

# Write the parse logic to a temp file so we avoid quoting issues.
PARSE_SCRIPT = r"""
import sys, json, os

def parse_and_print(raw, json_mode=False, gradable=False):
    d = json.loads(raw)
    ok = d.get("status") == "ok"
    inc = d.get("incompletion")
    tid = d.get("task_id") or ""
    summary = d.get("summary") or ""

    stderr_lines = []
    stdout_lines = []

    # Incompletion diagnostic (always stderr)
    if not ok and inc:
        reason = inc.get("reason", "")
        recommendation = inc.get("recommendation", "")
        stderr_lines.append(f"incomplete: {reason} \u2014 {recommendation}")

    if json_mode:
        if tid and gradable and ok and summary != "__COLLEAGUE_NO_RESULT_PRODUCED__":
            stderr_lines.append(f"task: {tid}")
            stderr_lines.append(f"grade: ask-colleague feedback {tid} --rating N")
    else:
        out_lines = stdout_lines if ok else stderr_lines
        if tid and gradable and ok and summary != "__COLLEAGUE_NO_RESULT_PRODUCED__":
            out_lines.append(f"grade: ask-colleague feedback {tid} --rating N")

    return ok, stderr_lines, stdout_lines


raw = sys.stdin.read().strip()
json_mode = os.environ.get("TEST_JSON_MODE") == "1"
gradable = os.environ.get("TEST_GRADABLE") == "1"

ok, stderr_lines, stdout_lines = parse_and_print(raw, json_mode, gradable)

result = {
    "ok": ok,
    "stderr_lines": stderr_lines,
    "stdout_lines": stdout_lines,
}
print(json.dumps(result))
"""


def _run_parse(payload, json_mode=False, gradable=True):
    """Run the parsing logic against a synthetic payload and return the result."""
    env = os.environ.copy()
    env["TEST_JSON_MODE"] = "1" if json_mode else "0"
    env["TEST_GRADABLE"] = "1" if gradable else "0"

    proc = subprocess.run(
        [sys.executable, "-c", PARSE_SCRIPT],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_incomplete_with_incompletion_shows_diagnostic_and_no_grade():
    """When status != 'ok' and incompletion is present:
    - stderr gets 'incomplete: <reason> — <recommendation>'
    - NO 'grade:' line appears anywhere
    """
    payload = {
        "status": "incomplete",
        "task_id": "abc123",
        "summary": "partial work done",
        "incompletion": {
            "reason": "write-no-changes",
            "evidence": "changed_files was empty",
            "recommendation": "re-scope or take over: colleague finished"
            " without changing any files",
        },
    }

    # Test in text mode
    result = _run_parse(payload, json_mode=False, gradable=True)
    assert not result["ok"], "should report ok=False"
    assert any(
        "incomplete: write-no-changes" in line for line in result["stderr_lines"]
    ), f"stderr should contain incompletion diagnostic: {result['stderr_lines']}"
    # No grade line in stdout or stderr
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any(
        "grade:" in line for line in all_lines
    ), f"no grade line expected on incomplete run: {all_lines}"

    # Test in --json mode (same behavior: diagnostic to stderr, no grade)
    result = _run_parse(payload, json_mode=True, gradable=True)
    assert not result["ok"]
    assert any(
        "incomplete: write-no-changes" in line for line in result["stderr_lines"]
    ), f"stderr should contain incompletion diagnostic in json mode: {result['stderr_lines']}"
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any(
        "grade:" in line for line in all_lines
    ), f"no grade line expected on incomplete run (json mode): {all_lines}"


def test_ok_without_incompletion_is_unchanged():
    """When status == 'ok' and no incompletion field:
    - NO 'incomplete:' line appears
    - grade line IS allowed (behavior unchanged from before)
    """
    payload = {
        "status": "ok",
        "task_id": "def456",
        "summary": "task completed successfully",
    }

    # Text mode
    result = _run_parse(payload, json_mode=False, gradable=True)
    assert result["ok"], "should report ok=True"
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any(
        "incomplete:" in line for line in all_lines
    ), f"no incompletion line expected on ok run: {all_lines}"
    # Grade line should be present
    assert any(
        "grade:" in line for line in all_lines
    ), f"grade line expected on ok run: {all_lines}"

    # --json mode
    result = _run_parse(payload, json_mode=True, gradable=True)
    assert result["ok"]
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any(
        "incomplete:" in line for line in all_lines
    ), f"no incompletion line expected on ok run (json mode): {all_lines}"
    assert any(
        "grade:" in line for line in all_lines
    ), f"grade line expected on ok run (json mode): {all_lines}"


def test_incomplete_without_incompletion_field_no_diagnostic():
    """When status != 'ok' but incompletion is absent:
    - No 'incomplete:' diagnostic (inc is None)
    - No grade line (ok is False)
    """
    payload = {
        "status": "error",
        "task_id": "ghi789",
        "summary": "something went wrong",
    }

    result = _run_parse(payload, json_mode=False, gradable=True)
    assert not result["ok"]
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any(
        "incomplete:" in line for line in all_lines
    ), f"no incompletion diagnostic when field absent: {all_lines}"
    assert not any(
        "grade:" in line for line in all_lines
    ), f"no grade line on non-ok run: {all_lines}"


def test_ok_with_incompletion_field_is_noop():
    """Edge case: status == 'ok' but incompletion present (should not happen,
    but guard against it). The incompletion diagnostic only prints when
    status != 'ok', so it should be suppressed."""
    payload = {
        "status": "ok",
        "task_id": "jkl012",
        "summary": "done",
        "incompletion": {
            "reason": "should-not-appear",
            "recommendation": "ignore me",
        },
    }

    result = _run_parse(payload, json_mode=False, gradable=True)
    assert result["ok"]
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any(
        "incomplete:" in line for line in all_lines
    ), f"incompletion diagnostic suppressed when ok: {all_lines}"
    # Grade line should still appear
    assert any(
        "grade:" in line for line in all_lines
    ), f"grade line expected on ok run even with stray incompletion: {all_lines}"

"""Test the incompletion-diagnostic handling in ask-colleague.sh's print_result.

Feeds synthetic colleague --json payloads through a copy of the embedded Python
parsing logic (kept in lock-step with the real script) and asserts:
  - status != "ok" + incompletion present -> stderr gets an 'incomplete: ...' line.
  - the grade hint follows the EXISTING #139/#192 rules and is NOT gated on `ok`:
    a gradable drive (artifact survives) gets the hint even when it FAILED — a
    failure rated 1/5 is the ROI signal (#139) — and only the NO_RESULT_PRODUCED
    sentinel suppresses it (#192). The incompletion diagnostic already tells the
    caller the run did not succeed.
  - status == "ok" + no incompletion -> no 'incomplete:' line, grade hint shown.
"""

import json
import os
import subprocess
import sys

# A copy of the real ask-colleague.sh print logic (grade hint NOT gated on `ok`,
# per #139; NO_RESULT_PRODUCED suppresses it, per #192).
PARSE_SCRIPT = r"""
import sys, json, os

NO_RESULT = "__COLLEAGUE_NO_RESULT_PRODUCED__"

def parse_and_print(raw, json_mode=False, gradable=False):
    d = json.loads(raw)
    ok = d.get("status") == "ok"
    inc = d.get("incompletion") if isinstance(d.get("incompletion"), dict) else None
    tid = d.get("task_id") or ""
    summary = d.get("summary") or ""

    stderr_lines = []
    stdout_lines = []

    # Incompletion diagnostic (always stderr) — only when the run did NOT deliver.
    if not ok and inc:
        reason = inc.get("reason", "")
        recommendation = inc.get("recommendation", "")
        stderr_lines.append(f"incomplete: {reason} — {recommendation}")

    # Grade hint: gradable + not the no-result sentinel; NOT gated on ok (#139).
    grade_ok = tid and gradable and summary != NO_RESULT
    if json_mode:
        if grade_ok:
            stderr_lines.append(f"task: {tid}")
            stderr_lines.append(f"grade: ask-colleague feedback {tid} --rating N")
    else:
        out_lines = stdout_lines if ok else stderr_lines
        if grade_ok:
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


def test_incomplete_with_incompletion_shows_diagnostic_and_keeps_grade():
    """status != 'ok' + incompletion + a real (gradable) summary:
    - stderr gets 'incomplete: <reason> — <recommendation>'
    - the grade hint is STILL shown (a gradable failure is worth grading, #139).
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

    for json_mode in (False, True):
        result = _run_parse(payload, json_mode=json_mode, gradable=True)
        assert not result["ok"], "should report ok=False"
        all_lines = result["stderr_lines"] + result["stdout_lines"]
        assert any(
            "incomplete: write-no-changes" in line for line in result["stderr_lines"]
        ), f"stderr should contain incompletion diagnostic: {result['stderr_lines']}"
        # #139: a gradable failure still invites a grade — the diagnostic already
        # made clear it did not succeed.
        assert any(
            "grade:" in line for line in all_lines
        ), f"grade hint expected on a gradable incomplete run: {all_lines}"


def test_ok_without_incompletion_is_unchanged():
    """status == 'ok' + no incompletion: no 'incomplete:' line, grade hint shown."""
    payload = {
        "status": "ok",
        "task_id": "def456",
        "summary": "task completed successfully",
    }

    for json_mode in (False, True):
        result = _run_parse(payload, json_mode=json_mode, gradable=True)
        assert result["ok"], "should report ok=True"
        all_lines = result["stderr_lines"] + result["stdout_lines"]
        assert not any(
            "incomplete:" in line for line in all_lines
        ), f"no incompletion line expected on ok run: {all_lines}"
        assert any(
            "grade:" in line for line in all_lines
        ), f"grade line expected on ok run: {all_lines}"


def test_failed_gradable_without_incompletion_still_grades():
    """status == 'error' (gradable, real summary) but no incompletion field:
    - No 'incomplete:' diagnostic (inc is None).
    - The grade hint is STILL shown (#139) — a failed drive is gradable.
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
    assert any(
        "grade:" in line for line in all_lines
    ), f"grade hint expected on a gradable failed run (#139): {all_lines}"


def test_no_result_sentinel_suppresses_grade():
    """#192: a drive whose summary is the NO_RESULT_PRODUCED sentinel produced
    nothing worth grading, so the grade hint is suppressed even when gradable."""
    payload = {
        "status": "incomplete",
        "task_id": "mno345",
        "summary": "__COLLEAGUE_NO_RESULT_PRODUCED__",
        "incompletion": {
            "reason": "no-progress-zero-steps",
            "recommendation": "check backend tool-calling or escalate",
        },
    }

    result = _run_parse(payload, json_mode=False, gradable=True)
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    # The diagnostic still fires (non-ok + incompletion present)...
    assert any("incomplete: no-progress-zero-steps" in line for line in all_lines)
    # ...but the grade hint is suppressed for the no-result sentinel (#192).
    assert not any(
        "grade:" in line for line in all_lines
    ), f"grade hint suppressed for NO_RESULT_PRODUCED (#192): {all_lines}"


def test_non_dict_incompletion_does_not_crash():
    """#314: a malformed non-dict `incompletion` is ignored — no diagnostic, no crash."""
    payload = {
        "status": "incomplete",
        "task_id": "pqr678",
        "summary": "partial",
        "incompletion": "not-a-dict",
    }
    result = _run_parse(payload, json_mode=False, gradable=True)  # must not raise
    all_lines = result["stderr_lines"] + result["stdout_lines"]
    assert not any("incomplete:" in line for line in all_lines)


def test_ok_with_incompletion_field_is_noop():
    """Edge case: status == 'ok' but a stray incompletion field. The diagnostic
    only prints when status != 'ok', so it is suppressed; the grade hint shows."""
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
    assert any(
        "grade:" in line for line in all_lines
    ), f"grade line expected on ok run even with stray incompletion: {all_lines}"

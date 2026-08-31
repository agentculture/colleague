"""Runtime memory wiring (plan t2, spec R1/c9/h7): recall-before + remember-after.

The loop consults the repo's eidetic memory store around every work item —
recall at task start (a token-capped "prior lessons" block injected as advisory
context) and remember at exit (a deterministic lesson record) — via the
:mod:`colleague.memory` adapter (plan t1).

Arming is deliberately conservative (h7 + test hygiene):

- the repo must contain a ``.eidetic/`` store (a repo opts into memory by
  having one; a tmp test repo without it is a strict no-op — zero subprocess);
- ``ContextControls.memory`` must be truthy (forwarded from
  ``EngineConfig.memory``, default-on, opt-out via ``COLLEAGUE_MEMORY=0`` /
  config.json ``{"memory": false}`` — the lint-gate pattern);
- the eidetic CLI must be on PATH (absent = strict no-op, from t1).

Everything recorded lands on ``TaskResult.memory`` (omit-when-None), so a
memory-less run serializes byte-identically.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_FINISH = ModelResponse(
    tool_calls=[
        ToolCall(
            "f",
            "finish",
            {
                "summary": (
                    "The survey found the adapter seam in alpha.py and the retry loop "
                    "in beta.py; the timeout classification is swallowed in beta.py's "
                    "except clause, which is where the fix belongs."
                )
            },
        )
    ]
)


def scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _fake_eidetic(bin_dir: Path, log: Path, recall_payload: list[dict]) -> None:
    """Install a fake ``eidetic`` executable that logs argv and answers recall."""
    script = bin_dir / "eidetic"
    payload = json.dumps(recall_payload)
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write("
        "json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
        "if sys.argv[1] == 'recall':\n"
        f"    print({payload!r})\n"
        "sys.exit(0)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".eidetic" / "memory").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def eidetic_log(repo: Path, tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "eidetic.log"
    _fake_eidetic(
        bin_dir,
        log,
        [
            {"text": "GOTCHA: loop.py is the hot file - merge sequentially."},
            {"text": "DECISION: the all-engines rule is settled."},
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line)["argv"] for line in log.read_text().splitlines()]


def _cwds(log: Path) -> list[str]:
    return [json.loads(line)["cwd"] for line in log.read_text().splitlines()]


#: The full ``TaskResult.memory`` key set of a plain armed run whose recall
#: surfaced NO class-relevant lesson (``class_relevant_rank`` appears only on a
#: hit, and the distill counters only when the rung-2 seam is armed).
_ARMED_MEMORY_KEYS = {
    "query",
    "recalled",
    "injected_chars",
    "lesson_recorded",
    "class_key",
    "precision_rule",
    "class_relevant_recalled",
    "class_relevant_in_top_k",
}

#: Every key the retrieval-precision instrumentation can ever add. The
#: memory-less regression guard asserts NONE of them reach the artifact.
_PRECISION_KEYS = _ARMED_MEMORY_KEYS - {
    "query",
    "recalled",
    "injected_chars",
    "lesson_recorded",
} | {"class_relevant_rank"}


def _fake_eidetic_capturing_env(bin_dir: Path, log: Path, env_var: str) -> None:
    """Install a fake ``eidetic`` that logs argv + one named env var per call."""
    script = bin_dir / "eidetic"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps({{"
        "'argv': sys.argv[1:], "
        f"'env_value': os.environ.get({env_var!r})"
        "}) + '\\n')\n"
        "if sys.argv[1] == 'recall':\n"
        "    print('[]')\n"
        "sys.exit(0)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _result_for_lesson(**kw):
    from colleague.contract import TaskResult

    base = dict(task_id="t379", status="incomplete", summary="")
    base.update(kw)
    return TaskResult(**base)


def _armed_distill_run(repo, distill_fn, *, memory_distill=True, task_text="fold the retry"):
    task = Task.new(str(repo), task_text)
    result = run(
        scripted([_FINISH]),
        task,
        max_steps=5,
        context=ContextControls(memory=True, memory_distill=memory_distill, distill_fn=distill_fn),
    )
    return task, result


def _remembered_record(log: Path) -> dict:
    remember_calls = [c for c in _calls(log) if c[0] == "remember"]
    assert len(remember_calls) == 1
    return json.loads(remember_calls[0][1])


def _fake_eidetic_records(bin_dir: Path, log: Path, records: list[dict]) -> None:
    """Like ``_fake_eidetic`` but the caller supplies full record dicts
    (id/score/signal/supersedes/metadata) rather than plain {"text": ...}."""
    script = bin_dir / "eidetic"
    payload = json.dumps(records)
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write("
        "json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
        "if sys.argv[1] == 'recall':\n"
        f"    print({payload!r})\n"
        "sys.exit(0)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def test_lesson_text_carries_incompletion_substance() -> None:
    """#379 rung 1: a failed run's lesson names WHAT failed — the structured
    incompletion {reason, evidence, recommendation} — not just step counts."""
    from colleague.contract import IncompletionRecord
    from colleague.memory import compose_lesson_text

    result = _result_for_lesson(
        incompletion=IncompletionRecord(
            reason="no-progress-zero-steps",
            evidence="finished outcome='stopped' with 0 changed file(s) over 0 step(s)",
            recommendation="check backend tool-calling or escalate to another model",
        )
    )
    text = compose_lesson_text(result)
    assert "no-progress-zero-steps" in text
    assert "0 changed file(s)" in text
    assert "escalate to another model" in text


def test_lesson_text_carries_error_and_refresh_warnings() -> None:
    from colleague.memory import compose_lesson_text

    result = _result_for_lesson(
        status="failed",
        error="HTTP Error 404: model_not_found",
        warnings=[
            {
                "role": "cortex",
                "stale_id": "old/model",
                "source": "CONVERTIBLE_MODEL",
                "refreshed_id": "new/model",
                "point": "resolution",
            }
        ],
    )
    text = compose_lesson_text(result)
    assert "HTTP Error 404" in text
    assert "old/model" in text
    assert "CONVERTIBLE_MODEL" in text
    assert "new/model" in text


def test_lesson_text_ok_run_stays_compact_and_stub_compatible() -> None:
    """An ok run without failure substance keeps the existing telemetry shape
    (prefix unchanged — recall consumers parse it)."""
    from colleague.memory import compose_lesson_text

    result = _result_for_lesson(status="ok", summary="did the thing")
    text = compose_lesson_text(result)
    assert text.startswith("Work item t379 finished ok")
    assert "Incompletion:" not in text
    assert "Error:" not in text


def test_lesson_text_folds_lint_report() -> None:
    """A result carrying lint_report folds it into the lesson text, bounded per field."""
    from colleague.contract import LintReport
    from colleague.memory import compose_lesson_text

    result = _result_for_lesson(
        lint_report=LintReport(
            fixed=["black reformatted 2 file(s)"],
            residual=["flake8 F811 colleague/x.py:10"],
            skipped=["ruff: not installed"],
        )
    )
    text = compose_lesson_text(result)
    assert "Lint:" in text
    assert "black reformatted 2 file(s)" in text
    assert "flake8 F811 colleague/x.py:10" in text
    assert "ruff: not installed" in text


def test_lesson_text_folds_test_integrity_report() -> None:
    """A result carrying test_integrity_report folds it into the lesson text, bounded per field."""
    from colleague.memory import compose_lesson_text
    from colleague.testintegrity import MirrorFinding, TestIntegrityReport

    result = _result_for_lesson(
        test_integrity_report=TestIntegrityReport(
            findings=[
                MirrorFinding(
                    symbol="FAKE_MIRROR",
                    kind="attribute",
                    test_file="tests/test_foo.py",
                    impl_file="colleague/foo.py",
                )
            ]
        )
    )
    text = compose_lesson_text(result)
    assert "Test integrity:" in text
    assert "FAKE_MIRROR" in text
    assert "tests/test_foo.py" in text
    assert "colleague/foo.py" in text


def test_lesson_text_folds_affected_tests_report() -> None:
    """A result carrying affected_tests_report folds it into the lesson text, bounded per field."""
    from colleague.affectedtests import AffectedTestsReport
    from colleague.memory import compose_lesson_text

    result = _result_for_lesson(
        affected_tests_report=AffectedTestsReport(
            status="failed",
            selected=["tests/test_foo.py"],
            total=1,
            capped=False,
            passed=0,
            failed=1,
        )
    )
    text = compose_lesson_text(result)
    assert "Affected tests:" in text
    assert "failed" in text
    assert "tests/test_foo.py" in text
    assert "1 failed" in text


def test_lesson_text_no_reports_is_byte_identical() -> None:
    """A result without lint/test_integrity/affected_tests reports produces
    byte-identical lesson text to the current rung-1 shape, same upsert id."""
    from colleague.memory import build_lesson_record, compose_lesson_text

    result = _result_for_lesson(status="ok", summary="did the thing")
    text = compose_lesson_text(result)
    # Should be identical to the stub shape — no new prefixes
    assert text.startswith("Work item t379 finished ok")
    assert "Incompletion:" not in text
    assert "Error:" not in text
    assert "Lint:" not in text
    assert "Test integrity:" not in text
    assert "Affected tests:" not in text
    # Same upsert id
    record = build_lesson_record(result.task_id, text, {})
    assert record["id"] == f"work-lesson-{result.task_id}"


def test_lesson_text_lint_report_bounded_per_field() -> None:
    """Each lint_report field is bounded (200-char cap) — no runaway text."""
    from colleague.contract import LintReport
    from colleague.memory import compose_lesson_text

    long_item = "X" * 300
    result = _result_for_lesson(
        lint_report=LintReport(
            fixed=[long_item, long_item],
            residual=[long_item],
            skipped=[],
        )
    )
    text = compose_lesson_text(result)
    # The joined+cap per field must not exceed 200 chars
    lint_section = text[text.index("Lint:") :].split(".")[0]
    assert len(lint_section) <= 200 + len("Lint: ") + 1  # section + prefix + trailing dot


def test_lesson_text_all_three_reports_together() -> None:
    """A result carrying all three reports folds each into the lesson text."""
    from colleague.affectedtests import AffectedTestsReport
    from colleague.contract import LintReport
    from colleague.memory import compose_lesson_text
    from colleague.testintegrity import MirrorFinding, TestIntegrityReport

    result = _result_for_lesson(
        lint_report=LintReport(fixed=["black reformatted 1 file(s)"], residual=[], skipped=[]),
        test_integrity_report=TestIntegrityReport(
            findings=[
                MirrorFinding(
                    symbol="MIRROR_SYM",
                    kind="dict_key",
                    test_file="tests/test_bar.py",
                    impl_file="colleague/bar.py",
                )
            ]
        ),
        affected_tests_report=AffectedTestsReport(
            status="passed",
            selected=["tests/test_bar.py"],
            total=1,
            capped=False,
            passed=1,
            failed=0,
        ),
    )
    text = compose_lesson_text(result)
    assert "Lint:" in text
    assert "Test integrity:" in text
    assert "Affected tests:" in text
    assert "black reformatted 1 file(s)" in text
    assert "MIRROR_SYM" in text
    assert "tests/test_bar.py" in text
    assert "passed" in text


def test_distill_valid_lesson_folds_into_record(repo: Path, eidetic_log: Path) -> None:
    raw = (
        '{"pattern": "wrong file edited first", "constant": "colleague/loop.py", '
        '"reason": "grep before edit"}'
    )
    task, result = _armed_distill_run(repo, lambda res, head: raw)
    record = _remembered_record(eidetic_log)
    assert "Lesson (origin=model)" in record["text"]
    assert "grep before edit" in record["text"]
    assert record["metadata"]["distill"] == "validated"
    assert result.memory["distill_attempts"] == 1
    assert result.memory["distill_validated"] == 1


def test_distill_garbage_completion_records_marker_not_lesson(
    repo: Path, eidetic_log: Path
) -> None:
    task, result = _armed_distill_run(repo, lambda res, head: "sorry, no idea at all")
    record = _remembered_record(eidetic_log)
    assert "Lesson (origin=model)" not in record["text"]
    assert record["metadata"]["distill"] == "no-lesson-extracted"
    assert result.memory["distill_attempts"] == 1
    assert result.memory["distill_validated"] == 0


def test_distill_schema_invalid_lesson_refused_whole(repo: Path, eidetic_log: Path) -> None:
    raw = '{"cause": "x", "lesson": "y", "next_delta": "z", "extra": "smuggled"}'
    task, result = _armed_distill_run(repo, lambda res, head: raw)
    record = _remembered_record(eidetic_log)
    assert "Lesson (origin=model)" not in record["text"]
    assert "smuggled" not in record["text"]
    assert result.memory["distill_validated"] == 0


def test_distill_seam_raising_counts_attempt_never_breaks_run(
    repo: Path, eidetic_log: Path
) -> None:
    def boom(res, head):
        raise RuntimeError("distillation child died")

    task, result = _armed_distill_run(repo, boom)
    assert result.status == OK
    assert result.memory["lesson_recorded"] is True
    assert result.memory["distill_attempts"] == 1
    assert result.memory["distill_validated"] == 0


def test_distill_knob_off_is_byte_identical_rung1(repo: Path, eidetic_log: Path) -> None:
    calls = {"n": 0}

    def seam(res, head):
        calls["n"] += 1
        return '{"cause": "a", "lesson": "b", "next_delta": "c"}'

    task, result = _armed_distill_run(repo, seam, memory_distill=False)
    assert calls["n"] == 0
    record = _remembered_record(eidetic_log)
    assert "Lesson (origin=model)" not in record["text"]
    assert "distill" not in record["metadata"]
    assert set(result.memory) == _ARMED_MEMORY_KEYS


def test_no_distill_fn_is_byte_identical_rung1(repo: Path, eidetic_log: Path) -> None:
    task = Task.new(str(repo), "no seam present")
    result = run(scripted([_FINISH]), task, max_steps=5, context=ContextControls(memory=True))
    record = _remembered_record(eidetic_log)
    assert "distill" not in record["metadata"]
    assert set(result.memory) == _ARMED_MEMORY_KEYS


def test_parse_lesson_json_tolerant_extraction() -> None:
    from colleague.lessons import parse_lesson_json

    fenced = 'Here it is:\n```json\n{"cause": "a", "lesson": "b", "next_delta": "c"}\n```\ndone'
    assert parse_lesson_json(fenced) == {"cause": "a", "lesson": "b", "next_delta": "c"}
    assert parse_lesson_json("no json here") is None
    assert parse_lesson_json('{"truncated": ') is None


def test_below_threshold_record_excluded_from_injection_and_recorded_on_artifact(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    bin_dir = tmp_path / "bin-thresh"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-thresh.log"
    _fake_eidetic_records(
        bin_dir,
        log,
        [
            {"id": "strong", "text": "GOOD LESSON: keep this one", "score": 0.9},
            {"id": "weak", "text": "WEAK LESSON: drop this one", "score": 0.05},
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("COLLEAGUE_RECALL_MIN_SCORE", "0.5")

    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    joined = json.dumps(seen_messages[0])
    assert "GOOD LESSON" in joined
    assert "WEAK LESSON" not in joined
    assert result.memory is not None
    # recalled stays the FULL count — the exclusion is an injection-time
    # concern, not a change to what was recalled.
    assert result.memory["recalled"] == 2
    assert result.memory["recall_excluded"] == [{"id": "weak", "reason": "below-min-score"}]
    assert result.to_dict()["memory"]["recall_excluded"] == [
        {"id": "weak", "reason": "below-min-score"}
    ]


def test_superseded_record_dropped_from_injection_and_recorded_on_artifact(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    bin_dir = tmp_path / "bin-supersedes"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-supersedes.log"
    _fake_eidetic_records(
        bin_dir,
        log,
        [
            {"id": "old", "text": "OLD LESSON: the stale answer"},
            {"id": "new", "text": "NEW LESSON: the corrected answer", "supersedes": "old"},
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    joined = json.dumps(seen_messages[0])
    assert "NEW LESSON" in joined
    assert "OLD LESSON" not in joined
    assert result.memory is not None
    assert result.memory["recalled"] == 2
    assert result.memory["recall_excluded"] == [{"id": "old", "reason": "superseded-by:new"}]


def test_recall_hygiene_env_disabled_is_byte_identical_to_today(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """COLLEAGUE_RECALL_HYGIENE=0 restores pre-t6 injection behavior exactly —
    even with a threshold configured AND a supersedes edge present, every
    recalled record is injected and no exclusion is recorded."""
    bin_dir = tmp_path / "bin-disabled"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-disabled.log"
    _fake_eidetic_records(
        bin_dir,
        log,
        [
            {"id": "old", "text": "OLD LESSON", "score": 0.0},
            {"id": "new", "text": "NEW LESSON", "score": 0.0, "supersedes": "old"},
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("COLLEAGUE_RECALL_MIN_SCORE", "0.99")
    monkeypatch.setenv("COLLEAGUE_RECALL_HYGIENE", "0")

    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    joined = json.dumps(seen_messages[0])
    assert "OLD LESSON" in joined
    assert "NEW LESSON" in joined
    assert result.memory is not None
    assert "recall_excluded" not in result.memory
    assert set(result.memory) == _ARMED_MEMORY_KEYS


def test_precision_fields_scored_over_full_recalled_set_not_filtered_injection(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """t5 composition rule, proven: a class-relevant record excluded from
    INJECTION by t6's threshold still counts toward class_relevant_recalled/
    class_relevant_in_top_k/class_relevant_rank — filtering happens strictly
    after precision scoring, never before."""
    from colleague.memory import task_class_key

    instruction = "fix the timeout classification in beta.py"
    key = task_class_key(instruction)
    bin_dir = tmp_path / "bin-precision"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-precision.log"
    _fake_eidetic_records(
        bin_dir,
        log,
        [
            {"id": "noise", "text": "unrelated", "metadata": {"class_key": "some-other-class"}},
            {
                "id": "the-lesson",
                "text": "THE CLASS LESSON",
                "metadata": {"class_key": key},
                "score": 0.01,  # below the threshold — excluded from injection
            },
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("COLLEAGUE_RECALL_MIN_SCORE", "0.5")

    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), instruction),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    # Excluded from the actual injected context...
    joined = json.dumps(seen_messages[0])
    assert "THE CLASS LESSON" not in joined
    assert result.memory is not None
    assert result.memory["recall_excluded"] == [{"id": "the-lesson", "reason": "below-min-score"}]
    # ...yet still counted by t5's precision scoring, at its real recalled rank.
    assert result.memory["class_key"] == key
    assert result.memory["class_relevant_recalled"] == 1
    assert result.memory["class_relevant_in_top_k"] is True
    assert result.memory["class_relevant_rank"] == 2


def test_legacy_three_key_lesson_recalls_as_free_text_without_error(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """t3 replaced the lesson schema outright (pattern/constant/reason
    superseding cause/lesson/next_delta) with no dual-schema validator. t3's
    own acceptance criterion — 'already-stored 3-key lessons recall as legacy
    free text without error' — is a property of the RECALL path, proven here:
    a store containing an old-shape 3-key record must recall + inject without
    raising, because recall never re-validates a record's schema — it only
    ever reads the record's own ``text`` field as opaque prose."""
    bin_dir = tmp_path / "bin-legacy"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-legacy.log"
    legacy_record = {
        "id": "work-lesson-legacy123",
        "text": (
            "Lesson (origin=model): cause=wrong file targeted; "
            "lesson=check imports before editing; next_delta=grep before edit."
        ),
        "metadata": {
            "cause": "wrong file targeted",
            "lesson": "check imports before editing",
            "next_delta": "grep before edit",
            "distill": "validated",
        },
    }
    _fake_eidetic_records(bin_dir, log, [legacy_record])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), "check imports before editing beta.py"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert result.status == OK
    joined = json.dumps(seen_messages[0])
    assert "check imports before editing" in joined
    assert result.memory is not None
    assert result.memory["recalled"] == 1
    assert "recall_excluded" not in result.memory


def test_memory_distill_config_resolution(tmp_path: Path, monkeypatch) -> None:
    from colleague.config import EngineConfig

    monkeypatch.delenv("COLLEAGUE_MEMORY_DISTILL", raising=False)
    assert EngineConfig().resolve(repo_path=str(tmp_path)).memory_distill is True
    monkeypatch.setenv("COLLEAGUE_MEMORY_DISTILL", "0")
    assert EngineConfig().resolve(repo_path=str(tmp_path)).memory_distill is False
    monkeypatch.delenv("COLLEAGUE_MEMORY_DISTILL", raising=False)
    (tmp_path / ".colleague").mkdir(exist_ok=True)
    (tmp_path / ".colleague" / "config.json").write_text('{"memory_distill": false}')
    assert EngineConfig().resolve(repo_path=str(tmp_path)).memory_distill is False


def test_split_next_time_record_written_when_steps_hit_the_cap(
    repo: Path, eidetic_log: Path
) -> None:
    """#416 c15/h10: a run that exhausts its steps leaves ONE split-next-time record
    beside the lesson, via the remember-after lane (never from step handling)."""
    never_finish = ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])
    result = run(
        scripted([never_finish]),
        Task.new(str(repo), "task"),
        max_steps=2,
        context=ContextControls(memory=True),
    )
    remember_calls = [c for c in _calls(eidetic_log) if c[0] == "remember"]
    kinds = [(json.loads(c[1]).get("metadata") or {}).get("kind") for c in remember_calls]
    assert "split-next-time" in kinds
    assert result.memory is not None
    assert result.memory["split_recorded"] is True

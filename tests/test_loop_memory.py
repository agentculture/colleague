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

from colleague.contract import OK, Task, TaskResult
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


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".eidetic" / "memory").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
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


def test_armed_run_recalls_injects_and_remembers(repo: Path, eidetic_log: Path) -> None:
    seen_messages: list[list[dict]] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen_messages.append([dict(m) for m in messages])
        return _FINISH

    task = Task.new(str(repo), "map the retry architecture")
    result = run(complete, task, max_steps=5, context=ContextControls(memory=True))

    assert result.status == OK
    calls = _calls(eidetic_log)
    recall_calls = [c for c in calls if c[0] == "recall"]
    remember_calls = [c for c in calls if c[0] == "remember"]
    assert len(recall_calls) == 1
    assert "--scope" in recall_calls[0] and "colleague" in recall_calls[0]
    assert len(remember_calls) == 1
    lesson = json.loads(remember_calls[0][1])
    assert lesson["id"] == f"work-lesson-{task.id}"
    assert task.id in lesson["text"] or "map the retry" in lesson["text"]
    # The recalled lessons were injected as advisory context before the first turn.
    first_turn = seen_messages[0]
    joined = json.dumps(first_turn)
    assert "GOTCHA: loop.py is the hot file" in joined
    # And the artifact records the whole exchange (h7: diagnosable, never silent).
    assert result.memory is not None
    assert result.memory["recalled"] == 2
    assert result.memory["injected_chars"] > 0
    assert result.memory["lesson_recorded"] is True
    assert result.to_dict()["memory"]["recalled"] == 2


def test_no_eidetic_dir_is_strict_noop(tmp_path: Path, monkeypatch) -> None:
    """A repo without .eidetic/ never spawns the CLI — byte-identical artifact."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "eidetic.log"
    _fake_eidetic(bin_dir, log, [{"text": "should never be read"}])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = run(
        scripted([_FINISH]),
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert result.status == OK
    assert _calls(log) == []
    assert result.memory is None
    assert "memory" not in result.to_dict()


def test_memory_disabled_is_strict_noop(repo: Path, eidetic_log: Path) -> None:
    """ContextControls.memory falsy → no subprocess even with a store present."""
    result = run(scripted([_FINISH]), Task.new(str(repo), "task"), max_steps=5)

    assert result.status == OK
    assert _calls(eidetic_log) == []
    assert result.memory is None


def test_recall_block_is_capped(repo: Path, tmp_path: Path, monkeypatch) -> None:
    """A huge recall result set injects at most the cap, never the firehose."""
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir()
    log = tmp_path / "eidetic2.log"
    _fake_eidetic(bin_dir, log, [{"text": "X" * 5000} for _ in range(10)])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    seen: list[int] = []

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append(sum(len(str(m.get("content", ""))) for m in messages))
        return _FINISH

    result = run(
        complete,
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert result.memory is not None
    assert result.memory["recalled"] == 10
    assert result.memory["injected_chars"] <= 4000


def test_lesson_recorded_even_on_incomplete_run(repo: Path, eidetic_log: Path) -> None:
    """A failed/partial run is the most valuable lesson — still remembered."""
    never_finish = ModelResponse(tool_calls=[ToolCall("x", "list_dir", {"path": "."})])
    result = run(
        scripted([never_finish]),
        Task.new(str(repo), "task"),
        max_steps=2,
        context=ContextControls(memory=True),
    )

    remember_calls = [c for c in _calls(eidetic_log) if c[0] == "remember"]
    assert len(remember_calls) == 1
    lesson = json.loads(remember_calls[0][1])
    assert "incomplete" in lesson["text"].lower()
    assert result.memory is not None and result.memory["lesson_recorded"] is True


def test_memory_root_targets_durable_store(repo: Path, eidetic_log: Path, tmp_path: Path) -> None:
    """An isolated run's lessons land in the OPERATOR repo, not the worktree.

    ``repo`` (with .eidetic) plays the operator root via ``memory_root``; the
    task's own repo_path is a store-less stand-in for the throwaway worktree —
    without the root override memory would not even arm, and a lesson written
    to the worktree would be reaped with it (caught live on the first smoke run).
    """
    worktree = tmp_path / "iso-worktree"
    worktree.mkdir()
    task = Task.new(str(worktree), "isolated work")
    result = run(
        scripted([_FINISH]),
        task,
        max_steps=5,
        context=ContextControls(memory=True, memory_root=str(repo)),
    )

    calls = _calls(eidetic_log)
    assert [c[0] for c in calls] == ["recall", "remember"]
    # THE point of memory_root: both CLI invocations run with cwd at the
    # durable operator root, never the throwaway worktree (the live-smoke bug).
    assert all(cwd == str(repo) for cwd in _cwds(eidetic_log))
    assert result.memory is not None and result.memory["lesson_recorded"] is True


def test_memory_field_round_trips() -> None:
    r = TaskResult(task_id="x", status=OK, memory={"recalled": 2, "lesson_recorded": True})
    assert TaskResult.from_dict(r.to_dict()).memory == {"recalled": 2, "lesson_recorded": True}
    bare = TaskResult(task_id="x", status=OK)
    assert "memory" not in bare.to_dict()


# ---------------------------------------------------------------------------
# Embedder env overrides (one-embedder increment, S2, colleague#291/#292 t19):
# ContextControls.embed_env reaches the eidetic subprocess env end-to-end,
# threaded through the SAME recall-before/remember-after call sites.
# ---------------------------------------------------------------------------


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


def test_embed_env_reaches_eidetic_subprocess_end_to_end(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """ContextControls.embed_env (S2) flows through _Work into BOTH the
    recall-before and remember-after eidetic shell-outs — the SAME endpoint
    colleague resolved reaches the child's environment."""
    bin_dir = tmp_path / "bin_embed"
    bin_dir.mkdir()
    log = tmp_path / "embed.log"
    monkeypatch.delenv("EIDETIC_EMBED_URL", raising=False)
    _fake_eidetic_capturing_env(bin_dir, log, "EIDETIC_EMBED_URL")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = run(
        scripted([_FINISH]),
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(
            memory=True,
            embed_env={"EIDETIC_EMBED_URL": "http://embed-host:9000/v1"},
        ),
    )

    assert result.status == OK
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    verbs = [line["argv"][0] for line in lines]
    assert verbs == ["recall", "remember"]
    assert all(line["env_value"] == "http://embed-host:9000/v1" for line in lines)


def test_embed_env_operator_set_var_survives_end_to_end(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """An operator-exported EIDETIC_EMBED_URL is never overwritten by a
    lobes-discovered embed_env override, even threaded through the full loop."""
    bin_dir = tmp_path / "bin_embed2"
    bin_dir.mkdir()
    log = tmp_path / "embed2.log"
    monkeypatch.setenv("EIDETIC_EMBED_URL", "http://operator-set:1234/v1")
    _fake_eidetic_capturing_env(bin_dir, log, "EIDETIC_EMBED_URL")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = run(
        scripted([_FINISH]),
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(
            memory=True,
            embed_env={"EIDETIC_EMBED_URL": "http://lobes-discovered:9000/v1"},
        ),
    )

    assert result.status == OK
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(line["env_value"] == "http://operator-set:1234/v1" for line in lines)


def test_absent_embed_env_is_byte_identical(repo: Path, eidetic_log: Path) -> None:
    """No embed_env set (the default) reproduces today's argv exactly — the
    embedder wiring is a strict no-op when dormant."""
    result = run(
        scripted([_FINISH]),
        Task.new(str(repo), "task"),
        max_steps=5,
        context=ContextControls(memory=True),
    )
    assert result.status == OK
    calls = _calls(eidetic_log)
    assert [c[0] for c in calls] == ["recall", "remember"]


def test_eidetic_only_changes_do_not_read_as_dirty(tmp_path: Path) -> None:
    """Store reinforcement/lessons never block the next run (#149 stays for real WIP)."""
    import subprocess

    from colleague.handoff import working_tree_dirty

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True
    )
    store = tmp_path / ".eidetic" / "memory"
    store.mkdir(parents=True)
    (store / "colleague__public.jsonl").write_text("{}\n")
    (tmp_path / "code.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    # A memory-armed run's own store churn: not dirty.
    (store / "colleague__public.jsonl").write_text('{"id": "work-lesson-x"}\n')
    assert working_tree_dirty(tmp_path) is False
    # Real operator WIP on a tracked file: still dirty (#149 unchanged).
    (tmp_path / "code.py").write_text("x = 2\n")
    assert working_tree_dirty(tmp_path) is True


# ── lesson-grade remember-after, rung 1 (#379) ──────────────────────────────


def _result_for_lesson(**kw):
    from colleague.contract import TaskResult

    base = dict(task_id="t379", status="incomplete", summary="")
    base.update(kw)
    return TaskResult(**base)


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


# ── rung 1.5: fold lint / test-integrity / affected-tests reports (#379) ──


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


# ── Rung 2: the distillation seam (t9 — spec c2/h2, c28/h23, c29/h24) ────────


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


def test_distill_valid_lesson_folds_into_record(repo: Path, eidetic_log: Path) -> None:
    raw = (
        '{"cause": "wrong file", "lesson": "check imports first", "next_delta": "grep before edit"}'
    )
    task, result = _armed_distill_run(repo, lambda res, head: raw)
    record = _remembered_record(eidetic_log)
    assert "Lesson (origin=model)" in record["text"]
    assert "check imports first" in record["text"]
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
    assert set(result.memory) == {"query", "recalled", "injected_chars", "lesson_recorded"}


def test_no_distill_fn_is_byte_identical_rung1(repo: Path, eidetic_log: Path) -> None:
    task = Task.new(str(repo), "no seam present")
    result = run(scripted([_FINISH]), task, max_steps=5, context=ContextControls(memory=True))
    record = _remembered_record(eidetic_log)
    assert "distill" not in record["metadata"]
    assert set(result.memory) == {"query", "recalled", "injected_chars", "lesson_recorded"}


def test_parse_lesson_json_tolerant_extraction() -> None:
    from colleague.lessons import parse_lesson_json

    fenced = 'Here it is:\n```json\n{"cause": "a", "lesson": "b", "next_delta": "c"}\n```\ndone'
    assert parse_lesson_json(fenced) == {"cause": "a", "lesson": "b", "next_delta": "c"}
    assert parse_lesson_json("no json here") is None
    assert parse_lesson_json('{"truncated": ') is None


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

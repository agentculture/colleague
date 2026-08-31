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
    # max_steps=2 also trips the #416 split-next-time record (steps at cap) — the
    # LESSON count stays exactly one; the split record is a separate, intended call.
    lessons = [
        c
        for c in remember_calls
        if (json.loads(c[1]).get("metadata") or {}).get("kind") != "split-next-time"
    ]
    assert len(lessons) == 1
    lesson = json.loads(lessons[0][1])
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


def test_task_class_key_is_deterministic_and_slugged() -> None:
    """The rule is a pure function of the assignment text — no judgment, no I/O."""
    from colleague.memory import task_class_key

    first = task_class_key("Fix the retry backoff")
    assert first == "fix-the-retry-backoff"
    # Same text ⇒ same key even after a DIFFERENT assignment is keyed in
    # between: repeating the call verbatim would hold for any deterministic
    # function, so interleaving is what actually proves no state leaks
    # between calls.
    task_class_key("an entirely unrelated assignment")
    assert task_class_key("Fix the retry backoff") == first
    # Case and punctuation are normalized away; a different assignment differs.
    assert task_class_key("  FIX  the/retry, backoff!  ") == "fix-the-retry-backoff"
    assert task_class_key("Fix the timeout classification") != task_class_key("Fix the retry")
    # Bounded: at most 8 tokens, at most 64 chars.
    long_key = task_class_key(" ".join(f"tok{i}" for i in range(50)))
    assert long_key == "tok0-tok1-tok2-tok3-tok4-tok5-tok6-tok7"
    assert len(task_class_key("x" * 200)) <= 64
    # Unscoreable text yields the empty key (the caller then adds no fields).
    assert task_class_key("") == ""
    assert task_class_key("   ...   ") == ""


def test_record_class_key_reads_exactly_two_declared_places() -> None:
    """No substring match, no score threshold — exact equality on a stamped key."""
    from colleague.memory import record_class_key

    assert record_class_key({"metadata": {"class_key": "fix-the-retry"}}) == "fix-the-retry"
    assert record_class_key({"class_key": "fix-the-retry"}) == "fix-the-retry"
    # metadata wins over the flattened fallback.
    assert record_class_key({"metadata": {"class_key": "a"}, "class_key": "b"}) == "a"
    # Anything else reads as "" — an unstamped record is simply not relevant.
    assert record_class_key({"text": "a lesson"}) == ""
    assert record_class_key({"metadata": "not-a-dict"}) == ""
    assert record_class_key({"metadata": {"class_key": 7}}) == ""
    assert record_class_key("not a record") == ""  # type: ignore[arg-type]


def test_score_recall_precision_hit_miss_and_rank() -> None:
    """The scoring rule, in isolation: counts, top-k outcome, 1-based rank."""
    from colleague.memory import CLASS_KEY_RULE, score_recall_precision

    key = "fix-the-retry-backoff"
    miss = score_recall_precision([{"text": "unrelated"}, {"text": "also unrelated"}], key)
    assert miss == {
        "class_key": key,
        "precision_rule": CLASS_KEY_RULE,
        "class_relevant_recalled": 0,
        "class_relevant_in_top_k": False,
    }
    assert "class_relevant_rank" not in miss  # omitted, never null

    hit = score_recall_precision(
        [
            {"text": "noise"},
            {"text": "the lesson", "metadata": {"class_key": key}},
            {"text": "another", "metadata": {"class_key": key}},
        ],
        key,
    )
    assert hit["class_relevant_recalled"] == 2
    assert hit["class_relevant_in_top_k"] is True
    assert hit["class_relevant_rank"] == 2  # 1-based rank of the FIRST match

    # An empty recall still scores honestly (0 / False), never silently absent.
    assert score_recall_precision([], key)["class_relevant_in_top_k"] is False
    # An unscoreable work item adds NO fields rather than a meaningless zero.
    assert score_recall_precision([{"metadata": {"class_key": ""}}], "") == {}


def test_armed_run_records_precision_miss_when_no_class_lesson(
    repo: Path, eidetic_log: Path
) -> None:
    """Store holds lessons, none of this class ⇒ the artifact says so, loudly."""
    task = Task.new(str(repo), "map the retry architecture")
    result = run(scripted([_FINISH]), task, max_steps=5, context=ContextControls(memory=True))

    from colleague.memory import CLASS_KEY_RULE, task_class_key

    assert result.memory is not None
    assert result.memory["recalled"] == 2
    assert result.memory["class_key"] == task_class_key("map the retry architecture")
    assert result.memory["precision_rule"] == CLASS_KEY_RULE
    assert result.memory["class_relevant_recalled"] == 0
    assert result.memory["class_relevant_in_top_k"] is False
    assert "class_relevant_rank" not in result.memory
    # And it survives the artifact round-trip.
    assert result.to_dict()["memory"]["class_relevant_in_top_k"] is False


def test_armed_run_records_precision_hit_from_recorded_recall_results(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """A class-stamped record in the top-k scores a hit at its real rank."""
    from colleague.memory import task_class_key

    instruction = "fix the timeout classification in beta.py"
    key = task_class_key(instruction)
    bin_dir = tmp_path / "bin-hit"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-hit.log"
    _fake_eidetic(
        bin_dir,
        log,
        [
            {"text": "unrelated lesson", "metadata": {"class_key": "some-other-class"}},
            {"text": "the class lesson", "metadata": {"class_key": key}},
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = run(
        scripted([_FINISH]),
        Task.new(str(repo), instruction),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert result.memory is not None
    assert result.memory["class_key"] == key
    assert result.memory["class_relevant_recalled"] == 1
    assert result.memory["class_relevant_in_top_k"] is True
    assert result.memory["class_relevant_rank"] == 2


def test_goal_wins_over_instruction_for_the_class_key(repo: Path, eidetic_log: Path) -> None:
    """The class key keys off the SAME text the recall query does (goal first)."""
    from colleague.memory import task_class_key

    task = Task.new(str(repo), "an instruction nobody scores on")
    task.goal = "converge the backoff multiplier"
    result = run(scripted([_FINISH]), task, max_steps=5, context=ContextControls(memory=True))

    assert result.memory is not None
    assert result.memory["query"] == "converge the backoff multiplier"
    assert result.memory["class_key"] == task_class_key("converge the backoff multiplier")


def test_remember_stamps_the_class_key_recall_matches_on(
    repo: Path, eidetic_log: Path, tmp_path: Path, monkeypatch
) -> None:
    """The loop closes: run N's stamp is exactly what run N+1 scores against.

    This is what makes the measurement real rather than synthetic — the
    stamped record is fed back through the recall path verbatim.
    """
    from colleague.memory import task_class_key

    instruction = "harden the retry backoff multiplier"
    run(
        scripted([_FINISH]),
        Task.new(str(repo), instruction),
        max_steps=5,
        context=ContextControls(memory=True),
    )
    stamped = _remembered_record(eidetic_log)
    assert stamped["metadata"]["class_key"] == task_class_key(instruction)

    # Feed run N's REAL stored record back as run N+1's recall result.
    bin_dir = tmp_path / "bin-loop"
    bin_dir.mkdir()
    log2 = tmp_path / "eidetic-loop.log"
    _fake_eidetic(bin_dir, log2, [stamped])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    second = run(
        scripted([_FINISH]),
        Task.new(str(repo), instruction),
        max_steps=5,
        context=ContextControls(memory=True),
    )
    assert second.memory is not None
    assert second.memory["class_relevant_in_top_k"] is True
    assert second.memory["class_relevant_rank"] == 1

    # A DIFFERENT class recalling the same record scores an honest miss.
    third = run(
        scripted([_FINISH]),
        Task.new(str(repo), "write the changelog entry"),
        max_steps=5,
        context=ContextControls(memory=True),
    )
    assert third.memory is not None
    assert third.memory["class_relevant_in_top_k"] is False


def test_memory_less_run_serializes_byte_identically(tmp_path: Path, monkeypatch) -> None:
    """THE regression guard: no store ⇒ not one precision key reaches the artifact."""
    bin_dir = tmp_path / "bin-none"
    bin_dir.mkdir()
    log = tmp_path / "eidetic-none.log"
    _fake_eidetic(bin_dir, log, [{"text": "should never be read"}])
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    store_less = tmp_path / "repo"
    store_less.mkdir()

    result = run(
        scripted([_FINISH]),
        Task.new(str(store_less), "a task with no store behind it"),
        max_steps=5,
        context=ContextControls(memory=True),
    )

    assert _calls(log) == []
    assert result.memory is None
    payload = result.to_dict()
    assert "memory" not in payload
    serialized = json.dumps(payload)
    for key in _PRECISION_KEYS:
        assert key not in serialized
    # The whole artifact round-trips with the memory key still absent.
    assert "memory" not in TaskResult.from_dict(payload).to_dict()


def test_unscoreable_task_adds_no_precision_fields(repo: Path, eidetic_log: Path) -> None:
    """An empty assignment text is unscoreable — honest silence, not a fake zero."""
    task = Task.new(str(repo), "   ")
    result = run(scripted([_FINISH]), task, max_steps=5, context=ContextControls(memory=True))

    assert result.memory is not None
    assert set(result.memory) == {"query", "recalled", "injected_chars", "lesson_recorded"}
    assert "class_key" not in _remembered_record(eidetic_log)["metadata"]


def test_class_relevance_rule_is_documented_in_the_feature_doc() -> None:
    """The rule must be AUDITABLE: the feature doc states it, and cannot drift."""
    from colleague.memory import CLASS_KEY_FIELD, CLASS_KEY_RULE

    doc = (Path(__file__).resolve().parents[1] / "docs" / "features" / "memory.md").read_text()
    assert CLASS_KEY_RULE in doc, "the versioned rule id must be named in the feature doc"
    assert CLASS_KEY_FIELD in doc, "the stamped metadata field must be named in the feature doc"
    for field_name in sorted(_PRECISION_KEYS):
        assert field_name in doc, f"{field_name} is undocumented in docs/features/memory.md"
    # The pre-declared / not-a-judgment property is stated, not merely implied.
    assert "pre-declared" in doc.lower()

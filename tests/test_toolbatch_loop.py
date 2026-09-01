"""Batched tool execution in the loop (plan adopt-from-qwen-code t15; spec c6/h4, c35/h24, c36/h25).

The pins: gates run on the main thread in request order BEFORE the pool; only
``executor.execute`` runs inside it; step indices, Step/tool-message appends,
post_tool hooks and progress emits land in request order after the join; one
error never cancels its siblings; a flight stop written mid-batch takes effect
before the NEXT batch; width 1 is byte-identical to the sequential loop.
"""

from __future__ import annotations

import ast
import inspect
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from colleague import flight as flightmod
from colleague import loop as loopmod
from colleague import toolbatch, toolbatch_loop
from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run
from colleague.tools import ToolError, ToolExecutor, ToolOutcome


class _SpyExecutor(ToolExecutor):
    """A repo-confined executor that records execution order + overlap and can sleep/fail."""

    def __init__(
        self, root: Path, *, sleeps: dict[str, float] | None = None, fail: set[str] = frozenset()
    ):
        super().__init__(root)
        self.sleeps = sleeps or {}
        self.fail = set(fail)
        self.started: list[str] = []
        self.finished: list[str] = []
        self.max_overlap = 0
        self._active = 0
        self._lock = threading.Lock()
        self.threads: dict[str, int] = {}

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name == "finish":
            return super().execute(name, arguments)
        key = str(arguments.get("path", arguments.get("command", name)))
        with self._lock:
            self.started.append(key)
            self._active += 1
            self.max_overlap = max(self.max_overlap, self._active)
            self.threads[key] = threading.get_ident()
        try:
            time.sleep(self.sleeps.get(key, 0.0))
            if key in self.fail:
                raise ToolError(f"boom for {key}")
            return super().execute(name, arguments)
        finally:
            with self._lock:
                self._active -= 1
                self.finished.append(key)


def _scripted(responses: list[ModelResponse]):
    state = {"i": 0}

    def complete(_messages: list[dict]) -> ModelResponse:
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _repo(tmp_path: Path) -> Path:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(f"{name} body\n")
    return tmp_path


def _reads(*names: str) -> list[ToolCall]:
    return [ToolCall(f"id-{n}", "read_file", {"path": n}) for n in names]


_FINISH = ModelResponse(tool_calls=[ToolCall("fin", "finish", {"summary": "done"})])


def test_inverted_sleeps_land_in_request_order_and_run_in_parallel(
    tmp_path: Path, monkeypatch
) -> None:
    """Sleeps 0.3/0.2/0.1: finish order inverts, steps stay in request order."""
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    executor = _SpyExecutor(_repo(tmp_path), sleeps={"a.txt": 0.3, "b.txt": 0.2, "c.txt": 0.1})
    task = Task.new(str(tmp_path), "read three files")
    started = time.monotonic()
    result = run(
        _scripted([ModelResponse(tool_calls=_reads("a.txt", "b.txt", "c.txt")), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
    )
    elapsed = time.monotonic() - started
    assert result.status == OK
    reads_done = [k for k in executor.finished if k.endswith(".txt")]
    assert reads_done == ["c.txt", "b.txt", "a.txt"], "completion order inverted (parallel)"
    assert executor.max_overlap == 3
    assert elapsed < 0.55, f"batch took {elapsed:.2f}s — not parallel"
    steps = [s for s in result.steps if s.tool == "read_file"]
    assert [s.index for s in steps] == [0, 1, 2]
    assert [s.arguments["path"] for s in steps] == ["a.txt", "b.txt", "c.txt"]
    tool_msgs = [m for m in result_messages(result) if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs][:3] == ["id-a.txt", "id-b.txt", "id-c.txt"]
    # the pool did the executing, the main thread did the bookkeeping
    assert len(set(executor.threads.values())) >= 2


def result_messages(result) -> list[dict]:
    """The wire-shaped messages the loop appended (from the artifact's step trace)."""
    return [
        {"role": "tool", "tool_call_id": f"id-{s.arguments.get('path')}", "content": s.result}
        for s in result.steps
        if s.tool == "read_file"
    ]


def test_ok_error_ok_batch_yields_three_ordered_steps_with_one_non_ok(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    executor = _SpyExecutor(_repo(tmp_path), fail={"b.txt"})
    task = Task.new(str(tmp_path), "read three files")
    result = run(
        _scripted([ModelResponse(tool_calls=_reads("a.txt", "b.txt", "c.txt")), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
    )
    steps = [s for s in result.steps if s.tool == "read_file"]
    assert [s.ok for s in steps] == [True, False, True]
    assert steps[1].result.startswith("error: boom for b.txt")
    assert [s.index for s in steps] == [0, 1, 2]
    assert sorted(executor.started) == [
        "a.txt",
        "b.txt",
        "c.txt",
    ], "an error never cancels siblings"
    assert result.status == OK


def test_mutating_call_splits_the_batch_and_runs_alone(tmp_path: Path, monkeypatch) -> None:
    """[read, read, write, read] → [[read, read] ‖, [write], [read]] — the write never overlaps."""
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    executor = _SpyExecutor(
        _repo(tmp_path), sleeps={"a.txt": 0.15, "b.txt": 0.15, "new.txt": 0.05, "c.txt": 0.05}
    )
    calls = [
        *_reads("a.txt", "b.txt"),
        ToolCall("w", "write_file", {"path": "new.txt", "content": "x"}),
        *_reads("c.txt"),
    ]
    task = Task.new(str(tmp_path), "mixed turn")
    result = run(
        _scripted([ModelResponse(tool_calls=calls), _FINISH]), task, max_steps=10, executor=executor
    )
    assert result.status == OK
    assert executor.started[:2] in (["a.txt", "b.txt"], ["b.txt", "a.txt"])
    assert executor.started[2:] == [
        "new.txt",
        "c.txt",
    ], "the write and the trailing read stay sequential"
    assert executor.finished.index("new.txt") > max(
        executor.finished.index("a.txt"), executor.finished.index("b.txt")
    )
    assert [s.tool for s in result.steps][:4] == [
        "read_file",
        "read_file",
        "write_file",
        "read_file",
    ]


def test_read_only_run_command_batches_but_a_mutating_one_does_not() -> None:
    safe = ToolCall("1", "run_command", {"command": "ls -la"})
    unsafe = ToolCall("2", "run_command", {"command": "rm -rf build"})
    read = ToolCall("3", "read_file", {"path": "a.txt"})
    batches = toolbatch.partition_by_concurrency_safety(
        [safe, read, unsafe, read], toolbatch_loop.is_batch_safe
    )
    assert [[c.id for c in b] for b in batches] == [["1", "3"], ["2"], ["3"]]


def test_policy_denied_call_inside_a_batch_is_recorded_in_request_order_and_never_executed(
    tmp_path: Path, monkeypatch
) -> None:
    """Gates run on the main thread before the pool: the denied middle call gets its
    non-ok step at index 1, the executor never sees it."""
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    from colleague.policy import Policy

    class _DenyCat(Policy):
        def check_run_command(self, command: str):
            verdict = super().check_run_command(command)
            if command.startswith("cat"):
                return type(verdict)(allowed=False, reason="denied by policy: cat")
            return verdict

    executor = _SpyExecutor(_repo(tmp_path))
    calls = [
        ToolCall("1", "run_command", {"command": "ls"}),
        ToolCall("2", "run_command", {"command": "cat a.txt"}),
        *_reads("b.txt"),
    ]
    task = Task.new(str(tmp_path), "gated batch")
    result = run(
        _scripted([ModelResponse(tool_calls=calls), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
        policy=_DenyCat(),
    )
    steps = result.steps[:3]
    assert [s.ok for s in steps] == [True, False, True]
    assert steps[1].result == "denied by policy: cat"
    assert steps[1].index == 1
    assert "cat a.txt" not in executor.started


def test_flight_stop_written_mid_batch_takes_effect_before_the_next_batch(
    tmp_path: Path, monkeypatch
) -> None:
    """Batch 1 (two reads) writes the stop file from inside a tool; batch 2 (a write) and
    batch 3 (a read) are recorded as skipped non-ok steps; the run ends on the stop."""
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    repo = _repo(tmp_path)
    task = Task.new(str(repo), "stop mid-turn", watch=True)
    control = flightmod.control_path(str(repo), task.id)

    class _StopWriter(_SpyExecutor):
        def execute(self, name, arguments):
            outcome = super().execute(name, arguments)
            control.parent.mkdir(parents=True, exist_ok=True)
            control.write_text(json.dumps({"stop": True, "guidance": ["hello"]}))
            return outcome

    executor = _StopWriter(repo)
    calls = [
        *_reads("a.txt", "b.txt"),
        ToolCall("w", "write_file", {"path": "n.txt", "content": "x"}),
        *_reads("c.txt"),
    ]
    result = run(
        _scripted([ModelResponse(tool_calls=calls), _FINISH]), task, max_steps=10, executor=executor
    )
    assert [s.tool for s in result.steps] == ["read_file", "read_file", "write_file", "read_file"]
    assert [s.ok for s in result.steps] == [True, True, False, False]
    assert result.steps[2].result == toolbatch_loop.STOP_SKIPPED
    assert "n.txt" not in executor.started
    assert not (repo / "n.txt").exists()
    assert result.status != OK, "the turn-boundary stop check still ends the run"
    assert (
        result.stats.step_count == 4
    ), "the artifact carries the completed batch + the skipped calls"


def test_width_one_is_the_sequential_path_and_never_builds_a_pool(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "1")

    def _explode(*a, **k):  # pragma: no cover - the assertion is that this never runs
        raise AssertionError("ThreadPoolExecutor instantiated at width 1")

    monkeypatch.setattr(toolbatch, "ThreadPoolExecutor", _explode)
    parallel_calls: list[Any] = []
    monkeypatch.setattr(
        toolbatch_loop, "_run_parallel_batch", lambda *a, **k: parallel_calls.append(a) or False
    )
    executor = _SpyExecutor(_repo(tmp_path))
    task = Task.new(str(tmp_path), "sequential")
    result = run(
        _scripted([ModelResponse(tool_calls=_reads("a.txt", "b.txt", "c.txt")), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
    )
    assert result.status == OK
    assert parallel_calls == []
    assert executor.max_overlap == 1
    assert executor.started == ["a.txt", "b.txt", "c.txt"]
    assert len({t for t in executor.threads.values()}) == 1


def test_width_one_and_width_ten_produce_identical_steps_and_messages(
    tmp_path: Path, monkeypatch
) -> None:
    """The batch path records exactly what the sequential path records (same helpers)."""
    traces = {}
    for width in ("1", "10"):
        monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", width)
        (tmp_path / width).mkdir()
        repo = _repo(tmp_path / width)
        executor = _SpyExecutor(repo, fail={"b.txt"})
        task = Task.new(str(repo), "same turn")
        calls = [
            *_reads("a.txt", "b.txt", "c.txt"),
            ToolCall("w", "write_file", {"path": "n.txt", "content": "x"}),
        ]
        result = run(
            _scripted([ModelResponse(tool_calls=calls), _FINISH]),
            task,
            max_steps=10,
            executor=executor,
        )
        traces[width] = [(s.index, s.tool, s.arguments, s.result, s.ok) for s in result.steps]
    assert traces["1"] == traces["10"]


def test_unset_knob_defaults_to_ten_and_garbage_falls_back(monkeypatch) -> None:
    monkeypatch.delenv("COLLEAGUE_TOOL_CONCURRENCY", raising=False)
    assert toolbatch_loop.concurrency_width() == 10
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "0")
    assert toolbatch_loop.concurrency_width() == 1
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "nope")
    assert toolbatch_loop.concurrency_width() == 10


def _names_in(fn) -> set[str]:
    tree = ast.parse(inspect.getsource(fn))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return names | attrs


def test_ast_guard_the_pool_target_references_no_loop_state() -> None:
    """Neither the pool target nor the execute primitive names ``ctx`` or ``_Work``."""
    for fn in (toolbatch_loop._execute_item, loopmod._execute_tool):
        seen = _names_in(fn)
        assert "ctx" not in seen, f"{fn.__name__} touches loop state: {seen & {'ctx', '_Work'}}"
        assert "_Work" not in seen, f"{fn.__name__} touches loop state: {seen & {'ctx', '_Work'}}"
    source = inspect.getsource(toolbatch_loop)
    assert "concurrent.futures" not in source
    assert "import threading" not in source
    assert "ThreadPoolExecutor" not in Path(loopmod.__file__).read_text()


def test_thread_allowlist_and_claude_md_record_convention_change_six() -> None:
    boundary = Path(__file__).with_name("test_boundary.py").read_text()
    assert '"colleague/toolbatch.py"' in boundary
    assert "convention change (6)" in boundary
    claude = (Path(__file__).resolve().parent.parent / "CLAUDE.md").read_text()
    assert "Seven deliberate, **recorded** convention changes" in claude
    assert "(6)" in claude
    assert "COLLEAGUE_TOOL_CONCURRENCY" in claude
    assert "toolbatch_loop.py" in claude


def test_stop_peek_does_not_consume_guidance(tmp_path: Path) -> None:
    session = flightmod.arm(str(tmp_path), "t-1")
    flightmod.control_path(str(tmp_path), "t-1").write_text(
        json.dumps({"stop": True, "guidance": ["g1"]})
    )

    class _Ctx:
        flight = session

    assert toolbatch_loop.stop_requested(_Ctx()) is True
    assert session.read_control().guidance == ["g1"], "the peek left the guidance cursor alone"
    assert toolbatch_loop.stop_requested(type("C", (), {"flight": None})()) is False


def test_tool_span_is_opened_exactly_once_per_call_in_a_batch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    from colleague.telemetry import Telemetry

    opened: list[tuple[str, int]] = []
    telemetry = Telemetry.disabled() if hasattr(Telemetry, "disabled") else Telemetry()
    real = telemetry.tool_span

    def spy(*, tool, step_index):
        opened.append((tool, step_index))
        return real(tool=tool, step_index=step_index)

    monkeypatch.setattr(telemetry, "tool_span", spy)
    executor = _SpyExecutor(_repo(tmp_path))
    task = Task.new(str(tmp_path), "spans")
    run(
        _scripted([ModelResponse(tool_calls=_reads("a.txt", "b.txt", "c.txt")), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
        telemetry=telemetry,
    )
    assert opened == [("read_file", 0), ("read_file", 1), ("read_file", 2), ("finish", 3)]


@pytest.mark.parametrize("width", ["1", "10"])
def test_mock_style_multi_call_turn_finishes_and_counts_steps(
    tmp_path: Path, monkeypatch, width: str
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", width)
    executor = _SpyExecutor(_repo(tmp_path))
    task = Task.new(str(tmp_path), "count")
    result = run(
        _scripted([ModelResponse(tool_calls=_reads("a.txt", "b.txt")), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
    )
    assert result.status == OK
    assert result.stats.step_count == 3


def test_pre_tool_rewrite_into_a_mutating_command_is_demoted_out_of_the_pool(
    tmp_path: Path, monkeypatch
) -> None:
    """Qodo #441-13: the partition saw `cat a.txt` (batch-safe); a pre_tool hook
    rewrites it into `touch mutated.txt` (mutating) — it must run, but never in
    the pool: sequentially on the main thread, after the parallel reads, with its
    step still recorded in request order."""
    import stat

    from colleague.hooks import HookConfig, HookEntry

    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    script = tmp_path / "rewrite.sh"
    script.write_text(
        "#!/bin/sh\n"
        'echo \'{"decision": "rewrite", "arguments": {"command": "touch mutated.txt"}}\'\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    hooks = HookConfig(
        _entries={
            "pre_tool": [HookEntry(event="pre_tool", matcher="run_command", command=str(script))]
        }
    )
    executor = _SpyExecutor(_repo(tmp_path), sleeps={"b.txt": 0.1, "c.txt": 0.1})
    calls = [ToolCall("1", "run_command", {"command": "cat a.txt"}), *_reads("b.txt", "c.txt")]
    task = Task.new(str(tmp_path), "rewritten batch")
    result = run(
        _scripted([ModelResponse(tool_calls=calls), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
        hooks=hooks,
    )
    assert result.status == OK
    assert (tmp_path / "mutated.txt").exists(), "the rewritten command did run"
    assert "cat a.txt" not in executor.started, "the pre-rewrite command never ran"
    assert executor.threads["touch mutated.txt"] == threading.get_ident(), "never in the pool"
    assert executor.started.index("touch mutated.txt") > max(
        executor.started.index("b.txt"), executor.started.index("c.txt")
    ), "demoted: runs after the parallel part"
    assert [s.tool for s in result.steps][:3] == ["run_command", "read_file", "read_file"]
    assert result.steps[0].arguments == {"command": "touch mutated.txt"}


# ---------------------------------------------------------------------------
# t18 (Qodo #4/#8 on PR #444) — the web in-flight cap + budget move OFF a
# worker-side threading.Semaphore / unsynchronised check-then-increment onto
# the MAIN thread: _apply_web_budget (before the pool), _web_capped_waves /
# _run_web_capped (sequential waves through the pool), _record_web_failures
# (after the join). Unit tests exercise these directly with fakes — a batch
# that goes through the REAL colleague.web_schemas.dispatch would double-count
# the budget here, because dispatch's own "_budget_counted" skip is t16's
# change and is not present in this worktree; the one integration test below
# stands in a fake 'web' executor for exactly that reason.
# ---------------------------------------------------------------------------


class _FakeWebExecutor:
    """Bare stand-in for ToolExecutor's three web-budget counters — enough for
    colleague.webbudget.check_and_increment/record_result, nothing else."""

    def __init__(self) -> None:
        self.web_calls = 0
        self.web_failed = 0
        self.web_cap_hit = None


def _prepared(name: str, arguments: dict) -> Any:
    return toolbatch_loop._Prepared(ToolCall("id", name, arguments), dict(arguments), None, False)


class TestApplyWebBudget:
    def test_refuses_past_the_cap_and_stamps_submitted_items(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_WEB_MAX_CALLS", "20")
        executor = _FakeWebExecutor()
        prepared = [
            _prepared("web", {"verb": "page open", "url": f"https://x/{i}"}) for i in range(25)
        ]
        submitted = toolbatch_loop._apply_web_budget(executor, prepared)
        assert len(submitted) == 20
        assert executor.web_calls == 20
        refused = [p for p in prepared if p not in submitted]
        assert len(refused) == 5
        for item in refused:
            assert isinstance(item.exc, ToolError)
            assert "web budget reached" in str(item.exc)
            assert item.outcome is None
        for item in submitted:
            assert item.arguments["_budget_counted"] is True

    def test_non_web_items_pass_through_untouched(self) -> None:
        executor = _FakeWebExecutor()
        prepared = [_prepared("read_file", {"path": "a"})]
        submitted = toolbatch_loop._apply_web_budget(executor, prepared)
        assert submitted == prepared
        assert executor.web_calls == 0
        assert "_budget_counted" not in submitted[0].arguments


class TestWebCappedWaves:
    def test_five_page_items_split_three_and_two(self) -> None:
        items = [(None, "web", {"verb": "page open"}) for _ in range(5)]
        waves = toolbatch_loop._web_capped_waves(items, cap=3)
        assert [len(w) for w in waves] == [3, 2]

    def test_non_page_items_are_never_split(self) -> None:
        items = [(None, "read_file", {"path": "a"}) for _ in range(5)]
        waves = toolbatch_loop._web_capped_waves(items, cap=1)
        assert waves == [items]

    def test_search_items_are_never_split(self) -> None:
        items = [(None, "web", {"verb": "search"}) for _ in range(5)]
        waves = toolbatch_loop._web_capped_waves(items, cap=1)
        assert waves == [items]


class TestRunWebCapped:
    def test_five_page_reads_never_more_than_three_in_flight(self, monkeypatch) -> None:
        monkeypatch.setenv(toolbatch.ENV_WEB_CONCURRENCY, "3")
        lock = threading.Lock()
        in_flight = 0
        max_seen = 0
        call_count = 0

        def fake_execute(item: tuple) -> tuple:
            nonlocal in_flight, max_seen, call_count
            with lock:
                in_flight += 1
                max_seen = max(max_seen, in_flight)
                call_count += 1
            time.sleep(0.05)
            with lock:
                in_flight -= 1
            return (item[2].get("url"), None, 0.0)

        monkeypatch.setattr(toolbatch_loop, "_execute_item", fake_execute)
        items = [(None, "web", {"verb": "page open", "url": f"https://x/{i}"}) for i in range(5)]
        results = toolbatch_loop._run_web_capped(items, width=10)
        assert call_count == 5
        assert max_seen <= 3, f"saw {max_seen} concurrent web page calls, cap is 3"
        assert [r[0] for r in results] == [f"https://x/{i}" for i in range(5)]


class TestRecordWebFailures:
    def test_missing_success_header_and_exceptions_count_as_failed(self) -> None:
        executor = _FakeWebExecutor()
        ok_item = _prepared("web", {})
        ok_item.outcome = ToolOutcome(result="operation_id: x\nlifecycle_state: succeeded\nbody")
        bad_item = _prepared("web", {})
        bad_item.outcome = ToolOutcome(result="operation_id: y\nlifecycle_state: failed\nbody")
        exc_item = _prepared("web", {})
        exc_item.outcome, exc_item.exc = None, ToolError("boom")
        non_web = _prepared("read_file", {})
        non_web.outcome = ToolOutcome(result="lifecycle_state: succeeded")

        toolbatch_loop._record_web_failures(executor, [ok_item, bad_item, exc_item, non_web])
        assert executor.web_failed == 2


class _WebCapExecutor(ToolExecutor):
    """A repo-confined executor with a FAKE ``web`` handler standing in for
    ``colleague.web_schemas.dispatch`` (t18): this worktree does not have
    t16's dispatch-side ``_budget_counted`` skip, so exercising the real
    dispatch here would double-count the budget. This proves the MAIN-thread
    orchestration (wave cap + budget + failure bookkeeping) alone."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_overlap = 0

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name != "web":
            return super().execute(name, arguments)
        assert arguments.get("_budget_counted") is True, "main thread must stamp submitted items"
        with self._lock:
            self.in_flight += 1
            self.max_overlap = max(self.max_overlap, self.in_flight)
        try:
            time.sleep(0.03)
            url = arguments.get("url")
            return ToolOutcome(result=f"operation_id: {url}\nlifecycle_state: succeeded\nbody")
        finally:
            with self._lock:
                self.in_flight -= 1


def test_five_page_calls_through_the_real_loop_never_exceed_the_web_cap(
    tmp_path: Path, monkeypatch
) -> None:
    """Integration proof of the t18 acceptance criterion: 5 page reads batched
    through run() never run more than COLLEAGUE_WEB_CONCURRENCY concurrently,
    all 5 execute, and results land in request order."""
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    monkeypatch.setenv(toolbatch.ENV_WEB_CONCURRENCY, "3")
    executor = _WebCapExecutor(_repo(tmp_path))
    calls = [
        ToolCall(str(i), "web", {"verb": "page open", "url": f"https://x/{i}"}) for i in range(5)
    ]
    task = Task.new(str(tmp_path), "web batch")
    result = run(
        _scripted([ModelResponse(tool_calls=calls), _FINISH]),
        task,
        max_steps=10,
        executor=executor,
    )
    assert result.status == OK
    assert executor.max_overlap <= 3, f"saw {executor.max_overlap} concurrent web calls"
    assert executor.web_calls == 5
    web_steps = [s for s in result.steps if s.tool == "web"]
    assert [s.arguments.get("url") for s in web_steps] == [f"https://x/{i}" for i in range(5)]
    assert all("lifecycle_state: succeeded" in s.result for s in web_steps)


# ---------------------------------------------------------------------------
# Hire confinement (delegation-follow-ups t11, c19/h10): a mixed batch
# [read_file, assign_to_colleague, grep_search] runs the hire/assign step
# OUTSIDE the pool, in request order. The assign handler is t13 and is not in
# this tree, so the step lands on the executor's unknown-tool path — the
# ordering + outside-the-pool guarantee is what this pins, and the readable
# per-step error is exactly the declared pre-t13 behavior.
# ---------------------------------------------------------------------------


def test_hire_step_in_a_mixed_batch_runs_outside_the_pool_in_request_order(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("COLLEAGUE_TOOL_CONCURRENCY", "10")
    executor = _SpyExecutor(_repo(tmp_path))
    calls = [
        ToolCall("r", "read_file", {"path": "a.txt"}),
        ToolCall("h", "assign_to_colleague", {"agent_id": "hire-1", "task": "survey"}),
        ToolCall("g", "grep_search", {"pattern": "body"}),
    ]
    # The partition splits the unsafe hire call into its own single-item batch.
    batches = toolbatch.partition_by_concurrency_safety(calls, toolbatch_loop.is_batch_safe)
    assert [[c.id for c in b] for b in batches] == [["r"], ["h"], ["g"]]

    task = Task.new(str(tmp_path), "hire mixed turn")
    result = run(
        _scripted([ModelResponse(tool_calls=calls), _FINISH]), task, max_steps=10, executor=executor
    )
    assert result.status == OK
    # Request order end to end: execution order and step order both hold.
    assert executor.started == ["a.txt", "assign_to_colleague", "grep_search"]
    steps = result.steps[:3]
    assert [s.tool for s in steps] == ["read_file", "assign_to_colleague", "grep_search"]
    assert [s.index for s in steps] == [0, 1, 2]
    # Outside the pool: the hire step ran on the main thread.
    assert executor.threads["assign_to_colleague"] == threading.get_ident()
    # t13's handler answers: without a live hire the step is a readable
    # 'no live hire' tool result (ok=True), never a crashed drive.
    assert steps[1].ok is True
    assert "no live hire: " in steps[1].result
    assert steps[0].ok is True
    assert steps[2].ok is True

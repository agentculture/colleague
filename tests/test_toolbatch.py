"""Tests for colleague/toolbatch.py — plan task t2, spec c40 / h29.

Covers every acceptance criterion verbatim from the confirmed plan:

1. ``partition_by_concurrency_safety`` is a pure function whose docstring
   example ``[Read, Read, Edit, Read] -> [[Read,Read],[Edit],[Read]]`` holds.
2. ``is_shell_command_read_only`` is table-tested on >= 30 commands; every
   compound/metacharacter form is unsafe; unknown root commands are unsafe.
3. ``CONCURRENCY_SAFE_TOOLS`` is exactly the expected frozenset plus a memory
   recall predicate; edit/write/run_tests/subagent/subagents/finish/devague/
   culture are never safe.
4. The module imports nothing from ``colleague.loop`` or ``colleague.tools``.

Plus a behavioral suite for ``run_batch`` (order-preserving, width<=1 never
instantiates a ThreadPoolExecutor).
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from colleague import toolbatch
from colleague.toolbatch import (
    CONCURRENCY_SAFE_TOOLS,
    READ_ONLY_ROOT_COMMANDS,
    is_memory_recall_call,
    is_shell_command_read_only,
    is_tool_call_concurrency_safe,
    partition_by_concurrency_safety,
    run_batch,
)

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "colleague"


# ---------------------------------------------------------------------------
# 1. partition_by_concurrency_safety — pure function, docstring example
# ---------------------------------------------------------------------------


class TestPartitionByConcurrencySafety:
    def test_docstring_example(self) -> None:
        """[Read, Read, Edit, Read] -> [[Read,Read],[Edit],[Read]]."""
        result = partition_by_concurrency_safety(
            ["Read", "Read", "Edit", "Read"], lambda x: x == "Read"
        )
        assert result == [["Read", "Read"], ["Edit"], ["Read"]]

    def test_all_safe_merges_into_one_batch(self) -> None:
        result = partition_by_concurrency_safety(["Read", "Read", "Read"], lambda x: True)
        assert result == [["Read", "Read", "Read"]]

    def test_all_unsafe_each_its_own_batch(self) -> None:
        result = partition_by_concurrency_safety(["Edit", "Edit"], lambda x: False)
        assert result == [["Edit"], ["Edit"]]

    def test_empty_input(self) -> None:
        assert partition_by_concurrency_safety([], lambda x: True) == []

    def test_order_preserved(self) -> None:
        items = list(range(10))
        result = partition_by_concurrency_safety(items, lambda x: x % 3 != 0)
        flattened = [x for batch in result for x in batch]
        assert flattened == items

    def test_is_pure_no_mutation_of_input(self) -> None:
        items = ["Read", "Edit", "Read"]
        original = list(items)
        partition_by_concurrency_safety(items, lambda x: x == "Read")
        assert items == original

    def test_batch_safety_recoverable_from_first_item(self) -> None:
        is_safe = lambda x: x == "Read"  # noqa: E731
        batches = partition_by_concurrency_safety(["Read", "Read", "Edit", "Read"], is_safe)
        verdicts = [is_safe(batch[0]) for batch in batches]
        assert verdicts == [True, False, True]


# ---------------------------------------------------------------------------
# 2. is_shell_command_read_only — table test, >= 30 commands
# ---------------------------------------------------------------------------

_READ_ONLY_COMMANDS = [
    "cat file.txt",
    "ls -la",
    "ls",
    "pwd",
    "cd /tmp",
    "echo hello",
    "wc -l file.txt",
    "cut -d: -f1 /etc/passwd",
    "column -t file.txt",
    "basename /a/b/c.txt",
    "dirname /a/b/c.txt",
    "df -h",
    "du -sh .",
    "printenv PATH",
    "ps aux",
    "which python3",
    "where python3",
    "whoami",
    "head -n 5 file.txt",
    "tail -n 5 file.txt",
    "grep -n foo file.txt",
    "find . -name '*.py'",
    "find . -maxdepth 1 -type f",
    "sed -n '1,5p' file.txt",
    "sed 's/a/b/' file.txt",
    "awk '{print $1}' file.txt",
    "git status",
    "git log --oneline -5",
    "git diff HEAD",
    "git show HEAD",
    "git branch",
    "git branch --list",
    "git rev-parse HEAD",
    "git blame file.txt",
    "git describe",
    "git ls-files",
    "git cat-file -p HEAD",
    "git --version",
    "  cat   file.txt  ",  # extra whitespace is fine
]

_UNSAFE_COMMANDS = [
    ("empty string", ""),
    ("whitespace only", "   "),
    ("semicolon chain", "cat file.txt; rm file.txt"),
    ("pipe", "cat file.txt | tee out.txt"),
    ("background amp", "cat file.txt &"),
    ("logical and", "cat file.txt && rm file.txt"),
    ("logical or", "false || rm file.txt"),
    ("command substitution dollar-paren", "echo $(rm -rf /)"),
    ("command substitution backtick", "echo `rm -rf /`"),
    ("write redirection", "cat file.txt > out.txt"),
    ("append redirection", "echo hi >> out.txt"),
    ("input redirection", "cat < in.txt"),
    ("sh -c wrapper", "sh -c 'rm -rf /'"),
    ("bash -c wrapper", "bash -c 'rm -rf /'"),
    ("xargs", "find . -name '*.py' -print0 | xargs -0 rm"),
    ("xargs alone", "xargs rm"),
    ("find -exec", "find . -name '*.py' -exec rm {} \\;"),
    ("find -delete", "find . -name '*.tmp' -delete"),
    ("find -execdir", "find . -execdir rm {} \\;"),
    ("sed -i", "sed -i 's/a/b/' file.txt"),
    ("sed --in-place", "sed --in-place 's/a/b/' file.txt"),
    ("awk system()", "awk '{system(\"rm -rf /\")}' file.txt"),
    ("unknown root command", "curl http://evil.example/"),
    ("unknown root command rm", "rm -rf /"),
    ("unknown root command python", "python3 -c 'print(1)'"),
    ("git push", "git push origin main"),
    ("git commit", "git commit -am 'x'"),
    ("git reset", "git reset --hard"),
    ("git remote add", "git remote add evil http://evil"),
    ("git branch create", "git branch new-feature"),
    ("git branch delete", "git branch -d new-feature"),
    ("env assignment only", "FOO=bar"),
    ("uppercase root command", "CAT file.txt"),
    ("non-string input", None),
    ("unbalanced quotes", "cat 'file.txt"),
]


class TestIsShellCommandReadOnly:
    @pytest.mark.parametrize("command", _READ_ONLY_COMMANDS)
    def test_read_only_commands_are_safe(self, command: str) -> None:
        assert is_shell_command_read_only(command) is True, command

    @pytest.mark.parametrize("case", _UNSAFE_COMMANDS, ids=[c[0] for c in _UNSAFE_COMMANDS])
    def test_unsafe_commands_are_rejected(self, case) -> None:
        _, command = case
        assert is_shell_command_read_only(command) is False, command

    def test_at_least_30_commands_covered(self) -> None:
        assert len(_READ_ONLY_COMMANDS) + len(_UNSAFE_COMMANDS) >= 30

    def test_never_raises_on_odd_input(self) -> None:
        for weird in (None, 123, [], {}, "\x00\x01"):
            assert is_shell_command_read_only(weird) is False

    def test_all_read_only_root_commands_in_allowlist(self) -> None:
        # every root command actually exercised by _READ_ONLY_COMMANDS must be
        # a member of the allow-list (guards the table against drifting).
        for command in _READ_ONLY_COMMANDS:
            root = command.strip().split()[0]
            assert root in READ_ONLY_ROOT_COMMANDS, root


# ---------------------------------------------------------------------------
# 3. CONCURRENCY_SAFE_TOOLS + memory recall predicate
# ---------------------------------------------------------------------------


class TestConcurrencySafeTools:
    def test_frozenset_contents(self) -> None:
        assert isinstance(CONCURRENCY_SAFE_TOOLS, frozenset)
        assert CONCURRENCY_SAFE_TOOLS == frozenset(
            {"read_file", "list_dir", "grep_search", "glob", "view_media"}
        )

    @pytest.mark.parametrize("tool_name", sorted(CONCURRENCY_SAFE_TOOLS))
    def test_each_safe_tool_is_concurrency_safe(self, tool_name: str) -> None:
        assert is_tool_call_concurrency_safe(tool_name, {}) is True

    def test_memory_recall_is_safe(self) -> None:
        assert is_memory_recall_call("memory", {"verb": "recall", "query": "x"}) is True
        assert is_tool_call_concurrency_safe("memory", {"verb": "recall"}) is True

    def test_memory_remember_is_never_safe(self) -> None:
        assert is_memory_recall_call("memory", {"verb": "remember", "record": {}}) is False
        assert is_tool_call_concurrency_safe("memory", {"verb": "remember"}) is False

    def test_memory_missing_verb_is_never_safe(self) -> None:
        assert is_tool_call_concurrency_safe("memory", {}) is False
        assert is_tool_call_concurrency_safe("memory", None) is False

    def test_run_command_safe_only_when_read_only(self) -> None:
        assert is_tool_call_concurrency_safe("run_command", {"command": "git status"}) is True
        assert is_tool_call_concurrency_safe("run_command", {"command": "rm -rf /"}) is False
        assert is_tool_call_concurrency_safe("run_command", {}) is False
        assert is_tool_call_concurrency_safe("run_command", None) is False

    @pytest.mark.parametrize(
        "tool_name",
        [
            "edit_file",
            "write_file",
            "run_tests",
            "subagent",
            "subagents",
            "finish",
            "devague",
            "culture",
        ],
    )
    def test_mutating_tools_are_never_safe(self, tool_name: str) -> None:
        assert is_tool_call_concurrency_safe(tool_name, {}) is False


# ---------------------------------------------------------------------------
# 4. Standalone module — no import of loop.py or tools.py
# ---------------------------------------------------------------------------


class TestModuleStandalone:
    def test_source_has_no_forbidden_imports(self) -> None:
        source = (_PACKAGE_DIR / "toolbatch.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.endswith("loop"), f"forbidden import: {module}"
                assert not module.endswith("tools"), f"forbidden import: {module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.endswith(".loop"), alias.name
                    assert not alias.name.endswith(".tools"), alias.name

    def test_module_has_marker_docstring(self) -> None:
        assert toolbatch.__doc__ is not None
        assert "adapted-from: qwen-code" in toolbatch.__doc__
        assert "coreToolScheduler.ts:1284-1348" in toolbatch.__doc__
        assert "shellReadOnlyChecker.ts" in toolbatch.__doc__

    def test_module_docstring_notes_scheduling_not_permission(self) -> None:
        assert "permission" in toolbatch.__doc__.lower()

    def test_module_importable_standalone(self) -> None:
        # importlib re-import in isolation to be extra sure no hidden
        # side-effecting import creeps in.
        import importlib

        importlib.reload(toolbatch)


# ---------------------------------------------------------------------------
# run_batch — bounded-concurrency helper
# ---------------------------------------------------------------------------


class TestRunBatch:
    def test_sequential_width_le_1_preserves_order(self) -> None:
        calls = [3, 1, 2]
        result = run_batch(lambda x: x * 10, calls, width=1)
        assert result == [30, 10, 20]

    def test_width_zero_is_sequential(self) -> None:
        calls = [1, 2, 3]
        result = run_batch(lambda x: x + 1, calls, width=0)
        assert result == [2, 3, 4]

    def test_width_le_1_never_instantiates_thread_pool(self, monkeypatch) -> None:
        def _boom(*args, **kwargs):
            raise AssertionError("ThreadPoolExecutor must not be instantiated")

        monkeypatch.setattr(toolbatch, "ThreadPoolExecutor", _boom)
        result = run_batch(lambda x: x, [1, 2, 3], width=1)
        assert result == [1, 2, 3]

    def test_single_call_never_instantiates_thread_pool(self, monkeypatch) -> None:
        def _boom(*args, **kwargs):
            raise AssertionError("ThreadPoolExecutor must not be instantiated")

        monkeypatch.setattr(toolbatch, "ThreadPoolExecutor", _boom)
        result = run_batch(lambda x: x * 2, [5], width=4)
        assert result == [10]

    def test_concurrent_execution_preserves_input_order(self) -> None:
        # Deliberately return slower for earlier items so a naive
        # completion-order implementation would misorder the result.
        def execute(item: int):
            delay, value = item
            time.sleep(delay)
            return value

        calls = [(0.03, "a"), (0.0, "b"), (0.01, "c")]
        result = run_batch(execute, calls, width=3)
        assert result == ["a", "b", "c"]

    def test_concurrent_execution_actually_runs_concurrently(self) -> None:
        def execute(_):
            time.sleep(0.05)
            return True

        start = time.monotonic()
        result = run_batch(execute, [1, 2, 3, 4], width=4)
        elapsed = time.monotonic() - start
        assert result == [True, True, True, True]
        # sequential would take >= 0.20s; concurrent should be well under that.
        assert elapsed < 0.18

    def test_empty_calls(self) -> None:
        assert run_batch(lambda x: x, [], width=4) == []

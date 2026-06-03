"""Boundary guard tests — c21 / h17.

Asserts that the execution boundary described in the spec holds:

    "No code path opens a socket, forks a daemon, or imports a command file as
    Python; hooks are only ever executed as subprocesses and the palette runs in
    the foreground."
                        — docs/specs/2026-05-27-colleague-gains-an-extensibility-layer.md

Four checks (two behavioral, two structural):

1. BEHAVIORAL — Hooks run as subprocesses, not Python imports.
   A hook whose body is valid shell but a Python syntax error executes
   correctly via ``run_hook``.  If the hook were exec'd as Python it would
   raise SyntaxError; running it via ``subprocess.run(shell=True)`` succeeds.

2. BEHAVIORAL — Commands are read as text, not imported.
   A command template whose body is arbitrary non-Python text (e.g. prose
   containing shell-like fragments that are not valid Python) is loaded and
   expanded via ``load_command`` / ``expand_command`` without error.

3. STRUCTURAL — No networking / daemon machinery anywhere in the package.
   Every ``colleague/**/*.py`` source is scanned for references to
   ``socket``, ``socketserver``, ``http.server``, ``asyncio`` (server-side
   patterns), ``os.fork``, and ``multiprocessing`` process-spawning.  Any
   match causes the test to fail with the offending file + line.

4. STRUCTURAL — ``subprocess`` is confined to its sanctioned files.
   The only modules permitted to import ``subprocess`` are:
   ``colleague/hooks.py``, ``colleague/tools.py``, ``colleague/handoff.py``.
   All three are sanctioned subprocess consumers; no other module may import it.

5. STRUCTURAL — No ``importlib.import_module`` / ``__import__`` applied to
   command or hook file paths anywhere in the package.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Resolve the package directory relative to this test file.
# ---------------------------------------------------------------------------

_PACKAGE_DIR: Path = Path(__file__).resolve().parents[1] / "colleague"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py_sources() -> list[Path]:
    """Return every ``*.py`` file under the colleague package."""
    return sorted(_PACKAGE_DIR.rglob("*.py"))


def _make_executable_script(directory: Path, name: str, content: str) -> Path:
    """Write a shell script, make it executable, and return its path."""
    script = directory / name
    script.write_text(content, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# ---------------------------------------------------------------------------
# Behavioral check 1 — hooks run as subprocesses, not Python imports
# ---------------------------------------------------------------------------


class TestHookRunsAsSubprocess:
    """run_hook executes the hook command in a child process, not via Python import."""

    def test_non_python_shell_script_executes_via_subprocess(self, tmp_path: Path) -> None:
        """A .sh script that is a Python syntax error runs correctly via run_hook.

        The script body is intentionally invalid Python (uses bash-only syntax
        ``[[`` and ``echo`` without parens) so that any attempt to evaluate it
        as Python would raise a SyntaxError.  The subprocess path must succeed
        and return ``decision="allow"`` with the expected stdout.
        """
        from colleague.hooks import HookDecision, HookEntry, run_hook

        # Write a script that is valid Bash but invalid Python.
        # "[[" is a Bash compound-command keyword; this is a syntax error in Python.
        script_content = """\
#!/usr/bin/env bash
# This is a bash-only construct that would be a Python SyntaxError.
VALUE=42
if [[ $VALUE -eq 42 ]]; then
    echo "subprocess-hook-ran"
fi
"""
        script = _make_executable_script(tmp_path, "guard.sh", script_content)

        entry = HookEntry(
            event="task_start",
            matcher="",
            command=str(script),
        )
        payload = {
            "event": "task_start",
            "tool": None,
            "arguments": {},
            "task_id": "test-id",
            "repo_path": str(tmp_path),
        }

        decision: HookDecision = run_hook(entry, payload, cwd=tmp_path)

        assert decision.exit_code == 0, (
            f"Hook exited with non-zero code {decision.exit_code!r}; "
            f"reason: {decision.reason!r}. "
            "This suggests the hook was not run as a subprocess."
        )
        assert decision.decision == "allow", (
            f"Expected 'allow' but got {decision.decision!r}. "
            f"Additional context: {decision.additional_context!r}"
        )

    def test_hook_that_would_fail_if_imported_as_python_runs_fine(self, tmp_path: Path) -> None:
        """A script with a deliberate Python import error still runs as a process.

        Uses ``import nonexistent_module_xyz`` — valid Python syntax but would
        raise ImportError if Python tried to execute it directly.  As a shell
        script that just echoes a line before the Python-ish fragment is in a
        comment, the shell ignores it and the hook succeeds.
        """
        from colleague.hooks import HookEntry, run_hook

        script_content = """\
#!/bin/sh
# Python would raise: import nonexistent_module_xyz
# But we are a shell script, not Python.
printf '{"decision":"allow","additionalContext":"ran-as-shell"}'
"""
        script = _make_executable_script(tmp_path, "no_import.sh", script_content)

        entry = HookEntry(
            event="pre_tool",
            matcher="",
            command=str(script),
        )
        payload = {
            "event": "pre_tool",
            "tool": "read_file",
            "arguments": {"path": "foo.py"},
            "task_id": "test-id",
            "repo_path": str(tmp_path),
        }

        decision = run_hook(entry, payload, cwd=tmp_path)

        assert (
            decision.exit_code == 0
        ), f"Hook failed (exit {decision.exit_code}): {decision.reason!r}"
        assert decision.additional_context == "ran-as-shell", (
            "Hook did not produce the expected additionalContext; "
            f"got {decision.additional_context!r}"
        )


# ---------------------------------------------------------------------------
# Behavioral check 2 — commands read as text, not imported
# ---------------------------------------------------------------------------


class TestCommandsReadAsText:
    """load_command / expand_command read template files as plain text."""

    def test_non_python_template_body_expands_correctly(self, tmp_path: Path) -> None:
        """A command template whose body is arbitrary non-Python text loads fine.

        The body contains shell metacharacters and prose that would be a
        SyntaxError as Python.  load_command must return it verbatim in
        Command.body without any attempt to parse or import it.
        """
        from colleague.commands import load_command

        # Content that is not valid Python — shell redirections, pipe chains,
        # bare words with curly syntax.
        raw_body = (
            "Fix lint errors under $1.\n"
            "Then run: grep -r 'TODO' . | sort > todos.txt\n"
            "Shell variable: ${MY_VAR:-default}\n"
            "Heredoc-like: << 'EOF'\n"
            "  some content\n"
            "EOF\n"
        )
        cmd_file = tmp_path / "fix-lint.md"
        cmd_file.write_text(raw_body, encoding="utf-8")

        cmd = load_command(cmd_file)

        assert cmd.name == "fix-lint", f"Expected name 'fix-lint', got {cmd.name!r}"
        assert cmd.body == raw_body, (
            "Command body was not read verbatim; " f"expected {raw_body!r}, got {cmd.body!r}"
        )

    def test_expand_command_with_non_python_body_returns_task(self, tmp_path: Path) -> None:
        """expand_command with a non-Python template body produces a valid Task.

        The template file is placed under .colleague/commands/ so it is
        discovered by discover_commands.  After expansion, the task instruction
        must contain the substituted body text.
        """
        from colleague.commands import expand_command
        from colleague.contract import Task

        cmds_dir = tmp_path / ".colleague" / "commands"
        cmds_dir.mkdir(parents=True)

        template = (
            "---\n"
            "description: A non-Python template\n"
            "---\n"
            "Reformat everything under $1 and then:\n"
            "  for f in *.py; do black $f; done\n"
            "Bash-only: [[ -d $1 ]] && echo 'exists'\n"
        )
        (cmds_dir / "reformat.md").write_text(template, encoding="utf-8")

        task: Task = expand_command(tmp_path, "reformat", ["src/"], engine_default="mock")

        assert isinstance(task, Task), f"expand_command should return a Task, got {type(task)!r}"
        assert (
            "src/" in task.instruction
        ), f"$1 substitution did not work; instruction: {task.instruction!r}"
        assert "Bash-only" in task.instruction, (
            "Non-Python body content was not preserved in the task instruction; "
            f"instruction: {task.instruction!r}"
        )


# ---------------------------------------------------------------------------
# Structural check 3 — no networking / daemon machinery in the package
# ---------------------------------------------------------------------------

# Patterns that indicate a networking or daemon boundary violation.
# Each pattern is (description, compiled regex).
_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Raw socket usage
    (
        "socket import",
        re.compile(r"\bimport\s+socket\b|from\s+socket\b"),
    ),
    (
        "socketserver import",
        re.compile(r"\bimport\s+socketserver\b|from\s+socketserver\b"),
    ),
    # HTTP server
    (
        "http.server import",
        re.compile(
            r"\bimport\s+http\.server\b|from\s+http\.server\b|from\s+http\s+import\s+server\b"
        ),
    ),
    # asyncio server-side primitives
    (
        "asyncio.start_server / create_server",
        re.compile(r"\basyncio\.(start_server|create_server|start_unix_server)\b"),
    ),
    # os.fork — daemon process spawning
    (
        "os.fork",
        re.compile(r"\bos\.fork\(\)"),
    ),
    # multiprocessing process-spawning
    (
        "multiprocessing.Process / Pool",
        re.compile(r"\bmultiprocessing\.(Process|Pool|Queue|Manager)\b"),
    ),
    # plain "import asyncio" without server usage is allowed only if not followed
    # by server calls — but a blanket asyncio import in colleague would be
    # suspicious; flag "import asyncio" to keep the boundary tight.
    (
        "asyncio import (no async I/O allowed in colleague)",
        re.compile(r"^\s*(import asyncio|from asyncio\b)", re.MULTILINE),
    ),
]


class TestNoNetworkingOrDaemonMachinery:
    """No module in colleague/ may open a socket, fork a daemon, or start a server."""

    @pytest.mark.parametrize(
        "py_file",
        _all_py_sources(),
        ids=lambda p: str(p.relative_to(_PACKAGE_DIR.parent)),
    )
    def test_source_has_no_forbidden_patterns(self, py_file: Path) -> None:
        """Assert that *py_file* contains none of the forbidden networking patterns."""
        source = py_file.read_text(encoding="utf-8")
        lines = source.splitlines()

        violations: list[str] = []
        for description, pattern in _FORBIDDEN_PATTERNS:
            for lineno, line in enumerate(lines, start=1):
                if pattern.search(line):
                    violations.append(
                        f"  {py_file.relative_to(_PACKAGE_DIR.parent)}:{lineno}: "
                        f"[{description}] {line.rstrip()!r}"
                    )

        assert not violations, (
            "Boundary violation — networking/daemon machinery found in package source:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Structural check 4 — subprocess confined to sanctioned files
# ---------------------------------------------------------------------------

# Files that are explicitly permitted to import subprocess, with justification:
#   hooks.py      — runs hook commands as subprocesses (the point of hooks)
#   tools.py      — run_command tool; executing model-issued commands is by design
#   handoff.py    — drives git + gh CLI; subprocess is the transport
#   neighbours.py — drives git clone/pull for read-only neighbour clones;
#                   subprocess is the transport
#   culture.py    — launches allow-listed AgentCulture CLIs (agtag/devex);
#                   subprocess is the transport
#   devague.py    — launches the allow-listed devague CLI (the destination tool);
#                   subprocess is the transport
#   worktrees.py  — drives git worktree add/remove for per-child isolation;
#                   subprocess is the transport
_SUBPROCESS_ALLOWED: frozenset[str] = frozenset(
    {
        "colleague/hooks.py",
        "colleague/tools.py",
        "colleague/handoff.py",
        "colleague/neighbours.py",
        "colleague/culture.py",
        "colleague/devague.py",
        "colleague/worktrees.py",
    }
)

_SUBPROCESS_IMPORT_RE = re.compile(r"^\s*import subprocess\b|^\s*from subprocess\b")


class TestSubprocessConfinement:
    """subprocess imports must only appear in the three sanctioned modules."""

    @pytest.mark.parametrize(
        "py_file",
        _all_py_sources(),
        ids=lambda p: str(p.relative_to(_PACKAGE_DIR.parent)),
    )
    def test_subprocess_only_in_sanctioned_files(self, py_file: Path) -> None:
        """Assert subprocess is only imported by its sanctioned consumers."""
        rel = str(py_file.relative_to(_PACKAGE_DIR.parent))
        source = py_file.read_text(encoding="utf-8")
        lines = source.splitlines()

        if rel in _SUBPROCESS_ALLOWED:
            # Sanctioned file — just verify it actually does import subprocess
            # (so the allowed list doesn't drift with dead entries).
            has_subprocess = any(_SUBPROCESS_IMPORT_RE.search(line) for line in lines)
            assert has_subprocess, (
                f"{rel} is listed as a sanctioned subprocess consumer "
                "but does not import subprocess — remove it from _SUBPROCESS_ALLOWED."
            )
            return

        # All other files must not import subprocess.
        violations: list[str] = []
        for lineno, line in enumerate(lines, start=1):
            if _SUBPROCESS_IMPORT_RE.search(line):
                violations.append(f"  {rel}:{lineno}: {line.rstrip()!r}")

        assert not violations, (
            "subprocess imported outside sanctioned files "
            f"(allowed: {sorted(_SUBPROCESS_ALLOWED)}):\n" + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Structural check 5 — no importlib.import_module / __import__ on command paths
# ---------------------------------------------------------------------------

_DYN_IMPORT_RE = re.compile(r"\bimport_module\s*\(|\b__import__\s*\(")


class TestNoDynamicCommandImport:
    """No source may use import_module / __import__ to load command or hook files."""

    @pytest.mark.parametrize(
        "py_file",
        _all_py_sources(),
        ids=lambda p: str(p.relative_to(_PACKAGE_DIR.parent)),
    )
    def test_no_dynamic_import_of_command_files(self, py_file: Path) -> None:
        """Assert *py_file* does not call import_module() or __import__() at all.

        The package reads command templates as plain text (``path.read_text()``)
        and runs hook commands via ``subprocess.run(shell=True)``.  There is no
        legitimate reason for any module in colleague/ to use
        ``importlib.import_module`` or ``__import__`` — their presence would
        signal that a command/hook file is being executed as Python, violating
        the boundary claim.
        """
        source = py_file.read_text(encoding="utf-8")
        rel = str(py_file.relative_to(_PACKAGE_DIR.parent))

        violations: list[str] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            if _DYN_IMPORT_RE.search(line):
                violations.append(f"  {rel}:{lineno}: {line.rstrip()!r}")

        assert not violations, (
            "Dynamic import (import_module / __import__) found in package source — "
            "command/hook files must be read as text, not imported as Python:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Structural check 6 — no mcp.json reference in any colleague source
# ---------------------------------------------------------------------------

# The CLAUDE.md v0 scope is explicit: colleague reads no mcp.json and has no
# mcp verb.  Any source-level reference to the filename (other than in a
# comment that documents the gap) would signal scope-creep.  We assert that no
# *executable* reference to "mcp.json" appears — i.e., no open/read/Path call
# whose string argument contains "mcp.json".  A documentary string in a comment
# or docstring is acceptable; an actual Path/open call is not.
_MCP_JSON_CODE_RE = re.compile(
    r"""(?x)
    (?:open|Path|read_text|load)\s*\(   # a file-opening call ...
    [^)]*                               # ... with any arguments ...
    mcp\.json                           # ... that contains "mcp.json"
    """,
)


class TestNoMcpJsonReference:
    """No colleague source may open or read an mcp.json file."""

    @pytest.mark.parametrize(
        "py_file",
        _all_py_sources(),
        ids=lambda p: str(p.relative_to(_PACKAGE_DIR.parent)),
    )
    def test_no_mcp_json_open_or_read(self, py_file: Path) -> None:
        """Assert *py_file* contains no code that opens/reads an mcp.json file.

        The v0 spec explicitly excludes an MCP execution runtime.  Any
        ``open(...mcp.json...)``, ``Path(...mcp.json...)``, or similar call
        signals that an excluded feature has been added without re-speccing.
        Documentary comments that mention the gap are fine — only executable
        file-open patterns are flagged.
        """
        source = py_file.read_text(encoding="utf-8")
        rel = str(py_file.relative_to(_PACKAGE_DIR.parent))

        violations: list[str] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            # Skip comment lines — documentary references are fine.
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _MCP_JSON_CODE_RE.search(line):
                violations.append(f"  {rel}:{lineno}: {line.rstrip()!r}")

        assert not violations, (
            "Executable mcp.json reference found in package source — "
            "colleague reads no mcp.json (v0 scope); re-spec before adding MCP support:\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Structural check 7 — mesh-member feature modules use no daemon primitives
# ---------------------------------------------------------------------------

# The culture / neighbours modules shell out to operator CLIs — they must
# never spawn a long-lived background process or start a server.  Concretely:
# no threading.Thread / threading.daemon, no socketserver, no os.fork.
# (multiprocessing and asyncio server patterns are already blocked by check 3.)
_MESH_MODULES: list[str] = [
    "colleague/culture.py",
    "colleague/neighbours.py",
    "colleague/identity.py",
    "colleague/devague.py",
]

_DAEMON_PRIMITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "threading import",
        re.compile(r"^\s*import threading\b|^\s*from threading\b", re.MULTILINE),
    ),
    (
        "threading.Thread / threading.Timer",
        re.compile(r"\bthreading\.(Thread|Timer|daemon)\b"),
    ),
    (
        "socketserver import",
        re.compile(r"^\s*import socketserver\b|^\s*from socketserver\b", re.MULTILINE),
    ),
    (
        "os.fork",
        re.compile(r"\bos\.fork\(\)"),
    ),
]


class TestMeshModulesNoDaemonPrimitives:
    """culture.py, neighbours.py, and identity.py must not spawn daemon processes."""

    @pytest.mark.parametrize("rel_path", _MESH_MODULES)
    def test_no_daemon_primitives(self, rel_path: str) -> None:
        """Assert the mesh-member module *rel_path* imports no daemon primitive.

        These modules may only shell out to operator CLIs via ``subprocess.run``
        (the sanctioned transport).  Any use of threading, socketserver, or
        os.fork would indicate an undocumented daemon — a boundary violation.
        """
        py_file = _PACKAGE_DIR.parent / rel_path
        assert py_file.is_file(), f"Expected source file not found: {py_file}"

        source = py_file.read_text(encoding="utf-8")
        lines = source.splitlines()

        violations: list[str] = []
        for description, pattern in _DAEMON_PRIMITIVE_PATTERNS:
            for lineno, line in enumerate(lines, start=1):
                if pattern.search(line):
                    violations.append(f"  {rel_path}:{lineno}: [{description}] {line.rstrip()!r}")

        assert not violations, (
            f"Daemon primitive found in mesh-member module {rel_path} — "
            "these modules must only shell out via subprocess.run, never spawn "
            "threads or background processes:\n" + "\n".join(violations)
        )

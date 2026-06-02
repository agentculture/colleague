"""End-to-end mesh proof — identity attribution + neighbour read (t7).

Two acceptance criteria:

AC1 — Identity attribution:
  Drive the mock engine under identity X (set via a repo-root ``culture.yaml``
  with ``nick: X``). The scripted drive invokes the ``culture`` tool (agtag).
  A fake ``agtag`` executable records the ``CONVERTIBLE_IDENTITY`` env it saw
  to a file; the test asserts the drive ran with ``CONVERTIBLE_IDENTITY=X``.

AC2 — Neighbour read + cleanup:
  Pre-create a fake neighbour under ``.colleague/neighbours/<name>/somefile``
  with known content. Script the mock engine to call ``read_file`` on that clone
  path during the drive.  Assert the drive successfully read the neighbour
  content — demonstrating a cross-repo task a sealed (no-neighbour) drive could
  not complete.  Assert the clone is cleaned up after ``finish`` (no residue).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from colleague.contract import Task
from colleague.hooks import HookConfig
from colleague.loop import ModelResponse, ToolCall, run
from colleague.tools import ToolExecutor

# ---------------------------------------------------------------------------
# Helpers shared by both ACs
# ---------------------------------------------------------------------------


def scripted(responses: list[ModelResponse]):
    """Return a ``complete`` callable that replays *responses* in sequence."""
    state = {"i": 0}

    def complete(_messages):
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]

    return complete


def _make_fake_agtag(directory: Path, record_file: Path) -> Path:
    """Write a fake ``agtag`` executable that appends CONVERTIBLE_IDENTITY to *record_file*.

    The script:
    - exits 0
    - appends the value of CONVERTIBLE_IDENTITY (or "<unset>") to *record_file*
      so the test can read it back after the drive.
    """
    script = directory / "agtag"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "${{CONVERTIBLE_IDENTITY:-<unset>}}" >> {record_file}\n'
        'echo "exit=0"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _make_fake_neighbour(repo: Path, name: str, filename: str, content: str) -> Path:
    """Write a file under ``.colleague/neighbours/<name>/`` (no git needed)."""
    clone_dir = repo / ".colleague" / "neighbours" / name
    clone_dir.mkdir(parents=True, exist_ok=True)
    file_path = clone_dir / filename
    file_path.write_text(content, encoding="utf-8")
    return clone_dir


# ---------------------------------------------------------------------------
# AC1 — Drive-as-X: identity attributed to the culture CLI subprocess
# ---------------------------------------------------------------------------


class TestIdentityAttribution:
    """The mock engine drives a culture tool call attributed to identity X."""

    def test_culture_tool_invoked_with_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONVERTIBLE_IDENTITY=X is visible to the agtag subprocess during the drive.

        Setup:
        - Repo root has ``culture.yaml`` with ``nick: agent-x``.
        - A fake ``agtag`` in a tmp bin dir records the env identity it sees.
        - The scripted mock drive: (1) call ``culture`` with agtag, (2) finish.

        Assertion:
        - The recorded identity file contains ``agent-x``.
        """
        # --- repo identity ---
        (tmp_path / "culture.yaml").write_text("nick: agent-x\n", encoding="utf-8")

        # --- fake agtag that records identity ---
        bin_dir = tmp_path / "_bin"
        bin_dir.mkdir()
        record_file = tmp_path / "identity_seen.txt"
        _make_fake_agtag(bin_dir, record_file)

        # Prepend our fake bin dir to PATH so the culture tool finds it.
        original_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{bin_dir}:{original_path}")

        # --- scripted drive: culture tool call, then finish ---
        responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "culture",
                        {"cli": "agtag", "args": ["issue", "post", "hello"]},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("f1", "finish", {"summary": "attributed"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]

        task = Task.new(str(tmp_path), "post a mesh issue as X")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok", f"drive failed: {result.summary}"

        # --- AC1 assertion: identity was injected into the subprocess ---
        assert (
            record_file.exists()
        ), "fake agtag must have written its identity record — it was never called"
        seen = record_file.read_text(encoding="utf-8").strip()
        assert (
            seen == "agent-x"
        ), f"CONVERTIBLE_IDENTITY seen by agtag was {seen!r}; expected 'agent-x'"

    def test_identity_via_identity_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identity resolved from .colleague/identity.json also reaches the subprocess."""
        # No culture.yaml — fall through to identity.json.
        import json

        dotdir = tmp_path / ".colleague"
        dotdir.mkdir(parents=True, exist_ok=True)
        (dotdir / "identity.json").write_text(json.dumps({"as": "json-identity"}), encoding="utf-8")

        bin_dir = tmp_path / "_bin"
        bin_dir.mkdir()
        record_file = tmp_path / "id_seen.txt"
        _make_fake_agtag(bin_dir, record_file)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

        responses = [
            ModelResponse(
                tool_calls=[ToolCall("c1", "culture", {"cli": "agtag", "args": ["overview"]})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("f1", "finish", {"summary": "done"})],
            ),
        ]

        task = Task.new(str(tmp_path), "test identity.json attribution")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"
        seen = record_file.read_text(encoding="utf-8").strip()
        assert seen == "json-identity", f"Expected 'json-identity', got {seen!r}"


# ---------------------------------------------------------------------------
# AC2 — Neighbour read + cleanup after finish
# ---------------------------------------------------------------------------


class TestNeighbourReadAndCleanup:
    """The mock engine reads a pre-created neighbour clone and the clone is cleaned up."""

    def test_neighbour_file_readable_during_drive_then_cleaned_up(self, tmp_path: Path) -> None:
        """Drive reads a file from a pre-created neighbour clone, then cleanup removes it.

        A sealed (no-neighbour) drive could not complete this task because the
        neighbour file would not exist. Here we:
        1. Pre-write ``.colleague/neighbours/sibling/facts.txt`` with known content.
        2. Script the mock drive to read that file, then finish.
        3. Assert the read succeeded (the step result contains the file content).
        4. Assert ``.colleague/neighbours/`` is gone after finish (cleanup fired).
        """
        neighbour_content = "NEIGHBOUR_FACT: cross-repo data only a clone provides\n"
        _make_fake_neighbour(tmp_path, "sibling", "facts.txt", neighbour_content)
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert clone_root.exists(), "pre-condition: clone dir must exist before drive"

        read_results: list[str] = []

        responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "r1",
                        "read_file",
                        {"path": ".colleague/neighbours/sibling/facts.txt"},
                    )
                ],
                prompt_tokens=1,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("f1", "finish", {"summary": "read neighbour"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]

        # Wrap the executor so we can capture the read result.
        real_executor = ToolExecutor(tmp_path)
        original_execute = real_executor.execute

        def capturing_execute(name, arguments):
            outcome = original_execute(name, arguments)
            if name == "read_file":
                read_results.append(outcome.result)
            return outcome

        real_executor.execute = capturing_execute

        task = Task.new(str(tmp_path), "read the neighbour facts file")
        result = run(
            scripted(responses),
            task,
            max_steps=10,
            executor=real_executor,
            hooks=HookConfig(),
        )

        # Drive completed successfully.
        assert result.status == "ok", f"drive failed: {result.summary}"

        # AC2a — the read_file step returned the neighbour content.
        assert read_results, "read_file must have been called and captured"
        assert (
            "NEIGHBOUR_FACT" in read_results[0]
        ), f"neighbour content not in read result: {read_results[0]!r}"
        assert "cross-repo data" in read_results[0]

        # AC2b — the read_file step is in the result trace and succeeded.
        read_steps = [s for s in result.steps if s.tool == "read_file"]
        assert read_steps, "a read_file step must appear in the trace"
        assert read_steps[0].ok is True

        # AC2c — cleanup fired: no clone dir residue after finish.
        assert not clone_root.exists(), (
            "cleanup() must remove .colleague/neighbours/ after finish — "
            "clone dir still present after drive"
        )

    def test_neighbour_cleanup_leaves_no_residue_after_normal_finish(self, tmp_path: Path) -> None:
        """Even with multiple neighbour files, cleanup removes everything after finish."""
        _make_fake_neighbour(tmp_path, "alpha", "a.txt", "alpha content\n")
        _make_fake_neighbour(tmp_path, "beta", "b.txt", "beta content\n")
        clone_root = tmp_path / ".colleague" / "neighbours"
        assert list(clone_root.iterdir()), "two fake clones must exist before drive"

        responses = [
            ModelResponse(
                tool_calls=[ToolCall("f1", "finish", {"summary": "skip to finish"})],
            ),
        ]

        task = Task.new(str(tmp_path), "just finish quickly")
        result = run(scripted(responses), task, max_steps=10, hooks=HookConfig())

        assert result.status == "ok"
        assert (
            not clone_root.exists()
        ), "cleanup() must remove all neighbour clones — dir still exists"


# ---------------------------------------------------------------------------
# AC1 + AC2 combined: a single drive that does both
# ---------------------------------------------------------------------------


class TestMeshDriveCombined:
    """One drive: posts to the mesh as X, reads a neighbour file, then finishes."""

    def test_attributed_drive_reads_neighbour_and_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The headline proof: identity attributed + neighbour read + cleanup in one drive.

        Steps:
        1. Set identity to ``mesh-agent`` via culture.yaml.
        2. Pre-create a neighbour file with known content.
        3. Script: culture tool call → read_file of neighbour → finish.
        4. Assert: identity seen by agtag == ``mesh-agent``.
        5. Assert: read_file captured the neighbour content.
        6. Assert: clone dir is gone after finish.
        """
        # --- identity ---
        (tmp_path / "culture.yaml").write_text("nick: mesh-agent\n", encoding="utf-8")

        # --- fake agtag ---
        bin_dir = tmp_path / "_bin"
        bin_dir.mkdir()
        record_file = tmp_path / "seen_identity.txt"
        _make_fake_agtag(bin_dir, record_file)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

        # --- fake neighbour ---
        neighbour_content = "CROSS_REPO_DATUM: only readable via neighbour clone\n"
        _make_fake_neighbour(tmp_path, "peer", "data.txt", neighbour_content)
        clone_root = tmp_path / ".colleague" / "neighbours"

        read_results: list[str] = []

        # --- scripted turns: culture → read_file → finish ---
        responses = [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "culture",
                        {"cli": "agtag", "args": ["issue", "post", "mesh task started"]},
                    )
                ],
                prompt_tokens=2,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        "r1",
                        "read_file",
                        {"path": ".colleague/neighbours/peer/data.txt"},
                    )
                ],
                prompt_tokens=2,
                completion_tokens=1,
            ),
            ModelResponse(
                tool_calls=[ToolCall("f1", "finish", {"summary": "mesh drive complete"})],
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]

        # Wrap executor to capture read results.
        real_executor = ToolExecutor(tmp_path)
        original_execute = real_executor.execute

        def capturing_execute(name, arguments):
            outcome = original_execute(name, arguments)
            if name == "read_file":
                read_results.append(outcome.result)
            return outcome

        real_executor.execute = capturing_execute

        task = Task.new(str(tmp_path), "mesh cross-repo task")
        result = run(
            scripted(responses),
            task,
            max_steps=10,
            executor=real_executor,
            hooks=HookConfig(),
        )

        # Drive succeeded.
        assert result.status == "ok", f"drive failed: {result.summary}"

        # AC1 — identity attributed.
        assert record_file.exists(), "fake agtag was never called"
        seen_identity = record_file.read_text(encoding="utf-8").strip()
        assert (
            seen_identity == "mesh-agent"
        ), f"CONVERTIBLE_IDENTITY seen by agtag: {seen_identity!r}; expected 'mesh-agent'"

        # AC2a — neighbour file was read.
        assert read_results, "read_file of neighbour must have been captured"
        assert "CROSS_REPO_DATUM" in read_results[0]

        # AC2b — cleanup: no clone dir after finish.
        assert not clone_root.exists(), "cleanup() must remove .colleague/neighbours/ after finish"

        # Trace sanity: culture step + read_file step both succeeded.
        culture_steps = [s for s in result.steps if s.tool == "culture"]
        read_steps = [s for s in result.steps if s.tool == "read_file"]
        assert culture_steps and culture_steps[0].ok is True
        assert read_steps and read_steps[0].ok is True

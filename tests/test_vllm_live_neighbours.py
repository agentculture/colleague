"""Opt-in live proof that operator-configured neighbour clones fire (#125, §5).

Sibling to ``test_vllm_live_loop_tools.py`` / ``test_vllm_live_subagents.py`` /
``test_vllm_live_gated_configs.py``. Skipped unless ``COLLEAGUE_VLLM_E2E=1`` so CI
and offline runs never touch the network.

Unlike subagents (#122) and the culture/devague loop tools (#124) — which the
model must *choose* and which therefore needed a ``_DEFAULT_SYSTEM`` paragraph to
even be discoverable — neighbours is a **config-present-to-fire** surface
(closest to the gated configs of #123). The shallow clone happens automatically
at drive start (``colleague/loop.py`` ``clone_all()`` before the loop,
runtime-owned, all-engines rule), and the model consults it through ``read_file``
— a base-five tool already validated live. So **no prompt change is needed**:
handing the model the explicit ``.colleague/neighbours/<name>/...`` path fires the
read reliably. The only *live* element here is a real model performing that read;
the neighbour itself is a hermetic local git repo (no remote, no network).

Covered:

* **§5 clone-on-start + read** — with one ``{name, url}`` in
  ``.colleague/neighbours.json``, the drive shallow-clones the neighbour into
  ``.colleague/neighbours/<name>/`` *before* the loop, and the model reads a
  sentinel file out of it (a successful ``read_file`` whose result carries the
  sentinel proves the clone was present and readable mid-drive).
* **§5 cleanup-on-finish** — after the drive the ``.colleague/neighbours/`` tree
  is gone (``cleanup()`` runs on every loop exit, before the handoff).
* **§5 gitignored** — the clone root is matched by the repo's ``.gitignore`` and
  never tracked, so a neighbour never leaks into the drive branch commit.

DETERMINISTIC (cited in the ledger, not re-proven here): the **empty-config
default is a no-op** — purely model-independent loop mechanics, proven by
``tests/test_clone_lifecycle.py::TestCleanupAtFinish::test_empty_allowlist_noop``.
The clone/refresh/cleanup mechanics, path-traversal guards, and never-execute
confinement are unit-proven by ``tests/test_neighbours.py`` and
``tests/test_clone_lifecycle.py``. The live drive proves the *positive* path: a
real model reads a real clone that the runtime created and then tore down.

Run it (rig up) like::

    COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_neighbours.py -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from colleague.cli._commands.work import execute_work
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult

pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)

# A distinctive marker the model could not plausibly hallucinate — its presence in
# a read_file result proves the clone was actually there to read.
_SENTINEL = "neighbour-sentinel-7f3a9c-do-not-hallucinate"
_NEIGHBOUR_NAME = "sibling"
_NEIGHBOUR_FILE = "GREETING.txt"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A consumer repo whose ``.colleague/neighbours.json`` points at a local neighbour.

    The neighbour is a hermetic local git repo (file:// URL, no remote) so the
    only network-touching part of the drive is the model itself.
    """
    # 1) The neighbour SOURCE repo — a real repo holding the sentinel file.
    source = tmp_path / "neighbour_source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "neighbour@colleague.test")
    _git(source, "config", "user.name", "Neighbour Source")
    (source / _NEIGHBOUR_FILE).write_text(_SENTINEL + "\n", encoding="utf-8")
    _git(source, "add", _NEIGHBOUR_FILE)
    _git(source, "commit", "-m", "neighbour: add greeting")

    # 2) The CONSUMER repo being driven.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    # Mirror the real repo's .gitignore so the clone root is genuinely ignored
    # (the runtime relies on the repo's .gitignore, not on neighbours.py).
    (repo / ".gitignore").write_text("/.colleague/neighbours/\n", encoding="utf-8")
    dotdir = repo / ".colleague"
    dotdir.mkdir()
    (dotdir / "neighbours.json").write_text(
        json.dumps([{"name": _NEIGHBOUR_NAME, "url": source.resolve().as_uri()}]),
        encoding="utf-8",
    )
    _git(repo, "add", "README.md", ".gitignore", ".colleague/neighbours.json")
    _git(repo, "commit", "-m", "initial commit")
    return repo


_NEIGHBOUR_TASK = (
    "A read-only neighbour repo has been cloned into this repo under "
    f".colleague/neighbours/{_NEIGHBOUR_NAME}/. Use the read_file tool to read the "
    f"file .colleague/neighbours/{_NEIGHBOUR_NAME}/{_NEIGHBOUR_FILE}, report its exact "
    "contents, then call finish. Do not modify any files."
)


def _drive(repo: Path, instruction: str, label: str) -> TaskResult:
    task = Task.new(str(repo), instruction, engine="vllm-openai")
    result, artifact_path = execute_work(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )
    print(f"\n[live #125 {label}] drive {result.task_id} -> {artifact_path}")
    print(f"[live #125 {label}] steps: {[(s.tool, s.ok) for s in result.steps]}")
    return result


def test_5_neighbour_clone_read_during_drive_then_cleaned_up(git_repo: Path) -> None:
    clone_root = git_repo / ".colleague" / "neighbours"
    assert not clone_root.exists(), "pre-condition: nothing cloned before the drive"

    result = _drive(git_repo, _NEIGHBOUR_TASK, "5-neighbours")

    # The whole drive must finish OK — a successful read followed by a later drive
    # error must not read as a false "validated live" (parity with 4a/4b).
    assert result.status == OK, result.error

    # Clone-on-start: a successful read_file of the neighbour file whose result
    # carries the sentinel proves the runtime cloned it BEFORE the loop and the
    # model read it mid-drive. Assert on the shell-out result, not the model prose.
    neighbour_reads = [
        s
        for s in result.steps
        if s.tool == "read_file" and s.ok and _NEIGHBOUR_NAME in str(s.arguments.get("path", ""))
    ]
    assert neighbour_reads, (
        "model never successfully read the neighbour file: "
        f"{[(s.tool, s.ok, s.arguments.get('path')) for s in result.steps]}"
    )
    assert any(
        _SENTINEL in s.result for s in neighbour_reads
    ), f"sentinel not in any neighbour read: {[s.result[:80] for s in neighbour_reads]}"

    # Cleanup-on-finish: the clone tree is gone after the drive (cleanup() runs on
    # every loop exit, before the handoff). The .colleague/ dir itself survives.
    assert not clone_root.exists(), ".colleague/neighbours/ must be removed after the drive"

    # Gitignored: the clone root is matched by .gitignore and never tracked, so a
    # neighbour can't leak into the drive branch commit. (check-ignore is rule-based,
    # so it works even though the dir is now gone; ls-files confirms nothing tracked.)
    ignored = subprocess.run(
        ["git", "check-ignore", f".colleague/neighbours/{_NEIGHBOUR_NAME}/{_NEIGHBOUR_FILE}"],
        cwd=str(git_repo),
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 0, "the neighbour clone root must be gitignored"
    tracked = subprocess.run(
        ["git", "ls-files", ".colleague/neighbours/"],
        cwd=str(git_repo),
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout.strip() == "", f"neighbour files leaked into git: {tracked.stdout!r}"

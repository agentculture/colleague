"""Opt-in live proof that gated configs fire in a real drive (#123, ledger §3).

Sibling to ``test_vllm_live_subagents.py``. Skipped unless ``COLLEAGUE_VLLM_E2E=1``
so CI and offline runs never touch the network. The unit suite already proves the
gates fire on config presence (engine-agnostically); what it cannot prove is that
a *real model*, mid-drive, issues the tool call the gate/hook intercepts. These
configs have never been present in a live drive — that is the gap §3 names.

Covered here (each needs the model to choose the gated tool call, so each is a
genuine live drive):

* **3a** approvals ``run_command`` — a denied program token blocks a real
  ``run_command`` call; an allowed one runs.
* **3c** hooks — a ``pre_tool`` hook denies a real ``write_file`` call; a separate
  rewrite hook swaps its arguments.
* **3d** per-model hooks overlay — a hook present ONLY in
  ``.colleague/<sanitized-model>/hooks.json`` fires (no base hook), proving the
  loop loads the overlay via ``load_hooks(repo, model=config.model)``.
* **3e** (soft) a per-model AGENTS layer asks for a summary marker — printed, not
  asserted; the deterministic proof lives in ``test_gated_configs_enforcement.py``.

The checksum-void (3b) and the prompt composition (3e) are engine-agnostic and are
proven deterministically in ``tests/test_gated_configs_enforcement.py``.

Run it (rig up) like::

    COLLEAGUE_VLLM_E2E=1 uv run pytest tests/test_vllm_live_gated_configs.py -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from colleague.cli._commands.drive import execute_drive
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult
from colleague.layers import sanitize_model

# Run only when either gate var is explicitly "1" (the deprecated CONVERTIBLE_*
# is honored as a fallback). Membership — not `A or B` — so a truthy non-"1"
# primary (e.g. "0") cannot mask a "1" fallback.
pytestmark = pytest.mark.skipif(
    "1" not in (os.environ.get("COLLEAGUE_VLLM_E2E"), os.environ.get("CONVERTIBLE_VLLM_E2E")),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live vLLM server) to run the live proof",
)


def _hook_cmd(script_rel: str) -> str:
    """A hook command that runs *script_rel* with THIS interpreter.

    Uses ``sys.executable`` (an absolute path), not a bare ``python3`` on PATH:
    the hook runner maps a launch failure / non-zero exit to a *deny*, so a
    missing ``python3`` would silently flip a hook's decision for the wrong reason.
    """
    return f"{sys.executable} {script_rel}"


# Dependency-free hook scripts (read the JSON tool-call payload from stdin, emit a
# decision on stdout). Written into the repo at setup; no jq, no third-party deps.
_DENY_WRITES = (
    "import sys, json\njson.load(sys.stdin)\n"
    'print(json.dumps({"decision": "deny", "reason": "writes denied by pre_tool hook"}))\n'
)

_REWRITE_PATH = (
    "import sys, json\n"
    "payload = json.load(sys.stdin)\n"
    "args = dict(payload.get('arguments') or {})\n"
    "args['path'] = 'rewritten.txt'\n"
    'print(json.dumps({"decision": "rewrite", "arguments": args}))\n'
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit (the handoff needs a HEAD)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def _write(repo: Path, rel: str, text: str) -> Path:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _write_json(repo: Path, rel: str, payload: dict) -> Path:
    return _write(repo, rel, json.dumps(payload))


def _drive(repo: Path, instruction: str, label: str) -> TaskResult:
    task = Task.new(str(repo), instruction, engine="vllm-openai")
    result, artifact_path = execute_drive(
        repo=repo,
        engine_name="vllm-openai",
        task=task,
        open_pr=False,
        base="main",
        config=EngineConfig.resolve(),
    )
    print(f"\n[live #123 {label}] drive {result.task_id} -> {artifact_path}")
    print(f"[live #123 {label}] steps: {[(s.tool, s.ok) for s in result.steps]}")
    print(
        f"[live #123 {label}] hook_firings: {[(h.event, h.decision) for h in result.hook_firings]}"
    )
    return result


# ---------------------------------------------------------------------------
# 3a — approvals.json gates run_command by program token
# ---------------------------------------------------------------------------


def test_3a_run_command_denied_token_is_blocked(git_repo: Path) -> None:
    _write_json(
        git_repo, ".colleague/approvals.json", {"run_command": {"deny": ["curl"], "allow": []}}
    )
    result = _drive(
        git_repo,
        "Use the run_command tool to run exactly this shell command: "
        "curl http://localhost:8001/v1/models . If it is blocked, just call finish.",
        "3a-deny",
    )
    denied = [s for s in result.steps if s.tool == "run_command" and not s.ok]
    assert denied, "the model never issued a run_command call to gate"
    assert any("deny" in s.result.lower() and "curl" in s.result for s in denied)


def test_3a_run_command_allowed_token_runs(git_repo: Path) -> None:
    _write_json(
        git_repo, ".colleague/approvals.json", {"run_command": {"allow": ["echo"], "deny": []}}
    )
    result = _drive(
        git_repo,
        "Use the run_command tool to run exactly this shell command: echo hello ."
        " Then call finish.",
        "3a-allow",
    )
    ran = [s for s in result.steps if s.tool == "run_command" and s.ok]
    assert ran, "the allowed run_command never executed"
    assert any("exit=0" in s.result and "hello" in s.result for s in ran)


# ---------------------------------------------------------------------------
# 3c — pre_tool hooks deny / rewrite a real tool call
# ---------------------------------------------------------------------------

_WRITE_TASK = (
    "Use the write_file tool to create a file named notes.txt with the content"
    " 'hello'. Then call finish."
)


def test_3c_pre_tool_hook_denies_write(git_repo: Path) -> None:
    _write(git_repo, ".colleague/hooks/deny_writes.py", _DENY_WRITES)
    _write_json(
        git_repo,
        ".colleague/hooks.json",
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": _hook_cmd(".colleague/hooks/deny_writes.py"),
                    }
                ]
            }
        },
    )
    result = _drive(git_repo, _WRITE_TASK, "3c-deny")
    denials = [h for h in result.hook_firings if h.event == "pre_tool" and h.decision == "deny"]
    assert denials, "the pre_tool deny hook never fired"
    blocked = [s for s in result.steps if s.tool == "write_file" and not s.ok]
    assert blocked, "write_file was not blocked by the deny hook"
    assert not (git_repo / "notes.txt").exists(), "denied write must not land on disk"


def test_3c_pre_tool_hook_rewrites_write(git_repo: Path) -> None:
    _write(git_repo, ".colleague/hooks/rewrite_path.py", _REWRITE_PATH)
    _write_json(
        git_repo,
        ".colleague/hooks.json",
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": _hook_cmd(".colleague/hooks/rewrite_path.py"),
                    }
                ]
            }
        },
    )
    result = _drive(git_repo, _WRITE_TASK, "3c-rewrite")
    rewrites = [h for h in result.hook_firings if h.event == "pre_tool" and h.decision == "rewrite"]
    assert rewrites, "the pre_tool rewrite hook never fired"
    # The loop records the EXECUTED (rewritten) write_file path in changed_files —
    # the robust signal that the rewrite took effect. We do NOT check the file on
    # disk: execute_drive's handoff commits drive output to the colleague/<id>
    # branch and restores the working tree, so drive-produced files aren't present
    # afterward (an on-disk check would be confounded by the handoff, not the hook).
    assert "rewritten.txt" in result.changed_files, "the rewritten path is not in changed_files"
    assert (
        "notes.txt" not in result.changed_files
    ), "the model's original write_file path should have been swapped by the hook"


# ---------------------------------------------------------------------------
# 3d — per-model hooks overlay fires (no base hook present)
# ---------------------------------------------------------------------------


def test_3d_per_model_overlay_hook_fires(git_repo: Path) -> None:
    safe = sanitize_model(EngineConfig.resolve().model)
    _write(git_repo, ".colleague/hooks/deny_writes.py", _DENY_WRITES)
    # The deny hook lives ONLY in the per-model overlay — there is no base hooks.json.
    _write_json(
        git_repo,
        f".colleague/{safe}/hooks.json",
        {
            "hooks": {
                "pre_tool": [
                    {
                        "matcher": "write_file",
                        "command": _hook_cmd(".colleague/hooks/deny_writes.py"),
                    }
                ]
            }
        },
    )
    assert not (git_repo / ".colleague" / "hooks.json").exists(), "no base hook — overlay only"
    result = _drive(git_repo, _WRITE_TASK, "3d-overlay")
    denials = [h for h in result.hook_firings if h.event == "pre_tool" and h.decision == "deny"]
    assert denials, "the per-model overlay deny hook never fired (overlay not loaded?)"
    blocked = [s for s in result.steps if s.tool == "write_file" and not s.ok]
    assert blocked, "the overlay hook did not block write_file"


# ---------------------------------------------------------------------------
# 3e (soft) — a per-model AGENTS layer reaches the model. Best-effort: printed,
# never hard-asserted, since colleague records the composed prompt nowhere and a
# live model may paraphrase. The deterministic proof is in the sibling file.
# ---------------------------------------------------------------------------


def test_3e_per_model_agents_layer_soft_marker(git_repo: Path) -> None:
    safe = sanitize_model(EngineConfig.resolve().model)
    _write(
        git_repo,
        f"AGENTS.colleague.{safe}.md",
        "When you call finish, set the summary to exactly: AGENTS_LAYER_ACTIVE\n",
    )
    result = _drive(git_repo, "Read README.md, then call finish.", "3e-marker")
    reflected = "AGENTS_LAYER_ACTIVE" in (result.summary or "")
    print(f"[live #123 3e-marker] AGENTS layer reflected in summary: {reflected}")
    assert result.status == OK, result.error

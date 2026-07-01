"""Live mode-profile proof against a served tool-calling model (plan t19 / risk r3).

Skipped unless ``COLLEAGUE_VLLM_E2E=1`` (the standard live-proof gate): the
reference rig must serve a tool-calling model (``--enable-auto-tool-choice`` +
a tool-call parser). As of 2026-07-02 the rig does NOT — ``/v1/models``
stale-lists the 27B (completions 404) and the served Qwen3.5-4B rejects tool
calls (see the evidence on issue #66) — so this proof is RECORDED AS PENDING
in ``docs/live-testing.md`` rather than claimed; the mock e2e
(``test_mode_e2e_validation.py``) is the validated floor until serving is
fixed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    "1"
    not in (
        os.environ.get("COLLEAGUE_VLLM_E2E"),
        os.environ.get("CONVERTIBLE_VLLM_E2E"),
    ),
    reason="set COLLEAGUE_VLLM_E2E=1 (with a live tool-calling vLLM server) to run",
)


def test_mode_explore_live(tmp_path: Path) -> None:
    """A live ``--mode explore`` run completes inside its profile (30 steps)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    for key, value in (("user.email", "t@e.c"), ("user.name", "T")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    (tmp_path / "README.md").write_text("A tiny repo with one README.\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    from colleague.cli._commands.work import cmd_work

    args = argparse.Namespace(
        instruction=["what", "does", "this", "repo", "contain?"],
        repo=str(tmp_path),
        engine="vllm-openai",
        no_pr=True,
        watch=False,
        base="main",
        model=None,
        base_url=None,
        api_key=None,
        max_steps=None,
        json=True,
        command_name=None,
        allow_dirty=True,
        tui=None,
        tui_events=None,
        mode="explore",
        role=None,
    )
    rc = cmd_work(args)
    artifacts = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((tmp_path / ".colleague").glob("*.json"))
    ]
    assert artifacts, "a moded live run must still write an artifact"
    assert artifacts[0].get("mode") == "explore"
    # The explore profile caps steps at 30; the step trace must respect it.
    assert len(artifacts[0].get("steps", [])) <= 30
    assert rc in (0, 2)  # ok, or honest INCOMPLETE — never a crash

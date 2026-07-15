"""Executable #285 acceptance proof — the coder-agent cockpit reads like a real
cockpit in BOTH states (task t10).

Makes the issue's acceptance concrete: from ONE rendered frame per state an
operator can answer the five idle questions (identity → permissions → workspace
→ capacity → next action) and, while a work item runs, see the live phase/step/
current-op status, the mutation ledger, and the disambiguated mode facts. Also
pins that every new panel reaches the agent-facing tiers (TAUI mirror + Markdown)
through the GENERIC panel walk — zero per-renderer code — and that a running
frame is visibly different from an idle one.

These assertions ride the imported ``agentfront.taui`` render paths only; there
is no colleague-side renderer (the #249 rule). The structural boundary proofs
(no colleague module shadows ``agentfront.taui``; the new pure helpers are not
under ``colleague/tui/``) live in ``tests/test_boundary.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentfront.taui.mirror import serialize
from agentfront.taui.render.ansi_flat import render_flat
from agentfront.taui.render.markdown import render_markdown

from colleague import icons
from colleague.cli._commands.session import (
    _ACTIVE_RUN_PANEL_ID,
    _CAPACITY_PANEL_ID,
    _LAST_RUN_PANEL_ID,
    _NEXT_PANEL_ID,
    SessionIO,
    _Session,
)
from colleague.config import EngineConfig
from colleague.contract import OK, Task, TaskResult, WorkStats


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _session(repo: Path, *, view: str = "markdown", open_pr: bool = False) -> _Session:
    return _Session(
        repo=repo,
        engine_name="mock",
        open_pr=open_pr,
        base="main",
        config=EngineConfig.resolve(model="m"),
        json_mode=False,
        view=view,
        io=SessionIO(out=lambda *a, **k: None, err=lambda *a, **k: None),
        work_fn=lambda **k: None,
    )


def _with_template(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git_repo(repo)
    cmds = repo / ".colleague" / "commands"
    cmds.mkdir(parents=True)
    (cmds / "setup.md").write_text("Set up the dev env.\n")
    return repo


# ── the five idle questions, answerable from ONE rendered frame ──────────────


def test_idle_frame_answers_the_five_questions(tmp_path: Path) -> None:
    """#285 acceptance: an idle frame answers identity → permissions → workspace
    → capacity → next action."""
    _with_template(tmp_path)
    frame = render_flat(_session(tmp_path).state, include_prompt=False)

    # 1. identity — whose repo / which colleague.
    assert tmp_path.name in frame
    # 2. permissions — the Run policy safety surface (honest, no invented gates).
    assert "run_command" in frame and "push + PR" in frame
    assert "requires confirmation" not in frame and "sandbox" not in frame.lower()
    # 3. workspace — branch + working-tree state.
    assert "branch" in frame and ("clean" in frame or "dirty" in frame)
    # 4. capacity — the context budget / mode profile.
    assert "budget" in frame and "tokens" in frame
    # 5. next action — the first-class Next panel with a concrete suggestion.
    assert icons.label("Next", "next", "emoji") in frame
    assert "Safest next" in frame


def test_idle_disambiguated_mode_facts_are_three_distinct_facts(tmp_path: Path) -> None:
    """#285: mode is three DISTINCT facts (behavior · source · execution profile),
    never one conflated line."""
    _with_template(tmp_path)
    panels = {p["id"]: p for p in serialize(_session(tmp_path).state)["panels"]}
    cap = panels[_CAPACITY_PANEL_ID]
    item_ids = {i["id"] for i in cap["items"]}
    # behavior+source is one row; the execution profile is a SEPARATE row.
    assert {"cap.mode", "cap.mode_profile"} <= item_ids
    mode_row = next(i for i in cap["items"] if i["id"] == "cap.mode")
    assert "auto" in mode_row["status"]  # behavior=auto, source=auto by default


# ── the running frame is visibly different + answers the running questions ───


def _run_and_capture(tmp_path: Path) -> dict:
    """Drive one work item; capture the RUNNING frame mid-flight + the finished state."""
    captured: dict = {}

    def _work_fn(*, display, **kwargs: object) -> tuple[TaskResult, Path]:
        progress_sink = display.sink
        progress_sink(0, "", "thinking… (waiting on the model)", True)  # a phase notice
        progress_sink(1, "edit_file", "colleague/loop.py", True)
        progress_sink(2, "run_command", "pytest -q", True)
        captured["running_flat"] = render_flat(s.state, include_prompt=False)
        captured["running_md"] = render_markdown(s.state)
        captured["running_panels"] = {p.id: p for p in s.state.panels}
        return (
            TaskResult(
                task_id="x",
                status=OK,
                summary="done",
                branch="colleague/x",
                stats=WorkStats(files_changed=1, tool_counts={"run_command": 1, "edit_file": 1}),
            ),
            tmp_path / "art.json",
        )

    s = _session(_with_template(tmp_path), view="markdown")
    s.work_fn = _work_fn
    captured["idle_flat"] = render_flat(s.state, include_prompt=False)
    s._run_work(Task.new(str(tmp_path), "wire the cockpit running state"), None)
    captured["finished_panels"] = {p.id: p for p in s.state.panels}
    captured["finished_md"] = render_markdown(s.state)
    captured["finished_status"] = s.state.status.message
    return captured


def test_running_frame_differs_from_idle_and_answers_running_questions(tmp_path: Path) -> None:
    cap = _run_and_capture(tmp_path)

    # The running frame is visibly DIFFERENT from the idle frame.
    assert cap["running_flat"] != cap["idle_flat"]

    panels = cap["running_panels"]
    # templates collapse, the Active-run panel appears, the idle Next is gone.
    assert panels["commands"].visible is False
    assert _ACTIVE_RUN_PANEL_ID in panels
    assert _NEXT_PANEL_ID not in panels

    # live status: phase cleared, step progress + current op shown.
    md = cap["running_md"]
    assert "step 2" in md  # two REAL steps folded (the phase notice is not a step)
    assert "[run_command] pytest -q" in md  # current op

    # the mutation ledger (changes-so-far) is present, commits OMITTED mid-run.
    active = panels[_ACTIVE_RUN_PANEL_ID]
    changes = next(i for i in active.items if i.id == "run.changes")
    assert changes.status == "1 files · 1 commands"


def test_finish_restores_idle_with_authoritative_last_run_ledger(tmp_path: Path) -> None:
    cap = _run_and_capture(tmp_path)
    panels = cap["finished_panels"]
    # idle layout restored.
    assert panels["commands"].visible is True
    assert _ACTIVE_RUN_PANEL_ID not in panels
    assert _NEXT_PANEL_ID in panels
    # the authoritative Last-run ledger is present with the reconciled numbers.
    assert _LAST_RUN_PANEL_ID in panels
    last = panels[_LAST_RUN_PANEL_ID]
    items = {i.id: i.status for i in last.items}
    assert items["last.files"] == "1"  # verbatim from TaskResult.stats.files_changed
    assert items["last.commands"] == "1"  # run_command count
    assert items["last.commits"] == "1"  # a committed branch → 1 commit
    assert items["last.publish"] == "local"  # committed, no PR

    # the status line is reset to the idle status — the running line
    # ("step N · [tool] …") must NOT linger on the restored idle frame (Qodo PR #288).
    status = cap["finished_status"]
    assert "step " not in status and "[run_command]" not in status
    assert "colleague session" in status  # the idle status line is back


# ── every new panel reaches the agent tiers through the generic walk ─────────


def test_new_panels_reach_mirror_and_markdown_via_generic_walk(tmp_path: Path) -> None:
    """The Next / Capacity panels (idle) and Active-run / Last-run panels
    (running) all render on the TAUI mirror + Markdown tiers with ZERO
    per-renderer code — proven by their presence via the generic panel walk."""
    cap = _run_and_capture(tmp_path)

    # Idle-side panels on the mirror.
    idle_ids = {
        p["id"] for p in serialize(_session(_with_template(tmp_path / "b")).state)["panels"]
    }
    assert {_NEXT_PANEL_ID, _CAPACITY_PANEL_ID, "policy", "context"} <= idle_ids

    # Running/finished panels reach Markdown (## headings) through the walk.
    running_md = cap["running_md"]
    assert f"## {icons.label('Active run', 'run', 'emoji')}" in running_md
    finished_md = cap["finished_md"]
    assert f"## {icons.label('Last run', 'ledger', 'emoji')}" in finished_md

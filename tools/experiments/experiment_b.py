"""Experiment B — worker promotion gate (pre-registered runner).

Protocol: docs/experiments/2026-08-05-experiment-b-worker-promotion.md
(committed BEFORE the first measured run; deviation d1 explains the vehicle).

Two arms, identical everything except the acting seat:

* ``baseline``  — legacy resolution (cortex acts).
* ``worker``    — ``COLLEAGUE_THREE_TIER=1`` (worker acts via t8's wiring).

For each arm, materializes the committed fixture repo into a fresh temp git
repo and runs the four pre-registered tasks serially via ``colleague work
--repo <tmp> --no-pr``, then harvests each run's artifact (status, steps,
tokens, wall time, finish_states truncation counts, commits landed on the
drive branch). Emits one JSON line per run and a per-arm summary. Quality
grading is operator-side (the protocol's rubric), from the drive-branch
diffs the runner prints paths for.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

FIXTURE = pathlib.Path(__file__).parent / "fixture_repo_b"

TASKS = [
    (
        "fix-divide",
        "Fix the failing test in test_calc.py: divide() must return the "
        "documented 0.0 sentinel on a zero denominator instead of crashing. "
        "Make the whole suite green with python -m pytest -q.",
    ),
    (
        "add-mean",
        "Add a mean(values) function to calc.py returning the arithmetic "
        "mean of the list (an empty list returns 0.0), plus a test for both "
        "cases in test_calc.py. Keep the suite green.",
    ),
    (
        "rename-acc",
        "Rename the internal helper _acc to _accumulate across the package, "
        "updating every reference. The suite must stay green.",
    ),
    (
        "write-usage",
        "Write USAGE.md documenting each public function in calc.py (add, "
        "divide, total, and mean if present) with one runnable example each.",
    ),
]


def _run(cmd, cwd, env=None, timeout=900):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def _materialize() -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="expb-"))
    for f in FIXTURE.iterdir():
        shutil.copy(f, tmp / f.name)
    _run(["git", "init", "-q"], tmp)
    _run(["git", "config", "user.email", "expb@example.com"], tmp)
    _run(["git", "config", "user.name", "expb"], tmp)
    _run(["git", "add", "-A"], tmp)
    _run(["git", "commit", "-qm", "fixture"], tmp)
    return tmp


def _artifact_facts(repo: pathlib.Path) -> dict:
    adir = repo / ".colleague"
    arts = sorted(adir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not arts:
        return {"artifact": None}
    data = json.loads(arts[-1].read_text())
    stats = data.get("stats") or {}
    finish = data.get("finish_states") or []
    truncated = sum(1 for f in finish if f.get("state") == "truncated")
    return {
        "status": data.get("status"),
        "steps": stats.get("step_count"),
        "model_turns": stats.get("model_turns"),
        "total_tokens": (stats.get("prompt_tokens") or 0) + (stats.get("completion_tokens") or 0),
        "truncated_turns": truncated,
        "finish_states": [f.get("state") for f in finish],
        "incompletion": (data.get("incompletion") or {}).get("reason"),
    }


def _drive_branch_diffstat(repo: pathlib.Path) -> str:
    out = _run(["git", "branch", "--list", "colleague/*"], repo).stdout
    branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    if not branches:
        return "(no drive branch)"
    stat = _run(["git", "diff", "--stat", "main..." + branches[-1]], repo).stdout
    if not stat:
        stat = _run(["git", "diff", "--stat", "master..." + branches[-1]], repo).stdout
    return stat.strip() or "(empty diff)"


def main() -> int:
    colleague_repo = pathlib.Path.cwd()
    rows = []
    for arm in ("baseline", "worker"):
        for task_id, task_text in TASKS:
            repo = _materialize()
            env = dict(os.environ)
            env["CONVERTIBLE_MODEL"] = "unsloth/Qwen3.6-27B-NVFP4"
            env["COLLEAGUE_TIMEOUT"] = "300"
            if arm == "worker":
                env["COLLEAGUE_THREE_TIER"] = "1"
            else:
                env.pop("COLLEAGUE_THREE_TIER", None)
            t0 = time.monotonic()
            proc = _run(
                [
                    "uv",
                    "run",
                    "colleague",
                    "work",
                    task_text,
                    "--repo",
                    str(repo),
                    "--no-pr",
                ],
                cwd=colleague_repo,
                env=env,
                timeout=1200,
            )
            wall = round(time.monotonic() - t0, 1)
            facts = _artifact_facts(repo)
            row = {
                "arm": arm,
                "task": task_id,
                "exit": proc.returncode,
                "wall_s": wall,
                "repo": str(repo),
                "diffstat": _drive_branch_diffstat(repo),
                **facts,
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    for arm in ("baseline", "worker"):
        arm_rows = [r for r in rows if r["arm"] == arm]
        summary = {
            "arm": arm,
            "runs": len(arm_rows),
            "ok": sum(1 for r in arm_rows if r.get("status") == "ok"),
            "incomplete": sum(1 for r in arm_rows if r.get("incompletion")),
            "truncated_turns": sum(r.get("truncated_turns") or 0 for r in arm_rows),
            "wall_s": round(sum(r["wall_s"] for r in arm_rows), 1),
            "tokens": sum(r.get("total_tokens") or 0 for r in arm_rows),
        }
        print("ARM " + json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

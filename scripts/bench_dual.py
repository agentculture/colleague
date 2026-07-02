#!/usr/bin/env python3
"""Wall-clock benchmark procedure: single-model vs. dual-model deepthink.

Plan task t10 (spec docs/specs/2026-07-01-colleague-drives-with-two-minds-a
-fast-wide-window.md, claims c16/h8, c3/h12). This is the SCRIPTED PROCEDURE
the spec's success signal asks for, not a validated result: it can only run
once the reference rig serves a tool-calling-capable model — as of 2026-07-02
it does not (see docs/live-testing.md, issue #66). It refuses to run against
an unreachable endpoint rather than fake a comparison.

Runs the same small set of benchmark task instructions (``BENCH_TASKS``)
twice through a real ``colleague work`` invocation: once **single** (the
deepthink env vars stripped from the subprocess environment, so the run is
single-model exactly as today regardless of your shell) and once **dual**
(the current environment as-is, so ``COLLEAGUE_DEEPTHINK_*`` takes effect).
Each (mode, task) pair gets its own disposable one-commit git repo. Wall-clock,
exit status, and step count are read back from the produced ``.colleague/
<id>.json`` artifact and printed as a comparison table.

QUALITY is NOT graded here — grade each printed task_id via the existing
feedback loop (``colleague feedback record <task_id> --rating N``).

Usage::

    uv run python scripts/bench_dual.py

Configure the two endpoints exactly like any other colleague run: the main
model via ``COLLEAGUE_BASE_URL``/``COLLEAGUE_MODEL``/``COLLEAGUE_API_KEY``,
the deepthink model via ``COLLEAGUE_DEEPTHINK_MODEL``/``_BASE_URL``/
``_API_KEY``/``_CONTEXT_BUDGET`` (see ``colleague/config.py``). Refuses to run
(clear error, exit 1) when either configured endpoint does not answer.

Stdlib only — no new dependency.
"""

from __future__ import annotations

import json
import os

# subprocess shells out to git and to `colleague work` itself — every call
# below passes a fixed argv list, never shell=True / untrusted interpolation.
import subprocess  # nosec B404
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

_PROBE_TIMEOUT = 3.0

# A handful of small, judgment-flavored tasks over one tiny module — enough to
# exercise both a mechanical edit and a design decision without needing a real
# project. This is a latency/status comparison, not a stress test.
BENCH_TASKS = [
    "Add a one-line docstring to calc.py's add_all function explaining what it computes.",
    "Review calc.py's add_all: decide whether a for-loop or Python's built-in "
    "sum() is the better design here. State your decision and a one-line "
    "rationale in the finish summary; do not change any code.",
    "Read calc.py and list, in the finish summary, any edge cases add_all does "
    "not handle (e.g. an empty list or non-numeric input). Do not change any code.",
    "Add a second function, subtract_all(nums), to calc.py that returns the "
    "running difference starting from the first element, mirroring add_all's style.",
]

_DEEPTHINK_ENV_KEYS = (
    "COLLEAGUE_DEEPTHINK_MODEL",
    "CONVERTIBLE_DEEPTHINK_MODEL",
    "COLLEAGUE_DEEPTHINK_BASE_URL",
    "CONVERTIBLE_DEEPTHINK_BASE_URL",
    "COLLEAGUE_DEEPTHINK_API_KEY",
    "CONVERTIBLE_DEEPTHINK_API_KEY",
    "COLLEAGUE_DEEPTHINK_CONTEXT_BUDGET",
    "CONVERTIBLE_DEEPTHINK_CONTEXT_BUDGET",
)

_CALC_PY = (
    "def add_all(nums):\n    total = 0\n    for n in nums:\n        total += n\n    return total\n"
)


def _reachable(base_url: str) -> tuple[bool, str]:
    """GET ``{base_url}/models`` with a short timeout (mirrors doctor --probe)."""
    url = base_url.rstrip("/") + "/models"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=_PROBE_TIMEOUT):  # nosec B310
            return True, ""
    except urllib.error.HTTPError:
        return True, ""  # server answered, just not with 2xx — it is up
    except OSError as exc:
        return False, str(getattr(exc, "reason", exc))


def _refuse_unless_reachable() -> None:
    """Exit 1 with a clear message rather than benchmark a dead/unconfigured rig."""
    main_url = (
        os.environ.get("COLLEAGUE_BASE_URL")
        or os.environ.get("CONVERTIBLE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "http://localhost:8000/v1"
    )
    ok, reason = _reachable(main_url)
    if not ok:
        print(f"ERROR: main endpoint {main_url!r} is not reachable: {reason}", file=sys.stderr)
        print(
            "Start the served model, then re-check with 'colleague doctor --probe'.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.environ.get("COLLEAGUE_DEEPTHINK_MODEL"):
        print(
            "ERROR: no COLLEAGUE_DEEPTHINK_MODEL configured — set the deepthink "
            "env vars so the dual-model half of the comparison has a target.",
            file=sys.stderr,
        )
        sys.exit(1)
    dt_url = os.environ.get("COLLEAGUE_DEEPTHINK_BASE_URL") or main_url
    ok, reason = _reachable(dt_url)
    if not ok:
        print(f"ERROR: deepthink endpoint {dt_url!r} is not reachable: {reason}", file=sys.stderr)
        sys.exit(1)


def _make_repo(tmp_root: Path, name: str) -> Path:
    """A fresh one-commit git repo with a tiny calc.py, isolated per (mode, task)."""
    repo = tmp_root / name
    repo.mkdir(parents=True)
    for args in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "bench@colleague.test"],
        ["git", "config", "user.name", "bench"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    (repo / "calc.py").write_text(_CALC_PY)
    subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
        ["git", "add", "calc.py"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(  # nosec B603 B607 - fixed 'git' argv, no shell
        ["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True
    )
    return repo


def _latest_artifact(repo: Path) -> dict | None:
    artifacts = sorted((repo / ".colleague").glob("*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(artifacts[-1].read_text(encoding="utf-8")) if artifacts else None


def _run_one(repo: Path, instruction: str, env: dict) -> dict:
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "colleague", "work", instruction, "--repo", str(repo)]
        + ["--engine", "vllm-openai", "--no-pr"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - start
    artifact = _latest_artifact(repo) or {}
    return {
        "duration": duration,
        "returncode": proc.returncode,
        "status": artifact.get("status"),
        "steps": len(artifact.get("steps", [])) if artifact else None,
        "task_id": artifact.get("task_id"),
        "stderr_tail": "" if proc.returncode in (0, 2) else proc.stderr[-300:],
    }


def _single_model_env() -> dict:
    """The current environment with every deepthink knob stripped."""
    env = dict(os.environ)
    for key in _DEEPTHINK_ENV_KEYS:
        env.pop(key, None)
    return env


def _print_report(rows: list[dict]) -> None:
    header = f"{'mode':7} {'task':5} {'status':10} {'steps':6} {'wall(s)':8} {'task_id':14}"
    print(header)
    print("-" * len(header))
    by_task: dict[int, dict[str, dict]] = {}
    for row in rows:
        print(
            f"{row['mode']:7} {row['task_index'] + 1:<5} {str(row['status']):10} "
            f"{str(row['steps']):6} {row['duration']:<8.2f} {str(row['task_id']):14}"
        )
        if row["stderr_tail"]:
            print(f"         stderr: {row['stderr_tail']!r}")
        by_task.setdefault(row["task_index"], {})[row["mode"]] = row

    print("\nPer-task wall-clock, single vs. dual:")
    for idx, modes in sorted(by_task.items()):
        single, dual = modes.get("single"), modes.get("dual")
        if single and dual:
            delta = dual["duration"] - single["duration"]
            print(
                f"  task {idx + 1}: single={single['duration']:.2f}s "
                f"dual={dual['duration']:.2f}s delta={delta:+.2f}s"
            )


def main() -> int:
    _refuse_unless_reachable()

    tmp_root = Path(tempfile.mkdtemp(prefix="colleague-bench-dual-"))
    print(f"Benchmark scratch repos under: {tmp_root}\n")

    rows: list[dict] = []
    for mode, env in (("single", _single_model_env()), ("dual", dict(os.environ))):
        for index, instruction in enumerate(BENCH_TASKS):
            repo = _make_repo(tmp_root, f"{mode}-{index}")
            print(f"[{mode}] task {index + 1}/{len(BENCH_TASKS)}: {instruction[:60]}...")
            row = _run_one(repo, instruction, env)
            row.update(mode=mode, task_index=index)
            rows.append(row)

    print()
    _print_report(rows)
    print(
        "\nQuality is NOT graded by this script. Grade each printed task_id via "
        "the existing feedback loop, e.g.:\n"
        "  colleague feedback record <task_id> --rating N --notes '...' --repo <repo path>\n"
        f"Scratch repos are preserved at {tmp_root} for grading/inspection — "
        "delete them yourself when done."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

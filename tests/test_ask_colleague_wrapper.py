"""Tests for the ask-colleague wrapper shell script (issues #217, #219, #220a).

These assert the wrapper source contains the required changes and, where
practical, exercise the behaviour end-to-end in a temporary git repo.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "ask-colleague"
    / "scripts"
    / "ask-colleague.sh"
)
PROMPT_REVIEW = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "ask-colleague"
    / "prompts"
    / "review.md"
)


# ── Source-assertion tests ──────────────────────────────────────────────────


def _script_src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _review_prompt() -> str:
    return PROMPT_REVIEW.read_text(encoding="utf-8")


class TestDirtyGuardTrackedOnly:
    """Issue #217: the write --apply dirty guard must be TRACKED-ONLY."""

    def test_dirty_guard_contains_untracked_files_no(self) -> None:
        src = _script_src()
        assert "--untracked-files=no" in src, "dirty guard must use --untracked-files=no"

    def test_dirty_guard_still_checks_porcelain(self) -> None:
        src = _script_src()
        assert "status --porcelain" in src, "dirty guard must still use --porcelain"


class TestMonitorFollow:
    """Issue #219: monitor must invoke flight status with --follow."""

    def test_run_monitor_has_follow(self) -> None:
        src = _script_src()
        # The invocation line should contain both "flight status" and "--follow".
        assert "flight status" in src
        assert "--follow" in src

    def test_monitor_help_mentions_follow(self) -> None:
        src = _script_src()
        # The usage/help line for monitor should mention --follow.
        assert "Stream a running flight's live feed (--follow)" in src


class TestFrontLoadReviewDiff:
    """Issue #220a: front_load_review_diff function exists and is wired into review."""

    def test_function_exists(self) -> None:
        src = _script_src()
        assert "front_load_review_diff" in src

    def test_function_references_stat(self) -> None:
        src = _script_src()
        # The function body must reference --stat for the diffstat.
        func = _extract_function(src, "front_load_review_diff")
        assert "--stat" in func

    def test_function_references_max_output_chars(self) -> None:
        src = _script_src()
        func = _extract_function(src, "front_load_review_diff")
        assert "COLLEAGUE_MAX_OUTPUT_CHARS" in func

    def test_function_references_exclude_pathspec(self) -> None:
        src = _script_src()
        func = _extract_function(src, "front_load_review_diff")
        assert ":(exclude)" in func

    def test_function_bounds_the_buffering(self) -> None:
        """#324: the diff is piped through `head -c` so the substitution never
        materializes more than cap+1 bytes, instead of buffering the full diff
        and capping only the printed output."""
        src = _script_src()
        func = _extract_function(src, "front_load_review_diff")
        assert "head -c" in func

    def test_review_dispatch_includes_front_load(self) -> None:
        src = _script_src()
        # The review case should call front_load_review_diff.
        assert "front_load_review_diff" in src
        # The dispatch line should append the diff output.
        assert "front_load_review_diff)" in src

    def test_review_prompt_says_diff_provided(self) -> None:
        prompt = _review_prompt()
        assert "ALREADY PROVIDED" in prompt or "already provided" in prompt.lower()

    def test_review_prompt_no_longer_instructs_git_diff(self) -> None:
        prompt = _review_prompt()
        # The prompt should NOT contain instructions to run `git diff` itself.
        assert "git diff" not in prompt


def _extract_function(src: str, name: str) -> str:
    """Extract a bash function body from the script source."""
    # Match `name() {` or `name () {` (bash function syntax)
    pattern = rf"{name}\s*\(\s*\)\s*\{{"
    m = re.search(pattern, src)
    if not m:
        return ""
    start = m.start()
    # Find the matching closing brace by counting braces.
    depth = 0
    i = start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    return src[start:]


# ── Behavioural test ────────────────────────────────────────────────────────


class TestFrontLoadReviewDiffBehavior:
    """End-to-end: front_load_review_diff excludes lockfiles and caps output."""

    def test_excludes_lockfiles_and_includes_py(self, tmp_path: Path) -> None:
        """In a tmp git repo with a committed base and a change touching both
        a .lock file and a .py file, the diff should include the .py change
        but NOT the .lock change."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "init",
            ],
            check=True,
        )

        # Create a .py file and a .lock file.
        (repo / "app.py").write_text("def hello():\n    pass\n")
        (repo / "requirements.lock").write_text("flask==2.0.0\n")

        # Stage and commit the base.
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "-m",
                "add files",
            ],
            check=True,
        )

        base_ref = "HEAD~1"

        # Now modify both files.
        (repo / "app.py").write_text("def hello():\n    print('hello')\n")
        (repo / "requirements.lock").write_text("flask==3.0.0\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "-m",
                "update files",
            ],
            check=True,
        )

        # Source the wrapper and call front_load_review_diff.
        # We need to set REPO and BASE, and also set up a minimal colleague env
        # so the script doesn't fail on resolve_colleague. We just need the
        # function, so we source a trimmed version.
        script_src = SCRIPT.read_text(encoding="utf-8")

        # Extract just the front_load_review_diff function and run it.
        func_src = _extract_function(script_src, "front_load_review_diff")
        assert func_src, "Could not extract front_load_review_diff"

        # Build a minimal script that sources the function and calls it.
        # Use raw string to avoid Python f-string interpreting bash ${} as format specs.
        runner = tmp_path / "runner.sh"
        runner.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + func_src + "\nfront_load_review_diff\n"
        )
        runner.chmod(0o755)

        env = {**os.environ, "REPO": str(repo), "BASE": base_ref}
        result = subprocess.run(
            ["bash", str(runner)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        output = result.stdout + result.stderr

        # The .py change should appear in the diff body.
        assert "app.py" in output, f"app.py should be in diff output: {output}"

        # The .lock file should NOT appear in the diff *body* (excluded by pathspec).
        # The diffstat (--stat) always shows all files, so we check the body portion
        # after the diffstat. The body starts after the blank line following --stat.
        parts = output.split("--- DIFF UNDER REVIEW", 1)
        assert len(parts) == 2, "header not found"
        after_header = parts[1]
        # The diff body contains "diff --git" lines; the lockfile should not.
        # Check that the lockfile does NOT appear in a "diff --git" line.
        for line in after_header.splitlines():
            if "diff --git" in line:
                assert (
                    "requirements.lock" not in line
                ), f"requirements.lock should be excluded from diff body: {line}"

    def test_oversized_diff_is_truncated_with_marker(self, tmp_path: Path) -> None:
        """#324: with a tiny cap, a diff larger than the cap comes back truncated
        (bounded output + the truncation marker), and the SIGPIPE from `head`
        closing git's pipe early is absorbed under `set -o pipefail`."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "big.py").write_text("# base\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-q", "-m", "base"],
            check=True,
        )
        (repo / "big.py").write_text("\n".join(f"line_{i} = {i}" for i in range(2000)) + "\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-q", "-m", "big change"],
            check=True,
        )

        func_src = _extract_function(SCRIPT.read_text(encoding="utf-8"), "front_load_review_diff")
        runner = tmp_path / "runner.sh"
        runner.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + func_src + "\nfront_load_review_diff\n"
        )
        runner.chmod(0o755)

        cap = 500
        env = {
            **os.environ,
            "REPO": str(repo),
            "BASE": "HEAD~1",
            "COLLEAGUE_MAX_OUTPUT_CHARS": str(cap),
        }
        result = subprocess.run(
            ["bash", str(runner)], capture_output=True, text=True, env=env, check=False
        )
        assert result.returncode == 0, result.stderr
        assert "truncated at 500 chars" in result.stdout
        # The body between the header and the marker is capped, not the full diff.
        body = result.stdout.split("--- DIFF UNDER REVIEW", 1)[1]
        body = body.split("[... diff body truncated", 1)[0]
        assert len(body) < 2 * cap + 200  # diffstat + capped body, nowhere near the full diff

    def test_diffstat_always_present(self, tmp_path: Path) -> None:
        """The diffstat line should always be present, even when the body is empty."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "init",
            ],
            check=True,
        )

        # Add a small file and commit.
        (repo / "small.txt").write_text("line1\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "-m",
                "add small",
            ],
            check=True,
        )

        script_src = SCRIPT.read_text(encoding="utf-8")
        func_src = _extract_function(script_src, "front_load_review_diff")
        runner = tmp_path / "runner.sh"
        runner.write_text(
            f"#!/usr/bin/env bash\nset -euo pipefail\n{func_src}\nfront_load_review_diff\n"
        )
        runner.chmod(0o755)

        env = {**os.environ, "REPO": str(repo), "BASE": "HEAD~1"}
        result = subprocess.run(
            ["bash", str(runner)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        output = result.stdout + result.stderr

        # The header should be present.
        assert "DIFF UNDER REVIEW" in output
        # The diffstat should mention small.txt.
        assert "small.txt" in output

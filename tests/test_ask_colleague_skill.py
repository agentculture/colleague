"""Offline guards for the `ask-colleague` skill (no live model).

These exercise the parts of the skill that do NOT invoke a drive: the prompt
templates render, the wrapper resolves verbs/flags, and the error paths exit
before `resolve_colleague` is ever reached. The live 27B behavior is proven by
dogfooding, not in CI.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "ask-colleague"
SCRIPT = SKILL / "scripts" / "ask-colleague.sh"
PROMPTS = SKILL / "prompts"

VERBS = ("explore", "review", "write")


def _render(name: str, arg: str, base: str) -> str:
    """Mirror the wrapper's render_prompt single-pass substitution."""
    tpl = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    repl = {"$ARGUMENTS": arg, "$BASE": base}
    return re.compile(r"\$ARGUMENTS|\$BASE").sub(lambda m: repl[m.group(0)], tpl)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False)


def _init_repo(path: Path) -> Path:
    """Create a git repo with a single empty commit (HEAD to worktree from)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
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
    return path


def _fake_colleague(bindir: Path, body: str) -> dict[str, str]:
    """Drop a stub `colleague` on a fresh PATH and return the env to run with."""
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "colleague"
    fake.write_text(body)
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}


def _worktree_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return len([ln for ln in out.splitlines() if ln.strip()])


def test_skill_layout_exists() -> None:
    assert (SKILL / "SKILL.md").is_file()
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK), "ask-colleague.sh must be executable"
    for verb in VERBS:
        assert (PROMPTS / f"{verb}.md").is_file(), f"missing prompt: {verb}.md"


@pytest.mark.parametrize("name", VERBS)
def test_prompt_renders_arguments(name: str) -> None:
    out = _render(name, "INVESTIGATE_ME", "trunk")
    assert "INVESTIGATE_ME" in out
    assert "$ARGUMENTS" not in out


@pytest.mark.parametrize("name", ["explore", "review"])
def test_readonly_prompts_carry_a_guard(name: str) -> None:
    out = _render(name, "x", "main").lower()
    assert "read-only" in out
    assert "do not" in out and "modify" in out


def test_review_prompt_says_diff_is_provided() -> None:
    """The review prompt no longer instructs running `git diff` itself; the diff
    is front-loaded by the wrapper (issue #220a). The prompt should say the diff
    is already provided."""
    out = _render("review", "x", "develop")
    assert "ALREADY PROVIDED" in out or "already provided" in out.lower()
    # The prompt should NOT contain `git diff` instructions.
    assert "git diff" not in out


def test_write_prompt_leads_with_the_task_so_the_commit_subject_describes_it() -> None:
    """handoff._commit_subject takes the instruction's first line; the write prompt
    must lead with the task (not a boilerplate preamble) so the drive's commit
    subject / PR title describes the change instead of a generic template line (#121)."""
    out = _render("write", "Add a docstring to foo()", "main")
    first = next(ln for ln in out.splitlines() if ln.strip())
    assert first.strip() == "Add a docstring to foo()"


def test_write_prompt_asks_for_lint_clean_edits() -> None:
    """A whole-file rewrite can drop the EOF newline (W292) or overshoot the max
    line length (E501); the write prompt nudges the model to keep edits lint-clean (#121)."""
    out = _render("write", "x", "main").lower()
    assert "newline" in out
    assert "line length" in out


def test_help_lists_the_verbs() -> None:
    r = _run("--help")
    assert r.returncode == 0
    for verb in VERBS:
        assert verb in r.stdout


def test_help_lists_the_feedback_verb() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "feedback" in r.stdout
    assert "--rating" in r.stdout


def test_help_documents_the_default_model() -> None:
    r = _run("--help")
    assert "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP" in r.stdout


def test_help_documents_preview_by_default_and_apply() -> None:
    """write previews by default (#1); the --apply opt-in must be discoverable."""
    r = _run("--help")
    assert r.returncode == 0
    assert "--apply" in r.stdout
    assert "preview by default" in r.stdout


def test_unknown_verb_errors_with_hint() -> None:
    # #161: a bad verb is a user-input error -> exit 1 (not 2, which is reserved
    # for environment/setup failures).
    r = _run("frobnicate", "x")
    assert r.returncode == 1
    assert "unknown verb" in r.stderr


def test_no_args_errors() -> None:
    r = _run()
    assert r.returncode == 1  # #161: missing verb is a user-input error


def test_missing_description_errors() -> None:
    r = _run("explore")
    assert r.returncode == 1  # #161: missing arg is a user-input error
    assert "needs a description" in r.stderr


def test_trailing_value_flag_errors_cleanly() -> None:
    """A value-flag with no following value must exit 1 (user-input error, #161)
    with a clear message, not crash on an unbound $2 under `set -u` (qodo finding)."""
    r = _run("explore", "investigate x", "--repo")
    assert r.returncode == 1
    assert "requires a value" in r.stderr
    assert "unbound variable" not in r.stderr


def test_wrapper_prints_work_summary_with_a_fake_colleague(tmp_path) -> None:
    """End-to-end wrapper path (resolve -> render -> drive -> print_result) with a
    stubbed `colleague` that echoes a canned TaskResult. Guards the result
    extraction (in particular: print_result must read the piped JSON from stdin,
    not have it shadowed by a heredoc). Uses --apply to exercise the in-place
    write path now that `write` previews by default."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "colleague"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "ok", "summary": "FAKE_SUMMARY_OK", '
        '"changed_files": ["x.py"], "branch": "colleague/abc123"}\'\n'
    )
    fake.chmod(0o755)

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

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "FAKE_SUMMARY_OK" in r.stdout
    assert "x.py" in r.stdout
    assert "colleague/abc123" in r.stdout


def test_feedback_verb_shells_to_colleague_feedback(tmp_path) -> None:
    """`ask-colleague feedback <ref> --rating N` must invoke `colleague feedback
    record <ref> --rating N --repo <repo>` (the ROI loop pass-through, t9). A
    stub colleague records its argv so we can assert the mapping without a model."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text(
        "#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n' 'echo "recorded"\n'
    )
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "feedback",
            "last",
            "--rating",
            "4",
            "--notes",
            "good",
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert argv[:3] == ["feedback", "record", "last"]
    assert "--rating" in argv and "4" in argv
    assert "--notes" in argv and "good" in argv
    assert "--repo" in argv


def test_feedback_verb_without_rating_shows(tmp_path) -> None:
    """No --rating → `colleague feedback show <ref>` (read, not record)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n')
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "feedback", "abc123", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert argv[:3] == ["feedback", "show", "abc123"]


def test_feedback_verb_list_shells_to_colleague_feedback_list(tmp_path) -> None:
    """`ask-colleague feedback list` → `colleague feedback list --repo <repo>` (#132)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n')
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "feedback", "list", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert argv[:2] == ["feedback", "list"]
    assert "--repo" in argv
    assert "show" not in argv and "record" not in argv  # list is its own verb


def test_readonly_verb_isolates_in_a_worktree_and_cleans_up(tmp_path) -> None:
    """explore/review (run_readonly) must run in a throwaway worktree and remove
    it afterwards. Stub `colleague`, run `ask-colleague explore`, and assert the
    summary comes back AND the worktree count is unchanged (no leak). Covers the
    run_readonly path a 27B dogfood-review flagged as untested."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "colleague"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "ok", "summary": "READONLY_OK", "changed_files": []}\'\n'
    )
    fake.chmod(0o755)

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

    def _wt_count() -> int:
        out = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return len([ln for ln in out.splitlines() if ln.strip()])

    before = _wt_count()
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate something", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "READONLY_OK" in r.stdout
    assert _wt_count() == before, "worktree leaked — run_readonly did not clean up"


def _mode_aware_fake_colleague(argv_log: Path, env_log: Path | None, *, mode_in_help: bool) -> str:
    """A stub `colleague` whose `work --help` output mentions `--mode` iff
    *mode_in_help*, and which otherwise (any other invocation — the real
    drive call) records its argv (and, when *env_log* is given, its own
    environment) before echoing a canned successful TaskResult. Mirrors the
    resolved CLI: `colleague work --help` for mode detection, `colleague
    drive ...` for the actual work item (t4/spec R1)."""
    help_line = (
        'echo "usage: colleague work [-h] [--model MODEL] "'
        '"--mode {auto,work,plan,explore,review} ..."'
        if mode_in_help
        # Deliberately includes --model (every version has it) but NOT --mode —
        # this is the real shape of a stale pre-#254 colleague CLI, and it is
        # the regression case for the substring bug where a naive `*--mode*`
        # match false-positives on "--model" (which literally starts with the
        # substring "--mode").
        else 'echo "usage: colleague work [-h] [--engine ENGINE] "'
        '"[--model MODEL] [--max-steps N] [--json]"'
    )
    env_dump = f'env > "{env_log}"\n' if env_log is not None else ""
    return (
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "work" && "$2" == "--help" ]]; then\n'
        f"    {help_line}\n"
        "    exit 0\n"
        "fi\n"
        f'printf "%s\\n" "$@" > "{argv_log}"\n'
        f"{env_dump}"
        'echo \'{"status": "ok", "summary": "MODE_STUB_OK", "changed_files": []}\'\n'
    )


@pytest.mark.parametrize("verb", ["explore", "review"])
def test_explore_review_adopt_native_mode_profile(tmp_path, verb: str) -> None:
    """t4/spec R1: when the resolved `colleague` supports `--mode`, explore/review
    select colleague's own native "explore"/"review" mode profile
    (colleague/profiles.py) instead of the wrapper's OLD caller-side overrides —
    no wrapper-default `--max-steps` is forwarded (the profile supplies it as a
    runtime DEFAULT) and no `COLLEAGUE_SYNTHESIS_RESERVE_STEPS` env var is
    exported (the profile's own reserve knob covers it)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    env_log = tmp_path / "env.txt"
    fake = bindir / "colleague"
    fake.write_text(_mode_aware_fake_colleague(argv_log, env_log, mode_in_help=True))
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("COLLEAGUE_SYNTHESIS_RESERVE_STEPS", None)
    args = ["bash", str(SCRIPT), verb, "investigate something", "--repo", str(repo)]
    if verb == "review":
        # review validates --base against a real ref before rendering the prompt;
        # _init_repo's default branch name depends on the local git config
        # (init.defaultBranch), so pin --base to the repo's actual current branch
        # rather than assume "main".
        branch = subprocess.run(
            ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        args += ["--base", branch]
    r = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert "--mode" in argv, argv
    assert argv[argv.index("--mode") + 1] == verb
    assert "--max-steps" not in argv, argv
    env_text = env_log.read_text()
    assert "COLLEAGUE_SYNTHESIS_RESERVE_STEPS" not in env_text


@pytest.mark.parametrize("explicit_steps", [12, 50])
def test_explicit_max_steps_still_wins_over_the_mode_profile(tmp_path, explicit_steps: int) -> None:
    """An explicit `--max-steps` from the caller must still be forwarded and win
    over the mode profile's own default (30) — in EITHER direction, lower (12)
    or higher (50) than the profile's number — because the runtime treats an
    explicit flag as authoritative ahead of any profile default."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text(_mode_aware_fake_colleague(argv_log, None, mode_in_help=True))
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "explore",
            "investigate something",
            "--repo",
            str(repo),
            "--max-steps",
            str(explicit_steps),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert "--max-steps" in argv, argv
    assert argv[argv.index("--max-steps") + 1] == str(explicit_steps)
    # The mode is still selected — only the step count is caller-overridden.
    assert "--mode" in argv, argv
    assert argv[argv.index("--mode") + 1] == "explore"


def test_write_keeps_legacy_max_steps_default_and_gains_no_mode(tmp_path) -> None:
    """write must stay byte-identical (t4 point 3): it keeps its existing
    `--max-steps 20` default and never gains a `--mode` flag — even against a
    `colleague` that supports `--mode` — because write's profile is
    behavior-neutral (identical to no mode at all)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text(_mode_aware_fake_colleague(argv_log, None, mode_in_help=True))
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert "--max-steps" in argv, argv
    assert argv[argv.index("--max-steps") + 1] == "20"
    assert "--mode" not in argv, argv


def test_explore_falls_back_to_legacy_defaults_without_native_mode_support(tmp_path) -> None:
    """Honest limit (t4 point 5): a stale installed `colleague` that predates
    `--mode` must not break the wrapper. explore falls back to the OLD
    caller-side `--max-steps 30` default + `COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3`
    export, and never passes `--mode` (which the stale CLI would reject)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    env_log = tmp_path / "env.txt"
    fake = bindir / "colleague"
    fake.write_text(_mode_aware_fake_colleague(argv_log, env_log, mode_in_help=False))
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("COLLEAGUE_SYNTHESIS_RESERVE_STEPS", None)
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate something", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert "--mode" not in argv, argv
    assert "--max-steps" in argv, argv
    assert argv[argv.index("--max-steps") + 1] == "30"
    env_text = env_log.read_text()
    assert "COLLEAGUE_SYNTHESIS_RESERVE_STEPS=3" in env_text


def test_explore_partial_warning_has_rerun_hint(tmp_path) -> None:
    """#194: a not-finished explore drive prints an ACTIONABLE re-run hint naming the
    reached step count and a concrete larger --max-steps (2x the explore default 30)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "colleague"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "incomplete", "not_finished": true, '
        '"summary": "a partial map", "task_id": "deadbeef", '
        '"stats": {"step_count": 41, "model_turns": 30}}\'\n'
    )
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "map the repo", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    # explore default budget is 30; the hint must name the reached count AND 2x=60.
    assert "30" in r.stderr, r.stderr
    assert "--max-steps 60" in r.stderr, r.stderr


def test_no_result_summary_warns_and_skips_grade_footer(tmp_path) -> None:
    """#192: a drive whose summary is the NO_RESULT sentinel prints a clear
    no-result warning and NO success-shaped grade footer."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "colleague"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "incomplete", "not_finished": true, '
        '"summary": "__COLLEAGUE_NO_RESULT_PRODUCED__", "task_id": "deadbeef", '
        '"stats": {"step_count": 30, "model_turns": 30}}\'\n'
    )
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "map the repo", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert "no result produced" in r.stderr.lower(), r.stderr
    # The success-shaped grade footer must NOT appear for a no-result run.
    assert "grade:" not in (r.stderr + r.stdout), (r.stdout, r.stderr)


def test_readonly_preserves_artifact_to_real_repo(tmp_path) -> None:
    """C4 + #132: explore/review drive in a throwaway worktree, but the artifact is
    copied back to the REAL repo before the worktree is removed — so the drive can
    still be graded afterwards by its task-id (it otherwise vanished with the
    worktree). A read-only probe must NOT move the `last` pointer (#132): no
    `last_drive` is written, and the digest names the task-id + a `grade:` hint so
    the caller grades the explicit drive, never a fragile `last`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "colleague"
    # A stub that behaves like a real drive: it writes its artifact under the
    # --repo's .colleague/ (the worktree), then echoes the TaskResult JSON.
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'repo=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        '    --repo) repo="$2"; shift 2;;\n'
        "    *) shift;;\n"
        "  esac\n"
        "done\n"
        'mkdir -p "$repo/.colleague"\n'
        'art="$repo/.colleague/tid123.json"\n'
        "printf "
        '\'{"status":"ok","summary":"READONLY_OK","task_id":"tid123",'
        '"changed_files":[],"artifacts_path":"%s"}\' '
        '"$art" > "$art"\n'
        'printf \'{"index":0,"tool":"finish","ok":true}\\n\' '
        '> "$repo/.colleague/tid123.trace.jsonl"\n'
        'cat "$art"\n'
    )
    fake.chmod(0o755)

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

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    # Artifact preserved in the REAL repo (not lost with the worktree), copied by
    # the basename the drive reported in artifacts_path — robust to bare or slugged
    # names.
    art = repo / ".colleague" / "tid123.json"
    assert art.exists(), f"artifact not preserved\nstdout={r.stdout}\nstderr={r.stderr}"
    # #132: a read-only probe must NOT move `last` — no pointer is written.
    assert not (repo / ".colleague" / "last_drive").exists()
    # The reported artifact path points at the real repo, not the temp worktree.
    assert str(art) in r.stdout
    # The digest echoes the task-id and a copy-paste grade hint (graded by id).
    assert "task: tid123" in r.stdout
    assert "grade: ask-colleague feedback tid123 --rating" in r.stdout


def test_grade_hint_shown_on_failed_but_gradable_drive(tmp_path) -> None:
    """#139 (qodo): a FAILED drive still writes an artifact (h5) and is gradable —
    a failure rated 1/5 is the ROI signal — so the `grade:` hint must print even
    when status != ok. The failure digest (and the hint) go to stderr."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "colleague"
    # A stub that fails (status=error, exit 1) but still writes its artifact.
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'repo=""\n'
        'while [ "$#" -gt 0 ]; do case "$1" in --repo) repo="$2"; shift 2;; *) shift;; esac; done\n'
        'mkdir -p "$repo/.colleague"\n'
        'art="$repo/.colleague/failtid.json"\n'
        "printf "
        '\'{"status":"error","summary":"FAILED","task_id":"failtid",'
        '"changed_files":[],"artifacts_path":"%s","error":"boom"}\' '
        '"$art" > "$art"\n'
        'cat "$art"\n'
        "exit 1\n"
    )
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode != 0  # the drive failed, so the verb fails
    # The artifact was preserved (gradable), and the grade hint is emitted to the
    # failure digest on stderr — not suppressed because status != ok.
    assert (repo / ".colleague" / "failtid.json").exists()
    assert "grade: ask-colleague feedback failtid --rating" in r.stderr


def test_readonly_rejects_unsafe_artifact_path(tmp_path) -> None:
    """C4 hardening (qodo #1) + #132: a malicious/buggy TaskResult whose
    artifacts_path is a traversal attempt must not let _preserve_artifact write
    outside $REPO/.colleague/. The copy keys off os.path.basename(artifacts_path),
    so any directory component (``../..``) is stripped before the join — the write
    can only ever land inside .colleague/. The drive still succeeds (preservation
    is best-effort) and no last_drive is written (read-only probe)."""
    # Echoes a TaskResult whose artifacts_path tries to escape via ``../``. (No
    # artifact file is written, so preservation finds nothing to copy and is a
    # no-op — the point is that the traversal never reaches outside .colleague/.)
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf "
        '\'{"status":"ok","summary":"OK","task_id":"tid123",'
        '"changed_files":[],"artifacts_path":"../../pwned.json"}\'\n',
    )
    repo = _init_repo(tmp_path / "repo")

    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    # The drive itself succeeded; preservation is best-effort, so the verb is ok.
    assert r.returncode == 0, r.stderr
    # Nothing escaped above .colleague/, and no pointer was left behind.
    assert not (repo / "pwned.json").exists()
    assert not (repo.parent / "pwned.json").exists()
    assert not (repo / ".colleague" / "last_drive").exists()


def test_readonly_does_not_claim_path_when_preservation_fails(tmp_path) -> None:
    """C4 hardening (qodo #3): if the worktree artifact is missing, the copy can't
    happen — run_readonly must NOT rewrite the printed `artifact:` to the real repo
    (no false path) and must not write last_drive."""
    # Reports a safe task_id and an artifacts_path, but never writes the file —
    # mimicking a drive whose artifact didn't materialize in the worktree.
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf "
        '\'{"status":"ok","summary":"OK","task_id":"tid404",'
        '"changed_files":[],"artifacts_path":"/tmp/wt/.colleague/tid404.json"}\'\n',
    )
    repo = _init_repo(tmp_path / "repo")

    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    # No real-repo artifact was created, so no false claim and no dangling pointer.
    assert not (repo / ".colleague" / "tid404.json").exists()
    assert not (repo / ".colleague" / "last_drive").exists()
    # The printed path is NOT rewritten to the (non-existent) real-repo location.
    assert str(repo / ".colleague" / "tid404.json") not in r.stdout
    # #180 finding-2: with preservation failed (not gradable) NO `artifact:` line is
    # printed at all — the raw artifacts_path points into the soon-deleted worktree.
    assert "artifact:" not in r.stdout


# ── issue #61: downstream qodo findings ─────────────────────────────────────


def test_render_preserves_literal_base_in_argument() -> None:
    """A literal `$BASE` inside the user's argument must survive (#6): single-pass
    substitution must not re-scan injected text. The old two-pass `.replace`
    clobbered it to the base value."""
    out = _render("explore", "describe the $BASE token literally", "main")
    assert "$BASE token literally" in out
    assert "main token literally" not in out


def test_literal_base_in_argument_survives_through_the_script(tmp_path) -> None:
    """Script-level guard for #6: stub `colleague` echoes the rendered drive
    instruction back as its summary, so we can assert a literal `$BASE` in the
    argument reaches the model verbatim instead of being rewritten to `main`."""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        'python3 -c "import json,sys; '
        "print(json.dumps({'status':'ok','summary':sys.argv[1],'changed_files':[]}))\" \"$2\"\n",
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "explore",
            "explain the $BASE placeholder literally",
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "$BASE placeholder literally" in r.stdout
    assert "main placeholder literally" not in r.stdout


def test_failure_digest_goes_to_stderr(tmp_path) -> None:
    """On a failed drive (status != ok) the digest must go to stderr (#4) so stdout
    stays clean for scripting; the wrapper still exits non-zero.

    The stub models real `colleague drive` faithfully (qodo #62): it prints the
    error JSON to stdout *and exits 1*. The apply path's `|| true` must keep that
    non-zero exit from aborting the script under `set -e` before print_result runs."""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "error", "summary": "BOOM_FAILED"}\'\n'
        "exit 1\n",
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "BOOM_FAILED" in r.stderr
    assert "BOOM_FAILED" not in r.stdout
    assert r.stdout.strip() == "", "stdout must stay clean on failure"


def test_review_rejects_bogus_base(tmp_path) -> None:
    """review interpolates --base into the LLM instruction, so a value that is not a
    real commit/ref must be rejected up front (#5) — before the CLI is invoked."""
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "review", "focus", "--repo", str(repo), "--base", "no-such-ref-xyz"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1  # #161: a bad --base value is a user-input error
    assert "not a valid commit/ref" in r.stderr


def test_non_git_repo_is_rejected_for_every_verb(tmp_path) -> None:
    """The git-repo guard (#2) now covers every verb, including write — a plain
    directory is rejected with a clear message, not an opaque mid-drive error."""
    plain = tmp_path / "plain"
    plain.mkdir()
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(plain), "--apply"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1  # #161: a bad --repo path is a user-input error
    assert "not a git repository" in r.stderr


def test_help_lists_the_clean_verb() -> None:
    """#162: `clean` (crashed-run recovery) must be discoverable in --help."""
    r = _run("--help")
    assert r.returncode == 0
    assert "clean" in r.stdout
    assert "--dry-run" in r.stdout


def test_clean_verb_shells_to_colleague_clean(tmp_path) -> None:
    """#162: `ask-colleague clean` → `colleague clean --repo <repo>` (pass-through).
    A stub colleague records its argv so we assert the mapping without a model."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n')
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    argv = argv_log.read_text().splitlines()
    assert argv[0] == "clean"
    assert "--repo" in argv
    assert "--dry-run" not in argv  # not requested


def test_clean_verb_passes_dry_run(tmp_path) -> None:
    """#162: `ask-colleague clean --dry-run` forwards --dry-run to colleague clean."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n')
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "--repo", str(repo), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "--dry-run" in argv_log.read_text().splitlines()


def test_clean_rejects_positional_arg(tmp_path) -> None:
    """#162: clean takes no description argument — a stray positional is a
    user-input error (#161 exit 1), caught before the CLI is invoked."""
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "stray-arg", "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1
    assert "takes no description argument" in r.stderr


def test_write_previews_by_default(tmp_path) -> None:
    """write without --apply (#1) runs in a throwaway worktree, prints the would-be
    change + diff, and lands NOTHING in the real working tree; the worktree and the
    ephemeral drive branch are cleaned up afterwards."""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'repo=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--repo" ] && repo="$a"; prev="$a"; done\n'
        'git -C "$repo" checkout -q -b colleague/previewfeed\n'
        "printf 'hello\\n' > \"$repo/preview_added.txt\"\n"
        'git -C "$repo" add -A\n'
        'git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m "drive change"\n'
        "python3 -c \"import json; print(json.dumps({'status':'ok',"
        "'summary':'PREVIEW_RAN','changed_files':['preview_added.txt'],"
        "'branch':'colleague/previewfeed'}))\"\n",
    )
    repo = _init_repo(tmp_path / "repo")
    before = _worktree_count(repo)
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "add a file", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "PREVIEW_RAN" in r.stdout
    assert "preview diff (NOT applied" in r.stdout
    assert "preview_added.txt" in r.stdout
    # nothing landed in the real working tree …
    assert not (repo / "preview_added.txt").exists()
    # … and the worktree + ephemeral drive branch were cleaned up.
    assert _worktree_count(repo) == before, "preview leaked a worktree"
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "colleague/previewfeed"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branches == "", "preview leaked the ephemeral drive branch"


# ── issue #181: resolve_colleague() honors --repo for the uv local-dev fallback ──


def _minimal_path_without_colleague(bindir: Path) -> str | None:
    """A minimal PATH = bindir + the system tool dirs, but NO dir that resolves
    `colleague` — so resolve_colleague falls through to the `uv run` helper. Returns
    None (the caller skips) if a required tool isn't resolvable there, or a real
    colleague leaked in (which would defeat the fallback test)."""
    path = os.pathsep.join([str(bindir), "/usr/bin", "/bin"])
    for tool in ("bash", "git", "python3", "grep", "mktemp", "dirname"):
        if shutil.which(tool, path=path) is None:
            return None
    if shutil.which("colleague", path=path) is not None:
        return None
    return path


def test_resolve_via_uv_against_repo_when_colleague_off_path(tmp_path) -> None:
    """#181: with `colleague` NOT on PATH and $PWD outside any checkout, a colleague
    checkout sitting at --repo must still resolve — via `uv run --project <repo>
    colleague`. On the pre-fix wrapper (which walked only $PWD) this exited 2
    ('colleague CLI not found'). A fake `uv` records its argv so we assert the
    resolution without actually building an environment."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv_argv = tmp_path / "uv_argv.txt"
    uv = bindir / "uv"
    uv.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{uv_argv}"\nexit 0\n')
    uv.chmod(0o755)

    path = _minimal_path_without_colleague(bindir)
    if path is None:
        pytest.skip("core tools not resolvable on a colleague-free minimal PATH")

    # A --repo that looks like a colleague checkout (git repo + naming pyproject).
    checkout = _init_repo(tmp_path / "checkout")
    (checkout / "pyproject.toml").write_text('name = "colleague"\n')
    # $PWD is deliberately OUTSIDE any checkout, so only the --repo walk can resolve.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    env = {**os.environ, "PATH": path}
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "--repo", str(checkout)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(elsewhere),
        check=False,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "colleague CLI not found" not in r.stderr
    argv = uv_argv.read_text().splitlines()
    # Resolved as `uv run --project <checkout> colleague clean --repo <checkout>`.
    assert argv[:2] == ["run", "--project"]
    assert argv[2] == str(checkout)
    assert argv[3] == "colleague"
    assert "clean" in argv


def test_installed_colleague_on_path_never_reaches_uv(tmp_path) -> None:
    """#181: the on-PATH branch is unchanged — when `colleague` is installed the uv
    helper is never invoked (a fake `uv` sentinel stays unwritten)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    (bindir / "colleague").write_text(
        "#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n'
    )
    (bindir / "colleague").chmod(0o755)
    uv_sentinel = tmp_path / "uv_was_called.txt"
    (bindir / "uv").write_text("#!/usr/bin/env bash\n" f'touch "{uv_sentinel}"\n')
    (bindir / "uv").chmod(0o755)
    repo = _init_repo(tmp_path / "repo")

    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert argv_log.read_text().splitlines()[0] == "clean"  # the installed tool ran
    assert not uv_sentinel.exists(), "uv fallback reached even though colleague is on PATH"


# ── issue #180 finding-1: propagate colleague's tri-state drive exit code (0/1/2) ──


def test_drive_env_failure_propagates_exit_2(tmp_path) -> None:
    """#180 finding-1: a drive that exits 2 (environment/setup) while emitting a
    partial TaskResult JSON on stdout must propagate as exit 2 — not collapse to 1.
    Mirrors colleague's CliError(EXIT_ENV_ERROR, result=partial) path, which surfaces
    the partial to stdout in --json mode while exiting 2."""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n" 'echo \'{"status": "error", "summary": "ENV_BOOM"}\'\nexit 2\n',
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "ENV_BOOM" in r.stderr  # the failure digest still prints (to stderr)


def test_drive_user_error_propagates_exit_1(tmp_path) -> None:
    """#180 finding-1: a drive that exits 1 (user-input) propagates as 1 — the
    tri-state's other arm. (Success → 0 is covered by the happy-path tests.)"""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n" 'echo \'{"status": "error", "summary": "USER_BOOM"}\'\nexit 1\n',
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "USER_BOOM" in r.stderr


def test_drive_empty_stdout_still_exits_2(tmp_path) -> None:
    """#180 finding-1: a drive with NO stdout (an env failure before any result)
    keeps print_result's parse-level exit 2 — the rc threading must not regress it."""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n>&2 echo 'fatal: provider unreachable'\nexit 2\n",
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


# ── issue #180 finding-2: never print an `artifact:` path into a deleted worktree ──


def test_preview_does_not_print_dead_artifact_path(tmp_path) -> None:
    """#180 finding-2: a write PREVIEW drives in a throwaway worktree, so its
    artifacts_path names a dir deleted on exit. The wrapper must print NO `artifact:`
    line for a preview (nor a `grade:` hint — a preview is not gradable). The print
    is gated on the survives-flag (ASK_COLLEAGUE_GRADABLE)."""
    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'repo=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--repo" ] && repo="$a"; prev="$a"; done\n'
        'git -C "$repo" checkout -q -b colleague/prevart\n'
        "printf 'hi\\n' > \"$repo/added.txt\"\n"
        'git -C "$repo" add -A\n'
        'git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m "c"\n'
        "python3 -c \"import json; print(json.dumps({'status':'ok',"
        "'summary':'PREVIEW_ART','task_id':'previd','changed_files':['added.txt'],"
        "'branch':'colleague/prevart',"
        "'artifacts_path':'/throwaway/.colleague/previd.json'}))\"\n",
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "add a file", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "PREVIEW_ART" in r.stdout
    assert "artifact:" not in (r.stdout + r.stderr)
    assert "grade:" not in (r.stdout + r.stderr)


def test_preview_json_does_not_leak_dead_artifact_path(tmp_path) -> None:
    """#186 qodo finding-3: a write PREVIEW in --json mode must NOT serialize a
    dead `artifacts_path`. The drive runs in a throwaway worktree (deleted on
    exit), so the raw artifacts_path names a gone dir. The json_mode branch gates
    on the same survives-flag (ASK_COLLEAGUE_GRADABLE) as the human digest, so a
    machine consumer never receives a path into the cleaned-up worktree."""
    import json

    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'repo=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--repo" ] && repo="$a"; prev="$a"; done\n'
        'git -C "$repo" checkout -q -b colleague/prevartjson\n'
        "printf 'hi\\n' > \"$repo/added.txt\"\n"
        'git -C "$repo" add -A\n'
        'git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m "c"\n'
        "python3 -c \"import json; print(json.dumps({'status':'ok',"
        "'summary':'PREVIEW_ART_JSON','task_id':'previd','changed_files':['added.txt'],"
        "'branch':'colleague/prevartjson',"
        "'artifacts_path':'/throwaway/.colleague/previd.json'}))\"\n",
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "add a file", "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    # The summary still carries through, but the stale worktree path is gone.
    assert payload["summary"] == "PREVIEW_ART_JSON"
    assert "artifacts_path" not in payload
    assert "/throwaway/" not in r.stdout
    # A preview is not gradable -> no grade hint on any stream.
    assert "grade:" not in (r.stdout + r.stderr)


# ── --json flag (qodo rule 824501): stdout reserved for JSON, diagnostics to stderr ──


def test_help_lists_the_json_flag() -> None:
    """The --json option must be discoverable in the usage text."""
    r = _run("--help")
    assert r.returncode == 0
    assert "--json" in r.stdout


def test_json_flag_emits_pure_json_on_stdout(tmp_path) -> None:
    """`--json` makes stdout carry ONLY the TaskResult JSON (no human digest); the
    drive verbs already get JSON from `colleague drive --json`, so the wrapper
    passes it through and routes the digest/diagnostics to stderr."""
    import json

    env = _fake_colleague(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "ok", "task_id": "t-1", "summary": "JSON_OK", '
        '"changed_files": ["a.py"], "branch": "colleague/t-1"}\'\n',
    )
    repo = _init_repo(tmp_path / "repo")
    r = subprocess.run(
        ["bash", str(SCRIPT), "write", "do a thing", "--repo", str(repo), "--apply", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    # stdout is exactly one JSON object — parseable, with the drive's fields.
    payload = json.loads(r.stdout)
    assert payload["status"] == "ok"
    assert payload["task_id"] == "t-1"
    # The human digest must NOT leak onto stdout in --json mode.
    assert "status:" not in r.stdout
    assert "grade:" not in r.stdout
    # #186 qodo finding-2: a gradable drive still emits the task:/grade: hints,
    # but on STDERR so stdout stays pure JSON (the convention every work item
    # follows; the task_id is in the payload too).
    assert "grade: ask-colleague feedback t-1" in r.stderr
    assert "task: t-1" in r.stderr


def test_feedback_forwards_json_flag(tmp_path) -> None:
    """feedback is a pass-through; `--json` must be forwarded to `colleague feedback`
    (which supports it natively) so stdout stays machine-readable end-to-end."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n')
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "feedback", "list", "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "--json" in argv_log.read_text().splitlines()


def test_clean_forwards_json_flag(tmp_path) -> None:
    """clean forwards `--json` to `colleague clean` (native support)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "colleague"
    fake.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{argv_log}"\n')
    fake.chmod(0o755)
    repo = _init_repo(tmp_path / "repo")
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "--json" in argv_log.read_text().splitlines()


# ── per-verb tool requirements (qodo bug): don't demand python3/mktemp for ──────
# ── feedback/clean, which never use them. ───────────────────────────────────────


def _minimal_bin(bindir: Path, *, include: tuple[str, ...], colleague_body: str) -> dict[str, str]:
    """A PATH containing only `include` tools (symlinked) + a fake colleague.
    Used to prove a verb runs WITHOUT python3/mktemp/grep on PATH."""
    bindir.mkdir(parents=True, exist_ok=True)
    for tool in include:
        src = shutil.which(tool)
        if src:
            (bindir / tool).symlink_to(src)
    fake = bindir / "colleague"
    fake.write_text(colleague_body)
    fake.chmod(0o755)
    # Replace PATH entirely (no fall-through to the real one) so python3/mktemp are
    # genuinely absent; keep a clean env otherwise.
    return {"PATH": str(bindir), "HOME": os.environ.get("HOME", "")}


# Tools feedback/clean legitimately need pre-dispatch (git work-tree guard +
# coreutils used while resolving paths) — deliberately excludes python3/mktemp/grep.
_FEEDBACK_TOOLS = ("bash", "git", "dirname", "mkdir", "rm", "cat", "env", "tr", "head", "printf")


def test_feedback_runs_without_python3_or_mktemp(tmp_path) -> None:
    """qodo bug: the old blanket require_tools demanded python3/git/grep/mktemp for
    EVERY verb, so feedback/clean failed exit-2 in minimal envs even though they
    never use python3/mktemp. feedback must now succeed with only git on PATH."""
    repo = _init_repo(tmp_path / "repo")
    env = _minimal_bin(
        tmp_path / "bin",
        include=_FEEDBACK_TOOLS,
        colleague_body="#!/usr/bin/env bash\necho feedback-ok\n",
    )
    # sanity: python3/mktemp really are absent from this PATH
    assert shutil.which("python3", path=env["PATH"]) is None
    assert shutil.which("mktemp", path=env["PATH"]) is None
    r = subprocess.run(
        ["bash", str(SCRIPT), "feedback", "last", "--rating", "4", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_drive_verb_still_requires_python3_and_mktemp(tmp_path) -> None:
    """The drive verbs DO render a prompt + parse JSON (python3) and isolate in a
    worktree (mktemp), so explore must still fail fast (exit 2) when they're absent,
    naming the missing tools."""
    repo = _init_repo(tmp_path / "repo")
    env = _minimal_bin(
        tmp_path / "bin",
        include=_FEEDBACK_TOOLS,
        colleague_body="#!/usr/bin/env bash\necho should-not-reach\n",
    )
    r = subprocess.run(
        ["bash", str(SCRIPT), "explore", "investigate x", "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "missing required tool" in r.stderr
    assert "python3" in r.stderr and "mktemp" in r.stderr


# ── issue #190: remove the last grep dependency (grep-free wrapper) ────


def test_script_contains_no_grep_invocation() -> None:
    """#190: the script must not contain any `grep` token — the pure-bash
    _pyproject_is_colleague helper replaced the last grep call."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "grep" not in src, "ask-colleague.sh must be grep-free"


def test_resolve_via_uv_without_grep_on_path(tmp_path) -> None:
    """#190: with `colleague` AND `grep` off PATH, the uv-fallback resolver must
    still find a colleague checkout via pure-bash pyproject matching. On the
    pre-fix wrapper (which used `grep -q`) this silently failed and printed
    'colleague CLI not found' even inside a real checkout."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv_argv = tmp_path / "uv_argv.txt"
    uv = bindir / "uv"
    uv.write_text("#!/usr/bin/env bash\n" f'printf "%s\\n" "$@" > "{uv_argv}"\nexit 0\n')
    uv.chmod(0o755)

    # Build a PATH with everything except colleague and grep.
    # We use _minimal_bin-style: only the tools we explicitly include.
    needed = (
        "bash",
        "git",
        "python3",
        "mktemp",
        "dirname",
        "mkdir",
        "rm",
        "cat",
        "env",
        "tr",
        "head",
        "printf",
    )
    for tool in needed:
        src = shutil.which(tool)
        if src:
            (bindir / tool).symlink_to(src)
    # Ensure grep is NOT on this PATH.
    assert shutil.which("grep", path=str(bindir)) is None, "test setup: grep must be absent"
    assert (
        shutil.which("colleague", path=str(bindir)) is None
    ), "test setup: colleague must be absent"

    # A --repo that looks like a colleague checkout (git repo + naming pyproject).
    checkout = _init_repo(tmp_path / "checkout")
    (checkout / "pyproject.toml").write_text('name = "colleague"\n')
    # $PWD is deliberately OUTSIDE any checkout, so only the --repo walk can resolve.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    env = {**os.environ, "PATH": str(bindir)}
    r = subprocess.run(
        ["bash", str(SCRIPT), "clean", "--repo", str(checkout)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(elsewhere),
        check=False,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "colleague CLI not found" not in r.stderr
    argv = uv_argv.read_text().splitlines()
    # Resolved as `uv run --project <checkout> colleague clean --repo <checkout>`.
    assert argv[:2] == ["run", "--project"]
    assert argv[2] == str(checkout)
    assert argv[3] == "colleague"
    assert "clean" in argv

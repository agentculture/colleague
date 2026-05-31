"""Offline guards for the `outsource` skill (no live model).

These exercise the parts of the skill that do NOT invoke a drive: the prompt
templates render, the wrapper resolves verbs/flags, and the error paths exit
before `resolve_convertible` is ever reached. The live 27B behavior is proven by
dogfooding, not in CI.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "outsource"
SCRIPT = SKILL / "scripts" / "outsource.sh"
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


def _fake_convertible(bindir: Path, body: str) -> dict[str, str]:
    """Drop a stub `convertible` on a fresh PATH and return the env to run with."""
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "convertible"
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
    assert os.access(SCRIPT, os.X_OK), "outsource.sh must be executable"
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


def test_review_prompt_uses_the_base_diff() -> None:
    out = _render("review", "x", "develop")
    assert "develop...HEAD" in out
    assert "$BASE" not in out


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
    assert "mmangkad/Qwen3.6-27B-NVFP4" in r.stdout


def test_help_documents_preview_by_default_and_apply() -> None:
    """write previews by default (#1); the --apply opt-in must be discoverable."""
    r = _run("--help")
    assert r.returncode == 0
    assert "--apply" in r.stdout
    assert "preview by default" in r.stdout


def test_unknown_verb_errors_with_hint() -> None:
    r = _run("frobnicate", "x")
    assert r.returncode == 2
    assert "unknown verb" in r.stderr


def test_no_args_errors() -> None:
    r = _run()
    assert r.returncode == 2


def test_missing_description_errors() -> None:
    r = _run("explore")
    assert r.returncode == 2
    assert "needs a description" in r.stderr


def test_trailing_value_flag_errors_cleanly() -> None:
    """A value-flag with no following value must exit 2 with a clear message,
    not crash on an unbound $2 under `set -u` (qodo finding)."""
    r = _run("explore", "investigate x", "--repo")
    assert r.returncode == 2
    assert "requires a value" in r.stderr
    assert "unbound variable" not in r.stderr


def test_wrapper_prints_drive_summary_with_a_fake_convertible(tmp_path) -> None:
    """End-to-end wrapper path (resolve -> render -> drive -> print_result) with a
    stubbed `convertible` that echoes a canned TaskResult. Guards the result
    extraction (in particular: print_result must read the piped JSON from stdin,
    not have it shadowed by a heredoc). Uses --apply to exercise the in-place
    write path now that `write` previews by default."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "convertible"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'{"status": "ok", "summary": "FAKE_SUMMARY_OK", '
        '"changed_files": ["x.py"], "branch": "convertible/abc123"}\'\n'
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
    assert "convertible/abc123" in r.stdout


def test_feedback_verb_shells_to_convertible_feedback(tmp_path) -> None:
    """`outsource feedback <ref> --rating N` must invoke `convertible feedback
    record <ref> --rating N --repo <repo>` (the ROI loop pass-through, t9). A
    stub convertible records its argv so we can assert the mapping without a model."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "convertible"
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
    """No --rating → `convertible feedback show <ref>` (read, not record)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv.txt"
    fake = bindir / "convertible"
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


def test_readonly_verb_isolates_in_a_worktree_and_cleans_up(tmp_path) -> None:
    """explore/review (run_readonly) must run in a throwaway worktree and remove
    it afterwards. Stub `convertible`, run `outsource explore`, and assert the
    summary comes back AND the worktree count is unchanged (no leak). Covers the
    run_readonly path a 27B dogfood-review flagged as untested."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "convertible"
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


# ── issue #61: downstream qodo findings ─────────────────────────────────────


def test_render_preserves_literal_base_in_argument() -> None:
    """A literal `$BASE` inside the user's argument must survive (#6): single-pass
    substitution must not re-scan injected text. The old two-pass `.replace`
    clobbered it to the base value."""
    out = _render("explore", "describe the $BASE token literally", "main")
    assert "$BASE token literally" in out
    assert "main token literally" not in out


def test_literal_base_in_argument_survives_through_the_script(tmp_path) -> None:
    """Script-level guard for #6: stub `convertible` echoes the rendered drive
    instruction back as its summary, so we can assert a literal `$BASE` in the
    argument reaches the model verbatim instead of being rewritten to `main`."""
    env = _fake_convertible(
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

    The stub models real `convertible drive` faithfully (qodo #62): it prints the
    error JSON to stdout *and exits 1*. The apply path's `|| true` must keep that
    non-zero exit from aborting the script under `set -e` before print_result runs."""
    env = _fake_convertible(
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
    assert r.returncode == 2
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
    assert r.returncode == 2
    assert "not a git repository" in r.stderr


def test_write_previews_by_default(tmp_path) -> None:
    """write without --apply (#1) runs in a throwaway worktree, prints the would-be
    change + diff, and lands NOTHING in the real working tree; the worktree and the
    ephemeral drive branch are cleaned up afterwards."""
    env = _fake_convertible(
        tmp_path / "bin",
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'repo=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--repo" ] && repo="$a"; prev="$a"; done\n'
        'git -C "$repo" checkout -q -b convertible/previewfeed\n'
        "printf 'hello\\n' > \"$repo/preview_added.txt\"\n"
        'git -C "$repo" add -A\n'
        'git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m "drive change"\n'
        "python3 -c \"import json; print(json.dumps({'status':'ok',"
        "'summary':'PREVIEW_RAN','changed_files':['preview_added.txt'],"
        "'branch':'convertible/previewfeed'}))\"\n",
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
        ["git", "-C", str(repo), "branch", "--list", "convertible/previewfeed"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branches == "", "preview leaked the ephemeral drive branch"

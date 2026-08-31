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

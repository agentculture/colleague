"""Tests for the background one-shot detach primitive (plan task t12).

Covers, mirroring the plan's acceptance criteria:

1. ``colleague work --background`` returns immediately; the child completes the
   work item end-to-end (``--engine mock``) producing the artifact + gradable
   feedback with no attached terminal.
2. A ``kill -9``'d child leaves partial residue (``.colleague/background/<id>/``)
   that ``colleague clean`` reaps, while a genuinely still-running background
   run is never touched — the repo is never wedged.
3. No daemon/socket: the detach primitive is confined to
   :mod:`colleague.background` (pinned separately in ``tests/test_boundary.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from colleague import artifact, background
from colleague.cli import main
from colleague.cli._commands import work as work_mod
from colleague.cli._commands.work import _background_child_argv


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _reap_child(pid: int, timeout: float = 30) -> None:
    """Wait out a spawned child so it never lingers as a zombie under pytest.

    In real usage the parent CLI process exits right after printing the start
    payload, so the kernel reparents any leftover zombie to init and it is
    reaped automatically. The test process stays alive across assertions, so
    this reaps explicitly for an accurate liveness check afterward.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            done_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if done_pid == pid:
            return
        time.sleep(0.05)
    pytest.fail(f"child pid {pid} did not exit within {timeout}s")


def _wait_for_artifact(repo: Path, task_id: str, timeout: float = 30) -> tuple[Path, dict]:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        path = artifact.find_artifact(repo, task_id)
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            if data is not None and data.get("status") in ("ok", "error", "incomplete"):
                return path, data
            last = data
        time.sleep(0.1)
    raise AssertionError(f"artifact for {task_id} incomplete after {timeout}s (last={last})")


# --- unit: the detach primitive itself --------------------------------------


def test_spawn_background_returns_immediately_with_handle(tmp_path):
    repo = _init_repo(tmp_path)
    handle = background.spawn_background(
        repo, [sys.executable, "-c", "import time; time.sleep(0.2)"]
    )
    try:
        assert handle.pid != os.getpid()
        assert handle.log_dir == f".colleague/background/{handle.id}/"
        assert handle.flight == handle.id
        ldir = background.log_dir(repo, handle.id)
        assert ldir.is_dir()
        meta = json.loads((ldir / "meta.json").read_text())
        assert meta["pid"] == handle.pid
        assert meta["flight"] == handle.id
        assert meta["id"] == handle.id
    finally:
        _reap_child(handle.pid)


def test_spawn_background_honors_explicit_handle_and_flight_ids(tmp_path):
    repo = _init_repo(tmp_path)
    handle = background.spawn_background(
        repo,
        [sys.executable, "-c", "pass"],
        handle_id="fixed-handle",
        flight_id="fixed-flight",
    )
    try:
        assert handle.id == "fixed-handle"
        assert handle.flight == "fixed-flight"
        assert handle.log_dir == ".colleague/background/fixed-handle/"
    finally:
        _reap_child(handle.pid)


def test_spawn_background_sets_env_var_for_child(tmp_path):
    repo = _init_repo(tmp_path)
    marker = repo / "env-seen.txt"
    snippet = (
        "import os; "
        f"open({str(marker)!r}, 'w').write(os.environ.get({background.BACKGROUND_ID_ENV!r}, ''))"
    )
    handle = background.spawn_background(
        repo,
        [sys.executable, "-c", snippet],
        handle_id="env-check",
    )
    try:
        _reap_child(handle.pid)
        assert marker.read_text() == "env-check"
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


def test_stdio_is_redirected_to_log_files_not_inherited(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    handle = background.spawn_background(
        repo,
        [
            sys.executable,
            "-c",
            "print('child stdout line'); import sys; print('child stderr line', file=sys.stderr)",
        ],
        handle_id="io-check",
    )
    try:
        _reap_child(handle.pid)
        ldir = background.log_dir(repo, "io-check")
        assert "child stdout line" in (ldir / "stdout.log").read_text()
        assert "child stderr line" in (ldir / "stderr.log").read_text()
        # Nothing leaked into the calling test's own captured streams.
        captured = capsys.readouterr()
        assert "child stdout line" not in captured.out
        assert "child stderr line" not in captured.err
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


def test_new_handle_id_is_short_and_unique():
    a = background.new_handle_id()
    b = background.new_handle_id()
    assert a != b
    assert len(a) == 12
    assert all(c in "0123456789abcdef" for c in a)


def test_relative_log_dir_format():
    assert background.relative_log_dir("abc123") == ".colleague/background/abc123/"


def test_list_background_ids(tmp_path):
    repo = _init_repo(tmp_path)
    assert background.list_background_ids(repo) == []
    background.log_dir(repo, "a1").mkdir(parents=True)
    background.log_dir(repo, "b2").mkdir(parents=True)
    assert background.list_background_ids(repo) == ["a1", "b2"]


# --- unit: pid liveness -------------------------------------------------


def test_pid_alive_true_for_self():
    assert background._pid_alive(os.getpid()) is True


def test_pid_alive_false_for_a_reaped_dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert background._pid_alive(proc.pid) is False


@pytest.mark.parametrize("bad", [None, "123", -5, 0, 3.5, True])
def test_pid_alive_false_for_non_positive_int_values(bad):
    assert background._pid_alive(bad) is False


# --- unit: reap_background ------------------------------------------------


def test_reap_background_missing_root_is_noop(tmp_path):
    repo = _init_repo(tmp_path)
    assert background.reap_background(repo) == []


def test_reap_background_reaps_dead_keeps_live(tmp_path):
    repo = _init_repo(tmp_path)

    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    dead_dir = background.log_dir(repo, "dead1")
    dead_dir.mkdir(parents=True)
    (dead_dir / "meta.json").write_text(
        json.dumps({"id": "dead1", "pid": dead_proc.pid, "flight": "dead1"})
    )
    (dead_dir / "stdout.log").write_text("some output\n")

    live_dir = background.log_dir(repo, "live1")
    live_dir.mkdir(parents=True)
    (live_dir / "meta.json").write_text(
        json.dumps({"id": "live1", "pid": os.getpid(), "flight": "live1"})
    )

    results = background.reap_background(repo)
    by_id = {r["background"]: r["action"] for r in results}
    assert by_id["dead1"] == "reaped"
    assert "live1" not in by_id  # a live holder is never even reported, let alone reaped
    assert not dead_dir.exists()
    assert live_dir.exists()


def test_reap_background_dry_run_changes_nothing(tmp_path):
    repo = _init_repo(tmp_path)
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    d = background.log_dir(repo, "dead2")
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"pid": dead_proc.pid}))

    results = background.reap_background(repo, dry_run=True)
    assert results == [{"background": "dead2", "action": "would-reap"}]
    assert d.exists()


def test_reap_background_corrupt_meta_is_kept(tmp_path):
    """No liveness signal (missing/corrupt meta.json) -> NEVER delete (PR #267).

    A child that crashed before its meta.json landed may still be alive behind
    the unreadable metadata; treating "unknown" as "dead" would let `colleague
    clean` remove logs for a genuinely running child. Reported honestly as
    kept-unknown instead — operator judgment removes it manually.
    """
    repo = _init_repo(tmp_path)
    d = background.log_dir(repo, "corrupt1")
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{not json")

    results = background.reap_background(repo)
    assert results == [{"background": "corrupt1", "action": "kept-unknown"}]
    assert d.exists()


def test_reap_background_never_touches_a_live_run(tmp_path):
    repo = _init_repo(tmp_path)
    handle = background.spawn_background(
        repo, [sys.executable, "-c", "import time; time.sleep(30)"], handle_id="alive1"
    )
    try:
        assert background._pid_alive(handle.pid) is True
        assert background.reap_background(repo, dry_run=True) == []
        assert background.reap_background(repo) == []
        assert background.log_dir(repo, "alive1").is_dir()
    finally:
        with suppress(ProcessLookupError):
            os.kill(handle.pid, signal.SIGKILL)
        _reap_child(handle.pid)


# --- kill -9 mid-run: residue survives, is reapable, repo never wedged -----


def test_kill_mid_run_leaves_reapable_residue_and_repo_never_wedged(tmp_path):
    repo = _init_repo(tmp_path)
    handle = background.spawn_background(
        repo,
        [sys.executable, "-c", "import time; time.sleep(30)"],
        handle_id="killme1",
    )
    try:
        assert background._pid_alive(handle.pid) is True
        assert background.reap_background(repo) == []  # still running -> nothing dead yet

        os.kill(handle.pid, signal.SIGKILL)
        _reap_child(handle.pid)  # reap the OS zombie so the liveness probe reads correctly
        assert background._pid_alive(handle.pid) is False

        ldir = background.log_dir(repo, "killme1")
        assert ldir.is_dir()  # partial residue survives the kill

        results = background.reap_background(repo)
        assert {"background": "killme1", "action": "reaped"} in results
        assert not ldir.exists()

        # The repo itself was never touched by any of this.
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True
        )
        assert status.returncode == 0
    finally:
        with suppress(ProcessLookupError):
            os.kill(handle.pid, signal.SIGKILL)
        with suppress(Exception):
            _reap_child(handle.pid, timeout=2)


def test_clean_cli_reaps_dead_background_and_keeps_live(tmp_path, capsys):
    repo = _init_repo(tmp_path)

    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    dead_dir = background.log_dir(repo, "cli-dead")
    dead_dir.mkdir(parents=True)
    (dead_dir / "meta.json").write_text(
        json.dumps({"id": "cli-dead", "pid": dead_proc.pid, "flight": "cli-dead"})
    )

    live_handle = background.spawn_background(
        repo, [sys.executable, "-c", "import time; time.sleep(30)"], handle_id="cli-live"
    )
    try:
        rc = main(["clean", "--repo", str(repo), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        by_id = {b["background"]: b["action"] for b in report["background"]}
        assert by_id["cli-dead"] == "reaped"
        assert "cli-live" not in by_id
        assert not dead_dir.exists()
        assert background.log_dir(repo, "cli-live").is_dir()

        # The repo is never wedged: git operations still work fine afterward.
        status = subprocess.run(["git", "status"], cwd=str(repo), capture_output=True, text=True)
        assert status.returncode == 0
    finally:
        with suppress(ProcessLookupError):
            os.kill(live_handle.pid, signal.SIGKILL)
        _reap_child(live_handle.pid)


def test_clean_cli_text_render_reports_background_runs(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    d = background.log_dir(repo, "text-dead")
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": "text-dead", "pid": dead_proc.pid}))

    rc = main(["clean", "--repo", str(repo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "background runs (reaped):" in out
    assert "text-dead" in out


# --- _background_child_argv: the reinvocation the parent builds ------------


def _full_namespace(**overrides) -> argparse.Namespace:
    base = dict(
        instruction=["do", "the", "thing"],
        command_name=None,
        repo=".",
        engine="mock",
        no_pr=True,
        allow_dirty=False,
        no_lint=False,
        no_affected_tests=False,
        test=None,
        base="main",
        base_url=None,
        model=None,
        role=None,
        api_key=None,
        max_steps=5,
        mode=None,
        tui=None,
        tui_events=None,
        json=True,
        watch=False,
        background=True,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_background_child_argv_drops_flag_and_forces_watch(tmp_path):
    repo = _init_repo(tmp_path)
    ns = _full_namespace()
    argv = _background_child_argv(ns, repo)

    assert argv[0] == "work"
    assert "--background" not in argv
    assert argv.count("--watch") == 1
    assert "do" in argv and "the" in argv and "thing" in argv


def test_background_child_argv_resolves_repo_to_absolute_path(tmp_path):
    repo = _init_repo(tmp_path)
    ns = _full_namespace(repo=".")  # a caller-relative path the child must not inherit
    argv = _background_child_argv(ns, repo)
    assert "--repo" in argv
    assert argv[argv.index("--repo") + 1] == str(repo)


def test_background_child_argv_forwards_json_and_engine(tmp_path):
    repo = _init_repo(tmp_path)
    ns = _full_namespace(json=True, engine="mock")
    argv = _background_child_argv(ns, repo)
    assert "--json" in argv
    assert "--engine" in argv and argv[argv.index("--engine") + 1] == "mock"


def test_background_child_argv_uses_command_template_form(tmp_path):
    repo = _init_repo(tmp_path)
    ns = _full_namespace(instruction=["arg1"], command_name="my-template")
    argv = _background_child_argv(ns, repo)
    assert "--command" in argv
    assert argv[argv.index("--command") + 1] == "my-template"
    assert "arg1" in argv


def test_background_child_argv_forwards_attach_as_absolute_path(tmp_path):
    """--attach must not be silently dropped for the detached background child.

    The child may run with a different cwd, and media.validate_attachment()
    resolves a relative path against cwd -- so the parent resolves each
    --attach value to an absolute path before handing it to the child (Qodo
    regression: --attach used to be omitted from the child argv entirely).
    """
    repo = _init_repo(tmp_path)
    ns = _full_namespace(attach=["a.png"])
    argv = _background_child_argv(ns, repo)

    assert "--attach" in argv
    idx = argv.index("--attach")
    assert argv[idx + 1] == str(Path("a.png").resolve())


def test_background_child_argv_forwards_multiple_attach_values_in_order(tmp_path):
    repo = _init_repo(tmp_path)
    ns = _full_namespace(attach=["a.png", "sub/b.wav"])
    argv = _background_child_argv(ns, repo)

    attach_indices = [i for i, tok in enumerate(argv) if tok == "--attach"]
    assert len(attach_indices) == 2
    resolved = [argv[i + 1] for i in attach_indices]
    assert resolved == [str(Path("a.png").resolve()), str(Path("sub/b.wav").resolve())]


def test_background_child_argv_forwards_until_done_and_max_episodes(tmp_path):
    """Acceptance (indefinite-run t9, criterion 2): a `work --background
    --until-done --max-episodes N` chain forwards BOTH arming flags to the
    detached child via the forwardable-flags list, so the child runs the same
    armed chain the parent was asked for."""
    repo = _init_repo(tmp_path)
    ns = _full_namespace(until_done=True, max_episodes=7)
    argv = _background_child_argv(ns, repo)

    assert "--until-done" in argv
    assert argv[argv.index("--max-episodes") + 1] == "7"


def test_background_child_argv_forwards_explicit_zero_max_episodes(tmp_path):
    """--max-episodes 0 (explicit unlimited, c21) is falsy — it must ride the
    tail's `is not None` idiom, never be dropped by the truthy flag table."""
    repo = _init_repo(tmp_path)
    ns = _full_namespace(until_done=True, max_episodes=0)
    argv = _background_child_argv(ns, repo)

    assert argv[argv.index("--max-episodes") + 1] == "0"


def test_background_child_argv_omits_chain_flags_when_unarmed(tmp_path):
    """An unarmed background run's child argv carries neither chain flag."""
    repo = _init_repo(tmp_path)
    ns = _full_namespace()  # no until_done / max_episodes attrs at all
    argv = _background_child_argv(ns, repo)

    assert "--until-done" not in argv
    assert "--max-episodes" not in argv


# --- cmd_work wiring: --background never runs the loop in the parent -------


def test_cmd_work_background_never_runs_loop_in_parent(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    calls: dict = {}

    def fake_spawn(repo_arg, argv, *, handle_id=None, flight_id=None, env=None):
        calls["repo"] = repo_arg
        calls["argv"] = argv
        calls["handle_id"] = handle_id
        calls["flight_id"] = flight_id
        return background.BackgroundHandle(
            id=handle_id,
            pid=999999,
            log_dir=f".colleague/background/{handle_id}/",
            flight=flight_id,
        )

    def boom_execute_work(*_a, **_k):
        raise AssertionError("execute_work must never run in the --background parent")

    monkeypatch.setattr(work_mod.background, "spawn_background", fake_spawn)
    monkeypatch.setattr(work_mod, "execute_work", boom_execute_work)

    rc = main(
        [
            "work",
            "do a thing",
            "--repo",
            str(repo),
            "--engine",
            "mock",
            "--no-pr",
            "--background",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "background": True,
        "id": calls["handle_id"],
        "pid": 999999,
        "log_dir": f".colleague/background/{calls['handle_id']}/",
        "flight": calls["handle_id"],
    }
    assert calls["handle_id"] == calls["flight_id"]
    assert Path(calls["repo"]) == repo
    assert "--background" not in calls["argv"]
    assert "--watch" in calls["argv"]
    assert calls["argv"][:3] == [sys.executable, "-m", "colleague"]
    assert calls["argv"][3] == "work"


def test_cmd_work_background_text_render(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)

    def fake_spawn(repo_arg, argv, *, handle_id=None, flight_id=None, env=None):
        return background.BackgroundHandle(
            id=handle_id,
            pid=424242,
            log_dir=f".colleague/background/{handle_id}/",
            flight=flight_id,
        )

    monkeypatch.setattr(work_mod.background, "spawn_background", fake_spawn)

    rc = main(
        [
            "work",
            "do a thing",
            "--repo",
            str(repo),
            "--engine",
            "mock",
            "--no-pr",
            "--background",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "background:" in out
    assert "pid: 424242" in out
    assert "log_dir:" in out
    assert "flight:" in out


# --- full end-to-end: the child actually completes the work item -----------


def test_background_work_completes_end_to_end_with_no_attached_terminal(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    rc = main(
        [
            "work",
            "write a mock file",
            "--repo",
            str(repo),
            "--engine",
            "mock",
            "--no-pr",
            "--background",
            "--json",
        ]
    )
    # The parent returns immediately with the JSON start payload -- it never
    # ran engine.work() itself (proven separately by
    # test_cmd_work_background_never_runs_loop_in_parent above).
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["background"] is True
    handle_id = payload["id"]
    assert payload["flight"] == handle_id
    assert isinstance(payload["pid"], int)
    assert payload["pid"] != os.getpid()
    assert payload["log_dir"] == f".colleague/background/{handle_id}/"

    ldir = repo / payload["log_dir"]
    assert ldir.is_dir()

    # Bounded wait for the detached child (mock engine, fast) to finish and
    # write its artifact end-to-end -- no polling loop of colleague's own, this
    # is purely the test observing the filesystem.
    artifact_path, result = _wait_for_artifact(repo, handle_id, timeout=30)
    assert result["task_id"] == handle_id
    assert result["status"] == "ok"
    assert "colleague-mock.md" in result.get("changed_files", [])

    # No attached terminal: the child's own stdio landed in the log files, not
    # in this test's captured streams.
    stderr_text = (ldir / "stderr.log").read_text()
    assert stderr_text.strip() != ""
    leaked = capsys.readouterr()
    assert "flight:" not in leaked.err  # the child's own flight diagnostic never leaked here

    # Gradable: the exact task_id the payload named can be graded via the
    # ordinary feedback verb, same as any foreground work item.
    rc2 = main(["feedback", "record", handle_id, "--rating", "5", "--repo", str(repo)])
    assert rc2 == 0
    capsys.readouterr()
    rc3 = main(["feedback", "show", handle_id, "--repo", str(repo), "--json"])
    assert rc3 == 0
    fb_payload = json.loads(capsys.readouterr().out)
    assert fb_payload["rating"] == 5
    assert fb_payload["task_id"] == handle_id

    # Reap the child from this test's own process table (see _reap_child) so a
    # genuine end-of-run liveness check is accurate, then prove it is reapable.
    _reap_child(payload["pid"])
    assert background._pid_alive(payload["pid"]) is False
    reaped = background.reap_background(repo)
    assert any(r["background"] == handle_id and r["action"] == "reaped" for r in reaped)
    assert not ldir.exists()

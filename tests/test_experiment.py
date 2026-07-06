"""Tests for the ``experiment`` noun (colleague#291 S5, plan task t23).

Covers, mirroring the plan's acceptance criteria:

1. ``experiment start`` validates the dataset first (a stub ``sloth validate``
   exit 1 refuses the run, exit 1, nothing detached); on success it writes
   ``start.json`` + detaches ``sloth train`` (payload shape, pid alive, this
   test never waits on the child beyond ``os.kill`` probing).
2. ``experiment status``/``experiment list`` round-trip against the written
   payload + a live pid probe + a best-effort sloth registry correlation.
3. ``experiment summarize --remember`` upserts into eidetic via a stubbed
   ``eidetic`` CLI on PATH — the argv carries ``--scope colleague
   --visibility public`` (the t18 drift-test convention).
4. A missing ``sloth`` CLI degrades to a structured error with remediation,
   never a traceback.
5. Boundary: ``colleague/experiment.py`` joins ``_SUBPROCESS_ALLOWED`` and has
   no ``.wait()``/``.poll()``/socket/asyncio/threading — pinned directly in
   ``tests/test_boundary.py``.
6. ``colleague clean`` reaps dead-pid + aged experiment residue; a live pid
   (or a too-recent dead one) is never touched.
7. Every new verb is wired end-to-end through ``main()``.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from unittest.mock import patch

import pytest

import colleague.experiment as experiment_mod
from colleague.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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

    Mirrors ``tests/test_background.py``'s helper of the same name: in real
    usage the parent CLI process exits right after printing the start
    payload, so the kernel reparents any leftover zombie to init; the test
    process stays alive across assertions, so this reaps explicitly.
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


_SLOTH_STUB = r"""#!/usr/bin/env python3
import json
import os
import sys
import time

argv = sys.argv[1:]

def _emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")

if argv[:1] == ["validate"]:
    exit_code = int(os.environ.get("SLOTH_STUB_VALIDATE_EXIT", "0"))
    if exit_code != 0:
        sys.stderr.write(os.environ.get(
            "SLOTH_STUB_VALIDATE_STDERR",
            '{"code": 1, "message": "dataset invalid", "remediation": "fix it"}',
        ))
        sys.stderr.write("\n")
        sys.exit(exit_code)
    _emit({"valid": True, "schema": "chat", "line_count": 3})
    sys.exit(0)

elif argv[:1] == ["train"]:
    marker = os.environ.get("SLOTH_STUB_TRAIN_MARKER")
    if marker:
        with open(marker, "a", encoding="utf-8") as fh:
            fh.write("train-ran\n")
    time.sleep(float(os.environ.get("SLOTH_STUB_TRAIN_SLEEP", "0.3")))
    sys.exit(0)

elif argv[:2] == ["runs", "list"]:
    raw = os.environ.get("SLOTH_STUB_RUNS_LIST_JSON", "[]")
    sys.stdout.write(raw)
    sys.stdout.write("\n")
    sys.exit(0)

elif argv[:2] == ["runs", "show"]:
    raw = os.environ.get("SLOTH_STUB_RUNS_SHOW_JSON", "{}")
    sys.stdout.write(raw)
    sys.stdout.write("\n")
    sys.exit(0)

elif argv[:1] == ["summarize"]:
    exit_code = int(os.environ.get("SLOTH_STUB_SUMMARIZE_EXIT", "0"))
    if exit_code != 0:
        sys.stderr.write(os.environ.get(
            "SLOTH_STUB_SUMMARIZE_STDERR",
            '{"code": 1, "message": "no such run", "remediation": "check the output dir"}',
        ))
        sys.stderr.write("\n")
        sys.exit(exit_code)
    raw = os.environ.get(
        "SLOTH_STUB_SUMMARIZE_JSON",
        '{"output_dir": "adapters/out", "metadata": null, "training": null, "notes": []}',
    )
    sys.stdout.write(raw)
    sys.stdout.write("\n")
    sys.exit(0)

else:
    sys.exit(1)
"""


def _install_sloth_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the fake ``sloth`` CLI at the front of PATH; return its path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "sloth"
    script.write_text(_SLOTH_STUB, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    return script


def _write_run_toml(
    repo: Path, *, dataset: str = "data/train.jsonl", output: str = "adapters/out"
) -> Path:
    (repo / "data").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "train.jsonl").write_text('{"messages": []}\n', encoding="utf-8")
    toml_path = repo / "run.toml"
    toml_path.write_text(
        f'[run]\nmodel = "unsloth/Qwen3-4B"\nmethod = "qlora"\n'
        f'dataset = "{dataset}"\noutput = "{output}"\n',
        encoding="utf-8",
    )
    return toml_path


# ---------------------------------------------------------------------------
# start_experiment — validate-first refusal
# ---------------------------------------------------------------------------


def test_start_refuses_on_validate_failure(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_VALIDATE_EXIT", "1")
    monkeypatch.setenv(
        "SLOTH_STUB_VALIDATE_STDERR",
        json.dumps({"code": 1, "message": "0 valid records", "remediation": "fix your dataset"}),
    )

    with pytest.raises(experiment_mod.ExperimentError) as excinfo:
        experiment_mod.start_experiment(repo, toml_path)

    assert excinfo.value.code == 1
    assert "0 valid records" in excinfo.value.message
    # Nothing was launched: no experiment dir was created.
    assert not experiment_mod.experiments_root(repo).exists()


# ---------------------------------------------------------------------------
# start_experiment — success: writes start.json + detaches, never waits
# ---------------------------------------------------------------------------


def test_start_writes_payload_and_detaches(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.3")

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        payload = handle.to_dict()
        assert set(payload) == {"id", "pid", "config", "output_dir", "log_dir", "started"}
        assert payload["output_dir"] == "adapters/out"
        assert payload["config"] == str(toml_path.resolve())
        assert payload["log_dir"] == f".colleague/experiments/{payload['id']}/"
        assert payload["pid"] != os.getpid()

        # This test never calls .wait()/.poll() — only the non-blocking probe.
        assert experiment_mod._pid_alive(payload["pid"]) is True

        edir = experiment_mod.experiment_dir(repo, payload["id"])
        assert edir.is_dir()
        on_disk = json.loads((edir / "start.json").read_text(encoding="utf-8"))
        assert on_disk == payload
    finally:
        _reap_child(handle.pid)


def test_start_config_relative_path_resolves_against_repo(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")

    handle = experiment_mod.start_experiment(repo, "run.toml")
    try:
        assert handle.config == str((repo / "run.toml").resolve())
    finally:
        _reap_child(handle.pid)


def test_start_missing_config_file_is_clean_error(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)

    with pytest.raises(experiment_mod.ExperimentError) as excinfo:
        experiment_mod.start_experiment(repo, "nope.toml")
    assert excinfo.value.code == 1
    assert "not found" in excinfo.value.message


def test_start_missing_run_section_key_is_clean_error(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = repo / "bad.toml"
    toml_path.write_text('[run]\nmodel = "x"\n', encoding="utf-8")  # missing dataset/output

    with pytest.raises(experiment_mod.ExperimentError) as excinfo:
        experiment_mod.start_experiment(repo, toml_path)
    assert excinfo.value.code == 1
    assert "dataset" in excinfo.value.message


# ---------------------------------------------------------------------------
# missing sloth CLI -> structured error, never a traceback
# ---------------------------------------------------------------------------


def test_start_missing_sloth_cli_is_structured_error(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    toml_path = _write_run_toml(repo)

    with pytest.raises(experiment_mod.ExperimentError) as excinfo:
        experiment_mod.start_experiment(repo, toml_path)
    assert excinfo.value.code == 2
    assert "uv tool install unsloth-cli" in excinfo.value.remediation


def test_summarize_missing_sloth_cli_is_structured_error(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    with pytest.raises(experiment_mod.ExperimentError) as excinfo:
        experiment_mod.summarize_experiment(repo, "nonexistent-id")
    assert excinfo.value.code == 2
    assert "uv tool install unsloth-cli" in excinfo.value.remediation


def test_cmd_experiment_start_missing_sloth_cli_exits_2(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    toml_path = _write_run_toml(repo)

    rc = main(
        [
            "experiment",
            "start",
            "--config",
            str(toml_path),
            "--repo",
            str(repo),
            "--json",
        ]
    )
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == 2
    assert "uv tool install unsloth-cli" in err["remediation"]


# ---------------------------------------------------------------------------
# experiment_status / list_experiments round-trip
# ---------------------------------------------------------------------------


def test_status_reports_alive_and_log_tail(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.3")
    monkeypatch.setenv("SLOTH_STUB_RUNS_LIST_JSON", "[]")

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        status = experiment_mod.experiment_status(repo, handle.id)
        assert status["id"] == handle.id
        assert status["pid"] == handle.pid
        assert status["alive"] is True
        assert status["sloth_run"] is None  # empty registry -> no match
        assert isinstance(status["log_tail"], list)
    finally:
        _reap_child(handle.pid)


def test_status_correlates_sloth_run_registry(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")
    record = {
        "run_id": "abc123-20260706T000000Z",
        "output_dir": "adapters/out",
        "status": "running",
    }
    monkeypatch.setenv("SLOTH_STUB_RUNS_LIST_JSON", json.dumps([record]))
    show_record = dict(record, output_dir_exists=True)
    monkeypatch.setenv("SLOTH_STUB_RUNS_SHOW_JSON", json.dumps(show_record))

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        _reap_child(handle.pid)  # let the short-lived stub finish before querying
        status = experiment_mod.experiment_status(repo, handle.id)
        assert status["sloth_run"] == show_record
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


def test_status_unknown_id_raises_clean_error(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    with pytest.raises(experiment_mod.ExperimentError) as excinfo:
        experiment_mod.experiment_status(repo, "does-not-exist")
    assert excinfo.value.code == 1


def test_list_experiments_newest_first_and_alive_flag(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")

    assert experiment_mod.list_experiments(repo) == []

    handle1 = experiment_mod.start_experiment(repo, toml_path)
    time.sleep(1.1)  # started timestamps are second-precision-ish; force ordering
    handle2 = experiment_mod.start_experiment(repo, toml_path)
    try:
        entries = experiment_mod.list_experiments(repo)
        assert [e["id"] for e in entries] == [handle2.id, handle1.id]
        assert all("alive" in e for e in entries)
    finally:
        _reap_child(handle1.pid)
        _reap_child(handle2.pid)


# ---------------------------------------------------------------------------
# summarize_experiment --remember -> eidetic upsert (scope colleague/public)
# ---------------------------------------------------------------------------


def _install_eidetic_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "eidetic-bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "eidetic"
    script.write_text(
        "#!/bin/sh\n"
        'LOG="$(pwd)/eidetic-argv.log"\n'
        'echo "$@" >> "$LOG"\n'
        'if [ "$1" = "remember" ]; then echo ok; fi\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    # Prepend so both sloth and eidetic are reachable from the SAME front-of-PATH dir set.
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")


def test_summarize_without_remember_never_calls_eidetic(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    _install_eidetic_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")
    monkeypatch.setenv(
        "SLOTH_STUB_SUMMARIZE_JSON",
        json.dumps(
            {
                "output_dir": "adapters/out",
                "metadata": {
                    "model": "unsloth/Qwen3-4B",
                    "method": "qlora",
                    "dataset": {"sha256": "deadbeef" * 8, "line_count": 3},
                },
                "training": {"final_step": 60, "final_loss": 0.42},
                "notes": [],
            }
        ),
    )

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        _reap_child(handle.pid)
        result = experiment_mod.summarize_experiment(repo, handle.id, remember=False)
        assert result["remembered"] is False
        assert not (repo / "eidetic-argv.log").exists()
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


def test_summarize_remember_upserts_with_scope_colleague_public(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    _install_eidetic_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")
    monkeypatch.setenv(
        "SLOTH_STUB_SUMMARIZE_JSON",
        json.dumps(
            {
                "output_dir": "adapters/out",
                "metadata": {
                    "model": "unsloth/Qwen3-4B",
                    "method": "qlora",
                    "dataset": {"sha256": "deadbeef" * 8, "line_count": 3},
                },
                "training": {"final_step": 60, "final_loss": 0.42},
                "notes": [],
            }
        ),
    )

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        _reap_child(handle.pid)
        result = experiment_mod.summarize_experiment(repo, handle.id, remember=True)
        assert result["remembered"] is True
        assert result["training"]["final_loss"] == 0.42

        argv_log = (repo / "eidetic-argv.log").read_text(encoding="utf-8")
        assert "remember" in argv_log
        assert "--scope colleague" in argv_log
        assert "--visibility public" in argv_log
        assert f"experiment-{handle.id}" in argv_log
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


def test_summarize_eidetic_absent_degrades_to_remembered_false(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")
    monkeypatch.setenv(
        "SLOTH_STUB_SUMMARIZE_JSON",
        json.dumps({"output_dir": "adapters/out", "metadata": None, "training": None, "notes": []}),
    )

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        _reap_child(handle.pid)
        # A bare PATH prepend (the usual `_install_sloth_stub` setup) still
        # finds a REAL `eidetic` CLI installed on the dev machine's own PATH,
        # which would make this "absent" test pass for the wrong reason — patch
        # `colleague.memory.shutil.which` directly instead (the same pattern
        # `tests/test_memory.py`'s own CLI-absent tests use).
        with patch("colleague.memory.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            result = experiment_mod.summarize_experiment(repo, handle.id, remember=True)
        assert result["remembered"] is False
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


def test_summarize_failure_raises_clean_error(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")
    monkeypatch.setenv("SLOTH_STUB_SUMMARIZE_EXIT", "1")
    monkeypatch.setenv(
        "SLOTH_STUB_SUMMARIZE_STDERR",
        json.dumps({"code": 1, "message": "no adapter found", "remediation": "check output dir"}),
    )

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        _reap_child(handle.pid)
        with pytest.raises(experiment_mod.ExperimentError) as excinfo:
            experiment_mod.summarize_experiment(repo, handle.id)
        assert "no adapter found" in excinfo.value.message
    finally:
        with suppress(Exception):
            _reap_child(handle.pid, timeout=1)


# ---------------------------------------------------------------------------
# colleague clean -> reap_experiments: dead+aged reaped, live/recent kept
# ---------------------------------------------------------------------------


def test_reap_experiments_missing_root_is_noop(tmp_path):
    repo = _init_repo(tmp_path)
    assert experiment_mod.reap_experiments(repo) == []


def test_reap_experiments_keeps_dead_but_recent(tmp_path):
    repo = _init_repo(tmp_path)
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    d = experiment_mod.experiment_dir(repo, "recent1")
    d.mkdir(parents=True)
    (d / "start.json").write_text(
        json.dumps({"id": "recent1", "pid": dead_proc.pid, "output_dir": "adapters/out"}),
        encoding="utf-8",
    )

    results = experiment_mod.reap_experiments(repo, min_age_seconds=3600)
    assert results == []
    assert d.exists()


def test_reap_experiments_reaps_dead_and_aged_keeps_live(tmp_path):
    repo = _init_repo(tmp_path)

    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    dead_dir = experiment_mod.experiment_dir(repo, "dead-aged")
    dead_dir.mkdir(parents=True)
    (dead_dir / "start.json").write_text(
        json.dumps({"id": "dead-aged", "pid": dead_proc.pid, "output_dir": "adapters/out"}),
        encoding="utf-8",
    )
    # Force the file to look old enough to be reapable.
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(dead_dir / "start.json", (old, old))

    live_dir = experiment_mod.experiment_dir(repo, "live1")
    live_dir.mkdir(parents=True)
    (live_dir / "start.json").write_text(
        json.dumps({"id": "live1", "pid": os.getpid(), "output_dir": "adapters/out"}),
        encoding="utf-8",
    )

    results = experiment_mod.reap_experiments(repo)
    by_id = {r["experiment"]: r["action"] for r in results}
    assert by_id["dead-aged"] == "reaped"
    assert "live1" not in by_id  # a live holder is never even reported
    assert not dead_dir.exists()
    assert live_dir.exists()


def test_reap_experiments_dry_run_changes_nothing(tmp_path):
    repo = _init_repo(tmp_path)
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    d = experiment_mod.experiment_dir(repo, "dead2")
    d.mkdir(parents=True)
    (d / "start.json").write_text(
        json.dumps({"id": "dead2", "pid": dead_proc.pid, "output_dir": "adapters/out"}),
        encoding="utf-8",
    )
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(d / "start.json", (old, old))

    results = experiment_mod.reap_experiments(repo, dry_run=True)
    assert results == [{"experiment": "dead2", "action": "would-reap"}]
    assert d.exists()


def test_reap_experiments_corrupt_payload_is_kept(tmp_path):
    repo = _init_repo(tmp_path)
    d = experiment_mod.experiment_dir(repo, "corrupt1")
    d.mkdir(parents=True)
    (d / "start.json").write_text("{not json", encoding="utf-8")

    results = experiment_mod.reap_experiments(repo)
    assert results == [{"experiment": "corrupt1", "action": "kept-unknown"}]
    assert d.exists()


def test_reap_experiments_never_touches_a_live_run(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "30")

    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        assert experiment_mod._pid_alive(handle.pid) is True
        assert experiment_mod.reap_experiments(repo, dry_run=True) == []
        assert experiment_mod.reap_experiments(repo) == []
        assert experiment_mod.experiment_dir(repo, handle.id).is_dir()
    finally:
        with suppress(ProcessLookupError):
            os.kill(handle.pid, signal.SIGKILL)
        _reap_child(handle.pid)


def test_clean_cli_reaps_dead_aged_experiment_and_keeps_live(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)

    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait()
    dead_dir = experiment_mod.experiment_dir(repo, "cli-dead")
    dead_dir.mkdir(parents=True)
    (dead_dir / "start.json").write_text(
        json.dumps({"id": "cli-dead", "pid": dead_proc.pid, "output_dir": "adapters/out"}),
        encoding="utf-8",
    )
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(dead_dir / "start.json", (old, old))

    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "30")
    handle = experiment_mod.start_experiment(repo, toml_path)
    try:
        rc = main(["clean", "--repo", str(repo), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        by_id = {e["experiment"]: e["action"] for e in report["experiments"]}
        assert by_id["cli-dead"] == "reaped"
        assert handle.id not in by_id
        assert not dead_dir.exists()
        assert experiment_mod.experiment_dir(repo, handle.id).is_dir()
    finally:
        with suppress(ProcessLookupError):
            os.kill(handle.pid, signal.SIGKILL)
        _reap_child(handle.pid)


# ---------------------------------------------------------------------------
# every new verb wired end-to-end through main()
# ---------------------------------------------------------------------------


def test_cmd_experiment_start_end_to_end_json(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.2")

    rc = main(
        [
            "experiment",
            "start",
            "--config",
            str(toml_path),
            "--repo",
            str(repo),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"id", "pid", "config", "output_dir", "log_dir", "started"}
    _reap_child(payload["pid"])


def test_cmd_experiment_start_text_render(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")

    rc = main(["experiment", "start", "--config", str(toml_path), "--repo", str(repo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "experiment:" in out
    assert "pid:" in out
    assert "output_dir:" in out
    # Reap the child by pid printed in the text output.
    for line in out.splitlines():
        if line.startswith("pid:"):
            _reap_child(int(line.split(":", 1)[1].strip()))


def test_cmd_experiment_start_validate_failure_exit_1(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_VALIDATE_EXIT", "1")

    rc = main(["experiment", "start", "--config", str(toml_path), "--repo", str(repo), "--json"])
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == 1


def test_cmd_experiment_status_and_list_end_to_end(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")

    rc = main(["experiment", "start", "--config", str(toml_path), "--repo", str(repo), "--json"])
    assert rc == 0
    start_payload = json.loads(capsys.readouterr().out)
    exp_id = start_payload["id"]

    rc = main(["experiment", "status", exp_id, "--repo", str(repo), "--json"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["id"] == exp_id

    rc = main(["experiment", "list", "--repo", str(repo), "--json"])
    assert rc == 0
    entries = json.loads(capsys.readouterr().out)
    assert any(e["id"] == exp_id for e in entries)

    _reap_child(start_payload["pid"])


def test_cmd_experiment_status_unknown_id_exit_1(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    rc = main(["experiment", "status", "nope", "--repo", str(repo), "--json"])
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == 1


def test_cmd_experiment_list_empty_repo(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    rc = main(["experiment", "list", "--repo", str(repo), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cmd_experiment_overview(capsys):
    rc = main(["experiment", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "sections" in payload


def test_bare_experiment_falls_through_to_overview(capsys):
    rc = main(["experiment"])
    assert rc == 0
    assert "colleague experiment" in capsys.readouterr().out


def test_cmd_experiment_summarize_end_to_end(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    _install_eidetic_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")
    monkeypatch.setenv(
        "SLOTH_STUB_SUMMARIZE_JSON",
        json.dumps(
            {
                "output_dir": "adapters/out",
                "metadata": {
                    "model": "m",
                    "method": "qlora",
                    "dataset": {"sha256": "ab", "line_count": 1},
                },
                "training": {"final_step": 10, "final_loss": 1.0},
                "notes": [],
            }
        ),
    )

    rc = main(["experiment", "start", "--config", str(toml_path), "--repo", str(repo), "--json"])
    assert rc == 0
    start_payload = json.loads(capsys.readouterr().out)
    _reap_child(start_payload["pid"])

    rc = main(
        [
            "experiment",
            "summarize",
            start_payload["id"],
            "--remember",
            "--repo",
            str(repo),
            "--json",
        ]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["remembered"] is True


# ---------------------------------------------------------------------------
# gradeable via `colleague feedback record <exp-id>`
# ---------------------------------------------------------------------------


def test_experiment_id_is_gradeable_via_feedback(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _install_sloth_stub(tmp_path, monkeypatch)
    toml_path = _write_run_toml(repo)
    monkeypatch.setenv("SLOTH_STUB_TRAIN_SLEEP", "0.1")

    rc = main(["experiment", "start", "--config", str(toml_path), "--repo", str(repo), "--json"])
    assert rc == 0
    start_payload = json.loads(capsys.readouterr().out)
    _reap_child(start_payload["pid"])

    rc = main(["feedback", "record", start_payload["id"], "--rating", "5", "--repo", str(repo)])
    assert rc == 0
    capsys.readouterr()

    rc = main(["feedback", "show", start_payload["id"], "--repo", str(repo), "--json"])
    assert rc == 0
    fb = json.loads(capsys.readouterr().out)
    assert fb["rating"] == 5
    assert fb["task_id"] == start_payload["id"]

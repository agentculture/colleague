"""Background one-shot detach primitive (plan task t12, spec R4 / honesty h10,
boundary h6).

``colleague work --background`` needs a run that starts detached from the
caller's terminal and keeps going after the caller's process exits — but it
must NOT become a daemon: no supervisor process, no polling loop, no socket.
The primitive here is the smallest thing that satisfies both: a ONE-SHOT
``subprocess.Popen(..., start_new_session=True)`` that re-invokes the
colleague CLI itself as a brand new *session leader* (``setsid``), with its
stdio redirected to per-handle log files under
``.colleague/background/<id>/`` and no further code running in the parent
after launch. The parent mints a handle id, launches the child, and returns —
nothing here ever blocks or polls the child.

This is colleague's answer to the sibling agent-lifecycle spec's question of
whether "batch"/run-to-completion needs its own lifecycle mode, or whether a
plain restart-policy ``never`` already covers it (see plan task t13, the
resident harness): a detached one-shot needs **no supervisor at all**. It
starts, runs the normal foreground work path in the child (the SAME
``colleague work`` code path, just re-invoked without ``--background``),
writes its artifact, and exits. There is nothing to restart and nothing to
supervise, so this module stays intentionally supervisor-free — the
*resident* (t13) is a different shape entirely (a long-lived Harness that
accepts many requests over time), not a generalization of this one-shot.

Liveness for reaping crashed residue (:func:`reap_background`, consumed by
``colleague clean``) is determined the same honest way the flight plane does
it — no daemon means no process registry, so a recorded pid is probed
directly with ``os.kill(pid, 0)``; a dir whose pid is gone is reapable, a dir
whose pid is still alive is never touched.

Confined here as the ONE sanctioned ``subprocess`` consumer for the detach
primitive (``tests/test_boundary.py`` extends its sanctioned-consumer list to
include this module) — no other colleague module spawns a background
process.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

BACKGROUND_DIR_NAME = "background"
#: Env var carrying the parent-minted handle id into the detached child so its
#: artifact/flight/log files are all findable from the SAME id the parent
#: printed in its start payload. Only ever set by :func:`spawn_background`.
BACKGROUND_ID_ENV = "COLLEAGUE_BACKGROUND_ID"
META_FILENAME = "meta.json"
STDOUT_FILENAME = "stdout.log"
STDERR_FILENAME = "stderr.log"


def background_root(repo_path: str | Path) -> Path:
    """``<repo_path>/.colleague/background/`` — the parent of every handle's log dir."""
    return Path(repo_path) / ".colleague" / BACKGROUND_DIR_NAME


def log_dir(repo_path: str | Path, handle_id: str) -> Path:
    """``<repo_path>/.colleague/background/<handle_id>/`` — one run's log directory."""
    return background_root(repo_path) / handle_id


def relative_log_dir(handle_id: str) -> str:
    """The repo-relative, POSIX-style ``log_dir`` string for the start payload."""
    return (Path(".colleague") / BACKGROUND_DIR_NAME / handle_id).as_posix() + "/"


def new_handle_id() -> str:
    """Mint a short, filesystem-safe handle id (parent-side, before the child exists)."""
    return uuid.uuid4().hex[:12]


@dataclass
class BackgroundHandle:
    """The parent-side record of a detached child — the JSON start payload's source."""

    id: str
    pid: int
    log_dir: str
    flight: str | None

    def to_dict(self) -> dict:
        return {
            "background": True,
            "id": self.id,
            "pid": self.pid,
            "log_dir": self.log_dir,
            "flight": self.flight,
        }


def spawn_background(
    repo_path: str | Path,
    argv: list[str],
    *,
    handle_id: str | None = None,
    flight_id: str | None = None,
    env: dict[str, str] | None = None,
) -> BackgroundHandle:
    """Detach *argv* as a session-leader child; return its :class:`BackgroundHandle`.

    One-shot: this function returns as soon as the child is launched — it never
    waits, polls, or supervises it. ``argv`` is executed as-is (the caller
    builds it — typically ``[sys.executable, "-m", "colleague", "work", ...]``
    so the child re-invokes the *exact* running package, never a stale PATH
    install).

    stdio is fully detached from the caller: stdout/stderr are redirected to
    ``<log_dir>/stdout.log`` / ``stderr.log`` and stdin is ``DEVNULL``, so the
    child can never block on or write to the caller's terminal.
    ``start_new_session=True`` makes the child a new session leader (POSIX
    ``setsid``), so it is not killed by the caller's terminal hanging up and
    keeps running after the caller's process exits.

    *handle_id* is normally pre-minted by the caller (:func:`new_handle_id`) so
    the caller's own JSON start payload and the child's artifact/log files
    share one id; a fresh one is minted here when omitted. A ``meta.json``
    recording ``{id, pid, flight, started_at}`` is written into the log dir so
    a later, unrelated process (``colleague clean``) can determine liveness
    without a daemon or process registry — see :func:`reap_background`.
    """
    repo_path = Path(repo_path)
    handle_id = handle_id or new_handle_id()
    ldir = log_dir(repo_path, handle_id)
    ldir.mkdir(parents=True, exist_ok=True)

    child_env = dict(os.environ if env is None else env)
    child_env[BACKGROUND_ID_ENV] = handle_id

    stdout_path = ldir / STDOUT_FILENAME
    stderr_path = ldir / STDERR_FILENAME
    with open(stdout_path, "ab") as out, open(stderr_path, "ab") as err:
        proc = subprocess.Popen(
            list(argv),
            cwd=str(repo_path),
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            env=child_env,
            start_new_session=True,
        )

    flight_id = flight_id or handle_id
    meta = {
        "id": handle_id,
        "pid": proc.pid,
        "flight": flight_id,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (ldir / META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")

    return BackgroundHandle(
        id=handle_id,
        pid=proc.pid,
        log_dir=relative_log_dir(handle_id),
        flight=flight_id,
    )


def _pid_alive(pid: object) -> bool:
    """True if *pid* refers to a process this host can still see.

    ``os.kill(pid, 0)`` sends no signal — it only probes existence/permission.
    ``ProcessLookupError`` means the pid is gone (reapable); a
    ``PermissionError`` means it exists but is owned by someone else (never
    reap what can't be proven dead); any other surprise is treated the same
    conservative way, so reaping never races a live holder.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _read_meta(d: Path) -> dict:
    try:
        data = json.loads((d / META_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_background_ids(repo_path: str | Path) -> list[str]:
    """Every handle id with a log dir under ``.colleague/background/``; ``[]`` if absent."""
    root = background_root(repo_path)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def reap_background(repo_path: str | Path, *, dry_run: bool = False) -> list[dict]:
    """Reap a background run's log dir once its holder pid is gone.

    A crashed (``kill -9``'d) background child leaves its ``meta.json`` and log
    files behind under ``.colleague/background/<id>/`` with no process left to
    clean them up — there is no supervisor (see the module docstring). This
    reaps exactly that: a dir whose recorded pid is no longer alive
    (:func:`_pid_alive`). A dir whose pid IS alive — a run still genuinely in
    progress — is never touched, matching the flight/artifact reap
    conventions (``colleague/flight.py`` / ``colleague/artifact.py``).

    Returns one ``{"background": <id>, "action": ...}`` dict per affected dir;
    ``action`` is ``reaped`` / ``would-reap`` (dry-run) / ``failed``. A missing
    root dir is a no-op (``[]``).
    """
    root = background_root(repo_path)
    results: list[dict] = []
    if not root.is_dir():
        return results
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = _read_meta(d)
        pid = meta.get("pid")
        if not isinstance(pid, int):
            # No liveness signal at all (meta.json missing/corrupt/incomplete):
            # a child may still be alive behind it, so NEVER delete — report the
            # dir honestly instead (PR #267 review; conservative like the
            # flight/artifact reaps). Operator judgment can remove it manually.
            results.append({"background": d.name, "action": "kept-unknown"})
            continue
        if _pid_alive(pid):
            continue  # a live holder -> never reap a run still in progress
        if dry_run:
            results.append({"background": d.name, "action": "would-reap"})
            continue
        try:
            shutil.rmtree(d)
            results.append({"background": d.name, "action": "reaped"})
        except OSError:
            results.append({"background": d.name, "action": "failed"})
    return results

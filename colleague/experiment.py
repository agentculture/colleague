"""Experiment runner — detached ``sloth`` training runs (colleague#291 S5).

The **experiment** noun drives unsloth-cli's ``sloth`` CLI via a curated
allow-listed shell-out (the same pattern as :mod:`colleague.culture` /
:mod:`colleague.devague` / :mod:`colleague.memory`), with the long-run
problem solved *job-shaped*: launched **detached** with a machine-readable job
handle (the ``colleague work --background`` session-leader-detach precedent,
:mod:`colleague.background`), status queryable mid-run, and on completion the
experiment summary is remembered to eidetic (the memory scope convention —
see ``tests/test_memory_convention.py``) and gradeable via ``colleague
feedback record <exp-id>``.

Flow, mirroring ``sloth train``'s own host-side preflight
(unsloth-cli/sloth/cli/_commands/train.py): **validate before spending GPU**.
:func:`start_experiment` reads the run's ``dataset``/``output`` straight out
of the ``[run]`` TOML table (stdlib ``tomllib`` — colleague never imports
``sloth.tune.config``, let alone torch/unsloth), runs ``sloth validate
--dataset <dataset> --json`` and refuses to launch anything on a failure, then
detaches ``sloth train --config <toml>`` **exactly the background.py way**:
``subprocess.Popen(..., start_new_session=True)``, stdio redirected to a log
file under ``.colleague/experiments/<id>/``, and a JSON start payload written
beside it. This module never blocks on or polls the child process — a
dedicated boundary test (mirroring ``test_background_module_confined_to_one_shot_detach``)
pins that, alongside ``tests/test_boundary.py``'s ``_SUBPROCESS_ALLOWED`` entry.

``experiment_status`` and ``list_experiments`` are pure local reads (the
start payload + a log tail + the pid liveness probe, ``os.kill(pid, 0)``,
duplicated locally rather than imported from :mod:`colleague.background` —
matching the existing per-module convention, see ``colleague/rig.py`` /
``colleague/worktrees.py``); they additionally best-effort correlate against
sloth's own run registry (``sloth runs list``/``show --json``) when the CLI is
reachable, degrading to ``sloth_run: None`` rather than failing the status
query. ``summarize_experiment`` shells out to ``sloth summarize <output_dir>
--json`` (an existing output directory always resolves directly — see
``sloth.tune.registry.resolve_target``) and, with ``remember=True``, upserts
ONE compact record into eidetic via :func:`colleague.memory.remember` — reused
as-is, so this module never re-implements or diverges from the memory scope
convention.

``reap_experiments`` (consumed by ``colleague clean``) follows the
``colleague/background.py`` reap pattern with ONE deliberate difference: a
background work item's durable result lives in a SEPARATE artifact file, so
``reap_background`` can remove a dead-pid log dir the instant the pid is
gone. An experiment's start payload + train log ARE the durable record (there
is no separate artifact) — reaping the moment the pid exits would delete a
successfully-finished, not-yet-summarized experiment out from under the
operator. So a dead-pid experiment dir is reapable only once it has ALSO
aged past ``_REAP_MIN_AGE_SECONDS`` (a day) — plenty of time to
``experiment status``/``summarize`` it first. A live pid is never touched,
same as background.

Allow-list: exactly ``sloth`` (this module is the sanctioned subprocess
consumer for the experiment noun — see ``tests/test_boundary.py``). No
socket, no daemon, no import of unsloth-cli/torch/unsloth — the CLI is
operator-installed and launched as a subprocess, never imported as Python.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess  # nosec B404 - launching operator CLI is the point (trusted env, D2)
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from colleague import memory as memory_mod
from colleague.identity import identity_env, resolve_identity

EXPERIMENTS_DIR_NAME = "experiments"
ALLOWED_CLI = "sloth"
START_FILENAME = "start.json"
TRAIN_LOG_FILENAME = "train.log"

#: Per-call timeouts (seconds) for the SHORT, synchronous sloth invocations —
#: not the detached ``sloth train`` child, which is never waited on.
_VALIDATE_TIMEOUT = 60
_SUMMARIZE_TIMEOUT = 60
_STATUS_TIMEOUT = 30

#: A dead-pid experiment dir must ALSO be at least this old before
#: `reap_experiments` removes it (see the module docstring for why this is
#: stricter than `colleague/background.py`'s immediate-on-death reap).
_REAP_MIN_AGE_SECONDS = 24 * 60 * 60

#: How many trailing lines of train.log to surface in a status query.
_LOG_TAIL_LINES = 20


class ExperimentError(Exception):
    """A structured error the CLI layer converts into a :class:`colleague.cli._errors.CliError`.

    Carries the same ``{message, remediation, code}`` shape as sloth's own
    ``CliError`` (unsloth-cli/sloth/cli/_errors.py) — a deliberate echo of the
    integration's own exit-code policy (1 = user-input error, 2 = environment/
    setup error) — so ``colleague/cli/_commands/experiment.py`` can convert
    every failure with ONE ``except`` clause instead of a subclass hierarchy.
    """

    def __init__(self, message: str, *, remediation: str = "", code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.remediation = remediation
        self.code = code


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def experiments_root(repo_path: str | Path) -> Path:
    """``<repo_path>/.colleague/experiments/`` — the parent of every experiment's dir."""
    return Path(repo_path) / ".colleague" / EXPERIMENTS_DIR_NAME


def _validate_exp_id(exp_id: str) -> str:
    """Reject an experiment id that is not a single safe path segment (guards
    ``status``/``summarize`` against path traversal). Minted ids
    (:func:`new_experiment_id`) and ordinary dir names always pass."""
    if (
        not isinstance(exp_id, str)
        or not exp_id
        or exp_id in (".", "..")
        or "/" in exp_id
        or "\\" in exp_id
        or "\x00" in exp_id
    ):
        raise ExperimentError(
            f"invalid experiment id: {exp_id!r}",
            remediation="an experiment id is a single path segment (no '/', '..', or leading '/')",
            code=1,
        )
    return exp_id


def experiment_dir(repo_path: str | Path, exp_id: str) -> Path:
    """``<repo_path>/.colleague/experiments/<exp_id>/`` — one experiment's directory."""
    return experiments_root(repo_path) / _validate_exp_id(exp_id)


def relative_log_dir(exp_id: str) -> str:
    """The repo-relative, POSIX-style directory string for the start payload."""
    return (Path(".colleague") / EXPERIMENTS_DIR_NAME / exp_id).as_posix() + "/"


def new_experiment_id() -> str:
    """Mint a short, filesystem-safe, unique experiment id: ``<timestamp>-<hash>``."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    salt = uuid.uuid4().hex[:8]
    return f"{ts}-{salt}"


# ---------------------------------------------------------------------------
# ExperimentHandle — the start payload
# ---------------------------------------------------------------------------


@dataclass
class ExperimentHandle:
    """The parent-side record of a detached ``sloth train`` child.

    ``to_dict()`` is exactly ``{id, pid, config, output_dir, log_dir,
    started}`` — the machine-readable start payload — plus an OPTIONAL
    ``runs_root`` key, present only when the caller passed an explicit
    override to :func:`start_experiment` (the common case stays exactly the
    six-key shape).
    """

    id: str
    pid: int
    config: str
    output_dir: str
    log_dir: str
    started: str
    runs_root: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "pid": self.pid,
            "config": self.config,
            "output_dir": self.output_dir,
            "log_dir": self.log_dir,
            "started": self.started,
        }
        if self.runs_root is not None:
            d["runs_root"] = self.runs_root
        return d


# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _pid_alive(pid: object) -> bool:
    """True if *pid* refers to a process this host can still see.

    Mirrors ``colleague/background.py``'s ``_pid_alive`` / ``colleague/rig.py``'s
    / ``colleague/worktrees.py``'s own copies — duplicated locally (the
    established per-module convention here) rather than importing a private
    helper across modules. ``os.kill(pid, 0)`` sends no signal, only probes
    existence/permission.
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


def _require_sloth() -> None:
    """Raise a clean, remediated :class:`ExperimentError` if ``sloth`` is absent."""
    if shutil.which(ALLOWED_CLI) is None:
        raise ExperimentError(
            "sloth CLI not found — is unsloth-cli installed and on PATH?",
            remediation="uv tool install unsloth-cli",
            code=2,
        )


def _sloth_env(repo_path: str | Path) -> dict[str, str]:
    """The child env: the caller's environment plus the resolved identity."""
    root = Path(repo_path).resolve()
    identity = resolve_identity(root)
    return {**os.environ, **identity_env(identity)}


def _parse_sloth_error(stderr_text: str) -> tuple[str, str]:
    """Best-effort ``(message, remediation)`` from a failed sloth ``--json`` call.

    sloth's own ``emit_error`` (unsloth-cli/sloth/cli/_output.py) writes
    ``json.dumps(err.to_dict())`` to STDERR under ``--json`` — the LAST line is
    the structured payload. Falls back to the raw (truncated) stderr text when
    it cannot be parsed, mirroring ``colleague/coherence.py``'s
    ``_parse_cli_error``.
    """
    try:
        payload = json.loads(stderr_text.strip().splitlines()[-1])
        if isinstance(payload, dict):
            message = payload.get("message")
            remediation = payload.get("remediation", "")
            if isinstance(message, str) and message:
                return message, remediation if isinstance(remediation, str) else ""
    except (ValueError, IndexError, AttributeError):
        pass
    text = stderr_text.strip()[:500]
    return (text or "sloth exited non-zero with no error output"), ""


def _parse_run_toml(config_path: Path) -> dict[str, Any]:
    """Read the ``[run]`` table's ``dataset``/``output`` (+ optional
    ``model``/``method``) out of *config_path* — pure stdlib ``tomllib``,
    never ``sloth.tune.config`` (colleague imports no unsloth-cli code)."""
    try:
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except OSError as exc:
        raise ExperimentError(f"cannot read config file: {config_path}: {exc}", code=2) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ExperimentError(
            f"config file is not valid TOML: {config_path}: {exc}", code=1
        ) from exc

    run_section = raw.get("run") if isinstance(raw, dict) else None
    if not isinstance(run_section, dict):
        raise ExperimentError(
            f"missing [run] section in {config_path}",
            remediation="see 'sloth config init' for a starting run.toml",
            code=1,
        )

    out: dict[str, Any] = {}
    for key in ("dataset", "output"):
        value = run_section.get(key)
        if not isinstance(value, str) or not value:
            raise ExperimentError(
                f"missing required key '{key}' in [run] section of {config_path}",
                remediation="see 'sloth config init' for a starting run.toml",
                code=1,
            )
        out[key] = value
    out["model"] = run_section.get("model")
    out["method"] = run_section.get("method")
    return out


def _resolve_output_path(repo_path: str | Path, output_dir: str) -> Path:
    """Resolve a (possibly relative) ``output`` value against *repo_path*.

    Mirrors sloth's OWN resolution (``sloth/cli/_commands/train.py``'s
    ``_resolve_container_invocation``: relative paths resolve against
    ``Path.cwd()`` at the point ``sloth train``/``validate`` is invoked) — every
    sloth subprocess this module launches runs with ``cwd=repo_path``, so this
    stays in agreement.
    """
    path = Path(output_dir)
    return path if path.is_absolute() else Path(repo_path) / path


def _resolve_runs_root(repo_path: str | Path, payload: dict[str, Any]) -> Path:
    """The registry root for a recorded experiment: an explicit override, else
    the ``output_dir``'s parent (``sloth.tune.registry.runs_root_for``)."""
    override = payload.get("runs_root")
    if override:
        p = Path(override)
        return p if p.is_absolute() else Path(repo_path) / p
    output_dir = payload.get("output_dir") or ""
    return _resolve_output_path(repo_path, output_dir).parent


def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else []


def _run_sloth_json(
    args: list[str], *, cwd: str | Path, env: dict[str, str], timeout: float
) -> tuple[int, Any, str]:
    """Run ``sloth <args>``; return ``(returncode, parsed_stdout_or_None, stderr)``.

    Never raises for a non-zero exit or unparseable JSON — the caller decides
    what that means. Raises :class:`ExperimentError` only when the subprocess
    itself cannot be launched/times out (an environment error, code 2).
    """
    try:
        proc = subprocess.run(  # nosec B603 - allow-listed CLI, no shell, trusted env (D2)
            [ALLOWED_CLI, *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ExperimentError(f"sloth {' '.join(args)} failed to launch: {exc}", code=2) from exc

    parsed: Any = None
    if proc.stdout:
        try:
            parsed = json.loads(proc.stdout)
        except ValueError:
            parsed = None
    return proc.returncode, parsed, proc.stderr or ""


# ---------------------------------------------------------------------------
# start_experiment
# ---------------------------------------------------------------------------


def start_experiment(
    repo_path: str | Path,
    config_toml: str | Path,
    runs_root: str | Path | None = None,
) -> ExperimentHandle:
    """Validate, then detach a ``sloth train`` run; return its :class:`ExperimentHandle`.

    1. **Validate first** — ``sloth validate --dataset <dataset> --json``
       (dataset/output read from the config's own ``[run]`` table) — mirrors
       ``sloth train``'s own "validate before spending GPU" preflight. A
       validation failure raises :class:`ExperimentError` (code 1) with the
       validator's own message; nothing is launched.
    2. **Detach** — ``sloth train --config <toml>``, exactly the
       ``colleague/background.py`` way: ``subprocess.Popen(...,
       start_new_session=True)``, stdio redirected to
       ``.colleague/experiments/<id>/train.log``, stdin ``DEVNULL``. This
       function returns as soon as the child is launched — it never waits,
       polls, or supervises it.
    3. **Write ``start.json``** — the machine-readable payload
       ``{id, pid, config, output_dir, log_dir, started}``.

    *runs_root* is an optional override recorded alongside the payload (only
    when given) for later ``experiment_status``/``summarize_experiment``
    registry lookups — sloth itself always derives the registry root as the
    ``output`` dir's parent, so this is a rarely-needed escape hatch, not a
    parameter sloth's own CLI accepts.
    """
    _require_sloth()
    repo = Path(repo_path)

    config_path = Path(config_toml)
    config_path = (
        config_path.resolve() if config_path.is_absolute() else (repo / config_path).resolve()
    )
    if not config_path.is_file():
        raise ExperimentError(
            f"config file not found: {config_path}",
            remediation="pass an existing run.toml (see 'sloth config init')",
            code=1,
        )

    run_section = _parse_run_toml(config_path)
    dataset = run_section["dataset"]
    output = run_section["output"]

    env = _sloth_env(repo)

    # 1) validate first — before any GPU work.
    returncode, _parsed, stderr = _run_sloth_json(
        ["validate", "--dataset", dataset, "--json"],
        cwd=repo,
        env=env,
        timeout=_VALIDATE_TIMEOUT,
    )
    if returncode != 0:
        message, remediation = _parse_sloth_error(stderr)
        raise ExperimentError(
            f"dataset validation failed: {message}", remediation=remediation, code=1
        )

    # 2) detach `sloth train --config <toml>` — exactly the background.py way.
    exp_id = new_experiment_id()
    edir = experiment_dir(repo, exp_id)
    edir.mkdir(parents=True, exist_ok=True)
    log_path = edir / TRAIN_LOG_FILENAME

    train_argv = [ALLOWED_CLI, "train", "--config", str(config_path), "--json"]
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(  # nosec B603 - allow-listed CLI, no shell, trusted env (D2)
            train_argv,
            cwd=str(repo),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )

    started = _now_iso()
    handle = ExperimentHandle(
        id=exp_id,
        pid=proc.pid,
        config=str(config_path),
        output_dir=output,
        log_dir=relative_log_dir(exp_id),
        started=started,
        runs_root=str(runs_root) if runs_root is not None else None,
    )
    (edir / START_FILENAME).write_text(json.dumps(handle.to_dict()), encoding="utf-8")
    return handle


# ---------------------------------------------------------------------------
# experiment_status / list_experiments
# ---------------------------------------------------------------------------


def _load_start_payload(repo_path: str | Path, exp_id: str) -> dict[str, Any]:
    start_path = experiment_dir(repo_path, exp_id) / START_FILENAME
    if not start_path.is_file():
        raise ExperimentError(
            f"no such experiment: {exp_id!r}",
            remediation=f"list known ids with: colleague experiment list --repo {repo_path}",
            code=1,
        )
    try:
        data = json.loads(start_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExperimentError(
            f"experiment {exp_id!r} start.json is unreadable: {exc}", code=2
        ) from exc
    if not isinstance(data, dict):
        raise ExperimentError(f"experiment {exp_id!r} start.json is malformed", code=2)
    return data


def _lookup_sloth_run(repo_path: str | Path, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Best-effort correlation against sloth's own run registry.

    Degrades to ``None`` (never raises) when sloth is unreachable, the
    registry doesn't exist yet (training hasn't reached the point of
    registering), or nothing matches this experiment's ``output_dir`` — a
    status query must always be answerable from local state alone.
    """
    if shutil.which(ALLOWED_CLI) is None:
        return None
    output_dir = payload.get("output_dir")
    if not output_dir:
        return None

    runs_root = _resolve_runs_root(repo_path, payload)
    env = _sloth_env(repo_path)

    try:
        returncode, records, _stderr = _run_sloth_json(
            ["runs", "list", "--runs-root", str(runs_root), "--json"],
            cwd=repo_path,
            env=env,
            timeout=_STATUS_TIMEOUT,
        )
    except ExperimentError:
        return None
    if returncode != 0 or not isinstance(records, list):
        return None

    matches = [r for r in records if isinstance(r, dict) and r.get("output_dir") == output_dir]
    if not matches:
        return None
    matches.sort(key=lambda r: str(r.get("started", "")))
    latest = matches[-1]
    run_id = latest.get("run_id")
    if not run_id:
        return latest

    try:
        returncode, record, _stderr = _run_sloth_json(
            ["runs", "show", str(run_id), "--runs-root", str(runs_root), "--json"],
            cwd=repo_path,
            env=env,
            timeout=_STATUS_TIMEOUT,
        )
    except ExperimentError:
        return latest
    if returncode != 0 or not isinstance(record, dict):
        return latest
    return record


def experiment_status(repo_path: str | Path, exp_id: str) -> dict[str, Any]:
    """Query a detached experiment's live status.

    Returns ``{id, pid, alive, log_tail, sloth_run, started}`` — ``alive`` is
    a fresh ``os.kill(pid, 0)`` probe (never trusts a stale flag), ``log_tail``
    is the last ~20 lines of ``train.log``, and ``sloth_run`` is the best-effort
    registry correlation (``None`` when unreachable/not-yet-registered).
    """
    payload = _load_start_payload(repo_path, exp_id)
    pid = payload.get("pid")
    alive = _pid_alive(pid)
    log_path = experiment_dir(repo_path, exp_id) / TRAIN_LOG_FILENAME
    return {
        "id": exp_id,
        "pid": pid,
        "alive": alive,
        "log_tail": _tail_lines(log_path, _LOG_TAIL_LINES),
        "sloth_run": _lookup_sloth_run(repo_path, payload),
        "started": payload.get("started"),
    }


def list_experiments(repo_path: str | Path) -> list[dict[str, Any]]:
    """Every ``.colleague/experiments/*/start.json`` payload, newest-first.

    Each entry carries its own ``alive`` (a fresh pid probe). A corrupt/
    unreadable payload is skipped, never a crash. A missing root dir returns
    ``[]``.
    """
    root = experiments_root(repo_path)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        start_path = d / START_FILENAME
        if not start_path.is_file():
            continue
        try:
            payload = json.loads(start_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        entry = dict(payload)
        entry["alive"] = _pid_alive(payload.get("pid"))
        out.append(entry)
    out.sort(key=lambda p: str(p.get("started", "")), reverse=True)
    return out


# ---------------------------------------------------------------------------
# summarize_experiment
# ---------------------------------------------------------------------------


def _build_experiment_record(exp_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    """Shape one experiment summary as an eidetic record (id/type/text/metadata).

    Idempotent by construction (the id is derived from exp_id, so a re-remember
    upserts in place — eidetic dedups by id), mirroring
    :func:`colleague.memory.build_lesson_record`.
    """
    metadata = summary.get("metadata") or {}
    training = summary.get("training") or {}
    dataset = metadata.get("dataset") or {}
    model = metadata.get("model")
    method = metadata.get("method")
    dataset_sha = dataset.get("sha256")
    final_loss = training.get("final_loss")
    adapter_path = summary.get("output_dir")

    parts = [f"experiment {exp_id}"]
    if model:
        parts.append(f"model={model}")
    if method:
        parts.append(f"method={method}")
    if dataset_sha:
        parts.append(f"dataset_sha={dataset_sha[:12]}")
    if final_loss is not None:
        parts.append(f"final_loss={final_loss}")
    if adapter_path:
        parts.append(f"adapter={adapter_path}")

    return {
        "id": f"experiment-{exp_id}",
        "type": "note",
        "text": " ".join(parts),
        "metadata": {
            "exp_id": exp_id,
            "output_dir": adapter_path,
            "model": model,
            "method": method,
            "dataset_sha256": dataset_sha,
            "final_loss": final_loss,
        },
    }


def summarize_experiment(
    repo_path: str | Path, exp_id: str, remember: bool = False
) -> dict[str, Any]:
    """``sloth summarize <output_dir> --json`` for a recorded experiment.

    Returns sloth's own summary shape (``output_dir``/``metadata``/``training``/
    ``notes``) plus one added key, ``remembered`` (bool). With ``remember=True``
    a compact record is upserted into eidetic via
    :func:`colleague.memory.remember` (reused as-is — never re-implemented —
    so the memory scope convention, ``tests/test_memory_convention.py``, can
    never drift between this module and the runtime's own recall/remember
    calls); when the ``eidetic`` CLI is absent this degrades to
    ``remembered: False``, never an error.
    """
    _require_sloth()
    payload = _load_start_payload(repo_path, exp_id)
    output_dir = payload.get("output_dir") or ""
    output_path = _resolve_output_path(repo_path, output_dir)
    env = _sloth_env(repo_path)

    returncode, summary, stderr = _run_sloth_json(
        ["summarize", str(output_path), "--json"],
        cwd=repo_path,
        env=env,
        timeout=_SUMMARIZE_TIMEOUT,
    )
    if returncode != 0:
        message, remediation = _parse_sloth_error(stderr)
        raise ExperimentError(f"sloth summarize failed: {message}", remediation=remediation, code=1)
    if not isinstance(summary, dict):
        raise ExperimentError("sloth summarize emitted an unparseable/non-object payload", code=2)

    remembered = False
    if remember:
        record = _build_experiment_record(exp_id, summary)
        remembered = memory_mod.remember(repo_path, record)

    result = dict(summary)
    result["remembered"] = remembered
    return result


# ---------------------------------------------------------------------------
# reap_experiments — consumed by `colleague clean`
# ---------------------------------------------------------------------------


def _classify_reap_dir(
    d: Path, now: float, min_age_seconds: float, dry_run: bool
) -> Optional[dict[str, Any]]:
    """Classify one experiment dir for reaping.

    Returns the ``{"experiment": <id>, "action": ...}`` result to record, or
    ``None`` to skip silently (a live pid, or a dead-but-too-recent one —
    :func:`reap_experiments`'s own ``continue`` cases).
    """
    start_path = d / START_FILENAME
    if not start_path.is_file():
        return None
    try:
        payload = json.loads(start_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # No readable liveness signal: a child may still be alive behind
        # a corrupt/missing payload — NEVER delete (PR #267 precedent).
        return {"experiment": d.name, "action": "kept-unknown"}
    pid = payload.get("pid")
    if not isinstance(pid, int):
        return {"experiment": d.name, "action": "kept-unknown"}
    if _pid_alive(pid):
        return None  # a live holder -> never reap a run still in progress

    try:
        age = now - start_path.stat().st_mtime
    except OSError:
        return {"experiment": d.name, "action": "kept-unknown"}
    if age < min_age_seconds:
        return None  # dead, but recent -> give the operator time to summarize

    if dry_run:
        return {"experiment": d.name, "action": "would-reap"}
    try:
        shutil.rmtree(d)
        return {"experiment": d.name, "action": "reaped"}
    except OSError:
        return {"experiment": d.name, "action": "failed"}


def reap_experiments(
    repo_path: str | Path,
    *,
    dry_run: bool = False,
    min_age_seconds: float = _REAP_MIN_AGE_SECONDS,
) -> list[dict[str, Any]]:
    """Reap a dead-pid experiment dir once it has ALSO aged past *min_age_seconds*.

    See the module docstring for why this is stricter than
    :func:`colleague.background.reap_background` (a background work item's
    result lives in a separate artifact; an experiment's start payload + log
    ARE the result). Never touches a dir whose pid is still alive, mirroring
    the flight/artifact/background reap conventions.

    Returns one ``{"experiment": <id>, "action": ...}`` dict per affected
    dir; ``action`` is ``reaped`` / ``would-reap`` (dry-run) / ``kept-unknown``
    (no readable pid signal — never delete what might still be running) /
    ``failed``. A missing root dir is a no-op (``[]``).
    """
    root = experiments_root(repo_path)
    results: list[dict[str, Any]] = []
    if not root.is_dir():
        return results

    now = time.time()
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        entry = _classify_reap_dir(d, now, min_age_seconds, dry_run)
        if entry is not None:
            results.append(entry)
    return results

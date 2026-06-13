"""File-based flight-control-plane primitives."""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

FLIGHT_DIR_NAME = "flight"
DEPTH_ENV = "COLLEAGUE_FLIGHT_DEPTH"
DEFAULT_DEPTH_CAP = 2
# A flight whose files were touched within this window is treated as *likely
# active* and preserved by reaping (no daemon/process registry exists, so this
# mtime heuristic is the honest signal). Generous on purpose: a running flight
# writes a feed record every turn, far more often than this, while crashed
# residue sits untouched — so an active flight is never reaped and stale residue
# still is. Flight files are gitignored and never wedge ``git fetch``, so a
# conservative delay on reaping them is harmless.
ACTIVE_WINDOW_SECONDS = 900


def is_safe_task_id(task_id) -> bool:
    """True if *task_id* is a single safe path segment (no traversal/escape).

    The flight CLI accepts an operator/agent-supplied task id; interpolating one
    containing ``/``, ``..``, or an absolute path into a flight path would escape
    ``.colleague/flight/``. Runtime-generated ids are plain hex and always pass.
    """
    s = str(task_id)
    return bool(s) and s not in (".", "..") and s == Path(s).name


def flight_dir(repo_path):
    """Return <repo_path>/.colleague/flight/."""
    return Path(repo_path) / ".colleague" / FLIGHT_DIR_NAME


def _segment(task_id):
    """Validate *task_id* as a safe path segment or raise ``ValueError``."""
    if not is_safe_task_id(task_id):
        raise ValueError(f"unsafe flight task id: {task_id!r}")
    return str(task_id)


def feed_path(repo_path, task_id):
    """Return <flight_dir>/<task_id>.feed.jsonl (rejects an unsafe task id)."""
    return flight_dir(repo_path) / f"{_segment(task_id)}.feed.jsonl"


def control_path(repo_path, task_id):
    """Return <flight_dir>/<task_id>.control.json (rejects an unsafe task id)."""
    return flight_dir(repo_path) / f"{_segment(task_id)}.control.json"


@dataclass
class Control:
    stop: bool
    guidance: list[str]


@dataclass
class FlightSession:
    repo_path: Path
    task_id: str
    _cursor: int = field(default=0, init=False)

    def append_feed(
        self, step_index: int, tool: str | None, intent: str | None, stats: dict
    ) -> None:
        """Append exactly one JSONL line to the feed file."""
        record = {"step_index": step_index, "tool": tool, "intent": intent, "stats": stats}
        with open(feed_path(self.repo_path, self.task_id), "a") as f:
            f.write(json.dumps(record) + "\n")

    def read_control(self) -> Control:
        """Read control file; return guidance beyond cursor, advancing cursor."""
        cp = control_path(self.repo_path, self.task_id)
        if not cp.exists():
            return Control(stop=False, guidance=[])
        try:
            data = json.loads(cp.read_text())
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            return Control(stop=False, guidance=[])

        stop = data.get("stop", False)
        guidance = data.get("guidance", [])
        new_guidance = guidance[self._cursor :]
        self._cursor = len(guidance)
        return Control(stop=stop, guidance=new_guidance)

    def reap(self) -> None:
        """Delete this flight's feed and control files if present."""
        fp = feed_path(self.repo_path, self.task_id)
        cp = control_path(self.repo_path, self.task_id)
        for p in (fp, cp):
            if p.exists():
                p.unlink()


def arm(repo_path, task_id):
    """Create the flight dir, truncate an empty feed file, return FlightSession."""
    repo_path = Path(repo_path)
    fd = flight_dir(repo_path)
    fd.mkdir(parents=True, exist_ok=True)
    fp = feed_path(repo_path, task_id)
    fp.write_text("")
    return FlightSession(repo_path=repo_path, task_id=task_id)


def write_stop(repo_path, task_id):
    """Set stop=true in the control file, preserving existing guidance."""
    repo_path = Path(repo_path)
    cp = control_path(repo_path, task_id)
    cp.parent.mkdir(parents=True, exist_ok=True)
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            data = {}
    else:
        data = {}
    data["stop"] = True
    if "guidance" not in data:
        data["guidance"] = []
    cp.write_text(json.dumps(data))


def append_guidance(repo_path, task_id, message: str):
    """Append message to the control file's guidance list, preserving stop."""
    repo_path = Path(repo_path)
    cp = control_path(repo_path, task_id)
    cp.parent.mkdir(parents=True, exist_ok=True)
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            data = {}
    else:
        data = {}
    if "guidance" not in data:
        data["guidance"] = []
    if "stop" not in data:
        data["stop"] = False
    data["guidance"].append(message)
    cp.write_text(json.dumps(data))


def _task_id_of(path: Path) -> str:
    """Extract the task id from a flight file name (<task_id>.feed.jsonl / .control.json).

    ``Path.stem`` strips only the final suffix (``a.feed.jsonl`` -> ``a.feed``), so
    we strip the known double-suffix explicitly and fall back to the first dot-token.
    """
    name = path.name
    for suffix in (".feed.jsonl", ".control.json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name.split(".", 1)[0]


def list_flight_files(repo_path):
    """Return every regular file directly under the flight dir; [] if absent."""
    repo_path = Path(repo_path)
    fd = flight_dir(repo_path)
    if not fd.is_dir():
        return []
    return sorted(p for p in fd.iterdir() if p.is_file())


def recent_flight_task_ids(repo_path, within_seconds=ACTIVE_WINDOW_SECONDS):
    """Task ids whose flight files were modified within *within_seconds* (likely active).

    Used to keep ``reap_orphans`` from deleting the feed/control of a flight that is
    still running — there is no process registry (no daemon), so file mtime is the
    honest staleness signal.
    """
    now = time.time()
    ids = set()
    for f in list_flight_files(repo_path):
        try:
            if now - f.stat().st_mtime < within_seconds:
                ids.add(_task_id_of(f))
        except OSError:
            continue
    return ids


def reap_orphans(repo_path, active_task_ids=None, *, dry_run=False):
    """Reap flight files not belonging to an active task id; return the reaped paths.

    With ``dry_run`` the paths that WOULD be reaped are returned without deleting.
    Pass the result of :func:`recent_flight_task_ids` as *active_task_ids* to spare
    a currently-running flight (see ``colleague clean``).
    """
    repo_path = Path(repo_path)
    fd = flight_dir(repo_path)
    if not fd.is_dir():
        return []

    # Only regular files DIRECTLY under the flight dir — never recurse out of scope.
    all_files = [f for f in fd.iterdir() if f.is_file() and f.parent == fd]

    if active_task_ids is None:
        active_task_ids = set()

    reaped = []
    for f in all_files:
        if _task_id_of(f) not in active_task_ids:
            if not dry_run:
                f.unlink()
            reaped.append(f)

    return reaped


def current_depth():
    """Return int(os.environ.get(DEPTH_ENV, '0') or 0); 0 on parse error."""
    val = os.environ.get(DEPTH_ENV, "0")
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def depth_exceeded(cap: int = DEFAULT_DEPTH_CAP):
    """Return True if current_depth() >= cap."""
    return current_depth() >= cap


def child_depth_env():
    """Return {DEPTH_ENV: str(current_depth() + 1)}."""
    return {DEPTH_ENV: str(current_depth() + 1)}

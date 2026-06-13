"""File-based flight-control-plane primitives."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

FLIGHT_DIR_NAME = "flight"
DEPTH_ENV = "COLLEAGUE_FLIGHT_DEPTH"
DEFAULT_DEPTH_CAP = 2


def flight_dir(repo_path):
    """Return <repo_path>/.colleague/flight/."""
    return Path(repo_path) / ".colleague" / FLIGHT_DIR_NAME


def feed_path(repo_path, task_id):
    """Return <flight_dir>/<task_id>.feed.jsonl."""
    return flight_dir(repo_path) / f"{task_id}.feed.jsonl"


def control_path(repo_path, task_id):
    """Return <flight_dir>/<task_id>.control.json."""
    return flight_dir(repo_path) / f"{task_id}.control.json"


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
        except (json.JSONDecodeError, ValueError):
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
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
        except (json.JSONDecodeError, ValueError):
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
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
        except (json.JSONDecodeError, ValueError):
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


def reap_orphans(repo_path, active_task_ids=None):
    """Delete flight files not belonging to an active task id."""
    repo_path = Path(repo_path)
    fd = flight_dir(repo_path)
    if not fd.is_dir():
        return []

    # Only regular files DIRECTLY under the flight dir — never recurse out of scope.
    all_files = [f for f in fd.iterdir() if f.is_file() and f.parent == fd]

    if active_task_ids is None:
        active_task_ids = set()

    deleted = []
    for f in all_files:
        if _task_id_of(f) not in active_task_ids:
            f.unlink()
            deleted.append(f)

    return deleted


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

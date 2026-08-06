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


def chat_path(repo_path, task_id):
    """Return <flight_dir>/<task_id>.chat.jsonl (rejects an unsafe task id).

    The talk-lane chat log (senses live presence arc, task t5): one JSONL line per
    senses talk-lane exchange (an operator message + the senses answer + whether it
    was relayed into cortex). Written by the talk-lane clients (``colleague talk``
    and the session concurrent lane) and folded into ``TaskResult.senses`` at loop
    finish, so the operator's mid-run conversation is reconstructable from the
    artifact alone. A sibling of the feed/control files — gitignored, ephemeral,
    reaped with them.
    """
    return flight_dir(repo_path) / f"{_segment(task_id)}.chat.jsonl"


def append_chat(repo_path, task_id, record: dict) -> None:
    """Append exactly one JSONL line to the talk-lane chat log.

    Creates the flight dir on demand so a talk-lane client can record an exchange
    even before the loop first writes the feed. ``record`` is a plain dict (the
    talk-lane exchange shape, e.g. ``{message, answer, relay, relay_text, latency,
    degraded, at}``) — the caller owns the shape; this only serializes it.
    """
    cp = chat_path(repo_path, task_id)
    cp.parent.mkdir(parents=True, exist_ok=True)
    with open(cp, "a") as f:
        f.write(json.dumps(record) + "\n")


def read_chat(repo_path, task_id) -> list[dict]:
    """Return every talk-lane chat record in order; ``[]`` when absent.

    Malformed lines are skipped (never raise) — the same best-effort stance as
    ``read_control``. Absent file (no talk lane was used) reads back as ``[]``, so
    folding at finish is a strict no-op on a run with no live conversation.
    """
    cp = chat_path(repo_path, task_id)
    if not cp.exists():
        return []
    records: list[dict] = []
    for line in cp.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


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

    def _append_marker(self, kind: str, step_index: int, intent: str, extra: dict) -> None:
        """Append a distinct, filterable liveness marker to the feed (#308).

        A marker carries a ``type`` key (``"run-start"`` / ``"heartbeat"``) that a
        step record NEVER has, so a consumer that must count steps or replay
        step-only (``tui replay``/``snapshot``, which read the events sink, not
        this feed) can filter markers out by ``record.get("type")``. The marker
        still carries the common ``step_index``/``tool``/``intent``/``stats`` keys
        so an existing feed reader (``colleague talk`` grounding, ``flight
        status``) renders it as informative liveness — never a KeyError.
        """
        record = {
            "type": kind,
            "step_index": step_index,
            "tool": None,
            "intent": intent,
            "stats": {},
            "at": time.time(),
        }
        record.update(extra)
        with open(feed_path(self.repo_path, self.task_id), "a") as f:
            f.write(json.dumps(record) + "\n")

    def append_run_start(self, goal: str | None, max_steps: int, seat: str = "cortex") -> None:
        """Mark that the run began — a liveness signal BEFORE the first step (#308).

        A reasoning cortex can spend minutes on its first completion with no tool
        call, so the feed would otherwise be empty and ``colleague talk`` / senses
        could only answer "I don't know". This run-start marker lets senses say
        "<seat> started, working on <goal>" immediately.

        ``seat`` names the acting seat for this record (t2, change-content
        consumption lane spec, covers c9/h9): the default ``"cortex"`` renders
        the pre-t2 line byte-identically — the legacy two-tier floor a caller
        that never passes ``seat`` still gets. A caller passes ``"worker"``
        when three-tier execution resolved a worker seat as the acting
        bounded-tool-loop actor (``colleague.loop.run``'s ``seat`` parameter,
        threaded there from each engine's resolved ``config.worker``). This
        method only renders whatever label it is given — the resolution
        decision (which seat actually acted) lives at the call site, not here.
        The label rides both the human-readable ``intent`` text and a
        structured ``seat`` key on the record, so a consumer can match on
        either.
        """
        goal_txt = (goal or "").strip()
        intent = f"{seat} started" + (f": {goal_txt}" if goal_txt else "")
        intent += f" (0/{max_steps} steps)"
        self._append_marker(
            "run-start",
            step_index=0,
            intent=intent,
            extra={"goal": goal_txt or None, "max_steps": max_steps, "seat": seat},
        )

    def append_heartbeat(self, phase: str, elapsed: float, step_index: int, max_steps: int) -> None:
        """Emit a liveness heartbeat during a (possibly long) completion (#308).

        Fired from the loop's pre-completion phase notice (#206) so a long single
        turn shows "cortex is on its Nth analysis, ~Ns elapsed" on the pilot plane
        instead of going silent. A ``type="heartbeat"`` record — it NEVER advances
        the run's ``step_count`` (the #206 invariant) and is filtered out of the
        step-only ``tui replay``/``snapshot`` (which read a different sink).
        """
        intent = f"{phase} ({elapsed:.0f}s elapsed, step {step_index}/{max_steps})"
        self._append_marker(
            "heartbeat",
            step_index=step_index,
            intent=intent,
            extra={"phase": phase, "elapsed": round(elapsed, 3), "max_steps": max_steps},
        )

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
        """Delete this flight's feed, control, and chat files if present."""
        fp = feed_path(self.repo_path, self.task_id)
        cp = control_path(self.repo_path, self.task_id)
        chat = chat_path(self.repo_path, self.task_id)
        for p in (fp, cp, chat):
            if p.exists():
                p.unlink()


def arm(repo_path, task_id):
    """Create the flight dir, truncate an empty feed file, return FlightSession."""
    from colleague.artifact import ensure_self_ignored

    repo_path = Path(repo_path)
    fd = flight_dir(repo_path)
    fd.mkdir(parents=True, exist_ok=True)
    ensure_self_ignored(fd.parent)
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


def transition_announcement(prior_task_id, episode_index: int, cap: int) -> str:
    """The pilot-facing episode-transition line, in its exact canonical form (t6).

    ``episode <N+1> of <cap>: continuing <prior-id>`` — the ONE form both the
    progress-sink announcement and the feed marker's ``intent`` carry, so a
    pilot reads the same words wherever the hop surfaces. A non-positive cap
    (``0`` = unlimited, decision c21) reads ``unlimited``.
    """
    cap_label = "unlimited" if cap <= 0 else str(cap)
    return f"episode {episode_index} of {cap_label}: continuing {prior_task_id}"


def append_episode_transition(
    repo_path, prior_task_id, *, next_task_id, episode_index: int, cap: int
) -> None:
    """Append a ``type="episode-transition"`` marker to the PRIOR episode's feed (t6).

    Written by the chain driver on starting episode N+1, onto the JUST-FINISHED
    episode's feed, recording ``{next_task_id, episode_index, cap}`` — so a
    pilot tailing episode 1's feed can follow the chain hop by hop (the loop
    reaps each episode's live plane at finish, so this append recreates the
    feed file with the marker as its only record). Carries the common marker
    keys (``step_index``/``tool``/``intent``/``stats`` — the #308 convention,
    ``step_index`` ``0`` like ``run-start``: the prior run is over) so an
    existing feed reader renders it as informative liveness, never a KeyError;
    ``intent`` IS :func:`transition_announcement`'s exact text.

    Best-effort: an unwritable flight dir/file (``OSError``) — and an unsafe
    ``task_id`` (:func:`feed_path`'s ``ValueError`` guard) — are swallowed: a
    marker must never crash the chain (the module's degrade convention; the
    path build lives INSIDE the try for exactly that reason — Qodo, PR #333).
    """
    record = {
        "type": "episode-transition",
        "step_index": 0,
        "tool": None,
        "intent": transition_announcement(prior_task_id, episode_index, cap),
        "stats": {},
        "at": time.time(),
        "next_task_id": str(next_task_id),
        "episode_index": episode_index,
        "cap": cap,
    }
    try:
        fp = feed_path(repo_path, prior_task_id)
        fp.parent.mkdir(parents=True, exist_ok=True)
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except (OSError, ValueError):
        return


def read_stop(repo_path, task_id) -> bool:
    """True when *task_id*'s control file requests a cooperative stop (t6).

    A pure PEEK for the chain driver's between-episode boundary check: unlike
    :meth:`FlightSession.read_control` it holds no guidance cursor and consumes
    nothing. Absent file, malformed JSON, or an unreadable path all read as
    ``False`` (the module's degrade convention — never raise, never block).
    """
    try:
        cp = control_path(repo_path, task_id)
        data = json.loads(cp.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # absent/unreadable/unsafe path, malformed JSON
        return False
    return bool(data.get("stop", False)) if isinstance(data, dict) else False


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

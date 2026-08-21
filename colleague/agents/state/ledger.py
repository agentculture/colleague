"""Append-only task ledger + replay-derived snapshot for model-bound agents (#411, t4).

Pure stdlib. No subprocess, no threads, no network — the only I/O is an
append to one JSONL file under an advisory ``fcntl`` lock (guarded import,
the :mod:`colleague.worktrees` pattern: a non-POSIX host degrades to an
unlocked append + a recorded warning, never a crash).

The task ledger is the durable truth of ONE task: what the operator asked
(verbatim ref), the constraints and acceptance it carries, the plan, the
decisions, the open loops, the working set, the changed paths, the
verification, the messages, the delegations, and the invocations that
re-entered it. Everything else (the evaluation ledger of
:mod:`colleague.ledger`, the config_events stream of
:mod:`colleague.configevents`) is a REFERENCED stream — a ``snapshot``
event may carry those streams' digests, never their content.

Design invariants
------------------
- **Append-only, no rewrite path.** :class:`TaskLedger` exposes ``append``
  (+ ``snapshot``, which is itself an append) and readers. The file is only
  ever opened in append mode; nothing here truncates, edits, or removes.
- **seq is ledger-owned.** ``append`` derives the next ``seq`` from the file
  tail UNDER the lock; a caller never supplies one.
- **Closed vocabulary.** ``kind`` must be one of :data:`EVENT_KINDS`.
- **Refs, not payloads.** An event carries refs to evidence (an artifact
  step index, a file path, a message id) — a line over
  :data:`MAX_EVENT_BYTES` is refused.
- **Replay-deterministic.** :func:`derive_snapshot` is a pure function of
  the seq-ordered event sequence; :func:`task_ledger_digest` reuses
  :func:`colleague.ledger.ledger_digest`'s sha256-over-the-replayed-sequence
  idea.
- **Fail-closed reader.** :func:`read_ledger` refuses an unknown schema
  version, a torn/non-JSON tail, a seq gap, or a recorded ``state_digest``
  that replay does not reproduce — always :class:`LedgerUnreadable`, never
  a partial snapshot.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

try:
    import fcntl  # POSIX-only; guarded so a non-POSIX host degrades, never crashes.
except ImportError:  # pragma: no cover - exercised only on a non-POSIX host
    fcntl = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Vocabulary + schema
# ---------------------------------------------------------------------------

#: The current on-disk schema version; the header line's ``version`` MUST
#: equal this exactly or :func:`read_ledger` refuses the whole file.
LEDGER_SCHEMA_VERSION = 1

#: The header line's schema tag (lets a reader tell a task ledger apart from
#: any other JSONL file before trusting its version).
LEDGER_SCHEMA_TAG = "colleague.task_ledger"

#: Every valid event ``kind``, in the fixed reading order. Closed.
EVENT_KINDS: tuple[str, ...] = (
    "operator_request",
    "operator_input",
    "constraint",
    "acceptance",
    "plan_node",
    "decision",
    "open_loop",
    "evidence",
    "working_set",
    "changed_path",
    "verification",
    "message",
    "delegate",
    "return",
    "invocation",
    "snapshot",
)

#: Hard cap on one serialized event line. Events carry refs, never payloads.
MAX_EVENT_BYTES = 4096

#: The authority-bearing keys an ``operator_request`` / ``decision`` event may
#: carry; exactly these (plus every constraint + acceptance event) feed
#: :func:`authority_digest`.
AUTHORITY_KEYS: tuple[str, ...] = ("approval_ref", "no_pr", "mode", "role", "thought_id")

_LEDGER_SUBDIR = Path(".colleague") / "ledger"


class LedgerUnreadable(Exception):
    """The ledger file cannot be trusted; ``reason`` says why. Never partial."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# LedgerEvent
# ---------------------------------------------------------------------------


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class LedgerEvent:
    """One appended line: ``kind`` (closed), ledger-owned ``seq``, the owning
    ``task_id``, and a small JSON-able ``data`` mapping of refs."""

    kind: str
    seq: int = 0
    task_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "seq": self.seq,
            "task_id": self.task_id,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LedgerEvent":
        data = raw.get("data", {})
        if not isinstance(data, Mapping):
            raise ValueError("event data must be a mapping")
        return cls(
            kind=str(raw.get("kind", "")),
            seq=int(raw.get("seq", 0) or 0),
            task_id=str(raw.get("task_id", "")),
            data=dict(data),
        )

    def canonical(self) -> str:
        """Deterministic encoding (sorted keys, no incidental whitespace)."""
        return _canonical(self.to_dict())


def task_ledger_digest(events: Sequence[LedgerEvent]) -> str:
    """sha256 over the REPLAYED event sequence alone — nothing ambient enters."""
    canonical_seq = "[" + ",".join(e.canonical() for e in events) + "]"
    return hashlib.sha256(canonical_seq.encode("utf-8")).hexdigest()


def authority_digest(events: Sequence[LedgerEvent]) -> str:
    """sha256 over the authority-bearing fields only: every constraint and
    acceptance event, plus the :data:`AUTHORITY_KEYS` an ``operator_request``
    or ``decision`` carries. A message/evidence/working_set event never moves
    it."""
    bearing: list[dict[str, Any]] = []
    for e in events:
        if e.kind in ("constraint", "acceptance"):
            bearing.append({"kind": e.kind, "seq": e.seq, "data": dict(e.data)})
        elif e.kind in ("operator_request", "decision"):
            picked = {k: e.data[k] for k in AUTHORITY_KEYS if k in e.data}
            if picked:
                bearing.append({"kind": e.kind, "seq": e.seq, "data": picked})
    return hashlib.sha256(_canonical(bearing).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# TaskSnapshot — derived purely by replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSnapshot:
    """The replay-derived state of one task. Every collection is a tuple of
    plain JSON dicts in first-seen seq order; equal events → equal snapshot."""

    task_id: str = ""
    original_request_ref: str = ""
    active_thought: str = ""
    constraints: tuple[dict[str, Any], ...] = ()
    acceptance: tuple[dict[str, Any], ...] = ()
    plan: tuple[dict[str, Any], ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    open_loops: tuple[dict[str, Any], ...] = ()
    working_set: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    verification: tuple[dict[str, Any], ...] = ()
    messages: tuple[dict[str, Any], ...] = ()
    delegations: tuple[dict[str, Any], ...] = ()
    episode: int = 0
    referenced_digests: dict[str, str] = field(default_factory=dict)
    authority_digest: str = ""
    state_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "original_request_ref": self.original_request_ref,
            "active_thought": self.active_thought,
            "constraints": [dict(x) for x in self.constraints],
            "acceptance": [dict(x) for x in self.acceptance],
            "plan": [dict(x) for x in self.plan],
            "decisions": [dict(x) for x in self.decisions],
            "open_loops": [dict(x) for x in self.open_loops],
            "working_set": list(self.working_set),
            "changed_paths": list(self.changed_paths),
            "verification": [dict(x) for x in self.verification],
            "messages": [dict(x) for x in self.messages],
            "delegations": [dict(x) for x in self.delegations],
            "episode": self.episode,
            "referenced_digests": dict(self.referenced_digests),
            "authority_digest": self.authority_digest,
            "state_digest": self.state_digest,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TaskSnapshot":
        def dicts(key: str) -> tuple[dict[str, Any], ...]:
            return tuple(dict(x) for x in raw.get(key, []) or [])

        return cls(
            task_id=str(raw.get("task_id", "")),
            original_request_ref=str(raw.get("original_request_ref", "")),
            active_thought=str(raw.get("active_thought", "")),
            constraints=dicts("constraints"),
            acceptance=dicts("acceptance"),
            plan=dicts("plan"),
            decisions=dicts("decisions"),
            open_loops=dicts("open_loops"),
            working_set=tuple(str(x) for x in raw.get("working_set", []) or []),
            changed_paths=tuple(str(x) for x in raw.get("changed_paths", []) or []),
            verification=dicts("verification"),
            messages=dicts("messages"),
            delegations=dicts("delegations"),
            episode=int(raw.get("episode", 0) or 0),
            referenced_digests={
                str(k): str(v) for k, v in (raw.get("referenced_digests") or {}).items()
            },
            authority_digest=str(raw.get("authority_digest", "")),
            state_digest=str(raw.get("state_digest", "")),
        )


def _ref_of(e: LedgerEvent) -> str:
    return str(e.data.get("ref") or f"seq:{e.seq}")


def _entry(e: LedgerEvent) -> dict[str, Any]:
    d = dict(e.data)
    d["seq"] = e.seq
    return d


def derive_snapshot(events: Sequence[LedgerEvent]) -> TaskSnapshot:
    """Replay ``events`` (sorted by ``seq``; equal seqs keep input order) into
    a :class:`TaskSnapshot`. Pure: same events → equal snapshot + digests.

    Replay rules: ``plan_node`` / ``open_loop`` / ``verification`` keyed by
    ``data["id"]`` (last wins, first-seen order; an open_loop whose latest
    ``status`` is ``closed`` drops out); ``working_set`` honours
    ``op: add|remove``; a ``delegate`` without a matching ``return`` (by
    ``id``) is ALSO an open loop; ``episode`` counts ``invocation`` events
    (or takes the latest one's explicit ``episode``); the latest ``snapshot``
    event's ``referenced_digests`` (evaluation ledger, config_events, ...)
    are carried, never their content.
    """
    ordered = sorted(events, key=lambda e: e.seq)
    task_id = ordered[0].task_id if ordered else ""
    request_ref = ""
    active_thought = ""
    constraints: list[dict[str, Any]] = []
    acceptance: list[dict[str, Any]] = []
    plan: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    loops: dict[str, dict[str, Any]] = {}
    working: dict[str, None] = {}
    changed: dict[str, None] = {}
    verification: dict[str, dict[str, Any]] = {}
    messages: list[dict[str, Any]] = []
    delegations: dict[str, dict[str, Any]] = {}
    episode = 0
    referenced: dict[str, str] = {}

    for e in ordered:
        d = e.data
        if "thought_id" in d and e.kind in (
            "operator_request",
            "operator_input",
            "decision",
            "plan_node",
        ):
            active_thought = str(d["thought_id"])
        if e.kind == "operator_request":
            if not request_ref:
                request_ref = _ref_of(e)
        elif e.kind == "constraint":
            constraints.append(_entry(e))
        elif e.kind == "acceptance":
            acceptance.append(_entry(e))
        elif e.kind == "plan_node":
            plan[str(d.get("id", e.seq))] = _entry(e)
        elif e.kind == "decision":
            decisions.append(_entry(e))
        elif e.kind == "open_loop":
            key = str(d.get("id", e.seq))
            if str(d.get("status", "open")) == "closed":
                loops.pop(key, None)
            else:
                loops[key] = _entry(e)
        elif e.kind == "working_set":
            path = str(d.get("path", d.get("ref", "")))
            if str(d.get("op", "add")) == "remove":
                working.pop(path, None)
            elif path:
                working[path] = None
        elif e.kind == "changed_path":
            path = str(d.get("path", ""))
            if path:
                changed[path] = None
        elif e.kind == "verification":
            verification[str(d.get("id", e.seq))] = _entry(e)
        elif e.kind == "message":
            messages.append(_entry(e))
        elif e.kind == "delegate":
            key = str(d.get("id", e.seq))
            delegations[key] = {
                "id": key,
                "child_ref": str(d.get("child_ref", "")),
                "seq": e.seq,
                "returned": False,
                "return_ref": "",
            }
        elif e.kind == "return":
            key = str(d.get("id", ""))
            if key in delegations:
                delegations[key] = dict(delegations[key], returned=True, return_ref=_ref_of(e))
        elif e.kind == "invocation":
            episode = int(d.get("episode", episode + 1) or 0)
        elif e.kind == "snapshot":
            ref = d.get("referenced_digests")
            if isinstance(ref, Mapping):
                referenced = {str(k): str(v) for k, v in ref.items()}

    open_loops = list(loops.values()) + [
        {"id": key, "kind": "delegate", "child_ref": v["child_ref"], "seq": v["seq"]}
        for key, v in delegations.items()
        if not v["returned"]
    ]
    return TaskSnapshot(
        task_id=task_id,
        original_request_ref=request_ref,
        active_thought=active_thought,
        constraints=tuple(constraints),
        acceptance=tuple(acceptance),
        plan=tuple(plan.values()),
        decisions=tuple(decisions),
        open_loops=tuple(open_loops),
        working_set=tuple(working),
        changed_paths=tuple(changed),
        verification=tuple(verification.values()),
        messages=tuple(messages),
        delegations=tuple(delegations.values()),
        episode=episode,
        referenced_digests=referenced,
        authority_digest=authority_digest(ordered),
        state_digest=task_ledger_digest(ordered),
    )


# ---------------------------------------------------------------------------
# Paths, header, reader
# ---------------------------------------------------------------------------


def ledger_path(repo_root: Union[str, Path], task_id: str) -> Path:
    """``<repo_root>/.colleague/ledger/<task_id>.jsonl``; refuses a task_id that
    would escape the directory."""
    tid = str(task_id)
    if not tid or "/" in tid or "\\" in tid or tid in (".", ".."):
        raise ValueError(f"invalid task_id for a ledger path: {task_id!r}")
    return Path(repo_root) / _LEDGER_SUBDIR / f"{tid}.jsonl"


def _header(task_id: str) -> str:
    return _canonical(
        {"schema": LEDGER_SCHEMA_TAG, "version": LEDGER_SCHEMA_VERSION, "task_id": task_id}
    )


def _parse_header(line: str) -> str:
    try:
        raw = json.loads(line)
    except ValueError as exc:
        raise LedgerUnreadable(f"header is not JSON: {exc}") from None
    if not isinstance(raw, Mapping) or raw.get("schema") != LEDGER_SCHEMA_TAG:
        raise LedgerUnreadable("missing task-ledger header line")
    version = raw.get("version")
    if version != LEDGER_SCHEMA_VERSION:
        raise LedgerUnreadable(
            f"unknown schema version {version!r} (this reader speaks {LEDGER_SCHEMA_VERSION})"
        )
    return str(raw.get("task_id", ""))


def _lines(text: str) -> list[str]:
    """Split a complete JSONL body; a final line without ``\\n`` is a torn tail."""
    if not text:
        return []
    if not text.endswith("\n"):
        raise LedgerUnreadable("torn tail: last line is not newline-terminated")
    return text.split("\n")[:-1]


@dataclass(frozen=True)
class LedgerRead:
    """A fully validated read: header task_id, the events, the derived snapshot."""

    task_id: str
    events: tuple[LedgerEvent, ...]
    snapshot: TaskSnapshot


def read_ledger(path: Union[str, Path]) -> LedgerRead:
    """Read + validate the whole file, then derive the snapshot. Any defect —
    missing file, bad/unknown header, non-JSON or torn tail, unknown kind,
    seq gap, task_id drift, a ``snapshot`` event whose recorded
    ``state_digest``/``authority_digest`` replay does not reproduce — raises
    :class:`LedgerUnreadable(reason)`. Never a partial result."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise LedgerUnreadable(f"cannot read {p}: {exc.strerror or exc}") from None
    except UnicodeDecodeError as exc:
        raise LedgerUnreadable(f"not UTF-8: {exc}") from None
    lines = _lines(text)
    if not lines:
        raise LedgerUnreadable("empty ledger (no header line)")
    task_id = _parse_header(lines[0])
    events: list[LedgerEvent] = []
    for lineno, line in enumerate(lines[1:], start=2):
        try:
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                raise ValueError("not an object")
            event = LedgerEvent.from_dict(raw)
        except ValueError as exc:
            raise LedgerUnreadable(f"torn/non-JSON line {lineno}: {exc}") from None
        if event.kind not in EVENT_KINDS:
            raise LedgerUnreadable(f"line {lineno}: unknown event kind {event.kind!r}")
        if event.seq != len(events):
            raise LedgerUnreadable(f"line {lineno}: seq {event.seq} (expected {len(events)})")
        if event.task_id != task_id:
            raise LedgerUnreadable(
                f"line {lineno}: task_id {event.task_id!r} != header {task_id!r}"
            )
        if event.kind == "snapshot":
            want_state = event.data.get("state_digest")
            if want_state is not None and want_state != task_ledger_digest(events):
                raise LedgerUnreadable(f"line {lineno}: state_digest mismatch on replay")
            want_auth = event.data.get("authority_digest")
            if want_auth is not None and want_auth != authority_digest(events):
                raise LedgerUnreadable(f"line {lineno}: authority_digest mismatch on replay")
        events.append(event)
    return LedgerRead(task_id=task_id, events=tuple(events), snapshot=derive_snapshot(events))


# ---------------------------------------------------------------------------
# TaskLedger — the append-only writer
# ---------------------------------------------------------------------------


class TaskLedger:
    """Append-only JSONL writer for one task. Opens the file in append mode
    only; every ``append`` takes an exclusive advisory ``fcntl`` lock on the
    file (degrading, on a host without ``fcntl``, to an unlocked append plus
    ONE recorded warning on :attr:`warnings`)."""

    def __init__(self, path: Union[str, Path], task_id: Optional[str] = None) -> None:
        self.path = Path(path)
        self.task_id = str(task_id) if task_id is not None else self.path.stem
        self.warnings: list[str] = []

    # -- locking ------------------------------------------------------------

    def _lock(self, handle: Any) -> bool:
        if fcntl is None:
            if not self.warnings:
                self.warnings.append(
                    "fcntl unavailable: task ledger append is unlocked on this host"
                )
            return False
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            self.warnings.append(f"fcntl lock failed ({exc}): task ledger append is unlocked")
            return False
        return True

    @staticmethod
    def _unlock(handle: Any) -> None:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - best-effort release
                pass

    # -- writing ------------------------------------------------------------

    def _next_seq(self, body: str) -> tuple[int, bool]:
        """(next seq, header needed) derived from the current file body."""
        lines = _lines(body)
        if not lines:
            return 0, True
        task_id = _parse_header(lines[0])
        if task_id != self.task_id:
            raise LedgerUnreadable(f"ledger belongs to task {task_id!r}, not {self.task_id!r}")
        if len(lines) == 1:
            return 0, False
        try:
            last = json.loads(lines[-1])
            return int(last["seq"]) + 1, False
        except (ValueError, KeyError, TypeError) as exc:
            raise LedgerUnreadable(f"torn/non-JSON tail: {exc}") from None

    def append(self, kind: str, data: Optional[Mapping[str, Any]] = None) -> LedgerEvent:
        """Append one event; returns it with its ledger-assigned ``seq``.

        ``ValueError`` for a kind outside :data:`EVENT_KINDS`, a non-mapping
        ``data``, or a line over :data:`MAX_EVENT_BYTES`;
        :class:`LedgerUnreadable` if the existing file is torn or foreign.
        """
        if kind not in EVENT_KINDS:
            raise ValueError(
                f"unknown task-ledger event kind: {kind!r} (expected one of {EVENT_KINDS})"
            )
        if data is not None and not isinstance(data, Mapping):
            raise ValueError("event data must be a mapping of refs")
        payload = dict(data or {})
        probe = LedgerEvent(kind=kind, seq=0, task_id=self.task_id, data=payload).canonical()
        if len(probe.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError(
                f"event exceeds {MAX_EVENT_BYTES} bytes — carry a ref to the evidence, "
                "not the payload"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+", encoding="utf-8") as handle:
            self._lock(handle)
            try:
                handle.seek(0)
                seq, need_header = self._next_seq(handle.read())
                event = LedgerEvent(kind=kind, seq=seq, task_id=self.task_id, data=payload)
                out = (
                    (_header(self.task_id) + "\n" if need_header else "") + event.canonical() + "\n"
                )
                handle.write(out)
                handle.flush()
            finally:
                self._unlock(handle)
        return event

    def snapshot(self, referenced_digests: Optional[Mapping[str, str]] = None) -> LedgerEvent:
        """Derive the current snapshot and append a ``snapshot`` event carrying
        its ``state_digest`` + ``authority_digest`` (what :func:`read_ledger`
        later re-verifies) and the REFERENCED streams' digests — e.g.
        ``{"evaluation_ledger": ..., "config_events": ...}`` — never their
        content."""
        snap = derive_snapshot(self.events())
        data: dict[str, Any] = {
            "state_digest": snap.state_digest,
            "authority_digest": snap.authority_digest,
        }
        if referenced_digests:
            data["referenced_digests"] = {str(k): str(v) for k, v in referenced_digests.items()}
        return self.append("snapshot", data)

    # -- reading ------------------------------------------------------------

    def read(self) -> LedgerRead:
        """:func:`read_ledger` over this ledger's path (fail-closed)."""
        return read_ledger(self.path)

    def events(self) -> tuple[LedgerEvent, ...]:
        """All events, or ``()`` when the file does not exist yet."""
        if not self.path.exists():
            return ()
        return self.read().events

    def derive(self) -> TaskSnapshot:
        """The replay-derived :class:`TaskSnapshot` of the current file."""
        return derive_snapshot(self.events())

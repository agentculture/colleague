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
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import fcntl  # POSIX-only; guarded so a non-POSIX host degrades, never crashes.
except ImportError:  # pragma: no cover - exercised only on a non-POSIX host
    fcntl = None  # type: ignore[assignment]

# --- Vocabulary + schema -------------------------------------------------------------------------

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


# --- LedgerEvent ---------------------------------------------------------------------------------


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


# --- TaskSnapshot — derived purely by replay -----------------------------------------------------


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
        """Plain JSON shape, field order: tuples → lists (entries copied),
        ``referenced_digests`` copied, scalars as-is."""
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, tuple):
                out[f.name] = [dict(x) if isinstance(x, dict) else x for x in value]
            else:
                out[f.name] = dict(value) if isinstance(value, dict) else value
        return out

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


#: Event kinds whose ``thought_id`` moves the active thought on replay.
_THOUGHT_KINDS = frozenset({"operator_request", "operator_input", "decision", "plan_node"})
#: The append family (kind → the snapshot list it extends), the keyed family
#: (kind → the collection keyed by ``data["id"]``) and the ``_on_<kind>`` kinds.
_APPEND_KINDS = {
    "constraint": "constraints",
    "acceptance": "acceptance",
    "decision": "decisions",
    "message": "messages",
}
_KEYED_KINDS = {"plan_node": "plan", "verification": "verification"}
_HANDLED_KINDS = ("operator_request", "open_loop", "working_set", "changed_path")
_HANDLED_KINDS += ("delegate", "return", "invocation", "snapshot")
_KEYED_FIELDS = ("plan", "working_set", "changed_paths", "verification", "delegations")


class _Replay:
    """Mutable replay state for :func:`derive_snapshot`; ``lists`` / ``keyed`` hold
    the snapshot's collections by field name (``working_set`` / ``changed_paths``
    are ordered sets: path → path).

    Replay rules: ``plan_node`` / ``open_loop`` / ``verification`` keyed by
    ``data["id"]`` (last wins, first-seen order; an open_loop whose latest
    ``status`` is ``closed`` drops out); ``working_set`` honours ``op: add|remove``;
    a ``delegate`` without a matching ``return`` (by ``id``) is ALSO an open loop;
    ``episode`` counts ``invocation`` events (or takes the latest one's explicit
    ``episode``); the latest ``snapshot`` event's ``referenced_digests``
    (evaluation ledger, config_events, ...) are carried, never their content;
    ``operator_input`` only moves the active thought, ``evidence`` moves nothing."""

    def __init__(self) -> None:
        self.request_ref = ""
        self.active_thought = ""
        self.episode = 0
        self.referenced: dict[str, str] = {}
        self.loops: dict[str, dict[str, Any]] = {}
        self.lists: dict[str, list[dict[str, Any]]] = {k: [] for k in _APPEND_KINDS.values()}
        self.keyed: dict[str, dict[str, Any]] = {k: {} for k in _KEYED_FIELDS}

    def feed(self, e: LedgerEvent) -> None:
        if "thought_id" in e.data and e.kind in _THOUGHT_KINDS:
            self.active_thought = str(e.data["thought_id"])
        if e.kind in _APPEND_KINDS:
            self.lists[_APPEND_KINDS[e.kind]].append(_entry(e))
        elif e.kind in _KEYED_KINDS:
            self.keyed[_KEYED_KINDS[e.kind]][str(e.data.get("id", e.seq))] = _entry(e)
        elif e.kind in _REPLAY_HANDLERS:
            _REPLAY_HANDLERS[e.kind](self, e)

    def _on_operator_request(self, e: LedgerEvent) -> None:
        if not self.request_ref:
            self.request_ref = _ref_of(e)

    def _on_open_loop(self, e: LedgerEvent) -> None:
        key = str(e.data.get("id", e.seq))
        if str(e.data.get("status", "open")) == "closed":
            self.loops.pop(key, None)
        else:
            self.loops[key] = _entry(e)

    def _on_working_set(self, e: LedgerEvent) -> None:
        path = str(e.data.get("path", e.data.get("ref", "")))
        if str(e.data.get("op", "add")) == "remove":
            self.keyed["working_set"].pop(path, None)
        elif path:
            self.keyed["working_set"][path] = path

    def _on_changed_path(self, e: LedgerEvent) -> None:
        path = str(e.data.get("path", ""))
        if path:
            self.keyed["changed_paths"][path] = path

    def _on_delegate(self, e: LedgerEvent) -> None:
        key = str(e.data.get("id", e.seq))
        child_ref = str(e.data.get("child_ref", ""))
        entry = {
            "id": key,
            "child_ref": child_ref,
            "seq": e.seq,
            "returned": False,
            "return_ref": "",
        }
        self.keyed["delegations"][key] = entry

    def _on_return(self, e: LedgerEvent) -> None:
        key = str(e.data.get("id", ""))
        delegations = self.keyed["delegations"]
        if key in delegations:
            delegations[key] = dict(delegations[key], returned=True, return_ref=_ref_of(e))

    def _on_invocation(self, e: LedgerEvent) -> None:
        self.episode = int(e.data.get("episode", self.episode + 1) or 0)

    def _on_snapshot(self, e: LedgerEvent) -> None:
        ref = e.data.get("referenced_digests")
        if isinstance(ref, Mapping):
            self.referenced = {str(k): str(v) for k, v in ref.items()}

    def open_loops(self) -> list[dict[str, Any]]:
        """Ledgered open loops + every delegation without a matching return."""
        return list(self.loops.values()) + [
            {"id": key, "kind": "delegate", "child_ref": v["child_ref"], "seq": v["seq"]}
            for key, v in self.keyed["delegations"].items()
            if not v["returned"]
        ]

    def to_snapshot(self, task_id: str, ordered: Sequence[LedgerEvent]) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=task_id,
            original_request_ref=self.request_ref,
            active_thought=self.active_thought,
            open_loops=tuple(self.open_loops()),
            episode=self.episode,
            referenced_digests=self.referenced,
            authority_digest=authority_digest(ordered),
            state_digest=task_ledger_digest(ordered),
            **{k: tuple(v) for k, v in self.lists.items()},
            **{k: tuple(v.values()) for k, v in self.keyed.items()},
        )


#: Replay dispatch for the kinds outside the append / keyed families.
_REPLAY_HANDLERS = {k: getattr(_Replay, f"_on_{k}") for k in _HANDLED_KINDS}


def derive_snapshot(events: Sequence[LedgerEvent]) -> TaskSnapshot:
    """Replay ``events`` (sorted by ``seq``; equal seqs keep input order) into
    a :class:`TaskSnapshot`. Pure: same events → equal snapshot + digests.
    The replay rules are documented on :class:`_Replay`."""
    ordered = sorted(events, key=lambda e: e.seq)
    state = _Replay()
    for e in ordered:
        state.feed(e)
    return state.to_snapshot(ordered[0].task_id if ordered else "", ordered)


# --- Paths, header, reader -----------------------------------------------------------------------


def ledger_path(repo_root: str | Path, task_id: str) -> Path:
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


def _event_at(lineno: int, line: str, task_id: str, prior: Sequence[LedgerEvent]) -> LedgerEvent:
    """Parse ONE body line and check it fail-closed against the header + prior events:
    JSON object, known kind, gap-free seq, no task_id drift, snapshot digests reproduce."""
    try:
        raw = json.loads(line)
        if not isinstance(raw, Mapping):
            raise ValueError("not an object")
        event = LedgerEvent.from_dict(raw)
    except ValueError as exc:
        raise LedgerUnreadable(f"torn/non-JSON line {lineno}: {exc}") from None
    if event.kind not in EVENT_KINDS:
        raise LedgerUnreadable(f"line {lineno}: unknown event kind {event.kind!r}")
    if event.seq != len(prior):
        raise LedgerUnreadable(f"line {lineno}: seq {event.seq} (expected {len(prior)})")
    if event.task_id != task_id:
        raise LedgerUnreadable(f"line {lineno}: task_id {event.task_id!r} != header {task_id!r}")
    if event.kind == "snapshot":
        want_state = event.data.get("state_digest")
        if want_state is not None and want_state != task_ledger_digest(prior):
            raise LedgerUnreadable(f"line {lineno}: state_digest mismatch on replay")
        want_auth = event.data.get("authority_digest")
        if want_auth is not None and want_auth != authority_digest(prior):
            raise LedgerUnreadable(f"line {lineno}: authority_digest mismatch on replay")
    return event


def read_ledger(path: str | Path) -> LedgerRead:
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
        events.append(_event_at(lineno, line, task_id, events))
    return LedgerRead(task_id=task_id, events=tuple(events), snapshot=derive_snapshot(events))


# --- TaskLedger — the append-only writer ---------------------------------------------------------


class TaskLedger:
    """Append-only JSONL writer for one task. Opens the file in append mode
    only; every ``append`` takes an exclusive advisory ``fcntl`` lock on the
    file (degrading, on a host without ``fcntl``, to an unlocked append plus
    ONE recorded warning on :attr:`warnings`)."""

    def __init__(self, path: str | Path, task_id: str | None = None) -> None:
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

    def append(self, kind: str, data: Mapping[str, Any] | None = None) -> LedgerEvent:
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
                header = _header(self.task_id) + "\n" if need_header else ""
                handle.write(header + event.canonical() + "\n")
                handle.flush()
            finally:
                self._unlock(handle)
        return event

    def snapshot(self, referenced_digests: Mapping[str, str] | None = None) -> LedgerEvent:
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

"""Tests for colleague.agents.state.ledger — the append-only task ledger (#411, t4).

Covers: closed EVENT_KINDS + ledger-owned seq + header-first + no rewrite
path; replay-deterministic derive_snapshot (property test over shuffled
inputs); locked append (N threads x M appends on a real tmp file) + the
non-POSIX degrade; the fail-closed reader (unknown version, torn/non-JSON
tail, state_digest mismatch); ledger_path; and the module's own boundary
(no subprocess / threading import, guarded fcntl import).
"""

from __future__ import annotations

import inspect
import json
import random
import re
import threading
from pathlib import Path

import pytest

from colleague.agents.state import ledger as ledger_mod
from colleague.agents.state.ledger import (
    EVENT_KINDS,
    LEDGER_SCHEMA_VERSION,
    MAX_EVENT_BYTES,
    LedgerEvent,
    LedgerUnreadable,
    TaskLedger,
    TaskSnapshot,
    authority_digest,
    derive_snapshot,
    ledger_path,
    read_ledger,
    task_ledger_digest,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _populated(tmp_path: Path, task_id: str = "t-1") -> TaskLedger:
    led = TaskLedger(tmp_path / f"{task_id}.jsonl", task_id=task_id)
    led.append(
        "operator_request",
        {"ref": "message:m-0", "thought_id": "th-1", "no_pr": True, "mode": "build"},
    )
    led.append("constraint", {"text_ref": "message:m-0#c1"})
    led.append("acceptance", {"text_ref": "message:m-0#a1"})
    led.append("plan_node", {"id": "p1", "status": "todo", "parent": ""})
    led.append("decision", {"ref": "artifact:step:3", "summary": "use stdlib"})
    led.append("open_loop", {"id": "q1", "ref": "message:m-2"})
    led.append("evidence", {"ref": "artifact:step:4"})
    led.append("working_set", {"path": "colleague/x.py", "op": "add"})
    led.append("changed_path", {"path": "colleague/x.py"})
    led.append("verification", {"id": "v1", "ref": "artifact:step:5", "status": "pass"})
    led.append("message", {"id": "m-3", "role": "operator"})
    led.append("delegate", {"id": "d1", "child_ref": "sub/t-1-d1"})
    led.append("delegate", {"id": "d2", "child_ref": "sub/t-1-d2"})
    led.append("return", {"id": "d1", "ref": "artifact:sub:d1"})
    led.append("invocation", {"ref": "artifact:run:1"})
    led.append("plan_node", {"id": "p1", "status": "done", "parent": ""})
    led.append("open_loop", {"id": "q1", "status": "closed"})
    led.append("working_set", {"path": "colleague/x.py", "op": "remove"})
    led.append("working_set", {"path": "colleague/y.py"})
    return led


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")[:-1]


# ---------------------------------------------------------------------------
# Vocabulary, header, seq, append-only
# ---------------------------------------------------------------------------


def test_event_kinds_is_the_closed_sixteen() -> None:
    assert EVENT_KINDS == (
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
    assert LEDGER_SCHEMA_VERSION == 1


def test_unknown_kind_refused_and_nothing_written(tmp_path: Path) -> None:
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    with pytest.raises(ValueError, match="unknown task-ledger event kind"):
        led.append("edit")
    assert not led.path.exists()


def test_header_line_first_then_events_with_ledger_owned_seq(tmp_path: Path) -> None:
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    e0 = led.append("operator_request", {"ref": "message:m-0"})
    e1 = led.append("message", {"id": "m-1"})
    lines = _lines(led.path)
    header = json.loads(lines[0])
    assert header == {"schema": "colleague.task_ledger", "version": 1, "task_id": "t"}
    assert (e0.seq, e1.seq) == (0, 1)
    assert [json.loads(x)["seq"] for x in lines[1:]] == [0, 1]
    # A fresh instance on the same file continues the ledger-owned seq.
    again = TaskLedger(led.path)
    assert again.task_id == "t"
    assert again.append("message", {"id": "m-2"}).seq == 2


def test_caller_cannot_supply_seq() -> None:
    sig = inspect.signature(TaskLedger.append)
    assert "seq" not in sig.parameters


def test_no_rewrite_path_exists() -> None:
    source = inspect.getsource(ledger_mod)
    # Only append-mode opens; never "w"/"r+"/"x", never truncate/unlink/write_text.
    assert re.search(r"""open\([^)]*["'](w|r\+|x)""", source) is None
    assert not re.search(r"\.(truncate|unlink|write_text|write_bytes|rename|replace)\(", source)
    for name in ("remove", "clear", "rewrite", "edit", "pop", "truncate", "reset", "delete"):
        assert not hasattr(TaskLedger, name), name


def test_large_payload_refused(tmp_path: Path) -> None:
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    with pytest.raises(ValueError, match="carry a ref"):
        led.append("evidence", {"blob": "x" * (MAX_EVENT_BYTES + 1)})
    assert not led.path.exists()


def test_non_mapping_data_refused(tmp_path: Path) -> None:
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    with pytest.raises(ValueError):
        led.append("evidence", ["not", "a", "mapping"])  # type: ignore[arg-type]


def test_event_roundtrip_and_canonical_is_construction_order_independent() -> None:
    a = LedgerEvent(kind="message", seq=1, task_id="t", data={"b": 1, "a": 2})
    b = LedgerEvent.from_dict(
        {"data": {"a": 2, "b": 1}, "task_id": "t", "seq": 1, "kind": "message"}
    )
    assert a == b
    assert a.canonical() == b.canonical()
    assert LedgerEvent.from_dict(a.to_dict()) == a


# ---------------------------------------------------------------------------
# derive_snapshot — replay determinism
# ---------------------------------------------------------------------------


def test_derive_snapshot_contents(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    snap = led.derive()
    assert isinstance(snap, TaskSnapshot)
    assert snap.task_id == "t-1"
    assert snap.original_request_ref == "message:m-0"
    assert snap.active_thought == "th-1"
    assert [c["text_ref"] for c in snap.constraints] == ["message:m-0#c1"]
    assert [a["text_ref"] for a in snap.acceptance] == ["message:m-0#a1"]
    assert [(p["id"], p["status"]) for p in snap.plan] == [("p1", "done")]  # last wins, keyed by id
    assert [d["summary"] for d in snap.decisions] == ["use stdlib"]
    assert snap.working_set == ("colleague/y.py",)  # add/remove replayed
    assert snap.changed_paths == ("colleague/x.py",)
    assert [(v["id"], v["status"]) for v in snap.verification] == [("v1", "pass")]
    assert [m["id"] for m in snap.messages] == ["m-3"]
    assert snap.episode == 1
    # q1 closed -> gone; d2 delegated without return -> an open loop carrying id + child ref.
    assert snap.open_loops == (
        {"id": "d2", "kind": "delegate", "child_ref": "sub/t-1-d2", "seq": 12},
    )
    dl = {d["id"]: d for d in snap.delegations}
    assert dl["d1"]["returned"] is True and dl["d1"]["return_ref"] == "artifact:sub:d1"
    assert dl["d2"]["returned"] is False
    assert len(snap.state_digest) == 64 and len(snap.authority_digest) == 64
    assert snap.state_digest == task_ledger_digest(led.events())
    assert snap.authority_digest == authority_digest(led.events())


def test_snapshot_roundtrip_to_dict_from_dict(tmp_path: Path) -> None:
    snap = _populated(tmp_path).derive()
    assert TaskSnapshot.from_dict(json.loads(json.dumps(snap.to_dict()))) == snap


@pytest.mark.parametrize("seed", range(12))
def test_derive_snapshot_is_replay_deterministic_over_shuffled_input(
    tmp_path: Path, seed: int
) -> None:
    """Property: any permutation of the same events (seq preserved) yields the
    same snapshot and the same digests — construction order never leaks."""
    events = list(_populated(tmp_path, task_id=f"t-{seed}").events())
    baseline = derive_snapshot(events)
    rng = random.Random(seed)
    shuffled = list(events)
    rng.shuffle(shuffled)
    # Re-build each event from its dict with shuffled key order too.
    rebuilt = [
        LedgerEvent.from_dict(dict(rng.sample(list(e.to_dict().items()), k=4))) for e in shuffled
    ]
    replayed = derive_snapshot(rebuilt)
    assert replayed == baseline
    assert replayed.state_digest == baseline.state_digest
    assert replayed.authority_digest == baseline.authority_digest


def test_digests_move_only_with_their_inputs(tmp_path: Path) -> None:
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    led.append("operator_request", {"ref": "message:m-0", "no_pr": True})
    s1 = led.derive()
    led.append("message", {"id": "m-1"})
    s2 = led.derive()
    assert s2.state_digest != s1.state_digest
    assert s2.authority_digest == s1.authority_digest  # a message bears no authority
    led.append("constraint", {"text_ref": "message:m-1#c1"})
    s3 = led.derive()
    assert s3.authority_digest != s2.authority_digest


def test_empty_events_snapshot_is_stable() -> None:
    assert derive_snapshot([]) == derive_snapshot(())
    assert derive_snapshot([]).state_digest == task_ledger_digest([])


def test_snapshot_event_references_other_streams_by_digest_only(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    ev = led.snapshot({"evaluation_ledger": "a" * 64, "config_events": "b" * 64})
    assert ev.kind == "snapshot"
    assert set(ev.data) == {"state_digest", "authority_digest", "referenced_digests"}
    read = led.read()  # the recorded digests verify on replay
    assert read.snapshot.referenced_digests == {
        "evaluation_ledger": "a" * 64,
        "config_events": "b" * 64,
    }
    # The snapshot event carries digests (64-hex strings), never the streams' entries.
    assert all(isinstance(v, str) and len(v) == 64 for v in ev.data["referenced_digests"].values())
    assert all(isinstance(v, str) for v in ev.data.values() if not isinstance(v, dict))


# ---------------------------------------------------------------------------
# Locked append
# ---------------------------------------------------------------------------


def test_threads_times_appends_yield_intact_lines(tmp_path: Path) -> None:
    n_threads, m_appends = 8, 25
    path = tmp_path / "shared.jsonl"
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            led = TaskLedger(path, task_id="shared")
            for j in range(m_appends):
                led.append("evidence", {"ref": f"artifact:step:{i}:{j}"})
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    lines = _lines(path)
    assert len(lines) == n_threads * m_appends + 1  # + header
    parsed = [json.loads(x) for x in lines]  # every line intact JSON
    assert sorted(e["seq"] for e in parsed[1:]) == list(range(n_threads * m_appends))
    assert {e["data"]["ref"] for e in parsed[1:]} == {
        f"artifact:step:{i}:{j}" for i in range(n_threads) for j in range(m_appends)
    }
    read = read_ledger(path)
    assert len(read.events) == n_threads * m_appends


def test_fcntl_lock_is_taken_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if ledger_mod.fcntl is None:  # pragma: no cover - non-POSIX host
        pytest.skip("fcntl unavailable on this host")
    calls: list[int] = []
    real = ledger_mod.fcntl.flock

    def spy(fd: int, op: int) -> None:
        calls.append(op)
        real(fd, op)

    monkeypatch.setattr(ledger_mod.fcntl, "flock", spy)
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    led.append("message", {"id": "m"})
    assert calls == [ledger_mod.fcntl.LOCK_EX, ledger_mod.fcntl.LOCK_UN]
    assert led.warnings == []


def test_non_posix_degrades_to_unlocked_append_with_recorded_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ledger_mod, "fcntl", None)
    led = TaskLedger(tmp_path / "t.jsonl", task_id="t")
    led.append("message", {"id": "m-1"})
    led.append("message", {"id": "m-2"})
    assert len(led.warnings) == 1 and "unlocked" in led.warnings[0]
    assert [e.seq for e in led.events()] == [0, 1]


# ---------------------------------------------------------------------------
# Fail-closed reader
# ---------------------------------------------------------------------------


def test_read_ledger_missing_file_is_unreadable(tmp_path: Path) -> None:
    with pytest.raises(LedgerUnreadable) as ei:
        read_ledger(tmp_path / "nope.jsonl")
    assert ei.value.reason


def test_read_ledger_refuses_unknown_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    p.write_text(
        json.dumps({"schema": "colleague.task_ledger", "version": 99, "task_id": "t"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerUnreadable, match="unknown schema version 99"):
        read_ledger(p)
    # The writer refuses to extend a foreign-version file too.
    with pytest.raises(LedgerUnreadable):
        TaskLedger(p, task_id="t").append("message", {"id": "m"})


def test_read_ledger_refuses_missing_header(tmp_path: Path) -> None:
    p = tmp_path / "t.jsonl"
    p.write_text('{"kind":"message","seq":0,"task_id":"t","data":{}}\n', encoding="utf-8")
    with pytest.raises(LedgerUnreadable, match="header"):
        read_ledger(p)


def test_read_ledger_refuses_torn_tail(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    with open(led.path, "a", encoding="utf-8") as fh:
        fh.write('{"kind":"message","seq":19,"task_id":"t-1","da')  # torn: no newline, not JSON
    with pytest.raises(LedgerUnreadable, match="torn tail") as ei:
        read_ledger(led.path)
    assert "torn" in ei.value.reason
    # The writer is fail-closed on the same defect — it never papers over it.
    with pytest.raises(LedgerUnreadable):
        led.append("message", {"id": "m"})


def test_read_ledger_refuses_non_json_line(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    with open(led.path, "a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
    with pytest.raises(LedgerUnreadable, match="non-JSON"):
        read_ledger(led.path)


def test_read_ledger_refuses_seq_gap_and_task_drift(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    n = len(led.events())
    with open(led.path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "message", "seq": n + 5, "task_id": "t-1", "data": {}}) + "\n")
    with pytest.raises(LedgerUnreadable, match="seq"):
        read_ledger(led.path)
    led2 = _populated(tmp_path, task_id="t-2")
    with open(led2.path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "message", "seq": n, "task_id": "other", "data": {}}) + "\n")
    with pytest.raises(LedgerUnreadable, match="task_id"):
        read_ledger(led2.path)


def test_read_ledger_refuses_unknown_kind_line(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    n = len(led.events())
    with open(led.path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "rewrite", "seq": n, "task_id": "t-1", "data": {}}) + "\n")
    with pytest.raises(LedgerUnreadable, match="unknown event kind"):
        read_ledger(led.path)


def test_read_ledger_refuses_state_digest_mismatch(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    led.snapshot()
    led.append("message", {"id": "m-after"})
    assert read_ledger(led.path).snapshot.messages[-1]["id"] == "m-after"
    # Tamper with one event BEFORE the snapshot line, keeping every line valid JSON.
    lines = _lines(led.path)
    tampered = json.loads(lines[5])
    tampered["data"]["summary"] = "use a daemon"
    lines[5] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerUnreadable, match="state_digest mismatch") as ei:
        read_ledger(led.path)
    assert "mismatch" in ei.value.reason


def test_read_ledger_refuses_authority_digest_mismatch(tmp_path: Path) -> None:
    led = _populated(tmp_path)
    led.snapshot()
    lines = _lines(led.path)
    snap_line = json.loads(lines[-1])
    snap_line["data"]["authority_digest"] = "0" * 64
    lines[-1] = json.dumps(snap_line, sort_keys=True, separators=(",", ":"))
    led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LedgerUnreadable, match="authority_digest mismatch"):
        read_ledger(led.path)


def test_read_is_never_partial_every_failure_is_ledger_unreadable(tmp_path: Path) -> None:
    """Across every defect the reader raises exactly LedgerUnreadable — no
    JSONDecodeError / KeyError / ValueError escapes, no snapshot object returns."""
    defects = {
        "empty": "",
        "binary": b"\xff\xfe\x00".decode("latin-1"),
        "header-not-object": "[1,2]\n",
        "header-wrong-tag": '{"schema":"other","version":1}\n',
        "event-not-object": '{"schema":"colleague.task_ledger","version":1,"task_id":"t"}\n[1]\n',
        "event-data-not-mapping": '{"schema":"colleague.task_ledger","version":1,"task_id":"t"}\n'
        '{"kind":"message","seq":0,"task_id":"t","data":[]}\n',
        "seq-not-int": '{"schema":"colleague.task_ledger","version":1,"task_id":"t"}\n'
        '{"kind":"message","seq":"x","task_id":"t","data":{}}\n',
    }
    for name, body in defects.items():
        p = tmp_path / f"{name}.jsonl"
        p.write_text(body, encoding="utf-8")
        with pytest.raises(LedgerUnreadable):
            read_ledger(p)


def test_ledger_unreadable_carries_reason() -> None:
    exc = LedgerUnreadable("because")
    assert exc.reason == "because" and str(exc) == "because"
    assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# Paths + module boundary
# ---------------------------------------------------------------------------


def test_ledger_path_layout(tmp_path: Path) -> None:
    assert ledger_path(tmp_path, "task-42") == tmp_path / ".colleague" / "ledger" / "task-42.jsonl"
    assert ledger_path(str(tmp_path), "x") == tmp_path / ".colleague" / "ledger" / "x.jsonl"
    for bad in ("", "a/b", "..", ".", "a\\b"):
        with pytest.raises(ValueError):
            ledger_path(tmp_path, bad)


def test_ledger_path_is_created_on_first_append(tmp_path: Path) -> None:
    led = TaskLedger(ledger_path(tmp_path, "t"), task_id="t")
    led.append("operator_request", {"ref": "message:m-0"})
    assert (tmp_path / ".colleague" / "ledger" / "t.jsonl").exists()


def test_module_boundary_no_subprocess_no_threads_guarded_fcntl() -> None:
    source = inspect.getsource(ledger_mod)
    assert not re.search(r"^\s*(import subprocess|from subprocess)", source, re.MULTILINE)
    assert not re.search(
        r"^\s*(import threading|from threading|from concurrent|import concurrent)", source, re.M
    )
    assert not re.search(r"^\s*(import socket|import asyncio)", source, re.MULTILINE)
    # fcntl import is guarded exactly like colleague/worktrees.py.
    assert re.search(r"try:\n\s+import fcntl.*\nexcept ImportError:.*\n\s+fcntl = None", source)


def test_state_package_exports() -> None:
    from colleague.agents import state

    for name in ("TaskLedger", "TaskSnapshot", "derive_snapshot", "read_ledger", "ledger_path"):
        assert getattr(state, name) is getattr(ledger_mod, name)

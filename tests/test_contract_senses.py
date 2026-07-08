"""ContextPacket + Task.context_packet + omit-when-None TaskResult.senses (t2).

Cortex/senses arc (#274): the "senses" model is a tools-off front door that
interprets an operator's verbatim request into a :class:`ContextPacket`
(``{original, interpretation, confidence, task_type, omissions}``) before the
"cortex" model drives the loop. Each senses invocation is recorded as a
:class:`SensesRecord` (``{point, latency, tokens, degraded}``) inside an
omit-when-None :class:`SensesBlock` (``{mode, packet, records}``) on
``TaskResult.senses``.

This module pins the *data contract only* — no split logic lives here. It
mirrors the existing ``TaskResult.deepthink`` discipline EXACTLY (see
``tests/test_contract_deepthink.py``): the field defaults to ``None`` and is
OMITTED (not emitted as null) from the artifact, so a run with no senses
involvement serializes byte-identically to today. The per-record numeric
coercion tolerance mirrors :class:`~colleague.contract.DeepthinkCall`, and the
``Task.context_packet`` omit-when-None treatment mirrors
``goal``/``acceptance``/``attachments`` (see ``tests/test_contract_attachments.py``).

CRITICAL: the ``ContextPacket.original`` string must round-trip through JSON
*verbatim* — no normalization, no trimming.
"""

from __future__ import annotations

import json

from colleague.contract import (
    OK,
    SENSES_CHAT_KINDS,
    SENSES_LOOP_POINT_PREFIX,
    ContextPacket,
    SensesBlock,
    SensesRecord,
    Task,
    TaskResult,
)

# ---------------------------------------------------------------------------
# ContextPacket dataclass: defaults, round-trip, verbatim `original`.
# ---------------------------------------------------------------------------


def test_context_packet_holds_all_fields() -> None:
    packet = ContextPacket(
        original="fix the bug",
        interpretation="fix the off-by-one in the paginator",
        confidence=0.82,
        task_type="bugfix",
        omissions=["which file", "which test"],
    )
    assert packet.original == "fix the bug"
    assert packet.interpretation == "fix the off-by-one in the paginator"
    assert packet.confidence == 0.82
    assert packet.task_type == "bugfix"
    assert packet.omissions == ["which file", "which test"]


def test_context_packet_round_trips_through_json() -> None:
    packet = ContextPacket(
        original="add a README",
        interpretation="write a top-level README.md",
        confidence=0.5,
        task_type="docs",
        omissions=["length", "sections"],
    )
    reloaded = ContextPacket.from_dict(json.loads(json.dumps(packet.to_dict())))
    assert reloaded == packet


def test_context_packet_original_survives_json_round_trip_verbatim() -> None:
    """The operator's verbatim text must NOT be normalized or trimmed.

    Leading/trailing whitespace, embedded newlines, tabs, and unicode must all
    survive a JSON round-trip byte-for-byte — this is the whole point of the
    ``original`` field (the operator's exact words feed the audit trail).
    """
    tricky = "  Fix\tthe\n\n  paginator — off-by-one 🐛  \n"
    packet = ContextPacket(
        original=tricky,
        interpretation="normalized interpretation",
        confidence=0.9,
        task_type="bugfix",
        omissions=[],
    )
    reloaded = ContextPacket.from_dict(json.loads(json.dumps(packet.to_dict())))
    assert reloaded.original == tricky
    # The interpretation may be normalized, but `original` is byte-identical.
    assert reloaded.original == packet.original


def test_context_packet_from_dict_tolerates_bad_confidence() -> None:
    """A malformed (unparseable) confidence degrades to 0.0, never raises."""
    packet = ContextPacket.from_dict({"original": "x", "confidence": "n/a", "task_type": "y"})
    assert packet.confidence == 0.0
    assert packet.original == "x"
    assert packet.task_type == "y"


def test_context_packet_from_dict_tolerates_missing_omissions() -> None:
    """No ``omissions`` key at all degrades to an empty list (the pre-existing
    ``data.get("omissions", [])`` behavior), never raises."""
    packet = ContextPacket.from_dict({"original": "x"})
    assert packet.omissions == []


def test_context_packet_from_dict_tolerates_none_omissions() -> None:
    """A malformed artifact's ``omissions: null`` must not crash (Qodo #1,
    cortex/senses PR #281): ``data.get("omissions", [])`` returns ``None``
    (not the default ``[]``) when the key is PRESENT but ``null``, and the old
    ``[str(o) for o in data.get(...)]`` would raise ``TypeError: 'NoneType'
    object is not iterable``."""
    packet = ContextPacket.from_dict({"original": "x", "omissions": None})
    assert packet.omissions == []


def test_context_packet_from_dict_tolerates_non_iterable_omissions() -> None:
    """A malformed artifact's ``omissions`` as a bare int must not crash
    (Qodo #1): the old comprehension would raise ``TypeError: 'int' object is
    not iterable``."""
    packet = ContextPacket.from_dict({"original": "x", "omissions": 5})
    assert packet.omissions == []


def test_context_packet_from_dict_wraps_bare_string_omissions() -> None:
    """A malformed artifact's ``omissions`` as a bare string must not silently
    iterate per-character (Qodo #1): the old ``[str(o) for o in "abc"]`` would
    yield ``['a', 'b', 'c']`` instead of treating the string as one omission."""
    packet = ContextPacket.from_dict({"original": "x", "omissions": "which file"})
    assert packet.omissions == ["which file"]


def test_context_packet_from_dict_stringifies_non_string_list_entries() -> None:
    """A list of non-string entries is still coerced to strings, matching the
    pre-fix comprehension's behavior for the well-formed list case."""
    packet = ContextPacket.from_dict({"original": "x", "omissions": [1, 2.5, None]})
    assert packet.omissions == ["1", "2.5", "None"]


# ---------------------------------------------------------------------------
# ContextPacket.ack: the senses-authored acknowledgment line riding the SAME
# intake completion (talking-to-one arc, task t5). Optional, omit-when-None.
# ---------------------------------------------------------------------------


def test_context_packet_ack_defaults_to_none() -> None:
    packet = ContextPacket(original="fix the bug")
    assert packet.ack is None


def test_context_packet_to_dict_omits_ack_when_none() -> None:
    """A packet without an ack serializes with no 'ack' key — byte-identical
    to before this field existed."""
    packet = ContextPacket(original="fix the bug", interpretation="fix it", confidence=0.5)
    serialized = packet.to_dict()
    assert "ack" not in serialized


def test_context_packet_to_dict_includes_ack_when_set() -> None:
    packet = ContextPacket(
        original="fix the bug",
        interpretation="fix the off-by-one",
        confidence=0.8,
        ack="Got it — fixing the off-by-one in the paginator. Handing this to cortex now.",
    )
    serialized = packet.to_dict()
    assert serialized["ack"] == (
        "Got it — fixing the off-by-one in the paginator. Handing this to cortex now."
    )


def test_context_packet_round_trips_with_ack() -> None:
    packet = ContextPacket(
        original="ship it",
        interpretation="ship the release",
        confidence=0.7,
        task_type="chore",
        omissions=["target env"],
        ack="On it — shipping the release, cortex is taking over.",
    )
    reloaded = ContextPacket.from_dict(json.loads(json.dumps(packet.to_dict())))
    assert reloaded == packet
    assert reloaded.ack == packet.ack


def test_context_packet_from_dict_tolerates_missing_ack() -> None:
    """A pre-arc artifact with no 'ack' key at all loads with ack=None."""
    packet = ContextPacket.from_dict({"original": "x"})
    assert packet.ack is None


def test_context_packet_from_dict_reads_none_ack() -> None:
    """An explicit 'ack': null loads back as None, never raises."""
    packet = ContextPacket.from_dict({"original": "x", "ack": None})
    assert packet.ack is None


def test_context_packet_from_dict_coerces_ack() -> None:
    """A malformed artifact's 'ack' must not crash downstream.

    ``session.py``'s ``_render_ack`` does ``(ack or "").strip()``, which
    raises ``AttributeError`` on a truthy non-string ack (e.g. a number or
    dict) — ``from_dict`` must defensively coerce ``ack`` the same way it
    already coerces ``confidence`` and ``omissions``."""
    assert ContextPacket.from_dict({"original": "x", "ack": 123}).ack is None
    assert ContextPacket.from_dict({"original": "x", "ack": {"a": 1}}).ack is None
    assert ContextPacket.from_dict({"original": "x", "ack": ""}).ack is None
    assert ContextPacket.from_dict({"original": "x", "ack": "  hi  "}).ack == "hi"
    assert ContextPacket.from_dict({"original": "x", "ack": "on it"}).ack == "on it"

    long_ack = "z" * 600
    truncated = ContextPacket.from_dict({"original": "x", "ack": long_ack}).ack
    assert truncated is not None
    assert len(truncated) == 500


# ---------------------------------------------------------------------------
# SensesRecord dataclass: mirrors DeepthinkCall {point, tokens, duration,
# degraded} with `latency` in place of `duration`.
# ---------------------------------------------------------------------------


def test_senses_record_defaults() -> None:
    rec = SensesRecord(point="interpret")
    assert rec.point == "interpret"
    assert rec.latency is None
    assert rec.tokens is None
    assert rec.degraded is False


def test_senses_record_accepts_all_fields() -> None:
    rec = SensesRecord(point="interpret", latency=0.4, tokens=128, degraded=True)
    assert rec.point == "interpret"
    assert rec.latency == 0.4
    assert rec.tokens == 128
    assert rec.degraded is True


def test_senses_record_round_trips_through_json() -> None:
    rec = SensesRecord(point="interpret", latency=1.5, tokens=64, degraded=False)
    reloaded = SensesRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert reloaded == rec


def test_senses_record_round_trips_with_none_latency_and_tokens() -> None:
    """A degraded senses call that never reached the wire reports no latency/tokens."""
    rec = SensesRecord(point="interpret", latency=None, tokens=None, degraded=True)
    reloaded = SensesRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert reloaded == rec
    assert reloaded.latency is None
    assert reloaded.tokens is None
    assert reloaded.degraded is True


def test_senses_record_from_dict_tolerates_unparseable_numbers() -> None:
    """Malformed latency/tokens fall back to None (mirrors DeepthinkCall)."""
    rec = SensesRecord.from_dict(
        {"point": "interpret", "latency": "bad", "tokens": "n/a", "degraded": True}
    )
    assert rec == SensesRecord(point="interpret", latency=None, tokens=None, degraded=True)


def test_senses_record_point_proactive_update_round_trips() -> None:
    """``point`` is free-form (talking-to-one arc, task t5): a proactive
    progress-update invocation is recorded with ``point="proactive-update"``
    and round-trips like any other point label — no field changes needed."""
    rec = SensesRecord(point="proactive-update", latency=1.1, tokens=88, degraded=False)
    reloaded = SensesRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert reloaded == rec
    assert reloaded.point == "proactive-update"


# ---------------------------------------------------------------------------
# SensesBlock dataclass: {mode, packet, records}.
# ---------------------------------------------------------------------------


def _packet() -> ContextPacket:
    return ContextPacket(
        original="the operator's exact words",
        interpretation="what senses believes is meant",
        confidence=0.77,
        task_type="feature",
        omissions=["scope"],
    )


def test_senses_block_round_trips_through_json() -> None:
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        records=[
            SensesRecord(point="interpret", latency=0.3, tokens=200, degraded=False),
            SensesRecord(point="interpret_retry", latency=None, tokens=None, degraded=True),
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block


# ---------------------------------------------------------------------------
# SensesBlock.chat entry `kind` convention (talking-to-one arc, task t5):
# a chat entry MAY carry "kind" — "talk" (implied when absent, today's
# entries), "ack", "update", "clarify" — so ack/update/clarify exchanges fold
# into the SAME chat list as talk-lane exchanges. `chat` stays a list of plain
# dicts; serialization passes every entry through verbatim regardless of
# whether it carries "kind" — this is a documented convention, not a schema
# change, so these tests pin the round-trip, not new (de)serialization code.
# ---------------------------------------------------------------------------


def test_senses_block_chat_entry_without_kind_round_trips_unchanged() -> None:
    """Today's talk-lane shape (no explicit "kind") is untouched — "talk" is
    only ever IMPLIED, never injected by serialization."""
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        chat=[
            {
                "message": "how's it going?",
                "answer": "still reading the paginator module.",
                "relay": False,
                "relay_text": None,
                "latency": 0.8,
                "degraded": False,
                "at": 12.5,
            }
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block
    assert "kind" not in reloaded.chat[0]


def test_senses_block_chat_entry_kind_ack_round_trips() -> None:
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        chat=[
            {
                "kind": "ack",
                "message": "fix the paginator bug",
                "answer": "Got it — fixing the off-by-one. Handing this to cortex now.",
                "at": 0.1,
            }
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block
    assert reloaded.chat[0]["kind"] == "ack"
    assert reloaded.chat[0]["answer"] == (
        "Got it — fixing the off-by-one. Handing this to cortex now."
    )


def test_senses_block_chat_entry_kind_update_round_trips() -> None:
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        chat=[
            {
                "kind": "update",
                "answer": "Still working through the paginator tests — 3 of 5 files edited.",
                "latency": 1.2,
                "degraded": False,
                "at": 40.0,
            }
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block
    assert reloaded.chat[0]["kind"] == "update"


def test_senses_block_chat_entry_kind_clarify_round_trips() -> None:
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        chat=[
            {
                "kind": "clarify",
                "message": "Which module should I touch?",
                "answer": "the paginator module",
                "at": 0.2,
            }
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block
    assert reloaded.chat[0]["kind"] == "clarify"


def test_senses_block_chat_mixes_kinds_and_preserves_order() -> None:
    """A single chat list folds ack/update/clarify/talk entries together, in
    the order they occurred — the whole exchange reconstructable from one list."""
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        chat=[
            {"kind": "ack", "answer": "Got it, handing to cortex.", "at": 0.1},
            {"kind": "update", "answer": "2 of 5 files done.", "at": 30.0},
            {
                "message": "how's it going?",
                "answer": "still going.",
                "relay": False,
                "at": 45.0,
            },
            {"kind": "update", "answer": "4 of 5 files done.", "at": 60.0},
        ],
    )
    reloaded = SensesBlock.from_dict(json.loads(json.dumps(block.to_dict())))
    assert reloaded == block
    assert [entry.get("kind", "talk") for entry in reloaded.chat] == [
        "ack",
        "update",
        "talk",
        "update",
    ]


# ---------------------------------------------------------------------------
# Presence-default-everywhere arc, task t3: ONE shared SensesBlock shape must
# serve every front (session, `colleague talk` attach, background runs, the
# mesh resident, one-shot `colleague work`, and the senses coordination loop
# itself). These tests pin the closed `chat[].kind` vocabulary + the
# `records[].point` "senses-loop:<move>" convention, that a run with no
# presence lane stays byte-identical, and that two different fronts populating
# the SAME beats produce structurally identical (not just similar) blocks.
# ---------------------------------------------------------------------------


def test_senses_chat_kinds_is_the_closed_four_value_vocabulary() -> None:
    """No fifth kind exists — `SENSES_CHAT_KINDS` is the complete, closed set
    every front (and the senses coordination loop, tasks t1/t5) must reuse."""
    assert set(SENSES_CHAT_KINDS) == {"talk", "ack", "update", "clarify"}


def test_senses_loop_point_prefix_value() -> None:
    """The senses coordination loop's per-turn `SensesRecord.point` convention
    is `f"{SENSES_LOOP_POINT_PREFIX}{move}"` — e.g.
    `"senses-loop:dispatch_to_cortex"` — distinguishing loop turns from the
    fixed-beat points (`"senses-intake"`, `"senses-update"`, ...) that share
    this SAME `SensesRecord` shape (no new field, no new record type)."""
    assert SENSES_LOOP_POINT_PREFIX == "senses-loop:"
    rec = SensesRecord(point=f"{SENSES_LOOP_POINT_PREFIX}dispatch_to_cortex")
    assert rec.point == "senses-loop:dispatch_to_cortex"
    reloaded = SensesRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert reloaded == rec


def test_senses_block_with_no_presence_lane_omits_chat_and_injections() -> None:
    """A cortex/senses split run where the presence lane (ack/updates/clarify/
    the senses loop) never fired keeps `chat`/`injections` omitted — only
    `mode`/`packet`/`records` appear, byte-identical to the pre-presence-lane
    cortex/senses shape. This is the "no presence lane" byte-identical pin
    (distinct from "no senses at all", already pinned by
    `test_default_taskresult_omits_senses_key`)."""
    block = SensesBlock(
        mode="split",
        packet=_packet(),
        records=[SensesRecord(point="senses-intake", latency=0.4, tokens=120, degraded=False)],
    )
    serialized = block.to_dict()
    assert set(serialized.keys()) == {"mode", "packet", "records"}
    assert "chat" not in serialized
    assert "injections" not in serialized

    result = TaskResult(task_id="no-presence", status=OK, summary="cortex-only work", senses=block)
    result_serialized = result.to_dict()
    assert "chat" not in result_serialized["senses"]
    assert "injections" not in result_serialized["senses"]

    reloaded = TaskResult.from_dict(json.loads(json.dumps(result_serialized)))
    assert reloaded == result
    assert reloaded.senses.chat == []
    assert reloaded.senses.injections == []


def _session_style_block() -> SensesBlock:
    """A SensesBlock populated the way `colleague/cli/_commands/session.py`'s
    existing `_render_ack` / `_maybe_proactive_update` / `_maybe_clarify` beats
    populate one today (talking-to-one arc)."""
    return SensesBlock(
        mode="split",
        packet=_packet(),
        records=[
            SensesRecord(point="senses-intake", latency=0.3, tokens=120, degraded=False),
            SensesRecord(point="senses-update", latency=0.9, tokens=64, degraded=False),
        ],
        injections=[{"text": "check the other file too", "at": 12.0, "source": "operator"}],
        chat=[
            {"kind": "ack", "text": "Got it, handing to cortex.", "fixed": False, "at": 0.1},
            {
                "kind": "update",
                "text": "2 of 5 files done.",
                "latency": 0.9,
                "degraded": False,
                "at": 30.0,
            },
            {"kind": "clarify", "role": "senses", "text": "which module?", "at": 5.0},
        ],
    )


def _senses_loop_style_block() -> SensesBlock:
    """A SensesBlock populated the way the senses coordination loop (tasks
    t1/t5, a DIFFERENT front from the session) would populate one: each turn
    records a `SensesRecord` with `point="senses-loop:<move>"`, and an
    operator-facing move reuses the SAME `SENSES_CHAT_KINDS` vocabulary —
    `guide_cortex` folds into `injections` instead of `chat`."""
    return SensesBlock(
        mode="split",
        packet=_packet(),
        records=[
            SensesRecord(
                point=f"{SENSES_LOOP_POINT_PREFIX}dispatch_to_cortex",
                latency=0.2,
                tokens=90,
                degraded=False,
            ),
            SensesRecord(
                point=f"{SENSES_LOOP_POINT_PREFIX}guide_cortex",
                latency=0.4,
                tokens=70,
                degraded=False,
            ),
        ],
        injections=[{"text": "look at the paginator tests", "at": 20.0, "source": "operator"}],
        chat=[
            {"kind": "ack", "text": "On it, dispatching to cortex.", "fixed": False, "at": 0.05},
            {"kind": "clarify", "role": "senses", "text": "which environment?", "at": 2.0},
        ],
    )


def test_shape_equality_across_two_fronts() -> None:
    """The same beats (ack, update/clarify, a guidance relay) reached via two
    DIFFERENT fronts (session-style vs. senses-loop-style) yield SensesBlocks
    with IDENTICAL schema — same top-level fields, same `records[]` item
    shape, same `chat[].kind` vocabulary, same per-kind entry key-shape —
    differing only in values. No front may grow its own record schema (t3
    acceptance criterion 3)."""
    session_block = _session_style_block()
    loop_block = _senses_loop_style_block()

    session_dict = session_block.to_dict()
    loop_dict = loop_block.to_dict()

    # 1. Same top-level SensesBlock field shape.
    assert set(session_dict.keys()) == set(loop_dict.keys())

    # 2. Same `records[]` item shape ({point, latency, tokens, degraded}).
    assert set(session_dict["records"][0].keys()) == set(loop_dict["records"][0].keys())
    assert set(session_dict["records"][0].keys()) == {"point", "latency", "tokens", "degraded"}

    # 3. Both fronts' `injections[]` items share the same conventional shape.
    assert set(session_dict["injections"][0].keys()) == set(loop_dict["injections"][0].keys())

    # 4. The chat `kind` vocabulary used by both fronts is the SAME closed
    #    set (colleague.contract.SENSES_CHAT_KINDS) — no front invents a
    #    fifth kind.
    session_kinds = {entry["kind"] for entry in session_dict["chat"]}
    loop_kinds = {entry["kind"] for entry in loop_dict["chat"]}
    assert session_kinds <= set(SENSES_CHAT_KINDS)
    assert loop_kinds <= set(SENSES_CHAT_KINDS)

    # 5. For every kind BOTH fronts use, the entry key-shape matches exactly
    #    — the whole point: no front-specific record schema.
    shared_kinds = session_kinds & loop_kinds
    assert shared_kinds, "fixture must exercise at least one shared kind"
    for kind in shared_kinds:
        session_entry = next(e for e in session_dict["chat"] if e["kind"] == kind)
        loop_entry = next(e for e in loop_dict["chat"] if e["kind"] == kind)
        assert set(session_entry.keys()) == set(
            loop_entry.keys()
        ), f"kind={kind!r} entry shape diverged between fronts"

    # 6. Both round-trip losslessly and reconstruct equal objects — the
    #    schema equality above isn't an artifact of a lossy comparison.
    assert SensesBlock.from_dict(json.loads(json.dumps(session_dict))) == session_block
    assert SensesBlock.from_dict(json.loads(json.dumps(loop_dict))) == loop_block


# ---------------------------------------------------------------------------
# h14 proof-shaped fixture: the whole operator-senses exchange (ack,
# proactive updates, folded chat) is reconstructable from the artifact alone,
# machine-checkable with no human judgment (talking-to-one arc, task t5,
# covers c8 + h14).
# ---------------------------------------------------------------------------


def test_h14_proof_shaped_artifact_is_machine_checkable_end_to_end() -> None:
    ack_text = "Got it — fixing the paginator off-by-one. Handing this to cortex now."
    packet = ContextPacket(
        original="fix the paginator off-by-one bug",
        interpretation="fix the off-by-one error in the paginator",
        confidence=0.85,
        task_type="bugfix",
        omissions=["which test file"],
        ack=ack_text,
    )
    block = SensesBlock(
        mode="split",
        packet=packet,
        records=[
            SensesRecord(point="interpret", latency=0.4, tokens=210, degraded=False),
            SensesRecord(point="proactive-update", latency=1.1, tokens=64, degraded=False),
            SensesRecord(point="proactive-update", latency=0.9, tokens=58, degraded=False),
        ],
        chat=[
            {"kind": "ack", "answer": ack_text, "at": 0.1},
            {
                "kind": "update",
                "answer": "2 of 4 files edited so far, tests still to run.",
                "latency": 1.1,
                "degraded": False,
                "at": 25.0,
            },
            {
                "kind": "update",
                "answer": "All 4 files edited, running the affected tests now.",
                "latency": 0.9,
                "degraded": False,
                "at": 55.0,
            },
        ],
    )
    result = TaskResult(
        task_id="h14-proof",
        status=OK,
        summary="fixed the paginator off-by-one",
        senses=block,
    )

    serialized = result.to_dict()

    # The ack text is readable straight from the artifact.
    assert serialized["senses"]["packet"]["ack"] == ack_text

    # At least one proactive-update record is present and machine-selectable.
    update_records = [
        r for r in serialized["senses"]["records"] if r["point"] == "proactive-update"
    ]
    assert len(update_records) == 2

    # The folded chat carries both the ack and the update exchanges, in order,
    # each machine-selectable by "kind".
    chat_kinds = [entry["kind"] for entry in serialized["senses"]["chat"]]
    assert chat_kinds == ["ack", "update", "update"]
    assert serialized["senses"]["chat"][0]["answer"] == ack_text

    # The whole exchange round-trips byte-for-byte through JSON.
    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert reloaded.senses.packet.ack == ack_text
    assert [r.point for r in reloaded.senses.records].count("proactive-update") == 2
    assert [entry["kind"] for entry in reloaded.senses.chat] == ["ack", "update", "update"]


# ---------------------------------------------------------------------------
# Byte-identical guard #1: TaskResult with no senses -> no "senses" key.
# ---------------------------------------------------------------------------


def test_default_taskresult_omits_senses_key() -> None:
    """A result with no senses involvement serializes byte-identical to today."""
    result = TaskResult(task_id="x", status=OK, summary="plain cortex-only drive")
    assert result.senses is None

    serialized = result.to_dict()
    assert "senses" not in serialized

    # Exact key set must match the pre-senses contract — no extra key sneaks in
    # even though the field exists on the dataclass with its default value.
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
        "not_finished",
        "stopped_without_finish",
    }
    assert set(serialized.keys()) == expected_keys


def test_default_taskresult_json_is_byte_identical_to_pre_feature_shape() -> None:
    """The JSON text itself (not just the key set) is unaffected by the new field."""
    result = TaskResult(task_id="abc", status=OK, summary="done")
    serialized = result.to_dict()
    reference = {
        "task_id": "abc",
        "status": OK,
        "summary": "done",
        "changed_files": [],
        "steps": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "stats": serialized["stats"],
        "artifacts_path": None,
        "error": None,
        "branch": None,
        "pr_url": None,
        "hook_firings": [],
        "command": None,
        "not_finished": False,
        "stopped_without_finish": False,
    }
    assert json.dumps(serialized, sort_keys=True) == json.dumps(reference, sort_keys=True)


# ---------------------------------------------------------------------------
# Populated senses block round-trips; packet.original preserved verbatim.
# ---------------------------------------------------------------------------


def test_task_result_with_senses_round_trips_and_preserves_original_verbatim() -> None:
    tricky_original = "\t Ship it.\n  (no scope given) 🚀 \n"
    block = SensesBlock(
        mode="split",
        packet=ContextPacket(
            original=tricky_original,
            interpretation="implement the shipping feature",
            confidence=0.6,
            task_type="feature",
            omissions=["acceptance criteria", "target module"],
        ),
        records=[
            SensesRecord(point="interpret", latency=0.9, tokens=321, degraded=False),
        ],
    )
    result = TaskResult(task_id="s1", status=OK, summary="senses split", senses=block)

    serialized = result.to_dict()
    assert "senses" in serialized
    assert serialized["senses"] == block.to_dict()

    reloaded = TaskResult.from_dict(json.loads(json.dumps(serialized)))
    assert reloaded == result
    assert reloaded.senses is not None
    # The whole point of the task: `original` is byte-identical after the trip.
    assert reloaded.senses.packet.original == tricky_original
    assert reloaded.senses.mode == "split"
    assert reloaded.senses.records[0].degraded is False


def test_task_result_senses_records_preserve_order() -> None:
    block = SensesBlock(
        mode="cortex-only",
        packet=_packet(),
        records=[SensesRecord(point="a"), SensesRecord(point="b"), SensesRecord(point="c")],
    )
    result = TaskResult(task_id="s2", status=OK, senses=block)
    reloaded = TaskResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert [r.point for r in reloaded.senses.records] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# from_dict back-compat: reads both WITH and WITHOUT the "senses" key.
# ---------------------------------------------------------------------------


def test_task_result_from_dict_tolerates_missing_senses() -> None:
    """A pre-senses artifact (no 'senses' key at all) loads with None."""
    old_payload = {
        "task_id": "back1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
    }
    result = TaskResult.from_dict(old_payload)
    assert result.senses is None


def test_task_result_from_dict_reads_senses_when_present() -> None:
    payload = {
        "task_id": "fwd1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "senses": {
            "mode": "split",
            "packet": {
                "original": "verbatim words",
                "interpretation": "interp",
                "confidence": 0.5,
                "task_type": "feature",
                "omissions": ["x"],
            },
            "records": [{"point": "interpret", "latency": 0.1, "tokens": 10, "degraded": False}],
        },
    }
    result = TaskResult.from_dict(payload)
    assert result.senses is not None
    assert result.senses.mode == "split"
    assert result.senses.packet.original == "verbatim words"
    assert result.senses.records == [
        SensesRecord(point="interpret", latency=0.1, tokens=10, degraded=False)
    ]


def test_task_result_from_dict_drops_malformed_senses_records() -> None:
    """Non-dict record entries are dropped rather than raising (best-effort,
    mirroring DeepthinkCall / acceptance_outcomes)."""
    payload = {
        "task_id": "malformed1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "senses": {
            "mode": "split",
            "packet": {"original": "x"},
            "records": ["not-a-dict", 42, None, {"point": "interpret"}],
        },
    }
    # Must not raise.
    result = TaskResult.from_dict(payload)
    assert result.senses is not None
    assert result.senses.records == [SensesRecord(point="interpret")]


def test_task_result_from_dict_non_dict_senses_degrades_to_none() -> None:
    """A bare-string / non-dict senses payload degrades to None, never raises."""
    payload = {
        "task_id": "bad1",
        "status": OK,
        "summary": "",
        "changed_files": [],
        "steps": [],
        "usage": {},
        "senses": "not-a-block",
    }
    result = TaskResult.from_dict(payload)
    assert result.senses is None


# ---------------------------------------------------------------------------
# Task.context_packet: optional, omit-when-None (mirrors goal/attachments).
# ---------------------------------------------------------------------------


def test_task_new_without_context_packet_is_byte_identical() -> None:
    """A Task authored without a context_packet serializes with the pre-t2 key set."""
    task = Task.new("/repo", "add a README", engine="mock")
    assert task.context_packet is None

    serialized = task.to_dict()
    assert "context_packet" not in serialized

    expected_keys = {"id", "repo_path", "instruction", "context", "constraints", "engine"}
    assert set(serialized.keys()) == expected_keys


def test_task_round_trips_without_context_packet() -> None:
    task = Task.new("/repo", "add a README", engine="mock")
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.context_packet is None


def test_task_new_with_context_packet_carries_it() -> None:
    packet = _packet()
    task = Task.new("/repo", "do it", engine="mock", context_packet=packet)
    assert task.context_packet == packet

    serialized = task.to_dict()
    assert serialized["context_packet"] == packet.to_dict()


def test_task_context_packet_round_trips_and_preserves_original_verbatim() -> None:
    tricky = "  do\tthe\n thing  \n"
    packet = ContextPacket(
        original=tricky,
        interpretation="the thing, interpreted",
        confidence=0.4,
        task_type="chore",
        omissions=[],
    )
    task = Task.new("/repo", "do it", engine="vllm-openai", context_packet=packet)
    reloaded = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    assert reloaded == task
    assert reloaded.context_packet is not None
    assert reloaded.context_packet.original == tricky


def test_task_from_dict_tolerates_missing_context_packet() -> None:
    """from_dict defaults context_packet to None when absent (back-compat)."""
    old_payload = {
        "id": "abc123",
        "repo_path": "/repo",
        "instruction": "do work",
        "context": "",
        "constraints": [],
        "engine": "mock",
    }
    task = Task.from_dict(old_payload)
    assert task.context_packet is None


def test_task_from_dict_non_dict_context_packet_degrades_to_none() -> None:
    """A bare-string / non-dict context_packet degrades to None, never raises."""
    base = Task.new("/tmp/x", "do x").to_dict()
    base["context_packet"] = "not-a-packet"
    assert Task.from_dict(base).context_packet is None

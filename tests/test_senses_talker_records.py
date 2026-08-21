"""Talker = senses: identity + invocation records at the senses call sites (#411, t16).

Covers the three acceptance criteria:

1. every senses completion (intake / speakback / media-bridge / talk / update /
   frontdoor in ``colleague.senses`` + the coordination loop's completion in
   ``colleague.senses_loop``) appends exactly ONE ``invocation`` event with
   purpose ``talker``, model_role ``senses``, the digest of the EMPTY tool
   surface — when agents are armed AND a ledger path is set; ``tools=[]``
   stays on every call site (tests/test_senses_cannot_act.py holds);
2. the talker profile refuses any write-class tool; a ``guide_cortex`` move
   lands as an ``operator_input`` event; reply / clarify / narrate are
   display-only (never ledgered); none of the senses modules can produce a
   ``delegate`` / ``handoff`` authority;
3. unarmed (or no ledger path, or no senses at all) → zero events, no ledger
   file, the bound callable is the caller's own (byte-identical).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from colleague.agents.profile import AgentProfile, validate_profile_tools
from colleague.agents.state.ledger import TaskLedger, read_ledger
from colleague.agents.talker import (
    GUIDE_CORTEX_VIA,
    MAX_OPERATOR_INPUT_CHARS,
    TALKER_TOOL_SURFACE_DIGEST,
    record_operator_input,
    record_talker_invocation,
    recording_complete,
    talker_ledger_path,
)
from colleague.agents.tools import (
    TALKER_TOOLS,
    THINKER_CODER_TOOLS,
    WORKER_TOOLS,
    assert_purpose_surface,
    tool_surface_digest,
)
from colleague.config import EngineConfig, SensesConfig
from colleague.loop import ModelResponse
from colleague.senses import (
    make_senses_run,
    run_senses_frontdoor,
    run_senses_intake,
    run_senses_media_bridge,
    run_senses_speakback,
    run_senses_talk,
    run_senses_update,
    senses_engine_config,
)
from colleague.senses_loop import (
    BOUNDARY_CADENCE_TICK,
    BOUNDARY_OPERATOR_INPUT,
    BoundaryContext,
    SensesLoopDriver,
)
from colleague.senses_moves import SensesMoveExecutor

REPO_ROOT = Path(__file__).resolve().parents[1]

_INTAKE_JSON = (
    '{"interpretation": "add a retry", "confidence": 0.8, '
    '"task_type": "feature", "omissions": [], "ack": "on it"}'
)
_TALK_JSON = '{"answer": "cortex is editing config.py", "relay": false}'
_UPDATE_JSON = '{"update": "still editing config.py"}'


# ---------------------------------------------------------------------------
# fakes (the tests/test_senses.py shapes, scripted, no network)
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Records ``make_complete(tools=...)`` + the messages; fully scripted."""

    name = "fake"

    def __init__(self, content: str) -> None:
        self.make_complete_calls: list = []
        self.complete_call_count = 0
        self._response = ModelResponse(content=content, prompt_tokens=5, completion_tokens=7)

    def make_count_tokens(self, config):
        def counter(messages):
            return sum(len(str(m.get("content") or "")) for m in messages)

        return counter

    def make_complete(self, config, tools=None):
        self.make_complete_calls.append(tools)

        def complete(messages):
            self.complete_call_count += 1
            return self._response

        return complete


class _FakeMakeComplete:
    """A bare ``make_complete`` factory (talk / frontdoor / the loop take one)."""

    def __init__(self, content: str) -> None:
        self.tools_calls: list = []
        self.complete_call_count = 0
        self._content = content

    def __call__(self, config, *, tools):
        self.tools_calls.append(tools)

        def complete(messages):
            self.complete_call_count += 1
            return ModelResponse(content=self._content, prompt_tokens=3, completion_tokens=4)

        return complete


def _char_counter(messages):
    return sum(len(str(m.get("content") or "")) for m in messages)


def _armed_config(tmp_path: Path, *, armed: bool = True, with_path: bool = True) -> EngineConfig:
    """The senses-pointed EngineConfig the run functions take, armed for t16."""
    cfg = EngineConfig(model="senses-model", context_budget_tokens=100000, agents=armed)
    if with_path:
        cfg.agents_ledger_path = str(tmp_path / "task-7.jsonl")
    return cfg


def _events(cfg) -> list:
    path = Path(cfg.agents_ledger_path)
    if not path.exists():
        return []
    return list(read_ledger(path).events)


def _assert_one_talker_invocation(cfg, *, model="senses-model") -> None:
    events = _events(cfg)
    invocations = [e for e in events if e.kind == "invocation"]
    assert len(invocations) == 1, [e.kind for e in events]
    inv = invocations[0]
    assert inv.data["purpose"] == "talker"
    assert inv.data["model_role"] == "senses"
    assert inv.data["fallback_from_role"] is None
    assert inv.data["resolved_model"] == model
    assert inv.data["tool_surface_digest"] == TALKER_TOOL_SURFACE_DIGEST
    assert inv.data["agent_id"] == "talker-task-7"
    # token_estimate is NEVER in the ledger event (runtime.append_invocation rule).
    assert "token_estimate" not in inv.data


# ---------------------------------------------------------------------------
# AC1 — every senses.py call site records exactly one talker invocation
# ---------------------------------------------------------------------------


def test_talker_tool_surface_digest_is_the_empty_set() -> None:
    assert TALKER_TOOLS == frozenset()
    assert TALKER_TOOL_SURFACE_DIGEST == tool_surface_digest(())


class TestEverySensesCallSiteRecordsATalkerInvocation:
    def test_intake(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        engine = _FakeEngine(_INTAKE_JSON)

        packet, record = run_senses_intake("add a retry", cfg, engine)

        assert packet is not None and record.degraded is False
        assert engine.make_complete_calls == [[]]  # tools=[] stays
        _assert_one_talker_invocation(cfg)

    def test_speakback(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        engine = _FakeEngine("Done: retry added.")

        display, record = run_senses_speakback("retry added", cfg, engine)

        assert display and record.degraded is False
        assert engine.make_complete_calls == [[]]
        _assert_one_talker_invocation(cfg)

    def test_media_bridge(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        engine = _FakeEngine("a red square")

        text, record = run_senses_media_bridge(
            "what is in the image?",
            [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
            cfg,
            engine,
        )

        assert text == "a red square" and record.degraded is False
        assert engine.make_complete_calls == [[]]
        _assert_one_talker_invocation(cfg)

    def test_talk(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        fake = _FakeMakeComplete(_TALK_JSON)

        result = run_senses_talk(
            "what is cortex doing?",
            feed_tail="[edit_file] colleague/config.py",
            packet=None,
            task_state=None,
            senses_config=cfg,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None and result["degraded"] is False
        assert fake.tools_calls == [[]]
        _assert_one_talker_invocation(cfg)

    def test_update(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        engine = _FakeEngine(_UPDATE_JSON)

        result = run_senses_update(["[edit_file] colleague/config.py"], None, cfg, engine)

        assert result is not None and result["degraded"] is False
        assert engine.make_complete_calls == [[]]
        _assert_one_talker_invocation(cfg)

    def test_frontdoor(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        fake = _FakeMakeComplete('{"answer": "hello!"}')

        result = run_senses_frontdoor(
            "hi",
            facts="F",
            senses_config=cfg,
            make_complete=fake,
            make_count_tokens=_char_counter,
        )

        assert result is not None and result["degraded"] is False
        assert fake.tools_calls == [[]]
        _assert_one_talker_invocation(cfg)

    def test_senses_loop_completion(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        fake = _FakeMakeComplete(json.dumps({"move": "wait"}))
        driver = SensesLoopDriver(
            senses_config=cfg,
            make_complete=fake,
            executor=_executor([]),
            make_count_tokens=_char_counter,
        )

        driver.process_boundary(BoundaryContext(kind=BOUNDARY_CADENCE_TICK))

        assert fake.tools_calls == [[]]
        _assert_one_talker_invocation(cfg)

    def test_record_is_appended_even_when_the_send_fails(self, tmp_path: Path) -> None:
        """An attempted invocation is still an invocation; the failure still
        degrades the senses call exactly as before (never raises)."""
        cfg = _armed_config(tmp_path)

        class _Dead(_FakeEngine):
            def make_complete(self, config, tools=None):
                self.make_complete_calls.append(tools)

                def complete(messages):
                    raise ConnectionError("dead port")

                return complete

        engine = _Dead(_INTAKE_JSON)
        packet, record = run_senses_intake("add a retry", cfg, engine)

        assert packet is None and record.degraded is True
        _assert_one_talker_invocation(cfg)


class TestRecordDetails:
    def test_token_estimate_is_labelled_and_never_in_usage_or_ledger(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        messages = [{"role": "user", "content": "x" * 400}]

        rec = record_talker_invocation(cfg, messages, engine=None)

        assert rec is not None
        assert rec.token_estimate == 100 and rec.token_estimate_source == "chars"
        assert rec.seq == 0
        assert rec.purpose == "talker" and rec.model_role == "senses"
        assert "token_estimate" not in _events(cfg)[0].data

    def test_engine_counter_labels_tokenize(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        rec = record_talker_invocation(
            cfg, [{"role": "user", "content": "abcd"}], engine=_FakeEngine("")
        )
        assert rec is not None
        assert rec.token_estimate_source == "tokenize"

    def test_truncation_marker_sets_truncated(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        seen: list = []
        wrapped = recording_complete(
            lambda m: seen.append(m) or "ok", cfg, truncation_marker="[cut]"
        )
        assert wrapped([{"role": "user", "content": "hello [cut]"}]) == "ok"
        assert len(seen) == 1
        assert _events(cfg)[0].data["truncated"] is True

    def test_ledger_digest_names_the_state_after_append(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        rec = record_talker_invocation(cfg, [{"role": "user", "content": "q"}])
        assert rec is not None
        assert rec.ledger_digest == read_ledger(cfg.agents_ledger_path).snapshot.state_digest

    def test_a_broken_ledger_never_breaks_the_senses_call(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        # A directory where the ledger file should be: the append fails.
        Path(cfg.agents_ledger_path).mkdir(parents=True)
        engine = _FakeEngine(_INTAKE_JSON)

        packet, record = run_senses_intake("add a retry", cfg, engine)

        assert packet is not None and record.degraded is False
        assert engine.complete_call_count == 1


# ---------------------------------------------------------------------------
# AC2 — talker profile refuses write tools; guide_cortex → operator_input;
#       reply / clarify / narrate are display-only; never delegate / handoff
# ---------------------------------------------------------------------------


def _talker_profile() -> AgentProfile:
    return AgentProfile(
        agent_id="talker-1",
        purpose="talker",
        model_role="senses",
        resolved_model="served-senses",
        tool_profile="talker",
        authority_profile="present",
        parent_agent_id=None,
        task_id="task-7",
        fallback_from_role=None,
    )


class TestTalkerProfileRefusesWriteTools:
    @pytest.mark.parametrize(
        "tool", ["write_file", "edit_file", "run_command", "subagent", "subagents"]
    )
    def test_write_class_refused(self, tool: str) -> None:
        with pytest.raises(ValueError, match="talker profile refuses"):
            validate_profile_tools(_talker_profile(), ["read_file", tool])

    @pytest.mark.parametrize("tool", ["culture", "devague"])
    def test_external_class_refused(self, tool: str) -> None:
        with pytest.raises(ValueError, match="external"):
            assert_purpose_surface("talker", [tool])

    def test_unknown_tool_fails_closed_for_talker(self) -> None:
        with pytest.raises(ValueError, match="unknown tool"):
            assert_purpose_surface("talker", ["teleport"])

    def test_empty_and_read_only_surfaces_pass(self) -> None:
        validate_profile_tools(_talker_profile(), [])
        validate_profile_tools(_talker_profile(), TALKER_TOOLS)
        assert_purpose_surface("talker", ["read_file", "list_dir", "finish"])

    def test_other_purposes_are_not_refused_here(self) -> None:
        assert_purpose_surface("worker", WORKER_TOOLS)
        assert_purpose_surface("thinker_coder", THINKER_CODER_TOOLS)
        assert_purpose_surface("associate", ["write_file", "run_command"])


def _executor(events: list) -> SensesMoveExecutor:
    return SensesMoveExecutor(
        dispatch_to_cortex=lambda i: events.append(("dispatch", i)) or "dispatched",
        guide_cortex=lambda g: events.append(("guide", g)) or "guided",
        read_flight=lambda: events.append(("read_flight",)) or "step 3/40",
        reply_to_operator=lambda t: events.append(("reply", t)) or "replied",
        clarify=lambda q: events.append(("clarify", q)) or "clarified",
    )


class _ScriptedMakeComplete:
    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.tools_calls: list = []

    def __call__(self, config, *, tools):
        self.tools_calls.append(tools)

        def complete(messages):
            reply = self._replies.pop(0) if self._replies else json.dumps({"move": "wait"})
            return ModelResponse(content=reply, prompt_tokens=3, completion_tokens=5)

        return complete


def _driver(cfg, replies, events, **kw) -> SensesLoopDriver:
    return SensesLoopDriver(
        senses_config=cfg,
        make_complete=_ScriptedMakeComplete(replies),
        executor=_executor(events),
        make_count_tokens=_char_counter,
        **kw,
    )


class TestGuideCortexIsOperatorInputAndTheRestIsDisplayOnly:
    def test_guide_cortex_lands_as_operator_input(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        events: list = []
        driver = _driver(
            cfg,
            [json.dumps({"move": "guide_cortex", "guidance": "prefer the retry helper"})],
            events,
            per_boundary_cap=1,
        )

        driver.process_boundary(
            BoundaryContext(kind=BOUNDARY_OPERATOR_INPUT, operator_input="use the retry helper")
        )

        ledger = _events(cfg)
        kinds = [e.kind for e in ledger]
        assert kinds == ["invocation", "operator_input"]
        op = ledger[1].data
        assert op["via"] == GUIDE_CORTEX_VIA
        assert op["source"] == "senses-loop"
        # The verbatim-to-cortex invariant: the operator's words ride the guidance.
        assert "use the retry helper" in op["text"]
        assert driver.injections and driver.injections[0]["text"] == op["text"]

    @pytest.mark.parametrize(
        "move_obj",
        [
            {"move": "reply_to_operator", "text": "cortex is editing config.py"},
            {"move": "clarify", "question": "which backoff?"},
            {"move": "narrate", "text": "cortex is writing the helper"},
        ],
    )
    def test_reply_clarify_narrate_are_display_only_not_ledgered(
        self, tmp_path: Path, move_obj: dict
    ) -> None:
        cfg = _armed_config(tmp_path)
        events: list = []
        driver = _driver(cfg, [json.dumps(move_obj)], events, per_boundary_cap=1)

        driver.process_boundary(
            BoundaryContext(
                kind=BOUNDARY_OPERATOR_INPUT,
                operator_input="how is it going?",
                delta_tail="def retry(): ...",
            )
        )

        kinds = [e.kind for e in _events(cfg)]
        assert kinds == ["invocation"]  # the completion's own record, nothing else

    def test_no_senses_move_can_produce_a_delegate_or_handoff_event(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        events: list = []
        moves = [
            {"move": "guide_cortex", "guidance": "g"},
            {"move": "reply_to_operator", "text": "r"},
            {"move": "clarify", "question": "c?"},
            {"move": "narrate", "text": "n"},
            {"move": "dispatch_to_cortex", "instruction": "do it", "ack": "ok"},
            {"move": "read_flight"},
        ]
        driver = _driver(cfg, [json.dumps(m) for m in moves], events, per_boundary_cap=6)
        for _ in moves:
            driver.process_boundary(
                BoundaryContext(kind=BOUNDARY_OPERATOR_INPUT, operator_input="x", delta_tail="y")
            )

        kinds = {e.kind for e in _events(cfg)}
        assert kinds <= {"invocation", "operator_input"}
        assert "delegate" not in kinds and "return" not in kinds and "message" not in kinds

    def test_operator_input_text_is_capped_with_a_truncated_flag(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        ev = record_operator_input(cfg, "g" * (MAX_OPERATOR_INPUT_CHARS + 10))
        assert ev is not None
        assert ev.data["truncated"] is True
        assert len(ev.data["text"]) == MAX_OPERATOR_INPUT_CHARS

    def test_blank_guidance_is_not_ledgered(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        assert record_operator_input(cfg, "   ") is None
        assert _events(cfg) == []


def test_senses_modules_cannot_import_a_delegate_or_handoff_authority() -> None:
    """The structural pin: no senses-side module (nor the talker helper) imports
    the delegation / messages contracts or the handoff module (AST-level, so a
    docstring MENTION of the rule is not a violation)."""
    banned = {"colleague.agents.delegation", "colleague.agents.messages", "colleague.handoff"}
    for rel in (
        "colleague/senses.py",
        "colleague/senses_loop.py",
        "colleague/senses_moves.py",
        "colleague/presence_engine.py",
        "colleague/agents/talker.py",
    ):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        assert not (imported & banned), f"{rel} imports {imported & banned}"


def test_talker_helper_writes_only_invocation_and_operator_input_kinds() -> None:
    src = (REPO_ROOT / "colleague" / "agents" / "talker.py").read_text(encoding="utf-8")
    for kind in ("delegate", "return", "message", "decision", "snapshot"):
        assert f'append("{kind}"' not in src
    assert 'append("operator_input"' in src
    assert "append_invocation(" in src


# ---------------------------------------------------------------------------
# AC3 — unarmed / no ledger path / headless-cortex-only: byte-identical
# ---------------------------------------------------------------------------


class TestUnarmedIsByteIdentical:
    def test_unarmed_with_a_path_writes_nothing(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path, armed=False)
        engine = _FakeEngine(_INTAKE_JSON)

        packet, record = run_senses_intake("add a retry", cfg, engine)

        assert packet is not None and record.degraded is False
        assert engine.make_complete_calls == [[]]
        assert not Path(cfg.agents_ledger_path).exists()

    def test_armed_without_a_path_writes_nothing(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path, armed=True, with_path=False)
        assert talker_ledger_path(cfg) is None
        engine = _FakeEngine(_INTAKE_JSON)

        packet, _ = run_senses_intake("add a retry", cfg, engine)

        assert packet is not None
        assert list(tmp_path.iterdir()) == []

    def test_unarmed_wrapper_is_the_identity(self) -> None:
        def complete(messages):
            return "x"

        assert recording_complete(complete, EngineConfig()) is complete
        assert recording_complete(complete, SimpleNamespace(context_budget_tokens=1)) is complete
        assert record_operator_input(EngineConfig(), "guidance") is None

    def test_senses_loop_test_double_config_reads_as_unarmed(self) -> None:
        cfg = SimpleNamespace(context_budget_tokens=24000)
        assert talker_ledger_path(cfg) is None

    def test_headless_cortex_only_has_no_senses_and_no_records(self, tmp_path: Path) -> None:
        cfg = EngineConfig(agents=True)
        cfg.agents_ledger_path = str(tmp_path / "task-7.jsonl")
        assert senses_engine_config(cfg) is None
        assert make_senses_run(cfg, "mock") is None
        assert list(tmp_path.iterdir()) == []

    def test_senses_engine_config_carries_the_ledger_path_to_the_seat(self, tmp_path: Path) -> None:
        parent = EngineConfig(
            agents=True,
            senses=SensesConfig(
                model="senses-model",
                base_url="http://senses:8003/v1",
                api_key="k",
                context_budget=32768,
            ),
        )
        parent.agents_ledger_path = str(tmp_path / "task-7.jsonl")

        seat = senses_engine_config(parent)

        assert seat is not None
        assert talker_ledger_path(seat) == parent.agents_ledger_path
        # ...and a parent WITHOUT the path leaves the seat unarmed.
        bare = EngineConfig(agents=True, senses=parent.senses)
        assert talker_ledger_path(senses_engine_config(bare)) is None

    def test_existing_ledger_keeps_its_task_id_and_seq(self, tmp_path: Path) -> None:
        cfg = _armed_config(tmp_path)
        TaskLedger(cfg.agents_ledger_path).append("operator_request", {"ref": "req"})

        rec = record_talker_invocation(cfg, [{"role": "user", "content": "q"}])

        assert rec is not None and rec.seq == 1 and rec.agent_id == "talker-task-7"

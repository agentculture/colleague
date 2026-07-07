"""Talking-to-one arc (task t8): structural proofs + byte-identical pins.

The 'talking to colleague feels like talking to one person' arc gives senses
an acknowledgment turn (t1), a proactive-update lane (t3), conversation
continuity (t4), a clarify-first lane (t7), and session middle-manager wiring
(t6). None of that may ever change what cortex actually does or reports —
this file pins the honesty conditions the spec (docs/specs/2026-07-05-talking-
to-colleague-now-feels-like-talking-to-one.md) attaches to that guarantee:

- c6/h6 — the task instruction always reaches cortex un-shortcut: no senses
  code path ever produces ``TaskResult.summary`` (the relay path — speakback
  shaping the DISPLAY string — is the ONLY senses influence on a run).
- h1 — the SAME work line run cortex-only and split yields the same
  ``TaskResult`` core (summary/status/steps); the middle-manager layer
  changes what the operator EXPERIENCES, never what cortex does or reports.
- c7/h13 — no new threading/clock imports outside the sanctioned list;
  proactive updates fire only from the existing thread-free sink boundary.
- h13/h9 — a session with senses unresolved is byte-identical to today: the
  presence lane and the rolling history never activate.
- h14 (the awareness invariant) — every ``senses:`` line the operator saw is
  reconstructable from ``TaskResult.to_dict()`` alone.
- the #206 invariant — recording an ack/update/clarify exchange never
  advances ``work_item.step_count``; narration is presentation, not work.

Structural-proof precedent: ``tests/test_senses_cannot_act.py`` already pins
that ``colleague/senses.py`` imports neither ``subprocess`` nor
``ToolExecutor`` for the cortex/senses arc; this file restates that check
(this arc adds ``run_senses_update``, a new function in the same module, so
the guarantee is re-verified here rather than assumed) and extends it with
the SESSION-side presence-lane pins the talking-to-one arc is specifically
responsible for. ``tests/test_presence.py`` already pins that
``colleague/presence.py`` imports no time/threading/datetime/subprocess — this
file does not repeat that; it pins the session-side constraint instead (the
sink boundary that is the ONLY caller of the cadence-gated update lane) plus
that ``colleague/senses.py`` itself imports no threading.

Driven the established ``test_session_presence.py`` / ``test_session_senses.py``
pattern: a scripted ``_Session`` over a recording fake ``work_fn``, with the
``run_senses_*`` seams monkeypatched for determinism (no network).
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import colleague
from colleague.cli._commands import session as session_mod
from colleague.cli._commands.session import (
    SensesSessionOptions,
    SessionIO,
    _Session,
    _WorkSink,
)
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, ContextPacket, SensesBlock, SensesRecord, Task, TaskResult
from colleague.presence import UpdateCadence
from colleague.senses import INTAKE_POINT, SPEAKBACK_POINT

_PACKAGE_DIR = Path(colleague.__file__).resolve().parent
_SENSES_PATH = _PACKAGE_DIR / "senses.py"


# ---------------------------------------------------------------------------
# Shared harness — mirrors tests/test_session_presence.py + test_session_senses.py
# (no shared conftest fixture exists for these; replicated locally, matching
# how every other session/senses test file in this suite does it).
# ---------------------------------------------------------------------------


class _CollectingOut:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.lines)


def _senses_config() -> EngineConfig:
    config = EngineConfig.resolve(model="cortex-model")
    config.senses = SensesConfig(
        model="senses-model", base_url="http://senses", api_key="k", context_budget=24000
    )
    return config


def _lane_session(tmp_path: Path, *, view: str = "ansi", config=None, cortex_only: bool = False):
    """A session for exercising the presence-lane METHODS directly (armed via
    ``_arm``) — the ``test_session_presence.py`` harness. ``work_fn`` is never
    actually invoked by these tests."""
    out, err = _CollectingOut(), _CollectingOut()
    result = TaskResult(task_id="t", status=OK, summary="s")

    def _fake_work(**kwargs: object):
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config if config is not None else _senses_config(),
        json_mode=False,
        view=view,
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=SensesSessionOptions(cortex_only=cortex_only),
    )
    return sess, out, err


def _run_session(tmp_path: Path, result: TaskResult, *, config: EngineConfig, **over):
    """A session for exercising a full ``.run()`` line on the MOCK engine — the
    ``test_session_senses.py`` harness: a scripted, recording fake ``work_fn``
    faithfully stands in for ``execute_work``, including the loop's own t6
    packet-injection convention (``result.senses = SensesBlock(mode="split",
    packet=task.context_packet)`` when a packet rode the task)."""
    out, err = _CollectingOut(), _CollectingOut()

    def _fake_work(**kwargs: object):
        task = kwargs.get("task")
        packet = getattr(task, "context_packet", None) if task is not None else None
        if packet is not None and result.senses is None:
            result.senses = SensesBlock(mode="split", packet=packet, records=[])
        return result, Path(str(tmp_path)) / ".colleague" / "art.json"

    senses_options = SensesSessionOptions(
        cortex_only=bool(over.pop("cortex_only", False)),
        debug_senses=bool(over.pop("debug_senses", False)),
    )
    sess = _Session(
        repo=tmp_path,
        engine_name="mock",
        open_pr=False,
        base="main",
        config=config,
        json_mode=False,
        view=over.pop("view", "ansi"),
        io=SessionIO(out=out, err=err),
        work_fn=_fake_work,
        senses_options=senses_options,
        **over,
    )
    return sess, out, err


def _conversation_lines(sess) -> list[str]:
    return [line.text for line in sess.state.conversation]


def _arm(sess, *, packet=None, cadence=None) -> None:
    """Arm the presence lane directly (the lane methods are the unit under test)."""
    sess._talk_active = True
    sess._talk_task_id = "tid"
    sess._talk_packet = packet
    if cadence is not None:
        sess._update_cadence = cadence


def _stub_update_sequence(monkeypatch, replies: list[str]):
    """Stub ``run_senses_update`` to return a DISTINCT reply per call — the
    #233 consecutive-line collapse would otherwise fold two identical
    ``senses:`` lines into one ``ConversationLine`` with ``count=2``, breaking
    a one-to-one rendered-line/chat-entry correspondence (h14 below)."""
    it = iter(replies)
    calls: list[dict] = []

    def _update(feed_tail, packet, senses_config, engine, **kw):
        calls.append({"feed_tail": feed_tail, "packet": packet})
        return {"update": next(it), "latency": 0.1, "tokens": 3, "degraded": False}

    monkeypatch.setattr(session_mod, "run_senses_update", _update)
    return calls


def _module_source_and_tree(path: Path) -> tuple[str, ast.Module]:
    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


# ---------------------------------------------------------------------------
# c6/h6 — the task always reaches cortex un-shortcut; senses never produces
# TaskResult.summary.
# ---------------------------------------------------------------------------


class TestSensesNeverProducesTaskResultSummary:
    def test_senses_module_imports_neither_toolexecutor_nor_subprocess(self) -> None:
        """Restates tests/test_senses_cannot_act.py's structural idiom for THIS
        arc's additions: ``colleague/senses.py`` gained ``run_senses_update``
        (task t3) since that precedent test was written, so the "no action
        surface" guarantee is re-verified here rather than assumed to still
        hold."""
        source, tree = _module_source_and_tree(_SENSES_PATH)
        modules: set[str] = set()
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
                names.update(alias.name for alias in node.names)
        assert not any(
            m == "subprocess" or m.startswith("subprocess.") for m in modules
        ), "colleague/senses.py must never import subprocess"
        assert "import subprocess" not in source
        assert "from subprocess" not in source
        assert (
            "colleague.tools" not in modules
        ), "colleague/senses.py must never import colleague.tools (ToolExecutor)"
        assert "ToolExecutor" not in names
        assert "ToolExecutor" not in source

        from tests.test_boundary import _SUBPROCESS_ALLOWED

        assert "colleague/senses.py" not in _SUBPROCESS_ALLOWED

    def test_presence_lane_methods_never_assign_to_a_summary_field(self) -> None:
        """Grep (AST-adjacent regex, matching this file's/the precedent's
        style) the source of every presence-lane method that touches a
        completed run's result for an assignment to any ``*.summary`` field.
        The speak-back path SHAPES the DISPLAY only — it must never rewrite
        the authoritative ``TaskResult.summary`` cortex produced."""
        assignment = re.compile(r"\.summary\s*=(?!=)")
        for name in (
            "_render_ack",
            "_maybe_proactive_update",
            "_maybe_clarify",
            "_finalize_split_run",
        ):
            src = inspect.getsource(getattr(_Session, name))
            assert assignment.search(src) is None, (
                f"_Session.{name} must never assign to a *.summary field — "
                "the raw cortex summary is read-only from every senses-lane method"
            )

    def test_finalize_split_run_never_mutates_result_summary(self, tmp_path, monkeypatch) -> None:
        """Direct behavioral pin (the brief's specific ask): drive
        ``_finalize_split_run`` with a stubbed speak-back that returns
        something wildly different from the raw summary, and confirm
        ``result.summary`` survives untouched — only the RETURNED display
        string is shaped (the docstring's own claim, made executable)."""
        sess, _o, _e = _lane_session(tmp_path, view="ansi")
        packet = ContextPacket(original="req", interpretation="tidy", ack="on it.")
        _arm(sess, packet=packet)

        def _speak(summary, senses_config, engine, **kw):
            return "A completely different, senses-authored shape", SensesRecord(
                point=SPEAKBACK_POINT, latency=0.1, degraded=False
            )

        monkeypatch.setattr(session_mod, "run_senses_speakback", _speak)
        result = TaskResult(
            task_id="t", status=OK, summary="RAW cortex summary — the only source of truth"
        )
        result.senses = SensesBlock(mode="split", packet=packet, records=[])
        intake_rec = SensesRecord(point=INTAKE_POINT, latency=0.1, degraded=False)

        shaped = sess._finalize_split_run(result, intake_rec)

        assert shaped == "A completely different, senses-authored shape"
        assert result.summary == "RAW cortex summary — the only source of truth"


# ---------------------------------------------------------------------------
# h1 — cortex-only vs split TaskResult core equality.
# ---------------------------------------------------------------------------


class TestCortexOnlyVsSplitTaskResultCoreEquality:
    def test_same_work_line_cortex_only_and_split_share_task_result_core(
        self, tmp_path, monkeypatch
    ) -> None:
        """Run the SAME work line through the session twice on the mock
        engine: once with the senses front door bypassed (--cortex-only) and
        once split with every senses function stubbed deterministically.
        ``summary``/``status``/``steps`` — the TaskResult CORE — must be
        identical; the split run may ONLY differ under the omit-when-None
        ``senses`` key (h1: 'the middle-manager layer changes what the
        operator EXPERIENCES, never what cortex does or reports')."""
        packet = ContextPacket(
            original="fix the flaky parser test",
            interpretation="repair the intermittently failing parser test",
            confidence=0.9,
            task_type="bugfix",
            ack="on it — repairing the test now.",
        )

        def _intake(text, senses_config, engine, **kw):
            return packet, SensesRecord(point=INTAKE_POINT, latency=0.1, tokens=8, degraded=False)

        def _speak(summary, senses_config, engine, **kw):
            return "Here's the shaped version of what cortex did.", SensesRecord(
                point=SPEAKBACK_POINT, latency=0.1, tokens=6, degraded=False
            )

        monkeypatch.setattr(session_mod, "run_senses_intake", _intake)
        monkeypatch.setattr(session_mod, "run_senses_speakback", _speak)

        result_cortex_only = TaskResult(task_id="t", status=OK, summary="RAW cortex summary")
        sess_a, _oa, _ea = _run_session(
            tmp_path, result_cortex_only, config=_senses_config(), view="ansi", cortex_only=True
        )
        sess_a.run(iter(["fix the flaky parser test"]))

        result_split = TaskResult(task_id="t", status=OK, summary="RAW cortex summary")
        sess_b, _ob, _eb = _run_session(
            tmp_path, result_split, config=_senses_config(), view="ansi", cortex_only=False
        )
        sess_b.run(iter(["fix the flaky parser test"]))

        # The core: byte-identical across both modes.
        assert result_cortex_only.summary == result_split.summary == "RAW cortex summary"
        assert result_cortex_only.status == result_split.status == OK
        assert result_cortex_only.steps == result_split.steps == []
        assert result_cortex_only.changed_files == result_split.changed_files == []

        dict_a = result_cortex_only.to_dict()
        dict_b = result_split.to_dict()
        # They DO differ — senses ran differently in each mode — but only
        # under the omit-when-None "senses" key.
        assert dict_a["senses"]["mode"] == "cortex-only"
        assert dict_a["senses"]["packet"] is None
        assert dict_b["senses"]["mode"] == "split"
        assert dict_b["senses"]["packet"] is not None
        del dict_a["senses"]
        del dict_b["senses"]
        assert dict_a == dict_b, "cortex-only vs split must differ ONLY under the senses key"


# ---------------------------------------------------------------------------
# c7/h13 — no new threading/clock imports; updates fire only from the
# existing thread-free sink boundary.
# ---------------------------------------------------------------------------


class TestNoNewThreadingOrClockImports:
    def test_maybe_proactive_update_has_exactly_one_call_site_in_colleague_package(
        self,
    ) -> None:
        """tests/test_presence.py already pins that colleague/presence.py
        imports no time/threading/datetime/subprocess (not repeated here).
        This pins the SESSION-side half of c7/h13: the cadence-gated update
        lane fires from exactly one place in the whole ``colleague`` package —
        the existing thread-free progress-sink boundary, ``_WorkSink.__call__``
        — never from a new thread, timer, or callback."""
        occurrences: list[tuple[Path, int, str]] = []
        for py_file in sorted(_PACKAGE_DIR.rglob("*.py")):
            source = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(source.splitlines(), start=1):
                if "_maybe_proactive_update" in line:
                    occurrences.append((py_file, lineno, line.strip()))

        assert len(occurrences) == 2, (
            "expected exactly 2 mentions of _maybe_proactive_update in colleague/ "
            f"(the def + its one caller), found {len(occurrences)}: {occurrences}"
        )
        def_sites = [o for o in occurrences if o[2].startswith("def _maybe_proactive_update")]
        call_sites = [o for o in occurrences if o not in def_sites]
        assert len(def_sites) == 1
        assert len(call_sites) == 1

        call_file, _call_lineno, call_text = call_sites[0]
        assert call_file.name == "session.py"
        # Structurally: the one call site sits inside _WorkSink.__call__ (the
        # #38/#206 progress sink) — the same boundary the concurrent talk lane
        # polls at, never a new thread/timer.
        sink_source = inspect.getsource(_WorkSink.__call__)
        assert call_text in sink_source, (
            "the sole _maybe_proactive_update call site must live inside "
            "_WorkSink.__call__, not any other method"
        )

    def test_senses_module_imports_no_threading(self) -> None:
        _source, tree = _module_source_and_tree(_SENSES_PATH)
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
        assert not any(
            m == "threading" or m.startswith("threading.") for m in modules
        ), "colleague/senses.py must never import threading"
        assert not any(
            m == "concurrent.futures" or m.startswith("concurrent.futures") for m in modules
        ), "colleague/senses.py must never import concurrent.futures"


# ---------------------------------------------------------------------------
# h13/h9 — a session with senses unresolved is byte-identical to today.
# ---------------------------------------------------------------------------


class TestSensesUnresolvedSessionByteIdentical:
    def test_run_with_no_senses_config_produces_pre_arc_conversation_and_artifact(
        self, tmp_path, monkeypatch
    ) -> None:
        """RUN-level pin (test_session_presence.py already pins the individual
        lane methods as no-ops off-armed; this drives a full ``sess.run()``
        line with NO senses model resolved at all and pins the exact
        resulting conversation + artifact shape, matching
        test_session_senses.py's ``test_no_senses_config_is_byte_identical``
        one level up, at the actual ``.run()`` entry point)."""

        def _boom_intake(*a, **k):
            raise AssertionError("intake must not run without a senses model")

        def _boom_update(*a, **k):
            raise AssertionError("update must not run without a senses model")

        monkeypatch.setattr(session_mod, "run_senses_intake", _boom_intake)
        monkeypatch.setattr(session_mod, "run_senses_update", _boom_update)

        result = TaskResult(task_id="t", status=OK, summary="raw summary")
        plain_config = EngineConfig.resolve(model="cortex-model")  # no senses declared
        sess, _out, _err = _run_session(tmp_path, result, config=plain_config, view="ansi")

        rc = sess.run(iter(["do the thing"]))

        assert rc == 0
        assert result.senses is None  # omitted entirely — byte-identical artifact
        assert "senses" not in result.to_dict()
        # The exact pre-arc conversation shape — no ack/update/clarify line
        # ever joins it.
        assert _conversation_lines(sess) == [
            "do the thing",
            "→ work: do the thing",
            "ok: raw summary [(none)]",
        ]
        assert sess._history == []
        assert sess._senses_chat == []
        assert sess._talk_active is False


# ---------------------------------------------------------------------------
# h14 — the awareness invariant: reconstructable from the artifact alone.
# ---------------------------------------------------------------------------


class TestReconstructableFromArtifactAlone:
    def test_every_rendered_senses_line_has_a_one_to_one_chat_entry(
        self, tmp_path, monkeypatch
    ) -> None:
        """Drive the ack, a proactive update, and a clarify exchange directly,
        then finalize the run. Every ``senses:``-prefixed conversation line
        the operator actually saw must correspond, IN ORDER, to a
        senses-authored chat entry recorded on ``TaskResult.senses.chat`` —
        checked both on the live ``_senses_chat`` list AND on the artifact's
        own ``to_dict()`` output, so the operator's whole exchange is provably
        reconstructable from the artifact alone with no other state."""
        sess, _o, _e = _lane_session(tmp_path, view="ansi")
        packet = ContextPacket(
            original="make the tests faster",
            interpretation="speed up the test suite",
            confidence=0.2,
            task_type="perf",
            omissions=["which suite"],
            ack="on it — speeding up the test suite now.",
        )
        _arm(sess, packet=packet, cadence=UpdateCadence(every_steps=100, max_updates=4))
        _stub_update_sequence(
            monkeypatch, ["reading the pytest config now", "editing the slow fixture"]
        )

        # 1. the ack (t1/t6, c9/h2).
        sess._render_ack(packet.ack)
        # 2. two proactive updates (t3/t6, c10/h4) — distinct phases so the
        #    #233 collapse never folds them into one line.
        sess._maybe_proactive_update("", "synthesizing…")
        sess._maybe_proactive_update("", "compacting…")
        # 3. a clarify exchange (t7, c19/h8) — an explicit go-word dispatches
        #    immediately, so only the SENSES-authored question is logged with
        #    the "senses:" prefix (the operator's own echoed "go" is not).
        sess._read_next = iter(["go"]).__next__
        task = Task.new(str(tmp_path), packet.original)
        sess._maybe_clarify(task, packet, sess.config, object())

        rendered = [
            ln[len("senses: ") :] for ln in _conversation_lines(sess) if ln.startswith("senses: ")
        ]
        assert rendered == [
            packet.ack,
            "reading the pytest config now",
            "editing the slow fixture",
            "before I hand this to cortex — your request left 'which suite' "
            "unspecified. Add details, or say 'go' to dispatch as-is.",
        ]

        def _senses_authored_texts(chat: list[dict]) -> list[str]:
            texts: list[str] = []
            for entry in chat:
                if entry.get("kind") in ("ack", "update"):
                    texts.append(entry["text"])
                elif entry.get("kind") == "clarify" and entry.get("role") == "senses":
                    texts.append(entry["text"])
            return texts

        assert _senses_authored_texts(sess._senses_chat) == rendered

        # Now finalize and confirm the SAME correspondence holds reading ONLY
        # the serialized artifact — no live session state.
        def _speak(summary, senses_config, engine, **kw):
            return "final shaped reply", SensesRecord(
                point=SPEAKBACK_POINT, latency=0.1, degraded=False
            )

        monkeypatch.setattr(session_mod, "run_senses_speakback", _speak)
        result = TaskResult(task_id="t", status=OK, summary="RAW")
        result.senses = SensesBlock(mode="split", packet=packet, records=[])
        intake_rec = SensesRecord(point=INTAKE_POINT, latency=0.1, degraded=False)
        sess._finalize_split_run(result, intake_rec)

        payload = result.to_dict()["senses"]
        assert _senses_authored_texts(payload["chat"]) == rendered


# ---------------------------------------------------------------------------
# The #206 invariant — recording ack/update/clarify never advances
# work_item.step_count.
# ---------------------------------------------------------------------------


class TestThe206InvariantHoldsForThePresenceLane:
    def test_ack_update_and_clarify_never_advance_step_count(self, tmp_path, monkeypatch) -> None:
        from dataclasses import replace

        from agentfront.taui.state import WorkItem

        sess, _o, _e = _lane_session(tmp_path, view="ansi")
        sess.state = replace(
            sess.state,
            work_item=WorkItem(task_id="t", engine="mock", step_count=3, running=True),
        )
        packet = ContextPacket(
            original="tidy the config",
            interpretation="tidy the config module",
            confidence=0.1,
            task_type="refactor",
            omissions=["which config file"],
            ack="on it — tidying the config now.",
        )
        _arm(sess, packet=packet, cadence=UpdateCadence(every_steps=100, max_updates=4))
        _stub_update_sequence(monkeypatch, ["reading the config module now"])

        sess._render_ack(packet.ack)
        assert sess.state.work_item.step_count == 3

        sess._maybe_proactive_update("", "synthesizing…")  # a phase notice — never a step
        assert sess.state.work_item.step_count == 3

        sess._read_next = iter(["go"]).__next__
        task = Task.new(str(tmp_path), packet.original)
        sess._maybe_clarify(task, packet, sess.config, object())
        assert sess.state.work_item.step_count == 3

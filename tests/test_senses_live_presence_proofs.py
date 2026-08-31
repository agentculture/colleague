"""Structural proofs + degradation pins for the senses live-presence + voice
arc (task t9). Tests only -- no production code changes.

Seven invariants from the build's honesty conditions, one section each:

1. Senses talk lane is tools-off (structural).
2. No code path returns a senses reply as the TASK answer.
3. Flight-file-only injection channel.
4. Threads/subprocess allow-lists unchanged (the new modules stay clean).
5. Kill-senses/stt/tts-mid-run completes as cortex-only + one notice.
6. No-lane TaskResult byte-identical (e2e shape).
7. Awareness reconstructable from feed + artifact alone (the KEY proof).

Several of these are ALREADY pinned exhaustively by earlier task waves --
this file cites those tests by name rather than duplicating them, and adds
only genuine gaps (new call sites, new degradation branches, the aggregate
cross-file proofs, and the reconstruction proof itself). See the docstring
of each test/class for the specific citation.
"""

from __future__ import annotations

import ast
import io
import time
import urllib.error
from pathlib import Path

from colleague import flight, voice, voice_devices
from colleague.cli._commands.talk import run_talk_repl
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.loop import ModelResponse, ToolCall, run
from colleague.senses import run_senses_talk

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_source(rel_path: str) -> str:
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _session_surface() -> tuple[str, ...]:
    """Every module the session's presence surface is spread across.

    Was just ``session.py``. The hard-1000-line-file-limit arc decomposed that
    file into ``_session_*.py`` mixin siblings, which moved two of the three
    ``flight.append_guidance`` relay call sites out of it — so a check that
    greps only ``session.py`` silently covers LESS than it did, while still
    passing. Enumerating the siblings by glob restores the original reach and
    keeps it as new siblings appear.
    """
    package = _REPO_ROOT / "colleague" / "cli" / "_commands"
    siblings = sorted(p.name for p in package.glob("_session_*.py"))
    return ("session.py",) + tuple(siblings)


def _session_surface_paths() -> tuple[str, ...]:
    return tuple(f"colleague/cli/_commands/{name}" for name in _session_surface())


def _assigned_attribute_names(source: str) -> set[str]:
    """Every attribute name that is ever an ASSIGNMENT TARGET in *source*
    (``x.foo = ...`` / ``x.foo += ...``), via AST -- catches an indirect or
    reformatted assignment a plain grep could miss."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def _list_dir_turn() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("c", "list_dir", {"path": "."})])


def _finish_turn() -> ModelResponse:
    return ModelResponse(tool_calls=[ToolCall("f", "finish", {"summary": "done"})])


def _read_feed(repo: Path, task_id: str) -> list[dict]:
    fp = flight.feed_path(repo, task_id)
    if not fp.exists():
        return []
    import json

    return [json.loads(line) for line in fp.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. Senses talk lane is tools-off (structural)
# ---------------------------------------------------------------------------


class TestTalkLaneIsToolsOff:
    """The no-subprocess / no-ToolExecutor import check on ``colleague/senses.py``
    is ALREADY pinned exhaustively by:

    - ``tests/test_senses_cannot_act.py::TestSensesModuleHasNoActionSurface``
      (a full AST import-walk, plus a grep-level belt-and-suspenders check).
    - ``tests/test_senses_talk.py::test_senses_module_still_has_no_io_surface_or_tool_executor``
      (a string-level check, written alongside ``run_senses_talk`` itself).

    Both predate this file; we do not re-derive the full AST walk here. What
    IS new: those two checks assert ``tools=[]`` appears at *at least* 3 call
    sites (intake/speakback/media-bridge) -- a bound written before
    ``run_senses_talk`` existed. This class raises that floor to 4 and pins
    the 4th call site by name, and adds the BEHAVIORAL half (a spy
    ``make_complete``) as the single-file aggregate proof this task asks for.
    """

    def test_every_run_senses_function_including_talk_is_tools_off_by_source(self) -> None:
        source = _read_source("colleague/senses.py")
        assert source.count("tools=[]") >= 4, (
            "expected (at least) 4 tools-off call sites -- intake, speakback, "
            "media-bridge, and the live-presence talk lane -- found fewer; a new "
            "senses completion call site may have been added without the "
            "structural tools=[] contract"
        )
        tree = ast.parse(source)
        talk_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run_senses_talk"
        )
        talk_src = ast.get_source_segment(source, talk_fn)
        assert talk_src is not None
        assert "tools=[]" in talk_src, (
            "run_senses_talk's own function body must issue its completion "
            "with an explicit empty tool list"
        )

    def test_run_senses_talk_calls_make_complete_with_an_explicit_empty_list(self) -> None:
        """Behavioral half: a spy ``make_complete`` records exactly ``tools=[]`` --
        never ``None``, never a populated schema. Mirrors
        ``tests/test_senses_talk.py::TestToolsOff`` (kept there as the
        function-level unit proof); reproduced here so this file stands alone
        as the arc's single aggregate structural-proof index.
        """
        calls: list[object] = []

        def spy_make_complete(config, tools=None):
            calls.append(tools)

            def complete(messages):
                return ModelResponse(content='{"answer": "ok", "relay": false, "relay_text": ""}')

            return complete

        record = run_senses_talk(
            "status?",
            feed_tail="",
            packet=None,
            task_state=None,
            senses_config=EngineConfig(model="senses-model", context_budget_tokens=1000),
            make_complete=spy_make_complete,
            make_count_tokens=lambda messages: sum(
                len(str(m.get("content") or "")) for m in messages
            ),
        )

        assert calls == [[]]
        assert calls[0] is not None
        assert record is not None and record["degraded"] is False

    def test_senses_module_still_has_no_subprocess_or_toolexecutor(self) -> None:
        """A cheap corroborating string check so this file's own assertions
        about ``colleague/senses.py`` don't depend on a reader jumping to
        ``test_senses_cannot_act.py`` / ``test_senses_talk.py`` to confirm the
        module-level claim this class's docstring makes."""
        source = _read_source("colleague/senses.py")
        assert "import subprocess" not in source
        assert "ToolExecutor" not in source


# ---------------------------------------------------------------------------
# 2. No code path returns a senses reply as the TASK answer
# ---------------------------------------------------------------------------


class TestSensesReplyNeverBecomesTheTaskAnswer:
    """The task answer always comes from cortex (the loop's ``finish``), never
    from senses -- a talk-lane answer is advisory display/chat-log only.
    """

    def test_talk_and_session_modules_never_assign_to_dot_summary(self) -> None:
        """AST-level: neither ``talk.py`` nor ``session.py`` ever has ``.summary``
        as an assignment target. ``session.py`` legitimately READS
        ``result.summary`` (e.g. ``_finalize_split_run`` shapes a DISPLAY-only
        speakback string from it, per its own docstring: "The raw cortex
        summary on result.summary is never mutated") -- reading is fine; this
        pins that it is never the target of an assignment."""
        for rel_path in ("colleague/cli/_commands/talk.py",) + _session_surface_paths():
            source = _read_source(rel_path)
            assigned = _assigned_attribute_names(source)
            assert "summary" not in assigned, (
                f"{rel_path} must never assign to a `.summary` attribute -- the "
                "task answer comes from cortex's own finish, never a senses reply"
            )

    def test_talk_module_never_constructs_or_touches_a_taskresult(self) -> None:
        """``colleague/cli/_commands/talk.py`` -- the ``colleague talk`` REPL --
        never even references ``TaskResult`` (it only relays via the flight
        control/chat files); confirmed structurally, not just for `.summary`."""
        source = _read_source("colleague/cli/_commands/talk.py")
        assert "TaskResult" not in source

    def test_talk_answer_only_reaches_stdout_and_the_flight_chat_log(self, tmp_path: Path) -> None:
        """Behavioral companion to the AST check above: running a full talk
        turn through the real REPL core and inspecting every side effect --
        the answer lands in the printed lines and the flight chat log, never
        anywhere resembling a work-item result."""
        flight.arm(tmp_path, "tid")
        lines: list[str] = []

        def stub_talk_fn(message, **kwargs):
            return {
                "answer": "reading the config",
                "relay": False,
                "relay_text": "",
                "latency": 0.2,
                "degraded": False,
                "tokens": 5,
            }

        rc = run_talk_repl(
            tmp_path,
            "tid",
            EngineConfig.resolve(repo_path=Path("/nonexistent-does-not-matter")),
            input_fn=iter(["how's it going?", "/quit"]),
            out=lines.append,
            talk_fn=stub_talk_fn,
        )
        assert rc == 0
        assert any("reading the config" in line for line in lines)
        chat = flight.read_chat(tmp_path, "tid")
        assert chat and chat[0]["answer"] == "reading the config"
        # No artifact file of any kind was written by the talk REPL itself.
        assert not (tmp_path / ".colleague" / "artifacts").exists()


# ---------------------------------------------------------------------------
# 3. Flight-file-only injection channel
# ---------------------------------------------------------------------------


class TestFlightFileIsTheOnlyInjectionChannel:
    """The ONLY way an operator message becomes cortex guidance is
    ``flight.append_guidance`` writing the control file, read by the loop's
    ``_flight_stop_requested`` at a turn boundary. This class pins that no
    OTHER path exists.
    """

    def test_talk_and_session_modules_never_import_the_loop(self) -> None:
        """Neither the ``colleague talk`` REPL nor the session's talk-lane
        methods import anything from ``colleague.loop`` -- they cannot reach
        ``ctx.messages`` even by accident, since they never hold a reference
        to the loop's internal work context at all."""
        for rel_path in ("colleague/cli/_commands/talk.py",) + _session_surface_paths():
            source = _read_source(rel_path)
            assert "colleague.loop" not in source
            assert "ctx.messages" not in source
            assert ".messages.append(" not in source

    def test_loop_reads_guidance_from_exactly_one_call_site(self) -> None:
        """``colleague/loop.py`` calls ``ctx.flight.read_control()`` -- the ONLY
        consumer of the control file's guidance list -- from exactly one
        place, and appends the operator's message to ``ctx.messages`` from
        exactly one place. Two call sites would mean a second, undocumented
        injection path exists."""
        source = _read_source("colleague/loop.py")
        assert source.count("read_control()") == 1
        assert (
            source.count('ctx.messages.append({"role": "user", "content": f"[pilot guidance]') == 1
        )

    def test_talk_and_session_relay_exclusively_via_flight_append_guidance(self) -> None:
        """Both live-presence relay callers -- ``colleague talk`` (task t6) and
        the session's concurrent lane (task t7) -- write a relayed instruction
        through ``flight.append_guidance`` only; this is the pragmatic
        behavioral companion to the structural checks above: writing directly
        to the control file (mimicking what the operator's own relay does) is
        picked up by the loop at the very next turn boundary -- the SAME
        mechanism, exercised end to end (see also
        ``tests/test_talk_lane.py::test_applied_guidance_recorded_on_feed_and_artifact``,
        which already pins the loop side of this in isolation)."""
        assert "flight.append_guidance(" in _read_source("colleague/cli/_commands/talk.py")
        # The session's relay used to sit wholly in session.py; the
        # hard-1000-line-file-limit arc spread it across _session_*.py mixins.
        # So this is a check on the SURFACE, not on every file in it: a module
        # with no relay at all is fine, a relay through some other channel is
        # not (the per-file absence checks above enforce that half).
        relaying = [
            rel
            for rel in _session_surface_paths()
            if "flight.append_guidance(" in _read_source(rel)
        ]
        assert relaying, (
            "no module of the session surface relays through flight.append_guidance -- "
            f"searched {list(_session_surface_paths())}"
        )

    def test_guidance_written_via_flight_append_guidance_is_applied_at_the_next_boundary(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: calling ``flight.append_guidance`` directly (the exact
        call every talk-lane client makes) is picked up by the real loop at
        the next turn boundary and lands in ``ctx.messages`` -- proving the
        file IS the channel, not merely that no other channel is referenced."""
        task = Task.new(str(tmp_path), "scan", watch=True)
        seen_messages: list[list[dict]] = []
        turns = {"n": 0}

        def complete(messages: list[dict]) -> ModelResponse:
            seen_messages.append(list(messages))
            n = turns["n"]
            turns["n"] += 1
            if n == 0:
                flight.append_guidance(tmp_path, task.id, "steer to plan B")
                return _list_dir_turn()
            return _finish_turn()

        result = run(complete, task, max_steps=10)
        assert result.status == OK
        # The turn AFTER the guidance was written (turn index 1) carries it.
        injected = [
            m
            for m in seen_messages[1]
            if "[pilot guidance] steer to plan B" in str(m.get("content", ""))
        ]
        assert len(injected) == 1


# ---------------------------------------------------------------------------
# 4. Threads/subprocess allow-lists unchanged
# ---------------------------------------------------------------------------


class TestNewModulesStayOffTheSubprocessAndThreadAllowLists:
    """The arc's three NEW modules -- ``colleague/voice.py`` (pure urllib),
    ``colleague/voice_devices.py`` (sounddevice/soundfile behind the ``[voice]``
    extra), and ``colleague/cli/_commands/talk.py`` (the REPL) -- must never
    import ``subprocess`` or a threading primitive. ``colleague/senses.py`` is
    reconfirmed too (already pinned elsewhere; see the class above)."""

    _NEW_MODULES = (
        "colleague/voice.py",
        "colleague/voice_devices.py",
        "colleague/cli/_commands/talk.py",
        "colleague/senses.py",
    )

    def test_no_subprocess_import(self) -> None:
        for rel_path in self._NEW_MODULES:
            source = _read_source(rel_path)
            assert "import subprocess" not in source, f"{rel_path} must not import subprocess"
            assert "from subprocess" not in source, f"{rel_path} must not import subprocess"

    def test_no_new_thread_or_concurrent_futures_import(self) -> None:
        for rel_path in self._NEW_MODULES:
            source = _read_source(rel_path)
            assert "import threading" not in source, f"{rel_path} must not import threading"
            assert "from threading" not in source, f"{rel_path} must not import threading"
            assert "concurrent.futures" not in source, (
                f"{rel_path} must not import concurrent.futures -- threads stay "
                "confined to colleague/subagents.py"
            )

    def test_new_modules_are_absent_from_the_boundary_allow_lists(self) -> None:
        """Cross-checked against the shared authority in
        ``tests/test_boundary.py`` -- confirms the allow-lists themselves were
        never widened to admit these modules."""
        from tests.test_boundary import _SUBPROCESS_ALLOWED, _THREADS_ALLOWED

        for rel_path in (
            "colleague/voice.py",
            "colleague/voice_devices.py",
            "colleague/cli/_commands/talk.py",
        ):
            assert rel_path not in _SUBPROCESS_ALLOWED, (
                f"{rel_path} must not be added to _SUBPROCESS_ALLOWED -- it has "
                "no subprocess use to sanction"
            )
            assert rel_path not in _THREADS_ALLOWED


# ---------------------------------------------------------------------------
# 5. Kill-senses/stt/tts-mid-run completes as cortex-only + one notice
# ---------------------------------------------------------------------------


class TestVoiceDegradationGaps:
    """``tests/test_voice.py`` already pins: an HTTP 500 error degrades
    ``transcribe`` to ``None`` + one stderr notice
    (``test_transcribe_degrades_on_http_error``), and a JSON error body
    degrades ``synthesize`` to ``None`` + one notice, writing no file
    (``test_synthesize_degrades_on_no_audio_json``). This class adds the two
    genuinely uncovered branches the task calls out: a raw connection failure
    (not an HTTP error status) for ``transcribe``, and an HTTP 502 (the rig's
    actual documented failure mode, per the media-input arc's CLAUDE.md
    bullet) for ``synthesize``.
    """

    def test_transcribe_degrades_on_connection_refused(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        audio = tmp_path / "a.wav"
        audio.write_bytes(b"x")

        def boom(*a, **k):
            raise ConnectionRefusedError("connection refused")

        monkeypatch.setattr(voice.urllib.request, "urlopen", boom)
        assert voice.transcribe(audio, stt_model="stt", base_url="http://x/v1") is None
        assert "stt transcribe failed" in capsys.readouterr().err

    def test_synthesize_degrades_on_502(self, tmp_path: Path, monkeypatch, capsys) -> None:
        def boom(*a, **k):
            raise urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b""))

        monkeypatch.setattr(voice.urllib.request, "urlopen", boom)
        out = tmp_path / "out.wav"
        assert voice.synthesize("hi", tts_model="tts", base_url="http://x/v1", out_path=out) is None
        assert not out.exists()
        assert "tts synthesize failed" in capsys.readouterr().err


class TestVoiceDevicesPlaybackExceptionGap:
    """``tests/test_voice_devices.py`` already pins the MISSING-extra path
    (``test_play_without_extra_returns_false_and_keeps_wav``). This adds the
    uncovered branch: the extra IS importable but playback itself raises mid-
    call (a device error) -- ``play`` must still degrade to ``False`` and
    leave the written wav untouched, never lose it or raise."""

    def test_play_degrades_on_playback_exception_and_keeps_wav(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        wav = tmp_path / "out.wav"
        wav.write_bytes(b"RIFF\x00\x00WAVEdata")

        class _FakeSoundfile:
            @staticmethod
            def read(path):
                raise RuntimeError("device busy")

        class _FakeSounddevice:
            @staticmethod
            def play(data, samplerate):  # pragma: no cover - unreachable, read() fails first
                raise AssertionError("play() must not be reached when read() fails")

            @staticmethod
            def wait():  # pragma: no cover
                pass

        monkeypatch.setattr(
            voice_devices, "_import_audio", lambda: (_FakeSounddevice, _FakeSoundfile)
        )

        ok = voice_devices.play(wav)

        assert ok is False
        assert wav.exists()
        assert wav.read_bytes() == b"RIFF\x00\x00WAVEdata"
        assert "playback failed" in capsys.readouterr().err


class TestTalkRepLDegradesAgainstADeadSensesEndpoint:
    """The integration-style proof the task asks for: a talk turn through the
    REAL ``run_senses_talk`` function (not a stub) against a senses endpoint
    that raises on every call completes cleanly -- cortex keeps driving, the
    operator sees a safe advisory notice instead of a crash, and an explicit
    ``cortex:``-prefixed relay still survives (the guaranteed-relay path,
    unit-pinned in isolation by
    ``tests/test_senses_talk.py::TestRelayPrefixOverride::test_prefix_override_survives_a_degraded_call``;
    this proves it survives the FULL REPL turn, not just the bare function)."""

    def test_talk_turn_against_dead_senses_endpoint_degrades_cleanly(self, tmp_path: Path) -> None:
        flight.arm(tmp_path, "tid")
        lines: list[str] = []

        def dead_make_complete(config, tools=None):
            def complete(messages):
                raise ConnectionRefusedError("senses endpoint is down")

            return complete

        def resolve_engine_seam(config, engine_name):
            return (
                EngineConfig(model="senses-model", context_budget_tokens=1000),
                dead_make_complete,
                None,
            )

        rc = run_talk_repl(
            tmp_path,
            "tid",
            EngineConfig.resolve(repo_path=Path("/nonexistent-does-not-matter")),
            input_fn=iter(["cortex: focus on tests", "/quit"]),
            out=lines.append,
            talk_fn=run_senses_talk,  # the REAL function, not a stub
            resolve_engine_seam=resolve_engine_seam,
        )

        assert rc == 0  # the REPL never crashes / never raises
        assert any("senses is unavailable" in line for line in lines)
        # The explicit prefix override still forces the relay even though senses
        # itself never answered.
        assert any("-> cortex: focus on tests" in line for line in lines)

        chat = flight.read_chat(tmp_path, "tid")
        assert len(chat) == 1
        assert chat[0]["degraded"] is True


# ---------------------------------------------------------------------------
# 6. No-lane TaskResult byte-identical (e2e shape)
# ---------------------------------------------------------------------------


class TestNoLaneArtifactByteIdentical:
    """``tests/test_talk_lane.py::test_flight_without_live_lane_leaves_senses_none``
    already pins that a watched-but-quiet run leaves ``result.senses`` at
    ``None``, and
    ``tests/test_talk_lane.py::test_senses_block_omits_empty_live_lane_keys``
    already pins that ``SensesBlock.to_dict()`` omits ``injections``/``chat``
    when empty -- both cited here, not duplicated. This class adds the
    genuinely new check: a full artifact-shape comparison between an
    UNWATCHED run and a WATCHED-but-silent run, proving the two serialize
    byte-identically (not merely that one key is absent)."""

    def test_watched_but_silent_run_serializes_byte_identically_to_unwatched(
        self, tmp_path: Path
    ) -> None:
        def complete(_messages: list[dict]) -> ModelResponse:
            return _finish_turn()

        plain_task = Task.new(str(tmp_path), "scan")
        plain_result = run(complete, plain_task, max_steps=5)

        watched_task = Task.new(str(tmp_path), "scan", watch=True)
        watched_result = run(complete, watched_task, max_steps=5)

        plain_dict = plain_result.to_dict()
        watched_dict = watched_result.to_dict()
        # task_id is random and wall-clock timing varies per run; normalize both
        # before the structural compare (everything else must match exactly).
        for d in (plain_dict, watched_dict):
            d.pop("task_id")
            d["stats"].pop("started_at")
            d["stats"].pop("duration_seconds")

        assert "senses" not in watched_dict
        assert plain_dict == watched_dict


# ---------------------------------------------------------------------------
# 7. Awareness reconstructable from feed + artifact alone (the KEY proof)
# ---------------------------------------------------------------------------


class TestAwarenessReconstructableFromFeedAndArtifactAlone:
    """A reviewer reading ONLY the flight feed + the artifact must be able to
    reconstruct exactly what the operator saw and injected mid-run -- the
    spec's honesty condition h8. This runs a watched work item during which
    TWO guidance injections and TWO chat exchanges happen, then reconstructs
    the full transcript from ``TaskResult.senses`` alone (never referencing
    the live feed capture for the reconstruction itself), and separately
    cross-checks the feed agrees. An unrecorded injection or an unlabeled
    answer would shrink one of the recovered counts below 2 and fail here.
    """

    def test_full_transcript_recoverable_from_the_artifact_alone(self, tmp_path: Path) -> None:
        task = Task.new(str(tmp_path), "scan", watch=True)
        injected_texts = ["pivot to plan B", "focus on tests"]
        chat_exchanges = [
            {"message": "how's it going?", "answer": "reading the config"},
            {"message": "what now?", "answer": "focusing on tests, per your steer"},
        ]
        captured: dict[str, list[dict]] = {}
        turns = {"n": 0}

        def complete(_messages: list[dict]) -> ModelResponse:
            n = turns["n"]
            turns["n"] += 1
            if n < 2:
                flight.append_guidance(tmp_path, task.id, injected_texts[n])
                flight.append_chat(
                    tmp_path,
                    task.id,
                    {
                        "message": chat_exchanges[n]["message"],
                        "answer": chat_exchanges[n]["answer"],
                        "relay": True,
                        "relay_text": injected_texts[n],
                        "latency": 0.3,
                        "degraded": False,
                        "at": time.time(),
                    },
                )
                return _list_dir_turn()
            # By this turn BOTH injections have already been applied at the two
            # prior boundaries -- snapshot the feed here, before the finish-time
            # reap, as "what a live operator watching would have seen."
            captured["final_feed"] = _read_feed(tmp_path, task.id)
            return _finish_turn()

        result = run(complete, task, max_steps=10)
        assert result.status == OK

        # --- Reconstruct from the ARTIFACT alone -----------------------------
        assert result.senses is not None
        recovered_injections = {entry["text"] for entry in result.senses.injections}
        recovered_answers = {entry["answer"] for entry in result.senses.chat}
        recovered_messages = {entry["message"] for entry in result.senses.chat}

        assert recovered_injections == set(injected_texts)
        assert recovered_messages == {c["message"] for c in chat_exchanges}
        assert recovered_answers == {c["answer"] for c in chat_exchanges}
        # The exact counts -- an unrecorded injection or an unlabeled answer
        # would silently shrink one of these below 2 and fail this assertion.
        assert len(result.senses.injections) == 2
        assert len(result.senses.chat) == 2

        # --- Cross-check against the live flight feed ------------------------
        # (what an operator watching in real time would have seen) -- feed and
        # artifact agree, so a reviewer with EITHER one alone reconstructs the
        # same picture.
        feed_injection_lines = [
            rec.get("intent", "") for rec in captured["final_feed"] if rec.get("tool") is None
        ]
        for text in injected_texts:
            assert any(f"[guidance applied] {text}" in line for line in feed_injection_lines)

"""Tests for the senses coordination-move protocol + executor (task t1).

Surfaces under test (:mod:`colleague.senses_moves`):

1. The move list is enumerated in exactly ONE place (:data:`MOVE_SCHEMA`),
   and the executor refuses any move name outside it — even one a model
   actually emits — as a recorded no-op, never raising and never invoking
   any injected callback.
2. Structural boundary: the module imports no ``subprocess`` and no
   :class:`colleague.tools.ToolExecutor` (mirrors
   ``tests/test_senses_cannot_act.py``'s pin on ``colleague/senses.py``), and
   it never builds anything shaped like an OpenAI tool schema — there is no
   code path here that could ever hand a non-empty ``tools=`` list to a
   completion.
3. :func:`parse_move` degrades malformed/truncated/unparseable completion
   text to a ``reply_to_operator`` move carrying the raw text, verbatim,
   never crashing.

No network, no I/O: every callback is a plain Python fake recording what it
was called with.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from colleague.senses_moves import (
    MOVE_CLARIFY,
    MOVE_DISPATCH_TO_CORTEX,
    MOVE_GUIDE_CORTEX,
    MOVE_READ_FLIGHT,
    MOVE_REPLY_TO_OPERATOR,
    MOVE_SCHEMA,
    MOVE_WAIT,
    MOVES,
    MoveResult,
    SensesMoveExecutor,
    build_moves_instruction,
    parse_move,
)

# ---------------------------------------------------------------------------
# 1a — the move list is enumerated in exactly one place.
# ---------------------------------------------------------------------------


def test_moves_enumerated_in_exactly_one_place() -> None:
    """MOVES is derived from MOVE_SCHEMA's keys — a single source of truth."""
    assert MOVES == frozenset(MOVE_SCHEMA)
    assert MOVES == {
        MOVE_DISPATCH_TO_CORTEX,
        MOVE_GUIDE_CORTEX,
        MOVE_READ_FLIGHT,
        MOVE_REPLY_TO_OPERATOR,
        MOVE_CLARIFY,
        MOVE_WAIT,
    }
    assert len(MOVES) == 6


def test_moves_instruction_names_every_move_and_nothing_else() -> None:
    """build_moves_instruction() is derived from MOVE_SCHEMA, not hand-duplicated."""
    instruction = build_moves_instruction()
    assert isinstance(instruction, str)
    for name in MOVES:
        assert f'"move": "{name}"' in instruction, f"{name} missing from instruction text"


# ---------------------------------------------------------------------------
# 1b — the executor refuses any move name not in MOVES, even a hallucinated
# one the model actually emitted, as a recorded no-op — never raises, never
# invokes any injected callback.
# ---------------------------------------------------------------------------


class _RecordingExecutor:
    """Wraps SensesMoveExecutor with callbacks that record every invocation,
    so a test can assert a refused/degraded move never reached a callback."""

    def __init__(self) -> None:
        self.calls: "list[tuple[str, tuple]]" = []
        self.executor = SensesMoveExecutor(
            dispatch_to_cortex=self._record("dispatch_to_cortex"),
            guide_cortex=self._record("guide_cortex"),
            read_flight=self._record("read_flight"),
            reply_to_operator=self._record("reply_to_operator"),
            clarify=self._record("clarify"),
            wait=self._record("wait"),
        )

    def _record(self, name: str):
        def handler(*args):
            self.calls.append((name, args))
            return f"{name}-outcome"

        return handler


def test_executor_refuses_hallucinated_move_never_raises_never_invokes_callback() -> None:
    rec = _RecordingExecutor()
    move_obj = {"move": "delete_repo", "path": "/", "text": "do it now"}

    result = rec.executor.execute(move_obj)  # must not raise

    assert isinstance(result, MoveResult)
    assert result.move == "delete_repo"
    assert result.refused is True
    assert result.degraded is False
    assert result.outcome is None
    assert result.detail is not None and "delete_repo" in result.detail
    assert rec.calls == [], "a refused move must never invoke any injected callback"


@pytest.mark.parametrize(
    "bad_move",
    [
        {"move": "read_file", "path": "secrets.env"},
        {"move": "run_command", "command": "rm -rf /"},
        {"move": "write_file", "path": "x", "content": "y"},
        {"move": ""},
        {"move": 123},
        {"move": None},
        {},
    ],
)
def test_executor_refuses_every_non_enumerated_or_malformed_move_object(bad_move) -> None:
    rec = _RecordingExecutor()

    result = rec.executor.execute(bad_move)

    assert result.refused is True
    assert result.outcome is None
    assert rec.calls == []


def test_executor_refuses_enumerated_move_with_no_bound_callback() -> None:
    """An enumerated move the caller never wired a callback for is refused
    (recorded no-op), never a crash — mirrors the hallucinated-move path."""
    executor = SensesMoveExecutor()  # no callbacks bound at all except default wait

    result = executor.execute({"move": MOVE_REPLY_TO_OPERATOR, "text": "hi"})

    assert result.refused is True
    assert result.outcome is None


def test_executor_wait_defaults_to_a_clean_no_op_without_a_bound_callback() -> None:
    """Unlike every other move, `wait` needs no caller-supplied behavior —
    omitting it is a clean execution, not a refusal."""
    executor = SensesMoveExecutor()

    result = executor.execute({"move": MOVE_WAIT})

    assert result.refused is False
    assert result.degraded is False
    assert result.move == MOVE_WAIT


# ---------------------------------------------------------------------------
# 1c — each enumerated move, when bound, dispatches to the right callback
# with the right positional argument(s) and returns a clean MoveResult.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "move_obj,expected_name,expected_args",
    [
        (
            {"move": MOVE_DISPATCH_TO_CORTEX, "instruction": "fix the bug"},
            "dispatch_to_cortex",
            ("fix the bug",),
        ),
        (
            {"move": MOVE_GUIDE_CORTEX, "guidance": "focus on config.py"},
            "guide_cortex",
            ("focus on config.py",),
        ),
        ({"move": MOVE_READ_FLIGHT}, "read_flight", ()),
        (
            {"move": MOVE_REPLY_TO_OPERATOR, "text": "sure thing"},
            "reply_to_operator",
            ("sure thing",),
        ),
        (
            {"move": MOVE_CLARIFY, "question": "which file?"},
            "clarify",
            ("which file?",),
        ),
        ({"move": MOVE_WAIT}, "wait", ()),
    ],
)
def test_executor_dispatches_each_enumerated_move_to_its_own_callback(
    move_obj, expected_name, expected_args
) -> None:
    rec = _RecordingExecutor()

    result = rec.executor.execute(move_obj)

    assert result.refused is False
    assert result.degraded is False
    assert result.move == move_obj["move"]
    assert result.outcome == f"{expected_name}-outcome"
    assert rec.calls == [(expected_name, expected_args)]


def test_executor_missing_param_key_defaults_to_empty_string_never_raises() -> None:
    """A parsed move missing its own parameter key (e.g. a lossy JSON
    recovery) still dispatches — degrade-tolerant, never a KeyError."""
    rec = _RecordingExecutor()

    result = rec.executor.execute({"move": MOVE_REPLY_TO_OPERATOR})  # no "text" key

    assert result.refused is False
    assert rec.calls == [("reply_to_operator", ("",))]


def test_executor_degrades_when_a_bound_callback_itself_raises() -> None:
    def _boom(*_args):
        raise RuntimeError("cortex worktree busy")

    executor = SensesMoveExecutor(dispatch_to_cortex=_boom)

    result = executor.execute({"move": MOVE_DISPATCH_TO_CORTEX, "instruction": "go"})

    assert result.refused is False
    assert result.degraded is True
    assert result.outcome is None
    assert "cortex worktree busy" in result.detail


# ---------------------------------------------------------------------------
# 2 — structural boundary: no subprocess, no ToolExecutor, no tool schema.
# ---------------------------------------------------------------------------


def _senses_moves_source_and_tree() -> "tuple[str, ast.Module]":
    src = Path(__file__).resolve().parents[1] / "colleague" / "senses_moves.py"
    source = src.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(src))


class TestSensesMovesModuleHasNoActionSurface:
    def test_no_subprocess_import(self) -> None:
        source, tree = _senses_moves_source_and_tree()
        modules: "set[str]" = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
        assert not any(m == "subprocess" or m.startswith("subprocess.") for m in modules), (
            "colleague/senses_moves.py must never import subprocess — it has no "
            "action/execution surface of its own"
        )
        assert "import subprocess" not in source
        assert "from subprocess" not in source

    def test_no_toolexecutor_import(self) -> None:
        source, tree = _senses_moves_source_and_tree()
        imported_names: "set[str]" = set()
        modules: "set[str]" = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module)
                imported_names.update(alias.name for alias in node.names)
        assert "colleague.tools" not in modules, (
            "colleague/senses_moves.py must never import colleague.tools — it must "
            "have no path to ToolExecutor"
        )
        assert "ToolExecutor" not in imported_names
        # NOTE: checked against imported names (the AST), NOT a raw-source
        # substring — the module docstring legitimately NAMES ToolExecutor in
        # describing the boundary it upholds, and prose must never trip a
        # structural pin.

    def test_senses_moves_module_is_absent_from_the_subprocess_allowlist(self) -> None:
        """Ties this pin to the shared boundary-test authority: senses_moves.py
        is independently confirmed to be outside the sanctioned subprocess
        consumer list in tests/test_boundary.py."""
        from tests.test_boundary import _SUBPROCESS_ALLOWED

        assert "colleague/senses_moves.py" not in _SUBPROCESS_ALLOWED

    def test_module_never_constructs_a_tool_schema(self) -> None:
        """Wire-level assertion: nothing in this module's CODE builds an OpenAI
        tool/function schema or issues a completion with a ``tools=`` argument —
        the protocol here is prompted-JSON text only, exercised entirely
        through injected callbacks. A downstream loop that DOES touch the wire
        (a later task) must still issue its completion with ``tools=[]`` exactly
        like every existing colleague.senses call, but that wire call does not
        live in this module at all.

        Checked against the AST (not a raw-source substring match) so the module
        docstring — which legitimately DESCRIBES this tools-off boundary — never
        trips the assertion. This is strictly stronger than a substring scan: it
        pins the actual code shapes, not incidental text.
        """
        _source, tree = _senses_moves_source_and_tree()
        # No call anywhere passes a ``tools=`` keyword — this module never
        # issues a completion.
        tools_kwargs = [
            kw
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for kw in node.keywords
            if kw.arg == "tools"
        ]
        assert not tools_kwargs, "senses_moves.py must never issue a completion with tools="
        # No reference to make_complete — this module never touches the wire.
        referenced = {
            (node.attr if isinstance(node, ast.Attribute) else node.id)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Attribute, ast.Name))
        }
        assert "make_complete" not in referenced, (
            "senses_moves.py must never reference make_complete — it does not "
            "touch the model wire"
        )
        # No dict literal shaped like a tool/function schema ({"type": "function"}).
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "type"
                        and isinstance(value, ast.Constant)
                        and value.value == "function"
                    ):
                        raise AssertionError(
                            "senses_moves.py must never construct a function/tool schema"
                        )


# ---------------------------------------------------------------------------
# 3 — parse_move degrades malformed/truncated/unparseable text to
# reply_to_operator carrying the raw text, verbatim, never crashing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "{",
        '{"move":"repl',
        "I dunno, {not real} json",
        "hello world, this is not json at all.",
    ],
    ids=[
        "empty-string",
        "lone-brace",
        "truncated-mid-string",
        "prose-wrapped-unparseable",
        "non-json-blob",
    ],
)
def test_parse_move_degrades_garbage_to_reply_to_operator_with_raw_text(garbage: str) -> None:
    parsed = parse_move(garbage)  # must not raise

    assert parsed["move"] == MOVE_REPLY_TO_OPERATOR
    assert parsed["text"] == garbage.strip()


def test_parse_move_never_raises_on_non_string_input() -> None:
    parsed = parse_move(None)  # type: ignore[arg-type]

    assert parsed["move"] == MOVE_REPLY_TO_OPERATOR
    assert parsed["text"] == ""


def test_parse_move_recovers_a_well_formed_move_object() -> None:
    raw = '{"move": "dispatch_to_cortex", "instruction": "add retry logic"}'

    parsed = parse_move(raw)

    assert parsed == {"move": "dispatch_to_cortex", "instruction": "add retry logic"}


def test_parse_move_recovers_a_move_wrapped_in_prose() -> None:
    raw = 'Sure! {"move": "reply_to_operator", "text": "on it"} thanks.'

    parsed = parse_move(raw)

    assert parsed["move"] == "reply_to_operator"
    assert parsed["text"] == "on it"


def test_parse_move_repairs_a_truncated_but_recoverable_object() -> None:
    """Mirrors _extract_json_object's bounded repair (retreat-to-last-complete
    element) — a trailing cut that still leaves a balanced ``"move"`` key
    recovers cleanly instead of degrading."""
    raw = '{"move": "guide_cortex", "guidance": "watch the tests"'  # missing final }

    parsed = parse_move(raw)

    assert parsed["move"] == "guide_cortex"
    assert parsed["guidance"] == "watch the tests"


def test_parse_move_does_not_filter_hallucinated_move_names() -> None:
    """A well-formed object naming an unenumerated move is returned AS-IS —
    rejecting it is the executor's job, not the parser's (see
    test_executor_refuses_hallucinated_move_never_raises_never_invokes_callback)."""
    raw = '{"move": "delete_repo", "path": "/"}'

    parsed = parse_move(raw)

    assert parsed == {"move": "delete_repo", "path": "/"}

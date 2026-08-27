"""Tests for :mod:`colleague.microcompact` (t4).

Proves the four acceptance criteria verbatim from the plan:

1. ``microcompact(messages, keep_recent=10)`` replaces the content of
   tool-role messages older than the most recent N with a one-line marker
   naming the tool and path, leaves every assistant message and
   ``tool_calls`` entry intact, and returns ``(messages, blanked_count)``.
2. Wire validity: every ``tool_call`` id still has exactly one paired
   ``tool`` message after blanking.
3. ``should_microcompact(prompt_tokens, budget)`` returns ``True`` at
   ``>= 0.85`` of budget.
4. The module never imports an engine or makes a network call.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from colleague.microcompact import (
    DEFAULT_KEEP_RECENT,
    MICROCOMPACT_THRESHOLD_PCT,
    microcompact,
    should_microcompact,
)

MODULE_PATH = Path(__file__).resolve().parent.parent / "colleague" / "microcompact.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _assistant_call(call_id: str, name: str, arguments: dict | str) -> dict:
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": args},
            }
        ],
    }


def _tool_reply(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _make_turn(i: int, name: str = "read_file", path: str | None = None) -> list[dict]:
    call_id = f"call_{i}"
    args = {"path": path} if path else {"path": f"file_{i}.py"}
    return [
        _assistant_call(call_id, name, args),
        _tool_reply(call_id, f"contents of turn {i}"),
    ]


def _tool_call_ids(messages: list[dict]) -> set[str]:
    ids = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                ids.add(tc["id"])
    return ids


def _tool_reply_ids(messages: list[dict]) -> list[str]:
    return [m["tool_call_id"] for m in messages if m.get("role") == "tool"]


# ---------------------------------------------------------------------------
# 1. blanking + recent-N window + marker shape
# ---------------------------------------------------------------------------


def test_blanks_old_tool_messages_keeps_recent_n():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(15):
        messages.extend(_make_turn(i, path=f"colleague/file_{i}.py"))

    result, blanked_count = microcompact(messages, keep_recent=10)

    tool_messages = [m for m in result if m.get("role") == "tool"]
    assert len(tool_messages) == 15
    # First 5 (15 - 10) are blanked, last 10 keep their real content.
    assert blanked_count == 5
    for i, m in enumerate(tool_messages):
        if i < 5:
            assert m["content"] != f"contents of turn {i}"
            assert m["content"].startswith("[old read_file result for colleague/file_")
            assert m["content"].endswith(" cleared — re-read if needed]")
        else:
            assert m["content"] == f"contents of turn {i}"


def test_marker_names_tool_and_path():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        *_make_turn(0, name="read_file", path="colleague/loop.py"),
        *_make_turn(1, name="run_command", path="irrelevant"),
    ]
    result, blanked_count = microcompact(messages, keep_recent=1)
    assert blanked_count == 1
    blanked = [m for m in result if m.get("role") == "tool"][0]
    assert (
        blanked["content"]
        == "[old read_file result for colleague/loop.py cleared — re-read if needed]"
    )


def test_marker_names_only_tool_when_no_path_arg():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        _assistant_call("call_0", "run_command", {"command": "ls"}),
        _tool_reply("call_0", "dir listing"),
        *_make_turn(1, path="keep/me.py"),
    ]
    result, blanked_count = microcompact(messages, keep_recent=1)
    assert blanked_count == 1
    blanked = [m for m in result if m.get("role") == "tool"][0]
    assert blanked["content"] == "[old run_command result cleared — re-read if needed]"
    assert " for " not in blanked["content"]


def test_assistant_messages_and_tool_calls_untouched():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(12):
        messages.extend(_make_turn(i))
    original_assistants = [m for m in messages if m.get("role") == "assistant"]

    result, _ = microcompact(messages, keep_recent=10)

    result_assistants = [m for m in result if m.get("role") == "assistant"]
    assert result_assistants == original_assistants
    # Same objects, not just equal — "intact" means untouched, not rebuilt.
    for orig, new in zip(original_assistants, result_assistants):
        assert orig is new


def test_default_keep_recent_is_ten():
    assert DEFAULT_KEEP_RECENT == 10
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(10):
        messages.extend(_make_turn(i))
    # Exactly 10 tool messages, default keep_recent=10 -> nothing old enough.
    result, blanked_count = microcompact(messages)
    assert blanked_count == 0
    assert result == messages


def test_input_list_is_not_mutated():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(5):
        messages.extend(_make_turn(i))
    import copy

    snapshot = copy.deepcopy(messages)
    microcompact(messages, keep_recent=1)
    assert messages == snapshot


def test_keep_recent_zero_blanks_everything():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(3):
        messages.extend(_make_turn(i))
    result, blanked_count = microcompact(messages, keep_recent=0)
    assert blanked_count == 3
    assert all(m["content"].startswith("[old ") for m in result if m.get("role") == "tool")


def test_keep_recent_exceeds_tool_count_is_noop():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(3):
        messages.extend(_make_turn(i))
    result, blanked_count = microcompact(messages, keep_recent=100)
    assert blanked_count == 0
    for m in result:
        if m.get("role") == "tool":
            assert not m["content"].startswith("[old ")


def test_returns_new_list_object():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    messages.extend(_make_turn(0))
    result, _ = microcompact(messages, keep_recent=0)
    assert result is not messages


# ---------------------------------------------------------------------------
# 2. wire validity
# ---------------------------------------------------------------------------


def test_wire_validity_every_tool_call_id_paired_exactly_once():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(20):
        messages.extend(_make_turn(i))

    result, blanked_count = microcompact(messages, keep_recent=7)
    assert blanked_count == 13

    call_ids = _tool_call_ids(result)
    reply_ids = _tool_reply_ids(result)

    # Every assistant tool_call id appears as exactly one tool reply's
    # tool_call_id (a Counter of 1 each), both before and after blanking.
    assert len(reply_ids) == len(call_ids)
    assert sorted(reply_ids) == sorted(call_ids)
    assert len(reply_ids) == len(set(reply_ids))  # no duplicates

    # And it held before blanking too (the fixture itself is wire-valid),
    # so this proves microcompact PRESERVES validity, not merely produces it.
    original_call_ids = _tool_call_ids(messages)
    original_reply_ids = _tool_reply_ids(messages)
    assert sorted(original_reply_ids) == sorted(original_call_ids)


def test_wire_validity_message_count_unchanged():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"}]
    for i in range(9):
        messages.extend(_make_turn(i))
    result, _ = microcompact(messages, keep_recent=3)
    assert len(result) == len(messages)


def test_wire_validity_with_orphan_tool_message_degrades_gracefully():
    """A tool message with no matching assistant tool_calls entry (malformed
    history) is still blanked (naming just "tool"), never raises, and the
    surviving pairing for the well-formed calls is untouched."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        _tool_reply("orphan_call", "mystery output"),
        *_make_turn(0, path="a.py"),
        *_make_turn(1, path="b.py"),
    ]
    result, blanked_count = microcompact(messages, keep_recent=1)
    assert blanked_count == 2  # orphan + turn 0
    orphan = result[2]
    assert orphan["content"] == "[old tool result cleared — re-read if needed]"


# ---------------------------------------------------------------------------
# 3. should_microcompact threshold
# ---------------------------------------------------------------------------


def test_threshold_constant_is_085():
    assert MICROCOMPACT_THRESHOLD_PCT == 0.85


@pytest.mark.parametrize(
    "prompt_tokens,budget,expected",
    [
        (850, 1000, True),  # exactly 0.85 -> True (>=)
        (849, 1000, False),
        (851, 1000, True),
        (1000, 1000, True),
        (0, 1000, False),
        (100, 100, True),
    ],
)
def test_should_microcompact_threshold(prompt_tokens, budget, expected):
    assert should_microcompact(prompt_tokens, budget) is expected


def test_should_microcompact_nonpositive_budget_is_false():
    assert should_microcompact(100, 0) is False
    assert should_microcompact(100, -5) is False


# ---------------------------------------------------------------------------
# 4. no engine / network import
# ---------------------------------------------------------------------------


def test_module_source_has_no_forbidden_imports():
    """AST-level check: no import of colleague.engines, colleague.loop,
    colleague.tools, urllib, http, requests, or socket anywhere in the
    module source."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "colleague.engines",
        "colleague.loop",
        "colleague.tools",
        "urllib",
        "http",
        "requests",
        "socket",
    )
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.append(node.module)

    for name in found:
        assert not any(
            name == p or name.startswith(p + ".") for p in forbidden_prefixes
        ), f"forbidden import found in colleague/microcompact.py: {name}"


def test_module_imports_only_stdlib():
    """The module's top-level imports resolve to stdlib (or __future__)
    only — no third-party or colleague.* dependency at all."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    top_level_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level_modules.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level_modules.append(node.module.split(".")[0])

    stdlib_allowed = {"__future__", "json", "typing"}
    for name in top_level_modules:
        assert name in stdlib_allowed, f"unexpected non-stdlib import: {name}"


def test_module_has_no_network_or_subprocess_symbols_in_source():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for token in ("subprocess", "socket.", "urlopen", "requests.", "httpx"):
        assert token not in source, f"forbidden symbol {token!r} found in module source"

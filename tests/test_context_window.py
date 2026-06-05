"""Tests for colleague/context.py — context-window management primitives.

TDD: tests written BEFORE implementation. Each test maps to a specific
acceptance criterion listed in the task spec.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers to build message fixtures
# ---------------------------------------------------------------------------


def sys_msg(text: str = "You are a coding agent.") -> dict:
    return {"role": "system", "content": text}


def user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def assistant_tool_calls_msg(call_id: str, fn_name: str, fn_args: str = "{}") -> dict:
    """An assistant turn that requests a tool call."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": fn_name, "arguments": fn_args},
            }
        ],
    }


def tool_result_msg(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def assistant_text_msg(text: str) -> dict:
    """An assistant turn with no tool calls (just text)."""
    return {"role": "assistant", "content": text}


# ---------------------------------------------------------------------------
# Validity checker (used as an assertion helper)
# ---------------------------------------------------------------------------


def is_openai_valid(messages: list[dict]) -> tuple[bool, str]:
    """Return (True, '') if OpenAI validity holds, else (False, reason)."""
    # Collect all tool_call_ids from assistant tool_calls messages
    declared_ids: set[str] = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                declared_ids.add(tc["id"])

    # Every tool message must have a declared parent
    for m in messages:
        if m.get("role") == "tool":
            tid = m.get("tool_call_id", "")
            if tid not in declared_ids:
                return False, f"orphan tool message tool_call_id={tid!r}"

    # Every assistant tool_calls turn must have ALL its replies present
    # Group by call_id; each id must appear exactly once as a tool message
    tool_ids_present: set[str] = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if tc["id"] not in tool_ids_present:
                    return False, f"assistant tool_calls id={tc['id']!r} missing tool reply"

    return True, ""


# ===========================================================================
# Tests for count_tokens_chars
# ===========================================================================


class TestCountTokensChars:
    def test_empty_list_returns_one(self):
        from colleague.context import count_tokens_chars

        # minimum 1 when there is any text ... actually spec says minimum 1
        # when there IS any text. Empty list = 0 chars → 0 // 4 = 0.
        # Spec: "minimum 1 when there is any text" — empty list has no text.
        result = count_tokens_chars([])
        assert result == 0

    def test_counts_content_chars(self):
        from colleague.context import count_tokens_chars

        # 400 chars of content → 400 // 4 = 100
        msgs = [{"role": "user", "content": "a" * 400}]
        assert count_tokens_chars(msgs) == 100

    def test_minimum_one_when_any_text(self):
        from colleague.context import count_tokens_chars

        # 1 char → 1 // 4 = 0 but minimum 1
        msgs = [{"role": "user", "content": "x"}]
        assert count_tokens_chars(msgs) == 1

    def test_counts_tool_calls_name_and_arguments(self):
        from colleague.context import count_tokens_chars

        fn_name = "read_file"  # 9 chars
        fn_args = '{"path": "foo.py"}'  # 18 chars
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": fn_name, "arguments": fn_args},
                    }
                ],
            }
        ]
        expected = (len(fn_name) + len(fn_args)) // 4
        assert count_tokens_chars(msgs) == max(1, expected)

    def test_sums_all_messages(self):
        from colleague.context import count_tokens_chars

        msgs = [
            {"role": "system", "content": "a" * 80},
            {"role": "user", "content": "b" * 80},
            {"role": "tool", "tool_call_id": "c1", "content": "c" * 80},
        ]
        assert count_tokens_chars(msgs) == 240 // 4

    def test_missing_content_key_treated_as_zero(self):
        from colleague.context import count_tokens_chars

        # assistant tool_calls message may have empty / missing content
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [],
            }
        ]
        assert count_tokens_chars(msgs) == 0


# ===========================================================================
# Tests for window_messages
# ===========================================================================


class TestWindowMessagesUnderBudget:
    def test_under_budget_returns_same_list(self):
        """When already under budget the list is returned unchanged."""
        from colleague.context import window_messages

        msgs = [
            sys_msg(),
            user_msg("do the task"),
            assistant_tool_calls_msg("c1", "read_file"),
            tool_result_msg("c1", "content"),
        ]
        result = window_messages(msgs, budget_tokens=10_000)
        # Same elements in same order
        assert result == msgs

    def test_under_budget_no_placeholder(self):
        from colleague.context import window_messages

        msgs = [sys_msg(), user_msg("task")]
        result = window_messages(msgs, budget_tokens=10_000)
        assert not any("[earlier steps elided" in (m.get("content") or "") for m in result)


class TestWindowMessagesOverBudget:
    def _long_history(self, n_pairs: int = 8) -> list[dict]:
        """Build: system, user(task), n_pairs*(assistant+tool), assistant(final)."""
        msgs: list[dict] = [sys_msg(), user_msg("do the task")]
        for i in range(n_pairs):
            call_id = f"call_{i}"
            msgs.append(assistant_tool_calls_msg(call_id, "read_file", f'{{"path":"f{i}.py"}}'))
            msgs.append(tool_result_msg(call_id, "x" * 200))  # 200 chars each
        msgs.append(assistant_text_msg("done"))
        return msgs

    def test_system_and_first_user_always_preserved(self):
        from colleague.context import window_messages

        msgs = self._long_history(10)
        result = window_messages(msgs, budget_tokens=50)
        assert result[0]["role"] == "system"
        first_user = next(m for m in result if m["role"] == "user")
        assert first_user["content"] == "do the task"

    def test_placeholder_present_exactly_once(self):
        from colleague.context import window_messages

        msgs = self._long_history(10)
        result = window_messages(msgs, budget_tokens=50)
        placeholders = [m for m in result if "[earlier steps elided" in (m.get("content") or "")]
        assert len(placeholders) == 1

    def test_result_is_openai_valid(self):
        """No orphan tool messages; every tool_calls id has a matching tool reply."""
        from colleague.context import window_messages

        msgs = self._long_history(10)
        result = window_messages(msgs, budget_tokens=80)
        ok, reason = is_openai_valid(result)
        assert ok, reason

    def test_most_recent_messages_retained(self):
        """The tail of the history (the most recent turns) is kept."""
        from colleague.context import window_messages

        msgs = self._long_history(6)
        result = window_messages(msgs, budget_tokens=300)
        # The last assistant message ("done") should survive
        last_assistant = [m for m in result if m.get("role") == "assistant"][-1]
        assert last_assistant.get("content") == "done"

    def test_dropped_pairs_are_matched_units(self):
        """No assistant tool_calls without its tool reply, and no orphan tool."""
        from colleague.context import window_messages

        msgs = self._long_history(8)
        # Very tight budget forces significant dropping
        result = window_messages(msgs, budget_tokens=60)
        ok, reason = is_openai_valid(result)
        assert ok, reason

    def test_placeholder_positioned_after_head(self):
        """Placeholder comes after system+first_user, before the retained tail."""
        from colleague.context import window_messages

        msgs = self._long_history(8)
        result = window_messages(msgs, budget_tokens=80)
        head_indices = [i for i, m in enumerate(result) if m["role"] in ("system",)]
        ph_indices = [
            i for i, m in enumerate(result) if "[earlier steps elided" in (m.get("content") or "")
        ]
        if ph_indices:
            # placeholder must come after the system message
            assert ph_indices[0] > head_indices[0]
            # placeholder must come before the last message
            assert ph_indices[0] < len(result) - 1


class TestWindowMessagesCallCount:
    def test_count_tokens_calls_bounded(self):
        """count_tokens must be called at most a small constant number of times."""
        from colleague.context import window_messages

        call_count = 0

        def counting_counter(msgs):
            nonlocal call_count
            call_count += 1
            # Use char-based estimate so it actually triggers trimming
            total = 0
            for m in msgs:
                total += len(m.get("content") or "")
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    total += len(fn.get("name") or "") + len(fn.get("arguments") or "")
            return max(1, total // 4) if total else 0

        # Build a long history so trimming is definitely needed
        msgs = [sys_msg(), user_msg("task")]
        for i in range(20):
            cid = f"call_{i}"
            msgs.append(assistant_tool_calls_msg(cid, "read_file", f'{{"path":"f{i}.py"}}'))
            msgs.append(tool_result_msg(cid, "r" * 300))
        msgs.append(assistant_text_msg("finished"))

        window_messages(msgs, budget_tokens=50, count_tokens=counting_counter)
        # Must be small constant — spec says e.g. <= 4
        assert call_count <= 4, f"count_tokens called {call_count} times (expected <= 4)"

    def test_custom_count_tokens_used(self):
        """When count_tokens is passed it must be used instead of chars heuristic."""
        from colleague.context import window_messages

        used = []

        def always_under(msgs):
            used.append(True)
            return 1  # always reports 1 token → always under budget

        msgs = [sys_msg(), user_msg("task")]
        result = window_messages(msgs, budget_tokens=10, count_tokens=always_under)
        assert result == msgs  # under budget → unchanged
        assert len(used) >= 1


class TestWindowMessagesEdgeCases:
    def test_only_head_and_one_turn_still_over_budget_returns_minimal(self):
        """When nothing droppable exists return minimal valid list."""
        from colleague.context import window_messages

        msgs = [
            sys_msg("s" * 1000),
            user_msg("u" * 1000),
        ]
        result = window_messages(msgs, budget_tokens=1)
        # Must include at least system and first user
        assert result[0]["role"] == "system"
        assert any(m["role"] == "user" for m in result)

    def test_assistant_text_turn_can_be_dropped_as_standalone(self):
        """A plain assistant text turn (no tool_calls) is droppable on its own."""
        from colleague.context import window_messages

        msgs = [
            sys_msg(),
            user_msg("task"),
            assistant_text_msg("intermediate thought " * 50),  # big, old
            assistant_tool_calls_msg("c1", "read_file"),
            tool_result_msg("c1", "ok"),
        ]
        result = window_messages(msgs, budget_tokens=30)
        ok, reason = is_openai_valid(result)
        assert ok, reason

    def test_no_placeholder_when_nothing_dropped(self):
        from colleague.context import window_messages

        msgs = [sys_msg(), user_msg("small")]
        result = window_messages(msgs, budget_tokens=10_000)
        assert not any("[earlier steps elided" in (m.get("content") or "") for m in result)


# ===========================================================================
# Tests for is_context_overflow
# ===========================================================================


class TestIsContextOverflow:
    def test_maximum_context_length(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("This model's maximum context length is 4096 tokens")

    def test_context_window(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("The context window has been exceeded")

    def test_too_many_tokens(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("Error: too many tokens in the prompt")

    def test_reduce_the_length(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("Please reduce the length of the messages")

    def test_context_length_exceeded(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("context_length_exceeded error code returned")

    def test_longer_than_the_maximum(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("Your input is longer than the maximum allowed")

    def test_case_insensitive(self):
        from colleague.context import is_context_overflow

        assert is_context_overflow("MAXIMUM CONTEXT LENGTH exceeded")
        assert is_context_overflow("Context Window Full")

    def test_unrelated_text_returns_false(self):
        from colleague.context import is_context_overflow

        assert not is_context_overflow("File not found")
        assert not is_context_overflow("rate limit exceeded")
        assert not is_context_overflow("")

    def test_none_like_empty_returns_false(self):
        from colleague.context import is_context_overflow

        assert not is_context_overflow("")

    def test_stdlib_only(self):
        """The module must import only stdlib — no third-party deps."""
        import sys

        # Remove cached module if present
        for key in list(sys.modules.keys()):
            if "colleague.context" in key:
                del sys.modules[key]

        import colleague.context  # noqa: F401

        # Verify the module only imports stdlib modules (no third-party)
        # We check by ensuring tiktoken / transformers / etc. are NOT imported
        third_party = {"tiktoken", "transformers", "openai", "anthropic"}
        loaded = set(sys.modules.keys())
        bad = third_party & loaded
        # Allow any that were already loaded before this test
        assert not bad, f"Third-party modules loaded: {bad}"


# ===========================================================================
# Tests for is_request_timeout
# ===========================================================================


class TestIsRequestTimeout:
    def test_timed_out(self):
        from colleague.context import is_request_timeout

        assert is_request_timeout("timed out")

    def test_full_timeout_message(self):
        from colleague.context import is_request_timeout

        assert is_request_timeout("request to http://localhost:8001/v1/chat/completions timed out after 120s")

    def test_case_insensitive(self):
        from colleague.context import is_request_timeout

        assert is_request_timeout("Read Timed Out")

    def test_unrelated_text_returns_false(self):
        from colleague.context import is_request_timeout

        assert not is_request_timeout("vLLM endpoint unreachable: Connection refused")

    def test_empty_returns_false(self):
        from colleague.context import is_request_timeout

        assert not is_request_timeout("")

    def test_disjoint_from_overflow(self):
        from colleague.context import is_request_timeout

        assert not is_request_timeout("maximum context length exceeded")


# ===========================================================================
# Tests for classify_degradable
# ===========================================================================


class TestClassifyDegradable:
    def test_overflow(self):
        from colleague.context import classify_degradable

        assert classify_degradable("maximum context length exceeded") == "overflow"

    def test_timeout(self):
        from colleague.context import classify_degradable

        assert classify_degradable("timed out") == "timeout"

    def test_neither(self):
        from colleague.context import classify_degradable

        assert classify_degradable("Connection refused") is None

    def test_empty(self):
        from colleague.context import classify_degradable

        assert classify_degradable("") is None

"""Tests for colleague.plan.cli_driver — the engine-backed proposal seams.

The model call is an injected callable, so these run with no network.
"""

from __future__ import annotations

import pytest

from colleague.plan.cli_driver import (
    make_propose_claims,
    make_propose_plan_items,
    parse_claims,
    parse_plan_items,
    robust_simple_complete,
    to_simple_complete,
)
from colleague.plan.frame import PlanFrame

_CLAIMS_JSON = """\
{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"},
            {"id": "c2", "kind": "audience", "text": "ops"}],
 "honesty": [{"id": "h1", "claim_id": "c1", "text": "true"}]}
"""

_PLAN_JSON = """\
Here is the plan:
```json
{"items": [{"id": "t1", "summary": "do A", "acceptance": ["A works"], "deps": []},
           {"id": "t2", "summary": "do B", "acceptance": ["B works"], "deps": ["t1"]}]}
```
"""


def test_parse_claims_reads_claims_and_honesty() -> None:
    claims, honesty = parse_claims(_CLAIMS_JSON)
    assert [c.id for c in claims] == ["c1", "c2"]
    assert all(c.state == "proposed" for c in claims)
    assert claims[0].kind == "announcement"
    assert honesty[0].claim_id == "c1" and honesty[0].state == "proposed"


def test_parse_plan_items_tolerates_prose_and_fence() -> None:
    items = parse_plan_items(_PLAN_JSON)
    assert [i.id for i in items] == ["t1", "t2"]
    assert items[0].acceptance == ["A works"]
    assert items[1].deps == ["t1"]


def test_parse_claims_raises_without_json() -> None:
    with pytest.raises(ValueError):
        parse_claims("no json here")


def test_parse_claims_tolerates_missing_keys() -> None:
    # A model that omits keys or emits a non-dict entry must not crash (no KeyError):
    # entries without an "id" are skipped; other fields default to "".
    blob = (
        '{"claims": [{"id": "c1"}, {"kind": "audience"}, "garbage", '
        '{"id": "c2", "kind": "audience", "text": "ops"}], '
        '"honesty": [{"claim_id": "c1"}, {"id": "h1", "claim_id": "c1"}]}'
    )
    claims, honesty = parse_claims(blob)
    assert [c.id for c in claims] == ["c1", "c2"]  # the keyless + non-dict entries dropped
    assert claims[0].kind == "" and claims[0].text == ""  # defaulted, not crashed
    assert [h.id for h in honesty] == ["h1"]


def test_parse_plan_items_tolerates_missing_keys() -> None:
    blob = '{"items": [{"summary": "no id"}, {"id": "t1"}, 42]}'
    items = parse_plan_items(blob)
    assert [i.id for i in items] == ["t1"]
    assert items[0].summary == "" and items[0].acceptance == []


def test_to_simple_complete_wraps_completefn() -> None:
    seen: dict[str, object] = {}

    class _Resp:
        content = "hello"

    def fake_complete(messages):
        seen["messages"] = messages
        return _Resp()

    simple = to_simple_complete(fake_complete)
    out = simple("SYS", "USR")
    assert out == "hello"
    assert seen["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USR"},
    ]


def test_to_simple_complete_handles_empty_content() -> None:
    class _Resp:
        content = None

    simple = to_simple_complete(lambda _m: _Resp())
    assert simple("a", "b") == ""


def test_make_propose_claims_uses_simple() -> None:
    calls: list[tuple[str, str]] = []
    call_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count
        calls.append((system, user))
        call_count += 1
        if call_count == 1:
            # First call: mandatory kinds
            return (
                '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}], "honesty": []}'
            )
        # Second call: requirements + honesty
        return (
            '{"claims": [{"id": "c2", "kind": "requirement", "text": "fast"}], '
            '"honesty": [{"id": "h1", "claim_id": "c1", "text": "true"}]}'
        )

    propose = make_propose_claims(simple)
    claims, honesty = propose("build a thing")
    # Accumulates claims from BOTH calls
    assert [c.id for c in claims] == ["c1", "c2"]
    # First call's user prompt = the request
    assert calls[0][1] == "build a thing"
    # Second call's user prompt contains the already-proposed claims
    assert "announcement" in calls[1][1]
    assert honesty[0].claim_id == "c1"


def test_make_propose_claims_tolerates_bad_second_chunk() -> None:
    """A bad second chunk does not abort; first chunk's claims survive."""
    call_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return (
                '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}], "honesty": []}'
            )
        return "not json at all"

    propose = make_propose_claims(simple)
    claims, honesty = propose("build a thing")
    assert [c.id for c in claims] == ["c1"]
    assert call_count == 2  # both calls attempted


def test_parse_plan_items_acceptance_string_not_split_into_chars() -> None:
    """When the model returns acceptance as a string, it should NOT be split into chars."""
    blob = '{"items": [{"id": "t1", "acceptance": "A works"}]}'
    items = parse_plan_items(blob)
    assert items[0].acceptance == ["A works"]
    assert items[0].acceptance != ["A", " ", "w", "o", "r", "k", "s"]


def test_parse_plan_items_deps_string_not_split_into_chars() -> None:
    """When the model returns deps as a string, it should NOT be split into chars."""
    blob = '{"items": [{"id": "t1", "deps": "t0"}]}'
    items = parse_plan_items(blob)
    assert items[0].deps == ["t0"]
    assert items[0].deps != ["t", "0"]


def test_parse_plan_items_acceptance_list_still_works() -> None:
    """A list value for acceptance still works element-wise."""
    blob = '{"items": [{"id": "t1", "acceptance": ["A works", "B works"]}]}'
    items = parse_plan_items(blob)
    assert items[0].acceptance == ["A works", "B works"]


def test_parse_plan_items_deps_list_still_works() -> None:
    """A list value for deps still works element-wise."""
    blob = '{"items": [{"id": "t1", "deps": ["t0", "t2"]}]}'
    items = parse_plan_items(blob)
    assert items[0].deps == ["t0", "t2"]


def test_make_propose_plan_items_includes_confirmed_claims() -> None:
    captured: list[str] = []
    call_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count
        call_count += 1
        captured.append(user)
        if call_count == 1:
            return (
                '{"items": [{"id": "t1", "summary": "do A", '
                '"acceptance": ["A works"], "deps": []}]}'
            )
        # Second batch returns empty -> stops
        return '{"items": []}'

    frame = PlanFrame()
    from colleague.plan.frame import Claim

    frame.claims.append(Claim(id="c1", kind="announcement", text="ABC", state="confirmed"))
    frame.claims.append(Claim(id="c2", kind="audience", text="XYZ", state="proposed"))

    propose = make_propose_plan_items(simple)
    items = propose(frame)
    assert [i.id for i in items] == ["t1"]
    # Only the CONFIRMED claim text is fed to the plan proposal.
    assert "ABC" in captured[0]
    assert "XYZ" not in captured[0]


def test_make_propose_plan_items_accumulates_batches() -> None:
    """Two batches accumulate; an empty batch ends the loop."""
    call_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"items": [{"id": "t1", "summary": "do A", "acceptance": [], "deps": []}]}'
        elif call_count == 2:
            return '{"items": [{"id": "t2", "summary": "do B", "acceptance": [], "deps": ["t1"]}]}'
        else:
            return '{"items": []}'

    frame = PlanFrame()
    from colleague.plan.frame import Claim

    frame.claims.append(Claim(id="c1", kind="announcement", text="X", state="confirmed"))

    propose = make_propose_plan_items(simple)
    items = propose(frame)
    assert [i.id for i in items] == ["t1", "t2"]
    assert call_count == 3  # batch1 + batch2 + empty batch3


def test_make_propose_plan_items_tolerates_bad_batch() -> None:
    """A bad batch does not abort; good batches still accumulate."""
    call_count = 0

    def simple(system: str, user: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"items": [{"id": "t1", "summary": "do A", "acceptance": [], "deps": []}]}'
        elif call_count == 2:
            return "not json"  # bad batch
        else:
            return '{"items": []}'  # stop

    frame = PlanFrame()
    from colleague.plan.frame import Claim

    frame.claims.append(Claim(id="c1", kind="announcement", text="X", state="confirmed"))

    propose = make_propose_plan_items(simple)
    items = propose(frame)
    assert [i.id for i in items] == ["t1"]
    assert call_count == 3  # all 3 batches attempted


# ---------------------------------------------------------------------------
# robust_simple_complete tests
# ---------------------------------------------------------------------------


class _ModelResp:
    """Minimal ModelResponse stand-in for tests."""

    def __init__(
        self,
        content: str = "",
        reasoning: str = "",
    ):
        self.content = content
        self.reasoning = reasoning


def test_robust_non_empty_content_is_byte_identical() -> None:
    """Non-empty content on the first turn -> byte-identical to to_simple_complete."""
    expected = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'

    def fake_complete(messages):
        return _ModelResp(content=expected)

    robust = robust_simple_complete(fake_complete)
    old = to_simple_complete(fake_complete)

    assert robust("SYS", "USR") == expected
    assert old("SYS", "USR") == expected
    assert robust("SYS", "USR") == old("SYS", "USR")


def test_robust_empty_content_then_non_empty_on_followup() -> None:
    """Empty content first turn, non-empty on follow-up -> parses correctly."""
    followup_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ModelResp(content="", reasoning="thinking...")
        return _ModelResp(content=followup_json)

    simple = robust_simple_complete(fake_complete)
    result = simple("SYS", "USR")
    assert result == followup_json
    assert call_count == 2


def test_robust_empty_both_turns_falls_back_to_reasoning() -> None:
    """Content empty on both turns but JSON in reasoning -> recovered."""
    reasoning_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ModelResp(content="", reasoning="thinking...")
        return _ModelResp(content="", reasoning=reasoning_json)

    simple = robust_simple_complete(fake_complete)
    result = simple("SYS", "USR")
    assert result == reasoning_json
    assert call_count == 2


def test_robust_first_reasoning_preserved_when_followup_empty() -> None:
    """When call 1 has JSON in reasoning and the follow-up returns empty
    content + empty reasoning, the first call's reasoning is returned."""
    first_reasoning_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ModelResp(content="", reasoning=first_reasoning_json)
        return _ModelResp(content="", reasoning="")

    simple = robust_simple_complete(fake_complete)
    result = simple("SYS", "USR")
    assert result == first_reasoning_json
    assert call_count == 2


def test_robust_followup_reasoning_preferred_over_first() -> None:
    """When both calls have reasoning, the follow-up's reasoning is preferred."""
    first_reasoning = '{"claims": [{"id": "c1", "kind": "announcement", "text": "old"}]}'
    followup_reasoning = '{"claims": [{"id": "c2", "kind": "audience", "text": "new"}]}'
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _ModelResp(content="", reasoning=first_reasoning)
        return _ModelResp(content="", reasoning=followup_reasoning)

    simple = robust_simple_complete(fake_complete)
    result = simple("SYS", "USR")
    assert result == followup_reasoning
    assert call_count == 2


def test_robust_timeout_retry_then_success() -> None:
    """Fake raises a timeout-classified error once then succeeds -> retried, not raised."""
    good_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("request timed out")
        return _ModelResp(content=good_json)

    simple = robust_simple_complete(fake_complete)
    result = simple("SYS", "USR")
    assert result == good_json
    assert call_count == 2


def test_robust_overflow_retry_then_success() -> None:
    """Fake raises an overflow-classified error once then succeeds -> retried."""
    good_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("maximum context length exceeded")
        return _ModelResp(content=good_json)

    simple = robust_simple_complete(fake_complete)
    result = simple("SYS", "USR")
    assert result == good_json
    assert call_count == 2


def test_robust_non_degradable_error_raises() -> None:
    """A non-degradable error re-raises immediately."""

    def fake_complete(messages):
        raise ValueError("something unrelated")

    simple = robust_simple_complete(fake_complete)
    with pytest.raises(ValueError, match="something unrelated"):
        simple("SYS", "USR")


def test_robust_identical_claims_to_old_path() -> None:
    """Non-empty content produces identical Claim objects to the current code."""
    blob = _CLAIMS_JSON

    def fake_complete(messages):
        return _ModelResp(content=blob)

    robust = robust_simple_complete(fake_complete)
    old = to_simple_complete(fake_complete)

    robust_text = robust("SYS", "USR")
    old_text = old("SYS", "USR")
    assert robust_text == old_text

    r_claims, r_honesty = parse_claims(robust_text)
    o_claims, o_honesty = parse_claims(old_text)

    assert [c.id for c in r_claims] == [c.id for c in o_claims]
    assert [c.kind for c in r_claims] == [c.kind for c in o_claims]
    assert [c.text for c in r_claims] == [c.text for c in o_claims]
    assert [h.id for h in r_honesty] == [h.id for h in o_honesty]
    assert [h.claim_id for h in r_honesty] == [h.claim_id for h in o_honesty]


def test_extract_prefers_object_with_required_key() -> None:
    """A stray object (e.g. a schema example) before the real payload must not
    shadow it: parse_plan_items skips the keyless object and returns the one
    carrying ``items`` (the reasoning-model robustness case, #210)."""
    blob = (
        'Here is the schema: {"id": "t1", "summary": "example"} and the answer:\n'
        '{"items": [{"id": "t1", "summary": "real", "acceptance": [], "deps": []}]}'
    )
    items = parse_plan_items(blob)
    assert [i.id for i in items] == ["t1"]
    assert items[0].summary == "real"


def test_extract_falls_back_to_first_object_when_key_absent() -> None:
    """When no object carries the key, the first balanced object is returned
    (back-compat with the keyless extractor)."""
    from colleague.plan.cli_driver import _extract_json_object

    assert _extract_json_object('{"a": 1} {"b": 2}', required_key="items") == {"a": 1}
    # And the keyless default still returns the first object byte-identically.
    assert _extract_json_object('{"a": 1} {"b": 2}') == {"a": 1}


def test_extract_repairs_object_missing_trailing_brace() -> None:
    """A reasoning model that stops before the final ``}`` (truncation) is
    recovered by the bounded repair path (#210 — the live 27B failure mode)."""
    truncated = '\n\n{"items": [{"id": "t1", "summary": "a", "acceptance": [], "deps": []}]'
    items = parse_plan_items(truncated)
    assert [i.id for i in items] == ["t1"]


def test_extract_repairs_truncated_mid_element() -> None:
    """Truncation mid-element retreats to the last complete element + recloses."""
    # Closes through t2, then t3 is cut off mid-string and the structure is open.
    truncated = (
        '{"items": [{"id": "t1", "summary": "a", "acceptance": [], "deps": []}, '
        '{"id": "t2", "summary": "b", "acceptance": [], "deps": []}, '
        '{"id": "t3", "summary": "unterminat'
    )
    items = parse_plan_items(truncated)
    assert [i.id for i in items] == ["t1", "t2"]


def test_extract_balanced_object_unchanged_by_repair() -> None:
    """A well-formed (balanced) object is returned without invoking repair."""
    items = parse_plan_items('{"items": [{"id": "t1", "summary": "ok", "deps": []}]}')
    assert [i.id for i in items] == ["t1"]
    assert items[0].summary == "ok"


def test_extract_repair_retreat_skips_brace_inside_string() -> None:
    """The truncation retreat is string-aware: a '}' inside a string value does
    not cause the retreat to cut at the wrong position (colleague review #210)."""
    # t1 closes cleanly; t2's summary contains a literal '}' then truncates.
    truncated = (
        '{"items": [{"id": "t1", "summary": "ok", "acceptance": ["a"], "deps": []}, '
        '{"id": "t2", "summary": "uses a } brace then cut off'
    )
    items = parse_plan_items(truncated)
    assert [i.id for i in items] == ["t1"]


def test_make_propose_plan_items_raises_on_total_failure() -> None:
    """When no batch yields any item, propose_plan_items raises (clean error),
    not a silent empty plan (symmetric with make_propose_claims)."""
    from colleague.plan.frame import Claim

    def simple(system: str, user: str) -> str:
        return "no json here at all"

    frame = PlanFrame()
    frame.claims.append(Claim(id="c1", kind="announcement", text="X", state="confirmed"))
    with pytest.raises(ValueError):
        make_propose_plan_items(simple)(frame)


# ---------------------------------------------------------------------------
# Overflow-shrinking retry tests (Qodo #2 on PR #214)
# ---------------------------------------------------------------------------


def test_overflow_retry_shrinks_user_message() -> None:
    """When an overflow error occurs, the retried call receives a shorter
    user message than the first attempt."""
    good_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0
    received_user_lengths: list[int] = []

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        # Record the user message length at call time (before any later shrink).
        user_content = messages[1]["content"]
        received_user_lengths.append(len(user_content))
        if call_count == 1:
            raise RuntimeError("maximum context length exceeded")
        return _ModelResp(content=good_json)

    simple = robust_simple_complete(fake_complete)
    long_user = "X" * 200
    result = simple("SYS", long_user)
    assert result == good_json
    assert call_count == 2
    # First call had the full user message; second call has a shorter one.
    assert received_user_lengths[1] < received_user_lengths[0]
    assert received_user_lengths[1] == received_user_lengths[0] // 2


def test_overflow_retry_exhausted_cap_raises() -> None:
    """When overflow errors exhaust the retry cap, the error re-raises."""
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("maximum context length exceeded")

    simple = robust_simple_complete(fake_complete)
    with pytest.raises(RuntimeError, match="maximum context length exceeded"):
        simple("SYS", "USR")
    # 1 initial + 3 overflow retries = 4 total calls
    assert call_count == 4


def test_timeout_retry_does_not_shrink() -> None:
    """A timeout retry retries without shrinking (shrinking is overflow-only)."""
    good_json = '{"claims": [{"id": "c1", "kind": "announcement", "text": "ships"}]}'
    call_count = 0
    received_messages: list[list[dict]] = []

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        received_messages.append(messages)
        if call_count == 1:
            raise RuntimeError("request timed out")
        return _ModelResp(content=good_json)

    simple = robust_simple_complete(fake_complete)
    long_user = "X" * 200
    result = simple("SYS", long_user)
    assert result == good_json
    assert call_count == 2
    # Timeout retry does NOT shrink — messages are identical.
    first_user = received_messages[0][1]["content"]
    second_user = received_messages[1][1]["content"]
    assert second_user == first_user


def test_non_degradable_error_raises_immediately() -> None:
    """A non-degradable error re-raises immediately without retry."""
    call_count = 0

    def fake_complete(messages):
        nonlocal call_count
        call_count += 1
        raise ValueError("something unrelated")

    simple = robust_simple_complete(fake_complete)
    with pytest.raises(ValueError, match="something unrelated"):
        simple("SYS", "USR")
    assert call_count == 1

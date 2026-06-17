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

    def simple(system: str, user: str) -> str:
        calls.append((system, user))
        return _CLAIMS_JSON

    propose = make_propose_claims(simple)
    claims, honesty = propose("build a thing")
    assert [c.id for c in claims] == ["c1", "c2"]
    assert calls and calls[0][1] == "build a thing"


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
    captured: dict[str, str] = {}

    def simple(system: str, user: str) -> str:
        captured["user"] = user
        return _PLAN_JSON

    frame = PlanFrame()
    from colleague.plan.frame import Claim

    frame.claims.append(Claim(id="c1", kind="announcement", text="ABC", state="confirmed"))
    frame.claims.append(Claim(id="c2", kind="audience", text="XYZ", state="proposed"))

    propose = make_propose_plan_items(simple)
    items = propose(frame)
    assert [i.id for i in items] == ["t1", "t2"]
    # Only the CONFIRMED claim text is fed to the plan proposal.
    assert "ABC" in captured["user"]
    assert "XYZ" not in captured["user"]


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

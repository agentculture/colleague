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

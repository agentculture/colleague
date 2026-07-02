"""Part-aware budget accounting + part-safe windowing (t6, spec c13/h11).

Media parts are counted against the context budget — exact-counter histories
get a flattened copy plus the per-media estimate (an exact tokenizer endpoint
cannot count an image part), and the char fallback charges the same estimate
directly. Windowing drops a media part WHOLE (a parts message is a droppable
segment like any other) — no output message ever contains a truncated or
partial parts list.
"""

from __future__ import annotations

from colleague.context import (
    count_tokens_chars,
    media_aware_count,
    window_messages,
)
from colleague.media import IMAGE_TOKEN_ESTIMATE

_IMG_PART = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def _parts_message(text: str = "look at this") -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}, dict(_IMG_PART)]}


def _history(n_turns: int = 6, with_mid_parts: bool = True) -> list[dict]:
    msgs = [
        {"role": "system", "content": "sys"},
        _parts_message("the task text"),
    ]
    for i in range(n_turns):
        msgs.append({"role": "assistant", "content": f"thinking {i} " + "x" * 400})
        if with_mid_parts and i == 1:
            msgs.append(_parts_message("[view_media] loaded image img.png"))
    msgs.append({"role": "assistant", "content": "latest turn"})
    return msgs


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_char_fallback_charges_the_media_estimate() -> None:
    text = "a" * 400
    plain = [{"role": "user", "content": text}]
    with_media = [{"role": "user", "content": [{"type": "text", "text": text}, dict(_IMG_PART)]}]
    base = count_tokens_chars(plain)
    counted = count_tokens_chars(with_media)
    # The image part contributes ~IMAGE_TOKEN_ESTIMATE tokens, never zero and
    # never len(list)-style nonsense.
    assert counted - base >= IMAGE_TOKEN_ESTIMATE - 1
    assert counted - base <= IMAGE_TOKEN_ESTIMATE + 1


def test_char_fallback_string_only_unchanged() -> None:
    msgs = [{"role": "user", "content": "abcd" * 25}]
    assert count_tokens_chars(msgs) == 25


def test_media_aware_count_flattens_for_the_exact_counter() -> None:
    seen: list[list[dict]] = []

    def exact(msgs: list[dict]) -> int:
        seen.append(msgs)
        assert all(isinstance(m.get("content"), str) for m in msgs)
        return 100

    msgs = [_parts_message()]
    total = media_aware_count(msgs, exact)
    assert seen, "the exact counter must be consulted"
    assert total == 100 + IMAGE_TOKEN_ESTIMATE


def test_media_aware_count_passthrough_without_media() -> None:
    calls: list[list[dict]] = []

    def exact(msgs: list[dict]) -> int:
        calls.append(msgs)
        return 42

    msgs = [{"role": "user", "content": "plain"}]
    assert media_aware_count(msgs, exact) == 42
    # No flattening copy for a string-only history: the exact counter sees the
    # original list object (zero-overhead passthrough).
    assert calls[0] is msgs


def test_media_aware_count_none_counter_falls_back_to_chars() -> None:
    msgs = [_parts_message("t" * 40)]
    assert media_aware_count(msgs, None) == count_tokens_chars(msgs)


# ---------------------------------------------------------------------------
# Windowing: parts survive whole or drop whole — never sliced
# ---------------------------------------------------------------------------


def _assert_no_partial_parts(msgs: list[dict], original_parts: list[list[dict]]) -> None:
    for m in msgs:
        content = m.get("content")
        if isinstance(content, list):
            assert content in original_parts, "a parts list must survive intact"


def test_windowing_keeps_head_parts_message_intact() -> None:
    msgs = _history()
    original = [m["content"] for m in msgs if isinstance(m.get("content"), list)]
    out = window_messages(msgs, budget_tokens=350)
    assert out[1]["content"] == msgs[1]["content"], "head (first user) always survives"
    _assert_no_partial_parts(out, original)
    assert any("elided" in str(m.get("content")) for m in out), "placeholder present"


def test_windowing_drops_mid_history_parts_message_whole() -> None:
    msgs = _history()
    out = window_messages(msgs, budget_tokens=300)
    mid_parts = [
        m
        for m in out[2:]
        if isinstance(m.get("content"), list)
        and any(p.get("type") == "image_url" for p in m["content"])
    ]
    # tight budget: the mid-history view_media fold drops whole (the head
    # attachment message is exempt — always preserved)
    assert not mid_parts
    for m in out:
        content = m.get("content")
        if isinstance(content, list):
            types = [p.get("type") for p in content]
            assert types == ["text", "image_url"], "never a truncated parts list"


def test_windowing_string_only_history_unchanged_when_under_budget() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "done"},
    ]
    assert window_messages(msgs, budget_tokens=10_000) is msgs

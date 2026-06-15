"""Tests for colleague.plan.reviewer — the adversarial plan reviewer."""

from __future__ import annotations

from colleague.plan.reviewer import CRITIC_SYSTEM_PROMPT, Critique, review_item


class _CallRecorder:
    """Records calls to a fake complete callable."""

    def __init__(self, return_value: str):
        self.calls: list[tuple[str, str]] = []
        self._return_value = return_value

    def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self._return_value


# ── Critique dataclass ──────────────────────────────────────────────────────


class TestCritique:
    def test_to_dict(self):
        c = Critique(text="weak", concerns=["scope too broad"])
        assert c.to_dict() == {"text": "weak", "concerns": ["scope too broad"]}

    def test_from_dict(self):
        c = Critique.from_dict({"text": "weak", "concerns": ["scope too broad"]})
        assert c.text == "weak"
        assert c.concerns == ["scope too broad"]

    def test_from_dict_defaults(self):
        c = Critique.from_dict({"text": "ok"})
        assert c.text == "ok"
        assert c.concerns == []

    def test_round_trip(self):
        original = Critique(text="critique", concerns=["a", "b"])
        restored = Critique.from_dict(original.to_dict())
        assert original == restored


# ── CRITIC_SYSTEM_PROMPT ────────────────────────────────────────────────────


class TestCriticSystemPrompt:
    def test_is_non_empty_string(self):
        assert isinstance(CRITIC_SYSTEM_PROMPT, str)
        assert len(CRITIC_SYSTEM_PROMPT) > 0

    def test_contains_adversarial_keywords(self):
        lower = CRITIC_SYSTEM_PROMPT.lower()
        assert "weakness" in lower or "critique" in lower or "risk" in lower

    def test_does_not_contain_approve(self):
        lower = CRITIC_SYSTEM_PROMPT.lower()
        assert "approve" not in lower
        assert "confirm" not in lower


# ── review_item enabled=True ────────────────────────────────────────────────


class TestReviewItemEnabled:
    def test_calls_complete_once(self):
        recorder = _CallRecorder(return_value="Found a gap.")
        review_item("Proposed item text", recorder, enabled=True)
        assert len(recorder.calls) == 1

    def test_passes_critic_system_prompt(self):
        recorder = _CallRecorder(return_value="Found a gap.")
        review_item("Proposed item text", recorder, enabled=True)
        assert recorder.calls[0][0] == CRITIC_SYSTEM_PROMPT

    def test_passes_item_text_as_user_prompt(self):
        recorder = _CallRecorder(return_value="Found a gap.")
        review_item("Proposed item text", recorder, enabled=True)
        assert recorder.calls[0][1] == "Proposed item text"

    def test_returns_critique_with_text(self):
        recorder = _CallRecorder(return_value="The plan is too broad.")
        result = review_item("Proposed item text", recorder, enabled=True)
        assert isinstance(result, Critique)
        assert result.text == "The plan is too broad."

    def test_returns_critique_with_empty_concerns(self):
        recorder = _CallRecorder(return_value="The plan is too broad.")
        result = review_item("Proposed item text", recorder, enabled=True)
        assert isinstance(result, Critique)
        assert isinstance(result.concerns, list)

    def test_no_approve_or_confirm_in_result(self):
        """The reviewer never returns an approve/confirm decision."""
        recorder = _CallRecorder(return_value="This is fine.")
        result = review_item("Proposed item text", recorder, enabled=True)
        assert isinstance(result, Critique)
        # Critique has no approve/confirm attribute — only text and concerns
        assert not hasattr(result, "approved")
        assert not hasattr(result, "confirmed")


# ── review_item enabled=False ───────────────────────────────────────────────


class TestReviewItemDisabled:
    def test_does_not_call_complete(self):
        recorder = _CallRecorder(return_value="Should not be called.")
        review_item("Proposed item text", recorder, enabled=False)
        assert len(recorder.calls) == 0

    def test_returns_none(self):
        recorder = _CallRecorder(return_value="Should not be called.")
        assert review_item("Proposed item text", recorder, enabled=False) is None

    def test_returns_none_with_different_callable(self):
        """Engine-agnostic: any callable is fine when disabled."""

        def other_complete(sys: str, usr: str) -> str:
            raise RuntimeError("Should not be called")

        assert review_item("Proposed item text", other_complete, enabled=False) is None

    def test_default_enabled_is_true(self):
        """Default enabled=True means complete IS called."""
        recorder = _CallRecorder(return_value="Default enabled.")
        result = review_item("Proposed item text", recorder)
        assert len(recorder.calls) == 1
        assert isinstance(result, Critique)

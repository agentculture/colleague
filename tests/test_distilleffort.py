"""Tests for colleague/distilleffort.py — the distill child's effort plumbing
(#416 extension, plan t3, spec c9/h9/c38/h36).

Two layers: unit tests directly against ``distilleffort``'s pure helpers, and
integration tests through ``distill.child_main``/``_openai_completion`` using
the existing distill-child fake-HTTP-server test harness (mirrors
``tests/test_distill.py``'s ``_patch_urlopen``/``_completion_body`` helpers).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from colleague import distill, distilleffort

# ---------------------------------------------------------------------------
# Unit tests — pure helpers
# ---------------------------------------------------------------------------


class TestChatTemplateFragment:
    def test_off_rung(self) -> None:
        assert distilleffort.chat_template_fragment("off") == {"enable_thinking": False}

    def test_low_rung(self) -> None:
        assert distilleffort.chat_template_fragment("low") == {"reasoning_effort": "low"}

    def test_none_is_absent(self) -> None:
        assert distilleffort.chat_template_fragment(None) is None

    def test_default_sentinel_is_absent(self) -> None:
        assert distilleffort.chat_template_fragment("default") is None


class TestMaxTokensForRung:
    def test_off_keeps_the_baseline_envelope(self) -> None:
        assert distilleffort.max_tokens_for_rung("off") == 4096

    def test_none_keeps_the_baseline_envelope(self) -> None:
        assert distilleffort.max_tokens_for_rung(None) == 4096

    def test_default_sentinel_keeps_the_baseline_envelope(self) -> None:
        assert distilleffort.max_tokens_for_rung("default") == 4096

    def test_low_raises_the_cap(self) -> None:
        assert distilleffort.max_tokens_for_rung("low") >= 12288

    def test_medium_raises_the_cap(self) -> None:
        assert distilleffort.max_tokens_for_rung("medium") >= 12288

    def test_high_raises_the_cap(self) -> None:
        assert distilleffort.max_tokens_for_rung("high") >= 12288

    def test_xhigh_raises_the_cap(self) -> None:
        assert distilleffort.max_tokens_for_rung("xhigh") >= 12288

    def test_armed_cap_exceeds_off_cap(self) -> None:
        assert distilleffort.max_tokens_for_rung("low") > distilleffort.max_tokens_for_rung("off")


class TestIsLadder400:
    class _FakeHTTPError(Exception):
        def __init__(self, code: int, msg: str) -> None:
            super().__init__(msg)
            self.code = code
            self._msg = msg

        def __str__(self) -> str:
            return self._msg

    def test_matches_reasoning_effort_400(self) -> None:
        exc = self._FakeHTTPError(400, "Unexpected reasoning effort bogus.")
        assert distilleffort.is_ladder_400(exc) is True

    def test_case_insensitive(self) -> None:
        exc = self._FakeHTTPError(400, "REASONING EFFORT invalid")
        assert distilleffort.is_ladder_400(exc) is True

    def test_other_400_is_not_a_ladder_400(self) -> None:
        exc = self._FakeHTTPError(400, "bad request: malformed json")
        assert distilleffort.is_ladder_400(exc) is False

    def test_other_status_is_not_a_ladder_400(self) -> None:
        exc = self._FakeHTTPError(500, "reasoning effort explosion")
        assert distilleffort.is_ladder_400(exc) is False


class TestRetryWithoutFragmentOnce:
    def test_non_ladder_400_returns_none(self) -> None:
        exc = TestIsLadder400._FakeHTTPError(400, "malformed json")
        payload = {"chat_template_kwargs": {"reasoning_effort": "low"}}
        outcome = distilleffort.retry_without_fragment_once(exc, payload, lambda: "unused")
        assert outcome is None
        # payload untouched when not retried
        assert "chat_template_kwargs" in payload

    def test_missing_fragment_returns_none(self) -> None:
        exc = TestIsLadder400._FakeHTTPError(400, "reasoning effort bogus")
        payload: dict = {}
        outcome = distilleffort.retry_without_fragment_once(exc, payload, lambda: "unused")
        assert outcome is None

    def test_ladder_400_retries_once_and_drops_the_fragment(self) -> None:
        exc = TestIsLadder400._FakeHTTPError(400, "Unexpected reasoning effort bogus.")
        payload = {"chat_template_kwargs": {"reasoning_effort": "bogus"}, "model": "m"}
        calls = []

        def dispatch() -> str:
            calls.append(dict(payload))
            return "retried-response"

        outcome = distilleffort.retry_without_fragment_once(exc, payload, dispatch)
        assert outcome is not None
        assert outcome.response == "retried-response"
        assert "chat_template_kwargs" not in payload
        assert len(calls) == 1
        assert "chat_template_kwargs" not in calls[0]
        assert "ladder retry" in outcome.warning
        assert "chat_template_kwargs" in outcome.warning


class TestReasoningExhaustedReason:
    def test_names_reasoning_exhausted_max_tokens(self) -> None:
        reason = distilleffort.reasoning_exhausted_reason(12288, 5000, 0)
        assert reason.startswith("reasoning exhausted max_tokens")
        assert "no lesson extracted" not in reason
        assert "12288" in reason


# ---------------------------------------------------------------------------
# Integration — through distill._openai_completion / distill.child_main
# ---------------------------------------------------------------------------


class _FakeCompletionResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_FakeCompletionResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _completion_body(*, content: str = "", finish_reason: str = "stop") -> dict:
    return {
        "choices": [
            {"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}
        ]
    }


class TestBodyCarriesTheFragment:
    def test_body_carries_the_fragment_at_low(self, monkeypatch: Any) -> None:
        import urllib.request

        captured: dict = {}

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeCompletionResponse:
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeCompletionResponse(_completion_body(content="{}"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        distill._openai_completion(
            "m",
            "http://rig/v1",
            "k",
            "prompt",
            max_tokens=distilleffort.max_tokens_for_rung("low"),
            chat_template_kwargs=distilleffort.chat_template_fragment("low"),
        )
        assert captured["body"]["chat_template_kwargs"] == {"reasoning_effort": "low"}
        assert captured["body"]["max_tokens"] == 12288

    def test_body_carries_enable_thinking_false_at_off(self, monkeypatch: Any) -> None:
        import urllib.request

        captured: dict = {}

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeCompletionResponse:
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeCompletionResponse(_completion_body(content="{}"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        distill._openai_completion(
            "m",
            "http://rig/v1",
            "k",
            "prompt",
            max_tokens=distilleffort.max_tokens_for_rung("off"),
            chat_template_kwargs=distilleffort.chat_template_fragment("off"),
        )
        assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert captured["body"]["max_tokens"] == 4096

    def test_body_carries_nothing_at_default_none(self, monkeypatch: Any) -> None:
        import urllib.request

        captured: dict = {}

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeCompletionResponse:
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeCompletionResponse(_completion_body(content="{}"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        distill._openai_completion(
            "m",
            "http://rig/v1",
            "k",
            "prompt",
            max_tokens=distilleffort.max_tokens_for_rung(None),
            chat_template_kwargs=distilleffort.chat_template_fragment(None),
        )
        assert "chat_template_kwargs" not in captured["body"]
        assert captured["body"]["max_tokens"] == 4096


class TestLadder400RetryThroughOpenAICompletion:
    def test_first_400_retries_without_chat_template_kwargs(self, monkeypatch: Any) -> None:
        import urllib.error
        import urllib.request

        calls: list[dict] = []

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeCompletionResponse:
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            if len(calls) == 1:
                assert "chat_template_kwargs" in body
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "Unexpected reasoning effort bogus. Supported types are xhigh (default).",
                    None,
                    None,
                )
            assert "chat_template_kwargs" not in body
            return _FakeCompletionResponse(_completion_body(content="{}"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        completion = distill._openai_completion(
            "m",
            "http://rig/v1",
            "k",
            "prompt",
            max_tokens=12288,
            chat_template_kwargs={"reasoning_effort": "low"},
        )
        assert len(calls) == 2
        assert completion.warning is not None
        assert "ladder retry" in completion.warning

    def test_marker_records_the_ladder_retry_warning(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        artifact = adir / "abc123.some-slug.json"
        artifact.write_text(
            json.dumps(
                {
                    "task_id": "abc123",
                    "status": "ok",
                    "summary": "s",
                    "stats": {"step_count": 3},
                }
            ),
            encoding="utf-8",
        )

        lesson_json = (
            '{"pattern": "p", "constant": "colleague/distill.py::x", "reason": "r because p"}'
        )
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content=lesson_json,
                reasoning="",
                finish_reason="stop",
                warning="colleague: distill ladder retry — the chat_template_kwargs "
                "fragment was rejected by the server; retried once without it. "
                "Server said: 400",
            ),
        )
        with patch("colleague.memory.remember", return_value=True):
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m", "--effort", "low"]
            )
        assert rc == 0
        marker = json.loads(artifact.with_suffix(".distill.json").read_text(encoding="utf-8"))
        assert marker["status"] == "done"
        assert "warning" in marker
        assert "ladder retry" in marker["warning"]


class TestFinishReasonLengthNoJsonMarksReasoningExhausted:
    def test_marker_reason_is_reasoning_exhausted_max_tokens(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        artifact = adir / "abc123.some-slug.json"
        artifact.write_text(
            json.dumps(
                {
                    "task_id": "abc123",
                    "status": "INCOMPLETE",
                    "summary": "s",
                    "stats": {"step_count": 5},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            distill,
            "_openai_completion",
            lambda *a, **k: distill.DistillCompletion(
                content="", reasoning="x" * 2000, finish_reason="length"
            ),
        )
        with patch("colleague.memory.remember") as mock_remember:
            rc = distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m", "--effort", "low"]
            )
            mock_remember.assert_not_called()
        assert rc == 1
        marker = json.loads(artifact.with_suffix(".distill.json").read_text(encoding="utf-8"))
        assert marker["status"] == "failed"
        assert marker["reason"].startswith("reasoning exhausted max_tokens")
        assert "no lesson extracted" not in marker["reason"]
        # the armed rung's raised cap, not the off-rung baseline
        assert "12288" in marker["reason"]


class TestChildMainThreadsEffort:
    def test_effort_argv_drives_the_raised_cap(self, tmp_path: Path, monkeypatch: Any) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        artifact = adir / "abc123.some-slug.json"
        artifact.write_text(
            json.dumps({"task_id": "abc123", "status": "ok", "summary": "s"}),
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_completion(model, base_url, api_key, prompt, **kwargs):
            captured.update(kwargs)
            return distill.DistillCompletion(content="{}", reasoning="", finish_reason="stop")

        monkeypatch.setattr(distill, "_openai_completion", fake_completion)
        with patch("colleague.memory.remember", return_value=False):
            distill.child_main(
                ["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m", "--effort", "low"]
            )
        assert captured["max_tokens"] == 12288
        assert captured["chat_template_kwargs"] == {"reasoning_effort": "low"}

    def test_no_effort_argv_keeps_the_baseline_cap(self, tmp_path: Path, monkeypatch: Any) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        artifact = adir / "abc123.some-slug.json"
        artifact.write_text(
            json.dumps({"task_id": "abc123", "status": "ok", "summary": "s"}),
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_completion(model, base_url, api_key, prompt, **kwargs):
            captured.update(kwargs)
            return distill.DistillCompletion(content="{}", reasoning="", finish_reason="stop")

        monkeypatch.setattr(distill, "_openai_completion", fake_completion)
        monkeypatch.delenv("COLLEAGUE_DISTILL_EFFORT", raising=False)
        with patch("colleague.memory.remember", return_value=False):
            distill.child_main(["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"])
        assert captured["max_tokens"] == 4096
        assert captured.get("chat_template_kwargs") is None

    def test_env_var_fallback_when_argv_absent(self, tmp_path: Path, monkeypatch: Any) -> None:
        adir = tmp_path / ".colleague"
        adir.mkdir()
        artifact = adir / "abc123.some-slug.json"
        artifact.write_text(
            json.dumps({"task_id": "abc123", "status": "ok", "summary": "s"}),
            encoding="utf-8",
        )
        captured: dict = {}

        def fake_completion(model, base_url, api_key, prompt, **kwargs):
            captured.update(kwargs)
            return distill.DistillCompletion(content="{}", reasoning="", finish_reason="stop")

        monkeypatch.setattr(distill, "_openai_completion", fake_completion)
        monkeypatch.setenv("COLLEAGUE_DISTILL_EFFORT", "medium")
        with patch("colleague.memory.remember", return_value=False):
            distill.child_main(["--repo", str(tmp_path), "--task-id", "abc123", "--model", "m"])
        assert captured["max_tokens"] == 12288
        assert captured["chat_template_kwargs"] == {"reasoning_effort": "medium"}


class TestBuildChildArgvCarriesEffort:
    def test_effort_rung_lands_in_argv(self) -> None:
        argv = distill._build_child_argv("/repo", "task-1", "model-x", "low")
        assert "--effort" in argv
        assert argv[argv.index("--effort") + 1] == "low"

    def test_no_effort_omits_the_flag(self) -> None:
        argv = distill._build_child_argv("/repo", "task-1", "model-x", None)
        assert "--effort" not in argv


class TestMakeDistillFnThreadsEffort:
    def test_detach_receives_the_author_effort(self, tmp_path: Path) -> None:
        from unittest.mock import patch as _patch

        from colleague import background

        repo = tmp_path / "repo"
        repo.mkdir()

        with _patch.object(background, "spawn_background") as mock_spawn:
            mock_spawn.return_value = background.BackgroundHandle(
                id="h1", pid=1, log_dir=".colleague/background/h1/", flight="f1"
            )
            distill_fn = distill.make_distill_fn(
                repo_path=repo,
                author_model="test-model",
                author_base_url="http://localhost:8001/v1",
                author_api_key="test-key",
                author_effort="medium",
            )

            class _R:
                task_id = "t1"

            distill_fn(_R(), "req")
            argv = mock_spawn.call_args[0][1]
            assert "--effort" in argv
            assert argv[argv.index("--effort") + 1] == "medium"

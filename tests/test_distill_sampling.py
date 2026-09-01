"""Tests for the distill child's sampling wiring (#479 t8, spec c14/h12).

The distill child is the SECOND greedy site alongside the acting-turn adapter:
``distill._openai_completion`` used to hard-code ``temperature: 0``
unconditionally, even when the completion carried an armed thinking rung via
``chat_template_kwargs``. This module proves:

1. The distill child's request body carries the same sampling profile as an
   equivalently-runged acting turn would (resolved via the SAME
   ``colleague.sampling.resolve_sampling`` ladder), verified from a dumped
   request payload (via ``_openai_completion``'s new ``COLLEAGUE_DUMP_REQUEST``
   path, modelled on the adapter's).
2. The child resolves its half from its OWN distilleffort rung — never from
   an acting seat's — proven by driving two different rungs through the same
   helper and observing two different halves/profiles.

Uses the existing fake-urlopen harness from ``tests/test_distilleffort.py``.
"""

from __future__ import annotations

import json
from typing import Any

from colleague import distill, sampling

_QWEN_MODEL = "unsloth/Qwen3.8-27B-NVFP4"  # normalises to the builtin card row
_UNMATCHED_MODEL = "some/other-model"


class _FakeCompletionResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "_FakeCompletionResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _completion_body(*, content: str = "{}", finish_reason: str = "stop") -> dict:
    return {
        "choices": [
            {"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}
        ]
    }


def _patch_urlopen(monkeypatch: Any) -> "dict[str, Any]":
    import urllib.request

    captured: dict = {}

    def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeCompletionResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeCompletionResponse(_completion_body())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return captured


class TestCriterion1SameProfileAsAnActingTurn:
    """The distill child's body carries the SAME sampling profile a
    resolve_sampling-driven acting turn would send for the same model/rung —
    verified from the dumped payload."""

    def test_low_rung_thinking_profile_matches_acting_resolution(self, monkeypatch: Any) -> None:
        captured = _patch_urlopen(monkeypatch)
        distill._openai_completion(
            _QWEN_MODEL,
            "http://rig/v1",
            "k",
            "prompt",
            effort_rung="low",
        )
        body = captured["body"]

        # What an equivalently-runged acting turn resolves via the SAME ladder.
        acting_profile = sampling.resolve_sampling(_QWEN_MODEL, role=None, rung="low")
        acting_fragment = sampling.sampling_payload(acting_profile)

        # The wire drops keys equal to the server default (t5 c8 parity,
        # implemented locally — see distill.py's _SAMPLING_SERVER_DEFAULTS).
        assert acting_fragment["temperature"] == 1.0
        assert acting_fragment["top_p"] == 0.95
        assert acting_fragment["top_k"] == 20
        assert acting_fragment["min_p"] == 0.0
        assert acting_fragment["repetition_penalty"] == 1.0

        assert body["temperature"] == 1.0
        assert body["top_p"] == 0.95
        assert body["top_k"] == 20
        # Server-default values are filtered off the wire on both sides.
        assert "min_p" not in body
        assert "repetition_penalty" not in body

    def test_off_rung_non_thinking_profile_matches_acting_resolution(
        self, monkeypatch: Any
    ) -> None:
        captured = _patch_urlopen(monkeypatch)
        distill._openai_completion(
            _QWEN_MODEL,
            "http://rig/v1",
            "k",
            "prompt",
            effort_rung="off",
        )
        body = captured["body"]

        acting_profile = sampling.resolve_sampling(_QWEN_MODEL, role=None, rung="off")
        acting_fragment = sampling.sampling_payload(acting_profile)
        assert acting_fragment["temperature"] == 0.7
        assert body["temperature"] == 0.7
        assert body["top_p"] == 0.80
        assert body["top_k"] == 20
        assert body["presence_penalty"] == 1.5

    def test_unmatched_model_keeps_the_byte_identical_floor(self, monkeypatch: Any) -> None:
        """No row matches -> no sampling keys at all -> the original
        hard-coded temperature 0 default still applies (t5's "byte-identical
        when no row matched" rule, mirrored here)."""
        captured = _patch_urlopen(monkeypatch)
        distill._openai_completion(
            _UNMATCHED_MODEL,
            "http://rig/v1",
            "k",
            "prompt",
            effort_rung="low",
        )
        body = captured["body"]
        assert body["temperature"] == 0
        assert "top_p" not in body
        assert "top_k" not in body

    def test_unarmed_rung_keeps_the_byte_identical_floor(self, monkeypatch: Any) -> None:
        captured = _patch_urlopen(monkeypatch)
        distill._openai_completion(
            _QWEN_MODEL,
            "http://rig/v1",
            "k",
            "prompt",
            effort_rung=None,
        )
        body = captured["body"]
        assert body["temperature"] == 0
        assert "top_p" not in body
        assert "top_k" not in body

    def test_dump_request_env_writes_the_payload_to_stderr(
        self, monkeypatch: Any, capsys: Any
    ) -> None:
        _patch_urlopen(monkeypatch)
        monkeypatch.setenv("COLLEAGUE_DUMP_REQUEST", "1")
        distill._openai_completion(
            _QWEN_MODEL,
            "http://rig/v1",
            "k",
            "prompt",
            effort_rung="low",
        )
        captured_out = capsys.readouterr()
        assert "outgoing distill request payload" in captured_out.err
        dumped = json.loads(captured_out.err.split("payload:\n", 1)[1])
        assert dumped["temperature"] == 1.0
        assert dumped["top_k"] == 20

    def test_dump_request_absent_by_default(self, monkeypatch: Any, capsys: Any) -> None:
        _patch_urlopen(monkeypatch)
        monkeypatch.delenv("COLLEAGUE_DUMP_REQUEST", raising=False)
        distill._openai_completion(
            _QWEN_MODEL,
            "http://rig/v1",
            "k",
            "prompt",
            effort_rung="low",
        )
        captured_out = capsys.readouterr()
        assert captured_out.err == ""


class TestCriterion2ChildResolvesItsOwnRung:
    """The child's half comes from ITS OWN distilleffort rung, never from an
    acting seat's — proven by driving two different rungs and observing two
    different halves/profiles for the SAME model."""

    def test_different_rungs_yield_different_halves(self) -> None:
        thinking_half = sampling.half_for_rung("low")
        non_thinking_half = sampling.half_for_rung("off")
        assert thinking_half != non_thinking_half
        assert thinking_half == sampling.THINKING
        assert non_thinking_half == sampling.NON_THINKING

    def test_child_payload_differs_between_rungs_for_the_same_model(self, monkeypatch: Any) -> None:
        low_captured = _patch_urlopen(monkeypatch)
        distill._openai_completion(_QWEN_MODEL, "http://rig/v1", "k", "prompt", effort_rung="low")
        low_body = dict(low_captured["body"])

        off_captured = _patch_urlopen(monkeypatch)
        distill._openai_completion(_QWEN_MODEL, "http://rig/v1", "k", "prompt", effort_rung="off")
        off_body = dict(off_captured["body"])

        # Same model, two different CHILD rungs -> two different resolved
        # sampling profiles. Nothing here reads an "acting seat" rung at all —
        # the only input to resolve_sampling on the distill path is the
        # argument threaded from distilleffort's own COLLEAGUE_DISTILL_EFFORT
        # resolution (see distill.child_main / _child_env).
        assert low_body["temperature"] != off_body["temperature"]
        assert low_body["presence_penalty"] == 0.0
        assert off_body["presence_penalty"] == 1.5

    @staticmethod
    def _seed_artifact(tmp_path: Any, task_id: str = "abc123") -> Any:
        adir = tmp_path / ".colleague"
        adir.mkdir(exist_ok=True)
        artifact = adir / f"{task_id}.some-slug.json"
        artifact.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "status": "INCOMPLETE",
                    "summary": "s",
                    "stats": {"step_count": 9},
                }
            ),
            encoding="utf-8",
        )
        return artifact

    def test_child_main_threads_its_own_rung_not_an_acting_seat_env_var(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """child_main resolves ``effort_rung`` from ``--effort`` /
        ``COLLEAGUE_DISTILL_EFFORT`` alone — an unrelated acting-seat-shaped
        env var (``COLLEAGUE_EFFORT``, ``COLLEAGUE_MAIN_EFFORT``) must have
        zero influence on the value threaded into ``_openai_completion``."""
        self._seed_artifact(tmp_path)
        monkeypatch.delenv("COLLEAGUE_DISTILL_EFFORT", raising=False)
        monkeypatch.setenv("COLLEAGUE_EFFORT", "xhigh")
        monkeypatch.setenv("COLLEAGUE_MAIN_EFFORT", "xhigh")

        captured: dict = {}
        real_openai_completion = distill._openai_completion

        def spying_openai_completion(*args: Any, **kwargs: Any) -> Any:
            captured["effort_rung"] = kwargs.get("effort_rung")
            return real_openai_completion(*args, **kwargs)

        monkeypatch.setattr(distill, "_openai_completion", spying_openai_completion)
        _patch_urlopen(monkeypatch)
        distill.child_main(
            [
                "--repo",
                str(tmp_path),
                "--task-id",
                "abc123",
                "--model",
                _QWEN_MODEL,
                "--effort",
                "low",
            ]
        )
        assert captured["effort_rung"] == "low"
        assert captured["effort_rung"] != "xhigh"

    def test_child_main_env_fallback_also_ignores_acting_seat_vars(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """Same proof via the env-fallback path (a hand-run child with no
        ``--effort`` argv, per ``child_main``'s ``args.effort or os.environ.get
        (...)`` fallback)."""
        self._seed_artifact(tmp_path)
        monkeypatch.setenv("COLLEAGUE_DISTILL_EFFORT", "off")
        monkeypatch.setenv("COLLEAGUE_EFFORT", "xhigh")
        monkeypatch.setenv("COLLEAGUE_MAIN_EFFORT", "xhigh")

        captured: dict = {}
        real_openai_completion = distill._openai_completion

        def spying_openai_completion(*args: Any, **kwargs: Any) -> Any:
            captured["effort_rung"] = kwargs.get("effort_rung")
            return real_openai_completion(*args, **kwargs)

        monkeypatch.setattr(distill, "_openai_completion", spying_openai_completion)
        _patch_urlopen(monkeypatch)
        distill.child_main(["--repo", str(tmp_path), "--task-id", "abc123", "--model", _QWEN_MODEL])
        assert captured["effort_rung"] == "off"
        assert captured["effort_rung"] != "xhigh"

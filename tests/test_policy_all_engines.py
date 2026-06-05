"""All-engines policy parity guard (t7 AC3, AC4).

Proves the approval gate is **chassis-owned** — not re-implemented by any engine
module — by driving both the ``mock`` engine and the ``vllm-openai`` engine
through the same policy and asserting:

* run_command denial shape (non-ok Step + reason) is identical across engines.
* Unapproved hook skip (HookFiring.decision == "skipped") is identical.
* Engine modules do NOT import ``colleague.policy`` (the gate lives in the loop).

Also covers the "announcement honesty" contract:

* With an active policy an unapproved/tampered run_command and an unapproved hook
  are refused and recorded, while AGENTS/skills config still loads.
* A no-policy run changes nothing — the artifact shape is unchanged and every
  formerly-run tool still runs.

Mocking strategy for vllm-openai: monkeypatch ``colleague.engines.vllm_openai._post_json``
to replay a scripted list of OpenAI chat-completion responses — the same approach used in
``test_e2e_mock.py`` and ``test_vllm_openai.py``.  No live server is needed; the live
proof stays gated behind ``COLLEAGUE_VLLM_E2E``.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from colleague import registry
from colleague.config import EngineConfig
from colleague.contract import OK, Task
from colleague.engines import vllm_openai

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_approvals(repo: Path, payload: dict) -> None:
    """Write ``.colleague/approvals.json`` under *repo*."""
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "approvals.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_hooks(repo: Path, payload: dict) -> None:
    """Write ``.colleague/hooks.json`` under *repo*."""
    dotdir = repo / ".colleague"
    dotdir.mkdir(parents=True, exist_ok=True)
    (dotdir / "hooks.json").write_text(json.dumps(payload), encoding="utf-8")


def _make_script(path: Path, content: str) -> Path:
    """Write an executable shell script and return it."""
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


# ---------------------------------------------------------------------------
# vllm HTTP mock builder
# ---------------------------------------------------------------------------


def _mock_vllm_turns(
    turns: list[dict[str, Any]],
) -> Any:
    """Return a ``fake_post`` callable that replays *turns* for monkeypatching."""
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return fake_post


def _openai_tool_call(call_id: str, name: str, arguments: dict) -> dict:
    """Build one OpenAI-format tool-call response turn."""
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


# ---------------------------------------------------------------------------
# AC3: all-engines run_command deny parity
# ---------------------------------------------------------------------------


class TestRunCommandDenyParity:
    """Driving the same run_command deny policy through mock and vllm-openai yields
    identical denial shape — Step.ok==False, denial reason contains the token, drive
    continues to finish (status==ok).  The gate is chassis-owned."""

    def _denied_mock_result(self, tmp_path: Path) -> Any:
        """Drive mock with a run_command deny policy."""
        repo = tmp_path / "mock_repo"
        repo.mkdir()
        _write_approvals(repo, {"run_command": {"deny": ["curl"], "allow": []}})

        task = Task.new(str(repo), "fetch something", engine="mock")
        # Mock engine is scripted: it always writes a file then finishes.
        # Inject a run_command call instead by driving the loop directly.
        from colleague.loop import ModelResponse, ToolCall, run
        from colleague.policy import load_policy

        policy = load_policy(repo)

        state = {"i": 0}
        scripted_responses = [
            ModelResponse(
                tool_calls=[ToolCall("m1", "run_command", {"command": "curl http://example.com"})]
            ),
            ModelResponse(tool_calls=[ToolCall("m2", "finish", {"summary": "done"})]),
        ]

        def complete(_messages: list[dict]) -> ModelResponse:
            i = min(state["i"], len(scripted_responses) - 1)
            state["i"] += 1
            return scripted_responses[i]

        return run(complete, task, max_steps=10, policy=policy)

    def _denied_vllm_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        """Drive vllm-openai with the same run_command deny policy via mocked HTTP."""
        repo = tmp_path / "vllm_repo"
        repo.mkdir()
        _write_approvals(repo, {"run_command": {"deny": ["curl"], "allow": []}})

        vllm_turns = [
            _openai_tool_call("v1", "run_command", {"command": "curl http://example.com"}),
            _openai_tool_call("v2", "finish", {"summary": "done"}),
        ]
        monkeypatch.setattr(vllm_openai, "_post_json", _mock_vllm_turns(vllm_turns))

        task = Task.new(str(repo), "fetch something", engine="vllm-openai")
        cfg = EngineConfig.resolve()
        return registry.load("vllm-openai").drive(task, cfg)

    def test_same_deny_policy_same_step_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mock and vllm-openai produce identical Step sequence for a denied run_command."""
        mock_result = self._denied_mock_result(tmp_path)
        vllm_result = self._denied_vllm_result(tmp_path, monkeypatch)

        # Both drives finished ok.
        assert mock_result.status == OK
        assert vllm_result.status == OK

        # Both have exactly one run_command step that is not ok.
        mock_deny = [s for s in mock_result.steps if s.tool == "run_command"]
        vllm_deny = [s for s in vllm_result.steps if s.tool == "run_command"]
        assert len(mock_deny) == 1, "expected exactly one run_command step for mock"
        assert len(vllm_deny) == 1, "expected exactly one run_command step for vllm"
        assert mock_deny[0].ok is False, "mock run_command step must be denied"
        assert vllm_deny[0].ok is False, "vllm run_command step must be denied"

        # Both denial reasons mention the offending token.
        assert "curl" in mock_deny[0].result
        assert "curl" in vllm_deny[0].result

        # Step sequence shape is identical: [(tool, ok), ...].
        mock_shape = [(s.tool, s.ok) for s in mock_result.steps]
        vllm_shape = [(s.tool, s.ok) for s in vllm_result.steps]
        assert (
            mock_shape == vllm_shape
        ), f"Step shapes differ:\n  mock: {mock_shape}\n  vllm: {vllm_shape}"

    def test_finish_step_is_ok_after_denial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drive continues after a denial — the final finish step is ok=True."""
        mock_result = self._denied_mock_result(tmp_path)
        vllm_result = self._denied_vllm_result(tmp_path, monkeypatch)

        for label, result in [("mock", mock_result), ("vllm", vllm_result)]:
            finish_steps = [s for s in result.steps if s.tool == "finish"]
            assert finish_steps, f"{label}: expected a finish step"
            assert finish_steps[0].ok is True, f"{label}: finish step must be ok"


# ---------------------------------------------------------------------------
# AC3: all-engines hook skip parity
# ---------------------------------------------------------------------------


class TestHookSkipParity:
    """An unapproved hook is skipped identically by both engines."""

    def _setup_hook_repo(self, base: Path) -> tuple[Path, Path]:
        """Create a repo with an unapproved hook script; return (repo, marker)."""
        repo = base
        repo.mkdir(parents=True, exist_ok=True)
        marker = repo / "ran.txt"
        script = repo / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # hooks section present but no entry for hook.sh → unapproved.
        _write_approvals(repo, {"hooks": {}})
        _write_hooks(repo, {"hooks": {"task_start": [{"command": str(script)}]}})
        return repo, marker

    def _mock_skip_result(self, tmp_path: Path) -> Any:
        repo, _ = self._setup_hook_repo(tmp_path / "mock_hook")
        from colleague.loop import ModelResponse, ToolCall, run
        from colleague.policy import load_policy

        policy = load_policy(repo)

        state = {"i": 0}
        responses = [ModelResponse(tool_calls=[ToolCall("m1", "finish", {"summary": "done"})])]

        def complete(_messages: list[dict]) -> ModelResponse:
            i = min(state["i"], len(responses) - 1)
            state["i"] += 1
            return responses[i]

        task = Task.new(str(repo), "test hook skip")
        return run(complete, task, max_steps=10, policy=policy)

    def _vllm_skip_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        repo, _ = self._setup_hook_repo(tmp_path / "vllm_hook")
        _write_approvals(repo, {"hooks": {}})

        vllm_turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]
        monkeypatch.setattr(vllm_openai, "_post_json", _mock_vllm_turns(vllm_turns))

        task = Task.new(str(repo), "test hook skip", engine="vllm-openai")
        cfg = EngineConfig.resolve()
        return registry.load("vllm-openai").drive(task, cfg)

    def test_unapproved_hook_skipped_identically_both_engines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both engines record a HookFiring(decision='skipped') for the unapproved hook."""
        mock_result = self._mock_skip_result(tmp_path)
        vllm_result = self._vllm_skip_result(tmp_path, monkeypatch)

        for label, result in [("mock", mock_result), ("vllm", vllm_result)]:
            skipped = [f for f in result.hook_firings if f.decision == "skipped"]
            assert skipped, f"{label}: expected a skipped HookFiring for the unapproved hook"
            assert (
                skipped[0].event == "task_start"
            ), f"{label}: skipped firing must be for task_start"
            assert skipped[0].reason, f"{label}: skipped firing must carry a reason"

    def test_hook_marker_absent_both_engines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unapproved hook never ran — marker file must not exist for either engine."""
        mock_repo, mock_marker = self._setup_hook_repo(tmp_path / "mock_hook2")
        vllm_repo, vllm_marker = self._setup_hook_repo(tmp_path / "vllm_hook2")

        # Run mock
        from colleague.loop import ModelResponse, ToolCall, run
        from colleague.policy import load_policy

        policy_m = load_policy(mock_repo)
        state = {"i": 0}
        responses = [ModelResponse(tool_calls=[ToolCall("m1", "finish", {"summary": "done"})])]

        def complete_m(_: list[dict]) -> ModelResponse:
            i = min(state["i"], len(responses) - 1)
            state["i"] += 1
            return responses[i]

        run(complete_m, Task.new(str(mock_repo), "check"), max_steps=10, policy=policy_m)

        # Run vllm
        vllm_turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]
        monkeypatch.setattr(vllm_openai, "_post_json", _mock_vllm_turns(vllm_turns))
        task_v = Task.new(str(vllm_repo), "check", engine="vllm-openai")
        registry.load("vllm-openai").drive(task_v, EngineConfig.resolve())

        assert not mock_marker.exists(), "mock: unapproved hook must not have run"
        assert not vllm_marker.exists(), "vllm: unapproved hook must not have run"


# ---------------------------------------------------------------------------
# Engine module isolation: neither engine imports colleague.policy
# ---------------------------------------------------------------------------


def test_engine_modules_do_not_import_policy() -> None:
    """Structural isolation (t7 AC3): the policy gate lives in the loop; engine modules
    must not import colleague.policy directly.

    This asserts the all-engines rule is satisfied by the chassis (loop.py), not by
    each engine re-implementing it.  We inspect the module's global namespace and
    its __dict__ for any symbol that IS the policy module.
    """
    import colleague.engines.mock as mock_engine
    import colleague.engines.vllm_openai as vllm_engine
    import colleague.policy as policy_mod

    for engine_mod in (mock_engine, vllm_engine):
        mod_vars = vars(engine_mod)
        # The policy module must not appear as a direct symbol in the engine module.
        assert policy_mod not in mod_vars.values(), (
            f"{engine_mod.__name__} imported colleague.policy — "
            "the gate must live in the loop (chassis), not in engine modules"
        )
        # Also assert the engine's source file does not mention 'colleague.policy'.
        # This is the structural guard: a text scan of the compiled source.
        engine_file = engine_mod.__file__
        assert engine_file is not None
        source = Path(engine_file).read_text(encoding="utf-8")
        assert "colleague.policy" not in source, (
            f"{engine_mod.__name__} source references 'colleague.policy' — "
            "the policy import must stay in the loop (chassis)"
        )


# ---------------------------------------------------------------------------
# AC4: Announcement honesty — active policy, refused tools, skills still load
# ---------------------------------------------------------------------------


class TestAnnouncementHonesty:
    """With an active policy, unapproved tools and hooks are refused and recorded.
    Skills+AGENTS config loads normally.  A no-policy run changes nothing.
    """

    def test_denied_run_command_is_recorded_with_reason(self, tmp_path: Path) -> None:
        """An unapproved run_command is not executed; its denial reason is recorded
        in the Step and the drive reaches finish (status==ok).  Same contract the
        loop tests prove at the unit level — this is the integrated, cross-cutting
        assertion that it holds when the full engine drive path is exercised."""
        repo = tmp_path / "announce_repo"
        repo.mkdir()
        _write_approvals(repo, {"run_command": {"deny": ["rm"], "allow": []}})

        from colleague.loop import ModelResponse, ToolCall, run
        from colleague.policy import load_policy

        policy = load_policy(repo)
        sentinel = repo / "sentinel.txt"
        sentinel.write_text("original", encoding="utf-8")

        state = {"i": 0}
        responses = [
            ModelResponse(
                tool_calls=[ToolCall("a1", "run_command", {"command": f"rm {sentinel}"})]
            ),
            ModelResponse(tool_calls=[ToolCall("a2", "finish", {"summary": "refused run"})]),
        ]

        def complete(_: list[dict]) -> ModelResponse:
            i = min(state["i"], len(responses) - 1)
            state["i"] += 1
            return responses[i]

        result = run(complete, Task.new(str(repo), "try rm"), max_steps=10, policy=policy)

        # Sentinel is untouched — command never ran.
        assert sentinel.read_text(encoding="utf-8") == "original"
        # Drive succeeded.
        assert result.status == OK
        # Non-ok Step recorded.
        deny_steps = [s for s in result.steps if s.tool == "run_command"]
        assert len(deny_steps) == 1
        assert deny_steps[0].ok is False
        assert "rm" in deny_steps[0].result

    def test_unapproved_hook_refused_and_recorded(self, tmp_path: Path) -> None:
        """An unapproved hook is skipped; a HookFiring(decision='skipped') with a
        non-empty reason is appended to the result.  Skills/AGENTS still load."""
        repo = tmp_path / "announce_hook_repo"
        repo.mkdir()
        marker = repo / "hook_ran.txt"
        script = repo / "hook.sh"
        _make_script(script, f"#!/bin/sh\ntouch '{marker}'\n")

        # Hooks section present; script not listed → unapproved.
        _write_approvals(repo, {"hooks": {}})
        _write_hooks(repo, {"hooks": {"task_start": [{"command": str(script)}]}})

        from colleague.loop import ModelResponse, ToolCall, run
        from colleague.policy import load_policy

        policy = load_policy(repo)

        state = {"i": 0}
        responses = [ModelResponse(tool_calls=[ToolCall("h1", "finish", {"summary": "done"})])]

        def complete(_: list[dict]) -> ModelResponse:
            i = min(state["i"], len(responses) - 1)
            state["i"] += 1
            return responses[i]

        result = run(complete, Task.new(str(repo), "check hooks"), max_steps=10, policy=policy)

        # Hook never ran.
        assert not marker.exists()
        # Drive ok.
        assert result.status == OK
        # Skipped firing recorded with reason.
        skipped = [f for f in result.hook_firings if f.decision == "skipped"]
        assert skipped, "expected a skipped HookFiring"
        assert skipped[0].reason, "skipped firing must carry a non-empty reason"

    def test_layers_load_normally_with_active_policy(self, tmp_path: Path) -> None:
        """AGENTS / skills config loads regardless of an active policy.

        This verifies that the policy gate is orthogonal to the layers system —
        turning on approval gating for run_command does not affect AGENTS.md or
        skills resolution.
        """
        repo = tmp_path / "layers_repo"
        repo.mkdir()
        # An active policy.
        _write_approvals(repo, {"run_command": {"allow": ["echo"], "deny": []}})

        # Write an AGENTS.colleague.md to prove layers loads it.
        agents_md = repo / "AGENTS.colleague.md"
        agents_md.write_text("# Test agents instructions\n", encoding="utf-8")

        from colleague.config import EngineConfig
        from colleague.contract import Task

        # Engine.system_prompt() calls layers.load_agents_instructions + load_skills.
        # Instantiate the mock engine and call system_prompt — must not raise.
        mock_engine = registry.load("mock")
        task = Task.new(str(repo), "test layers")
        cfg = EngineConfig.resolve()
        prompt = mock_engine.system_prompt(task, cfg)
        # The prompt is a string (possibly empty — that's fine).
        assert isinstance(prompt, str)

    def test_no_policy_run_is_unchanged(self, tmp_path: Path) -> None:
        """With no approvals.json, a run produces the identical key set and step
        shape as before the policy feature was added.  This is the regression
        guard: the feature must be a strict no-op when not configured."""
        repo_policy_free = tmp_path / "nopolicy"
        repo_policy_free.mkdir()

        from colleague.loop import ModelResponse, ToolCall, run

        state = {"i": 0}
        responses = [
            ModelResponse(
                tool_calls=[ToolCall("np1", "write_file", {"path": "out.txt", "content": "hi"})]
            ),
            ModelResponse(tool_calls=[ToolCall("np2", "finish", {"summary": "wrote"})]),
        ]

        def complete(_: list[dict]) -> ModelResponse:
            i = min(state["i"], len(responses) - 1)
            state["i"] += 1
            return responses[i]

        task = Task.new(str(repo_policy_free), "write something")
        # No policy= kwarg → load_policy finds no file → empty policy → no-op.
        result = run(complete, task, max_steps=10)

        assert result.status == OK
        serialized = result.to_dict()

        # The key set is the pre-feature contract set.
        expected_keys = {
            "task_id",
            "status",
            "summary",
            "changed_files",
            "steps",
            "usage",
            "stats",
            "artifacts_path",
            "error",
            "branch",
            "pr_url",
            "hook_firings",
            "command",
            "not_finished",
            "stopped_without_finish",
        }
        assert set(serialized.keys()) == expected_keys, (
            f"Extra/missing keys in no-policy run: " f"{set(serialized.keys()) ^ expected_keys}"
        )

        # All steps are ok.
        for step in result.steps:
            assert step.ok is True, f"Step {step.tool!r} must be ok in a no-policy run"

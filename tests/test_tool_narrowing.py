"""Tool-narrowing consumption: schema + executor intersect (plan task t3, spec c8/h8).

The change-content consumption lane
(``docs/specs/2026-08-06-change-content-consumption-lane.md``): an applied
``worker.tools`` narrowing on the episode's config-lifecycle snapshot
intersects the role-curated tool surface on BOTH halves of the EXISTING role
mechanism — the offered schema (:func:`colleague.tools.curate_schemas`) and
the :class:`~colleague.tools.ToolExecutor` allow-list (``allowlist=role``) —
composed through ONE new helper,
:func:`colleague.tools.narrow_role_by_tool_set`, so the two halves can never
diverge and no second refusal mechanism is ever added.

These tests FAIL on the pre-t3 tree: ``narrow_role_by_tool_set`` does not
exist, ``EngineConfig`` has no ``config_lifecycle`` field, and neither engine
reads a snapshot's ``tool_set`` at all — every tool is offered/allowed
regardless of any (nonexistent) narrowing.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from colleague.config import EngineConfig
from colleague.configlifecycle import (
    WINDOW_BEFORE_EPISODE_1,
    EpisodeConfigLifecycle,
)
from colleague.contract import OK, Task
from colleague.engines import vllm_openai
from colleague.engines.mock import OUTPUT_FILE, MockEngine
from colleague.lattice import CapabilityCatalog, ChangeUnit, Origin, Target
from colleague.roles import BUILTIN_ROLES, Role
from colleague.tools import ToolError, ToolExecutor, curate_schemas, narrow_role_by_tool_set

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


@dataclass(frozen=True)
class _FakeSnapshot:
    tool_set: tuple[str, ...] = ()


class _FakeLifecyclePropertyStyle:
    """Mirrors the REAL :class:`EpisodeConfigLifecycle`'s shape: ``snapshot``
    is a read-only PROPERTY (already evaluated), never a callable method.

    Also implements ``observe_turn``/``end_episode`` as no-ops — the loop
    (``colleague/loop.py``, pre-existing, forward-compatible getattr) already
    calls those on ANY ``config.config_lifecycle`` attachment unconditionally
    (not this task's file scope), so a double driven through a real
    ``engine.work()`` call must answer them to avoid an unrelated
    ``AttributeError`` masking the narrowing behaviour under test.
    """

    def __init__(self, tool_set: tuple[str, ...] = ()) -> None:
        self._snapshot = _FakeSnapshot(tool_set)

    @property
    def snapshot(self) -> _FakeSnapshot:
        return self._snapshot

    def observe_turn(self) -> str:
        return ""

    def end_episode(self) -> int:
        return 0


class _FakeLifecycleMethodStyle:
    """Mirrors a possible future frozen child-view adapter (t10): ``snapshot()``
    is a CALLABLE method — the defensive read must handle both shapes.

    See :class:`_FakeLifecyclePropertyStyle` for why ``observe_turn``/
    ``end_episode`` no-ops are also required.
    """

    def __init__(self, tool_set: tuple[str, ...] = ()) -> None:
        self._snapshot = _FakeSnapshot(tool_set)

    def snapshot(self) -> _FakeSnapshot:
        return self._snapshot

    def observe_turn(self) -> str:
        return ""

    def end_episode(self) -> int:
        return 0


def _openai_tool_call(call_id: str, name: str, arguments: dict) -> dict:
    """Build one OpenAI-format tool-call response turn (mirrors test_policy_all_engines)."""
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


def _capturing_vllm_post(turns: list[dict[str, Any]], captured_payloads: list[dict]):
    """A ``fake_post`` that replays *turns* AND records every payload it saw."""
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        captured_payloads.append(payload)
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    return fake_post


# ===========================================================================
# 1. narrow_role_by_tool_set — pure function
# ===========================================================================


class TestNarrowRoleByToolSet:
    def test_empty_tool_set_returns_role_unchanged(self) -> None:
        writer = BUILTIN_ROLES["writer"]
        assert narrow_role_by_tool_set(writer, ()) is writer

    def test_default_tool_set_returns_role_unchanged(self) -> None:
        writer = BUILTIN_ROLES["writer"]
        assert narrow_role_by_tool_set(writer) is writer

    def test_none_role_and_empty_tool_set_stays_none(self) -> None:
        assert narrow_role_by_tool_set(None, ()) is None

    def test_intersects_role_surface_with_tool_set(self) -> None:
        writer = BUILTIN_ROLES["writer"]
        narrowed = narrow_role_by_tool_set(writer, ("read_file", "list_dir"))
        assert isinstance(narrowed, Role)
        assert set(narrowed.tool_allowlist) == {"read_file", "list_dir"}

    def test_tool_set_entry_outside_role_surface_adds_nothing(self) -> None:
        explorer = BUILTIN_ROLES["explorer"]
        assert "write_file" not in explorer.tool_allowlist
        narrowed = narrow_role_by_tool_set(explorer, ("write_file", "read_file"))
        assert "write_file" not in narrowed.tool_allowlist
        assert "read_file" in narrowed.tool_allowlist

    def test_narrowing_never_widens_past_the_role_ceiling(self) -> None:
        explorer = BUILTIN_ROLES["explorer"]
        narrowed = narrow_role_by_tool_set(explorer, tuple(BUILTIN_ROLES["writer"].tool_allowlist))
        # tool_set names the whole writer surface, but explorer's own ceiling
        # still bounds the result — never adds a tool explorer withheld. t5
        # (q9/q10): the writer surface no longer includes "web", so that one
        # explorer-held name is the sole exclusion from the intersection.
        assert set(narrowed.tool_allowlist) == set(explorer.tool_allowlist) - {"web"}

    def test_role_none_narrows_full_surface_straight_to_tool_set(self) -> None:
        narrowed = narrow_role_by_tool_set(None, ("read_file", "list_dir"))
        assert isinstance(narrowed, Role)
        assert set(narrowed.tool_allowlist) == {"read_file", "list_dir"}
        assert narrowed.read_only is False  # None meant unrestricted, never read-only

    def test_preserves_read_only_flag(self) -> None:
        explorer = BUILTIN_ROLES["explorer"]
        assert explorer.read_only is True
        narrowed = narrow_role_by_tool_set(explorer, ("read_file",))
        assert narrowed.read_only is True

    def test_preserves_role_name_and_prompt_fragment(self) -> None:
        writer = BUILTIN_ROLES["writer"]
        narrowed = narrow_role_by_tool_set(writer, ("read_file",))
        assert narrowed.name == writer.name
        assert narrowed.prompt_fragment == writer.prompt_fragment

    def test_role_name_string_is_resolved_like_curate_schemas(self) -> None:
        narrowed = narrow_role_by_tool_set("explorer", ("read_file", "write_file"))
        assert isinstance(narrowed, Role)
        assert set(narrowed.tool_allowlist) == {"read_file"}

    def test_unknown_role_name_string_raises(self) -> None:
        with pytest.raises(ValueError):
            narrow_role_by_tool_set("not-a-real-role", ("read_file",))


# ===========================================================================
# 2. ToolExecutor allowlist composition — ONE mechanism, same refusal shape
# ===========================================================================


class TestExecutorAllowlistComposition:
    def test_narrowed_away_tool_refuses_with_role_withholding_shape(self, tmp_path: Path) -> None:
        # Baseline: a role that never had write_file (role-withheld refusal).
        explorer = BUILTIN_ROLES["explorer"]
        ex_role_withheld = ToolExecutor(tmp_path, allowlist=explorer)
        with pytest.raises(ToolError) as role_exc:
            ex_role_withheld.execute("write_file", {"path": "a.txt", "content": "x"})

        # writer normally allows write_file; narrow it away via tool_set.
        writer = BUILTIN_ROLES["writer"]
        assert "write_file" in writer.tool_allowlist
        narrowed = narrow_role_by_tool_set(writer, ("read_file", "list_dir"))
        ex_narrowed = ToolExecutor(tmp_path, allowlist=narrowed)
        with pytest.raises(ToolError) as narrow_exc:
            ex_narrowed.execute("write_file", {"path": "b.txt", "content": "y"})

        # Same refusal shape — literally the same message template, since both
        # go through the identical ``self._allowlist`` check in ``execute()``.
        assert str(role_exc.value) == str(narrow_exc.value)
        assert str(narrow_exc.value) == "tool 'write_file' is not allowed for this role"

    def test_tool_set_entry_outside_role_adds_nothing_at_executor(self, tmp_path: Path) -> None:
        explorer = BUILTIN_ROLES["explorer"]
        narrowed = narrow_role_by_tool_set(explorer, ("write_file",))
        ex = ToolExecutor(tmp_path, allowlist=narrowed)
        with pytest.raises(ToolError):
            ex.execute("write_file", {"path": "c.txt", "content": "z"})

    def test_narrowing_still_permits_a_kept_tool(self, tmp_path: Path) -> None:
        writer = BUILTIN_ROLES["writer"]
        narrowed = narrow_role_by_tool_set(writer, ("write_file",))
        ex = ToolExecutor(tmp_path, allowlist=narrowed)
        out = ex.execute("write_file", {"path": "d.txt", "content": "ok"})
        assert out.changed_file == "d.txt"

    def test_no_second_refusal_mechanism_is_added(self) -> None:
        # ToolExecutor.execute's ONE allowlist check is untouched by this task —
        # the narrowing composes entirely into the value handed to
        # ``allowlist=``, never a second gate inside ToolExecutor itself.
        import inspect

        source = inspect.getsource(ToolExecutor.execute)
        assert source.count("is not allowed for this role") == 1


# ===========================================================================
# 3. Mock engine consumes the narrowing (criteria 1 [schema-vacuous side],
#    2, 3 on the mock backend)
# ===========================================================================


class TestMockEngineConsumesNarrowing:
    def test_narrowed_away_write_tool_mutates_nothing(self, git_repo: Path) -> None:
        # "writer" role's full surface includes write_file; the scripted mock
        # turn always tries write_file first. Narrow it away and prove the
        # executor refuses it — the mock's ONE tool-enforcement point.
        cfg = EngineConfig(
            role="writer",
            config_lifecycle=_FakeLifecyclePropertyStyle(("list_dir", "read_file", "finish")),
        )
        res = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg)
        assert res.changed_files == [], "a narrowed-away write_file must not have executed"
        refusal_steps = [s for s in res.steps if s.tool == "write_file"]
        assert refusal_steps
        assert refusal_steps[0].ok is False
        assert "not allowed for this role" in refusal_steps[0].result

    def test_narrowing_permits_a_kept_write_tool(self, git_repo: Path) -> None:
        cfg = EngineConfig(
            role="writer",
            config_lifecycle=_FakeLifecyclePropertyStyle(("write_file", "finish")),
        )
        res = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg)
        assert res.changed_files == [OUTPUT_FILE]

    def test_callable_snapshot_method_style_is_also_honored(self, git_repo: Path) -> None:
        # A future frozen child-view adapter (t10) may expose snapshot() as a
        # callable rather than a property — the defensive read must accept it.
        cfg = EngineConfig(
            role="writer",
            config_lifecycle=_FakeLifecycleMethodStyle(("list_dir", "read_file", "finish")),
        )
        res = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg)
        assert res.changed_files == []

    def test_absent_lifecycle_is_byte_identical(self, git_repo: Path) -> None:
        cfg_no_field = EngineConfig(role="writer")
        cfg_none = EngineConfig(role="writer", config_lifecycle=None)
        res1 = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg_no_field)
        res2 = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg_none)
        assert res1.changed_files == res2.changed_files == [OUTPUT_FILE]
        assert res1.status == res2.status == OK

    def test_empty_snapshot_tool_set_is_not_narrowed(self, git_repo: Path) -> None:
        # c26: () on the snapshot means not-narrowed — byte-identical to an
        # absent lifecycle entirely.
        cfg_lifecycle_empty = EngineConfig(
            role="writer", config_lifecycle=_FakeLifecyclePropertyStyle(())
        )
        cfg_absent = EngineConfig(role="writer")
        res1 = MockEngine().work(
            Task.new(str(git_repo), "do it", engine="mock"), cfg_lifecycle_empty
        )
        res2 = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg_absent)
        assert res1.changed_files == res2.changed_files == [OUTPUT_FILE]


# ===========================================================================
# 4. vLLM-openai engine consumes the narrowing (criteria 1, 2, 3 on the wire)
# ===========================================================================


class TestVllmEngineConsumesNarrowing:
    def test_offered_schema_is_intersection_of_role_and_tool_set(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict] = []
        turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured))

        cfg = EngineConfig(
            role="writer",
            config_lifecycle=_FakeLifecyclePropertyStyle(("read_file", "list_dir", "finish")),
        )
        task = Task.new(str(git_repo), "do it", engine="vllm-openai")
        vllm_openai.VllmOpenAIEngine().work(task, cfg)

        assert captured, "the engine must have sent at least one completion request"
        sent_tool_names = {t["function"]["name"] for t in captured[0]["tools"]}
        assert sent_tool_names == {"read_file", "list_dir", "finish"}

    def test_narrowed_away_tool_refuses_at_the_executor(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict] = []
        turns = [
            _openai_tool_call("v1", "write_file", {"path": "x.txt", "content": "no"}),
            _openai_tool_call("v2", "finish", {"summary": "done"}),
        ]
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured))

        cfg = EngineConfig(
            role="writer",
            config_lifecycle=_FakeLifecyclePropertyStyle(("read_file", "list_dir", "finish")),
        )
        task = Task.new(str(git_repo), "do it", engine="vllm-openai")
        res = vllm_openai.VllmOpenAIEngine().work(task, cfg)

        assert res.changed_files == []
        write_steps = [s for s in res.steps if s.tool == "write_file"]
        assert write_steps
        assert write_steps[0].ok is False
        assert "not allowed for this role" in write_steps[0].result

    def test_tool_set_entry_outside_role_surface_never_offered(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict] = []
        turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured))

        # explorer never has write_file; naming it in tool_set must add nothing.
        cfg = EngineConfig(
            role="explorer",
            config_lifecycle=_FakeLifecyclePropertyStyle(("write_file", "read_file", "finish")),
        )
        task = Task.new(str(git_repo), "do it", engine="vllm-openai")
        vllm_openai.VllmOpenAIEngine().work(task, cfg)

        sent_tool_names = {t["function"]["name"] for t in captured[0]["tools"]}
        assert "write_file" not in sent_tool_names
        assert "read_file" in sent_tool_names

    def test_absent_narrowing_is_byte_identical(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]

        captured_before: list[dict] = []
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured_before))
        cfg_before = EngineConfig(role="writer")
        vllm_openai.VllmOpenAIEngine().work(
            Task.new(str(git_repo), "do it", engine="vllm-openai"), cfg_before
        )

        captured_after: list[dict] = []
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured_after))
        cfg_after = EngineConfig(role="writer", config_lifecycle=None)
        vllm_openai.VllmOpenAIEngine().work(
            Task.new(str(git_repo), "do it", engine="vllm-openai"), cfg_after
        )

        names_before = {t["function"]["name"] for t in captured_before[0]["tools"]}
        names_after = {t["function"]["name"] for t in captured_after[0]["tools"]}
        assert names_before == names_after

    def test_empty_snapshot_tool_set_is_byte_identical_to_absent(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]

        captured_empty: list[dict] = []
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured_empty))
        cfg_empty = EngineConfig(role="writer", config_lifecycle=_FakeLifecyclePropertyStyle(()))
        vllm_openai.VllmOpenAIEngine().work(
            Task.new(str(git_repo), "do it", engine="vllm-openai"), cfg_empty
        )

        captured_absent: list[dict] = []
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured_absent))
        cfg_absent = EngineConfig(role="writer")
        vllm_openai.VllmOpenAIEngine().work(
            Task.new(str(git_repo), "do it", engine="vllm-openai"), cfg_absent
        )

        names_empty = {t["function"]["name"] for t in captured_empty[0]["tools"]}
        names_absent = {t["function"]["name"] for t in captured_absent[0]["tools"]}
        assert names_empty == names_absent


# ===========================================================================
# 5. All-engines parity: the SAME narrowing yields the SAME effective surface
#    on both backends (acceptance 1, "on BOTH mock and vllm-openai")
# ===========================================================================


class TestAllEnginesParity:
    def test_offered_and_effective_surface_match_across_engines(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tool_set = ("read_file", "list_dir", "write_file", "finish")
        role = "writer"
        expected = {
            s["function"]["name"] for s in curate_schemas(narrow_role_by_tool_set(role, tool_set))
        }
        assert expected == set(tool_set)

        # vLLM half: the actual wire payload's "tools" names.
        captured: list[dict] = []
        turns = [_openai_tool_call("v1", "finish", {"summary": "done"})]
        monkeypatch.setattr(vllm_openai, "_post_json", _capturing_vllm_post(turns, captured))
        cfg_vllm = EngineConfig(role=role, config_lifecycle=_FakeLifecyclePropertyStyle(tool_set))
        vllm_openai.VllmOpenAIEngine().work(
            Task.new(str(git_repo), "do it", engine="vllm-openai"), cfg_vllm
        )
        vllm_names = {t["function"]["name"] for t in captured[0]["tools"]}
        assert vllm_names == expected

        # Mock half: the mock has no wire, so its enforcement point is the
        # executor allowlist — directly construct it the same way mock.py's
        # work() does, and prove it matches the SAME expected surface.
        narrowed_role = narrow_role_by_tool_set(BUILTIN_ROLES[role], tool_set)
        ex = ToolExecutor(git_repo, allowlist=narrowed_role)
        assert ex._allowlist == expected  # noqa: SLF001 - direct introspection, tests-only


# ===========================================================================
# 6. Real EpisodeConfigLifecycle integration (not just fakes)
# ===========================================================================


def _catalog(tool_ids: list[str]) -> CapabilityCatalog:
    return CapabilityCatalog(tool_ids=tuple(tool_ids))


def _tools_change(tool_ids: list[str], origin: Origin = Origin.CORTEX) -> ChangeUnit:
    return ChangeUnit(target=Target.WORKER_TOOLS, origin=origin, tool_ids=tool_ids)


class TestRealLifecycleIntegration:
    def test_real_lifecycle_applied_narrowing_reaches_mock_executor(self, git_repo: Path) -> None:
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file", "list_dir", "finish"]))
        verdict = lifecycle.propose(_tools_change(["read_file", "list_dir", "finish"]))
        assert verdict.allowed is True
        lifecycle.apply_window(WINDOW_BEFORE_EPISODE_1)
        assert lifecycle.snapshot.tool_set == ("read_file", "list_dir", "finish")

        cfg = EngineConfig(role="writer", config_lifecycle=lifecycle)
        res = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg)

        assert (
            res.changed_files == []
        ), "write_file must be refused via the REAL lifecycle's applied narrowing"

    def test_real_lifecycle_no_applied_change_is_not_narrowed(self, git_repo: Path) -> None:
        # A lifecycle with nothing ever applied keeps EpisodeConfigSnapshot's
        # default tool_set == () — not-narrowed (c26).
        lifecycle = EpisodeConfigLifecycle(catalog=_catalog(["read_file"]))
        assert lifecycle.snapshot.tool_set == ()

        cfg = EngineConfig(role="writer", config_lifecycle=lifecycle)
        res = MockEngine().work(Task.new(str(git_repo), "do it", engine="mock"), cfg)

        assert res.changed_files == [OUTPUT_FILE]

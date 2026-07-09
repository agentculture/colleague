"""Cortex-side self-knowledge injection (self-knowledge arc, t9 / #306).

When the operator's message is a *self-knowledge* question — a question about
colleague itself (identity, architecture, gates, capabilities) — the loop
injects ONE advisory companion message BEFORE the first cortex turn carrying
(a) the LIVE guide-doc index (``build_guide_index``) and (b) the resolved
self-facts block (``build_self_facts``), so cortex answers from colleague's own
docs + runtime state instead of guessing. The operator's original question is
never replaced — the advisory augments it (the recall-before/context-packet
precedent).

The gate is the deterministic
:func:`colleague.selfknowledge.classify_selfknowledge`. An ordinary work item is
a STRICT no-op — no guide index, no self-facts, no extra message — so the guide
docs are loaded ONLY when a self-knowledge turn triggers it (#306): the
byte-identical pin is written FIRST below.

All-engines: the injection lives in the shared :func:`colleague.loop.run` path,
so it fires identically for ``mock`` and ``vllm-openai``. It is exercised here
directly through ``run`` (the shared path both engines call — the senses-loop
precedent) AND through the real ``mock`` engine's ``work()`` path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague import registry
from colleague.config import EngineConfig, SensesConfig
from colleague.contract import OK, Task
from colleague.loop import ContextControls, ModelResponse, ToolCall, run

_SELF_KNOWLEDGE_QUESTION = "what model are you and how does the affected-tests gate work?"
_ORDINARY_INSTRUCTION = "fix the bug in foo.py"


def _finish_complete(seen: list):
    """A fake ``complete`` that records the messages it is handed, then finishes.

    Mirrors ``tests/test_loop_senses.py`` — capturing ``seen[0]`` is how we pin
    the exact initial messages the loop composes before the first completion.
    """

    def complete(messages: list[dict]) -> ModelResponse:
        seen.append([dict(m) for m in messages])
        return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

    return complete


def _make_guide_repo(root: Path) -> None:
    """Populate *root* with the two locations ``build_guide_index`` scans.

    A ``CLAUDE.md`` at the root + a couple of ``docs/features/*.md`` files, so a
    self-knowledge turn has a real guide index to fold in — and, on the ordinary
    turn, proves the docs are loaded ONLY for a self-knowledge turn (#306).
    """
    (root / "CLAUDE.md").write_text("# colleague\n", encoding="utf-8")
    features = root / "docs" / "features"
    features.mkdir(parents=True, exist_ok=True)
    (features / "affected-tests.md").write_text("# affected tests\n", encoding="utf-8")
    (features / "example-feature.md").write_text("# example\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Byte-identical pin (written FIRST): an ordinary instruction is a strict no-op.
# ---------------------------------------------------------------------------


def test_ordinary_instruction_is_byte_identical_no_injection(tmp_path: Path) -> None:
    """An ordinary work item — even in a repo that HAS guide docs — composes the
    exact same initial messages as pre-feature colleague: system + one verbatim
    user message, no guide index, no self-facts, no advisory companion.

    This is the #306 acceptance: the guide knowledge is loaded ONLY when a
    self-knowledge turn triggers it — base context is byte-identical otherwise.
    """
    _make_guide_repo(tmp_path)
    seen: list = []
    task = Task.new(str(tmp_path), _ORDINARY_INSTRUCTION)
    result = run(_finish_complete(seen), task, max_steps=3, model="cortex-model-x")

    assert result.status == OK
    first = seen[0]
    # Exactly system + one user turn — no advisory companion was appended.
    assert [m["role"] for m in first] == ["system", "user"]
    assert first[1]["content"] == _ORDINARY_INSTRUCTION
    # No self-knowledge advisory, no guide index, no facts block anywhere.
    assert not [m for m in first if str(m.get("content", "")).startswith("[self-knowledge]")]
    joined = "\n".join(str(m.get("content", "")) for m in first)
    assert "CLAUDE.md" not in joined
    assert "docs/features/" not in joined
    assert "cortex-model-x" not in joined  # the facts block was never built


# ---------------------------------------------------------------------------
# Injection: a self-knowledge turn folds in the guide index + self-facts.
# ---------------------------------------------------------------------------


def test_self_knowledge_turn_injects_guide_index_and_self_facts(tmp_path: Path) -> None:
    """A self-knowledge question produces ONE advisory companion carrying the
    guide-doc paths AND the resolved self-facts, while the operator's original
    instruction stays cortex's first user message VERBATIM (augment, never
    replace)."""
    _make_guide_repo(tmp_path)
    seen: list = []
    task = Task.new(str(tmp_path), _SELF_KNOWLEDGE_QUESTION)
    result = run(_finish_complete(seen), task, max_steps=3, model="cortex-model-x")

    assert result.status == OK
    first = seen[0]
    # The operator's question is cortex's first user message, verbatim.
    user_msgs = [m for m in first if m.get("role") == "user"]
    assert user_msgs[0]["content"] == _SELF_KNOWLEDGE_QUESTION
    # Exactly ONE advisory companion, and it is a DIFFERENT message.
    advisory = [
        m
        for m in first
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[self-knowledge]")
    ]
    assert len(advisory) == 1
    body = advisory[0]["content"]
    assert body != _SELF_KNOWLEDGE_QUESTION
    # (a) guide doc paths from build_guide_index.
    assert "CLAUDE.md" in body
    assert "docs/features/affected-tests.md" in body
    assert "docs/features/example-feature.md" in body
    # (b) the build_self_facts block: the cortex model id + the gates line.
    assert "cortex: cortex-model-x" in body
    assert "gates:" in body
    # Honest ABSENT lines: no senses/lobes threaded (direct run, no controls) —
    # never a fabricated senses id or gateway URL.
    assert "senses: not configured" in body
    assert "lobes: not armed" in body


def test_self_knowledge_armed_renders_real_senses_and_gateway(tmp_path: Path) -> None:
    """The armed inverse of the honest-absent pin: when the session resolved a
    senses model + lobes gateway (threaded through ContextControls), the facts
    block renders the EXACT senses model id + gateway URL — a present value must
    never render as the false 'not configured'/'not armed'."""
    _make_guide_repo(tmp_path)
    seen: list = []
    task = Task.new(str(tmp_path), _SELF_KNOWLEDGE_QUESTION)
    controls = ContextControls(
        senses_model="gemma-senses-12b", lobes_gateway="http://lobes.local:8001"
    )
    result = run(
        _finish_complete(seen), task, max_steps=3, model="cortex-model-x", context=controls
    )

    assert result.status == OK
    advisory = [
        m
        for m in seen[0]
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[self-knowledge]")
    ]
    assert len(advisory) == 1
    body = advisory[0]["content"]
    assert "senses: gemma-senses-12b" in body
    assert "lobes: http://lobes.local:8001" in body
    # The armed values REPLACE the absent lines — no false statement remains.
    assert "senses: not configured" not in body
    assert "lobes: not armed" not in body


def test_self_knowledge_facts_degrade_to_guide_only_without_model(tmp_path: Path) -> None:
    """Honest degradation: with NO resolved cortex model id (a direct ``run``
    caller that passed no ``model``), the advisory carries the guide index alone
    and NEVER a fabricated facts block."""
    _make_guide_repo(tmp_path)
    seen: list = []
    task = Task.new(str(tmp_path), _SELF_KNOWLEDGE_QUESTION)
    result = run(_finish_complete(seen), task, max_steps=3)  # no model=

    assert result.status == OK
    advisory = [
        m
        for m in seen[0]
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[self-knowledge]")
    ]
    assert len(advisory) == 1
    body = advisory[0]["content"]
    # Guide index present …
    assert "CLAUDE.md" in body
    # … but no facts block (no fabricated "cortex:" / "gates:" line).
    assert "cortex:" not in body
    assert "gates:" not in body


def test_self_knowledge_noop_when_no_guides_and_no_model(tmp_path: Path) -> None:
    """In a bare repo (no CLAUDE.md, no docs/features) with no model, a
    self-knowledge turn still injects exactly ONE advisory (the header primes
    cortex) and never crashes — the guide index is simply empty."""
    seen: list = []
    task = Task.new(str(tmp_path), _SELF_KNOWLEDGE_QUESTION)
    result = run(_finish_complete(seen), task, max_steps=3)

    assert result.status == OK
    advisory = [
        m
        for m in seen[0]
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[self-knowledge]")
    ]
    assert len(advisory) == 1
    # The operator's question still stands as the first user message.
    assert [m for m in seen[0] if m.get("role") == "user"][0]["content"] == _SELF_KNOWLEDGE_QUESTION


# ---------------------------------------------------------------------------
# All-engines: the same behavior through the real mock engine's work() path.
# ---------------------------------------------------------------------------


def test_ordinary_run_through_mock_engine_unaffected(tmp_path: Path) -> None:
    """An ordinary work item through the real ``mock`` engine — with guide docs
    present — runs normally: status OK, it edited the repo, and no new TaskResult
    key leaked (the feature adds no artifact field). The pin at the shared-run
    level above proves no message was injected."""
    _make_guide_repo(tmp_path)
    cfg = EngineConfig.resolve()
    result = registry.load("mock").work(Task.new(str(tmp_path), "do work"), cfg)

    assert result.status == OK
    assert result.changed_files  # the mock actually wrote its marker file
    # No new omit-when-None key introduced by this feature.
    assert "incompletion" not in result.to_dict() or result.to_dict().get("incompletion")


def test_self_knowledge_fires_through_mock_engine_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injection fires identically on the real ``mock`` engine's ``work()``
    path (all-engines rule): a recording script substituted for the mock's own
    observes the ``[self-knowledge]`` advisory carrying the guide index + a facts
    block resolved from the mock's ``config.model``."""
    _make_guide_repo(tmp_path)
    seen: list = []

    def _recording_script(_task):
        def complete(messages: list[dict]) -> ModelResponse:
            seen.append([dict(m) for m in messages])
            return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", _recording_script)
    cfg = EngineConfig.resolve()
    result = registry.load("mock").work(Task.new(str(tmp_path), "what model are you?"), cfg)

    assert result.status == OK
    advisory = [
        m
        for m in seen[0]
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[self-knowledge]")
    ]
    assert len(advisory) == 1
    body = advisory[0]["content"]
    assert "CLAUDE.md" in body
    assert f"cortex: {cfg.model}" in body  # facts resolved from the mock's config.model


def test_armed_config_threads_through_from_config_on_mock_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All-engines armed path: an EngineConfig carrying a resolved SensesConfig +
    lobes_gateway_url reaches the advisory through the shared
    ``ContextControls.from_config`` seam BOTH engines build their controls with —
    proven end-to-end on the real ``mock`` engine's ``work()`` path."""
    _make_guide_repo(tmp_path)
    seen: list = []

    def _recording_script(_task):
        def complete(messages: list[dict]) -> ModelResponse:
            seen.append([dict(m) for m in messages])
            return ModelResponse(tool_calls=[ToolCall("1", "finish", {"summary": "done"})])

        return complete

    monkeypatch.setattr("colleague.engines.mock._script", _recording_script)
    cfg = EngineConfig.resolve()
    cfg.senses = SensesConfig(
        model="gemma-senses-12b", base_url="http://x", api_key="k", context_budget=24000
    )
    cfg.lobes_gateway_url = "http://lobes.local:8001"
    result = registry.load("mock").work(Task.new(str(tmp_path), "what model are you?"), cfg)

    assert result.status == OK
    advisory = [
        m
        for m in seen[0]
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[self-knowledge]")
    ]
    assert len(advisory) == 1
    body = advisory[0]["content"]
    assert "senses: gemma-senses-12b" in body
    assert "lobes: http://lobes.local:8001" in body
    assert "senses: not configured" not in body
    assert "lobes: not armed" not in body


def test_from_config_populates_self_knowledge_fields() -> None:
    """The from_config mapping itself (the single source both engines share):
    senses_model/lobes_gateway are filled when armed and stay "" when absent."""
    armed = EngineConfig.resolve()
    armed.senses = SensesConfig(
        model="gemma-senses-12b", base_url="http://x", api_key="k", context_budget=24000
    )
    armed.lobes_gateway_url = "http://lobes.local:8001"
    controls = ContextControls.from_config(armed)
    assert controls.senses_model == "gemma-senses-12b"
    assert controls.lobes_gateway == "http://lobes.local:8001"

    bare = EngineConfig.resolve()
    bare_controls = ContextControls.from_config(bare)
    assert bare_controls.senses_model == ""
    assert bare_controls.lobes_gateway == ""

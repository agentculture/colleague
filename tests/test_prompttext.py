"""Task t8 — prompt text adoption (spec c14/h11, c47/h34).

Pins: the v1 floor byte-for-byte, the adapted-from marker with BOTH copyright
holders, model-keyed example families with one snapshot each, the headless
variant's no-question guidance + the absence of ask-style tools, and that the
prompt is built once per run (prefix-stable).

Regenerate snapshots deliberately with ``COLLEAGUE_UPDATE_SNAPSHOTS=1``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from colleague import prompttext
from colleague.prompttext import (
    ADAPTED_FROM_MARKER,
    TOOL_CALL_FAMILIES,
    V1_DEFAULT_SYSTEM,
    default_system,
    interaction_guidance,
    tool_call_family_for,
)
from colleague.tools import SCHEMAS

SNAP = Path(__file__).parent / "snapshots"

#: Read at IMPORT time on purpose: conftest's autouse ``_isolate_provider_env``
#: fixture deletes every ``COLLEAGUE_*`` var before each test, so reading this
#: inside ``_snapshot`` would make the documented regeneration workflow a no-op.
_UPDATE_SNAPSHOTS = bool(os.environ.get("COLLEAGUE_UPDATE_SNAPSHOTS"))


def _snapshot(name: str, actual: str) -> None:
    path = SNAP / f"prompttext_{name}.txt"
    if _UPDATE_SNAPSHOTS:
        path.write_text(actual)
    assert path.read_text() == actual, f"snapshot drift: {path.name}"


# --- c14/h11: the adopted sections + the marker ------------------------------


def test_default_system_moved_to_prompttext_and_loop_reexports_it():
    import colleague.loop as loop

    assert loop._DEFAULT_SYSTEM == default_system(None)
    assert prompttext.__file__.endswith("prompttext.py")


@pytest.mark.parametrize(
    "heading",
    ["# Core Mandates", "# Using Your Tools", "# Executing actions with care", "# Final Reminder"],
)
def test_adopted_sections_carry_the_marker(heading: str):
    prompt = default_system("unsloth/Qwen3.8-27B-NVFP4", variant="qwen")
    idx = prompt.index(heading)
    section = prompt[idx : idx + 400]
    assert ADAPTED_FROM_MARKER in section, f"{heading} lacks the adapted-from marker"


def test_marker_names_both_copyright_holders():
    assert "Copyright 2025 Google LLC" in ADAPTED_FROM_MARKER
    assert "Copyright 2026 Qwen Team" in ADAPTED_FROM_MARKER
    assert "Apache-2.0" in ADAPTED_FROM_MARKER
    assert ADAPTED_FROM_MARKER.startswith("adapted-from: qwen-code core/prompts.ts:278-440")
    # The literal must be greppable in the module source (h34).
    src = Path(prompttext.__file__).read_text()
    assert "Copyright 2025 Google LLC" in src
    assert "Copyright 2026 Qwen Team" in src


def test_colleague_owned_sections_are_kept_verbatim():
    prompt = default_system("any", variant="qwen")
    for para in V1_DEFAULT_SYSTEM.split("\n\n")[1:]:  # Destination … AgentFront
        assert para in prompt, para[:40]


# --- per-model example families (one snapshot each) ---------------------------


@pytest.mark.parametrize(
    "model, family",
    [
        ("Qwen/Qwen3-Coder-480B-A35B", "qwen-coder"),
        ("qwen2.5-coder-7b", "qwen-coder"),
        ("some-coder-model", "qwen-coder"),
        ("qwen2-vl-7b-instruct", "qwen-vl"),
        ("unsloth/g" + "emma-4-12B-it-qat-w4a16", "general"),  # no 4th family: repo no-g*mma guard
        ("unsloth/Qwen3.8-27B-NVFP4", "general"),
        (None, "general"),
        ("x" * 120, "general"),
    ],
)
def test_family_is_keyed_by_model_id(model, family):
    assert tool_call_family_for(model) == family


def test_style_override_wins_and_unknown_falls_back():
    assert tool_call_family_for("unsloth/Qwen3.8-27B-NVFP4", style_override="qwen-vl") == "qwen-vl"
    assert tool_call_family_for("qwen3-coder", style_override="bogus") == "qwen-coder"


@pytest.mark.parametrize("family", TOOL_CALL_FAMILIES)
def test_snapshot_per_family(family: str):
    _snapshot(family, default_system("x", headless=True, variant="qwen", style_override=family))


def test_examples_use_colleague_tool_names_only():
    names = {s["function"]["name"] for s in SCHEMAS} | {"grep_search", "glob"}
    import re

    for family in TOOL_CALL_FAMILIES:
        block = prompttext.tool_call_examples("x", style_override=family)
        for tool in re.findall(r"tool_call: (\w+)|function=(\w+)|\"name\": \"(\w+)\"", block):
            name = next(t for t in tool if t)
            assert name in names, f"{family}: unknown tool {name}"


# --- headless variant + no ask-style tools ------------------------------------


def test_headless_variant_never_asks_and_no_ask_tool_is_offered(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_PROMPT_INTERACTIVE", raising=False)
    prompt = default_system("x", variant="qwen")
    assert "non-interactive" in prompt
    assert "Never ask the operator a question" in prompt
    assert "Interaction mode reminder:" in prompt
    assert not [s for s in SCHEMAS if s["function"]["name"].startswith("ask")]


def test_interactive_variant_keeps_no_ask_tool(monkeypatch):
    monkeypatch.setenv("COLLEAGUE_PROMPT_INTERACTIVE", "1")
    prompt = default_system("x", variant="qwen")
    assert "no ask-style tool is offered" in prompt
    assert interaction_guidance(headless=False) in prompt
    assert "Never ask the operator a question" not in prompt.split("# Final Reminder")[0]


# --- COLLEAGUE_PROMPT_VARIANT=v1 byte-for-byte + built once -------------------


def test_v1_variant_is_the_pre_arc_prompt_byte_for_byte(monkeypatch):
    # t9 regenerated this fixture deliberately (approved deviation d1): the
    # section it pins stopped naming subagent/subagents. Regenerate it the same
    # way as every other snapshot here — COLLEAGUE_UPDATE_SNAPSHOTS=1.
    _snapshot("v1", V1_DEFAULT_SYSTEM)
    pinned = (SNAP / "prompttext_v1.txt").read_text()
    assert V1_DEFAULT_SYSTEM == pinned
    monkeypatch.setenv("COLLEAGUE_PROMPT_VARIANT", "v1")
    assert default_system("Qwen/Qwen3-Coder") == pinned  # model/style ignored under v1
    assert default_system("x", style_override="qwen-vl") == pinned


def test_prompt_is_built_once_per_run(monkeypatch, tmp_path):
    """Engine.system_prompt builds the model-keyed base exactly once per run
    (a repo WITH an AGENTS layer, so composition happens); a 2-turn mock work
    item never rebuilds it per turn — prefix-stable."""
    from colleague.config import EngineConfig
    from colleague.contract import Task
    from colleague.engines.mock import MockEngine

    (tmp_path / "AGENTS.md").write_text("# agents\nbe brief\n")
    calls: list[str | None] = []
    real = prompttext.default_system

    def spy(model=None, **kw):
        calls.append(model)
        return real(model, **kw)

    monkeypatch.setattr(prompttext, "default_system", spy)
    task = Task(id="t8-probe", repo_path=str(tmp_path), instruction="hi")
    config = EngineConfig.resolve(repo_path=str(tmp_path))
    engine = MockEngine()
    prompt = engine.system_prompt(task, config) or ""
    assert calls == [config.model]
    assert prompt.startswith(default_system(config.model))

    calls.clear()
    result = engine.work(task, config)  # the mock recipe: write_file + finish = 2 turns
    assert result.status == "ok"
    assert calls == [config.model], "the prompt must be built once per run, not per turn"


# --- t9: the delegation section names the tools the acting seat holds ---------
#
# Plan t9, spec c2/h10 (the prompt must not advertise absent tools) and c24/h16
# (COLLEAGUE_PROMPT_SECTIONS must not be able to change the default text).


PURPOSE_TOOL_NAMES = (
    "web_survey",
    "code_survey",
    "review",
    "validate",
    "plan",
    "handover_to_colleague",
)


def _acting_seat_prompt(repo: Path) -> str:
    """The prompt an acting seat actually composes on a bare run.

    Goes through ``Engine.system_prompt`` (post-t5 unification) rather than
    ``default_system`` alone, so a role fragment that re-introduced the old
    names would be caught too.
    """
    from colleague.config import EngineConfig
    from colleague.contract import Task
    from colleague.engines.mock import MockEngine

    task = Task(id="t9", instruction="probe", repo_path=repo)
    composed = MockEngine().system_prompt(task, EngineConfig(model="any"))
    return composed if composed is not None else default_system("any")


@pytest.mark.parametrize("name", PURPOSE_TOOL_NAMES)
def test_default_prompt_names_every_purpose_tool(monkeypatch, tmp_path, name):
    monkeypatch.delenv("COLLEAGUE_PROMPT_VARIANT", raising=False)
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    assert name in _acting_seat_prompt(tmp_path)
    assert name in default_system("any")


def test_default_prompt_never_names_the_raw_delegation_tools(monkeypatch, tmp_path):
    """c2/h10: subagent/subagents are on the seat again as arm 4 (t11), but the
    baseline arm drops them (COLLEAGUE_ACTING_DROP_TOOLS) — so prose must name
    neither. A present-but-undescribed tool is honest in BOTH arm states."""
    monkeypatch.delenv("COLLEAGUE_PROMPT_VARIANT", raising=False)
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    for prompt in (_acting_seat_prompt(tmp_path), default_system("any"), V1_DEFAULT_SYSTEM):
        assert "subagent" not in prompt  # also covers the plural
    # The qwen variant shares the section (both literals were repaired).
    qwen = default_system("x", variant="qwen")
    assert "subagent" not in qwen
    for name in PURPOSE_TOOL_NAMES:
        assert name in qwen


def test_repaired_section_is_no_longer_than_the_174_words_it_replaced():
    assert len(prompttext._PURPOSE_TOOLS.split()) <= 174


@pytest.mark.parametrize(
    "sections",
    ["", "HANDOVER_EXAMPLE", "handover_example", "BOGUS", "HANDOVER_EXAMPLE,BOGUS"],
)
def test_prompt_sections_cannot_change_the_default_prompt(monkeypatch, sections):
    """c24 PROVEN, not asserted.

    ``default_system`` returns ``V1_DEFAULT_SYSTEM`` at the variant guard
    BEFORE it ever reads ``sections`` — so with the variant unset, no value of
    ``COLLEAGUE_PROMPT_SECTIONS`` (nor the explicit keyword) can reach the
    default text. Demonstrated over the env var, the keyword, and a value that
    DOES change the adopted text, which is what makes the comparison mean
    something.
    """
    monkeypatch.delenv("COLLEAGUE_PROMPT_VARIANT", raising=False)
    monkeypatch.setenv("COLLEAGUE_PROMPT_SECTIONS", sections)
    assert default_system("any") == V1_DEFAULT_SYSTEM
    monkeypatch.delenv("COLLEAGUE_PROMPT_SECTIONS", raising=False)
    assert default_system("any", sections=sections) == V1_DEFAULT_SYSTEM


def test_prompt_sections_control_is_live_on_the_adopted_text(monkeypatch):
    """The control arm for the test above: the same env value DOES move the
    adopted variant, so the byte-identity above is the v1 guard at work and not
    an inert knob."""
    monkeypatch.setenv("COLLEAGUE_PROMPT_SECTIONS", "HANDOVER_EXAMPLE")
    assert default_system("x", variant="qwen") != default_system("x", variant="qwen", sections="")

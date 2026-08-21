"""Tests for colleague/agents/guidance.py (plan task t12).

Covers: GUIDANCE is a frozen tuple of (purpose, when-to-prefer bullets) pairs
over the closed purpose set (the dormant ``worker`` purpose absent per
deviation d3); build_guidance_text() renders deterministically into prompt
text that names purposes only (no vendor model names); and the module exposes
no function that takes task text and returns a model/role (the runtime never
routes — the grep guard in t18 pins this across the package).
"""

import re
from pathlib import Path

import pytest

from colleague.agents.guidance import GUIDANCE, build_guidance_text
from colleague.agents.profile import PURPOSES

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "colleague" / "agents"

#: The vendor model families the reference topology must never name.
_VENDOR_PATTERN = re.compile(r"gemma|qwen|nemotron|lightning", re.IGNORECASE)


# ---------------------------------------------------------------------------
# GUIDANCE shape
# ---------------------------------------------------------------------------


def test_guidance_is_a_frozen_tuple_of_pairs():
    assert isinstance(GUIDANCE, tuple)
    for entry in GUIDANCE:
        assert isinstance(entry, tuple)
        assert len(entry) == 2
        purpose, bullets = entry
        assert isinstance(purpose, str)
        assert purpose
        assert isinstance(bullets, tuple)
        assert all(isinstance(b, str) and b for b in bullets)


def test_guidance_purposes_are_the_closed_set_minus_dormant_worker():
    purposes = [purpose for purpose, _ in GUIDANCE]
    # Deviation d3: the non-coding worker purpose stays dormant — its profile
    # exists but the role is never bound, so the guidance table omits it.
    assert set(purposes) == {"talker", "associate", "thinker_coder"}
    assert "worker" not in purposes
    assert set(purposes) <= PURPOSES
    # No purpose is listed twice.
    assert len(purposes) == len(set(purposes))


def test_guidance_table_is_immutable():
    # The table is a frozen tuple of tuples: no in-place mutation is possible.
    with pytest.raises(TypeError):
        GUIDANCE[0] = ("talker", ())  # type: ignore[index]
    with pytest.raises(TypeError):
        GUIDANCE[0][1] = ("swapped",)  # type: ignore[index]


# ---------------------------------------------------------------------------
# build_guidance_text
# ---------------------------------------------------------------------------


def test_rendered_text_is_deterministic():
    first = build_guidance_text()
    assert first == build_guidance_text()


def test_rendered_text_names_every_purpose():
    text = build_guidance_text()
    for purpose, _ in GUIDANCE:
        assert purpose in text


def test_rendered_text_names_no_vendor_model_families():
    text = build_guidance_text()
    assert not _VENDOR_PATTERN.search(
        text
    ), f"vendor model names in guidance text: {_VENDOR_PATTERN.findall(text)}"


def test_rendered_text_routes_routine_coding_to_associate_else_thinker_coder():
    text = build_guidance_text()
    # Deviation d3: routine coding goes to associate when present, else
    # thinker_coder — never to worker.
    assert "associate" in text
    assert "thinker_coder" in text
    assert "never to the dormant **worker** purpose" in text


def test_rendered_text_says_the_runtime_never_routes():
    text = build_guidance_text()
    assert "The runtime never routes" in text


def test_rendered_text_is_nonempty_prompt_fragment():
    text = build_guidance_text()
    assert isinstance(text, str)
    assert len(text) > 0
    # It is a self-contained fragment: every bullet line is indented under a
    # purpose heading, and the fragment starts with its own heading.
    assert text.startswith("## ")


# ---------------------------------------------------------------------------
# No router: no function takes task text and returns a model/role
# ---------------------------------------------------------------------------


def test_no_function_in_module_takes_task_text_and_returns_a_model_or_role():
    """The module is prompt text, never a runtime branch.

    Scans the module's public surface: no callable other than
    ``build_guidance_text`` exists, and ``build_guidance_text`` takes no
    arguments (so it cannot read task text) and returns a ``str`` (prompt
    text, not a model/role id).
    """
    import colleague.agents.guidance as guidance_module

    callables = {
        name: obj
        for name, obj in vars(guidance_module).items()
        if callable(obj) and not name.startswith("_") and name not in ("annotations",)
    }
    assert set(callables) == {"build_guidance_text"}
    import inspect

    sig = inspect.signature(build_guidance_text)
    assert len(sig.parameters) == 0, "build_guidance_text must take no task text"
    assert isinstance(build_guidance_text(), str)


def test_no_vendor_model_names_under_agents():
    """Grep guard (mirrors tests/test_agents_profile.py): no file under
    colleague/agents/ names a vendor model family."""
    offenders = []
    for path in sorted(AGENTS_DIR.rglob("*.py")):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if _VENDOR_PATTERN.search(text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"vendor model names found under colleague/agents/: {offenders}"

"""Declarative config carve-out (R5): skills + AGENTS load independent of approval policy.

Acceptance:
1. Skills resolve identically whether or not an active approval policy is present.
2. AGENTS resolve identically whether or not an active approval policy is present.
3. system_prompt_for() includes the layered content while a policy is active.
4. convertible.layers does not import convertible.policy (structural independence).
"""

from __future__ import annotations

import json
from pathlib import Path

from convertible.layers import (
    compose_agents,
    compose_skills,
    resolve_agents,
    resolve_skills,
    system_prompt_for,
)
from convertible.policy import load_policy

_BASE_PROMPT = "DEFAULT-ENGINE-SYSTEM"
_MODEL = "Qwen/Qwen3-32B"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- R5: Skills load independent of policy ----


def test_skills_load_with_empty_policy(tmp_path: Path) -> None:
    """Skills resolve identically with or without an active policy."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    # Write a skill.
    _write(repo / ".convertible" / "skills" / "my_skill.md", "# my_skill\nA test skill.")

    # No policy file at all.
    skills_no_policy = resolve_skills(repo, _MODEL, user_home=home)
    assert "my_skill" in skills_no_policy

    # Now add an active policy (non-empty run_command section).
    _write(
        repo / ".convertible" / "approvals.json",
        json.dumps({"run_command": {"allow": ["git", "pytest"]}}),
    )

    # Skills should still resolve identically.
    skills_with_policy = resolve_skills(repo, _MODEL, user_home=home)
    assert "my_skill" in skills_with_policy
    assert skills_no_policy["my_skill"].path == skills_with_policy["my_skill"].path


def test_skills_compose_with_active_policy(tmp_path: Path) -> None:
    """compose_skills() output is unaffected by an active approval policy."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write(repo / ".convertible" / "skills" / "skill_alpha.md", "# Alpha\nFirst skill.")
    _write(repo / ".convertible" / "skills" / "skill_beta.md", "# Beta\nSecond skill.")

    # Compose without policy.
    skills_no_policy = resolve_skills(repo, _MODEL, user_home=home)
    catalog_no_policy = compose_skills(skills_no_policy)
    assert "skill_alpha" in catalog_no_policy
    assert "skill_beta" in catalog_no_policy

    # Add an active policy (e.g., deny all run_command).
    _write(repo / ".convertible" / "approvals.json", json.dumps({"run_command": {"deny": ["*"]}}))

    # Composition should be identical.
    skills_with_policy = resolve_skills(repo, _MODEL, user_home=home)
    catalog_with_policy = compose_skills(skills_with_policy)
    assert catalog_no_policy == catalog_with_policy


# --- R5: AGENTS load independent of policy ----


def test_agents_load_with_active_policy(tmp_path: Path) -> None:
    """AGENTS resolve identically with or without an active policy."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write(repo / "AGENTS.md", "Base AGENTS rule.")
    _write(repo / "AGENTS.convertible.md", "Convertible overlay.")

    # No policy.
    agents_no_policy = resolve_agents(repo, _MODEL, user_home=home)
    assert len(agents_no_policy) == 2
    texts_no_policy = [layer.text for layer in agents_no_policy]
    assert "Base AGENTS rule." in texts_no_policy
    assert "Convertible overlay." in texts_no_policy

    # Add an active policy (hooks section is present).
    _write(
        repo / ".convertible" / "approvals.json",
        json.dumps({"hooks": {"lint.sh": "sha256:abc123"}}),
    )

    # AGENTS should still resolve identically.
    agents_with_policy = resolve_agents(repo, _MODEL, user_home=home)
    assert len(agents_with_policy) == 2
    texts_with_policy = [layer.text for layer in agents_with_policy]
    assert texts_no_policy == texts_with_policy


def test_agents_compose_with_active_policy(tmp_path: Path) -> None:
    """compose_agents() output is unaffected by an active approval policy."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write(repo / "AGENTS.md", "Base guidance.")
    _write(repo / "AGENTS.convertible.md", "Convertible-specific guidance.")

    # Compose without policy.
    agents_no_policy = resolve_agents(repo, _MODEL, user_home=home)
    composed_no_policy = compose_agents(agents_no_policy)
    assert "Base guidance." in composed_no_policy
    assert "Convertible-specific guidance." in composed_no_policy

    # Add an active policy (commands section present).
    _write(
        repo / ".convertible" / "approvals.json", json.dumps({"commands": {"deploy": "md5:xyz789"}})
    )

    # Composition should be unchanged.
    agents_with_policy = resolve_agents(repo, _MODEL, user_home=home)
    composed_with_policy = compose_agents(agents_with_policy)
    assert composed_no_policy == composed_with_policy


# --- R5: system_prompt_for includes layers with active policy ----


def test_system_prompt_for_with_active_policy(tmp_path: Path) -> None:
    """system_prompt_for() includes AGENTS + skills while policy is active."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    _write(repo / "AGENTS.md", "Rule: be helpful.")
    _write(repo / ".convertible" / "skills" / "code_gen.md", "# code-gen\nGenerate code.")

    # Without policy.
    prompt_no_policy = system_prompt_for(repo, _MODEL, user_home=home, base=_BASE_PROMPT)
    assert prompt_no_policy is not None
    assert "Rule: be helpful." in prompt_no_policy
    assert "code_gen" in prompt_no_policy
    assert prompt_no_policy.startswith(_BASE_PROMPT)

    # With active policy (non-empty run_command section).
    _write(
        repo / ".convertible" / "approvals.json",
        json.dumps({"run_command": {"allow": ["bash"], "deny": ["rm"]}}),
    )

    # Prompt should include layers identically.
    prompt_with_policy = system_prompt_for(repo, _MODEL, user_home=home, base=_BASE_PROMPT)
    assert prompt_with_policy is not None
    assert "Rule: be helpful." in prompt_with_policy
    assert "code_gen" in prompt_with_policy
    assert prompt_no_policy == prompt_with_policy


def test_system_prompt_for_none_when_no_layers_even_with_policy(tmp_path: Path) -> None:
    """system_prompt_for() still returns None (no layers) even with active policy."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    # Add a policy but no AGENTS or skills.
    _write(
        repo / ".convertible" / "approvals.json",
        json.dumps(
            {
                "run_command": {"allow": ["ls"]},
                "hooks": {"test.sh": "sha256:abc"},
                "commands": {"cmd": "sha256:def"},
            }
        ),
    )

    # system_prompt_for should still return None.
    prompt = system_prompt_for(repo, _MODEL, user_home=home, base=_BASE_PROMPT)
    assert prompt is None


# --- R5: Structural independence (layers does not import policy) ----


def test_layers_does_not_import_policy() -> None:
    """convertible.layers module never imports convertible.policy."""
    import convertible.layers as layers_mod

    # Inspect the module's source to ensure 'policy' is not imported.
    source = layers_mod.__file__
    assert source is not None
    source_text = Path(source).read_text(encoding="utf-8")
    assert "import policy" not in source_text
    assert "from convertible.policy" not in source_text


# --- R5: Complex multi-layer policy does not affect resolution ----


def test_complex_policy_does_not_affect_multi_layer_resolution(tmp_path: Path) -> None:
    """A complex multi-section policy is fully ignored by AGENTS + skills resolution."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    # Set up multiple layers.
    _write(repo / "AGENTS.md", "Base AGENTS.")
    _write(repo / "AGENTS.convertible.md", "Convertible AGENTS.")
    _write(repo / ".convertible" / "skills" / "skill_1.md", "# Skill 1\nText 1.")
    _write(repo / ".convertible" / "skills" / "skill_2.md", "# Skill 2\nText 2.")

    # Capture resolution before policy.
    agents_before = resolve_agents(repo, _MODEL, user_home=home)
    skills_before = resolve_skills(repo, _MODEL, user_home=home)
    prompt_before = system_prompt_for(repo, _MODEL, user_home=home, base=_BASE_PROMPT)

    # Add a comprehensive active policy.
    _write(
        repo / ".convertible" / "approvals.json",
        json.dumps(
            {
                "run_command": {
                    "allow": ["git", "pytest", "uv"],
                    "deny": ["rm", "dd"],
                },
                "hooks": {
                    "lint.sh": "sha256:deadbeef",
                    "format.sh": "sha256:cafebabe",
                },
                "commands": {
                    "fix-style": "sha256:feedfeed",
                    "test-all": "sha256:badcadba",
                },
            }
        ),
    )

    # Verify policy is indeed active and non-empty.
    policy = load_policy(repo, model=_MODEL, user_home=home)
    assert not policy.is_empty()

    # Resolution should be identical.
    agents_after = resolve_agents(repo, _MODEL, user_home=home)
    skills_after = resolve_skills(repo, _MODEL, user_home=home)
    prompt_after = system_prompt_for(repo, _MODEL, user_home=home, base=_BASE_PROMPT)

    assert len(agents_before) == len(agents_after)
    assert len(skills_before) == len(skills_after)
    assert prompt_before == prompt_after
    for before, after in zip(agents_before, agents_after):
        assert before.path == after.path
        assert before.text == after.text


# --- R5: Per-model policy overlay does not affect per-model layer resolution ----


def test_per_model_policy_overlay_does_not_affect_layer_resolution(tmp_path: Path) -> None:
    """Per-model approvals.json overlay does not interfere with per-model AGENTS/skills."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)

    # Per-model AGENTS and skills.
    _write(repo / "AGENTS.convertible.Qwen-Qwen3-32B.md", "Qwen-specific AGENTS.")
    _write(
        repo / ".convertible" / "Qwen-Qwen3-32B" / "skills" / "qwen_skill.md",
        "# Qwen Skill\nQwen-specific.",
    )

    # Per-model policy overlay.
    _write(
        repo / ".convertible" / "Qwen-Qwen3-32B" / "approvals.json",
        json.dumps({"run_command": {"allow": ["python"]}}),
    )

    # Verify the per-model policy loads.
    policy = load_policy(repo, model=_MODEL, user_home=home)
    assert not policy.is_empty()

    # Resolve layers with the per-model policy active.
    agents = resolve_agents(repo, _MODEL, user_home=home)
    skills = resolve_skills(repo, _MODEL, user_home=home)

    assert any("Qwen-specific AGENTS" in layer.text for layer in agents)
    assert "qwen_skill" in skills

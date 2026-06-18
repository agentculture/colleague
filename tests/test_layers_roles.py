"""Tests for colleague/layers — role-aware prompt composition.

Acceptance:
1. compose_role_prompt composes base + role prompt_fragment + filtered skills
   in a fixed documented order, reusing the existing prompt-assembly path.
2. skill_subset=None yields ALL skills (byte-identical to today).
3. Per-model role-prompt overlay at .colleague/<model>/agents/<name>.md composes
   ahead of the base by exact path (uses sanitize_model), no sibling globbing.
4. No second prompt-assembly code path — the existing composer is extended.
"""

from __future__ import annotations

from pathlib import Path

from colleague import layers
from colleague.roles import Role, load_role

_BASE_PROMPT = "BASE-DEFAULT"
_MODEL_X = "Qwen/Qwen3-32B"
_SAFE_X = "Qwen-Qwen3-32B"


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


# --- compose_role_prompt: basic composition ---------------------------------


class TestComposeRolePromptBasic:
    """AC1: base + role prompt_fragment + filtered skills, fixed order."""

    def test_composes_base_and_role_fragment(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        role = Role(
            name="test_role",
            prompt_fragment="You are a test role.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert _BASE_PROMPT in prompt
        assert "You are a test role." in prompt
        # Base comes before role fragment
        assert prompt.index(_BASE_PROMPT) < prompt.index("You are a test role.")

    def test_composes_base_role_and_agents(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _write(repo / "AGENTS.md", "agent rules")
        role = Role(
            name="test_role",
            prompt_fragment="Role fragment.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        # Order: base, agents, role fragment
        assert prompt.index(_BASE_PROMPT) < prompt.index("agent rules")
        assert prompt.index("agent rules") < prompt.index("Role fragment.")

    def test_composes_base_role_agents_and_skills(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _write(repo / "AGENTS.md", "agent rules")
        _write(repo / ".colleague" / "skills" / "greet.md", "# greet\nSay hi.")
        role = Role(
            name="test_role",
            prompt_fragment="Role fragment.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        # Full order: base, agents, role fragment, skills catalog
        assert prompt.index(_BASE_PROMPT) < prompt.index("agent rules")
        assert prompt.index("agent rules") < prompt.index("Role fragment.")
        assert prompt.index("Role fragment.") < prompt.index("greet")
        assert "Say hi." in prompt

    def test_fixed_documented_order(self, tmp_path: Path) -> None:
        """Verify the exact composition order: base -> AGENTS -> role fragment -> skills."""
        repo = _repo(tmp_path)
        _write(repo / "AGENTS.md", "AGENTS-LAYER")
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        _write(repo / ".colleague" / "skills" / "beta.md", "# beta\nBeta skill.")
        role = Role(
            name="test_role",
            prompt_fragment="ROLE-FRAGMENT",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        # Verify ordering by index
        idx_base = prompt.index(_BASE_PROMPT)
        idx_agents = prompt.index("AGENTS-LAYER")
        idx_role = prompt.index("ROLE-FRAGMENT")
        idx_skills = prompt.index("Available skills")
        assert idx_base < idx_agents < idx_role < idx_skills


# --- skill_subset filtering ------------------------------------------------


class TestSkillSubsetFiltering:
    """AC2: skill_subset filters skills; None yields all (byte-identical)."""

    def test_skill_subset_filters_to_named_skills(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        _write(repo / ".colleague" / "skills" / "beta.md", "# beta\nBeta skill.")
        _write(repo / ".colleague" / "skills" / "gamma.md", "# gamma\nGamma skill.")
        role = Role(
            name="filtered_role",
            prompt_fragment="Filtered role.",
            tool_allowlist=("read_file",),
            skill_subset=("alpha", "gamma"),
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "alpha" in prompt
        assert "gamma" in prompt
        assert "beta" not in prompt

    def test_skill_subset_none_yields_all_skills(self, tmp_path: Path) -> None:
        """skill_subset=None must include all resolved skills."""
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        _write(repo / ".colleague" / "skills" / "beta.md", "# beta\nBeta skill.")
        role = Role(
            name="all_skills_role",
            prompt_fragment="All skills role.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "alpha" in prompt
        assert "beta" in prompt

    def test_skill_subset_none_is_byte_identical_to_system_prompt_for(self, tmp_path: Path) -> None:
        """When role has no prompt_fragment and skill_subset=None, output should
        match system_prompt_for (no role layer added)."""
        repo = _repo(tmp_path)
        _write(repo / "AGENTS.md", "agent rules")
        _write(repo / ".colleague" / "skills" / "greet.md", "# greet\nSay hi.")
        role = Role(
            name="empty_role",
            prompt_fragment="",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt_with_role = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        prompt_without_role = layers.system_prompt_for(repo, _MODEL_X, base=_BASE_PROMPT)
        # Both should be non-None and identical (empty fragment adds nothing)
        assert prompt_with_role == prompt_without_role

    def test_skill_subset_empty_tuple_yields_no_skills(self, tmp_path: Path) -> None:
        """An empty skill_subset tuple yields no skills catalog."""
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        role = Role(
            name="no_skills_role",
            prompt_fragment="No skills role.",
            tool_allowlist=("read_file",),
            skill_subset=(),
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "No skills role." in prompt
        assert "Available skills" not in prompt

    def test_skill_subset_filters_model_overlay_skills(self, tmp_path: Path) -> None:
        """skill_subset filters across base and model overlay skills."""
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "base_skill.md", "# base\nBase skill.")
        safe = layers.sanitize_model(_MODEL_X)
        _write(
            repo / ".colleague" / safe / "skills" / "model_skill.md",
            "# model\nModel skill.",
        )
        role = Role(
            name="overlay_role",
            prompt_fragment="Overlay role.",
            tool_allowlist=("read_file",),
            skill_subset=("model_skill",),
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "model_skill" in prompt
        assert "base_skill" not in prompt


# --- per-model role-prompt overlay ------------------------------------------


class TestPerModelRoleOverlay:
    """AC3: per-model overlay at .colleague/<model>/agents/<name>.md."""

    def test_role_overlay_composes_ahead_of_base(self, tmp_path: Path) -> None:
        """A per-model role overlay file is loaded by load_role and its content
        appears in the composed prompt via the role's prompt_fragment."""
        repo = _repo(tmp_path)
        safe = layers.sanitize_model(_MODEL_X)
        overlay_dir = repo / ".colleague" / safe / "agents"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "explorer.md").write_text("Model-specific explorer prompt.")

        role = load_role("explorer", repo, _MODEL_X)
        assert role is not None
        assert role.prompt_fragment == "Model-specific explorer prompt."

        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "Model-specific explorer prompt." in prompt

    def test_role_overlay_uses_sanitized_model_path(self, tmp_path: Path) -> None:
        """Overlay path uses sanitize_model, not raw model string."""
        repo = _repo(tmp_path)
        safe = layers.sanitize_model(_MODEL_X)
        overlay_dir = repo / ".colleague" / safe / "agents"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "planner.md").write_text("Sanitized overlay prompt.")

        role = load_role("planner", repo, _MODEL_X)
        assert role is not None
        assert role.prompt_fragment == "Sanitized overlay prompt."

        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "Sanitized overlay prompt." in prompt

    def test_no_sibling_globbing_for_role_overlay(self, tmp_path: Path) -> None:
        """A file in a sibling model dir must NOT be picked up for role overlay."""
        repo = _repo(tmp_path)
        # Put overlay in a different model's dir
        sibling_dir = repo / ".colleague" / "other-model" / "agents"
        sibling_dir.mkdir(parents=True)
        (sibling_dir / "explorer.md").write_text("sibling overlay prompt")

        role = load_role("explorer", repo, _MODEL_X)
        assert role is not None
        # Should fall back to built-in, not sibling
        assert role.prompt_fragment != "sibling overlay prompt"

    def test_base_role_file_fallback(self, tmp_path: Path) -> None:
        """When no model overlay exists, base .colleague/agents/<name>.md is used."""
        repo = _repo(tmp_path)
        base_dir = repo / ".colleague" / "agents"
        base_dir.mkdir(parents=True)
        (base_dir / "reviewer.md").write_text("Base reviewer prompt.")

        role = load_role("reviewer", repo, _MODEL_X)
        assert role is not None
        assert role.prompt_fragment == "Base reviewer prompt."

        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "Base reviewer prompt." in prompt


# --- reuse of existing path (no second assembly) -----------------------------


class TestReuseExistingPath:
    """Verify compose_role_prompt reuses the existing prompt-assembly path."""

    def test_reuses_compose_skills(self, tmp_path: Path) -> None:
        """compose_role_prompt must use compose_skills for the skills catalog."""
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "greet.md", "# greet\nSay hi.")
        role = Role(
            name="reuse_test",
            prompt_fragment="Reuse test.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        # compose_skills produces "Available skills..." header
        assert "Available skills" in prompt
        # And the summary line from the skill doc
        assert "Say hi." in prompt

    def test_reuses_sanitize_model(self, tmp_path: Path) -> None:
        """Per-model resolution uses sanitize_model (same as existing path)."""
        repo = _repo(tmp_path)
        safe = layers.sanitize_model(_MODEL_X)
        # Model-specific AGENTS overlay
        _write(repo / f"AGENTS.colleague.{safe}.md", "model agents overlay")
        role = Role(
            name="sanitize_test",
            prompt_fragment="Sanitize test.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "model agents overlay" in prompt

    def test_returns_none_when_nothing_to_add(self, tmp_path: Path) -> None:
        """When there's no AGENTS, no skills, and empty role fragment, return None."""
        repo = _repo(tmp_path)
        role = Role(
            name="empty",
            prompt_fragment="",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        # No AGENTS, no skills, empty fragment → None (like system_prompt_for)
        assert prompt is None

    def test_returns_prompt_when_only_role_fragment(self, tmp_path: Path) -> None:
        """A non-empty role fragment alone should produce a prompt."""
        repo = _repo(tmp_path)
        role = Role(
            name="fragment_only",
            prompt_fragment="Just a fragment.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "Just a fragment." in prompt
        assert _BASE_PROMPT in prompt


# --- integration with load_role ---------------------------------------------


class TestIntegrationWithLoadRole:
    """End-to-end: load_role + compose_role_prompt."""

    def test_load_and_compose_explorer(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        _write(repo / ".colleague" / "skills" / "beta.md", "# beta\nBeta skill.")

        role = load_role("explorer", repo, _MODEL_X)
        assert role is not None
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert role.prompt_fragment in prompt
        # explorer has skill_subset=None → all skills
        assert "alpha" in prompt
        assert "beta" in prompt

    def test_load_and_compose_with_custom_skill_subset(self, tmp_path: Path) -> None:
        """A custom role with skill_subset filters skills correctly."""
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        _write(repo / ".colleague" / "skills" / "beta.md", "# beta\nBeta skill.")

        role = Role(
            name="custom",
            prompt_fragment="Custom role.",
            tool_allowlist=("read_file",),
            skill_subset=("alpha",),
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        assert "alpha" in prompt
        assert "beta" not in prompt

    def test_compose_role_prompt_with_role_name(self, tmp_path: Path) -> None:
        """compose_role_prompt accepts a role name string and loads it."""
        repo = _repo(tmp_path)
        _write(repo / ".colleague" / "skills" / "greet.md", "# greet\nSay hi.")

        prompt = layers.compose_role_prompt("explorer", repo, _MODEL_X, base=_BASE_PROMPT)
        assert prompt is not None
        # Explorer's built-in prompt fragment
        assert "explorer" in prompt.lower() or "You are an explorer" in prompt
        assert "greet" in prompt

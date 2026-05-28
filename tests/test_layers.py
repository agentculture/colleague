"""Layered, per-model config loader (AGENTS instructions + skills).

Acceptance:
1. Per-model isolation: resolving for model X never reads model Y's overlay.
2. AGENTS cascade resolves general -> specific; compose concatenates in order.
3. Skills union: model overlay shadows base by stem.
4. Repo-level shadows user-level for both families.
5. Absent files never raise; system_prompt_for returns None when nothing to add.
"""

from __future__ import annotations

from pathlib import Path

from convertible.layers import (
    AGENTS_BASE,
    AGENTS_CONVERTIBLE,
    AGENTS_MODEL,
    SKILL_BASE,
    SKILL_MODEL,
    compose_agents,
    resolve_agents,
    resolve_skills,
    sanitize_model,
    system_prompt_for,
)

_BASE_PROMPT = "BASE-DEFAULT"
_MODEL_X = "Qwen/Qwen3-32B"
_SAFE_X = "Qwen-Qwen3-32B"
_MODEL_Y = "meta/Llama-3.1-8B"
_SAFE_Y = "meta-Llama-3.1-8B"


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


# --- sanitize_model ---------------------------------------------------------


def test_sanitize_model_slash_to_dash() -> None:
    assert sanitize_model("Qwen/Qwen3-32B") == "Qwen-Qwen3-32B"


def test_sanitize_model_preserves_dots() -> None:
    assert sanitize_model("mmangkad/Qwen3.6-27B-NVFP4") == "mmangkad-Qwen3.6-27B-NVFP4"


def test_sanitize_model_empty_is_default() -> None:
    assert sanitize_model("") == "default"
    assert sanitize_model("   ") == "default"
    assert sanitize_model("///") == "default"


def test_sanitize_model_strips_edges_and_collapses_runs() -> None:
    assert sanitize_model("  a // b :: c  ") == "a-b-c"


# --- per-model isolation (the headline invariant) ---------------------------


def test_agents_isolation_x_does_not_see_y(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / f"AGENTS.convertible.{_SAFE_X}.md", "X overlay")
    _write(repo / f"AGENTS.convertible.{_SAFE_Y}.md", "Y overlay")

    layers_x = resolve_agents(repo, _MODEL_X, user_home=home)
    paths_x = {layer.path.name for layer in layers_x}
    assert f"AGENTS.convertible.{_SAFE_X}.md" in paths_x
    assert f"AGENTS.convertible.{_SAFE_Y}.md" not in paths_x

    layers_y = resolve_agents(repo, _MODEL_Y, user_home=home)
    paths_y = {layer.path.name for layer in layers_y}
    assert f"AGENTS.convertible.{_SAFE_Y}.md" in paths_y
    assert f"AGENTS.convertible.{_SAFE_X}.md" not in paths_y


def test_skills_isolation_x_does_not_see_y(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / ".convertible" / _SAFE_X / "skills" / "only_x.md", "# x")
    _write(repo / ".convertible" / _SAFE_Y / "skills" / "only_y.md", "# y")

    skills_x = resolve_skills(repo, _MODEL_X, user_home=home)
    assert "only_x" in skills_x
    assert "only_y" not in skills_x

    skills_y = resolve_skills(repo, _MODEL_Y, user_home=home)
    assert "only_y" in skills_y
    assert "only_x" not in skills_y


# --- AGENTS cascade ---------------------------------------------------------


def test_agents_full_cascade_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "AGENTS.md", "base text")
    _write(repo / "AGENTS.convertible.md", "convertible text")
    _write(repo / f"AGENTS.convertible.{_SAFE_X}.md", "model text")

    layers = resolve_agents(repo, _MODEL_X, user_home=_home(tmp_path))
    assert [layer.scope for layer in layers] == [
        AGENTS_BASE,
        AGENTS_CONVERTIBLE,
        AGENTS_MODEL,
    ]
    assert compose_agents(layers) == "base text\n\nconvertible text\n\nmodel text"


def test_agents_gaps_allowed(tmp_path: Path) -> None:
    """Missing convertible overlay → base then model, in order."""
    repo = _repo(tmp_path)
    _write(repo / "AGENTS.md", "base text")
    _write(repo / f"AGENTS.convertible.{_SAFE_X}.md", "model text")

    layers = resolve_agents(repo, _MODEL_X, user_home=_home(tmp_path))
    assert [layer.scope for layer in layers] == [AGENTS_BASE, AGENTS_MODEL]
    assert compose_agents(layers) == "base text\n\nmodel text"


def test_compose_agents_drops_empty_layers(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "AGENTS.md", "   \n  ")  # whitespace only
    _write(repo / "AGENTS.convertible.md", "real")
    layers = resolve_agents(repo, _MODEL_X, user_home=_home(tmp_path))
    assert compose_agents(layers) == "real"


# --- skills union / shadow --------------------------------------------------


def test_skills_model_overlay_shadows_base(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / ".convertible" / "skills" / "shared.md", "# base shared")
    _write(repo / ".convertible" / "skills" / "base_only.md", "# base only")
    _write(repo / ".convertible" / _SAFE_X / "skills" / "shared.md", "# model shared")
    _write(repo / ".convertible" / _SAFE_X / "skills" / "model_only.md", "# model only")

    skills = resolve_skills(repo, _MODEL_X, user_home=home)
    assert set(skills) == {"shared", "base_only", "model_only"}
    assert skills["shared"].scope == SKILL_MODEL
    assert skills["base_only"].scope == SKILL_BASE
    assert skills["model_only"].scope == SKILL_MODEL


# --- repo-shadows-user ------------------------------------------------------


def test_agents_repo_shadows_user(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / "AGENTS.md", "repo base")
    _write(home / ".convertible" / "AGENTS.md", "user base")

    layers = resolve_agents(repo, _MODEL_X, user_home=home)
    assert len(layers) == 1
    assert layers[0].text == "repo base"


def test_agents_user_fallback_when_repo_absent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(home / ".convertible" / "AGENTS.md", "user base")

    layers = resolve_agents(repo, _MODEL_X, user_home=home)
    assert len(layers) == 1
    assert layers[0].text == "user base"


def test_skills_repo_shadows_user(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / ".convertible" / "skills" / "s.md", "# repo")
    _write(home / ".convertible" / "skills" / "s.md", "# user")

    skills = resolve_skills(repo, _MODEL_X, user_home=home)
    assert skills["s"].path.read_text() == "# repo"


# --- absent files never raise ----------------------------------------------


def test_empty_repo_resolves_to_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    assert resolve_agents(repo, _MODEL_X, user_home=home) == []
    assert resolve_skills(repo, _MODEL_X, user_home=home) == {}


# --- symlink confinement (security: layer reads stay in repo/config roots) --


def test_agents_symlink_escape_is_ignored(tmp_path: Path) -> None:
    """A repo AGENTS.md symlinked outside the repo is not read into the prompt."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    secret = tmp_path / "secret.md"  # outside the repo root
    secret.write_text("TOP SECRET", encoding="utf-8")
    (repo / "AGENTS.md").symlink_to(secret)

    assert resolve_agents(repo, _MODEL_X, user_home=home) == []
    assert system_prompt_for(repo, _MODEL_X, user_home=home, base=_BASE_PROMPT) is None


def test_agents_symlink_within_repo_is_allowed(tmp_path: Path) -> None:
    """A symlink that stays inside the repo is followed (matches tool reads)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    target = repo / "docs.md"
    target.write_text("in-repo rules", encoding="utf-8")
    (repo / "AGENTS.md").symlink_to(target)

    layers = resolve_agents(repo, _MODEL_X, user_home=home)
    assert [layer.text for layer in layers] == ["in-repo rules"]


def test_skills_symlink_escape_is_ignored(tmp_path: Path) -> None:
    """A skill doc symlinked outside the .convertible roots is skipped."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    secret = tmp_path / "secret.md"  # outside any .convertible root
    secret.write_text("# secret\nleak", encoding="utf-8")
    skills_dir = repo / ".convertible" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "evil.md").symlink_to(secret)

    assert resolve_skills(repo, _MODEL_X, user_home=home) == {}


def test_skills_symlink_within_config_is_allowed(tmp_path: Path) -> None:
    """A skill symlink that stays inside .convertible is followed."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    conv = repo / ".convertible"
    target = conv / "shared" / "real.md"
    _write(target, "# real\nuse me")
    skills_dir = conv / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "link.md").symlink_to(target)

    skills = resolve_skills(repo, _MODEL_X, user_home=home)
    assert "link" in skills


# --- system_prompt_for composition ------------------------------------------


def test_system_prompt_for_none_when_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    assert system_prompt_for(repo, _MODEL_X, user_home=home, base=_BASE_PROMPT) is None


def test_system_prompt_for_composes_base_agents_skills(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / "AGENTS.md", "agent rules")
    _write(repo / ".convertible" / "skills" / "greet.md", "# greet\nSay hi.")

    prompt = system_prompt_for(repo, _MODEL_X, user_home=home, base=_BASE_PROMPT)
    assert prompt is not None
    # Order: base, then AGENTS, then skills catalog.
    assert prompt.startswith(_BASE_PROMPT)
    assert "agent rules" in prompt
    assert prompt.index(_BASE_PROMPT) < prompt.index("agent rules")
    assert "greet" in prompt
    assert prompt.index("agent rules") < prompt.index("greet")
    # Skill summary comes from the first non-empty content line, not the heading.
    assert "Say hi." in prompt


def test_system_prompt_for_agents_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write(repo / "AGENTS.md", "agent rules")
    prompt = system_prompt_for(repo, _MODEL_X, user_home=home, base=_BASE_PROMPT)
    assert prompt == f"{_BASE_PROMPT}\n\nagent rules"

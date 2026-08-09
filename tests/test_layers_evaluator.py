"""Tests for the bounded task-local evaluator prompt section (plan t5).

Covers docs/plans/2026-08-05-three-tier-execution.md task t5:

    Compose through layers.py's existing path (system_prompt_for /
    compose_role_prompt) — injected once on Engine.system_prompt(), exact-path
    isolation preserved. The section is named, bounded, and absent renders
    nothing.

Acceptance (verbatim from the plan):
    baseline vs cortex-configured composed prompt differs in exactly ONE named
    task-local evaluator section; base prompt, AGENTS layers, role prompts,
    skills, and operator text pinned unchanged by test.

This is a pure composition capability added to layers.py. It does NOT decide
who calls it (no wiring into Engine.system_prompt() here) — that is a later
task's job; these tests exercise system_prompt_for/compose_role_prompt
directly with the new optional evaluator_section/evaluator_seat kwargs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.layers import (
    EVALUATOR_SEAT_SENSES,
    EVALUATOR_SEAT_WORKER,
    EVALUATOR_SECTION_HEADING,
    EVALUATOR_SECTION_MAX_CHARS,
    EvaluatorSectionTooLarge,
    compose_evaluator_section,
    compose_role_prompt,
    system_prompt_for,
)
from colleague.roles import Role

_BASE_PROMPT = "BASE-DEFAULT"
_MODEL_X = "Qwen/Qwen3-32B"


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


# --- compose_evaluator_section: the pure primitive --------------------------


class TestComposeEvaluatorSectionPrimitive:
    def test_none_text_renders_nothing(self) -> None:
        assert compose_evaluator_section(None, EVALUATOR_SEAT_WORKER) is None

    def test_empty_text_renders_nothing(self) -> None:
        assert compose_evaluator_section("", EVALUATOR_SEAT_WORKER) is None

    def test_whitespace_only_text_renders_nothing(self) -> None:
        assert compose_evaluator_section("   \n  ", EVALUATOR_SEAT_SENSES) is None

    def test_valid_text_worker_seat_renders_named_section(self) -> None:
        section = compose_evaluator_section("Focus on the auth module.", EVALUATOR_SEAT_WORKER)
        assert section is not None
        assert section.startswith(EVALUATOR_SECTION_HEADING)
        assert "Focus on the auth module." in section

    def test_valid_text_senses_seat_renders_named_section(self) -> None:
        section = compose_evaluator_section("Relay tersely.", EVALUATOR_SEAT_SENSES)
        assert section is not None
        assert section.startswith(EVALUATOR_SECTION_HEADING)
        assert "Relay tersely." in section

    def test_heading_is_the_documented_example(self) -> None:
        # Design notes pin this exact heading text.
        assert EVALUATOR_SECTION_HEADING == "## Evaluator (task-local)"

    def test_text_is_stripped(self) -> None:
        section = compose_evaluator_section("  padded text  \n", EVALUATOR_SEAT_WORKER)
        assert section == f"{EVALUATOR_SECTION_HEADING}\n\npadded text"

    def test_unknown_seat_raises(self) -> None:
        with pytest.raises(ValueError):
            compose_evaluator_section("text", "cortex")

    def test_unknown_seat_raises_even_with_empty_text(self) -> None:
        # Seat validation is unconditional — a bad seat is always a caller bug,
        # regardless of whether there happens to be text to render this time.
        with pytest.raises(ValueError):
            compose_evaluator_section(None, "not-a-seat")

    def test_at_cap_boundary_succeeds(self) -> None:
        text = "x" * EVALUATOR_SECTION_MAX_CHARS
        section = compose_evaluator_section(text, EVALUATOR_SEAT_WORKER)
        assert section is not None
        assert text in section

    def test_over_cap_raises_too_large_never_truncates(self) -> None:
        text = "x" * (EVALUATOR_SECTION_MAX_CHARS + 1)
        with pytest.raises(EvaluatorSectionTooLarge):
            compose_evaluator_section(text, EVALUATOR_SEAT_WORKER)

    def test_too_large_is_a_value_error_subclass(self) -> None:
        # A caller that only catches ValueError still catches this.
        assert issubclass(EvaluatorSectionTooLarge, ValueError)


# --- system_prompt_for: evaluator section threading -------------------------


class TestSystemPromptForEvaluator:
    def test_default_unused_is_byte_identical_to_today(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        _write(repo / "AGENTS.md", "agent rules")
        without_kwarg = system_prompt_for(repo, _MODEL_X, user_home=home, base=_BASE_PROMPT)
        with_none = system_prompt_for(
            repo, _MODEL_X, user_home=home, base=_BASE_PROMPT, evaluator_section=None
        )
        assert without_kwarg == with_none

    def test_none_repo_stays_none_when_evaluator_absent(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        assert (
            system_prompt_for(
                repo, _MODEL_X, user_home=home, base=_BASE_PROMPT, evaluator_section=""
            )
            is None
        )

    def test_evaluator_alone_produces_a_prompt(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        prompt = system_prompt_for(
            repo,
            _MODEL_X,
            user_home=home,
            base=_BASE_PROMPT,
            evaluator_section="Prioritize tests.",
        )
        assert prompt is not None
        assert prompt == f"{_BASE_PROMPT}\n\n{EVALUATOR_SECTION_HEADING}\n\nPrioritize tests."

    def test_order_base_agents_evaluator_skills(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        _write(repo / "AGENTS.md", "AGENTS-LAYER")
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        prompt = system_prompt_for(
            repo,
            _MODEL_X,
            user_home=home,
            base=_BASE_PROMPT,
            evaluator_section="EVALUATOR-TEXT",
        )
        assert prompt is not None
        idx_base = prompt.index(_BASE_PROMPT)
        idx_agents = prompt.index("AGENTS-LAYER")
        idx_evaluator = prompt.index("EVALUATOR-TEXT")
        idx_skills = prompt.index("Available skills")
        assert idx_base < idx_agents < idx_evaluator < idx_skills

    def test_baseline_vs_configured_prefix_and_suffix_pinned(self, tmp_path: Path) -> None:
        """The headline t5 acceptance criterion: baseline vs cortex-configured
        composed prompt differs in EXACTLY one named task-local evaluator
        section; everything else (base/AGENTS/skills) is byte-identical."""
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        _write(repo / "AGENTS.md", "AGENTS-LAYER")
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")

        baseline = system_prompt_for(repo, _MODEL_X, user_home=home, base=_BASE_PROMPT)
        configured = system_prompt_for(
            repo,
            _MODEL_X,
            user_home=home,
            base=_BASE_PROMPT,
            evaluator_section="CORTEX-AUTHORED-NOTE",
            evaluator_seat=EVALUATOR_SEAT_WORKER,
        )
        assert baseline is not None
        assert configured is not None
        assert baseline != configured

        prefix = f"{_BASE_PROMPT}\n\nAGENTS-LAYER\n\n"
        evaluator_block = f"{EVALUATOR_SECTION_HEADING}\n\nCORTEX-AUTHORED-NOTE"
        skills_text = baseline[len(prefix) :]  # everything after the pinned prefix in baseline

        # Prefix (base + AGENTS layers) is pinned unchanged.
        assert baseline.startswith(prefix)
        assert configured.startswith(prefix)

        # Suffix (skills catalog) is pinned unchanged — byte-identical tail.
        assert baseline.endswith(skills_text)
        assert configured.endswith(skills_text)

        # The only difference is the one named evaluator section, inserted
        # between the pinned prefix and the pinned suffix.
        assert baseline == prefix + skills_text
        assert configured == prefix + evaluator_block + "\n\n" + skills_text

    def test_oversize_evaluator_section_propagates(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        with pytest.raises(EvaluatorSectionTooLarge):
            system_prompt_for(
                repo,
                _MODEL_X,
                user_home=home,
                base=_BASE_PROMPT,
                evaluator_section="x" * (EVALUATOR_SECTION_MAX_CHARS + 1),
            )

    def test_invalid_seat_propagates(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        home = _home(tmp_path)
        with pytest.raises(ValueError):
            system_prompt_for(
                repo,
                _MODEL_X,
                user_home=home,
                base=_BASE_PROMPT,
                evaluator_section="text",
                evaluator_seat="cortex",
            )


# --- compose_role_prompt: evaluator section threading -----------------------


class TestComposeRolePromptEvaluator:
    def _role(self, prompt_fragment: str = "ROLE-FRAGMENT") -> Role:
        return Role(
            name="test_role",
            prompt_fragment=prompt_fragment,
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )

    def test_default_unused_is_byte_identical_to_today(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        role = self._role()
        without_kwarg = compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        with_none = compose_role_prompt(
            role, repo, _MODEL_X, base=_BASE_PROMPT, evaluator_section=None
        )
        assert without_kwarg == with_none

    def test_order_base_agents_role_evaluator_skills(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        _write(repo / "AGENTS.md", "AGENTS-LAYER")
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        role = self._role()
        prompt = compose_role_prompt(
            role, repo, _MODEL_X, base=_BASE_PROMPT, evaluator_section="EVALUATOR-TEXT"
        )
        assert prompt is not None
        idx_base = prompt.index(_BASE_PROMPT)
        idx_agents = prompt.index("AGENTS-LAYER")
        idx_role = prompt.index("ROLE-FRAGMENT")
        idx_evaluator = prompt.index("EVALUATOR-TEXT")
        idx_skills = prompt.index("Available skills")
        assert idx_base < idx_agents < idx_role < idx_evaluator < idx_skills

    def test_baseline_vs_configured_prefix_and_suffix_pinned(self, tmp_path: Path) -> None:
        """Same acceptance criterion, via the role-aware composer: base prompt,
        AGENTS layers, role prompt, and skills are pinned; only the one named
        evaluator section differs."""
        repo = _repo(tmp_path)
        _write(repo / "AGENTS.md", "AGENTS-LAYER")
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        role = self._role()

        baseline = compose_role_prompt(role, repo, _MODEL_X, base=_BASE_PROMPT)
        configured = compose_role_prompt(
            role,
            repo,
            _MODEL_X,
            base=_BASE_PROMPT,
            evaluator_section="CORTEX-AUTHORED-NOTE",
            evaluator_seat=EVALUATOR_SEAT_SENSES,
        )
        assert baseline is not None
        assert configured is not None
        assert baseline != configured

        prefix = f"{_BASE_PROMPT}\n\nAGENTS-LAYER\n\nROLE-FRAGMENT\n\n"
        evaluator_block = f"{EVALUATOR_SECTION_HEADING}\n\nCORTEX-AUTHORED-NOTE"
        skills_text = baseline[len(prefix) :]

        assert baseline.startswith(prefix)
        assert configured.startswith(prefix)
        assert baseline.endswith(skills_text)
        assert configured.endswith(skills_text)

        assert baseline == prefix + skills_text
        assert configured == prefix + evaluator_block + "\n\n" + skills_text

    def test_role_name_string_path_also_threads_evaluator(self, tmp_path: Path) -> None:
        """compose_role_prompt(role_name_str, ...) — the unknown-role fallback
        path — also threads the evaluator kwargs through to system_prompt_for."""
        repo = _repo(tmp_path)
        prompt = compose_role_prompt(
            "no-such-role",
            repo,
            _MODEL_X,
            base=_BASE_PROMPT,
            evaluator_section="EVALUATOR-TEXT",
        )
        assert prompt is not None
        assert "EVALUATOR-TEXT" in prompt
        assert EVALUATOR_SECTION_HEADING in prompt

    def test_oversize_evaluator_section_propagates(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        role = self._role()
        with pytest.raises(EvaluatorSectionTooLarge):
            compose_role_prompt(
                role,
                repo,
                _MODEL_X,
                base=_BASE_PROMPT,
                evaluator_section="x" * (EVALUATOR_SECTION_MAX_CHARS + 1),
            )

    def test_invalid_seat_propagates(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        role = self._role()
        with pytest.raises(ValueError):
            compose_role_prompt(
                role,
                repo,
                _MODEL_X,
                base=_BASE_PROMPT,
                evaluator_section="text",
                evaluator_seat="cortex",
            )


# --- module surface sanity ---------------------------------------------------


def test_seat_constants_match_lattice_seat_names() -> None:
    # layers.py stays decoupled from colleague.lattice (no import), but the
    # seat vocabulary is deliberately the same two strings the t4 lattice's
    # WORKER_PROMPT_EVALUATOR / SENSES_PROMPT_EVALUATOR targets name.
    assert EVALUATOR_SEAT_WORKER == "worker"
    assert EVALUATOR_SEAT_SENSES == "senses"


def test_layers_module_does_not_import_lattice() -> None:
    import colleague.layers as layers_mod

    assert "colleague.lattice" not in layers_mod.__dict__

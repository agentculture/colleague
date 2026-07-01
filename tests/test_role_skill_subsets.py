"""Curated built-in role skill subsets (t10).

Today every built-in role sets ``skill_subset=None`` (full skill catalog).
This module pins the t10 acceptance criteria from
``docs/plans/2026-07-01-colleague-s-work-modes-explore-plan-review-work-no.md``
(covers c13) and spec R4:

(a) explorer/planner/reviewer/validator carry a non-``None`` curated
    ``skill_subset``; ``writer`` keeps ``None`` (today's full-catalog
    behavior, unchanged).
(b) a composed role prompt over a tmp-repo fixture whose skills are named
    like this repo's real release/side-effect skills (``cicd``,
    ``version-bump``) plus an investigation-shaped skill (``explore-notes``)
    OMITS the former and KEEPS the latter.
(c) ``skill_subset=None`` still composes ALL fixture skills — the
    no-silent-skill-loss floor (honesty condition h4) never regresses.
(d) a subset matching nothing in a given repo's catalog composes zero
    skills without error (never a crash, never a partial/garbled catalog).
"""

from __future__ import annotations

from pathlib import Path

from colleague import layers
from colleague.roles import BUILTIN_ROLES, Role

_MODEL = "test-model"
_BASE_PROMPT = "BASE-DEFAULT"

_READ_REPORT_ROLES = ("explorer", "planner", "reviewer", "validator")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_with_release_and_investigation_skills(tmp_path: Path) -> Path:
    """A tmp repo whose skill catalog mirrors this repo's real shape: two
    release/side-effect-class skills (cicd, version-bump) and one
    investigation-shaped skill (explore-notes)."""
    repo = tmp_path / "repo"
    _write(repo / ".colleague" / "skills" / "cicd.md", "# cicd\nOpen and manage PRs.")
    _write(
        repo / ".colleague" / "skills" / "version-bump.md",
        "# version-bump\nBump the release version.",
    )
    _write(
        repo / ".colleague" / "skills" / "explore-notes.md",
        "# explore-notes\nSurvey an area and take investigation notes.",
    )
    return repo


# ---------------------------------------------------------------------------
# (a) non-None subsets on the read/report roles; writer stays None
# ---------------------------------------------------------------------------


class TestBuiltinSkillSubsets:
    def test_read_report_roles_have_curated_subset(self) -> None:
        for name in _READ_REPORT_ROLES:
            role = BUILTIN_ROLES[name]
            assert role.skill_subset is not None, f"{name} must have a curated skill_subset"
            assert len(role.skill_subset) > 0, f"{name}'s skill_subset must not be empty"

    def test_writer_keeps_full_catalog(self) -> None:
        assert BUILTIN_ROLES["writer"].skill_subset is None

    def test_validator_subset_includes_run_tests_pattern(self) -> None:
        # The validator's whole purpose is running tests via its dedicated
        # run_tests tool, so its curated subset keeps the matching skill doc.
        role = BUILTIN_ROLES["validator"]
        assert any(pattern.startswith("run-tests") for pattern in role.skill_subset)


# ---------------------------------------------------------------------------
# (b) composed prompt omits release/cicd-class skills, keeps investigation ones
# ---------------------------------------------------------------------------


class TestComposedPromptCuration:
    def test_explorer_omits_release_skills_keeps_investigation_skill(self, tmp_path: Path) -> None:
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = BUILTIN_ROLES["explorer"]
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        assert prompt is not None
        assert "explore-notes" in prompt
        assert "cicd" not in prompt
        assert "version-bump" not in prompt

    def test_planner_omits_release_skills_keeps_investigation_skill(self, tmp_path: Path) -> None:
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = BUILTIN_ROLES["planner"]
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        assert prompt is not None
        assert "explore-notes" in prompt
        assert "cicd" not in prompt
        assert "version-bump" not in prompt

    def test_reviewer_omits_release_skills_keeps_investigation_skill(self, tmp_path: Path) -> None:
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = BUILTIN_ROLES["reviewer"]
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        assert prompt is not None
        assert "explore-notes" in prompt
        assert "cicd" not in prompt
        assert "version-bump" not in prompt

    def test_validator_omits_release_skills_keeps_investigation_skill(self, tmp_path: Path) -> None:
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = BUILTIN_ROLES["validator"]
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        assert prompt is not None
        assert "explore-notes" in prompt
        assert "cicd" not in prompt
        assert "version-bump" not in prompt


# ---------------------------------------------------------------------------
# (c) skill_subset=None composes ALL fixture skills — no silent skill loss (h4)
# ---------------------------------------------------------------------------


class TestNoSilentSkillLoss:
    def test_writer_composes_every_fixture_skill(self, tmp_path: Path) -> None:
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = BUILTIN_ROLES["writer"]
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        assert prompt is not None
        assert "explore-notes" in prompt
        assert "cicd" in prompt
        assert "version-bump" in prompt

    def test_none_subset_composes_all_regardless_of_role(self, tmp_path: Path) -> None:
        # A custom role with skill_subset=None must never silently drop a
        # skill, independent of which built-in it otherwise resembles.
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = Role(
            name="custom-full",
            prompt_fragment="Custom full-catalog role.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        assert prompt is not None
        assert "explore-notes" in prompt
        assert "cicd" in prompt
        assert "version-bump" in prompt


# ---------------------------------------------------------------------------
# (d) a subset matching nothing composes zero skills, never an error
# ---------------------------------------------------------------------------


class TestSubsetMatchingNothing:
    def test_nonmatching_subset_yields_empty_catalog_no_error(self, tmp_path: Path) -> None:
        repo = _repo_with_release_and_investigation_skills(tmp_path)
        role = Role(
            name="dead-end",
            prompt_fragment="Dead-end subset role.",
            tool_allowlist=("read_file",),
            skill_subset=("no-such-skill-*", "totally-absent"),
            read_only=True,
        )
        # Must not raise.
        prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        # The role fragment still composes; the skills section is simply absent.
        assert prompt is not None
        assert "Dead-end subset role." in prompt
        assert "Available skills" not in prompt
        assert "cicd" not in prompt
        assert "explore-notes" not in prompt

    def test_builtin_read_report_roles_against_repo_with_no_matching_skills(
        self, tmp_path: Path
    ) -> None:
        # A repo whose only skills are release/side-effect-shaped (no
        # investigation-shaped skill at all) must still compose cleanly —
        # empty skills section, no exception — for every read/report role.
        repo = tmp_path / "repo"
        _write(repo / ".colleague" / "skills" / "cicd.md", "# cicd\nOpen and manage PRs.")
        _write(
            repo / ".colleague" / "skills" / "version-bump.md",
            "# version-bump\nBump the release version.",
        )
        for name in _READ_REPORT_ROLES:
            role = BUILTIN_ROLES[name]
            prompt = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
            assert prompt is not None, name
            assert "Available skills" not in prompt, name
            assert "cicd" not in prompt, name


# ---------------------------------------------------------------------------
# Unit-level: _filter_skills honors fnmatch-style glob patterns
# ---------------------------------------------------------------------------


class TestFilterSkillsGlobSemantics:
    def _skills(self, tmp_path: Path) -> dict[str, layers.Skill]:
        names = ("cicd", "version-bump", "explore-notes", "review-checklist")
        skills: dict[str, layers.Skill] = {}
        for name in names:
            path = tmp_path / f"{name}.md"
            path.write_text(f"# {name}\nBody.", encoding="utf-8")
            skills[name] = layers.Skill(name=name, path=path, scope=layers.SKILL_BASE)
        return skills

    def test_glob_pattern_matches_a_class_of_skills(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        filtered = layers._filter_skills(skills, ("explore*", "review*"))
        assert set(filtered) == {"explore-notes", "review-checklist"}

    def test_exact_name_still_matches_only_itself(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        filtered = layers._filter_skills(skills, ("cicd",))
        assert set(filtered) == {"cicd"}

    def test_none_passes_through_unfiltered(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        filtered = layers._filter_skills(skills, None)
        assert filtered == skills

    def test_empty_tuple_yields_nothing(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        filtered = layers._filter_skills(skills, ())
        assert filtered == {}

    def test_nonmatching_pattern_yields_nothing_no_error(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        filtered = layers._filter_skills(skills, ("no-such-thing*",))
        assert filtered == {}

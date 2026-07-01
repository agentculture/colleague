"""Token-capped skill composition (t11, spec R4 / honesty condition h4).

``compose_skills`` (and the role-composed path, ``compose_role_prompt``) gains
an optional token cap. Resolution: an explicit parameter wins, else the
``COLLEAGUE_SKILLS_TOKEN_CAP`` env var (``CONVERTIBLE_SKILLS_TOKEN_CAP`` legacy
fallback), else 0 = uncapped = byte-identical to today (the h4 floor).

When the composed catalog would exceed the cap, whole skills are dropped —
lowest priority first, ties broken by reverse name order (the alphabetically
later name is dropped first) — and one explicit note line is appended:
``omitted N skill(s) over the token cap: <name1>, <name2>``. A skill is never
truncated mid-text.

TDD acceptance items covered here:
(b) under-cap catalog is byte-identical (cap=0 AND a generous cap).
(c) over-cap drops whole lowest-priority skills + the omitted-note names them.
(d) a skill is never split mid-text.
(e) role subset + cap compose together (filter first, then cap).
plus: the documented tie-break rule, and env-var cap resolution precedence.
"""

from __future__ import annotations

from pathlib import Path

from colleague import layers
from colleague.layers import Skill
from colleague.roles import Role

_BASE_PROMPT = "BASE-DEFAULT"
_MODEL = "test-model"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(tmp_path: Path, name: str, text: str) -> Skill:
    path = tmp_path / f"{name}.md"
    _write(path, text)
    return Skill(name=name, path=path, scope=layers.SKILL_BASE)


def _word_count_tokens(text: str) -> int:
    """A simple, fully deterministic token counter for tests: one token per
    whitespace-separated word. Using a custom counter (rather than the char
    heuristic) makes cap math exact and easy to reason about in test fixtures,
    while still exercising the pluggable ``count_tokens`` seam."""
    return len(text.split())


# ---------------------------------------------------------------------------
# (b) under-cap catalog is byte-identical to today's composition
# ---------------------------------------------------------------------------


class TestUnderCapByteIdentical:
    def _skills(self, tmp_path: Path) -> dict[str, Skill]:
        return {
            "alpha": _skill(tmp_path, "alpha", "# alpha\nAlpha summary."),
            "beta": _skill(tmp_path, "beta", "# beta\nBeta summary."),
        }

    def test_cap_zero_is_byte_identical_to_uncapped(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        baseline = layers.compose_skills(skills)
        capped = layers.compose_skills(skills, token_cap=0)
        assert capped == baseline

    def test_generous_cap_is_byte_identical_to_uncapped(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        baseline = layers.compose_skills(skills)
        capped = layers.compose_skills(skills, token_cap=100_000)
        assert capped == baseline

    def test_no_cap_kwarg_matches_explicit_none(self, tmp_path: Path) -> None:
        skills = self._skills(tmp_path)
        assert layers.compose_skills(skills) == layers.compose_skills(skills, token_cap=None)

    def test_empty_skills_dict_is_always_empty_string(self) -> None:
        assert layers.compose_skills({}, token_cap=5) == ""
        assert layers.compose_skills({}) == ""


# ---------------------------------------------------------------------------
# (c) over-cap drops whole lowest-priority skills + names them in the note
# ---------------------------------------------------------------------------


class TestOverCapDropsLowestPriorityFirst:
    def test_lower_priority_skill_dropped_first(self, tmp_path: Path) -> None:
        skills = {
            # No marker -> default priority 100 (lower priority than beta).
            "alpha": _skill(tmp_path, "alpha", "# alpha\nAlpha summary line."),
            "beta": _skill(
                tmp_path, "beta", "<!-- skill-priority: 1 -->\n# beta\nBeta summary line."
            ),
        }
        # header=5 words, each entry=5 words -> 2 entries=15, 1 entry=10.
        text = layers.compose_skills(skills, token_cap=10, count_tokens=_word_count_tokens)
        body, _, note = text.partition("\n\nomitted")
        assert "beta" in body
        assert "alpha" not in body
        assert note  # a note was appended
        assert "omitted 1 skill(s) over the token cap: alpha" in text

    def test_omitted_note_names_every_dropped_skill(self, tmp_path: Path) -> None:
        skills = {
            "alpha": _skill(
                tmp_path, "alpha", "<!-- skill-priority: 50 -->\n# alpha\nAlpha summary line."
            ),
            "beta": _skill(
                tmp_path, "beta", "<!-- skill-priority: 60 -->\n# beta\nBeta summary line."
            ),
            "gamma": _skill(
                tmp_path, "gamma", "<!-- skill-priority: 1 -->\n# gamma\nGamma summary line."
            ),
        }
        # header=5, each entry=5 words -> total=20. Cap=10 keeps exactly gamma.
        text = layers.compose_skills(skills, token_cap=10, count_tokens=_word_count_tokens)
        assert "omitted 2 skill(s) over the token cap: beta, alpha" in text

    def test_never_drops_silently_note_always_present_when_something_omitted(
        self, tmp_path: Path
    ) -> None:
        skills = {
            "alpha": _skill(tmp_path, "alpha", "# alpha\nAlpha summary line."),
            "beta": _skill(tmp_path, "beta", "# beta\nBeta summary line."),
        }
        text = layers.compose_skills(skills, token_cap=10, count_tokens=_word_count_tokens)
        assert "omitted" in text


# ---------------------------------------------------------------------------
# Tie-break: equal priority -> alphabetically LATER name dropped first
# ---------------------------------------------------------------------------


class TestTieBreak:
    def test_equal_priority_drops_alphabetically_later_name_first(self, tmp_path: Path) -> None:
        skills = {
            "aaa": _skill(tmp_path, "aaa", "# aaa\nAAA summary line here."),
            "zzz": _skill(tmp_path, "zzz", "# zzz\nZZZ summary line here."),
        }
        # header=5, each entry=6 words -> 1 entry=11, 2 entries=17.
        kept, omitted = layers.select_skills_within_budget(
            skills, token_cap=11, count_tokens=_word_count_tokens
        )
        assert omitted == ["zzz"]
        assert set(kept) == {"aaa"}

    def test_tie_break_is_independent_of_dict_insertion_order(self, tmp_path: Path) -> None:
        skills = {
            "zzz": _skill(tmp_path, "zzz", "# zzz\nZZZ summary line here."),
            "aaa": _skill(tmp_path, "aaa", "# aaa\nAAA summary line here."),
        }
        kept, omitted = layers.select_skills_within_budget(
            skills, token_cap=11, count_tokens=_word_count_tokens
        )
        assert omitted == ["zzz"]
        assert set(kept) == {"aaa"}


# ---------------------------------------------------------------------------
# (d) a skill is never split mid-text
# ---------------------------------------------------------------------------


class TestNeverTruncatesMidSkill:
    def test_surviving_skill_full_text_present_omitted_fully_absent(self, tmp_path: Path) -> None:
        skills = {
            "keep-me": _skill(
                tmp_path,
                "keep-me",
                "<!-- skill-priority: 1 -->\n# keep-me\nKEEP_ME_UNIQUE_MARKER full sentence.",
            ),
            "drop-me": _skill(
                tmp_path,
                "drop-me",
                "<!-- skill-priority: 90 -->\n# drop-me\nDROP_ME_UNIQUE_MARKER full sentence.",
            ),
        }
        text = layers.compose_skills(skills, token_cap=11, count_tokens=_word_count_tokens)
        body, _, _note = text.partition("\n\nomitted")
        # The surviving skill's full summary line is present, verbatim.
        assert "- keep-me: KEEP_ME_UNIQUE_MARKER full sentence." in body
        # The omitted skill's name AND its summary text are fully absent from
        # the body — not partially present, not truncated.
        assert "drop-me" not in body
        assert "DROP_ME_UNIQUE_MARKER" not in body

    def test_no_partial_word_of_an_omitted_skill_leaks_into_body(self, tmp_path: Path) -> None:
        skills = {
            "aaa": _skill(tmp_path, "aaa", "# aaa\nAAA summary line here."),
            "zzz": _skill(tmp_path, "zzz", "# zzz\nZZZ_DISTINCTIVE_TOKEN summary line here."),
        }
        kept, omitted = layers.select_skills_within_budget(
            skills, token_cap=11, count_tokens=_word_count_tokens
        )
        body = layers._render_skill_catalog(kept, sorted(kept))
        assert "ZZZ_DISTINCTIVE_TOKEN" not in body
        assert omitted == ["zzz"]


# ---------------------------------------------------------------------------
# (e) role subset + cap compose together: filter first, then cap
# ---------------------------------------------------------------------------


class TestRoleSubsetAndCapComposeTogether:
    def test_subset_excludes_regardless_of_cap_then_cap_trims_the_rest(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        _write(repo / ".colleague" / "skills" / "cicd.md", "# cicd\nOpen and manage PRs.")
        _write(
            repo / ".colleague" / "skills" / "explore-a.md",
            "<!-- skill-priority: 50 -->\n# explore-a\nExplore A summary line here.",
        )
        _write(
            repo / ".colleague" / "skills" / "explore-b.md",
            "<!-- skill-priority: 1 -->\n# explore-b\nExplore B summary line here.",
        )
        role = Role(
            name="scoped",
            prompt_fragment="Scoped role.",
            tool_allowlist=("read_file",),
            skill_subset=("explore*",),
            read_only=True,
        )
        # header=5, each explore-* entry=7 words -> 1 entry=12, 2 entries=19.
        prompt = layers.compose_role_prompt(
            role,
            repo,
            _MODEL,
            base=_BASE_PROMPT,
            skills_token_cap=12,
            count_tokens=_word_count_tokens,
        )
        assert prompt is not None
        # cicd is excluded by the role's skill_subset — never appears, not even
        # in the omitted-note (the filter runs BEFORE the cap ever sees it).
        assert "cicd" not in prompt
        # explore-b (priority 1) survives the cap; explore-a (priority 50, the
        # lower-priority one) is dropped by the cap, not the filter.
        body, _, note = prompt.partition("omitted")
        assert "explore-b" in body
        assert "explore-a" not in body
        assert "explore-a" in note
        assert "explore-b" not in note

    def test_none_subset_with_cap_still_caps_the_full_catalog(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _write(
            repo / ".colleague" / "skills" / "one.md",
            "<!-- skill-priority: 1 -->\n# one\nOne summary line here now.",
        )
        _write(
            repo / ".colleague" / "skills" / "two.md",
            "<!-- skill-priority: 90 -->\n# two\nTwo summary line here now.",
        )
        role = Role(
            name="full",
            prompt_fragment="Full role.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        prompt = layers.compose_role_prompt(
            role,
            repo,
            _MODEL,
            base=_BASE_PROMPT,
            skills_token_cap=12,
            count_tokens=_word_count_tokens,
        )
        assert prompt is not None
        assert "one" in prompt
        assert "omitted 1 skill(s) over the token cap: two" in prompt

    def test_role_with_no_cap_is_byte_identical_to_before(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _write(repo / ".colleague" / "skills" / "alpha.md", "# alpha\nAlpha skill.")
        _write(repo / ".colleague" / "skills" / "beta.md", "# beta\nBeta skill.")
        role = Role(
            name="test_role",
            prompt_fragment="Role fragment.",
            tool_allowlist=("read_file",),
            skill_subset=None,
            read_only=True,
        )
        without_kwargs = layers.compose_role_prompt(role, repo, _MODEL, base=_BASE_PROMPT)
        with_none_cap = layers.compose_role_prompt(
            role, repo, _MODEL, base=_BASE_PROMPT, skills_token_cap=None, count_tokens=None
        )
        assert without_kwargs == with_none_cap


# ---------------------------------------------------------------------------
# select_skills_within_budget: direct unit coverage
# ---------------------------------------------------------------------------


class TestSelectSkillsWithinBudget:
    def test_uncapped_returns_all_skills_and_no_omissions(self, tmp_path: Path) -> None:
        skills = {
            "a": _skill(tmp_path, "a", "# a\nA."),
            "b": _skill(tmp_path, "b", "# b\nB."),
        }
        kept, omitted = layers.select_skills_within_budget(skills, 0)
        assert kept == skills
        assert omitted == []

    def test_empty_skills_dict_returns_empty(self) -> None:
        kept, omitted = layers.select_skills_within_budget({}, 50)
        assert kept == {}
        assert omitted == []

    def test_drop_order_is_worst_priority_first(self, tmp_path: Path) -> None:
        skills = {
            "low": _skill(
                tmp_path, "low", "<!-- skill-priority: 200 -->\n# low\nLow summary line here."
            ),
            "mid": _skill(
                tmp_path, "mid", "<!-- skill-priority: 100 -->\n# mid\nMid summary line here."
            ),
            "high": _skill(
                tmp_path, "high", "<!-- skill-priority: 1 -->\n# high\nHigh summary line here."
            ),
        }
        # Cap so tight only one skill fits -> drop order should surface low, then mid.
        kept, omitted = layers.select_skills_within_budget(
            skills, token_cap=11, count_tokens=_word_count_tokens
        )
        assert omitted == ["low", "mid"]
        assert set(kept) == {"high"}


# ---------------------------------------------------------------------------
# env-var resolution: explicit > COLLEAGUE_SKILLS_TOKEN_CAP > legacy > default
# ---------------------------------------------------------------------------


class TestResolveSkillsTokenCapEnv:
    def test_explicit_wins_over_env(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_SKILLS_TOKEN_CAP", "999")
        assert layers.resolve_skills_token_cap(50) == 50

    def test_env_used_when_no_explicit(self, monkeypatch) -> None:
        monkeypatch.delenv("CONVERTIBLE_SKILLS_TOKEN_CAP", raising=False)
        monkeypatch.setenv("COLLEAGUE_SKILLS_TOKEN_CAP", "42")
        assert layers.resolve_skills_token_cap() == 42

    def test_legacy_env_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("COLLEAGUE_SKILLS_TOKEN_CAP", raising=False)
        monkeypatch.setenv("CONVERTIBLE_SKILLS_TOKEN_CAP", "77")
        assert layers.resolve_skills_token_cap() == 77

    def test_new_env_wins_over_legacy(self, monkeypatch) -> None:
        monkeypatch.setenv("COLLEAGUE_SKILLS_TOKEN_CAP", "42")
        monkeypatch.setenv("CONVERTIBLE_SKILLS_TOKEN_CAP", "77")
        assert layers.resolve_skills_token_cap() == 42

    def test_default_is_zero_uncapped(self, monkeypatch) -> None:
        monkeypatch.delenv("COLLEAGUE_SKILLS_TOKEN_CAP", raising=False)
        monkeypatch.delenv("CONVERTIBLE_SKILLS_TOKEN_CAP", raising=False)
        assert layers.resolve_skills_token_cap() == 0

    def test_malformed_env_value_falls_back_to_default(self, monkeypatch) -> None:
        monkeypatch.delenv("CONVERTIBLE_SKILLS_TOKEN_CAP", raising=False)
        monkeypatch.setenv("COLLEAGUE_SKILLS_TOKEN_CAP", "not-a-number")
        assert layers.resolve_skills_token_cap() == 0

    def test_compose_skills_honors_env_cap_when_no_explicit_param(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.delenv("CONVERTIBLE_SKILLS_TOKEN_CAP", raising=False)
        monkeypatch.setenv("COLLEAGUE_SKILLS_TOKEN_CAP", "10")
        skills = {
            "alpha": _skill(
                tmp_path, "alpha", "<!-- skill-priority: 90 -->\n# alpha\nAlpha summary line."
            ),
            "beta": _skill(
                tmp_path, "beta", "<!-- skill-priority: 1 -->\n# beta\nBeta summary line."
            ),
        }
        text = layers.compose_skills(skills, count_tokens=_word_count_tokens)
        assert "omitted 1 skill(s) over the token cap: alpha" in text


# ---------------------------------------------------------------------------
# default counter: count_skill_tokens_chars delegates to context.count_tokens_chars
# ---------------------------------------------------------------------------


class TestDefaultCounterDelegatesToContextHeuristic:
    def test_matches_context_count_tokens_chars(self) -> None:
        from colleague.context import count_tokens_chars

        text = "some skill catalog text of a certain length"
        assert layers.count_skill_tokens_chars(text) == count_tokens_chars([{"content": text}])

    def test_empty_text_is_zero(self) -> None:
        assert layers.count_skill_tokens_chars("") == 0

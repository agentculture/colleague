"""Unit tests for :mod:`colleague.architecture_facts`."""

from __future__ import annotations

from colleague.architecture_facts import ARCHITECTURE_FACTS, load_architecture_facts


class TestLoadArchitectureFacts:
    def test_returns_non_empty_str(self) -> None:
        fragment = load_architecture_facts()
        assert isinstance(fragment, str)
        assert fragment.strip() != ""

    def test_names_senses_as_the_front_lobe(self) -> None:
        fragment = load_architecture_facts().lower()
        assert "senses" in fragment
        assert "front" in fragment

    def test_names_cortex_as_the_back_lobe_that_does_the_work(self) -> None:
        fragment = load_architecture_facts().lower()
        assert "cortex" in fragment
        assert "back" in fragment

    def test_states_senses_does_not_touch_the_repo(self) -> None:
        fragment = load_architecture_facts().lower()
        # Pin on stable, low-level substrings rather than a full sentence so
        # the exact wording can evolve without breaking this test.
        assert "senses" in fragment
        assert "tools-off" in fragment or "tools off" in fragment
        assert "never" in fragment
        assert "repo" in fragment

    def test_states_identity_one_runtime_many_minds(self) -> None:
        fragment = load_architecture_facts().lower()
        assert "swappable coder-agent harness" in fragment
        assert "one runtime, many minds" in fragment

    def test_mentions_core_capabilities(self) -> None:
        fragment = load_architecture_facts().lower()
        for capability in (
            "read_file",
            "write_file",
            "edit_file",
            "list_dir",
            "run_command",
            "finish",
            "subagent",
            "plan mode",
            "lint",
            "test-integrity",
            "affected-tests",
        ):
            assert capability in fragment

    def test_mentions_backends_are_operator_configured(self) -> None:
        fragment = load_architecture_facts().lower()
        assert "operator" in fragment
        assert "config" in fragment or "lobes" in fragment

    def test_mentions_senses_may_defer_to_cortex(self) -> None:
        fragment = load_architecture_facts().lower()
        assert "defer" in fragment

    def test_fragment_is_rendered_as_bullet_lines(self) -> None:
        fragment = load_architecture_facts()
        lines = [line for line in fragment.splitlines() if line.strip()]
        assert len(lines) >= 5
        for line in lines:
            assert line.strip().startswith(("-", "*", "•"))

    def test_fragment_derives_from_the_structured_constant(self) -> None:
        fragment = load_architecture_facts()
        # Every fact in the structured constant must show up verbatim in the
        # rendered fragment — the loader must not silently drop or rewrite facts.
        for fact in _flatten(ARCHITECTURE_FACTS):
            assert fact in fragment

    def test_structured_constant_is_non_empty(self) -> None:
        facts = list(_flatten(ARCHITECTURE_FACTS))
        assert len(facts) >= 5
        for fact in facts:
            assert isinstance(fact, str)
            assert fact.strip() != ""

    def test_is_pure_and_deterministic(self) -> None:
        first = load_architecture_facts()
        second = load_architecture_facts()
        assert first == second


def _flatten(facts) -> list:
    """Yield every fact string out of ``ARCHITECTURE_FACTS``.

    ``ARCHITECTURE_FACTS`` may be a flat tuple of strings, or a dict grouping
    strings/tuples by topic — flatten either shape uniformly for assertions.
    """
    flattened: list = []
    if isinstance(facts, dict):
        for value in facts.values():
            flattened.extend(_flatten(value))
    elif isinstance(facts, (tuple, list)):
        for item in facts:
            flattened.extend(_flatten(item))
    else:
        flattened.append(facts)
    return flattened

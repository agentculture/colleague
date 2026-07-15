"""Unit tests for :func:`colleague.slug.slugify` (the request → label helper)."""

from __future__ import annotations

import pytest

from colleague.slug import DEFAULT_MAX_LEN, slugify


def test_basic_request_slugifies() -> None:
    assert slugify("Add a hello function") == "add-a-hello-function"


def test_punctuation_and_runs_collapse_to_single_dash() -> None:
    assert slugify("Fix:  the  parser!! (again)") == "fix-the-parser-again"


def test_leading_trailing_separators_stripped() -> None:
    assert slugify("  --refactor the loop--  ") == "refactor-the-loop"


@pytest.mark.parametrize("text", ["", "   ", "!!!", "---", "***   ***"])
def test_empty_or_all_punctuation_yields_empty(text: str) -> None:
    assert slugify(text) == ""


def test_unicode_non_ascii_is_dropped_not_crashed() -> None:
    # Non-ASCII letters are not in [a-z0-9]; they collapse to separators. The
    # surrounding ASCII still produces a usable slug (never raises).
    assert slugify("café déjà — résumé") == "caf-d-j-r-sum"


def test_length_is_capped_on_a_word_boundary() -> None:
    slug = slugify("one two three four five six seven eight nine ten eleven")
    assert len(slug) <= DEFAULT_MAX_LEN
    # Backed off to a '-' boundary — never ends mid-word with a trailing dash.
    assert not slug.endswith("-")
    assert slug.startswith("one-two-three")


def test_custom_max_len_honoured() -> None:
    assert slugify("alpha beta gamma delta", max_len=10) == "alpha-beta"


def test_hard_cut_when_no_boundary_to_back_off_to() -> None:
    # A single long token has no '-' to back off to: hard cut at max_len.
    assert slugify("supercalifragilisticexpialidocious", max_len=8) == "supercal"


def test_is_deterministic() -> None:
    text = "Implement the destination tool for vague tasks"
    first = slugify(text)
    second = slugify(text)
    assert first == second

"""--no-affected-tests and --test flags on the work CLI (#213)."""

from __future__ import annotations

from colleague.cli import _build_parser


def test_no_affected_tests_flag_parses() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--no-affected-tests", "--repo", "."])
    assert ns.no_affected_tests is True


def test_no_affected_tests_defaults_false() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--repo", "."])
    assert ns.no_affected_tests is False


def test_test_flag_parses() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--test", "tests/unit", "--repo", "."])
    assert ns.test == "tests/unit"


def test_test_flag_defaults_none() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--repo", "."])
    assert ns.test is None

"""--no-lint flag on the work CLI (#200, task t5)."""

from __future__ import annotations

from colleague.cli import _build_parser


def test_no_lint_flag_parses() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--no-lint", "--repo", "."])
    assert ns.no_lint is True


def test_no_lint_defaults_false() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--repo", "."])
    assert ns.no_lint is False

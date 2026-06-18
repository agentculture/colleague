"""--role flag on the work CLI (t10: typed-subagent roles)."""

from __future__ import annotations

from colleague.cli import _build_parser


def test_role_flag_parses() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--role", "explorer", "--repo", "."])
    assert ns.role == "explorer"


def test_role_flag_default_none() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--repo", "."])
    assert ns.role is None


def test_role_flag_writer() -> None:
    ns = _build_parser().parse_args(["work", "do a thing", "--role", "writer", "--repo", "."])
    assert ns.role == "writer"

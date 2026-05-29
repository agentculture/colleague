"""Edge-branch coverage for ``convertible/policy.py``.

Targets the defensive/degenerate branches that the happy-path policy tests don't
reach: an unsupported checksum algorithm, an unknown file category, malformed
allow/deny shapes, an unparseable run_command string, and a non-object ledger.
"""

from __future__ import annotations

import pytest

from convertible import policy


def test_file_checksum_rejects_unsupported_algo(tmp_path):
    f = tmp_path / "x"
    f.write_text("hi")
    with pytest.raises(ValueError):
        policy.file_checksum(f, "crc32")


def test_check_file_unknown_category_is_ungated(tmp_path):
    dotdir = tmp_path / ".convertible"
    dotdir.mkdir()
    (dotdir / "approvals.json").write_text('{"commands": {"a": "sha256:x"}}')
    pol = policy.load_policy(tmp_path)
    verdict = pol.check_file("bogus", "a", tmp_path / "a")
    assert verdict.allowed  # unrecognised category never gates


def test_str_list_non_list_is_empty():
    assert policy._str_list("not a list") == []


def test_str_list_drops_non_strings():
    assert policy._str_list(["a", 1, "b", None]) == ["a", "b"]


def test_first_token_unparseable_is_none():
    assert policy._first_token('echo "unbalanced') is None


def test_first_token_blank_is_none():
    assert policy._first_token("   ") is None


def test_parse_policy_file_non_object_is_empty(tmp_path):
    p = tmp_path / "approvals.json"
    p.write_text("[1, 2, 3]")
    assert policy._parse_policy_file(p) == {}


def test_parse_policy_file_drops_non_object_sections(tmp_path):
    p = tmp_path / "approvals.json"
    p.write_text('{"commands": {"a": "sha256:x"}, "junk": "str", "more": [1]}')
    parsed = policy._parse_policy_file(p)
    assert "commands" in parsed
    assert "junk" not in parsed and "more" not in parsed

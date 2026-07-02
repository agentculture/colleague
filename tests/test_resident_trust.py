"""t13 — the c19 trust-policy classifier: any channel member may ask, only the
operator is authoritative.

Pure/synchronous — no ``agent_lifecycle`` import needed (the classifier reads
plain ``str``/``Mapping`` values a caller extracts from a ``Message``, never
the ``Message`` type itself), so this module (unlike the harness/supervisor
seam tests) runs unconditionally, with no ``[culture]``/``[resident]`` extra
required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from colleague.resident.trust import (
    ALLOW_READ_ONLY,
    ALLOW_WRITE,
    READ_ONLY_ROLE,
    REFUSE,
    check_attachment_path,
    classify_request,
)


def test_operator_request_is_allowed_write_unrestricted() -> None:
    """The operator's own requests are unrestricted — write-capable, no role cap."""
    decision = classify_request(sender="ori", metadata=None, operator_identity="ori")
    assert decision.outcome == ALLOW_WRITE
    assert decision.role is None
    assert "ori" in decision.reason


def test_non_operator_plain_request_is_downgraded_to_read_only() -> None:
    """A non-operator's plain request is downgraded to the read-only explorer role."""
    decision = classify_request(sender="some-peer", metadata=None, operator_identity="ori")
    assert decision.outcome == ALLOW_READ_ONLY
    assert decision.role == READ_ONLY_ROLE
    assert "some-peer" in decision.reason


def test_non_operator_explicit_write_request_is_refused() -> None:
    """A non-operator explicitly asking for write access is refused (beyond limits)."""
    decision = classify_request(
        sender="some-peer",
        metadata={"mode": "write"},
        operator_identity="ori",
    )
    assert decision.outcome == REFUSE
    assert decision.role is None
    assert "some-peer" in decision.reason
    assert "operator" in decision.reason.lower()


def test_operator_explicit_write_request_still_allowed() -> None:
    """The operator asking explicitly for write mode is still just ALLOW_WRITE (no-op flag)."""
    decision = classify_request(
        sender="ori",
        metadata={"mode": "write"},
        operator_identity="ori",
    )
    assert decision.outcome == ALLOW_WRITE
    assert decision.role is None


def test_unresolved_operator_identity_never_grants_write() -> None:
    """A None operator_identity is a fail-safe: nobody is treated as the operator."""
    decision_plain = classify_request(sender="anyone", metadata=None, operator_identity=None)
    assert decision_plain.outcome == ALLOW_READ_ONLY

    decision_write = classify_request(
        sender="anyone", metadata={"mode": "write"}, operator_identity=None
    )
    assert decision_write.outcome == REFUSE


def test_empty_operator_identity_string_never_matches() -> None:
    """An empty-string operator_identity is falsy — never matches any sender."""
    decision = classify_request(sender="", metadata=None, operator_identity="")
    assert decision.outcome == ALLOW_READ_ONLY


def test_metadata_defaults_to_empty_mapping() -> None:
    """Omitting metadata entirely is equivalent to an empty mapping (no write request)."""
    decision = classify_request(sender="peer", operator_identity="ori")
    assert decision.outcome == ALLOW_READ_ONLY


def test_unrelated_metadata_mode_value_does_not_trigger_write() -> None:
    """A metadata 'mode' value other than exactly 'write' is treated as a plain request."""
    decision = classify_request(sender="peer", metadata={"mode": "read"}, operator_identity="ori")
    assert decision.outcome == ALLOW_READ_ONLY


# ---------------------------------------------------------------------------
# check_attachment_path -- relative paths are anchored to repo_path, not the
# resident process's current working directory (Qodo reliability finding).
# ---------------------------------------------------------------------------


def test_non_operator_relative_attach_path_is_resolved_against_repo_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo-relative `attach:` reference (e.g. `docs/img.png`) must resolve
    against repo_path regardless of the resident process's CWD -- previously
    `Path(path).resolve()` resolved a relative path against the process CWD,
    so a valid repo-relative reference was wrongly refused when the resident
    was started from a different working directory."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    picture = repo / "docs" / "img.png"
    picture.write_bytes(b"\x89PNG")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    decision = check_attachment_path(
        "docs/img.png", repo_path=str(repo), sender="random-peer", operator_identity="ori"
    )
    assert decision.allowed is True


def test_non_operator_relative_dotdot_escape_is_still_refused_regardless_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative `..` escape must still be refused once anchored to
    repo_path -- CWD-independence must not weaken the containment rule."""
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private key material")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    decision = check_attachment_path(
        "../secret.txt", repo_path=str(repo), sender="random-peer", operator_identity="ori"
    )
    assert decision.allowed is False
    assert "repo" in decision.reason.lower()


def test_non_operator_absolute_path_outside_repo_still_refused_regardless_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absolute path outside the repo is still refused for a non-operator
    -- absolute-path handling is unaffected by the CWD-anchoring fix."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside" / "secret.png"
    outside.parent.mkdir()
    outside.write_bytes(b"\x89PNG")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    decision = check_attachment_path(
        str(outside), repo_path=str(repo), sender="random-peer", operator_identity="ori"
    )
    assert decision.allowed is False

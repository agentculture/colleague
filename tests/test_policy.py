"""Approval-gate policy tests (t1) — TEST-FIRST.

Covers the operator-declared approval gate in :mod:`colleague.policy`:

* Absent ``approvals.json`` → empty Policy, pass-through no-ops (back-compat).
* Checksum verification over file bytes; algorithm-prefixed values
  (``sha256:`` default, ``md5:`` honored); a changed file fails to match.
* ``check_run_command``: shlex extracts the program token; allow-list denies
  unlisted tokens; deny-list blocks listed tokens; present-section gating.
* Per-model overlay path is built by **exact construction** via
  :func:`colleague.layers.sanitize_model` — model X never loads model Y's
  policy (no sibling glob).
* The module imports stdlib only (mirrors ``tests/test_zero_deps.py`` style).

Fixtures mirror the existing test style (``tmp_path`` repo + fake user home),
matching ``tests/test_hooks_per_model.py`` / ``tests/test_configdir.py``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from colleague.layers import sanitize_model
from colleague.policy import (
    DEFAULT_ALGO,
    POLICY_FILENAME,
    Policy,
    Verdict,
    file_checksum,
    load_policy,
    verify_checksum,
)

# ---------------------------------------------------------------------------
# Module-level constants (mirroring test_hooks_per_model.py _MODEL_X / _MODEL_Y)
# ---------------------------------------------------------------------------

_MODEL_X = "Qwen/Qwen3-32B"
_SAFE_X = sanitize_model(_MODEL_X)  # "Qwen-Qwen3-32B"

_MODEL_Y = "meta/Llama-3.1-8B"
_SAFE_Y = sanitize_model(_MODEL_Y)  # "meta-Llama-3.1-8B"


# ---------------------------------------------------------------------------
# Helpers (mirrors _repo / _home / _write in test_hooks_per_model.py)
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    """Create and return a bare repo directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _home(tmp_path: Path) -> Path:
    """Create and return a fake user home directory."""
    home = tmp_path / "home"
    home.mkdir()
    return home


def _write_policy(dotdir: Path, relative: str, payload: dict) -> Path:
    """Write *payload* as JSON to *dotdir*/*relative*; mkdir -p as needed."""
    path = dotdir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_file(path: Path, content: bytes) -> Path:
    """Write raw *content* bytes to *path*; mkdir -p as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ===========================================================================
# AC1 — Absent approvals.json → empty Policy, pass-through no-ops
# ===========================================================================


def test_load_policy_absent_is_empty(tmp_path: Path) -> None:
    """No approvals.json anywhere → Policy.is_empty() is True."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    policy = load_policy(repo, user_home=home)
    assert isinstance(policy, Policy)
    assert policy.is_empty() is True


def test_empty_policy_run_command_passthrough(tmp_path: Path) -> None:
    """Absent run_command section → every command is allowed (no-op)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    policy = load_policy(repo, user_home=home)
    verdict = policy.check_run_command("rm -rf /")
    assert isinstance(verdict, Verdict)
    assert verdict.allowed is True


def test_empty_policy_check_file_passthrough(tmp_path: Path) -> None:
    """Absent hooks/commands section → check_file allows anything (no-op)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    policy = load_policy(repo, user_home=home)
    some_file = _write_file(tmp_path / "lint.sh", b"echo hi")
    assert policy.check_file("hooks", "lint.sh", some_file).allowed is True
    # Even a non-existent file is allowed when the section is absent.
    assert policy.check_file("commands", "missing", tmp_path / "nope").allowed is True


def test_absent_model_overlay_is_strict_no_op(tmp_path: Path) -> None:
    """Passing a model with no overlay behaves identically to no model."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    policy = load_policy(repo, model=_MODEL_X, user_home=home)
    assert policy.is_empty() is True
    assert policy.check_run_command("anything goes").allowed is True


# ===========================================================================
# AC2 — Checksum verification over file bytes; algorithm-prefixed values
# ===========================================================================


def test_file_checksum_default_is_sha256(tmp_path: Path) -> None:
    """file_checksum default algo is sha256 and is prefixed accordingly."""
    f = _write_file(tmp_path / "f.sh", b"hello world")
    cs = file_checksum(f)
    assert DEFAULT_ALGO == "sha256"
    assert cs.startswith("sha256:")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert cs == f"sha256:{expected}"


def test_file_checksum_md5_honored(tmp_path: Path) -> None:
    """file_checksum honors md5 and prefixes md5:."""
    f = _write_file(tmp_path / "f.sh", b"hello world")
    cs = file_checksum(f, algo="md5")
    expected = hashlib.md5(b"hello world").hexdigest()  # noqa: S324 - test vector
    assert cs == f"md5:{expected}"


def test_verify_checksum_match_and_mismatch(tmp_path: Path) -> None:
    """verify_checksum is True on match, False when the file content changes."""
    f = _write_file(tmp_path / "f.sh", b"original")
    approval = file_checksum(f)
    assert verify_checksum(f, approval) is True

    # Change the file content → the stored approval is now void.
    f.write_bytes(b"tampered")
    assert verify_checksum(f, approval) is False


def test_verify_checksum_md5_roundtrip(tmp_path: Path) -> None:
    """An md5-prefixed approval verifies against an md5 recompute."""
    f = _write_file(tmp_path / "f.sh", b"payload")
    approval = file_checksum(f, algo="md5")
    assert verify_checksum(f, approval) is True
    f.write_bytes(b"payload2")
    assert verify_checksum(f, approval) is False


def test_verify_checksum_unknown_algo_is_false(tmp_path: Path) -> None:
    """Unknown algorithm → False, never raises."""
    f = _write_file(tmp_path / "f.sh", b"x")
    assert verify_checksum(f, "sha999:deadbeef") is False


def test_verify_checksum_malformed_approval_is_false(tmp_path: Path) -> None:
    """A malformed approval string (no algo:hex) → False, never raises."""
    f = _write_file(tmp_path / "f.sh", b"x")
    assert verify_checksum(f, "not-a-valid-approval") is False
    assert verify_checksum(f, "") is False


def test_verify_checksum_missing_file_is_false(tmp_path: Path) -> None:
    """A missing file cannot be verified → False, never raises."""
    approval = "sha256:" + hashlib.sha256(b"x").hexdigest()
    assert verify_checksum(tmp_path / "does-not-exist", approval) is False


def test_check_file_present_section_approved_match(tmp_path: Path) -> None:
    """check_file: an approved, unchanged file passes."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    hook = _write_file(repo / ".colleague" / "hooks" / "lint.sh", b"echo lint")
    approval = file_checksum(hook)
    _write_policy(repo / ".colleague", POLICY_FILENAME, {"hooks": {"lint.sh": approval}})

    policy = load_policy(repo, user_home=home)
    assert policy.check_file("hooks", "lint.sh", hook).allowed is True


def test_check_file_present_section_changed_denies(tmp_path: Path) -> None:
    """check_file: an approved file whose content changed is denied."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    hook = _write_file(repo / ".colleague" / "hooks" / "lint.sh", b"echo lint")
    approval = file_checksum(hook)
    _write_policy(repo / ".colleague", POLICY_FILENAME, {"hooks": {"lint.sh": approval}})

    # Tamper after approval was recorded.
    hook.write_bytes(b"rm -rf /")

    policy = load_policy(repo, user_home=home)
    verdict = policy.check_file("hooks", "lint.sh", hook)
    assert verdict.allowed is False
    assert verdict.reason  # populated on deny


def test_check_file_present_section_unlisted_denies(tmp_path: Path) -> None:
    """check_file: a name not in the present section is denied (allow-list)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"hooks": {"lint.sh": "sha256:" + hashlib.sha256(b"x").hexdigest()}},
    )
    other = _write_file(repo / ".colleague" / "hooks" / "evil.sh", b"evil")

    policy = load_policy(repo, user_home=home)
    verdict = policy.check_file("hooks", "evil.sh", other)
    assert verdict.allowed is False
    assert "evil.sh" in verdict.reason


def test_check_file_present_section_missing_file_denies(tmp_path: Path) -> None:
    """check_file: an approved name whose file is gone cannot be verified → deny."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    approval = "sha256:" + hashlib.sha256(b"x").hexdigest()
    _write_policy(repo / ".colleague", POLICY_FILENAME, {"hooks": {"lint.sh": approval}})

    policy = load_policy(repo, user_home=home)
    verdict = policy.check_file("hooks", "lint.sh", repo / ".colleague" / "hooks" / "lint.sh")
    assert verdict.allowed is False


def test_check_file_commands_category(tmp_path: Path) -> None:
    """check_file works for the commands category too (parity with hooks)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    cmd = _write_file(repo / ".colleague" / "commands" / "fix-lint.md", b"# fix lint")
    approval = file_checksum(cmd)
    _write_policy(repo / ".colleague", POLICY_FILENAME, {"commands": {"fix-lint": approval}})

    policy = load_policy(repo, user_home=home)
    assert policy.check_file("commands", "fix-lint", cmd).allowed is True
    cmd.write_bytes(b"# tampered")
    assert policy.check_file("commands", "fix-lint", cmd).allowed is False


# ===========================================================================
# AC3 — check_run_command: shlex token extraction + allow/deny gating
# ===========================================================================


def test_run_command_shlex_token_extraction(tmp_path: Path) -> None:
    """The first shlex token (the program) is what is matched against the lists."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git"], "deny": []}},
    )
    policy = load_policy(repo, user_home=home)
    # "git status --short" → token "git" → allowed.
    assert policy.check_run_command("git status --short").allowed is True


def test_run_command_allow_list_denies_unlisted(tmp_path: Path) -> None:
    """A present allow-list denies a token not in it."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git", "pytest", "uv"], "deny": []}},
    )
    policy = load_policy(repo, user_home=home)
    assert policy.check_run_command("git status").allowed is True
    verdict = policy.check_run_command("curl http://evil")
    assert verdict.allowed is False
    assert "curl" in verdict.reason


def test_run_command_deny_list_blocks_listed(tmp_path: Path) -> None:
    """A deny-list blocks a token in it, even when allow is empty/absent."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": [], "deny": ["rm", "curl"]}},
    )
    policy = load_policy(repo, user_home=home)
    # No allow-list present (empty) → only deny gating; rm is blocked.
    verdict = policy.check_run_command("rm -rf /tmp/x")
    assert verdict.allowed is False
    assert "rm" in verdict.reason
    # Something not denied passes (empty allow-list is not a gate).
    assert policy.check_run_command("ls -la").allowed is True


def test_run_command_section_present_empty_lists_allows(tmp_path: Path) -> None:
    """run_command present with empty allow + empty deny → nothing gated."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": [], "deny": []}},
    )
    policy = load_policy(repo, user_home=home)
    assert policy.check_run_command("anything at all").allowed is True
    # Section IS present, so the policy is not empty.
    assert policy.is_empty() is False


def test_run_command_empty_command_is_safe(tmp_path: Path) -> None:
    """An empty/whitespace command does not crash; with allow-list it denies."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git"], "deny": []}},
    )
    policy = load_policy(repo, user_home=home)
    # Empty command → no token → denied under an allow-list, never raises.
    assert policy.check_run_command("").allowed is False
    assert policy.check_run_command("   ").allowed is False


def test_run_command_deny_takes_priority_over_allow(tmp_path: Path) -> None:
    """A token in both allow and deny is denied (deny wins)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git"], "deny": ["git"]}},
    )
    policy = load_policy(repo, user_home=home)
    assert policy.check_run_command("git push").allowed is False


# ===========================================================================
# AC4 — Per-model overlay isolation (exact-construction via sanitize_model)
# ===========================================================================


def test_per_model_overlay_applies(tmp_path: Path) -> None:
    """An overlay under .colleague/<safe_model>/ applies for that model."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        f"{_SAFE_X}/{POLICY_FILENAME}",
        {"run_command": {"allow": ["git"], "deny": []}},
    )
    policy = load_policy(repo, model=_MODEL_X, user_home=home)
    assert policy.check_run_command("git status").allowed is True
    assert policy.check_run_command("curl x").allowed is False


def test_per_model_isolation_x_not_seen_by_y(tmp_path: Path) -> None:
    """Model X's overlay is invisible when loading for model Y (no sibling glob)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    # X allows only git; Y allows only pytest.
    _write_policy(
        repo / ".colleague",
        f"{_SAFE_X}/{POLICY_FILENAME}",
        {"run_command": {"allow": ["git"], "deny": []}},
    )
    _write_policy(
        repo / ".colleague",
        f"{_SAFE_Y}/{POLICY_FILENAME}",
        {"run_command": {"allow": ["pytest"], "deny": []}},
    )

    policy_x = load_policy(repo, model=_MODEL_X, user_home=home)
    policy_y = load_policy(repo, model=_MODEL_Y, user_home=home)

    # X sees git allowed, pytest denied (Y's entry invisible to X).
    assert policy_x.check_run_command("git status").allowed is True
    assert policy_x.check_run_command("pytest -q").allowed is False

    # Y sees pytest allowed, git denied (X's entry invisible to Y).
    assert policy_y.check_run_command("pytest -q").allowed is True
    assert policy_y.check_run_command("git status").allowed is False


def test_per_model_overlay_wins_over_base(tmp_path: Path) -> None:
    """For a key it defines, the per-model overlay overrides the base section."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    # Base allows git; model-X overlay narrows run_command to pytest only.
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git"], "deny": []}},
    )
    _write_policy(
        repo / ".colleague",
        f"{_SAFE_X}/{POLICY_FILENAME}",
        {"run_command": {"allow": ["pytest"], "deny": []}},
    )

    policy = load_policy(repo, model=_MODEL_X, user_home=home)
    # Overlay's run_command wins for the run_command key.
    assert policy.check_run_command("pytest -q").allowed is True
    assert policy.check_run_command("git status").allowed is False


def test_base_section_survives_when_overlay_defines_other_key(tmp_path: Path) -> None:
    """A base section is preserved when the overlay only defines a different key."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    # Base gates run_command; overlay only gates hooks.
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git"], "deny": []}},
    )
    _write_policy(
        repo / ".colleague",
        f"{_SAFE_X}/{POLICY_FILENAME}",
        {"hooks": {"lint.sh": "sha256:" + hashlib.sha256(b"x").hexdigest()}},
    )

    policy = load_policy(repo, model=_MODEL_X, user_home=home)
    # Base run_command gate still active.
    assert policy.check_run_command("git status").allowed is True
    assert policy.check_run_command("curl x").allowed is False
    # Overlay hooks gate also active (present section).
    assert policy.is_empty() is False


def test_repo_overrides_user_base(tmp_path: Path) -> None:
    """Repo-level approvals.json wins over the user-level one (repo-over-user)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    # User base allows curl; repo base allows only git.
    _write_policy(
        home / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["curl"], "deny": []}},
    )
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": {"allow": ["git"], "deny": []}},
    )

    policy = load_policy(repo, user_home=home)
    assert policy.check_run_command("git status").allowed is True
    # Repo's allow-list wins — curl is not allowed.
    assert policy.check_run_command("curl x").allowed is False


def test_sanitize_model_tokens_match_expected() -> None:
    """Document the exact path construction load_policy uses for overlays."""
    assert _SAFE_X == "Qwen-Qwen3-32B"
    assert _SAFE_Y == "meta-Llama-3.1-8B"


# ===========================================================================
# AC5 — Malformed / resilience: never raise, degrade to no-op
# ===========================================================================


def test_malformed_json_is_treated_as_empty(tmp_path: Path) -> None:
    """A malformed approvals.json degrades to empty, never raises."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    (repo / ".colleague").mkdir(parents=True)
    (repo / ".colleague" / POLICY_FILENAME).write_text("{ not valid json", encoding="utf-8")

    policy = load_policy(repo, user_home=home)
    assert policy.is_empty() is True
    assert policy.check_run_command("rm -rf /").allowed is True


def test_non_object_sections_ignored(tmp_path: Path) -> None:
    """Sections with the wrong shape are ignored (treated as absent)."""
    repo = _repo(tmp_path)
    home = _home(tmp_path)
    _write_policy(
        repo / ".colleague",
        POLICY_FILENAME,
        {"run_command": "not-a-dict", "hooks": ["also", "wrong"]},
    )
    policy = load_policy(repo, user_home=home)
    # Malformed sections do not gate anything.
    assert policy.check_run_command("anything").allowed is True
    assert policy.check_file("hooks", "x", tmp_path / "x").allowed is True


# ===========================================================================
# AC5 — Zero-deps guard: the module imports stdlib only
# ===========================================================================


def test_policy_module_imports_stdlib_only() -> None:
    """Importing + exercising colleague.policy introduces no third-party module.

    Mirrors tests/test_zero_deps.py: snapshot sys.modules before/after, reduce to
    top-level names, and assert none are third-party.
    """
    before = set(sys.modules.keys())

    import colleague.policy as _policy  # noqa: F401

    # Exercise the real load path so any lazy import would surface.
    _policy.load_policy(Path.cwd(), model="some/model")

    new_top_level = {name.split(".")[0] for name in (set(sys.modules.keys()) - before) if name}
    third_party = []
    for name in sorted(new_top_level):
        is_stdlib = name in sys.stdlib_module_names
        is_colleague = name.startswith("colleague")
        is_builtin = name.startswith("_")
        if not (is_stdlib or is_colleague or is_builtin):
            third_party.append(name)
    assert not third_party, f"colleague.policy leaked third-party imports: {third_party}"

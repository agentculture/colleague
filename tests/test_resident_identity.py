"""t4 — identity minting: culture.yaml + prompt, reusing colleague/identity.py.

Acceptance criteria:
  1. The minted culture.yaml carries suffix/backend/model; prompt file is written.
  2. Round-trip: resolve_identity(repo) == suffix after minting (no identity.py changes).
  3. Idempotent re-mint is stable; minting over a differing culture.yaml without
     overwrite=True raises a clear error and does NOT clobber.
"""

from __future__ import annotations

import pytest

from colleague.identity import resolve_identity
from colleague.resident.identity_mint import (
    ConflictError,
    MintResult,
    mint_identity,
)


class TestMintWrites:
    """AC1: minted files carry the right content."""

    def test_culture_yaml_has_suffix_backend_model(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        text = (tmp_path / "culture.yaml").read_text()
        assert "suffix: spark" in text
        assert "backend: colleague" in text
        assert "model: qwen3-27b" in text

    def test_culture_yaml_agents_block_present(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="nova", model="llama3")
        text = (tmp_path / "culture.yaml").read_text()
        assert "agents:" in text

    def test_prompt_file_written_at_root(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        assert (tmp_path / "AGENTS.colleague.md").exists()

    def test_prompt_file_custom_text(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b", prompt_text="hello world")
        text = (tmp_path / "AGENTS.colleague.md").read_text()
        assert "hello world" in text

    def test_prompt_file_custom_filename(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b", prompt_filename="AGENTS.md")
        assert (tmp_path / "AGENTS.md").exists()

    def test_default_prompt_text_non_empty(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        text = (tmp_path / "AGENTS.colleague.md").read_text()
        assert len(text.strip()) > 0

    def test_returns_mint_result(self, tmp_path) -> None:
        result = mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        assert isinstance(result, MintResult)
        assert result.nick == "spark"
        assert result.culture_yaml_path == tmp_path / "culture.yaml"
        assert result.prompt_path == tmp_path / "AGENTS.colleague.md"


class TestRoundTrip:
    """AC2: resolve_identity(repo) == suffix after minting (key criterion)."""

    def test_resolve_identity_reads_back_suffix(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        assert resolve_identity(tmp_path) == "spark"

    def test_resolve_identity_different_suffix(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="nova", model="llama3")
        assert resolve_identity(tmp_path) == "nova"

    def test_resolve_identity_suffix_with_hyphen(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="my-agent", model="mixtral")
        assert resolve_identity(tmp_path) == "my-agent"


class TestIdempotence:
    """AC3a: minting again with the same args is stable."""

    def test_remint_same_args_is_noop(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        text_before = (tmp_path / "culture.yaml").read_text()
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        text_after = (tmp_path / "culture.yaml").read_text()
        assert text_before == text_after

    def test_remint_same_args_returns_same_nick(self, tmp_path) -> None:
        r1 = mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        r2 = mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        assert r1.nick == r2.nick

    def test_remint_same_args_identity_still_resolves(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        assert resolve_identity(tmp_path) == "spark"


class TestConflict:
    """AC3b: minting over a DIFFERING culture.yaml without overwrite=True raises ConflictError."""

    def test_conflict_raises_on_different_suffix(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        with pytest.raises(ConflictError):
            mint_identity(tmp_path, suffix="other", model="qwen3-27b")

    def test_conflict_raises_on_different_model(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        with pytest.raises(ConflictError):
            mint_identity(tmp_path, suffix="spark", model="llama3")

    def test_conflict_does_not_clobber(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        original = (tmp_path / "culture.yaml").read_text()
        with pytest.raises(ConflictError):
            mint_identity(tmp_path, suffix="other", model="qwen3-27b")
        # File must be unchanged
        assert (tmp_path / "culture.yaml").read_text() == original

    def test_conflict_resolved_with_overwrite(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        result = mint_identity(tmp_path, suffix="other", model="qwen3-27b", overwrite=True)
        assert result.nick == "other"
        assert resolve_identity(tmp_path) == "other"

    def test_conflict_error_message_is_clear(self, tmp_path) -> None:
        mint_identity(tmp_path, suffix="spark", model="qwen3-27b")
        with pytest.raises(ConflictError) as exc:
            mint_identity(tmp_path, suffix="other", model="qwen3-27b")
        msg = str(exc.value)
        assert "culture.yaml" in msg
        assert "overwrite" in msg.lower()

    def test_externally_written_culture_yaml_raises(self, tmp_path) -> None:
        """A pre-existing culture.yaml not written by mint_identity triggers ConflictError."""
        (tmp_path / "culture.yaml").write_text("nick: someone\n")
        with pytest.raises(ConflictError):
            mint_identity(tmp_path, suffix="spark", model="qwen3-27b")

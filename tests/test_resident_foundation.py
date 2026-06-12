"""t1 — resident foundation: the [culture] lazy-import boundary + steward consumer.

Covers the spec targets c11 (the resident dep never touches the base/work-item
path) and h3 (opt-in; base unchanged). The boundary-guard exemptions and the
zero-deps assertions live in tests/test_boundary.py and tests/test_zero_deps.py;
this module exercises the runtime behavior of the foundation seam.
"""

from __future__ import annotations

import importlib.util

import pytest

from colleague.resident import CultureExtraMissing, require_culture_deps
from colleague.resident import steward as steward_mod
from colleague.resident.steward import ALLOWED_STEWARD_CLIS, StewardError, run_steward

#: Whether the opt-in [culture] extra is installed in this environment. The
#: import-clean core (steward, require_culture_deps raising) is tested either way;
#: only the "passes when installed" assertion is gated on it.
_HAS_CULTURE = (
    importlib.util.find_spec("agent_lifecycle") is not None
    and importlib.util.find_spec("agentirc") is not None
)


class TestRequireCultureDeps:
    @pytest.mark.skipif(not _HAS_CULTURE, reason="needs the [culture] extra")
    def test_passes_when_extra_installed(self) -> None:
        """With the [culture] extra installed (dev/CI), the gate is a no-op."""
        # Should not raise — agent-lifecycle + agentirc-cli are installed.
        require_culture_deps()

    def test_raises_actionable_message_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing extra surfaces CultureExtraMissing with an install hint, not ImportError."""
        import importlib.util as _util

        real_find_spec = _util.find_spec

        def _fake_find_spec(name: str, *a, **k):
            if name in ("agent_lifecycle", "agentirc"):
                return None
            return real_find_spec(name, *a, **k)

        monkeypatch.setattr("importlib.util.find_spec", _fake_find_spec)
        with pytest.raises(CultureExtraMissing) as exc:
            require_culture_deps()
        msg = str(exc.value)
        assert "colleague[culture]" in msg
        assert "agent-lifecycle" in msg and "agentirc-cli" in msg


class TestRunSteward:
    def test_rejects_cli_outside_allow_list(self, tmp_path) -> None:
        """A CLI name outside the allow-list is refused before any subprocess spawns."""
        with pytest.raises(StewardError) as exc:
            run_steward("rm", ["-rf", "/"], root=tmp_path)
        assert "allow-list" in str(exc.value)

    def test_allow_list_is_steward_and_culture(self) -> None:
        assert ALLOWED_STEWARD_CLIS == frozenset({"steward", "culture"})

    def test_absent_cli_maps_to_clean_error(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An uninstalled CLI surfaces a clean StewardError, never a raw FileNotFoundError."""

        def _boom(*a, **k):
            raise FileNotFoundError("steward")

        monkeypatch.setattr(steward_mod.subprocess, "run", _boom)
        with pytest.raises(StewardError) as exc:
            run_steward("steward", ["roster"], root=tmp_path)
        assert "not found" in str(exc.value)

    def test_returns_exit_and_body(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful launch returns 'exit=<code>\\n<body>'."""

        class _Proc:
            returncode = 0
            stdout = "#colleague\n#general\n"
            stderr = ""

        monkeypatch.setattr(steward_mod.subprocess, "run", lambda *a, **k: _Proc())
        out = run_steward("steward", ["roster"], root=tmp_path)
        assert out.startswith("exit=0\n")
        assert "#colleague" in out

"""t5 — channel selection: query steward, rank, operator-confirm, own #<nick>.

Tests for :mod:`colleague.resident.channels`.  All tests monkeypatch
``colleague.resident.channels.run_steward`` so no real ``steward``/``culture``
CLI is required — the suite runs offline and deterministically.
"""

from __future__ import annotations

import pytest

from colleague.resident.channels import ChannelSelection, select_channels
from colleague.resident.steward import StewardError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROSTER_BODY = "#colleague\n#general\n#eng\n#spark\n"
_ROSTER_REPLY = f"exit=0\n{_ROSTER_BODY}"


def _make_steward_ok(body: str = _ROSTER_BODY) -> object:
    """Return a callable suitable for monkeypatching ``run_steward``."""

    def _run_steward(cli, args, *, root):  # noqa: ANN001
        return f"exit=0\n{body}"

    return _run_steward


def _make_steward_err() -> object:
    """Return a callable that raises :class:`StewardError`."""

    def _run_steward(cli, args, *, root):  # noqa: ANN001
        raise StewardError("steward CLI not found — is it installed and on PATH?")

    return _run_steward


# ---------------------------------------------------------------------------
# ChannelSelection contract
# ---------------------------------------------------------------------------


class TestChannelSelectionContract:
    def test_owned_and_chosen_are_accessible(self, tmp_path) -> None:
        """ChannelSelection exposes .owned and .chosen attributes."""
        sel = ChannelSelection(owned="#colleague", chosen=["#colleague", "#general"])
        assert sel.owned == "#colleague"
        assert "#general" in sel.chosen

    def test_owned_always_in_chosen(self, tmp_path) -> None:
        """The owned channel is always present in chosen, even if not in candidates."""
        sel = ChannelSelection(owned="#mybot", chosen=["#general"])
        # ChannelSelection itself doesn't enforce this — select_channels does.
        # Just verify the dataclass accepts it.
        assert sel.owned == "#mybot"

    def test_degraded_flag_and_note(self) -> None:
        """A degraded ChannelSelection carries a non-empty note."""
        sel = ChannelSelection(
            owned="#colleague", chosen=["#colleague"], degraded=True, note="CLI absent"
        )
        assert sel.degraded is True
        assert sel.note


# ---------------------------------------------------------------------------
# Owned channel resolution
# ---------------------------------------------------------------------------


class TestOwnedChannelResolution:
    def test_owned_channel_uses_nick_from_culture_yaml(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When culture.yaml has a nick, owned == '#<nick>'."""
        culture_yaml = tmp_path / "culture.yaml"
        culture_yaml.write_text("nick: spark\n")

        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok())
        sel = select_channels(tmp_path)
        assert sel.owned == "#spark"

    def test_owned_channel_fallback_when_no_identity(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no nick is resolvable, owned falls back to '#colleague'."""
        # tmp_path has no culture.yaml / identity.json
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok())
        sel = select_channels(tmp_path)
        assert sel.owned == "#colleague"

    def test_owned_channel_from_agents_suffix(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """culture.yaml with agents[].suffix (not top-level nick) resolves correctly."""
        culture_yaml = tmp_path / "culture.yaml"
        culture_yaml.write_text("agents:\n  - suffix: cortex\n    model: x\n")

        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok())
        sel = select_channels(tmp_path)
        assert sel.owned == "#cortex"


# ---------------------------------------------------------------------------
# Candidate channels from steward
# ---------------------------------------------------------------------------


class TestCandidateParsing:
    def test_hash_tokens_extracted_from_body(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Channel names starting with '#' are extracted from the roster body."""
        body = "exit=0\n#alpha\n#beta\nsome-non-channel text\n"

        def _run(cli, args, *, root):  # noqa: ANN001
            return body

        monkeypatch.setattr("colleague.resident.channels.run_steward", _run)
        sel = select_channels(tmp_path)
        for ch in ("#alpha", "#beta"):
            assert ch in sel.chosen

    def test_non_hash_tokens_not_included(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Plain words without '#' prefix are NOT treated as channel names."""
        body = "exit=0\njust-text no-hash here\n"

        def _run(cli, args, *, root):  # noqa: ANN001
            return body

        monkeypatch.setattr("colleague.resident.channels.run_steward", _run)
        sel = select_channels(tmp_path)
        # only the owned channel (#colleague fallback) should be present
        assert sel.chosen == [sel.owned]

    def test_channel_discovery_uses_culture_channel_list(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Channel discovery shells ``culture channel list`` — even when the roster
        CLI is ``steward`` (an agent registrar with no channel-listing verb)."""
        captured: dict = {}

        def _run(cli, args, *, root):  # noqa: ANN001
            captured["cli"] = cli
            captured["args"] = list(args)
            return "exit=0\n"

        monkeypatch.setattr("colleague.resident.channels.run_steward", _run)
        select_channels(tmp_path, roster_cli="steward")
        assert captured["cli"] == "culture"
        assert captured["args"] == ["channel", "list"]

    def test_real_culture_channel_list_output_parses(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real ``culture channel list`` output (a header, indented ``#channels``,
        and stderr WARNING noise combined in) yields exactly the active channels — and
        the warning lines do not leak a bogus channel."""
        real = (
            "exit=0\n"
            "2026-06-12 23:51:39 culture WARNING culture.yaml missing for "
            "spark-shushu at /home/spark/git/shushu — run 'culture agents unregister "
            "shushu' to remove this stale manifest entry\n"
            "Active channels:\n"
            "  #general\n"
            "  #system\n"
        )

        monkeypatch.setattr(
            "colleague.resident.channels.run_steward",
            lambda cli, args, *, root: real,  # noqa: ANN001
        )
        sel = select_channels(tmp_path)
        assert "#general" in sel.chosen
        assert "#system" in sel.chosen
        assert sel.chosen == [sel.owned, "#general", "#system"]
        assert not sel.degraded


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_default_rank_puts_nick_match_first(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default ranker puts the channel that contains the nick first (before unrelated ones)."""
        # Use nick "spark"; #spark-dev contains the nick, #general does not.
        # #spark (the exact owned channel) is excluded from the "ranked" comparison
        # since it's always prepended as owned — we check the relative order of
        # the remaining candidates.
        (tmp_path / "culture.yaml").write_text("nick: spark\n")
        body = "#general\n#eng\n#spark-dev\n#zz-last\n"
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok(body))
        sel = select_channels(tmp_path)
        # #spark-dev contains "spark" so it should rank before #general and #eng
        ranked = [c for c in sel.chosen if c != sel.owned]
        spark_dev_idx = ranked.index("#spark-dev") if "#spark-dev" in ranked else len(ranked)
        general_idx = ranked.index("#general") if "#general" in ranked else len(ranked)
        assert spark_dev_idx < general_idx

    def test_custom_rank_callable_used(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A custom rank callable controls ordering."""
        body = "#alpha\n#beta\n#gamma\n"
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok(body))

        def _reverse(candidates: list[str]) -> list[str]:
            return list(reversed(candidates))

        sel = select_channels(tmp_path, rank=_reverse)
        # The custom rank runs on the candidate list; #gamma before #alpha
        ranked = [c for c in sel.chosen if c != sel.owned]
        assert ranked.index("#gamma") < ranked.index("#alpha")


# ---------------------------------------------------------------------------
# Confirm gate
# ---------------------------------------------------------------------------


class TestConfirmGate:
    def test_default_confirm_accepts_all_candidates(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a confirm callback all ranked candidates are accepted."""
        body = "#alpha\n#beta\n"
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok(body))
        sel = select_channels(tmp_path)
        assert "#alpha" in sel.chosen
        assert "#beta" in sel.chosen

    def test_confirm_callback_drops_channels(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A confirm callback that drops a channel removes it from chosen."""
        body = "#keep\n#drop\n"
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok(body))

        def _only_keep(candidates: list[str]) -> list[str]:
            return [c for c in candidates if c == "#keep"]

        sel = select_channels(tmp_path, confirm=_only_keep)
        assert "#keep" in sel.chosen
        assert "#drop" not in sel.chosen

    def test_owned_always_present_even_if_confirm_drops_it(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The owned channel is always in chosen, even if confirm rejects everything."""
        (tmp_path / "culture.yaml").write_text("nick: mybot\n")
        body = "#alpha\n#mybot\n"
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok(body))

        sel = select_channels(tmp_path, confirm=lambda _: [])
        assert sel.owned == "#mybot"
        assert sel.owned in sel.chosen


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegrade:
    def test_steward_error_degrades_cleanly(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When run_steward raises StewardError, select_channels returns a degraded selection."""
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_err())
        sel = select_channels(tmp_path)
        assert sel.degraded is True
        assert sel.note  # non-empty note

    def test_steward_error_no_exception_escapes(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """StewardError must NOT propagate out of select_channels."""
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_err())
        # Should not raise
        sel = select_channels(tmp_path)
        assert sel is not None

    def test_degraded_selection_contains_only_owned(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A degraded selection's chosen contains exactly the owned channel."""
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_err())
        sel = select_channels(tmp_path)
        assert sel.chosen == [sel.owned]

    def test_degraded_uses_nick_when_available(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even when degraded, the owned channel uses the resolved nick."""
        (tmp_path / "culture.yaml").write_text("nick: fenix\n")
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_err())
        sel = select_channels(tmp_path)
        assert sel.owned == "#fenix"
        assert sel.degraded is True


# ---------------------------------------------------------------------------
# Integration: all pieces together
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_flow_with_nick_candidates_confirm(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full flow: nick resolved, candidates parsed, confirm applied, owned present."""
        (tmp_path / "culture.yaml").write_text("nick: pixel\n")
        body = "#pixel\n#general\n#dev\n#ops\n"
        monkeypatch.setattr("colleague.resident.channels.run_steward", _make_steward_ok(body))

        # confirm drops #ops
        def _no_ops(candidates: list[str]) -> list[str]:
            return [c for c in candidates if c != "#ops"]

        sel = select_channels(tmp_path, confirm=_no_ops)
        assert sel.owned == "#pixel"
        assert "#pixel" in sel.chosen
        assert "#ops" not in sel.chosen
        assert "#general" in sel.chosen
        assert not sel.degraded


class TestNonZeroRosterExit:
    def test_non_zero_exit_degrades_instead_of_parsing_error_output(
        self, monkeypatch, tmp_path
    ) -> None:
        """A non-zero roster exit degrades to owned-only — error output is NOT parsed
        for channels (qodo correctness flag)."""
        monkeypatch.setattr(
            "colleague.resident.channels.run_steward",
            lambda cli, args, *, root: "exit=1\nerror: #should-not-be-joined unreachable\n",
        )
        sel = select_channels(tmp_path)
        assert sel.degraded is True
        assert sel.chosen == [sel.owned]
        assert "#should-not-be-joined" not in sel.chosen

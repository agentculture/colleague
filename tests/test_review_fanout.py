"""Tests for the advisory review fan-out (#220b).

Covers the deterministic recommendation builder
(:func:`colleague.autosplit.build_review_fanout_recommendation`), the runtime
trigger (:func:`colleague.loop._maybe_offer_review_fanout` /
:func:`colleague.loop._distinct_folders_read`), and the dormant-by-default config
wiring (``EngineConfig.review_fanout_folders``).
"""

from __future__ import annotations

from types import SimpleNamespace

from colleague.autosplit import build_review_fanout_recommendation
from colleague.config import EngineConfig
from colleague.contract import Step
from colleague.loop import _distinct_folders_read, _maybe_offer_review_fanout

# ── builder ─────────────────────────────────────────────────────────────


class TestBuilder:
    def test_names_subagents_reviewer_and_numbers(self):
        msg = build_review_fanout_recommendation(folders=5, max_children=3)
        assert "subagents" in msg
        assert "reviewer" in msg
        assert "5" in msg  # folders
        assert "3" in msg  # max_children

    def test_per_folder_and_advisory(self):
        msg = build_review_fanout_recommendation(folders=4, max_children=3)
        assert "per-folder" in msg or "folder" in msg
        assert "optional" in msg or "advisory" in msg.lower()

    def test_states_honest_no_speedup_limit(self):
        # h13: on a single serializing backend, fan-out does NOT reduce wall-clock.
        msg = build_review_fanout_recommendation(folders=6, max_children=3)
        assert "serializing" in msg
        assert "wall-clock" in msg or "wall clock" in msg

    def test_deterministic(self):
        a = build_review_fanout_recommendation(folders=3, max_children=3)
        b = build_review_fanout_recommendation(folders=3, max_children=3)
        assert a == b and a  # identical and non-empty


# ── _distinct_folders_read ──────────────────────────────────────────────


def _read(path: str) -> Step:
    return Step(0, "read_file", {"path": path}, "", True)


class TestDistinctFoldersRead:
    def test_counts_distinct_parent_folders(self):
        ctx = SimpleNamespace(
            result=SimpleNamespace(
                steps=[
                    _read("a/x.py"),
                    _read("a/y.py"),  # same folder a/
                    _read("b/z.py"),
                    _read("c/d/w.py"),
                    _read("root.py"),  # repo-root bucket ""
                ]
            )
        )
        assert _distinct_folders_read(ctx) == 4  # a, b, c/d, ""

    def test_ignores_non_read_file_and_pathless_steps(self):
        ctx = SimpleNamespace(
            result=SimpleNamespace(
                steps=[
                    _read("a/x.py"),
                    Step(1, "list_dir", {"path": "b"}, "", True),  # not read_file
                    Step(2, "run_command", {"command": "ls"}, "", True),
                    Step(3, "read_file", {}, "", True),  # no path
                ]
            )
        )
        assert _distinct_folders_read(ctx) == 1  # only a/


# ── _maybe_offer_review_fanout ──────────────────────────────────────────


def _ctx(steps, threshold, offered=None):
    return SimpleNamespace(
        result=SimpleNamespace(steps=steps),
        messages=[],
        review_fanout_folders=threshold,
        _review_fanout_offered=[] if offered is None else offered,
    )


class TestMaybeOfferReviewFanout:
    def test_dormant_when_threshold_none(self):
        ctx = _ctx([_read("a/x.py"), _read("b/y.py"), _read("c/z.py")], threshold=None)
        _maybe_offer_review_fanout(ctx)
        assert ctx.messages == []  # byte-identical: nothing injected

    def test_dormant_when_threshold_zero(self):
        ctx = _ctx([_read("a/x.py"), _read("b/y.py"), _read("c/z.py")], threshold=0)
        _maybe_offer_review_fanout(ctx)
        assert ctx.messages == []

    def test_no_offer_below_threshold(self):
        # 2 folders, threshold 2 → not strictly greater → no offer.
        ctx = _ctx([_read("a/x.py"), _read("b/y.py")], threshold=2)
        _maybe_offer_review_fanout(ctx)
        assert ctx.messages == []

    def test_offers_once_above_threshold(self):
        ctx = _ctx([_read("a/x.py"), _read("b/y.py"), _read("c/z.py")], threshold=2)
        _maybe_offer_review_fanout(ctx)
        assert len(ctx.messages) == 1
        assert ctx.messages[0]["role"] == "user"
        assert "subagents" in ctx.messages[0]["content"]
        assert "reviewer" in ctx.messages[0]["content"]
        assert ctx._review_fanout_offered == [True]

        # A second call must NOT inject again (at most once per work item).
        _maybe_offer_review_fanout(ctx)
        assert len(ctx.messages) == 1


# ── config wiring (dormant by default) ──────────────────────────────────


class TestConfigWiring:
    def test_default_is_none_dormant(self, monkeypatch):
        monkeypatch.delenv("COLLEAGUE_REVIEW_FANOUT_FOLDERS", raising=False)
        monkeypatch.delenv("CONVERTIBLE_REVIEW_FANOUT_FOLDERS", raising=False)
        cfg = EngineConfig.resolve()
        assert cfg.review_fanout_folders is None

    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("COLLEAGUE_REVIEW_FANOUT_FOLDERS", "3")
        cfg = EngineConfig.resolve()
        assert cfg.review_fanout_folders == 3

    def test_to_dict_includes_field(self, monkeypatch):
        monkeypatch.delenv("COLLEAGUE_REVIEW_FANOUT_FOLDERS", raising=False)
        cfg = EngineConfig.resolve()
        assert "review_fanout_folders" in cfg.to_dict()

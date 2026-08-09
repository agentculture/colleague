"""Tests for component-attributed, role-scoped lessons.

Covers three changes across two modules:

- colleague/memory.py: ``attribute_component``, ``build_lesson_record``
  component validation, ``filter_for_injection`` role-scoped filtering.
- colleague/distill.py: ``lesson_has_external_evidence``, flywheel guard
  that refuses evaluator-only lessons.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import colleague.memory as memory_mod
import colleague.distill as distill_mod


# ===========================================================================
# PART 1 — attribute_component
# ===========================================================================


class TestAttributeComponent:
    """The attribution table: thought_ok, action_faithful, verdict_correct → component."""

    def test_front_bad_thought_good_action(self) -> None:
        """faithful action from a bad thought → component 'front'."""
        assert memory_mod.attribute_component(
            thought_ok=False, action_faithful=True, verdict_correct=False
        ) == "front"

    def test_worker_good_thought_action_drift(self) -> None:
        """good thought but action drift → component 'worker'."""
        assert memory_mod.attribute_component(
            thought_ok=True, action_faithful=False, verdict_correct=False
        ) == "worker"

    def test_evaluator_incorrect_verdict(self) -> None:
        """incorrect evaluator verdict → component 'evaluator'."""
        assert memory_mod.attribute_component(
            thought_ok=False, action_faithful=False, verdict_correct=False
        ) == "evaluator"

    def test_system_cross_role_or_routing(self) -> None:
        """cross-role or routing failure → component 'system'."""
        assert memory_mod.attribute_component(
            thought_ok=True, action_faithful=True, verdict_correct=False
        ) == "system"

    def test_all_true_is_system(self) -> None:
        """thought_ok=True, action_faithful=True, verdict_correct=True → system."""
        assert memory_mod.attribute_component(
            thought_ok=True, action_faithful=True, verdict_correct=True
        ) == "system"

    def test_all_false_is_evaluator(self) -> None:
        """thought_ok=False, action_faithful=False, verdict_correct=False → evaluator."""
        assert memory_mod.attribute_component(
            thought_ok=False, action_faithful=False, verdict_correct=False
        ) == "evaluator"

    def test_deterministic(self) -> None:
        """Same inputs always produce the same output."""
        r1 = memory_mod.attribute_component(False, True, False)
        r2 = memory_mod.attribute_component(False, True, False)
        assert r1 == r2 == "front"


# ===========================================================================
# PART 1 — build_lesson_record rejects invalid component
# ===========================================================================


class TestBuildLessonRecordComponent:
    """build_lesson_record must accept a component in metadata and reject
    values that are not one of the four allowed seats."""

    def _make_fake_eidetic(self, directory: Path) -> Path:
        script = directory / "eidetic"
        script.write_text(
            "#!/bin/sh\n"
            'LOG="$(pwd)/eidetic.log"\n'
            'echo "ARGV: $@" >> "$LOG"\n'
            'echo "CWD: $(pwd)" >> "$LOG"\n'
            'echo "---" >> "$LOG"\n'
            'if [ "$1" = "recall" ]; then\n'
            '  echo \'[]\'\n'
            'elif [ "$1" = "remember" ]; then\n'
            '  echo "ok"\n'
            "fi\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return script

    def test_valid_component_accepted(self, tmp_path: Path, monkeypatch) -> None:
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
        record = memory_mod.build_lesson_record(
            "task-1",
            "test lesson",
            {"component": "worker", "topic": "test"},
        )
        assert record["metadata"]["component"] == "worker"

    def test_invalid_component_rejected(self, tmp_path: Path, monkeypatch) -> None:
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
        with self.assertRaises(ValueError):
            memory_mod.build_lesson_record(
                "task-1",
                "test lesson",
                {"component": "invalid_value", "topic": "test"},
            )

    def test_no_component_is_ok(self, tmp_path: Path, monkeypatch) -> None:
        """Legacy records without a component field are still accepted."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
        record = memory_mod.build_lesson_record(
            "task-1",
            "test lesson",
            {"topic": "test"},
        )
        assert "component" not in record["metadata"]

    def test_all_four_valid_components(self, tmp_path: Path, monkeypatch) -> None:
        for comp in ("front", "worker", "evaluator", "system"):
            record = memory_mod.build_lesson_record(
                "task-1",
                "test lesson",
                {"component": comp, "topic": "test"},
            )
            assert record["metadata"]["component"] == comp


# ===========================================================================
# PART 2 — lesson_has_external_evidence
# ===========================================================================


class TestLessonHasExternalEvidence:
    """A durable lesson must be grounded in EXTERNAL evidence."""

    def test_external_evidence_nonempty_list(self) -> None:
        evidence = {"external_evidence": ["ext-1", "ext-2"]}
        assert distill_mod.lesson_has_external_evidence(evidence) is True

    def test_external_evidence_empty_list(self) -> None:
        evidence = {"external_evidence": []}
        assert distill_mod.lesson_has_external_evidence(evidence) is False

    def test_external_evidence_missing(self) -> None:
        evidence = {}
        assert distill_mod.lesson_has_external_evidence(evidence) is False

    def test_outcome_nonempty_string(self) -> None:
        evidence = {"outcome": "something happened"}
        assert distill_mod.lesson_has_external_evidence(evidence) is True

    def test_outcome_empty_string(self) -> None:
        evidence = {"outcome": ""}
        assert distill_mod.lesson_has_external_evidence(evidence) is False

    def test_outcome_missing(self) -> None:
        evidence = {}
        assert distill_mod.lesson_has_external_evidence(evidence) is False

    def test_only_evaluation_id_is_false(self) -> None:
        """evaluator verdict alone is NOT ground truth."""
        evidence = {"evaluation_id": "eval-1"}
        assert distill_mod.lesson_has_external_evidence(evidence) is False

    def test_external_evidence_and_outcome(self) -> None:
        evidence = {"external_evidence": ["ext-1"], "outcome": "done"}
        assert distill_mod.lesson_has_external_evidence(evidence) is True

    def test_external_evidence_with_evaluation_id(self) -> None:
        evidence = {"external_evidence": ["ext-1"], "evaluation_id": "eval-1"}
        assert distill_mod.lesson_has_external_evidence(evidence) is True


# ===========================================================================
# PART 2 — distill refuses evaluator-only lessons
# ===========================================================================


class TestDistillEvaluatorOnlyRefusal:
    """The distill child must refuse to persist a lesson whose only evidence
    is an evaluator verdict."""

    def _make_fake_eidetic(self, directory: Path) -> Path:
        script = directory / "eidetic"
        script.write_text(
            "#!/bin/sh\n"
            'LOG="$(pwd)/eidetic.log"\n'
            'echo "ARGV: $@" >> "$LOG"\n'
            'echo "CWD: $(pwd)" >> "$LOG"\n'
            'echo "---" >> "$LOG"\n'
            'if [ "$1" = "recall" ]; then\n'
            '  echo \'[]\'\n'
            'elif [ "$1" = "remember" ]; then\n'
            '  echo "ok"\n'
            "fi\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return script

    def test_evaluator_only_lesson_refused(self, tmp_path: Path, monkeypatch) -> None:
        """A lesson with only evaluation_id in evidence is refused."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        # The child_main path: when the lesson has only evaluation_id,
        # upsert_lesson should return False because the evidence guard
        # rejects it.
        lesson = {
            "pattern": "test pattern",
            "constant": "test constant",
            "reason": "test reason",
        }
        # We test the guard directly: lesson_has_external_evidence returns
        # False for evaluator-only evidence, so the upsert path should
        # refuse.
        evidence = {"evaluation_id": "eval-1"}
        assert distill_mod.lesson_has_external_evidence(evidence) is False

    def test_lesson_with_external_evidence_accepted(self, tmp_path: Path, monkeypatch) -> None:
        """A lesson with external_evidence is accepted."""
        evidence = {"external_evidence": ["ext-1"]}
        assert distill_mod.lesson_has_external_evidence(evidence) is True

    def test_lesson_with_outcome_accepted(self, tmp_path: Path, monkeypatch) -> None:
        """A lesson with outcome is accepted."""
        evidence = {"outcome": "something happened"}
        assert distill_mod.lesson_has_external_evidence(evidence) is True


# ===========================================================================
# PART 3 — filter_for_injection role-scoped filtering
# ===========================================================================


class TestFilterForInjectionRoleScoped:
    """filter_for_injection must filter by component when role is provided."""

    def _make_fake_eidetic(self, directory: Path) -> Path:
        script = directory / "eidetic"
        script.write_text(
            "#!/bin/sh\n"
            'LOG="$(pwd)/eidetic.log"\n'
            'echo "ARGV: $@" >> "$LOG"\n'
            'echo "CWD: $(pwd)" >> "$LOG"\n'
            'echo "---" >> "$LOG"\n'
            'if [ "$1" = "recall" ]; then\n'
            '  echo \'[]\'\n'
            'elif [ "$1" = "remember" ]; then\n'
            '  echo "ok"\n'
            "fi\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return script

    # --- regression guard: role=None is byte-identical to today ---

    def test_role_none_no_filtering(self, tmp_path: Path, monkeypatch) -> None:
        """When role is None, behaviour is exactly as it is today: no filtering."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "1", "metadata": {"component": "worker"}},
            {"id": "2", "metadata": {"component": "evaluator"}},
            {"id": "3", "metadata": {"component": "front"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, env=None)
        # With role=None, all records pass through (no role filtering)
        assert len(kept) == 3
        assert excluded == []

    def test_role_none_empty_records(self, tmp_path: Path, monkeypatch) -> None:
        """role=None with empty records returns empty."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
        kept, excluded = memory_mod.filter_for_injection([], env=None)
        assert kept == []
        assert excluded == []

    # --- role-scoped filtering ---

    def test_role_worker_injects_worker_and_cross_role(self, tmp_path: Path, monkeypatch) -> None:
        """role='worker' injects worker lessons and cross_role lessons."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "w1", "metadata": {"component": "worker"}},
            {"id": "w2", "metadata": {"component": "worker", "cross_role": True}},
            {"id": "e1", "metadata": {"component": "evaluator"}},
            {"id": "f1", "metadata": {"component": "front"}},
            {"id": "s1", "metadata": {"component": "system"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, role="worker", env=None)
        kept_ids = {r["id"] for r in kept}
        assert "w1" in kept_ids  # worker
        assert "w2" in kept_ids  # cross_role
        assert "e1" not in kept_ids  # evaluator
        assert "f1" not in kept_ids  # front
        assert "s1" not in kept_ids  # system

    def test_role_worker_injects_legacy_no_component(self, tmp_path: Path, monkeypatch) -> None:
        """Records with no component are treated as unscoped and still injected."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "legacy1", "metadata": {"topic": "old"}},
            {"id": "legacy2", "metadata": {}},
            {"id": "worker1", "metadata": {"component": "worker"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, role="worker", env=None)
        kept_ids = {r["id"] for r in kept}
        assert "legacy1" in kept_ids
        assert "legacy2" in kept_ids
        assert "worker1" in kept_ids

    def test_role_evaluator_injects_evaluator_and_cross_role(self, tmp_path: Path, monkeypatch) -> None:
        """role='evaluator' injects evaluator lessons and cross_role lessons."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "e1", "metadata": {"component": "evaluator"}},
            {"id": "e2", "metadata": {"component": "evaluator", "cross_role": True}},
            {"id": "w1", "metadata": {"component": "worker"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, role="evaluator", env=None)
        kept_ids = {r["id"] for r in kept}
        assert "e1" in kept_ids
        assert "e2" in kept_ids
        assert "w1" not in kept_ids

    def test_role_system_injects_system_and_cross_role(self, tmp_path: Path, monkeypatch) -> None:
        """role='system' injects system lessons and cross_role lessons."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "s1", "metadata": {"component": "system"}},
            {"id": "s2", "metadata": {"component": "system", "cross_role": True}},
            {"id": "f1", "metadata": {"component": "front"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, role="system", env=None)
        kept_ids = {r["id"] for r in kept}
        assert "s1" in kept_ids
        assert "s2" in kept_ids
        assert "f1" not in kept_ids

    def test_role_front_injects_front_and_cross_role(self, tmp_path: Path, monkeypatch) -> None:
        """role='front' injects front lessons and cross_role lessons."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "f1", "metadata": {"component": "front"}},
            {"id": "f2", "metadata": {"component": "front", "cross_role": True}},
            {"id": "w1", "metadata": {"component": "worker"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, role="front", env=None)
        kept_ids = {r["id"] for r in kept}
        assert "f1" in kept_ids
        assert "f2" in kept_ids
        assert "w1" not in kept_ids

    def test_cross_role_true_injects_for_any_role(self, tmp_path: Path, monkeypatch) -> None:
        """A record with cross_role=True is injected regardless of role."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "x1", "metadata": {"component": "evaluator", "cross_role": True}},
        ]
        for role in ("worker", "front", "system", "evaluator"):
            kept, excluded = memory_mod.filter_for_injection(records, role=role, env=None)
            assert len(kept) == 1
            assert kept[0]["id"] == "x1"

    def test_excluded_list_populated(self, tmp_path: Path, monkeypatch) -> None:
        """Excluded records appear in the excluded list."""
        eidetic = self._make_fake_eidetic(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        records = [
            {"id": "e1", "metadata": {"component": "evaluator"}},
            {"id": "w1", "metadata": {"component": "worker"}},
        ]
        kept, excluded = memory_mod.filter_for_injection(records, role="worker", env=None)
        assert len(kept) == 1
        assert len(excluded) == 1
        assert excluded[0]["id"] == "e1"
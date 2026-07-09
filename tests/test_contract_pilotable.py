"""Contract shapes for the pilotable-runs arc (plan t1).

Two additive contract pieces, both omit-when-None / byte-identical when unused:

* ``Task.flight_repo_path`` — the operator-repo path for the flight plane,
  distinct from ``repo_path`` (the work CWD). Set by ``_setup_isolation`` so an
  isolated run's flight plane lives in the operator repo, not the throwaway
  worktree (#310). Omit-when-None: a task without it serializes byte-identically
  to today.
* ``SensesDirectRecord`` — the lightweight standalone record for a senses-direct
  front-door turn (#311): ``{route, text, answer, latency, tokens, degraded,
  at}`` in the ``SensesRecord`` shape family, with verbatim ``text`` and
  best-effort numeric coercion on read-back.
"""

from dataclasses import replace

from colleague.contract import SensesDirectRecord, Task


class TestTaskFlightRepoPath:
    def test_default_none_is_omitted_from_to_dict(self):
        """A task without flight_repo_path serializes byte-identically to today."""
        task = Task.new("/repo", "do a thing")
        assert task.flight_repo_path is None
        assert "flight_repo_path" not in task.to_dict()

    def test_set_value_round_trips(self):
        task = Task.new("/repo", "do a thing")
        task = replace(task, repo_path="/repo/iso-abc", flight_repo_path="/repo")
        data = task.to_dict()
        assert data["flight_repo_path"] == "/repo"
        assert data["repo_path"] == "/repo/iso-abc"
        restored = Task.from_dict(data)
        assert restored.flight_repo_path == "/repo"
        assert restored.repo_path == "/repo/iso-abc"

    def test_replace_is_the_isolation_pattern(self):
        """_setup_isolation does replace(task, repo_path=worktree,
        flight_repo_path=operator_repo) — both fields must survive replace."""
        task = Task.new("/operator/repo", "write a file")
        isolated = replace(
            task, repo_path="/operator/repo/iso-xyz", flight_repo_path="/operator/repo"
        )
        assert isolated.repo_path == "/operator/repo/iso-xyz"
        assert isolated.flight_repo_path == "/operator/repo"

    def test_from_dict_missing_key_is_none(self):
        """A legacy artifact (no flight_repo_path key) reads back as None."""
        data = {"id": "abc", "repo_path": "/repo", "instruction": "x"}
        assert Task.from_dict(data).flight_repo_path is None


class TestSensesDirectRecord:
    def test_to_dict_shape(self):
        rec = SensesDirectRecord(
            route="senses_direct",
            text="what are you?",
            answer="I'm colleague's front door.",
            latency=0.83,
            tokens=42,
            degraded=False,
            at=1720000000.0,
        )
        data = rec.to_dict()
        assert data == {
            "route": "senses_direct",
            "text": "what are you?",
            "answer": "I'm colleague's front door.",
            "latency": 0.83,
            "tokens": 42,
            "degraded": False,
            "at": 1720000000.0,
        }

    def test_round_trip_preserves_verbatim_text(self):
        rec = SensesDirectRecord(
            route="senses_direct",
            text="  weird\tverbatim  text  ",
            answer="hi",
            latency=1.0,
            tokens=1,
            degraded=False,
            at=1.0,
        )
        restored = SensesDirectRecord.from_dict(rec.to_dict())
        # text is verbatim — never normalized/derived.
        assert restored.text == "  weird\tverbatim  text  "
        assert restored == rec

    def test_from_dict_best_effort_numeric_coercion(self):
        """latency/tokens/at that cannot parse fall back to None, mirroring
        SensesRecord.from_dict — a bad value never aborts artifact read-back."""
        rec = SensesDirectRecord.from_dict(
            {
                "route": "senses_direct",
                "text": "hi",
                "answer": "hello",
                "latency": "not-a-float",
                "tokens": "not-an-int",
                "degraded": True,
                "at": "not-a-time",
            }
        )
        assert rec.latency is None
        assert rec.tokens is None
        assert rec.at is None
        assert rec.degraded is True
        assert rec.text == "hi"

    def test_defaults(self):
        rec = SensesDirectRecord(route="senses_direct", text="hi", answer="yo")
        assert rec.latency is None
        assert rec.tokens is None
        assert rec.degraded is False
        assert rec.at is None

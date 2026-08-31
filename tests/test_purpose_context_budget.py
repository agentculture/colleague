"""The per-purpose child context-budget lever (#458 re-scoped, row 64b).

``COLLEAGUE_<PURPOSE>_CONTEXT_BUDGET`` caps that ONE purpose child's window
through ``ChildSpec.context_budget_tokens``; unset/invalid = the child
inherits the parent's budget, byte-identical to today.
"""

from __future__ import annotations

import pytest

from colleague import efforttables


def test_purpose_context_override_unset_is_none(monkeypatch):
    monkeypatch.delenv("COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET", raising=False)
    assert efforttables.purpose_context_override("code_survey") is None


@pytest.mark.parametrize("raw", ["", "  ", "abc", "0", "-5", "1.5"])
def test_purpose_context_override_ignores_invalid_values(monkeypatch, raw):
    monkeypatch.setenv("COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET", raw)
    assert efforttables.purpose_context_override("code_survey") is None


def test_value_reaches_the_child_config(monkeypatch, tmp_path):
    from colleague.config import EngineConfig
    from colleague.efforttables import PURPOSE_STEPS
    from colleague.subagents import make_spawn

    captured: list = []

    class _Eng:
        def work(self, task, config):
            from colleague.contract import OK, TaskResult

            captured.append(config)
            return TaskResult(task_id="c", status=OK, summary="done")

    monkeypatch.setenv("COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET", "65536")
    monkeypatch.setattr("colleague.registry.load", lambda name: _Eng())
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "README.md").write_text("x\n")
    import subprocess

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
        check=True,
    )
    parent = EngineConfig.resolve(repo_path=repo)
    spawn = make_spawn(str(repo), parent, "mock")
    spawn(
        "survey", role="scout", max_steps=PURPOSE_STEPS["code_survey"], context_budget_tokens=65536
    )
    assert captured, "the child engine must have run"
    assert captured[0].context_budget_tokens == 65536
    assert captured[0].max_steps == PURPOSE_STEPS["code_survey"]

    # unset -> the child inherits the parent's budget (byte-identical)
    captured.clear()
    spawn("survey", role="scout")
    assert captured[0].context_budget_tokens == parent.context_budget_tokens


def test_dispatch_passes_the_override(monkeypatch, tmp_path):
    import tests.test_purpose_executor as tpe
    from colleague import purpose_schemas

    monkeypatch.setenv("COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET", "65536")
    rec = tpe._Recorder()
    handlers = purpose_schemas.dispatch(tpe._executor(tmp_path, rec))
    handlers["code_survey"](dict(tpe._ARGS["code_survey"]))
    assert rec.calls, "the spawn must have been called"
    assert rec.calls[0]["context_budget_tokens"] == 65536

    monkeypatch.delenv("COLLEAGUE_CODE_SURVEY_CONTEXT_BUDGET", raising=False)
    handlers["code_survey"](dict(tpe._ARGS["code_survey"]))
    assert rec.calls[1]["context_budget_tokens"] is None

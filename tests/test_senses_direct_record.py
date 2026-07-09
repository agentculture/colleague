"""#311 — a senses-direct turn leaves a standalone auditable record.

A senses-direct front-door turn (the front door answering a non-repo turn itself)
produces NO Task/TaskResult, so the dispatched path's ``TaskResult.senses.records``
audit trail had no counterpart for it. This writes a lightweight
``.colleague/senses-direct/<id>.json`` :class:`SensesDirectRecord` for every
senses-direct route (answered AND degraded/misroute), with the operator's verbatim
text — a strict no-op on the unarmed / cortex / no-record_repo paths.
"""

import json

from colleague.config import EngineConfig
from colleague.contract import SensesDirectRecord
from colleague.frontdoor import run_frontdoor
from colleague.loop import ModelResponse

_ANSWER_JSON = json.dumps({"answer": "I am senses, the front lobe."})


def _senses_config(**overrides) -> EngineConfig:
    defaults = dict(model="senses-model", context_budget_tokens=100000)
    defaults.update(overrides)
    return EngineConfig(**defaults)


class _FakeMakeComplete:
    def __init__(self, raise_on_complete=None) -> None:
        self._raise = raise_on_complete

    def __call__(self, config, tools=None):
        def complete(messages):
            if self._raise is not None:
                raise self._raise
            return ModelResponse(content=_ANSWER_JSON, prompt_tokens=5, completion_tokens=7)

        return complete


def _char_counter(messages):
    return sum(len(m.get("content") or "") for m in messages)


def _records(repo):
    d = repo / ".colleague" / "senses-direct"
    if not d.exists():
        return []
    return [SensesDirectRecord.from_dict(json.loads(p.read_text())) for p in d.glob("*.json")]


# ── answered + degraded senses-direct turns both write a record ────────────


def test_senses_direct_answered_writes_one_record(tmp_path):
    run_frontdoor(
        "hello there",
        senses_config=_senses_config(),
        make_complete=_FakeMakeComplete(),
        make_count_tokens=_char_counter,
        record_repo=str(tmp_path),
    )
    recs = _records(tmp_path)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.route == "senses_direct"
    assert rec.text == "hello there"  # verbatim operator text
    assert "front lobe" in rec.answer
    assert rec.degraded is False
    assert rec.at is not None


def test_degraded_senses_direct_also_writes_a_record(tmp_path):
    """A degraded senses-direct (senses could not answer -> fell back to cortex) is
    still recorded — that is the misroute signal an audit wants."""
    run_frontdoor(
        "hello there",
        senses_config=_senses_config(),
        make_complete=_FakeMakeComplete(raise_on_complete=RuntimeError("boom")),
        make_count_tokens=_char_counter,
        record_repo=str(tmp_path),
    )
    recs = _records(tmp_path)
    assert len(recs) == 1
    assert recs[0].degraded is True
    assert recs[0].text == "hello there"


def test_record_text_is_verbatim(tmp_path):
    weird = "  hello,\tthere!  "
    run_frontdoor(
        weird,
        senses_config=_senses_config(),
        make_complete=_FakeMakeComplete(),
        make_count_tokens=_char_counter,
        record_repo=str(tmp_path),
    )
    (rec,) = _records(tmp_path)
    # verbatim — never normalized or derived from model output
    assert rec.text == weird


# ── strict no-op paths ─────────────────────────────────────────────────────


def test_no_record_repo_writes_nothing(tmp_path):
    """Backward-compat: without record_repo the front door writes no file."""
    run_frontdoor(
        "hello there",
        senses_config=_senses_config(),
        make_complete=_FakeMakeComplete(),
        make_count_tokens=_char_counter,
    )
    assert _records(tmp_path) == []


def test_cortex_route_writes_no_record(tmp_path):
    """Routing unchanged: a repo-touching (cortex) turn writes no senses-direct
    file — its record rides TaskResult.senses.records, not this file."""
    out = run_frontdoor(
        "fix the bug in loop.py",
        senses_config=_senses_config(),
        make_complete=_FakeMakeComplete(),
        make_count_tokens=_char_counter,
        record_repo=str(tmp_path),
    )
    assert out.route == "cortex"
    assert out.record is not None and out.record.point.endswith(":cortex")
    assert _records(tmp_path) == []


def test_unarmed_writes_no_record(tmp_path):
    """Unarmed (senses_config=None) never consults senses and writes no file."""
    run_frontdoor(
        "hello there",
        senses_config=None,
        make_complete=_FakeMakeComplete(),
        make_count_tokens=_char_counter,
        record_repo=str(tmp_path),
    )
    assert _records(tmp_path) == []
